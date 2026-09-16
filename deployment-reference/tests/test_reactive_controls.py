import tempfile,unittest
from pathlib import Path
from bot.dialog import Dialog
from bot.download_dashboard import publish
from mac_agent.media import MediaController
from test_transfer_controls import RPC
class Telegram:
 def __init__(self):self.calls=[]
 def call(self,method,**payload):self.calls.append((method,payload));return {'message_id':3}
class ReactiveTests(unittest.TestCase):
 def test_burst_shows_desired_mode_before_mac_and_sends_only_latest(self):
  with tempfile.TemporaryDirectory() as tmp:
   tg=Telegram();d=Dialog(tmp,tg,'','',lambda:{})
   h='a'*40;d.jobs.write_state('transfer:1:'+h,dict(uid=1,hash=h,name='Film',active=True,priority=-1,created=1,text='0 из 100'))
   d.jobs.write_state('download-dashboard:1',dict(message_id=3))
   modes=[]
   for i in range(10):
    d.callback(1,1,'priority:'+h,'click:'+str(i))
    modes.append(d.jobs.read_state('priority-desired:1:'+h)['mode'])
   self.assertEqual(modes,[0,1,2,-1,0,1,2,-1,0,1])
   self.assertEqual(len(d.jobs.pending_priorities()),1)
   self.assertEqual(d.jobs.pending_priorities()[0]['payload']['mode'],1)
   self.assertEqual(tg.calls,[],'click handler must not wait for Telegram or Mac')
   publish(d,1,100,cleanup=False,wait=False,controls_only=True)
   self.assertEqual(tg.calls[-1][0],'editMessageReplyMarkup')
   button=tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['text']
   self.assertIn('🔴',button);self.assertIn('⏳',button)
   d.callback(1,1,'priority:'+h,'click:9')
   self.assertEqual(d.jobs.read_state('priority-desired:1:'+h)['mode'],1)
 def test_absolute_target_is_idempotent_and_pause_resumes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rpc=RPC(root);c=MediaController(root/'agent',rpc,lambda:root)
   c.store.write_state('managed',{'a'*40:{}})
   for job,mode in [('high',1),('pause',2),('low',-1),('again',-1)]:
    r=c.command(job,{'action':'bandwidth_priority','hash':'a'*40,'mode':mode})
    self.assertTrue(r['ok']);self.assertEqual(rpc.rows[0]['status']==0,mode==2)
    if mode!=2:self.assertEqual(rpc.rows[0]['bandwidthPriority'],mode)
