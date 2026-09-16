import tempfile,unittest
from pathlib import Path
from mac_agent.media import MediaController
from test_transfer_controls import RPC
class AbsoluteModes(unittest.TestCase):
 def test_absolute_target_is_idempotent_and_pause_resumes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rpc=RPC(root);c=MediaController(root/'agent',rpc,lambda:root)
   c.store.write_state('managed',{'a'*40:{}})
   for job,mode in [('high',1),('pause',2),('low',-1),('again',-1)]:
    r=c.command(job,{'action':'bandwidth_priority','hash':'a'*40,'mode':mode})
    self.assertTrue(r['ok']);self.assertEqual(rpc.rows[0]['status']==0,mode==2)
    if mode!=2:self.assertEqual(rpc.rows[0]['bandwidthPriority'],mode)
