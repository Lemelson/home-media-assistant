import unittest
from bot.queue_eta import observe


def torrent(h='a', left=100000, done=0, status=4, **extra):
    return dict(hashString=h, totalSize=left+done, leftUntilDone=left,
                status=status, rateDownload=999999999, **extra)


class QueueEtaTests(unittest.TestCase):
    def run_window(self, speeds, left=100000):
        history = {}
        total = left + sum(speeds)*60
        result = observe(history, [torrent(left=total)], 0)
        done = 0
        for minute, speed in enumerate(speeds, 1):
            done += speed*60
            result = observe(history, [torrent(left=total-done, done=done)], minute*60)
        return history, result

    def test_uses_ten_minutes_of_bytes_including_zero_progress(self):
        _, result = self.run_window([100]*5+[0]*5)
        row = result['films']['a']
        self.assertEqual(row['rate'], 50)
        self.assertEqual(row['coverage'], 600)
        self.assertIsNone(row['high'])
        self.assertEqual(row['state'], 'stalled')

    def test_expired_fast_bytes_do_not_affect_window(self):
        _, result = self.run_window([10000]+[100]*10)
        self.assertAlmostEqual(result['films']['a']['rate'], 100)
        self.assertAlmostEqual(result['films']['a']['low'], 100000/115)
        self.assertAlmostEqual(result['films']['a']['high'], 100000/85)

    def test_slowest_film_controls_completion_not_aggregate_rate(self):
        history = {}
        for at in range(0, 601, 60):
            result = observe(history, [torrent('fast', 100000-at*100, at*100),
                                      torrent('slow', 100000-at, at)], at)
        self.assertEqual(result['complete']['low'], result['films']['slow']['low'])
        self.assertGreater(result['complete']['low'], 80000)

    def test_pause_prevents_finite_whole_queue_forecast(self):
        history = {}
        for at in range(0, 601, 60):
            result = observe(history, [torrent('active', 100000-at*100, at*100),
                                      torrent('pause', status=0)], at)
        self.assertIsNone(result['complete'])
        self.assertEqual(result['paused'], 1)
        self.assertIsNotNone(result['active'])

    def test_partial_window_and_missing_observations_are_not_ten_minutes(self):
        history, _ = self.run_window([100]*9)
        result = observe(history, [torrent(left=100000, done=54000)], 700)
        self.assertEqual(result['warming'], 1)
        self.assertIsNone(result['complete'])

    def test_counter_reset_discards_false_progress(self):
        history, _ = self.run_window([100]*10)
        result = observe(history, [torrent(left=160000)], 660)
        self.assertEqual(result['warming'], 1)
        self.assertEqual(result['films']['a']['coverage'], 0)

    def test_restart_preserves_window_and_duplicate_tick_is_harmless(self):
        import json
        history, first = self.run_window([100]*10)
        restored = json.loads(json.dumps(history))
        second = observe(restored, [torrent(left=100000, done=60000)], 600)
        self.assertEqual(first, second)
        third = observe(restored, [torrent(left=94000, done=66000)], 660)
        self.assertEqual(third['films']['a']['coverage'], 600)

    def test_disk_fill_accounts_for_fast_film_finishing(self):
        from bot.queue_eta import fill_time
        # Fast film completes after 1s, slow one supplies the other 900 bytes.
        self.assertAlmostEqual(fill_time([(100,100), (1000,1)], 1000), 900)
        self.assertIsNone(fill_time([(100,100), (1000,0)], 1000))

    def test_poll_cadence_and_window_edges_are_time_weighted(self):
        history = {}
        for at in [7, 24, 81, 99, 168, 240, 290, 366, 430, 500, 575, 620]:
            result = observe(history, [torrent(left=100000-at*20, done=at*20)], at)
        self.assertAlmostEqual(result['films']['a']['rate'], 20)
        self.assertAlmostEqual(result['films']['a']['coverage'], 600)
        self.assertLessEqual(len(history['films']['a']['buckets']), 11)

    def test_resume_keeps_observed_pause_in_ten_minute_average(self):
        history = {}
        for at in range(0, 601, 60):
            done = max(0, at-300)*100
            result = observe(history, [torrent(left=100000-done, done=done, status=0 if at<=300 else 4)], at)
        self.assertEqual(result['films']['a']['rate'], 50)
        self.assertIsNone(result['complete']['high'])

    def test_unmanaged_disk_queue_prevents_whole_queue_promise(self):
        history, _ = self.run_window([100]*10)
        result = observe(history, [torrent(left=100000, done=60000)], 600,
                         {'remaining_bytes':200000, 'free_bytes':1000000})
        self.assertIsNone(result['complete'])
        self.assertEqual(result['unknown'], 1)

    def test_compact_ranges_and_pause_wording(self):
        from bot.disk_summary import render
        disk = dict(free_bytes=20*1024**3, remaining_bytes=5*1024**3,
                    headroom_bytes=2*1024**3, unknown_count=0, at=100,
                    forecast={'complete':dict(low=3600, high=7200)})
        text = render(disk,100)
        self.assertEqual(len(text.splitlines()),2)
        self.assertIn('≈ 1 ч 00 мин–2 ч 00 мин (за 10 мин)', text)
        disk['forecast'] = dict(active=dict(low=3600,high=7200), paused=1)
        text = render(disk,100)
        self.assertIn('Активные:', text)
        self.assertIn('пауза: 1', text)

    def test_progress_monitor_persists_real_byte_history(self):
        import tempfile
        from bot.dialog import Dialog
        from bot.progress import ProgressMonitor
        from test_progress_rotation import Chat
        with tempfile.TemporaryDirectory() as tmp:
            row = torrent(left=100000, name='Film')
            status = dict(disk_ok=True, torrents=[row], disk_summary={
                'free_bytes':1000000,'remaining_bytes':100000,'headroom_bytes':1000,'unknown_count':0})
            dialog = Dialog(tmp,Chat(),'','',lambda:status)
            monitor = ProgressMonitor(dialog)
            monitor.register(1, dict(hash='a',name='Film'),0)
            for at in range(0,601,60):
                row.update(leftUntilDone=100000-at*10, percentDone=at*10/100000)
                status['disk_summary']['remaining_bytes']=row['leftUntilDone']
                monitor.tick(at)
            result=dialog.jobs.read_state('disk-summary')['forecast']
            self.assertEqual(result['films']['a']['rate'],10)
            self.assertIn('(за 10 мин)',dialog.jobs.read_state('download-dashboard:1')['text'])
