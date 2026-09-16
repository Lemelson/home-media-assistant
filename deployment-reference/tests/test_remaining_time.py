import unittest
from bot.progress import progress_text
from bot.download_dashboard import render


def torrent(done=1000, seconds=100, **extra):
    return dict(name='Фильм (2000)', hashString='a'*40, status=4,
                sizeWhenDone=100000, leftUntilDone=100000-done,
                percentDone=done/100000, secondsDownloading=seconds,
                downloadedEver=done, bandwidthPriority=0, **extra)


class RemainingDisplayTest(unittest.TestCase):
    def test_seven_films_show_remaining_without_speed_calendar_or_redundant_footer(self):
        states=[]
        for i in range(7):
            state=dict(name='Фильм (2000)', hash=str(i)*40)
            for now in range(0,301,30):
                state['text'],_=progress_text(state,torrent(1000+10*now,100+now),now)
            states.append(state)
        text,markup,page=render(states,1)
        self.assertIn('По всей загрузке:',text)
        self.assertIn('Осталось:',text)
        self.assertNotIn('Скорость:',text)
        self.assertNotIn('МСК',text)
        self.assertNotIn('Приоритет каждого фильма независим',text)
        self.assertEqual(7,sum(len(row) for row in markup['inline_keyboard']))
        self.assertEqual(0,page)


class RemainingMathTest(unittest.TestCase):
    def test_window_scale(self):
        from bot.remaining_time import recent_window
        for age, expected in [(1200,300),(3600,900),(7200,900),(10801,1800),
                              (21601,3600),(43201,7200),(86401,14400)]:
            self.assertEqual(expected,recent_window(age))

    def test_sample_cadence_does_not_change_average(self):
        from bot.remaining_time import observe
        results=[]
        for step in (5,15,30,60):
            state={}
            for now in range(0,601,step):
                result=observe(state,torrent(1000+now*10,7200),now)
            results.append(result)
        for result in results:
            self.assertEqual(9300,result['recent'])
            self.assertEqual(600,result['window'])
            self.assertLess(result['low'],result['recent'])
            self.assertGreater(result['high'],result['recent'])

    def test_priority_and_competitor_changes_discard_recent_not_lifetime(self):
        from bot.remaining_time import observe
        for change in ('priority','competitors'):
            state={}
            for now in (0,30,60,90):
                before=observe(state,torrent(1000+now*10,7200),now)
            self.assertIsNotNone(before['recent'])
            t=torrent(2200,7200)
            if change=='priority':t['bandwidthPriority']=1
            else:state['remaining_workload']=[['another',1]]
            after=observe(state,t,120)
            self.assertIsNone(after['recent'])
            self.assertIsNotNone(after['full'])
            for now in (150,180):
                t['leftUntilDone']-=300
                after=observe(state,t,now)
            self.assertIsNotNone(after['recent'])

    def test_pause_gap_and_counter_regression_do_not_become_download_speed(self):
        from bot.remaining_time import observe
        for interruption in ('pause','gap','regression'):
            state={}
            for now in (0,30,60):observe(state,torrent(1000+now*10,100+now),now)
            t=torrent(2000,200)
            if interruption=='pause':
                t['status']=0
                self.assertIsNone(observe(state,t,90)['recent'])
                t['status']=4
                after=observe(state,t,120)
            elif interruption=='gap':after=observe(state,t,300)
            else:after=observe(state,torrent(500,200),90)
            self.assertIsNone(after['recent'])

    def test_stall_hides_recent_and_recovery_relearns(self):
        from bot.remaining_time import observe, lines
        state={}
        for now in (0,30,60):observe(state,torrent(1000+now*10,100+now),now)
        for now in (90,120,150,180):estimate=observe(state,torrent(1600,100+now),now)
        self.assertTrue(estimate['stalled'])
        self.assertIsNone(estimate['recent'])
        self.assertIn('после возобновления',lines(estimate)[-1])
        estimate=observe(state,torrent(1900,310),210)
        self.assertFalse(estimate['stalled'])
        self.assertIsNone(estimate['recent'])

    def test_client_lifetime_counters_win_over_partial_bot_history(self):
        from bot.remaining_time import observe
        state={'remaining_history':{'bytes':100,'seconds':100}}
        result=observe(state,torrent(10000,1000),0)
        self.assertEqual(9000,result['full'])
        # Extra retransmitted data must not make the useful transfer seem faster.
        t=torrent(10000,1000);t['downloadedEver']=20000
        self.assertEqual(9000,observe(state,t,30)['full'])

    def test_persistent_history_is_bounded_and_survives_serialization(self):
        import json
        from bot.remaining_time import observe
        state={}
        for now in range(0,20000,30):
            t=torrent(1000,100000);t.update(sizeWhenDone=100000000,leftUntilDone=100000000-now*10)
            result=observe(state,t,now)
            state=json.loads(json.dumps(state))
        self.assertLessEqual(len(state['remaining_model']['buckets']),241)
        self.assertEqual(14400,result['window'])
        self.assertAlmostEqual(t['leftUntilDone']/10,result['recent'])

    def test_long_zero_intervals_do_not_get_finite_upper_bound(self):
        from bot.remaining_time import observe
        state={};done=1000
        for now in range(0,1201,30):
            if 0<now%120<=60:done+=600
            estimate=observe(state,torrent(done,7200),now)
        self.assertIsNotNone(estimate['recent'])
        self.assertIsNone(estimate['high'])

    def test_workload_ignores_seeding_but_includes_zero_rate_downloads(self):
        from bot.remaining_time import workload
        a=torrent(rateDownload=0);b=torrent();b.update(hashString='b',status=6)
        self.assertEqual([['a'*40,0]],workload([a,b]))

    def test_single_status_failure_preserves_recent_window(self):
        import tempfile
        from bot.dialog import Dialog
        from bot.progress import ProgressMonitor
        from tests.test_progress import Telegram
        with tempfile.TemporaryDirectory() as tmp:
            current=torrent(1000,100)
            available=[True]
            def status():
                if not available[0]:raise RuntimeError('temporary')
                return {'disk_ok':True,'torrents':[current]}
            dialog=Dialog(tmp,Telegram(),'','',status)
            monitor=ProgressMonitor(dialog)
            monitor.register(1,dict(hash='a'*40,name='Film'),100)
            monitor.tick(100)
            current.update(leftUntilDone=98700,downloadedEver=1300,secondsDownloading=130)
            monitor.tick(130)
            before=dialog.jobs.read_state('transfer:1:'+'a'*40)['remaining_model']
            available[0]=False;monitor.tick(160)
            after=dialog.jobs.read_state('transfer:1:'+'a'*40).get('remaining_model')
            self.assertEqual(before,after)
            available[0]=True
            current.update(leftUntilDone=98100,downloadedEver=1900,secondsDownloading=190)
            monitor.tick(190)
            self.assertIn('(за ',dialog.jobs.read_state('transfer:1:'+'a'*40)['text'])
