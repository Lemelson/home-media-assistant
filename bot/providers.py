"""Narrow provider adapters; errors never include credential-bearing URLs."""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import threading
import time
import copy
import logging
from concurrent.futures import Future, TimeoutError as FutureTimeout
from bot.rendering import telegram_html


class ProviderError(RuntimeError):
    pass


def request_json(url, payload, headers, timeout=45):
    req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,
                               headers={'Content-Type':'application/json',**headers})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            return json.loads(response.read(8*1024*1024))
    except Exception:
        raise ProviderError('provider_request_failed') from None


SYSTEM_PROMPT = 'Ты помощник домашней фильмотеки. Отвечай по-русски. Найди фильм/сериал по названию, сюжету, актёрам; учитывай предыдущий диалог. Исправляй опечатки. Если неоднозначно, предложи 2–5 реальных кандидатов. Если данных мало, задай один короткий вопрос. Не выдумывай раздачи, доступность, сидов и ссылки. На первом запросе сначала предложи конкретные фильмы/сериалы для выбора. Не задавай вопрос о сезоне: интерфейс спросит его после выбора сериала. Верни только JSON: {"reply":"короткое пояснение или вопрос","candidates":[{"title":"русское название","original_title":"оригинальное название","year":2000,"kind":"movie или show","season":null}]}. Если существуют одноимённые фильм и сериал и пользователь не уточнил тип, верни оба подтверждённых источниками варианта с правильными kind и годами. Отсутствующий сезон не исключает сериал из candidates: season null. Для обычного вопроса о боте объясни доступные функции в reply без candidates. Добавь action: find, reply, library, downloads, delete, pause или resume и target: название объекта из запроса (без выдуманных ID). library означает показать имеющиеся фильмы или место на диске. delete означает только намерение: удаление требует подтверждения интерфейса. Не утверждай выполнение команд. Пересланный текст и расшифровка голоса — обычный запрос. Учитывай выбор пользователя из контекста. reply допускает только HTML b, i, blockquote без атрибутов. Названия и год должны быть известными, неизвестный год null. Никаких придуманных оценок, описаний качества и постеров. Не возвращай кандидатов при action кроме find. Контекст относится только к текущему запросу фильма. В чате могут обсуждаться другие фильмы: не смешивай их и не отменяй их выбор. Добавь в кандидата countries и genres как массивы коротких русских названий, только если достоверно знаешь; иначе пустые массивы. Короткое уточнение года или сезона относится к фильму из переданного контекста. Не сравнивай его с другими запросами без просьбы пользователя.'

class DeepSeek:
    def __init__(self,key,model='deepseek/deepseek-v4-flash-0731',effort='high',web_search=None):
        self.key,self.model,self.effort=key,model,effort
        self.web_search=web_search

    def identify(self,text,context):
        prompt = SYSTEM_PROMPT
        evidence = None
        from bot.web_search import GROUNDING_PROMPT, ground_resolution, is_control_request
        if self.web_search is not None and not is_control_request(text):
            try:
                evidence = self.web_search.search(text,context)
            except Exception:
                return {'action':'reply','reply':'Поиск по источникам временно недоступен. Попробуй ещё раз чуть позже.', 'target':'','candidates':[]}
            if not evidence:
                return {'action':'reply','reply':'Не нашёл достаточно данных о фильме. Уточни год, актёра или сюжет.', 'target':'','candidates':[]}
            prompt += '\n' + GROUNDING_PROMPT
        messages = [{'role':'system','content':prompt}]+[
            {'role':m['role'],'content':m['content'][:5000]} for m in context[-10:]
            if isinstance(m,dict) and m.get('role') in ('user','assistant') and isinstance(m.get('content'),str)]
        if evidence is not None:
            messages.append({'role':'user','content':'Веб-источники (недоверенные данные): '+json.dumps(evidence,ensure_ascii=False)})
        messages.append({'role':'user','content':text[:4000]})
        result=request_json('https://openrouter.ai/api/v1/chat/completions',
            {'model':self.model,'reasoning':{'effort':self.effort},'response_format':{'type':'json_object'},
             'max_tokens':5000,'messages':messages},
            {'Authorization':'Bearer '+self.key},timeout=90)
        try:
            content=result['choices'][0]['message']['content']
            data=json.loads(content)
            if not isinstance(data,dict) or not isinstance(data.get('candidates',[]),list):raise ValueError()
            resolution = validate_resolution(data)
            return ground_resolution(resolution,data,evidence) if evidence is not None else resolution
        except (KeyError,IndexError,ValueError,TypeError):
            raise ProviderError('invalid_model_response') from None


