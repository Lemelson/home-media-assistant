import io,json,threading,time,unittest
from unittest.mock import patch
from bot.transport import MediaAPI

class StatusContentionTests(unittest.TestCase):
 def test_slow_shared_refresh_returns_fresh_result_to_all_readers(self):
  entered=threading.Event();result=[];errors=[]
  class API(MediaAPI):
   calls=0
   def request(self,*args):
    self.calls+=1;entered.set();time.sleep(1.2);return {'torrents':[{'percentDone':.6}]}
  api=API('test')
  def read():
   try:result.append(api.status())
   except Exception as e:errors.append(type(e).__name__)
  a=threading.Thread(target=read);a.start();self.assertTrue(entered.wait(1))
  b=threading.Thread(target=read);b.start();a.join(3);b.join(3)
  self.assertEqual(errors,[]);self.assertEqual(len(result),2);self.assertEqual(api.calls,1)


 def test_http_status_budget_covers_agent_read_and_disk_check(self):
  class Response(io.BytesIO):
   def __enter__(self):return self
   def __exit__(self,*a):self.close()
  with patch('bot.transport.urllib.request.urlopen',side_effect=lambda *a,**kw:Response(b'{"ok":true}')) as request:
   api=MediaAPI('test');api.request('/status');self.assertEqual(request.call_args.kwargs['timeout'],35)
   api.request('/command',{});self.assertEqual(request.call_args.kwargs['timeout'],20)
