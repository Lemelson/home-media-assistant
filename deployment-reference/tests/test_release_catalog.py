import unittest
from bot.search import rank_releases,release_button
class CatalogTests(unittest.TestCase):
 def test_keep_all_resolutions_and_sizes_sorted_by_seeders(self):
  media={'title':'Film','kind':'movie','year':2000}
  rows=[{'title':'Film (2000) '+q,'seeders':100-i,'size':(i+1)*1024**3,'categories':[{'id':2000}]} for i,q in enumerate(['720p','2160p','1080i','BluRay','8K','4320p','1920x1080','WEB-DL','1080p','4K'])]
  found=rank_releases(rows,media)
  self.assertEqual([x['title'] for x in found],[x['title'] for x in rows])
 def test_user_quality_names(self):
  for token,label in [('2160p','4К'),('1080i','Full HD'),('1080p','Full HD'),('720p','HD')]:
   self.assertIn(label,release_button(1,{'title':token,'seeders':3,'size':1024**3}))
 def test_actual_uhd_source_rip_is_full_hd(self):
  from bot.release_catalog import quality_key
  self.assertEqual(quality_key({'title':'UHD BDRip 1080p HDR10'}),'fhd')
 def test_pagination_preserves_all_indices_and_size_sort(self):
  from bot.release_catalog import catalog_page
  state={'releases':[{'title':'720p','size':50-i,'seeders':100-i} for i in range(33)]}
  seen=[]
  for page in range(5):seen+=catalog_page({**state,'page':page})[0]
  self.assertEqual(seen,list(range(33)))
  self.assertEqual(catalog_page({**state,'sort':'size'})[0],list(range(32,24,-1)))
 def test_real_general_video_category_not_lost(self):
  row={'title':'Темный рыцарь / The Dark Knight [2008, HybridRip-AVC]','seeders':76,'categories':[{'id':5050},{'id':100807}]}
  self.assertEqual(rank_releases([row],{'title':'Темный рыцарь','original_title':'The Dark Knight','year':2008,'kind':'movie'}),[row])
 def test_same_year_documentary_is_not_feature(self):
  row={'title':'To End All War: Oppenheimer & the Atomic Bomb [2023, WEB-DL 2160p]','seeders':30,'categories':[{'id':2000}]}
  self.assertEqual(rank_releases([row],{'title':'Оппенгеймер','original_title':'Oppenheimer','year':2023,'kind':'movie'}),[])
 def test_theatrical_anime_in_tv_anime_category_is_retained(self):
  m={'title':'Унесенные призраками','original_title':'Spirited Away','year':2001,'kind':'movie'}
  row={'title':'Унесенные призраками / Spirited Away [Movie] [2001, BDRip] [720p]','seeders':75,'categories':[{'id':5070},{'id':101391}]}
  self.assertEqual(rank_releases([row],m),[row])

class CatalogFlowTests(unittest.TestCase):
 def test_page_two_callback_queues_correct_release_after_restart(self):
  import tempfile
  from bot.dialog import Dialog
  from bot.search import SearchFlow
  from test_multifilm import Telegram
  class Resolver:
   def identify(self,*a):return {'candidates':[{'title':'Film','kind':'movie','year':2000}]}
  class Indexer:
   def search(self,q):return [{'title':'Film (2000) 720p '+str(i),'guid':str(i),'seeders':100-i,'size':(i+1)*1024**3} for i in range(30)]
   def download(self,row):return {'magnet':'magnet:?xt=urn:btih:'+format(int(row['guid']),'040x')}
  with tempfile.TemporaryDirectory() as tmp:
   tg=Telegram();d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
   d.search(10,10,'Film',d);s=d.jobs.read_state('search:10');d.search.choose(10,10,'media',s['nonce'],0,d)
   s=d.jobs.read_state('search:10');nonce=s['nonce'];message=s['choice_message_id']
   d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
   d.callback(10,10,'catalog:'+nonce+':p1','page')
   self.assertEqual(d.jobs.read_state('search:10')['choice_message_id'],message)
   self.assertIn('страница 2/4',tg.calls[-1][1]['text'])
   d.callback(10,10,'release:'+nonce+':12','pick')
   self.assertEqual(d.jobs.pending()[0]['payload']['name'],'Film (2000) 720p 12')
 def test_page_and_download_callbacks_share_ordered_lane(self):
  from bot.inbox import Inbox
  def update(data):return {'callback_query':{'from':{'id':10},'message':{'chat':{'id':10}},'data':data}}
  self.assertEqual(Inbox._routing(update('catalog:aaaaaaaaaa:p1'))[0],Inbox._routing(update('release:aaaaaaaaaa:12'))[0])
