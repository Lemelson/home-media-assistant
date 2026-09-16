import io,json,tempfile,threading,time,unittest,urllib.error
from unittest.mock import patch
from bot.transport import MediaAPI,TelegramAPI,APIError
class ResilienceTests(unittest.TestCase):
 def test_concurrent_status_reads_share_one_request_and_return_copies(self):
  class API(MediaAPI):
   calls=0
   def request(self,path,payload=None):self.calls+=1;time.sleep(.08);return {'torrents':[{'name':'Film'}]}
  api=API('test');results=[];start=threading.Barrier(6)
  def read():start.wait();results.append(api.status())
  ts=[threading.Thread(target=read) for _ in range(6)]
  for t in ts:t.start()
  for t in ts:t.join(2)
  self.assertEqual(len(results),6);self.assertEqual(api.calls,1)
  results[0]['torrents'][0]['name']='changed';self.assertEqual(api.status()['torrents'][0]['name'],'Film')
 def test_command_invalidates_status_cache(self):
  class API(MediaAPI):
   value=0
   def request(self,path,payload=None):
    if payload:self.value+=1;return {'ok':True}
    return {'value':self.value}
  api=API('test');self.assertEqual(api.status()['value'],0)
  api.command({'id':'1','payload':{'action':'pause'}})
  self.assertEqual(api.status()['value'],1)
 def test_transient_status_failure_is_not_hammered(self):
  class API(MediaAPI):
   calls=0
   def request(self,*a):self.calls+=1;raise APIError('mac_unavailable')
  api=API('test')
  for _ in range(8):
   with self.assertRaises(APIError):api.status()
  self.assertEqual(api.calls,1)
 def test_telegram_rate_limit_waits_without_sleeping_worker(self):
  api=TelegramAPI('secret')
  error=urllib.error.HTTPError('secret-url',429,'rate',{},io.BytesIO(json.dumps({'parameters':{'retry_after':10}}).encode()))
  with patch('urllib.request.urlopen',side_effect=error) as call:
   for _ in range(4):
    with self.assertRaises(APIError):api.call('editMessageText',chat_id=1,message_id=2,text='text')
   self.assertEqual(call.call_count,1)
 def test_slow_read_does_not_hold_command_lock(self):
  entered=threading.Event();release=threading.Event();done=threading.Event()
  class API(MediaAPI):
   def request(self,path,payload=None):
    if path=='/status':entered.set();release.wait(2);return {'value':'old'}
    return {'ok':True}
  api=API('test');reader=threading.Thread(target=api.status);reader.start();entered.wait(1)
  def command():api.command({'id':'x','payload':{}});done.set()
  worker=threading.Thread(target=command);worker.start()
  try:self.assertTrue(done.wait(.2))
  finally:release.set();reader.join();worker.join()
  self.assertIsNone(api._status_cache)
 def test_rate_limit_recovers_after_deadline(self):
  api=TelegramAPI('test');api._retry_after=20
  class Response(io.BytesIO):
   def __enter__(self):return self
   def __exit__(self,*a):self.close()
  with patch('bot.transport.time.monotonic',return_value=21),patch('urllib.request.urlopen',return_value=Response(b'{"ok":true,"result":true}')):
   self.assertTrue(api.call('editMessageText'))
