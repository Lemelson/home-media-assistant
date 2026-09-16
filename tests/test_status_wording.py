import unittest,tempfile
from bot.dialog import Dialog
from bot.progress import ProgressMonitor
class Telegram:
 def __init__(self):self.calls=[]
 def call(self,method,**payload):self.calls.append((method,payload));return {'message_id':len(self.calls)}
class StatusWordingTests(unittest.TestCase):
 def test_no_rpc_response_does_not_claim_paused_or_missing_disk(self):
  with tempfile.TemporaryDirectory() as d:
   tg=Telegram()
   def failed():raise RuntimeError('timeout')
   dialog=Dialog(d,tg,'','',failed);monitor=ProgressMonitor(dialog)
   monitor.register(1,{'hash':'a'*40,'name':'Film'},100);monitor.tick(160)
   text=tg.calls[-1][1]['text']
   self.assertIn('Служба загрузок не отвечает',text)
   self.assertNotIn('<b>⏸',text);self.assertNotIn('media disk недоступен',text)
 def test_uncertain_disk_probe_with_live_rpc_shows_real_progress(self):
  with tempfile.TemporaryDirectory() as d:
   tg=Telegram();t={'hashString':'a'*40,'name':'Film','status':4,'percentDone':.5,'totalSize':1000,'leftUntilDone':500,'rateDownload':100}
   dialog=Dialog(d,tg,'','',lambda:{'disk_ok':None,'disk_state':'checking','torrents':[t]})
   monitor=ProgressMonitor(dialog);monitor.register(1,{'hash':'a'*40,'name':'Film'},100);monitor.tick(160)
   self.assertIn('50.0%',tg.calls[-1][1]['text'])
 def test_unavailable_status_preserves_last_progress_and_size(self):
  with tempfile.TemporaryDirectory() as d:
   tg=Telegram();live=[True]
   def status():
    if not live[0]:raise RuntimeError('timeout')
    return {'disk_ok':True,'torrents':[{'hashString':'a'*40,'name':'Film','status':4,'percentDone':.5,'totalSize':1000,'leftUntilDone':500,'rateDownload':100}]}
   dialog=Dialog(d,tg,'','',status);monitor=ProgressMonitor(dialog)
   monitor.register(1,{'hash':'a'*40,'name':'Film'},100);monitor.tick(160);live[0]=False;monitor.tick(190)
   text=tg.calls[-1][1]['text'];self.assertIn('50.0%',text);self.assertIn('Последние полученные данные',text)
