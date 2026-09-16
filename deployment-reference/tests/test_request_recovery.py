import tempfile,unittest
from pathlib import Path
from bot.search import SearchFlow
from bot.dialog import Dialog
from tests.test_dialog import Telegram
class RestartTests(unittest.TestCase):
 def test_interrupted_lookup_is_retried_then_deduplicated(self):
  class Interrupted(BaseException):pass
  class Resolver:
   calls=0
   def identify(self,text,context):
    self.calls+=1
    if self.calls==1:raise Interrupted()
    return {'reply':'Найден фильм','candidates':[{'title':'Как выйти замуж за миллионера','year':1953,'kind':'movie'}]}
  with tempfile.TemporaryDirectory() as tmp:
   resolver=Resolver();flow=SearchFlow(resolver,None);d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
   with self.assertRaises(Interrupted):flow(10,10,'Как выйти замуж за миллионера',d,source='tg:123',receipt_id=5)
   flow=SearchFlow(resolver,None)
   flow(10,10,'Как выйти замуж за миллионера',d,source='tg:123',receipt_id=5)
   self.assertEqual(resolver.calls,2)
   self.assertEqual(d.jobs.read_state('search:10')['candidates'][0]['year'],1953)
   flow(10,10,'Как выйти замуж за миллионера',d,source='tg:123',receipt_id=5)
   self.assertEqual(resolver.calls,2)
