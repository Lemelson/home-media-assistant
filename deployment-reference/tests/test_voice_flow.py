import tempfile
import unittest
from unittest.mock import Mock, patch

from bot.__main__ import acknowledge_message
from bot.dialog import Dialog
from bot.providers import DeepSeek
from bot.search import SearchFlow
from bot.speech import OpenRouterTranscriber
from test_multifilm import Telegram


class VoiceFlowTests(unittest.TestCase):
    def voice(self):
        return {'update_id': 44, 'message': {'message_id': 44,
            'from': {'id': 10, 'username': 'owner'},
            'chat': {'id': 10, 'type': 'private'},
            'voice': {'file_id': 'voice', 'duration': 7}}}

    def test_receipt_transcription_resolution_and_result_use_one_message(self):
        transcript = 'Скачай второй сезон Чёрного зеркала'
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            tg.download_file = Mock(return_value=b'OggS test audio')
            flow = SearchFlow(DeepSeek('test-key'), None)
            d = Dialog(tmp, tg, 'owner', '', lambda: {}, search=flow,
                       transcribe=OpenRouterTranscriber('test-key', tg))
            d.remember(10, 'assistant', 'Вечное сияние чистого разума — загружается')
            row = self.voice()
            receipt = acknowledge_message(d, row)
            self.assertIsInstance(receipt, int)
            row['message']['_receipt_message_id'] = receipt
            def stt(url, payload, headers, **kwargs):
                self.assertIn('Расшифровываю', tg.calls[-1][1]['text'])
                self.assertEqual(payload['model'], 'openai/whisper-large-v3-turbo')
                return {'text': transcript}
            def llm(url, payload, headers, **kwargs):
                self.assertEqual(payload['messages'][-1]['content'], transcript)
                self.assertNotIn('Вечное сияние', str(payload['messages']))
                self.assertIn('Разбираю запрос', tg.calls[-1][1]['text'])
                return {'choices': [{'message': {'content': '{"action":"find","candidates":[{"title":"Чёрное зеркало","kind":"show","season":2}]}'}}]}
            with patch('bot.speech.request_json', side_effect=stt), patch('bot.providers.request_json', side_effect=llm):
                d.handle(row)
            messages = [(m,p) for m,p in tg.calls if m in ('sendMessage','editMessageText')]
            self.assertEqual(sum(m == 'sendMessage' for m,p in messages), 1)
            self.assertTrue(all(p['message_id'] == receipt for m,p in messages if m == 'editMessageText'))
            self.assertIn('<b><i>', messages[0][1]['text'])
            self.assertIn(transcript, messages[-1][1]['text'])
            self.assertIn('сезон 2', messages[-1][1]['text'])
            self.assertEqual(d.jobs.pending(), [])

    def test_transcription_failure_finishes_receipt_and_never_calls_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); resolver = Mock()
            d = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(resolver, None),
                       transcribe=Mock(side_effect=RuntimeError('private')))
            row = self.voice(); receipt = acknowledge_message(d, row)
            row['message']['_receipt_message_id'] = receipt
            d.handle(row)
            resolver.identify.assert_not_called()
            self.assertEqual(sum(m == 'sendMessage' for m,p in tg.calls), 1)
            self.assertEqual(tg.calls[-1][0], 'editMessageText')
            self.assertEqual(tg.calls[-1][1]['message_id'], receipt)
            self.assertIn('Не удалось', tg.calls[-1][1]['text'])
            self.assertNotIn('private', str(tg.calls))

    def test_complete_long_transcript_reaches_deepseek(self):
        transcript = 'Уточняю запрос. ' * 310 + 'Скачай второй сезон Чёрного зеркала'
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            d = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(DeepSeek('key'), None),
                       transcribe=lambda voice: transcript)
            response = {'choices': [{'message': {'content': '{"action":"reply","reply":"Уточни","candidates":[]}'}}]}
            with patch('bot.providers.request_json', return_value=response) as request:
                d.handle(self.voice())
            self.assertEqual(request.call_args.args[1]['messages'][-1]['content'], transcript)

    def test_forwarded_voice_is_acknowledged_but_unauthorized_voice_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); d = Dialog(tmp, tg, 'owner', '', lambda: {})
            row = self.voice(); row['message']['forward_origin'] = {'type': 'hidden_user'}
            self.assertIsInstance(acknowledge_message(d, row), int)
            row['message']['from'] = {'id': 99, 'username': 'stranger'}
            self.assertIsNone(acknowledge_message(d, row))
            self.assertEqual(len(tg.calls), 1)

    def test_voice_result_with_poster_uses_existing_text_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); resolver = Mock()
            resolver.identify.return_value = {'action': 'find', 'candidates': [
                {'title': 'Чёрное зеркало', 'kind': 'show', 'season': 2,
                 'source_images': ['https://example.org/poster.jpg']}]}
            d = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(resolver, None),
                       transcribe=lambda v: 'Скачай второй сезон Чёрного зеркала')
            row = self.voice(); row['message']['_receipt_message_id'] = acknowledge_message(d, row)
            d.handle(row)
            self.assertFalse(any(m in ('sendPhoto','sendMediaGroup') for m,p in tg.calls))
            self.assertEqual(sum(m == 'sendMessage' for m,p in tg.calls), 1)
            self.assertIn('Распознано', tg.calls[-1][1]['text'])
            self.assertIn('inline_keyboard', tg.calls[-1][1]['reply_markup'])

    def test_download_request_cannot_become_unrelated_download_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); status = Mock(return_value={})
            d = Dialog(tmp, tg, 'owner', '', status, search=SearchFlow(DeepSeek('key'), None),
                       transcribe=lambda v: 'Скачай второй сезон Чёрного зеркала')
            response = {'choices': [{'message': {'content': '{"action":"downloads","candidates":[]}'}}]}
            row = self.voice(); row['message']['_receipt_message_id'] = acknowledge_message(d, row)
            with patch('bot.providers.request_json', return_value=response):
                d.handle(row)
            status.assert_not_called()
            self.assertEqual(sum(m == 'sendMessage' for m,p in tg.calls), 1)
            self.assertIn('не удалось', tg.calls[-1][1]['text'])

    def test_explicit_download_status_request_still_resolves(self):
        response = {'choices': [{'message': {'content': '{"action":"downloads","candidates":[]}'}}]}
        with patch('bot.providers.request_json', return_value=response):
            self.assertEqual(DeepSeek('key').identify('Покажи текущие загрузки', [])['action'], 'downloads')

    def test_voice_shortcut_does_not_leave_processing_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            d = Dialog(tmp, tg, 'owner', '', lambda: {'disk_ok': True, 'torrents': []},
                       search=Mock(), transcribe=lambda v: 'Загрузки')
            row = self.voice(); row['message']['_receipt_message_id'] = acknowledge_message(d, row)
            d.handle(row)
            edits = [p for m,p in tg.calls if m == 'editMessageText']
            self.assertIn('Распознано', edits[-1]['text'])
            self.assertNotIn('Разбираю', edits[-1]['text'])
