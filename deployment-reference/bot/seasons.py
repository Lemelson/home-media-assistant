"""Explicit season requests and conservative torrent file selection, without an LLM."""
import re

ORDINALS={'первый':1,'первого':1,'второй':2,'второго':2,'третий':3,'третьего':3,
 'четвертый':4,'пятый':5,'шестой':6,'седьмой':7,'восьмой':8,'девятый':9,'десятый':10}

def parse_seasons(text):
    text=text.casefold().replace('ё','е').strip()
    text=re.sub(r'\bсезон(?:ы|ов|а)?\b','',text)
    for word,number in ORDINALS.items():text=re.sub(r'\b'+word+r'\b',str(number),text)
    text=re.sub(r'\s+и\s+',',',text).strip()
    if not re.fullmatch(r'\d{1,2}(?:\s*[-–—]\s*\d{1,2})?(?:\s*[,;]\s*\d{1,2}(?:\s*[-–—]\s*\d{1,2})?)*',text):return None
    result=set()
    for item in re.split('[,;]',text):
        values=[int(n) for n in re.split('[-–—]',item)]
        start,end=values[0],values[-1]
        if not 1<=start<=end<=99:return None
        result.update(range(start,end+1))
    return sorted(result) if len(result)<=30 else None

def title_seasons(title):
    result=set()
    pattern=r'(?:\bS|\bSeasons?\s*[:№]?\s*|сезоны?\s*[:№]?\s*)(\d{1,2})(?!\d)(?:\s*[-–—]\s*S?(\d{1,2})(?!\d))?'
    for m in re.finditer(pattern,title,re.I):
        start,end=int(m[1]),int(m[2] or m[1])
        if 1<=start<=end<=99:result.update(range(start,end+1))
    for m in re.finditer(r'(?<!\d)(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?\s*(?:сезоны?|seasons?)\b',title,re.I):
        start,end=int(m[1]),int(m[2] or m[1])
        if 1<=start<=end<=99:result.update(range(start,end+1))
    return result

def select_files(files,seasons,release_name=''):
    requested=set(seasons);found=set();wanted=[]
    declared=title_seasons(release_name)
    for i,file in enumerate(files):
        name=file.get('name','')
        if re.search(r'(?:^|[/\\ ._-])(?:sample|trailer|extras?|bonus|образец|трейлер)(?:[/\\ ._-]|$)',name,re.I):continue
        if not re.search(r'\.(?:mkv|mp4|avi|m4v|mov|ts|m2ts|vob|mpg|mpeg|wmv|srt|ass|ssa|sub|idx|mka|ac3|dts|dtsma|aac|flac|sup)$',name,re.I):continue
        components=[title_seasons(part) for part in re.split(r'[/\\]',name)]
        specific=[part for part in components if len(part)==1]
        seasons_in_path=set().union(*(specific or components))
        if not seasons_in_path and len(declared)==1:seasons_in_path=declared
        # Ambiguous files must never be assigned to a season by guessing.
        if len(seasons_in_path)!=1:
            if seasons_in_path & requested:raise ValueError('season_files_ambiguous')
            continue
        if seasons_in_path & requested:
            wanted.append(i)
            if re.search(r'\.(?:mkv|mp4|avi|m4v|mov|ts|m2ts|vob|mpg|mpeg|wmv)$',name,re.I):found.update(seasons_in_path)
    if found!=requested:raise ValueError('season_files_missing')
    return wanted

def selected_torrent(torrent,managed):
    indices=managed.get('selected_file_indices')
    if indices is None:return torrent
    return {**torrent,'files':[f for i,f in enumerate(torrent.get('files',[])) if i in set(indices)]}
