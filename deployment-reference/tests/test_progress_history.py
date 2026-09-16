import unittest
from bot.progress import progress_text

class HistoryTests(unittest.TestCase):
    def test_resume_keeps_torrent_history_but_excludes_paused_time(self):
        s={'name':'Film'}
        t=dict(status=4, totalSize=1000000, leftUntilDone=1000000, percentDone=0)
        for now in range(100,701,30):
            t.update(leftUntilDone=1000000-(now-100)*100,percentDone=(now-100)/10000)
            progress_text(s,t,now)
        t['status']=0
        progress_text(s,t,800)
        t['status']=4
        text,_=progress_text(s,t,5000)
        self.assertIn('Предварительно',text)
        self.assertIn('Осталось:',text)
        self.assertNotIn('Скорость: 0.0',text)
        self.assertTrue(s['speed_history'])
        t['leftUntilDone']-=6000
        progress_text(s,t,5060)
        self.assertAlmostEqual(s['eta_model']['rate'],100)

    def test_historical_prior_is_not_a_promise_during_stall(self):
        s={'name':'Film','speed_history':[[100,100],[160,110],[220,90]]}
        t=dict(status=4,totalSize=1000000,leftUntilDone=900000,percentDone=.1)
        text,_=progress_text(s,t,300)
        self.assertIn('Предварительно',text)
        progress_text(s,t,360)
        text,_=progress_text(s,t,430)
        self.assertIn('Ожидаю данные',text)
        self.assertNotIn('Осталось:',text)

    def test_new_torrent_gets_robust_history_from_same_user(self):
        import tempfile
        from bot.dialog import Dialog
        from bot.progress import ProgressMonitor, history_rate
        from tests.test_progress_rotation import Chat
        with tempfile.TemporaryDirectory() as tmp:
            d=Dialog(tmp,Chat(),'','',lambda:{})
            d.jobs.write_state('transfer:1:old',dict(uid=1,hash='old',speed_history=[[100,100],[160,100],[220,10000]]))
            d.jobs.write_state('transfer:2:other',dict(uid=2,hash='other',speed_history=[[220,100000]]))
            ProgressMonitor(d).register(1,dict(hash='new',name='New'),300)
            s=d.jobs.read_state('transfer:1:new')
            self.assertLess(history_rate(s['bootstrap_history'],300),200)
            text,_=progress_text(s,dict(status=4,totalSize=1000000,leftUntilDone=1000000,percentDone=0),300)
            self.assertIn('Предварительно',text)
            self.assertIn('Осталось:',text)
