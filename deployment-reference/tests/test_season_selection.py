import unittest
from bot.seasons import parse_seasons, title_seasons, select_files
class SeasonTests(unittest.TestCase):
 def test_ranges_lists_words(self):
  for text,expected in [('1-3',[1,2,3]),('1,5',[1,5]),('2, 4',[2,4]),('2–4',[2,3,4]),('первый, третий',[1,3]),('сезоны 1 и 3',[1,3]),('Сезон 2',[2])]:
   self.assertEqual(parse_seasons(text),expected,text)
  for text in ['Черное зеркало','3-1','0','1-100','2004','1, xyz']:
   self.assertIsNone(parse_seasons(text),text)
 def test_release_seasons(self):
  for title in ['Show S01-S03 1080p','Show Сезоны: 1-3','Show [Сезон 1-3 из 3]']:
   self.assertEqual(title_seasons(title),{1,2,3})
 def test_only_requested_files_and_ignore_sample(self):
  files=[{'name':n,'length':100} for n in ['Show/S01E01.mkv','Show/Season 02/01.mkv','Show/Сезон 3/02.mkv','Show/S01E02.sample.mkv','Show/cover.jpg']]
  self.assertEqual(select_files(files,[1,3]),[0,2])
 def test_single_season_fallback_only_if_release_explicitly_single(self):
  files=[{'name':'Show/01.mkv','length':100},{'name':'Show/02.mkv','length':100}]
  self.assertEqual(select_files(files,[2],release_name='Show Сезон 2'),[0,1])
  with self.assertRaises(ValueError):select_files(files,[2],release_name='Show Сезоны 1-3')
 def test_missing_or_conflicting_seasons_fail_closed(self):
  for files in [[{'name':'Show/S01E01.mkv'}],[{'name':'Show/Season 1/S02E01.mkv'}]]:
   with self.assertRaises(ValueError):select_files(files,[2])

class SeasonFlowTests(unittest.TestCase):
 def test_range_creates_three_independent_menus_without_resolver(self):
  import tempfile,time
  from bot.search import SearchFlow
  from bot.search_sessions import SearchSessions
  from bot.dialog import Dialog
  from test_multifilm import Telegram
  class Resolver:
   def identify(self,*args):raise AssertionError('Season reply must not identify a new film')
  class Indexer:
   def search(self,q):return [{'title':'Black Mirror Сезоны 1-3 720p','seeders':50,'size':30*1024**3,'guid':'pack'}]
  with tempfile.TemporaryDirectory() as tmp:
   tg=Telegram(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
   sessions=SearchSessions(d.jobs,10)
   sessions.save({'thread_id':'a'*10,'nonce':'b'*10,'stage':'season','selected':{'title':'Black Mirror','kind':'show'},'expires':time.time()+1000})
   d.search(10,10,'1-3',d)
   states=sessions.active()
   self.assertEqual(len(states),3)
   self.assertEqual({s['selected']['season'] for s in states},{1,2,3})
   self.assertTrue(all(s['stage']=='release' for s in states))
   self.assertEqual(len({s['nonce'] for s in states}),3)

class SelectedFilesTests(unittest.TestCase):
 def test_pack_root_does_not_override_specific_file_season(self):
  self.assertEqual(select_files([{'name':'Show Сезоны 1-3/Season 2/01.mkv'}],[2]),[0])
 def test_controller_sets_wanted_before_start_and_preserves_other_seasons_on_duplicate(self):
  import tempfile,base64
  from pathlib import Path
  from mac_agent.media import MediaController
  class RPC:
   def __init__(self):
    self.calls=[];self.added=False
    self.row={'hashString':'a'*40,'name':'Show Сезоны 1-3','totalSize':300,'leftUntilDone':300,'sizeWhenDone':300,'status':0,
      'files':[{'name':f'Show/S0{i}E01.mkv','length':100,'bytesCompleted':0} for i in [1,2,3]],'fileStats':[{'wanted':True}]*3}
   def call(self,method,args=None):
    self.calls.append((method,args))
    if method=='torrent-add':
     key='torrent-duplicate' if self.added else 'torrent-added';self.added=True;return {key:self.row}
    if method=='torrent-get':return {'torrents':[self.row]}
    if method=='torrent-set' and 'files-wanted' in args:
     self.row['fileStats']=[{'wanted':i in args['files-wanted']} for i in range(3)]
     self.row['sizeWhenDone']=self.row['leftUntilDone']=100*len(args['files-wanted'])
    return {}
  with tempfile.TemporaryDirectory() as tmp:
   rpc=RPC();c=MediaController(Path(tmp)/'db',rpc,lambda:Path(tmp))
   payload={'action':'add','kind':'show','season':2,'name':'Show Сезоны 1-3','metainfo':base64.b64encode(b'd4:infod4:name4:testee').decode()}
   self.assertTrue(c.command('one',payload)['ok'])
   selects=[a for m,a in rpc.calls if m=='torrent-set' and 'files-wanted' in a]
   self.assertEqual(selects[0]['files-wanted'],[1]);self.assertEqual(selects[0]['files-unwanted'],[0,2])
   self.assertEqual(c.store.read_state('managed')['a'*40]['reserved_bytes'],100)
   self.assertTrue(c.command('two',{**payload,'season':3})['ok'])
   self.assertEqual([a['files-wanted'] for m,a in rpc.calls if m=='torrent-set' and 'files-wanted' in a][-1],[1,2])
   set_index=next(i for i,(m,a) in enumerate(rpc.calls) if m=='torrent-set' and 'files-wanted' in a)
   start_index=next(i for i,(m,a) in enumerate(rpc.calls) if m.startswith('torrent-start'))
   self.assertLess(set_index,start_index)

class SelectedNamingTests(unittest.TestCase):
 def test_naming_view_ignores_unrequested_incomplete_season(self):
  from bot.seasons import selected_torrent
  from bot.naming import make_plan
  row={'name':'Show','files':[{'name':'Show/S01E01.mkv','length':10,'bytesCompleted':10}, {'name':'Show/S02E01.mkv','length':10,'bytesCompleted':0}]}
  limited=selected_torrent(row,{'selected_file_indices':[0]})
  plan=make_plan(limited,{'title':'Show','kind':'show','year':2020})
  self.assertFalse(any('S02' in x['path'] for x in plan))
  self.assertEqual(len(limited['files']),1)

class SeasonSearchCoverageTests(unittest.TestCase):
 def test_reverse_season_label(self):
  self.assertEqual(title_seasons('Шерлок / Sherlock [1 Сезон][3 из 3][2010, HDTV]'),{1})
 def test_supplemental_queries_for_missing_old_season(self):
  from bot.release_matching import additional_search_queries
  queries=additional_search_queries({'title':'Шерлок','original_title':'Sherlock','kind':'show','year':2010,'season':1})
  self.assertIn('Sherlock 2010',queries)
  self.assertIn('Sherlock S01',queries)
  self.assertIn('Шерлок сезон 1',queries)
