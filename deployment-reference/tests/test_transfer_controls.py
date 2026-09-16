import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mac_agent.media import MediaController, DiskUnavailable

class RPC:
    def __init__(self,root):
        self.calls=[]
        self.rows=[{'hashString':c*40,'name':c,'status':4 if c=='a' else 0,'leftUntilDone':100,'totalSize':100,'downloadDir':str(root/'Movies'),'bandwidthPriority':0} for c in ('a','b')]
    def call(self,m,a=None):
        a=a or {};self.calls.append((m,a))
        rows=[r for r in self.rows if not a.get('ids') or r['hashString'] in a['ids']]
        if m=='torrent-get':return {'torrents':[dict(r) for r in rows]}
        if m in ('torrent-start','torrent-start-now','torrent-stop'):
            for r in rows:r['status']=0 if m=='torrent-stop' else 4
        if m=='torrent-set':
            for r in rows:r.update({k:v for k,v in a.items() if k!='ids'})
        return {}

class TransferTests(unittest.TestCase):
    def test_disk_recovery_restarts_only_automatically_paused_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rpc=RPC(root);up=[True]
            def disk():
                if not up[0]:raise DiskUnavailable('disk_unreadable')
                return root
            c=MediaController(root/'db',rpc,disk)
            c.store.write_state('managed',{'a'*40:{'destination':str(root/'Movies')},'b'*40:{'destination':str(root/'Movies'),'manual_pause':True}})
            with patch.object(c,'_capacity',return_value=None):
                up[0]=False;c.guard_disk()
                self.assertEqual(rpc.rows[0]['status'],0)
                self.assertEqual(c.store.read_state('managed')['a'*40].get('system_pause'),'disk_unavailable')
                up[0]=True;c.guard_disk()
                self.assertEqual(rpc.rows[0]['status'],0,'Require two healthy observations')
                c.guard_disk()
                self.assertEqual(rpc.rows[0]['status'],4)
                self.assertEqual(rpc.rows[1]['status'],0,'Never undo explicit pause')

    def test_torrent_bandwidth_priority_does_not_change_other_films_or_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rpc=RPC(root);c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'a'*40:{'destination':str(root/'Movies')}})
            c.command('prio',{'action':'bandwidth_priority','hash':'a'*40,'priority':1})
            self.assertEqual(rpc.rows[0]['bandwidthPriority'],1)
            self.assertEqual(rpc.rows[1]['bandwidthPriority'],0)
            self.assertEqual(rpc.rows[0]['status'],4)
            with self.assertRaises(ValueError):c.command('bad',{'action':'bandwidth_priority','hash':'a'*40,'priority':10})

    def test_priority_clicks_cycle_once_per_job_even_when_queued_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rpc=RPC(root);c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'a'*40:{'destination':str(root/'Movies')}})
            payload={'action':'bandwidth_priority','hash':'a'*40,'cycle':True}
            for job,wanted in [('one',1),('two',1),('three',-1),('four',0)]:
                c.command(job,payload);self.assertEqual(rpc.rows[0]['bandwidthPriority'],wanted)
                c.command(job,payload);self.assertEqual(rpc.rows[0]['bandwidthPriority'],wanted)
