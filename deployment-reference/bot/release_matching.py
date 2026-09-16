"""Explainable identity checks. Quality and size are never exclusion criteria."""
import re
import unicodedata
from bot.seasons import title_seasons

VIDEO=r'\b(?:\d{3,4}[pi]|[248][KК]|UHD|BluRay|BR-DISK|WEB[ -]?DL|WEBRip|BDRip|BDRemux|Hybrid(?:Rip)?|HDRip|DVDRip|DVD[59]|SATRip|HDTV|TVRip|AVC|HEVC|\d{3,5}[xх×]\d{3,5})\b'
YEAR=r'(?<!\d)(?:19|20)\d{2}(?!\d)'

def normalized(value):
    value=unicodedata.normalize('NFKD',value.casefold().replace('ё','е'))
    value=''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[^\W_]+',value))

def protected_titles(title, names):
    """Mark known title aliases before interpreting their punctuation as metadata."""
    text=unicodedata.normalize('NFKD',title.casefold().replace('ё','е'))
    text=''.join(c for c in text if not unicodedata.combining(c))
    replacements={}
    if not names:return text,replacements
    patterns=[r'(?<!\w)'+r'[\W_]+'.join(re.escape(token) for token in name.split())+r'(?!\w)'
              for name in sorted(names,key=len,reverse=True)]
    pattern=re.compile('|'.join(patterns))
    def replace(match):
        # Only title-position occurrences qualify; a production year or a word
        # buried in another title must never be hidden from metadata checks.
        start=text.rfind('/',0,match.start())+1
        prefix=text[start:match.start()]
        prefix=re.sub(r'\[[^\]]*\]|\([^)]*\)',' ',prefix)
        if normalized(prefix):return match.group()
        marker='knownmovietitle'+chr(ord('a')+len(replacements))
        replacements[marker]=normalized(match.group())
        return marker
    return pattern.sub(replace,text),replacements


def aliases(title):
    # Bracketed production years start shared metadata. A bare number in an
    # unknown translated alias must not hide a later known original title.
    prefix=re.split(r'[\[(]\s*(?:'+YEAR+r')',title,maxsplit=1)[0]
    def annotation(match):
        return match.group() if 'knownmovietitle' in match.group() else ' '
    prefix=re.sub(r'\[[^\]]*\]',annotation,prefix)
    prefix=re.split(r'(?:\bS\d{1,2}(?!\d)|\bSeason\b|сезоны?\s*[:№]?\s*\d)',prefix,maxsplit=1,flags=re.I)[0]
    prefix=re.split(VIDEO,prefix,maxsplit=1,flags=re.I)[0]
    prefix=re.sub(r'\([^)]*\)',annotation,prefix)
    return [normalized(re.split(YEAR,part,maxsplit=1)[0]) for part in prefix.split('/')]

def rejection_reason(row,media=None):
    title=row.get('title','')
    names={normalized(n) for n in [media.get('title',''),media.get('original_title','')] if n} if media else set()
    title,replacements=protected_titles(title,names)
    if int(row.get('seeders') or 0)<=0:return 'no_seeders'
    if re.search(r'\b(?:EPUB|FB2|PDF|аудиокнига|саундтрек|Soundtrack|Score)\b',title,re.I):return 'book_or_audio'
    video=bool(re.search(VIDEO,title,re.I))
    if re.search(r'\b(?:FLAC|MP3)\b',title,re.I) and not video:return 'audio'
    if not media:return None
    release_names={replacements.get(alias,alias) for alias in aliases(title)}
    if not names.intersection(release_names):return 'different_title'
    years=re.findall(YEAR,title)
    if media.get('kind')=='movie' and media.get('year') and years and str(media['year']) not in years:return 'different_year'
    # Raw model years and season dates cannot identify an older remake.
    confirmed_year=media.get('verified_series_year')
    if media.get('kind')=='show' and confirmed_year and years and max(map(int,years))<int(confirmed_year):return 'older_series'
    seasons=title_seasons(title)
    if media.get('kind')=='movie' and seasons:return 'series'
    if media.get('kind')=='show' and media.get('season') and int(media['season']) not in seasons:return 'different_season'
    all_categories={c['id'] for c in row.get('categories',[]) if isinstance(c,dict) and type(c.get('id')) is int}
    categories={c for c in all_categories if c<100000}
    if categories:
        low,high=(5000,6000) if media.get('kind')=='show' else (2000,3000)
        if not any(low<=c<high for c in categories):
            # Some general-video and theatrical-animation categories have broad mappings.
            known_video_forum=bool(all_categories & {100807,100893,102182}) or (media.get("kind")=="movie" and 5070 in categories)
            pc_video=all(4000<=c<5000 for c in categories)
            identity=(media.get('kind')=='show' and media.get('season')) or (media.get('year') and str(media['year']) in years)
            if not ((known_video_forum or pc_video) and video and identity):return 'non_movie_category'
    return None

def search_queries(media):
    names=list(dict.fromkeys(n for n in [media['title'].replace('ё','е').replace('Ё','Е'),media.get('original_title')] if n))
    # Short/common names otherwise fill the tracker's first page with unrelated works.
    if media.get('kind')=='movie' and media.get('year'):
        return [name+' '+str(media['year']) for name in names]
    return names


def additional_search_queries(media):
    if media.get('kind')!='show' or not media.get('season'):return []
    season=int(media['season']);ru=media['title'].replace('ё','е').replace('Ё','Е')
    original=media.get('original_title') or ru
    queries=[ru+' сезон '+str(season),original+' S%02d'%season]
    if season==1 and media.get('year'):queries.insert(0,original+' '+str(media['year']))
    return list(dict.fromkeys(queries))
