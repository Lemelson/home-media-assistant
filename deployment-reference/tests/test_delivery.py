import tempfile
import unittest

from bot.dialog import Dialog
from bot.delivery import DeliveryWorker


class Telegram:
    def __init__(self): self.calls = []
    def call(self, method, **payload):
        self.calls.append((method, payload)); return {'message_id': len(self.calls)}


class Media:
    def __init__(self, result): self.result = result; self.commands = []
    def command(self, job): self.commands.append(job); return self.result
    def status(self): return {'disk_ok': True, 'torrents': []}


class DeliveryTests(unittest.TestCase):
    def test_added_is_not_completed_and_restarting_worker_does_not_renotify(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); media = Media({'ok': True, 'name': 'Film', 'hash': 'a' * 40})
            dialog = Dialog(tmp, tg, '', '', media.status)
            dialog.jobs.enqueue('film', 1, {'action': 'add', 'name': 'Film'})
            DeliveryWorker(dialog, media).step(now=100)
            self.assertEqual(len(media.commands), 1)
            self.assertEqual(len([m for m,p in tg.calls if m == 'sendMessage']), 1)
            self.assertFalse(any('Фильм скачан' in p.get('text','') for m,p in tg.calls))
            DeliveryWorker(dialog, media).step(now=120)
            self.assertEqual(len([m for m,p in tg.calls if m == 'sendMessage']), 1)

    def test_insufficient_space_offers_named_largest_files_and_no_delete_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); media = Media({'ok': False, 'error': 'insufficient_space',
                'required_bytes': 9*1024**3, 'free_bytes': 2*1024**3, 'headroom_bytes': 2*1024**3,
                'biggest': [{'id': 'b'*32, 'name': 'Big film', 'size_bytes': 20*1024**3}]})
            dialog = Dialog(tmp, tg, '', '', media.status)
            dialog.jobs.enqueue('film', 1, {'action': 'add', 'name': 'New film'})
            DeliveryWorker(dialog, media).step(now=100)
            self.assertEqual(dialog.jobs.pending(), [])
            message = tg.calls[-1][1]
            self.assertIn('Big film', message['text'])
            self.assertIn('20.0 ГБ', message['text'])
            self.assertTrue(message['reply_markup']['inline_keyboard'][0][0]['callback_data'].startswith('library-delete:'))
