"""Supplemental page-associated film images, using two bounded Exa queries at most."""
from collections import OrderedDict
import re
import threading
import time
from urllib.parse import urlsplit,parse_qs,unquote

from bot.web_search import usable_source_image


def _normal(value):
    return ' '.join(re.findall(r'[^\W_]+',str(value).casefold().replace('ё','е')))


def _photo_url(value):
    if not usable_source_image(value):return False
    parsed=urlsplit(value)
    if '.webp' in unquote(parsed.path).casefold():return False
    return not any(v.casefold()=='webp' for k,values in parse_qs(parsed.query).items()
                   if k.casefold() in ('format','fm','f') for v in values) and not any(
                       'to_webp' in v.casefold() for v in parse_qs(parsed.query).get('mod',[]))


class MovieImages:
    def __init__(self,search):
        self.search=search
        self._cache=OrderedDict()
        self._lock=threading.Lock()

    def for_media_gallery(self,media,limit=3,language='ru'):
        """Prefer first RU query image, first EN query image, second RU query image.

        Query language is a preference, not a guarantee about text inside the image.
        No LLM call, local image download, or fabricated image URL is used.
        """
        limit=max(0,min(3,int(limit)))
        title=str(media.get('title') or '').strip()[:180]
        original=str(media.get('original_title') or '').strip()[:180]
        if not limit or not (title or original):return []
        kind=media.get('kind','movie')
        if kind not in ('movie','show'):return []
        year=media.get('year')
        key=(_normal(title),_normal(original),year,kind)
        with self._lock:
            entry=self._cache.get(key)
            if not entry or entry['expires']<=time.monotonic():
                entry={'expires':time.monotonic()+86400,'lock':threading.Lock(),'ru':None,'en':None}
                self._cache[key]=entry
            self._cache.move_to_end(key)
            while len(self._cache)>128:self._cache.popitem(last=False)
        # Only identical identities serialize; other movies remain independent.
        with entry['lock']:
            if entry['ru'] is None:
                query=f'{title or original} {year or ""} постер фильма русский постер кадры'
                entry['ru']=self._lookup(query,title,original,year)
            if entry['en'] is None and (limit>1 or not entry['ru']):
                query=f'{original or title} {year or ""} movie English poster stills'
                entry['en']=self._lookup(query,title,original,year)
            ru,en=entry['ru'],entry['en'] or []
            ordered=ru[:1]+en[:1]+ru[1:]+en[1:]
            return list(dict.fromkeys(ordered))[:limit]

    def _lookup(self,query,title,original,year):
        try:rows=self.search.search(query,[])
        except Exception:return []
        names=[_normal(n) for n in (title,original) if n]
        photos=[]
        for row in rows[:5]:
            if not isinstance(row,dict):continue
            text=_normal(str(row.get('title',''))+' '+str(row.get('excerpt','')))
            # Full normalized title as a token sequence, never a substring of another word.
            if not any(' '+name+' ' in ' '+text+' ' for name in names):continue
            if year is not None and str(year) not in text.split():continue
            image=row.get('image')
            if _photo_url(image) and image not in photos:photos.append(image)
        return photos[:3]
