import tempfile
import unittest
from unittest.mock import patch
from bot.dialog import Dialog
from bot.progress import ProgressMonitor
from bot.download_dashboard import publish

class Telegram:
    def __init__(self): self.calls=[]; self.fail=False
    def call(self, method, **payload):
        if self.fail and method=='editMessageText': raise RuntimeError('temporary')
        self.calls.append((method,payload)); return {'message_id':1}

class StatusDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.tg=Telegram(); self.ok=True; self.disk=True; self.requests=0
        self.dialog=Dialog(self.tmp.name,self.tg,'','',self.status)
        self.monitor=ProgressMonitor(self.dialog)
        for h in ('a'*40,'b'*40):self.monitor.register(1,{'hash':h,'name':'Example'},100)
        self.monitor.tick(160)
    def status(self):
        self.requests+=1
        if not self.ok:raise TimeoutError()
        return {'disk_ok':self.disk,'torrents':[{'hashString':h,'status':4,'percentDone':.5,'totalSize':1000,'leftUntilDone':500,'rateDownload':100} for h in ('a'*40,'b'*40)]}
    def text(self):return self.dialog.jobs.read_state('download-dashboard:1')['text']
    def test_transient_failure_has_one_age_notice_and_recovers(self):
        self.ok=False;self.monitor.tick(190)
        text=self.text()
        self.assertNotIn('Обновление статуса задерживается',text)
        self.assertEqual(text.count('Данные получены'),1)
        self.assertEqual(text.count('50.0%'),2)
        self.assertNotIn('Осталось:',text)
        self.assertNotIn('По всей загрузке:',text)
        self.ok=True;self.monitor.tick(205)
        self.assertNotIn('Данные получены',self.text())
    def test_age_alone_exposes_outage_while_poll_is_blocked(self):
        publish(self.dialog,1,280)
        self.assertEqual(self.text().count('Нет свежего статуса'),1)
        self.assertNotIn('Осталось:',self.text())
    def test_missing_disk_is_immediate_and_once(self):
        self.disk=False;self.monitor.tick(175)
        self.assertEqual(self.text().count('Диск недоступен'),1)
    def test_delivery_retry_does_not_request_status(self):
        from bot.status_delivery import DashboardDelivery
        self.ok=False;self.monitor.tick(190,publish_updates=False)
        count=self.requests;worker=DashboardDelivery(self.dialog)
        self.tg.fail=True;worker.step(190)
        self.tg.fail=False;worker.step(193)
        self.assertEqual(self.requests,count)
        self.assertEqual(self.text().count('Данные получены'),1)
    def test_independent_mode_does_not_poll_in_command_worker(self):
        from bot.delivery import DeliveryWorker
        worker=DeliveryWorker(self.dialog,object(),separate_progress=True)
        with patch.object(worker.monitor,'tick') as tick:
            worker.step(200)
            tick.assert_not_called()

    def test_blocked_poll_does_not_block_delivery(self):
        import threading
        from bot.status_delivery import DashboardDelivery
        started=threading.Event(); release=threading.Event()
        def slow():
            started.set();release.wait(2)
            return self.status()
        self.dialog.media_status=slow
        thread=threading.Thread(target=lambda:self.monitor.tick(280,publish_updates=False))
        thread.start()
        try:
            self.assertTrue(started.wait(1))
            DashboardDelivery(self.dialog).step(280)
            self.assertTrue(thread.is_alive())
            self.assertIn('Нет свежего статуса',self.text())
        finally:
            release.set();thread.join(3)
        DashboardDelivery(self.dialog).step(281)
        self.assertNotIn('Нет свежего статуса',self.text())
