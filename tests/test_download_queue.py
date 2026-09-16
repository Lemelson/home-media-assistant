import tempfile
import unittest
from pathlib import Path
from mac_agent.media import MediaController
from test_transfer_controls import RPC

class QueueTests(unittest.TestCase):
    def test_independent_priorities_cycle_pause_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rpc=RPC(root)
            rpc.rows=[dict(rpc.rows[0],hashString=h*40,status=4) for h in 'abcde']
            c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{h*40:{} for h in 'abcde'})
            c.reconcile_queue()
            self.assertEqual(sum(r['status']==4 for r in rpc.rows),5)
            for h in 'ab':c.command('high'+h,{'action':'bandwidth_priority','hash':h*40,'priority':1})
            self.assertEqual(sum(r['bandwidthPriority']==1 for r in rpc.rows),2)
            p={'action':'bandwidth_priority','hash':'e'*40,'cycle':True}
            for job,wanted,paused in [('high',1,False),('pause',1,True),('low',-1,False),('medium',0,False)]:
                c.command(job,p);c.command(job,p)
                self.assertEqual(rpc.rows[4]['bandwidthPriority'],wanted)
                self.assertEqual(rpc.rows[4]['status']==0,paused)
                self.assertEqual([r['bandwidthPriority'] for r in rpc.rows[:2]],[1,1])
            c.command('manual',{'action':'pause','hash':'a'*40});c.reconcile_queue()
            self.assertEqual(rpc.rows[0]['status'],0)

    def test_does_not_restart_external_pause_or_touch_unmanaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rpc=RPC(root);c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'b'*40:{}})
            c.reconcile_queue()
            self.assertEqual([r['status'] for r in rpc.rows],[4,0])
