import tempfile,threading,time,unittest
from unittest.mock import patch
from bot.inbox import Inbox
from bot.providers import Prowlarr,ProviderError
from bot.search import SearchFlow
from bot.search_sessions import SearchSessions
from bot.dialog import Dialog
from test_multifilm import Telegram
from test_inbox import update

class IndependentSearchTests(unittest.TestCase):
 def test_release_search_does_not_block_new_title_or_other_release_download(self):
  started=threading.Event();release=threading.Event();title=threading.Event();download=threading.Event()
  def handle(row):
   if row['update_id']==1:started.set();release.wait(2)
   elif row['update_id']==2:title.set()
   else:download.set()
  with tempfile.TemporaryDirectory() as tmp:
   inbox=Inbox(tmp,handle)
   for row in [update(1,callback='media:aaaaaaaaaa:0'),update(2,text='Another film'),update(3,callback='release:bbbbbbbbbb:0')]:inbox.enqueue(row)
   inbox.pump()
   try:self.assertTrue(started.wait(1));self.assertTrue(title.wait(.3));self.assertTrue(download.wait(.3))
   finally:release.set();inbox.wait_idle(2);inbox.stop()

 def test_empty_search_during_indexer_backoff_is_failure_not_no_results(self):
  def request(url,*a,**kw):
   if url.endswith('/indexer'):return [{'id':1,'enable':True}]
   if url.endswith('/indexerstatus'):return [{'indexerId':1,'disabledTill':'2099-01-01T00:00:00Z'}]
   return []
  with patch('bot.providers.request_json',side_effect=request):
   with self.assertRaises(ProviderError):Prowlarr('test').search('Film')

 def test_provider_failure_during_search_does_not_cache_empty_response(self):
  calls=[]
  def request(url,*a,**kw):
   calls.append(url)
   if url.endswith('/indexer'):return [{'id':1,'enable':True}]
   if url.endswith('/indexerstatus'):
    return [] if sum('/search?' in x for x in calls)==0 else [{'indexerId':1,'disabledTill':'2099-01-01T00:00:00Z'}]
   return []
  api=Prowlarr('test')
  with patch('bot.providers.request_json',side_effect=request):
   with self.assertRaises(ProviderError):api.search('Film')
  self.assertEqual(api._cache,{})

 def test_five_independent_menus_survive_two_half_day_waits_and_restart(self):
  class Resolver:
   def identify(self,text,context):return {'candidates':[{'title':text,'year':2000,'kind':'movie'}]}
  class Indexer:
   def search(self,q):return [{'title':q+' (2000) 1080p','seeders':20,'size':1024**3}]
   def download(self,row):return {'magnet':'magnet:?xt=urn:btih:'+format(int(row['title'][4]),'040x')}
  with tempfile.TemporaryDirectory() as tmp,patch('bot.search.time.time',return_value=1000) as clock:
   tg=Telegram();d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()));buttons=[]
   for i in range(5):
    d.search(10,10,'Film'+str(i),d,message_id=i+1)
    buttons.append(d.jobs.read_state('search:10')['nonce'])
   clock.return_value=1000+12*3600;releases=[]
   for nonce in reversed(buttons):
    d.search.choose(10,10,'media',nonce,0,d)
    releases.append(d.jobs.read_state('search:10')['nonce'])
   clock.return_value=1000+25*3600
   d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
   for nonce in releases:d.search.choose(10,10,'release',nonce,0,d)
   self.assertEqual(len(d.jobs.pending()),5)
   for nonce in releases:d.search.choose(10,10,'release',nonce,0,d)
   self.assertEqual(len(d.jobs.pending()),5)

 def test_retry_updates_same_named_card(self):
  class Resolver:
   def identify(self,*a):return {'candidates':[{'title':'Film','kind':'movie'}]}
  class Indexer:
   def search(self,*a):raise ProviderError('temporary')
  with tempfile.TemporaryDirectory() as tmp:
   tg=Telegram();d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
   d.search(10,10,'Film',d);nonce=d.jobs.read_state('search:10')['nonce']
   d.search.choose(10,10,'media',nonce,0,d);first=d.jobs.read_state('search:10').get('choice_message_id')
   d.search.choose(10,10,'media',nonce,0,d);second=d.jobs.read_state('search:10').get('choice_message_id')
   self.assertEqual(first,second)
   self.assertIn('Film',tg.calls[-1][1]['text'])
