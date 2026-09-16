import unittest
from bot.download_forecast import predict, observe, forecast_line
class ForecastTests(unittest.TestCase):
    def test_no_history_is_honest(self):
        self.assertIsNone(predict([],dict(size=30*1024**3,seeders=20),1000))
        self.assertIn('Недостаточно',forecast_line(None))
    def test_saturation_outlier_and_size(self):
        rows=[dict(updated=900,bytes=600*1024**2,seconds=60,seeders=20,leechers=5) for _ in range(4)]
        rows.append(dict(updated=900,bytes=60000*1024**2,seconds=60,seeders=20))
        a=predict(rows,dict(size=30*1024**3,seeders=10),1000)
        b=predict(rows,dict(size=30*1024**3,seeders=1000),1000)
        self.assertAlmostEqual(a['speed'],b['speed'])
        self.assertLess(a['speed'],20*1024**2)
        self.assertGreater(predict(rows,dict(size=60*1024**3,seeders=10),1000)['seconds'],a['seconds'])
        self.assertLess(predict(rows,dict(size=30*1024**3,seeders=1),1000)['speed'],a['speed'])
        self.assertIsNone(predict(rows,dict(size=30*1024**3,seeders=0),1000))
    def test_observations_exclude_pause_outage_and_counter_reset(self):
        r={};t=dict(status=4,totalSize=10000,leftUntilDone=10000,quality=dict(seeders=12,leechers=2))
        observe(r,t,100);t['leftUntilDone']=9000;observe(r,t,110)
        self.assertEqual(r['bytes'],1000);self.assertEqual(r['seconds'],10)
        t['status']=0;observe(r,t,120)
        t['status']=4;t['leftUntilDone']=8000;observe(r,t,1000)
        self.assertEqual(r['bytes'],1000)
        t['leftUntilDone']=10000;observe(r,t,1010)
        self.assertEqual(r['bytes'],1000);self.assertEqual(r['seeders'],12)
    def test_stale_and_tiny_history_excluded(self):
        self.assertIsNone(predict([dict(updated=0,bytes=100,seconds=1)],dict(size=10000,seeders=10),9999999))
    def test_existing_history_is_preserved_without_invented_duration(self):
        from bot.download_forecast import records_for
        class Store:
            def read_states(self,prefix):
                if prefix.startswith('download-history:'):return {}
                return {'a':dict(uid=1,hash='a',speed_history=[[900,1000],[960,2000]]),'b':dict(uid=2,hash='b',speed_history=[[960,999999]])}
        rows=records_for(Store(),1)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['legacy'])
        self.assertNotIn('elapsed_seconds',rows[0])
    def test_rendered_release_choices_have_bold_forecast_and_buttons(self):
        import tempfile
        from bot.dialog import Dialog
        from bot.search import SearchFlow
        from tests.test_dialog import Telegram
        class Resolver:
            def identify(self,text,context):return dict(reply='Выберите',candidates=[dict(title='Film',year=2008,kind='movie')])
        class Indexer:
            def search(self,q):return [dict(title='Film 2008 1080p',seeders=12,leechers=3,size=6*1024**3,guid='r')]
        with tempfile.TemporaryDirectory() as tmp:
            chat=Telegram();flow=SearchFlow(Resolver(),Indexer());d=Dialog(tmp,chat,'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d);flow(10,10,'первый',d)
            messages=[p for _,p in chat.sent if 'text' in p and 'Недостаточно истории' in p['text']]
            self.assertTrue(messages)
            self.assertIn('<b>⏱',messages[-1]['text'])
            self.assertIn('раздают: 12',messages[-1]['text'])
            self.assertTrue(messages[-1]['reply_markup']['inline_keyboard'])
    def test_slow_edges_affect_whole_film_without_replacing_middle_speed(self):
        rows=[dict(updated=900,bytes=55200,seconds=720,phases=dict(start=dict(bytes=600,seconds=60),middle=dict(bytes=54000,seconds=600),end=dict(bytes=600,seconds=60)))]
        estimate=predict(rows,dict(size=10000,seeders=10),1000)
        self.assertAlmostEqual(estimate['speed'],50)
        self.assertAlmostEqual(estimate['seconds'],200)
    def test_mac_history_is_used_and_local_selection_metadata_kept(self):
        import tempfile
        from pathlib import Path
        from bot.jobs import JobStore
        from bot.download_forecast import records_for
        with tempfile.TemporaryDirectory() as tmp:
            store=JobStore(Path(tmp)/'jobs.db')
            store.write_state('download-history:1:h',dict(hash='h',seeders=89,bytes=100,seconds=10))
            store.write_state('mac-download-history',dict(records=[dict(hash='h',updated=900,bytes=10000,seconds=100)]))
            rows=records_for(store,1)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['seeders'],89)
            self.assertEqual(rows[0]['bytes'],10000)
