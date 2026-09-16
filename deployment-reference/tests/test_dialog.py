import tempfile
import unittest
from pathlib import Path

from bot.dialog import Dialog


class Telegram:
    def __init__(self):
        self.sent = []
    def call(self, method, **payload):
        self.sent.append((method, payload))
        return {}
    def download_file(self, file_id, max_bytes):
        return b'd4:infod4:name4:testee'


class DialogTests(unittest.TestCase):
    def test_repeated_space_checks_are_new_jobs_but_same_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dialog = Dialog(tmp, Telegram(), '', '', lambda: {})
            job = dialog.jobs.enqueue('add', 1, {'action': 'add', 'size_bytes': 999})
            denied = {'ok': False, 'error': 'insufficient_space', 'hash': 'b' * 40}
            dialog.jobs.finish(job, denied)
            dialog.callback(1, 1, 'retry:' + job, 'tg:20')
            first = dialog.jobs.pending()[0]['id']
            dialog.jobs.finish(first, denied)
            dialog.callback(1, 1, 'retry:' + job, 'tg:21')
            dialog.callback(1, 1, 'retry:' + job, 'tg:21')
            self.assertEqual(len(dialog.jobs.pending()), 1)
            self.assertNotEqual(dialog.jobs.pending()[0]['id'], first)

    def test_download_list_is_one_message_with_detail_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            rows = [{'hashString': h*40, 'name': name, 'status': 4, 'percentDone': .5,
                     'totalSize': 1000, 'leftUntilDone': 500} for h,name in [('a','One'),('b','Two')]]
            dialog = Dialog(tmp, tg, '', '', lambda: {'disk_ok': True, 'torrents': rows})
            dialog.downloads(1)
            messages = [p for m,p in tg.sent if m == 'sendMessage']
            self.assertEqual(len(messages), 1)
            self.assertIn('One', messages[0]['text'])
            self.assertIn('Two', messages[0]['text'])
            self.assertEqual(messages[0]['reply_markup']['inline_keyboard'][0][0]['callback_data'], 'download:'+'a'*40)

    def test_cancel_after_confirm_does_not_claim_queued_delete_was_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Telegram()
            dialog = Dialog(tmp, telegram, '', '', lambda: {})
            token = dialog.jobs.offer_delete(1, 'a' * 40)
            dialog.callback(1, 1, 'confirm:' + token, 'one')
            dialog.callback(1, 1, 'cancel-delete:' + token, 'two')
            self.assertNotIn('Удаление отменено', telegram.sent[-1][1]['text'])
            self.assertEqual(len(dialog.jobs.pending()), 1)

    def test_retry_paused_insufficient_space_rechecks_resume_instead_of_duplicate_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            dialog = Dialog(tmp, Telegram(), '', '', lambda: {})
            job = dialog.jobs.enqueue('add', 1, {'action': 'add', 'size_bytes': 999})
            dialog.jobs.finish(job, {'ok': False, 'error': 'insufficient_space', 'hash': 'b' * 40})
            dialog.callback(1, 1, 'retry:' + job, 'retry')
            self.assertEqual(dialog.jobs.pending()[0]['payload'], {'action': 'resume', 'hash': 'b' * 40})

    def test_plain_reply_keeps_persistent_menu_and_context_includes_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Telegram()
            seen = []
            dialog = Dialog(tmp, telegram, 'owner', '', lambda: {},
                            search=lambda uid, chat, text, d, source: seen.append(text))
            dialog.send(10, 'Обычный ответ')
            self.assertTrue(telegram.sent[-1][1]['reply_markup']['is_persistent'])
            dialog.handle({'update_id': 3, 'message': {'from': {'id': 10, 'username': 'owner'},
                'chat': {'id': 10, 'type': 'private'}, 'caption': 'Поищи этот фильм',
                'forward_origin': {'type': 'channel'}}})
            self.assertEqual(seen, ['Поищи этот фильм'])
            self.assertEqual(dialog.conversation(10)[-1]['content'], 'Поищи этот фильм')

    def test_library_delete_requires_fresh_named_button_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Telegram()
            inventory = {'ok': True, 'disk_ok': True, 'free_bytes': 99 * 1024**3,
                'items': [{'id': 'a' * 32, 'name': 'Film <One>', 'kind': 'movie', 'size_bytes': 2 * 1024**3}]}
            dialog = Dialog(tmp, telegram, 'owner', '', lambda: {}, media_library=lambda: inventory)
            dialog.resolve_intent(10, 10, {'action': 'delete', 'target': 'Film'}, source='test')
            self.assertEqual(dialog.jobs.pending(), [])
            confirmation = telegram.sent[-1][1]
            self.assertIn('Film &lt;One&gt;', confirmation['text'])
            data = confirmation['reply_markup']['inline_keyboard'][0][0]['callback_data']
            dialog.callback(10, 10, data, 'confirm-test')
            self.assertEqual(dialog.jobs.pending()[0]['payload'],
                             {'action': 'delete_library', 'inventory_id': 'a' * 32})
            dialog.callback(10, 10, data, 'confirm-test-2')
            self.assertEqual(len(dialog.jobs.pending()), 1)

    def test_owner_torrent_document_is_queued_as_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dialog = Dialog(Path(tmp), Telegram(), 'owner', '', lambda: {})
            dialog.handle({'update_id': 5, 'message': {'message_id': 5, 'from': {'id': 10, 'username': 'owner'},
                'chat': {'id': 10, 'type': 'private'}, 'document': {'file_id': 'testfile', 'file_name': 'film.torrent', 'file_size': 20}}})
            payload = dialog.jobs.pending()[0]['payload']
            self.assertEqual(payload['action'], 'add')
            self.assertIn('metainfo', payload)

    def test_stranger_cannot_queue_magnet_owner_can_and_replay_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Telegram()
            dialog = Dialog(Path(tmp), telegram, 'owner', '+70000000002', lambda: {'ok': True, 'disk_ok': True, 'torrents': []})
            def update(uid, username, update_id):
                return {'update_id': update_id, 'message': {'message_id': update_id,
                    'from': {'id': uid, 'username': username}, 'chat': {'id': uid, 'type': 'private'},
                    'text': 'magnet:?xt=urn:btih:' + 'a' * 40}}
            dialog.handle(update(77, 'stranger', 1))
            self.assertEqual(dialog.jobs.pending(), [])
            dialog.handle(update(10, 'owner', 2))
            dialog.handle(update(10, 'owner', 2))
            self.assertEqual(len(dialog.jobs.pending()), 1)
            self.assertEqual(dialog.jobs.pending()[0]['user_id'], 10)

    def test_callback_delete_only_offers_confirmation_without_queuing_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Telegram()
            dialog = Dialog(Path(tmp), telegram, 'owner', '', lambda: {'ok': True, 'disk_ok': True, 'torrents': []})
            dialog.handle({'update_id': 1, 'callback_query': {'id': 'cb1', 'from': {'id': 10, 'username': 'owner'},
                'data': 'delete:' + 'a' * 40, 'message': {'message_id': 1, 'chat': {'id': 10, 'type': 'private'}}}})
            self.assertEqual(dialog.jobs.pending(), [])
            sent = telegram.sent[-1][1]
            self.assertIn('Удалить', sent['text'])
            self.assertTrue(sent['reply_markup']['inline_keyboard'][0][0]['callback_data'].startswith('confirm:'))
