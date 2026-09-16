import base64
import unittest
from unittest.mock import Mock, patch

from bot.providers import ProviderError
from bot.speech import OpenRouterTranscriber


class OpenRouterSpeechTests(unittest.TestCase):
    def setUp(self):
        self.telegram = Mock()
        self.telegram.download_file.return_value = b'OggS voice bytes'
        self.transcriber = OpenRouterTranscriber('secret', self.telegram)

    @patch('bot.speech.request_json')
    def test_telegram_voice_becomes_russian_transcription(self, request):
        request.return_value = {'text': '  Найди Мемуары гейши  ', 'usage': {'seconds': 3}}
        text = self.transcriber({'file_id': 'voice', 'duration': 3, 'file_size': 16})
        self.assertEqual(text, 'Найди Мемуары гейши')
        url, payload, headers = request.call_args.args
        self.assertEqual(url, 'https://openrouter.ai/api/v1/audio/transcriptions')
        self.assertEqual(payload['model'], 'openai/whisper-large-v3-turbo')
        self.assertEqual(payload['language'], 'ru')
        self.assertEqual(payload['input_audio']['format'], 'ogg')
        self.assertEqual(base64.b64decode(payload['input_audio']['data']), b'OggS voice bytes')
        self.assertEqual(headers['Authorization'], 'Bearer secret')

    @patch('bot.speech.request_json')
    def test_oversize_voice_rejected_before_download_or_api(self, request):
        for voice in ({'file_id': 'x', 'file_size': 20 * 1024 * 1024 + 1},
                      {'file_id': 'x', 'duration': 601}):
            with self.assertRaisesRegex(ProviderError, '^voice_too_long$'):
                self.transcriber(voice)
        self.telegram.download_file.assert_not_called()
        request.assert_not_called()

    @patch('bot.speech.request_json')
    def test_actual_download_size_is_bounded_even_if_metadata_wrong(self, request):
        self.telegram.download_file.return_value = b'x' * (20 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ProviderError, '^voice_too_long$'):
            self.transcriber({'file_id': 'x'})
        request.assert_not_called()

    @patch('bot.speech.request_json')
    def test_invalid_provider_output_never_becomes_dialogue(self, request):
        for response in ({}, {'text': None}, {'text': ''}, {'text': '  '}, [], {'text': 4}):
            request.return_value = response
            with self.assertRaisesRegex(ProviderError, '^transcription_failed$'):
                self.transcriber({'file_id': 'x'})

    @patch('bot.speech.request_json')
    def test_request_error_does_not_expose_credentials(self, request):
        request.side_effect = RuntimeError('secret Bearer private')
        with self.assertRaisesRegex(ProviderError, '^transcription_failed$'):
            self.transcriber({'file_id': 'x'})

    @patch('bot.speech.request_json')
    def test_explicit_model_override_is_used(self, request):
        request.return_value = {'text': 'Тест'}
        OpenRouterTranscriber('key', self.telegram, model='openai/whisper-large-v3')({'file_id': 'x'})
        self.assertEqual(request.call_args.args[1]['model'], 'openai/whisper-large-v3')
