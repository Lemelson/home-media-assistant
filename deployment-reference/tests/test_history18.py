import tempfile,unittest
from pathlib import Path
from bot.progress import progress_bar,progress_text

class BarTests(unittest.TestCase):
    def test_18_cells_and_half_step(self):
        for percent in (0,2.7,50,99.9,100,-10,150):self.assertEqual(len(progress_bar(percent)),18)
        self.assertEqual(progress_bar(0),'░'*18)
        self.assertEqual(progress_bar(50),'█'*9+'░'*9)
        self.assertEqual(progress_bar(100),'█'*18)
        self.assertIn('▌',progress_bar(2.8))
        self.assertNotEqual(progress_bar(99.9),'█'*18)
    def test_tracker_and_selection_counts_are_not_live_connections(self):
        s={'name':'Film'};t=dict(status=0,totalSize=100,leftUntilDone=50,percentDone=.5,quality=dict(seeders=89,leechers=5))
        text,_=progress_text(s,t,100)
        self.assertIn('Участники: нет свежих данных',text);self.assertNotIn('Раздают:',text)
        t.update(seeders=7,leechers=2,peersSendingToUs=3,peersConnected=4);text,_=progress_text(s,t,110)
        self.assertIn('Передают вам: 3 · подключено: 4',text)

class StorageWarningTests(unittest.TestCase):
    def test_owner_warning_once_then_every_new_film_and_retry(self):
        from bot.history_storage import sync_history
        from bot.jobs import JobStore
        class Access:
            def members(self):return [dict(role='owner',user_id=1),dict(role='mother',user_id=2)]
        class Dialog:
            access=Access()
            def __init__(self,tmp):self.jobs=JobStore(Path(tmp)/'jobs.db');self.sent=[];self.fail=False
            def send(self,uid,text):
                if self.fail:raise RuntimeError('offline')
                self.sent.append((uid,text))
        with tempfile.TemporaryDirectory() as tmp:
            d=Dialog(tmp)
            status=dict(download_history=[],history_storage=dict(bytes=300000001,limit=300000000,over_limit=True,events=[dict(id=1,over_limit=1)]))
            sync_history(d,status,100);sync_history(d,status,110)
            self.assertEqual(len(d.sent),1);self.assertEqual(d.sent[0][0],1)
            status['history_storage']['events'].append(dict(id=2,over_limit=1))
            d.fail=True
            with self.assertRaises(RuntimeError):sync_history(d,status,120)
            d.fail=False;sync_history(d,status,130)
            self.assertEqual(len(d.sent),2)