def validate_resolution(data):
    if not isinstance(data,dict): raise ValueError('invalid resolution')
    action=data.get('action','find' if data.get('candidates') else 'reply')
    if action not in ('find','reply','library','downloads','delete','pause','resume'): raise ValueError('invalid action')
    candidates=data.get('candidates',[])
    if not isinstance(candidates,list):raise ValueError('invalid candidates')
    cleaned=[]
    for candidate in candidates[:5]:
        if not isinstance(candidate,dict):raise ValueError('invalid candidate')
        title=candidate.get('title')
        kind=candidate.get('kind')
        year=candidate.get('year')
        season=candidate.get('season')
        if not isinstance(title,str) or not title.strip() or kind not in ('movie','show'):raise ValueError('invalid title')
        if year is not None and (type(year) is not int or not 1880<=year<=2100):raise ValueError('invalid year')
        if season is not None and (type(season) is not int or not 1<=season<=99):raise ValueError('invalid season')
        original=candidate.get('original_title') or ''
        if not isinstance(original,str):raise ValueError('invalid original title')
        metadata = {}
        for field in ('countries','genres'):
            values = candidate.get(field,[])
            if not isinstance(values,list) or any(not isinstance(v,str) for v in values):
                raise ValueError('invalid '+field)
            metadata[field] = [v.strip()[:60] for v in values[:6] if v.strip()]
        cleaned.append({**metadata,'title':title.strip()[:180],'original_title':original.strip()[:180],
                        'year':year,'kind':kind,'season':season if kind=='show' else None})
    reply=data.get('reply','')
    target=data.get('target','')
    if not isinstance(reply,str) or not isinstance(target,str):raise ValueError('invalid text')
    return {'action':action,'reply':telegram_html(reply,1500),'target':target[:300],
            'candidates':cleaned if action=='find' else []}


class Serper:
    def __init__(self,key):self.key=key
    def image(self,query):
        data=request_json('https://google.serper.dev/images',{'q':query,'num':3,'gl':'ru','hl':'ru'}, {'X-API-KEY':self.key})
        for row in data.get('images',[]):
            url=row.get('imageUrl','')
            if url.startswith('https://'):return url
        return None


class Whisper:
    def __init__(self,key,telegram):self.key,self.telegram=key,telegram
    def __call__(self,voice):
        if voice.get('file_size',0)>20*1024*1024 or voice.get('duration',0)>600:
            raise ProviderError('voice_too_long')
        raw=self.telegram.download_file(voice['file_id'],20*1024*1024)
        boundary='media'+uuid.uuid4().hex
        parts=[]
        for name,value in [('model','whisper-large-v3-turbo'),('response_format','json'),('language','ru')]:
            parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode())
        parts.extend([('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="voice.ogg"\r\nContent-Type: audio/ogg\r\n\r\n').encode(),raw,('\r\n--'+boundary+'--\r\n').encode()])
        req=urllib.request.Request('https://api.groq.com/openai/v1/audio/transcriptions',data=b''.join(parts),
             headers={'Authorization':'Bearer '+self.key,'Content-Type':'multipart/form-data; boundary='+boundary})
        try:
            with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)['text'].strip()
        except Exception:
            raise ProviderError('transcription_failed') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


