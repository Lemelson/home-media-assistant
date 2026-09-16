import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from mac_agent.disk_summary import collect
from bot.disk_summary import render

G = 1024**3

class DiskSummaryTests(unittest.TestCase):
    def test_queue_includes_paused_but_not_other_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [dict(hashString='a', downloadDir=str(root/'Movies'), totalSize=10*G, leftUntilDone=4*G, rateDownload=G, status=4),
                    dict(hashString='b', downloadDir=str(root/'Movies'), totalSize=10*G, leftUntilDone=8*G, rateDownload=99*G, status=0),
                    dict(hashString='c', downloadDir='/elsewhere', totalSize=50*G, leftUntilDone=50*G, rateDownload=G, status=4)]
            with patch('mac_agent.disk_summary.shutil.disk_usage', return_value=SimpleNamespace(free=10*G)):
                result = collect(root, rows, {}, G)
            self.assertEqual(result['remaining_bytes'], 12*G)
            self.assertEqual(result['rate_bytes'], G)
            text = render(dict(result, at=100), 100)
            self.assertIn('Не хватит: <b>2.0 ГБ', text)
            self.assertIn('Свободно: <b>10.0 ГБ', text)
            self.assertIn('защитная пауза', text)

    def test_unknown_size_and_zero_speed_do_not_promise_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = dict(hashString='a', downloadDir=tmp, totalSize=0, leftUntilDone=0, status=0)
            with patch('mac_agent.disk_summary.shutil.disk_usage', return_value=SimpleNamespace(free=10*G)):
                result = collect(Path(tmp), [row], {'a': {'reserved_bytes': 5*G}}, G)
            self.assertEqual(result['remaining_bytes'], 5*G)
            text = render(dict(result, at=100), 100)
            self.assertIn('после загрузок: уточняется', text)
            self.assertNotIn('после загрузок: <b>', text)
            self.assertIn('Жду скорость', text)

    def test_sufficient_space_and_stale_data(self):
        result = dict(free_bytes=20*G, remaining_bytes=5*G, rate_bytes=G/100,
                      headroom_bytes=G, unknown_count=0, at=100)
        text = render(result, 100)
        self.assertIn('после загрузок: <b>15.0 ГБ', text)
        self.assertIn('При текущем темпе:', text)
        self.assertNotIn('До заполнения', text)
        self.assertEqual(len(text.splitlines()), 2)
        self.assertLess(len(text), 140)
        stale = render(result, 200)
        self.assertNotIn('15.0 ГБ', stale)
        self.assertNotIn('≈', stale)

    def test_unavailable_probe_is_not_zero_free(self):
        self.assertIn('Обновляю данные о диске', render({'at':100}, 100))

    def test_status_to_dashboard_delivery_and_outage(self):
        from bot.dialog import Dialog
        from bot.progress import ProgressMonitor
        from test_progress_rotation import Chat
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = dict(free_bytes=20*G, remaining_bytes=5*G, rate_bytes=G/100,
                            headroom_bytes=G, unknown_count=0)
            row = dict(hashString='a'*40, name='Film', status=4, totalSize=10*G,
                       leftUntilDone=5*G, percentDone=.5, rateDownload=G/100)
            status = dict(disk_ok=True, torrents=[row], disk_summary=snapshot)
            chat = Chat()
            dialog = Dialog(tmp, chat, '', '', lambda: status)
            monitor = ProgressMonitor(dialog)
            monitor.register(1, dict(hash=row['hashString'], name='Film'), 100)
            monitor.tick(101)
            text = dialog.jobs.read_state('download-dashboard:1')['text']
            self.assertIn('15.0 ГБ', text)
            status.clear()
            monitor.tick(110)
            text = dialog.jobs.read_state('download-dashboard:1')['text']
            self.assertIn('Обновляю данные о диске', text)
            self.assertNotIn('15.0 ГБ', text)

    def test_summary_is_in_message_budget_on_every_page(self):
        from bot.download_dashboard import render as dashboard
        rows = [dict(hash=str(i), name='Long film '*15, text='█'*18, active=True) for i in range(45)]
        snapshot = dict(free_bytes=20*G, remaining_bytes=5*G, rate_bytes=G/100,
                        headroom_bytes=G, unknown_count=0, at=100)
        for page in range(15):
            text, _, _ = dashboard(rows, page, 100, snapshot)
            self.assertIn('15.0 ГБ', text)
            self.assertLessEqual(len(text.encode('utf-16-le'))//2, 3800)

    def test_agent_status_supplies_capacity(self):
        from mac_agent.media import MediaController
        from tests.test_media import FakeRPC
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rpc = FakeRPC()
            rpc.torrents = [dict(hashString='a', downloadDir=tmp, totalSize=10*G,
                                 leftUntilDone=4*G, rateDownload=100, status=4)]
            controller = MediaController(root/'db', rpc, lambda: root)
            with patch('mac_agent.disk_summary.shutil.disk_usage', return_value=SimpleNamespace(free=10*G)):
                status = controller.status()
            self.assertEqual(status['disk_summary']['remaining_bytes'], 4*G)
            self.assertEqual(status['disk_summary']['free_bytes'], 10*G)
