import tempfile,unittest
from bot.dialog import Dialog
from bot.progress import ProgressMonitor
class TG:
 def call(self,*a,**k):return {'message_id':1}
class Tests(unittest.TestCase):
 def test_short_failure_is_delay_and_keeps_model_long_failure_is_outage(self):
  with tempfile.TemporaryDirectory() as d:
   def fail():raise RuntimeError('status_refresh_pending')
   dialog=Dialog(d,TG(),'','',fail);monitor=ProgressMonitor(dialog);monitor.register(1,{'hash':'a'*40,'name':'Film'},now=100)
   key='transfer:1:'+'a'*40;s=dialog.jobs.read_state(key);s['eta_model']={'rate':123};s['samples']=[[100,50]];dialog.jobs.write_state(key,s)
   monitor.tick(now=115);s=dialog.jobs.read_state(key)
   self.assertIn('Обновление статуса задерживается',s['text']);self.assertNotIn('Служба загрузок не отвечает',s['text']);self.assertEqual(s['eta_model']['rate'],123)
   monitor.tick(now=145);monitor.tick(now=175);s=dialog.jobs.read_state(key)
   self.assertIn('Служба загрузок не отвечает',s['text']);self.assertNotIn('eta_model',s)

class VerificationTests(unittest.TestCase):
 def test_active_verification_overrides_previous_corruption_error(self):
  from bot.progress import progress_text
  text,complete=progress_text({'name':'Film'},{'status':2,'errorString':'Please Verify Local Data! Piece #5557 is corrupt.','percentDone':.51,'recheckProgress':.03,'totalSize':1000,'leftUntilDone':490},100)
  self.assertIn('Проверка файлов',text);self.assertNotIn('⚠️ Ошибка загрузки',text);self.assertFalse(complete)
