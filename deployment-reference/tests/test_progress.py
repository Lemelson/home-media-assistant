import tempfile
import unittest
from pathlib import Path

from bot.dialog import Dialog
from bot.progress import ProgressMonitor


class Telegram:
    def __init__(self):
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {'message_id': len(self.calls)}


class ProgressTests(unittest.TestCase):
    def test_error_at_100_percent_is_not_reported_as_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            t = {'hashString': 'c' * 40, 'status': 0, 'percentDone': 1,
                 'totalSize': 1000, 'leftUntilDone': 0, 'errorString': 'No data found'}
            dialog = Dialog(tmp, tg, '', '', lambda: {'disk_ok': True, 'torrents': [t]})
            monitor = ProgressMonitor(dialog)
            monitor.register(1, {'hash': 'c' * 40, 'name': 'Missing'}, now=100)
            monitor.tick(now=160)
            self.assertFalse(any('Фильм скачан' in p.get('text', '') for m,p in tg.calls))

    def test_edit_failure_cannot_suppress_separate_completion_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            class CannotEdit(Telegram):
                def call(self, method, **payload):
                    if method == 'editMessageText':
                        raise RuntimeError('message_not_found')
                    return super().call(method, **payload)
            tg = CannotEdit()
            t = {'hashString': 'd' * 40, 'status': 6, 'percentDone': 1,
                 'totalSize': 1000, 'leftUntilDone': 0}
            dialog = Dialog(tmp, tg, '', '', lambda: {'disk_ok': True, 'torrents': [t]})
            monitor = ProgressMonitor(dialog)
            monitor.register(1, {'hash': 'd' * 40, 'name': 'Complete'}, now=100)
            monitor.tick(now=160)
            self.assertTrue(any('Фильм скачан' in p.get('text', '') for m,p in tg.calls))

    def test_progress_edits_one_message_and_completion_notifies_once_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            current = {'hashString': 'a' * 40, 'name': 'Film <A>', 'status': 4,
                       'sizeWhenDone': 1000, 'totalSize': 1000, 'leftUntilDone': 1000, 'percentDone': 0}
            status = lambda: {'disk_ok': True, 'torrents': [current]}
            dialog = Dialog(Path(tmp), tg, '', '', status)
            monitor = ProgressMonitor(dialog)
            monitor.register(10, {'hash': 'a' * 40, 'name': 'Film <A>'}, now=100)
            monitor.tick(now=100)
            current.update(leftUntilDone=700, percentDone=.3)
            monitor.tick(now=160)
            edits = [p for m, p in tg.calls if m == 'editMessageText']
            self.assertEqual(len(edits), 1)
            self.assertIn('30.0%', edits[0]['text'])
            self.assertIn('По наблюдениям бота: ≈ 5 мин', edits[0]['text'])
            self.assertIn('Film &lt;A&gt;', edits[0]['text'])
            current.update(leftUntilDone=0, percentDone=1, status=6)
            monitor.tick(now=220)
            completed = [p for m, p in tg.calls if m == 'editMessageText' and 'Фильм скачан' in p['text']]
            self.assertEqual(len(completed), 1)
            ProgressMonitor(dialog).tick(now=280)
            self.assertEqual(len([p for m, p in tg.calls if m == 'editMessageText' and 'Фильм скачан' in p['text']]), 1)

    def test_pause_and_offline_do_not_predict_completion_or_create_more_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram()
            current = {'hashString': 'b' * 40, 'status': 0, 'percentDone': .9,
                       'totalSize': 1000, 'leftUntilDone': 100, 'rateDownload': 1000}
            dialog = Dialog(tmp, tg, '', '', lambda: {'disk_ok': True, 'torrents': [current]})
            monitor = ProgressMonitor(dialog)
            monitor.register(1, {'hash': 'b' * 40, 'name': 'Paused'}, now=100)
            monitor.tick(now=160)
            payload = [p for m,p in tg.calls if m == 'editMessageText'][-1]
            self.assertIn('паузе', payload['text'])
            self.assertNotIn('Готово примерно', payload['text'])
            self.assertEqual(len([m for m,p in tg.calls if m == 'sendMessage']), 1)

    def test_milestones_edit_the_same_dashboard_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram();torrent=dict(hashString='e'*40,name='Film',status=4,percentDone=0,totalSize=1000,leftUntilDone=1000)
            dialog=Dialog(tmp,tg,'','',lambda:dict(disk_ok=True,torrents=[torrent]))
            ProgressMonitor(dialog).register(1,dict(hash='e'*40,name='Film'),100)
            for now,pct in [(160,.76),(220,.96),(280,.99)]:
                torrent.update(percentDone=pct,leftUntilDone=1000*(1-pct))
                ProgressMonitor(dialog).tick(now)
                self.assertIn('%.1f%%' % (pct*100),tg.calls[-1][1]['text'])
            self.assertEqual(sum(m=='sendMessage' for m,p in tg.calls),1)
            self.assertEqual(len({p['message_id'] for m,p in tg.calls if m=='editMessageText'}),1)

    def test_adopts_old_successful_job_only_for_incomplete_torrent_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram();active={'hashString':'f'*40,'name':'Old Film','status':4,'percentDone':.4,'totalSize':1000,'leftUntilDone':600}
            complete={'hashString':'a'*40,'name':'Done','status':6,'percentDone':1,'totalSize':1000,'leftUntilDone':0}
            dialog=Dialog(tmp,tg,'','',lambda:{'disk_ok':True,'torrents':[active,complete]})
            for t in (active,complete):
                job=dialog.jobs.enqueue('old:'+t['hashString'],1,{'action':'add'})
                dialog.jobs.finish(job,{'ok':True,'hash':t['hashString'],'name':t['name']})
                dialog.jobs.mark_notified(job)
            ProgressMonitor(dialog).tick(now=100)
            self.assertEqual(len(tg.calls),1);self.assertIn('Old Film',tg.calls[0][1]['text'])
            self.assertIsNone(dialog.jobs.read_state('transfer:1:'+'a'*40))
            ProgressMonitor(dialog).tick(now=120);self.assertEqual(len([m for m,p in tg.calls if m=='sendMessage']),1)

    def test_progress_bottom_has_bar_percent_and_italic_eta(self):
        from bot.progress import progress_text
        state={'name':'Film','samples':[[100,0]],'eta_model':{'start':100,'last_progress':100}}
        text,complete=progress_text(state,{'name':'Film','status':4,'percentDone':.5,'totalSize':1000,'leftUntilDone':500},160)
        self.assertFalse(complete);self.assertIn('<b>Film</b>',text)
        self.assertIn('50.0%',text.splitlines()[-2]);self.assertIn('█',text.splitlines()[-2])
        self.assertIn('<i>Осталось:',text.splitlines()[-1])

    def test_transient_edit_failure_retries_completion_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            class FailOnce(Telegram):
                failed=False
                def call(self,method,**payload):
                    if method=='editMessageText' and not self.failed:
                        self.failed=True
                        raise RuntimeError('temporary')
                    return super().call(method,**payload)
            tg=FailOnce();torrent=dict(hashString='b'*40,status=6,percentDone=1,totalSize=1000,leftUntilDone=0)
            dialog=Dialog(tmp,tg,'','',lambda:dict(disk_ok=True,torrents=[torrent]))
            ProgressMonitor(dialog).register(1,dict(hash='b'*40,name='Film'),100)
            ProgressMonitor(dialog).tick(160)
            ProgressMonitor(dialog).tick(220)
            self.assertIn('Фильм скачан',tg.calls[-1][1]['text'])
            self.assertEqual(sum(m=='sendMessage' for m,p in tg.calls),1)


