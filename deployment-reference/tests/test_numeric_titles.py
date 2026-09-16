import tempfile
import unittest
from bot.release_matching import rejection_reason
from bot.search import SearchFlow, rank_releases
from bot.dialog import Dialog
from bot.search_sessions import SearchSessions
from test_multifilm import Telegram

BLADE={'title':'Бегущий по лезвию 2049','original_title':'Blade Runner 2049','year':2017,'kind':'movie'}
CHILDREN={'title':'Дитя человеческое','original_title':'Children of Men','year':2006,'kind':'movie'}
def release(media, year=None):
 return {'title':media['title']+' / '+media['original_title']+' ('+str(year or media['year'])+') BDRip 1080p', 'seeders':50,'size':1024**3}

class NumericTitleTests(unittest.TestCase):
 def test_real_tracker_title_with_bracketed_metadata(self):
  row={'title':'Бегущий по лезвию 2049 / Blade Runner 2049 [2017, США, Великобритания, Венгрия, Канада, фантастика, триллер, драма, детектив, HEVC, BDRip 1080p, HDR10] Dub + Original (Eng) + )','seeders':25}
  self.assertEqual(rank_releases([row],BLADE),[row])

 def test_numeric_titles_survive_ranking(self):
  for media in [BLADE,{'title':'1917','original_title':'1917','year':2019,'kind':'movie'}, {'title':'2001: Космическая одиссея','original_title':'2001: A Space Odyssey','year':1968,'kind':'movie'}, {'title':'2012','original_title':'2012','year':2009,'kind':'movie'}]:
   with self.subTest(media=media):self.assertTrue(rank_releases([release(media)],media))

 def test_title_number_cannot_substitute_for_production_year(self):
  media={'title':'1917','original_title':'1917','year':1917,'kind':'movie'}
  self.assertEqual(rejection_reason(release(media,2019),media),'different_year')

 def test_wrong_film_year_and_unseeded_still_rejected(self):
  self.assertIsNotNone(rejection_reason(release(CHILDREN),BLADE))
  self.assertIsNotNone(rejection_reason(release(BLADE,1982),BLADE))
  self.assertIsNotNone(rejection_reason({**release(BLADE),'seeders':0},BLADE))
  original={'title':'Бегущий по лезвию','original_title':'Blade Runner','year':1982,'kind':'movie'}
  self.assertIsNotNone(rejection_reason(release(BLADE),original))

 def test_two_film_requests_keep_their_own_results_on_retry(self):
  class Resolver:
   def identify(self,text,context):return {'candidates':[BLADE if text=='blade' else CHILDREN]}
  class Indexer:
   fail=True
   def search(self,q):
    media=BLADE if '2049' in q else CHILDREN
    return [] if self.fail and media is BLADE else [release(media)]
  with tempfile.TemporaryDirectory() as tmp:
   indexer=Indexer();d=Dialog(tmp,Telegram(),'owner','',lambda:{},search=SearchFlow(Resolver(),indexer))
   d.search(10,10,'blade',d,message_id=1);blade=d.jobs.read_state('search:10')['nonce']
   d.search.choose(10,10,'media',blade,0,d)
   d.search(10,10,'children',d,message_id=2);children=d.jobs.read_state('search:10')['nonce']
   d.search.choose(10,10,'media',children,0,d)
   children_state=d.jobs.read_state('search:10')
   self.assertEqual(children_state['selected'],CHILDREN)
   indexer.fail=False
   d.search.choose(10,10,'media',blade,0,d)
   blade_state=d.jobs.read_state('search:10')
   self.assertEqual(blade_state['stage'],'release')
   self.assertEqual(blade_state['selected'],BLADE)
   self.assertTrue(all('2049' in r['title'] for r in blade_state['releases']))
   self.assertNotEqual(blade_state['thread_id'],children_state['thread_id'])
   self.assertEqual(SearchSessions(d.jobs,10).load(children_state['thread_id']),children_state)

if __name__=='__main__':unittest.main()