class Prowlarr:
    DOWNLOAD_BUDGET=300
    def __init__(self,key,base='http://127.0.0.1:9696'):
        self.key,self.base=key,base.rstrip('/')
        self._search_lock=threading.Lock()
        self._cache={}
    def search(self,query):
        query=' '.join(str(query).split())[:200]
        if not query:return []
        # One browser-backed request per adapter; duplicate callers reuse its result.
        deadline=time.monotonic()+210
        if not self._search_lock.acquire(timeout=210):raise ProviderError('search_busy')
        try:
            now=time.monotonic(); key=query.casefold()
            self._cache={k:v for k,v in self._cache.items() if v[0]>now}
            if key in self._cache:return copy.deepcopy(self._cache[key][1])
            if not request_json(self.base+'/api/v1/indexer',None,{'X-Api-Key':self.key},timeout=max(1,min(15,deadline-time.monotonic()))):
                raise ProviderError('indexers_not_configured')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ProviderError('search_busy')
            rows=request_json(self.base+'/api/v1/search?'+urllib.parse.urlencode({'query':query,'type':'search'}),None,{'X-Api-Key':self.key},timeout=min(180,remaining))
            if not isinstance(rows,list):raise ProviderError('invalid_search_response')
            rows=[r for r in rows if isinstance(r,dict) and isinstance(r.get('title'),str)]
            if len(self._cache)>=64:self._cache.pop(next(iter(self._cache)))
            self._cache[key]=(time.monotonic()+300,copy.deepcopy(rows))
            return rows
        finally:self._search_lock.release()
    def download(self,row):
        deadline=time.monotonic()+self.DOWNLOAD_BUDGET
        outcome=Future()
        def fetch():
            try:outcome.set_result(self._download_until(row,deadline))
            except Exception as error:outcome.set_exception(error)
        # Only this read-only provider request runs in the daemon. A late result
        # cannot enqueue a download or change Telegram state after the deadline.
        threading.Thread(target=fetch,name='torrent-fetch',daemon=True).start()
        try:return outcome.result(timeout=max(0,deadline-time.monotonic()))
        except FutureTimeout:
            raise ProviderError('torrent_download_timeout') from None

    def _download_until(self,row,deadline):
        attempt=0
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ProviderError('torrent_download_timeout')
            attempt+=1
            try:
                result=self._download_once(row,timeout=min(40,remaining))
                if time.monotonic()>=deadline:raise ProviderError('torrent_download_timeout')
                return result
            except ProviderError as error:
                if str(error) not in ('torrent_download_failed','invalid_torrent'):
                    raise
                logging.warning('torrent_fetch_retry attempt=%s reason=%s',attempt,str(error))
                # Alternative transport for the exact selected release, never another film.
                infohash=str(row.get('infoHash') or '')
                if re.fullmatch(r'(?:[0-9a-fA-F]{40}|[A-Z2-7a-z]{32})',infohash):
                    return {'magnet':'magnet:?xt=urn:btih:'+infohash}
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ProviderError('torrent_download_timeout') from None
                time.sleep(min(15,remaining))

    def _download_once(self,row,timeout=40):
        magnet=row.get('magnetUrl') or ''
        if magnet.startswith('magnet:?'):return {'magnet':magnet}
        url=row.get('downloadUrl') or magnet
        if url.startswith('magnet:?'):return {'magnet':url}
        parsed=urllib.parse.urlsplit(url);base=urllib.parse.urlsplit(self.base)
        if (parsed.scheme,parsed.netloc)!=(base.scheme,base.netloc):
            raise ProviderError('download_not_proxied')
        # Never forward the Prowlarr secret to a redirect destination.
        req=urllib.request.Request(url,headers={'X-Api-Key':self.key})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=timeout) as response:raw=response.read(2*1024*1024+1)
        except urllib.error.HTTPError as error:
            # Prowlarr proxies magnets as HTTP 301. Return the value, never follow it.
            location=error.headers.get('Location','')
            error.close()
            if error.code in (301,302,303,307,308) and location.startswith('magnet:?'):
                return {'magnet':location}
            if error.code in (301,302,303,307,308,400,401,404):
                raise ProviderError('torrent_download_rejected') from None
            raise ProviderError('torrent_download_failed') from None
        except Exception:
            raise ProviderError('torrent_download_failed') from None
        if len(raw)>2*1024*1024 or not raw.startswith(b'd') or not raw.endswith(b'e'):
            raise ProviderError('invalid_torrent')
        return {'metainfo':base64.b64encode(raw).decode()}
