import unittest
from bot.naming import make_plan

class NamingTests(unittest.TestCase):
 def test_obfuscated_movie_uses_selected_identity(self):
  row={'hashString':'a'*40,'name':'hns-mog.mkv','files':[{'name':'hns-mog.mkv','length':100,'bytesCompleted':100}]}
  plan=make_plan(row,{'kind':'movie','original_title':'Memoirs of a Geisha','year':2005})
  self.assertEqual(plan,[{'path':'hns-mog.mkv','name':'Memoirs of a Geisha (2005).mkv'}])
 def test_incomplete_and_ambiguous_movies_are_untouched(self):
  identity={'kind':'movie','title':'Film','year':2000}
  for files in ([{'name':'a.mkv','length':100,'bytesCompleted':50}], [{'name':x+'.mkv','length':100,'bytesCompleted':100} for x in ('a','b')]):
   with self.assertRaises(ValueError):make_plan({'name':'pack','files':files},identity)
 def test_multiple_seasons_preserve_episode_numbers(self):
  files=[{'name':'pack/'+name,'length':100,'bytesCompleted':100} for name in ('season1/a.S01E02.mkv','season2/b.S02E03.mkv')]
  plan=make_plan({'name':'pack','files':files},{'kind':'show','title':'Example','year':2000})
  self.assertIn({'path':'pack/season1/a.S01E02.mkv','name':'Example (2000) - S01E02.mkv'},plan)
  self.assertIn({'path':'pack/season2/b.S02E03.mkv','name':'Example (2000) - S02E03.mkv'},plan)
 def test_unknown_episode_and_path_escape_rejected(self):
  for name in ('pack/unknown.mkv','../evil.S01E01.mkv'):
   with self.assertRaises(ValueError):make_plan({'name':'pack','files':[{'name':name,'length':100,'bytesCompleted':100}]},{'kind':'show','title':'Example','year':2000})

class ApplyTests(unittest.TestCase):
 def test_collision_preflight_prevents_any_rename(self):
  import tempfile
  from pathlib import Path
  from mac_agent.naming import apply_plan
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();d=str(root);(root/'a.mkv').write_bytes(b'abc');(root/'Film (2000).mkv').write_bytes(b'xyz')
   class RPC:
    def call(self,*a):raise AssertionError('must not mutate')
   row={'hashString':'a'*40,'name':'a.mkv','downloadDir':d,'files':[{'name':'a.mkv','length':3,'bytesCompleted':3}]}
   with self.assertRaisesRegex(ValueError,'target_exists'):apply_plan(RPC(),row,{'kind':'movie','title':'Film','year':2000},lambda *a:None)
   self.assertEqual((root/'a.mkv').read_bytes(),b'abc')

class WorkerTests(unittest.TestCase):
 def test_matching_requires_identity_and_every_file(self):
  from bot.naming_worker import is_matched
  row={'downloadDir':'/media','files':[{'name':'a.mkv'},{'name':'b.mkv'}]}
  identity={'kind':'movie','title':'Example','year':2000}
  item={'kind':'show','title':'Example','year':'2000','guid':'plex://show/123','files':['/media/a.mkv']}
  self.assertFalse(is_matched(row,identity,[item]))
  movie={'downloadDir':'/media','files':[{'name':'a.mkv'}]}
  self.assertFalse(is_matched(movie,identity,[item]))
  self.assertTrue(is_matched(movie,identity,[{**item,'kind':'movie','guid':'plex://movie/123'}]))
  self.assertFalse(is_matched(movie,{**identity,'year':2001},[item]))
 def test_two_failed_model_attempts_stop(self):
  import tempfile
  from bot.jobs import JobStore
  from bot.naming_worker import NamingWorker
  class Resolver:
   calls=0
   def identify(self,*args):self.calls+=1;raise RuntimeError('offline')
  class API:
   def command(self,job):return {'torrents':[{'hashString':'a'*40,'name':'a.mkv','percentDone':1,'files':[{'name':'a.mkv','length':3,'bytesCompleted':3}],'downloadDir':'/media'}],'plex':[]}
  with tempfile.TemporaryDirectory() as d:
   store=JobStore(d+'/db');store.write_state('film:'+'a'*40,{'media':{'kind':'movie','title':'Film','year':None},'fallback':'Film 2000'})
   resolver=Resolver();worker=NamingWorker(store,API(),resolver)
   for now in (1000,1300,1600,1900):worker.step(now)
   self.assertEqual(resolver.calls,2)
   self.assertEqual(store.read_state('naming:'+'a'*40)['phase'],'left_unchanged')

