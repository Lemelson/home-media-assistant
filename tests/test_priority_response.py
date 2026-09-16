import io,json,tempfile,threading,unittest,urllib.error
from unittest.mock import patch
from bot.dialog import Dialog
from bot.download_dashboard import PUBLISH_LOCK,publish
from bot.transport import TelegramAPI,APIError
from test_progress_rotation import Chat
class ResponseTests(unittest.TestCase):
 def test_priority_is_enqueued_without_waiting_for_dashboard_lock(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Dialog(tmp,Chat(),'','',lambda:{})
   ready=threading.Event();release=threading.Event()
   def lock():
    with PUBLISH_LOCK:ready.set();release.wait(3)
   t=threading.Thread(target=lock);t.start();ready.wait(1)
   done=threading.Event()
   def click():d.callback(1,1,'priority:'+'a'*40,'tg:test');done.set()
   worker=threading.Thread(target=click);worker.start()
   try:
    self.assertTrue(done.wait(.5),'callback must not wait for rendering or cleanup')
    self.assertEqual(len(d.jobs.pending_priorities()),1)
   finally:release.set();t.join();worker.join()
 def test_missing_deleted_message_is_classified_without_token(self):
  error=urllib.error.HTTPError('secret-url',400,'bad',{},io.BytesIO(json.dumps({'description':'Bad Request: message to delete not found'}).encode()))
  with patch('urllib.request.urlopen',side_effect=error):
   with self.assertRaisesRegex(APIError,'^message to delete not found$'):TelegramAPI('private').call('deleteMessage',chat_id=1,message_id=3)
 def test_shared_old_message_deleted_once_and_not_retried(self):
  class Client(Chat):
   deleted=[]
   def call(self,method,**p):
    if method=='deleteMessage':self.deleted.append(p['message_id']);raise APIError('message to delete not found')
    return super().call(method,**p)
  with tempfile.TemporaryDirectory() as tmp:
   chat=Client();d=Dialog(tmp,chat,'','',lambda:{})
   for h in 'abc':d.jobs.write_state('transfer:1:'+h,dict(uid=1,hash=h,name=h,active=True,message_id=99,pending_delete=[99]))
   publish(d,1,100);publish(d,1,120)
   self.assertEqual(chat.deleted,[99])