class AdaptiveETATests(unittest.TestCase):
    def sample(self,state,now,done,left=100000):
        from bot.progress import adaptive_eta
        return adaptive_eta(state,done,left,now)

    def test_warmup_and_growing_window_are_bounded_to_five_minutes(self):
        state={}
        self.assertIsNone(self.sample(state,0,0)['eta'])
        self.assertIsNone(self.sample(state,30,300)['eta'])
        for t in range(60,3661,30):result=self.sample(state,t,t*10)
        self.assertGreater(result['window'],250);self.assertLessEqual(result['window'],300)
        self.assertAlmostEqual(result['eta'],10000)
        self.assertGreaterEqual(state['samples'][0][0],3360)

    def test_sustained_rate_change_resets_but_brief_spike_does_not(self):
        for rate in (3,30):
            state={}
            for t in range(0,301,30):self.sample(state,t,t*10)
            self.sample(state,330,3000+rate*30)
            changed=self.sample(state,360,3000+rate*60)
            self.assertLess(changed['window'],150)
            self.assertLess(changed['eta'],10000) if rate>10 else self.assertGreater(changed['eta'],10000)
        state={}
        for t in range(0,301,5):self.sample(state,t,t*10)
        baseline=self.sample(state,305,3050)
        self.sample(state,310,4050)
        for t in range(315,361,5):result=self.sample(state,t,4050+(t-310)*10)
        self.assertGreater(result['eta'],baseline['eta']*.65);self.assertLess(result['eta'],baseline['eta']*1.1)

    def test_stalled_99_percent_and_recovery_have_no_stale_eta(self):
        state={}
        for t in (0,30,60):self.sample(state,t,t*10,left=10)
        self.sample(state,120,600,left=10)
        stalled=self.sample(state,180,600,left=10)
        self.assertTrue(stalled['stalled']);self.assertIsNone(stalled['eta'])
        recovery=self.sample(state,190,610,left=10)
        self.assertTrue(recovery['preliminary']);self.assertGreater(recovery['eta'],0)

    def test_near_completion_shortens_window_and_unstable_rates_hide_clock(self):
        state={}
        for t in range(0,301,30):self.sample(state,t,t*10)
        near=self.sample(state,330,3300,left=3000)
        self.assertLessEqual(near['window'],120)
        unstable={};done=0
        self.sample(unstable,0,0)
        for i,rate in enumerate((1,100,1,100,1,100),1):
            done+=rate*30;result=self.sample(unstable,i*30,done)
        self.assertTrue(result['unstable']);self.assertIsNone(result['eta'])

    def test_remaining_duration_has_no_calendar_and_pause_resets_warmup(self):
        from bot.progress import eta_description,progress_text
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now=datetime(2026,9,14,23,50,tzinfo=ZoneInfo('Europe/Moscow')).timestamp()
        self.assertIn('20 мин',eta_description(1200,now));self.assertNotIn('00:10',eta_description(1200,now))
        self.assertNotIn('сегодня',eta_description(60,now));self.assertIn('≈',eta_description(60,now))
        state={'name':'Film'}
        torrent={'status':4,'percentDone':.1,'totalSize':10000,'leftUntilDone':9000}
        progress_text(state,torrent,0);torrent['leftUntilDone']=8000;progress_text(state,torrent,60)
        torrent['status']=0;progress_text(state,torrent,70)
        torrent['status']=4;torrent['leftUntilDone']=7900
        text,_=progress_text(state,torrent,80)
        self.assertIn('Предварительно',text);self.assertNotIn('МСК',text)

    def test_ema_decay_is_time_based_and_near_finish_window_changes_continuously(self):
        import math
        import copy
        from bot.progress import _mix
        self.assertAlmostEqual(_mix(10,30,60,120),10+20*(1-math.exp(-.5)))
        self.assertAlmostEqual(_mix(_mix(10,30,30,120),30,30,120),_mix(10,30,60,120))
        state={}
        for t in range(0,301,30):self.sample(state,t,t*10)
        first=self.sample(copy.deepcopy(state),330,3300,left=5990)
        second=self.sample(copy.deepcopy(state),330,3300,left=6010)
        self.assertLess(abs(first['window']-second['window']),1)
        self.assertGreaterEqual(first['window'],60)

    def test_recent_display_speed_is_faster_than_smoothed_forecast_after_spike(self):
        state={}
        for t in range(0,301,5):self.sample(state,t,t*10)
        result=self.sample(state,305,4000)
        self.assertGreater(result['speed'],100000/result['eta'])

    def test_restart_keeps_ema_and_outage_resets_it(self):
        import json
        state={}
        for t in (0,30,60):self.sample(state,t,t*10)
        restored=json.loads(json.dumps(state))
        self.assertAlmostEqual(self.sample(restored,90,900)['eta'],10000)
        self.assertTrue(self.sample(restored,400,1000)['preliminary'])

    def test_initial_peer_wait_is_excluded_from_progress_warmup(self):
        state={}
        self.sample(state,0,0);self.sample(state,60,0)
        first_bytes=self.sample(state,75,150)
        self.assertIsNone(first_bytes['eta'])
        self.assertIsNone(self.sample(state,90,300)['eta'])
        ready=self.sample(state,120,600)
        self.assertAlmostEqual(ready['eta'],10000)

    def test_slow_transfer_shows_remaining_duration_instead_of_speed(self):
        from bot.progress import progress_text
        state={'name':'Film'}
        torrent={'status':4,'totalSize':1000000,'leftUntilDone':1000000,'percentDone':0}
        progress_text(state,torrent,0)
        torrent.update(leftUntilDone=940000,percentDone=.06)
        text,_=progress_text(state,torrent,60)
        self.assertIn('Осталось:',text);self.assertNotIn('Б/с',text)

    def test_two_minute_sustained_slowdown_is_not_hidden_by_ten_minute_history(self):
        state={}
        for t in range(0,601,15):self.sample(state,t,t*.5)
        for t in range(615,721,15):result=self.sample(state,t,300+(t-600)*.1)
        forecast_rate=100000/result['eta']
        self.assertLessEqual(forecast_rate,.2)
        self.assertGreaterEqual(result['window'],60)