class SafetyTests(unittest.TestCase):
 def test_season_directory_collision_preflight(self):
  import tempfile
  from pathlib import Path
  from mac_agent.naming import apply_plan
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();d=str(root)
   files=[]
   for name in ('pack/one/a.S01E01.mkv','pack/two/b.S01E02.mkv'):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'abc')
    files.append({'name':name,'length':3,'bytesCompleted':3})
   class RPC:
    def call(self,*args):raise AssertionError('no mutations on collision')
   with self.assertRaisesRegex(ValueError,'name_collision'):apply_plan(RPC(),{'name':'pack','files':files,'downloadDir':d},{'kind':'show','title':'Show','year':2000},lambda *a:None)
 def test_rename_preserves_sidecar_contents_and_is_idempotent(self):
  import tempfile
  from pathlib import Path
  from mac_agent.naming import apply_plan
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();d=str(root);files=[]
   for name,content in [('pack/odd.mkv',b'video'),('pack/odd.en.srt',b'subtitles')]:
    p=root/name;p.parent.mkdir(exist_ok=True);p.write_bytes(content);files.append({'name':name,'length':len(content),'bytesCompleted':len(content)})
   t={'hashString':'a'*40,'name':'pack','files':files,'downloadDir':d}
   class RPC:
    def call(self,method,args):
     self.assert_method=method;old=args['path'];new=str(Path(old).parent/args['name'])
     (root/old).rename(root/new)
     for f in files:
      if f['name']==old or f['name'].startswith(old+'/'):f['name']=new+f['name'][len(old):]
     if t['name']==old:t['name']=new
   rpc=RPC();identity={'kind':'movie','title':'Movie','year':2001}
   apply_plan(rpc,t,identity,lambda *a:None)
   self.assertEqual((root/'Movie (2001)/Movie (2001).en.srt').read_bytes(),b'subtitles')
   self.assertEqual((root/'Movie (2001)/Movie (2001).mkv').read_bytes(),b'video')
   self.assertEqual(apply_plan(rpc,t,identity,lambda *a:None)['operations'],[])

class RussianNamingTests(unittest.TestCase):
 def test_russian_release_title_is_preferred_to_original(self):
  row={'name':'old.mkv','files':[{'name':'old.mkv','length':100,'bytesCompleted':100}]}
  plan=make_plan(row,{'kind':'movie','title':'Мемуары гейши','original_title':'Memoirs of a Geisha','year':2005})
  self.assertEqual(plan,[{'path':'old.mkv','name':'Мемуары гейши (2005).mkv'}])

class SavedIdentityTests(unittest.TestCase):
 def test_first_pass_does_not_request_model(self):
  import tempfile
  from bot.jobs import JobStore
  from bot.naming_worker import NamingWorker
  class Resolver:
   def identify(self,*args):raise AssertionError('saved identity must be reused')
  class API:
   applied=[]
   def command(self,job):
    if job['payload']['action']=='naming_apply':self.applied.append(job['payload']);return {'ok':True}
    return {'torrents':[{'hashString':'a'*40,'name':'a.mkv','percentDone':1,'files':[{'name':'a.mkv','length':3,'bytesCompleted':3}],'downloadDir':'/media'}],'plex':[]}
  with tempfile.TemporaryDirectory() as d:
   store=JobStore(d+'/db');identity={'kind':'movie','title':'Мемуары гейши','original_title':'Memoirs of a Geisha','year':2005}
   store.write_state('film:'+'a'*40,{'media':identity});api=API()
   NamingWorker(store,api,Resolver()).step(1000)
   self.assertEqual(api.applied[0]['identity'],identity)
   self.assertEqual(store.read_state('naming:'+'a'*40)['phase'],'waiting_for_plex')
