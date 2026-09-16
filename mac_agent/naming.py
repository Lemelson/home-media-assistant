"""Apply validated plans through Transmission; inspect Plex using local credentials."""
import json
import plistlib
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from bot.naming import make_plan,relative,VIDEO


def apply_plan(rpc,torrent,identity,journal):
 plan=make_plan(torrent,identity)
 base=Path(torrent['downloadDir'])
 # Validate the whole plan before the first RPC. No overwrite, symlink or stale file.
 for item in torrent['files']:
  p=base/item['name']
  if any(parent.is_symlink() for parent in [p,*p.parents]):raise ValueError('symlink')
  if not p.is_file() or p.stat().st_size!=item['length']:raise ValueError('file_changed')
 virtual={str(relative(f['name'])) for f in torrent['files']}
 destinations=set()
 for op in plan:
  source=relative(op['path']);dest=str(source.parent/op['name'])
  if len(op['name'].encode())>240 or dest.casefold() in destinations:raise ValueError('name_collision')
  destinations.add(dest.casefold())
  if (base/dest).exists() and dest!=str(source):raise ValueError('target_exists')
  renamed={dest+p[len(str(source)):] if p==str(source) or p.startswith(str(source)+'/') else p for p in virtual}
  if len({p.casefold() for p in renamed})!=len(virtual):raise ValueError('name_collision')
  virtual=renamed
 journal('planned',{'identity':identity,'before':torrent['files'],'operations':plan})
 for op in plan:
  rpc.call('torrent-rename-path',{'ids':[torrent['hashString']],**op})
  journal('renamed',op)
 return {'operations':plan,'files':sorted(virtual)}


class Plex:
 def request(self,path,method='GET'):
  prefs=Path.home()/'Library/Preferences/com.plexapp.plexmediaserver.plist'
  token=plistlib.loads(prefs.read_bytes()).get('PlexOnlineToken','')
  request=urllib.request.Request('http://127.0.0.1:32400'+path,method=method,headers={'X-Plex-Token':token})
  try:
   with urllib.request.urlopen(request,timeout=15) as response:raw=response.read(8*1024*1024)
   return ET.fromstring(raw) if raw else ET.Element('MediaContainer')
  except Exception:raise RuntimeError('plex_unavailable') from None
 def inventory(self):
  result=[];shows={}
  for section in self.request('/library/sections').findall('Directory'):
   kind=section.get('type')
   if kind not in ('movie','show'):continue
   sid=section.get('key')
   if not sid or not sid.isdigit():continue
   path='/library/sections/'+sid+'/all'+('?type=4' if kind=='show' else '')
   for item in self.request(path):
    if kind=='show':
     parent=item.get('grandparentRatingKey','')
     if parent.isdigit() and parent not in shows:shows[parent]=self.request('/library/metadata/'+parent).find('Directory')
     show=shows.get(parent)
    else:show=item
    if show is None:continue
    result.append({'key':item.get('ratingKey'),'match_key':show.get('ratingKey'),'section':sid,'kind':kind,'title':show.get('title'),
      'original_title':show.get('originalTitle'),'year':show.get('year'),'guid':show.get('guid'),
      'season':item.get('parentIndex'),'episode':item.get('index'),
      'files':[p.get('file') for p in item.findall('.//Part')]})
  return result
 def repair(self,torrent,identity):
  from bot.naming_worker import same_identity
  paths={str(Path(torrent['downloadDir'])/f['name']) for f in torrent['files']}
  targets={i['match_key']:i for i in self.inventory() if paths.intersection(i['files']) and i['kind']==identity['kind']}
  if len(targets)!=1:raise ValueError('plex_target_ambiguous')
  key,item=next(iter(targets.items()))
  if not str(key).isdigit():raise ValueError('plex_target_invalid')
  if not same_identity(identity,item) or not str(item.get('guid','')).startswith('plex://'):
   candidates={}
   for title in dict.fromkeys([identity.get('title'),identity.get('original_title')]):
    if not title:continue
    query=urllib.parse.urlencode({'title':title,'year':identity['year'],'manual':1,'language':'ru-RU'})
    for candidate in self.request('/library/metadata/'+key+'/matches?'+query):
     data={'title':candidate.get('name') or candidate.get('title'),'year':candidate.get('year')}
     guid=candidate.get('guid','')
     if same_identity(identity,data) and guid.startswith('plex://'+identity['kind']+'/'):candidates[guid]=data
   if len(candidates)!=1:raise ValueError('plex_match_ambiguous')
   guid,data=next(iter(candidates.items()))
   query=urllib.parse.urlencode({'guid':guid,'name':data['title'],'year':data['year'],'language':'ru-RU'})
   self.request('/library/metadata/'+key+'/match?'+query,'PUT')
  self.request('/library/metadata/'+key+'/prefs?languageOverride=ru-RU&useOriginalTitle=0','PUT')
  self.request('/library/metadata/'+key+'/refresh','PUT')
 def refresh(self,kind):
  for section in self.request('/library/sections').findall('Directory'):
   sid=section.get('key','')
   if section.get('type')==('show' if kind=='show' else 'movie') and sid.isdigit():
    self.request('/library/sections/'+sid+'/refresh')


def naming_command(controller,payload):
 action=payload['action'];known=controller.store.read_state('managed',{})
 rows=controller.rpc.call('torrent-get',{'fields':['hashString','name','downloadDir','files','percentDone','status','errorString']}).get('torrents',[])
 root=controller.check_disk()
 if action=='naming_status':
  return {'ok':True,'torrents':[t for t in rows if t['hashString'] in known],'plex':Plex().inventory()}
 h=payload.get('hash')
 if h not in known:raise ValueError('unmanaged_torrent')
 row=next(t for t in rows if t['hashString']==h)
 expected=root/('TV' if known[h]['kind']=='show' else 'Movies')
 if Path(row['downloadDir'])!=expected:raise ValueError('wrong_directory')
 if row.get('errorString') or row.get('percentDone')!=1 or row.get('status') in (1,2):raise ValueError('torrent_not_ready')
 identity=payload['identity']
 if identity.get('kind')!=known[h]['kind']:raise ValueError('wrong_kind')
 key='naming-journal:'+h
 def journal(stage,data):
  record=controller.store.read_state(key,{'events':[]})
  record['events']=(record['events']+[{'stage':stage,'data':data}])[-2100:]
  controller.store.write_state(key,record)
 if payload.get('repair_match'):Plex().repair(row,identity)
 if payload.get('localize_only'):return {'ok':True,'hash':h,'localized':True}
 result=apply_plan(controller.rpc,row,identity,journal)
 try:Plex().refresh(identity['kind']);scan=True
 except Exception:scan=False
 return {'ok':True,'hash':h,'scan_requested':scan,**result}
