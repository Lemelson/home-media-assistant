import tempfile
import time
import unittest
from unittest.mock import Mock
from bot.dialog import Dialog
from bot.progress import ProgressMonitor
from test_progress_rotation import Chat

class DownloadsRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chat = Chat()
        self.status = Mock(return_value={'disk_ok': True, 'torrents': [
            {'hashString': 'a' * 40, 'name': 'Film', 'status': 4,
             'percentDone': .5, 'totalSize': 1000, 'leftUntilDone': 500,
             'rateDownload': 100}]})
        self.dialog = Dialog(self.tmp.name, self.chat, '', '', self.status)
        monitor = ProgressMonitor(self.dialog)
        monitor.register(1, {'hash': 'a' * 40, 'name': 'Film'}, time.time())
        monitor.tick()
        self.later = self.dialog.send_html(1, 'Library shown later')['message_id']
        self.status.reset_mock()

    def test_explicit_request_reappears_after_later_messages(self):
        self.dialog.downloads(1)
        dashboard = self.dialog.jobs.read_state('download-dashboard:1')
        self.assertGreater(dashboard['message_id'], self.later)
        self.assertIn('50.0%', self.chat.messages[dashboard['message_id']])
        self.assertEqual(dashboard['markup']['inline_keyboard'][0][0]['callback_data'], 'priority:' + 'a' * 40)

    def test_existing_snapshot_is_delivered_without_remote_status_wait(self):
        self.status.side_effect = TimeoutError('slow Air')
        self.dialog.downloads(1)
        self.status.assert_not_called()
        dashboard = self.dialog.jobs.read_state('download-dashboard:1')
        self.assertGreater(dashboard['message_id'], self.later)
