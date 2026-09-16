import tempfile,unittest
from pathlib import Path
from mac_agent.download_journal import DownloadJournal

class JournalTests(unittest.TestCase):
    def test_persistent_intervals_phases_and_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=DownloadJournal(Path(tmp)/'history');j.register('h',dict(name='Film',quality=dict(seeders=89,leechers=5)),100)
            t=dict(hashString='h',name='Film',totalSize=10000,leftUntilDone=10000,percentDone=0,status=4)
            j.record([t],110)
            t.update(leftUntilDone=9400,percentDone=.06);j.record([t],140)
            t.update(leftUntilDone=500,percentDone=.95);j.record([t],440) # outage is excluded
            t.update(leftUntilDone=400,percentDone=.96);j.record([t],470)
            t.update(status=0);j.record([t],480)
            t.update(status=4,leftUntilDone=300);j.record([t],500)
            t.update(status=6,leftUntilDone=0,percentDone=1);j.record([t],530)
            r=DownloadJournal(Path(tmp)/'history').summaries()[0]
            self.assertEqual(r['bytes'],1000)
            self.assertEqual(r['seconds'],90)
            self.assertEqual(r['seeders'],89)
            self.assertIn('start',r['phases']);self.assertIn('end',r['phases'])
            self.assertEqual(r['completed'],530)
            self.assertGreater(j.storage()['bytes'],0)
            self.assertGreaterEqual(j.sample_count(),6)
    def test_each_new_torrent_over_threshold_has_durable_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=DownloadJournal(Path(tmp)/'history',limit=1)
            j.register('a',{},1);j.register('a',{},2);j.register('b',{},3)
            storage=j.storage()
            self.assertTrue(storage['over_limit']);self.assertEqual(len(storage['events']),2)
    def test_completed_torrent_does_not_grow_every_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=DownloadJournal(Path(tmp)/'history')
            t=dict(hashString='a',status=6,totalSize=100,leftUntilDone=0,percentDone=1)
            j.record([t],100);n=j.sample_count();j.record([t],200)
            self.assertEqual(j.sample_count(),n)
