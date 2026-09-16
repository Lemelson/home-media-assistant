"""Conservative naming plans: model proposals never become arbitrary paths."""
import re
from pathlib import PurePosixPath
VIDEO={'.mkv','.mp4','.avi','.m4v','.mov','.ts','.webm','.mpg','.mpeg'}
SIDECAR={'.srt','.ass','.ssa','.sub','.idx','.ac3','.dts','.dtsma','.aac','.flac','.mka','.sup'}

def component(text):
 if not isinstance(text,str) or not text.strip():raise ValueError('missing_title')
 text=' '.join(re.sub(r'[\\/:*?"<>|\x00-\x1f]',' ',text).split()).strip(' .')
 if not text or len(text.encode())>180:raise ValueError('invalid_title')
 return text

def relative(path):
 if not isinstance(path,str) or '\\' in path or '\x00' in path:raise ValueError('invalid_path')
 p=PurePosixPath(path)
 if p.is_absolute() or any(x in ('','.','..') for x in path.split('/')):raise ValueError('invalid_path')
 return p

def episode_numbers(path,season=None):
 m=re.search(r'(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,3})(?:[ ._-]*e(\d{1,3}))?(?!\d)',path)
 if not m:m=re.search(r'(?i)(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)',path)
 if m:
  values=[int(x) for x in m.groups() if x is not None]
  if values[1]<1 or (len(values)>2 and values[2]<values[1]):raise ValueError('invalid_episode')
  if re.match(r'(?i)[ -]*(?:-|to)[ -]*(?:e)?\d',path[m.end():]):raise ValueError('episode_range_ambiguous')
  return values
 directory=re.search(r'(?i)(?:season|сезон)[ ._-]*(\d{1,2})',path)
 selected=int(directory.group(1)) if directory else season
 m=re.match(r'(?i)(?:episode|серия|ep|e)?[ ._-]*(\d{1,3})(?:[ ._-]|$)',PurePosixPath(path).stem)
 if type(selected) is int and 0<=selected<=99 and m and 1<=int(m.group(1))<=999:return [selected,int(m.group(1))]
 raise ValueError('episode_ambiguous')

def make_plan(torrent,identity,episode_titles=None):
 year=identity.get('year');kind=identity.get('kind')
 if type(year) is not int or not 1888<=year<=2100 or kind not in ('movie','show'):raise ValueError('identity_incomplete')
 base='%s (%d)'%(component(identity.get('title') or identity.get('original_title')),year)
 files=torrent.get('files',[])
 if not files or len(files)>2000:raise ValueError('file_count')
 for f in files:
  relative(f['name'])
  if f.get('length',0)>f.get('bytesCompleted',0):raise ValueError('incomplete')
 videos=[f for f in files if relative(f['name']).suffix.lower() in VIDEO and not re.search(r'(?i)(?:^|[/ ._-])(?:sample|trailer|extras|featurettes|bonus)(?:[/ ._-]|$)',f['name'])]
 if not videos or (kind=='movie' and len(videos)!=1):raise ValueError('ambiguous_video_set')
 operations=[];targets=set();episode_seen=set()
 for f in videos:
  path=relative(f['name']);stem=base
  if kind=='show':
   nums=episode_numbers(f['name'],identity.get('season'));key=tuple(nums)
   if key in episode_seen:raise ValueError('duplicate_episode')
   episode_seen.add(key);stem+=' - S%02dE%02d'%(nums[0],nums[1])
   if len(nums)>2:stem+='E%02d'%nums[2]
   if episode_titles and f['name'] in episode_titles:stem+=' - '+component(episode_titles[f['name']])
  new=stem+path.suffix
  for other in files:
   p=relative(other['name'])
   if p==path:target=new
   elif p.parent==path.parent and p.suffix.lower() in SIDECAR and (p.name.startswith(path.stem+'.') or p.name.startswith(path.stem+'-')):target=stem+p.name[len(path.stem):]
   else:continue
   dest=str(p.parent/target)
   if dest.casefold() in targets:raise ValueError('name_collision')
   targets.add(dest.casefold())
   if str(p)!=dest:operations.append({'path':str(p),'name':target})
 root=relative(torrent.get('name',''))
 if len(root.parts)==1 and all(relative(f['name']).parts[0]==str(root) and len(relative(f['name']).parts)>1 for f in files):
  if kind=='show':
   parents={str(relative(f['name']).parent) for f in videos}
   for parent in sorted(parents,key=lambda p:-len(relative(p).parts)):
    if parent==str(root):continue
    nums={episode_numbers(f['name'],identity.get('season'))[0] for f in videos if str(relative(f['name']).parent)==parent}
    if len(nums)!=1:continue
    new='Season %02d'%next(iter(nums))
    if relative(parent).name!=new:operations.append({'path':parent,'name':new})
  if str(root)!=base:operations.append({'path':str(root),'name':base})
 return operations
