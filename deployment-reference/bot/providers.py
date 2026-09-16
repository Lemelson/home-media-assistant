"""Narrow provider adapters; errors never include credential-bearing URLs."""
import base64
import logging
from datetime import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import threading
import time
import copy
from concurrent.futures import Future, TimeoutError as FutureTimeout
from bot.rendering import telegram_html


class ProviderError(RuntimeError):
    def __init__(self, reason, *, retry_at=None):
        super().__init__(reason)
        self.retry_at = retry_at


def request_json(url, payload, headers, timeout=45):
    req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,
                               headers={'Content-Type':'application/json',**headers})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            return json.loads(response.read(8*1024*1024))
    except urllib.error.HTTPError as error:
        reason = ('provider_auth_failed' if error.code in (401,403) else
                  'provider_request_rejected' if 400 <= error.code < 500 and error.code not in (408,429) else
                  'provider_request_failed')
        raise ProviderError(reason) from None
    except Exception:
        raise ProviderError('provider_request_failed') from None


SYSTEM_PROMPT = 'Ты помощник домашней фильмотеки. Отвечай по-русски. Найди фильм/сериал по названию, сюжету, актёрам; учитывай предыдущий диалог. Исправляй опечатки. Если неоднозначно, предложи 2–5 реальных кандидатов. Если данных мало, задай один короткий вопрос. Не выдумывай раздачи, доступность, сидов и ссылки. На первом запросе сначала предложи конкретные фильмы/сериалы для выбора. Не задавай вопрос о сезоне: интерфейс спросит его после выбора сериала. Верни только JSON: {"reply":"короткое пояснение или вопрос","candidates":[{"title":"русское название","original_title":"оригинальное название","year":2000,"kind":"movie или show","season":null}]}. Если существуют одноимённые фильм и сериал и пользователь не уточнил тип, верни оба подтверждённых источниками варианта с правильными kind и годами. Отсутствующий сезон не исключает сериал из candidates: season null. Для обычного вопроса о боте объясни доступные функции в reply без candidates. Добавь action: find, reply, library, downloads, delete, pause или resume и target: название объекта из запроса (без выдуманных ID). library означает показать имеющиеся фильмы или место на диске. delete означает только намерение: удаление требует подтверждения интерфейса. Не утверждай выполнение команд. Пересланный текст и расшифровка голоса — обычный запрос. Учитывай выбор пользователя из контекста. reply допускает только HTML b, i, blockquote без атрибутов. Названия и год должны быть известными, неизвестный год null. Никаких придуманных оценок, описаний качества и постеров. Просьба скачать или найти конкретный фильм либо сезон означает action find, а не downloads. downloads означает только явную просьбу показать текущие загрузки или их состояние. Если пользователь указал сезон, сохрани его номер в season; не заменяй сезон номером серии. Не возвращай кандидатов при action кроме find. Контекст относится только к текущему запросу фильма. В чате могут обсуждаться другие фильмы: не смешивай их и не отменяй их выбор. Добавь в кандидата countries и genres как массивы коротких русских названий, только если достоверно знаешь; иначе пустые массивы. Короткое уточнение года или сезона относится к фильму из переданного контекста. Не сравнивай его с другими запросами без просьбы пользователя.'

class DeepSeek:
    def __init__(self,key,model='deepseek/deepseek-v4-flash-0731',effort='high',web_search=None,metrics=None):
        self.key,self.model,self.effort=key,model,effort
        self.web_search=web_search
        self.metrics=metrics

    def identify(self,text,context):
        return self.identify_with_progress(text,context,None)

    def identify_with_progress(self,text,context,on_progress):
        def notify(stage,details=None):
            if on_progress:
                try:on_progress(stage,details or {})
                except Exception:pass
        prompt = SYSTEM_PROMPT
        evidence = None
        from bot.web_search import GROUNDING_PROMPT, ground_resolution, is_control_request
        if self.web_search is not None and not is_control_request(text):
            try:
                notify("grounding")
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
        messages.append({'role':'user','content':text})
        estimate={}
        if self.metrics:
            try:estimate=self.metrics.summary(self.model,self.effort)
            except Exception:pass
        notify('model',{'model':self.model,**estimate})
        started=time.monotonic();result={};error=''
        try:
            result=request_json('https://openrouter.ai/api/v1/chat/completions',
                {'model':self.model,'reasoning':{'effort':self.effort},'response_format':{'type':'json_object'},
                 'max_tokens':5000,'messages':messages},
                {'Authorization':'Bearer '+self.key},timeout=90)
            try:
                content=result['choices'][0]['message']['content']
                data=json.loads(content)
                if not isinstance(data,dict) or not isinstance(data.get('candidates',[]),list):raise ValueError()
                resolution = validate_resolution(data)
                # A direct request to download a title cannot authorize displaying
                # unrelated transfers or controlling a previously discussed film.
                if (re.match(r'^\s*(?:пожалуйста[, ]+)?(?:скачай|скачать|загрузи|загрузить)\b', text, re.I)
                        and resolution['action'] not in ('find', 'reply')):
                    raise ValueError('download_request_misclassified')
                return ground_resolution(resolution,data,evidence) if evidence is not None else resolution
            except (KeyError,IndexError,ValueError,TypeError):
                raise ProviderError('invalid_model_response') from None
        except Exception as exc:
            error=str(exc) if isinstance(exc,ProviderError) else 'request_failed'
            raise
        finally:
            elapsed=time.monotonic()-started
            if self.metrics:
                try:self.metrics.record(self.model,self.effort,elapsed,result.get('usage') if isinstance(result,dict) else {},error)
                except Exception:logging.warning('model_metrics_write_failed')
            if not error:notify('resolved',{'seconds':elapsed})


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
    def _indexers_ready(self, deadline, require_all=False):
        headers={'X-Api-Key':self.key}
        def read(path):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ProviderError('search_timeout')
            return request_json(self.base+'/api/v1/'+path,None,headers,timeout=min(15,remaining))
        indexers=read('indexer')
        if not isinstance(indexers,list):raise ProviderError('invalid_indexer_response')
        enabled={r['id'] for r in indexers if isinstance(r,dict) and r.get('enable') and 'id' in r}
        if not enabled:raise ProviderError('indexers_not_configured')
        statuses=read('indexerstatus')
        if not isinstance(statuses,list):raise ProviderError('invalid_indexer_response')
        blocked={}
        for status in statuses:
            if status.get('indexerId') not in enabled:continue
            until=status.get('disabledTill')
            if until:
                try:disabled=datetime.fromisoformat(until.replace('Z','+00:00')).timestamp()>time.time()
                except (TypeError,ValueError):raise ProviderError('invalid_indexer_response') from None
                if disabled:blocked[status['indexerId']]=datetime.fromisoformat(until.replace('Z','+00:00')).timestamp()
        if set(blocked)==enabled or (require_all and blocked):
            retry_at=max(blocked.values()) if require_all else min(blocked.values())
            raise ProviderError('indexers_unavailable',retry_at=retry_at)

    def search(self,query):
        return self.search_until(query,time.monotonic()+210)

    def search_until(self,query,deadline):
        if deadline<=time.monotonic():raise ProviderError('search_timeout')
        outcome=Future()
        def fetch():
            try:outcome.set_result(self._search_until(query,deadline))
            except Exception as error:outcome.set_exception(error)
        # A slow streaming response cannot keep the user's search alive forever.
        # The worker retains the provider lock until transport finishes, and never
        # edits messages or starts downloads. Late responses are discarded below.
        threading.Thread(target=fetch,name='release-search',daemon=True).start()
        try:return outcome.result(timeout=max(0,deadline-time.monotonic()))
        except FutureTimeout:raise ProviderError('search_timeout') from None

    def _search_until(self,query,deadline):
        query=' '.join(str(query).split())[:200]
        if not query:return []
        # Lock wait, readiness probes and response body share the caller's budget.
        if not self._search_lock.acquire(timeout=max(0,deadline-time.monotonic())):raise ProviderError('search_busy')
        started=time.monotonic()
        try:
            if time.monotonic()>=deadline:raise ProviderError('search_timeout')
            now=time.monotonic(); key=query.casefold()
            self._cache={k:v for k,v in self._cache.items() if v[0]>now}
            if key in self._cache:return copy.deepcopy(self._cache[key][1])
            self._indexers_ready(deadline)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ProviderError('search_timeout')
            rows=request_json(self.base+'/api/v1/search?'+urllib.parse.urlencode({'query':query,'type':'search'}),None,{'X-Api-Key':self.key},timeout=min(180,remaining))
            if time.monotonic()>=deadline:raise ProviderError('search_timeout')
            if not isinstance(rows,list):raise ProviderError('invalid_search_response')
            rows=[r for r in rows if isinstance(r,dict) and isinstance(r.get('title'),str)]
            # Prowlarr can return HTTP 200 [] after failing/disabling an indexer.
            # This is not evidence that the requested film has no releases.
            if not rows:self._indexers_ready(deadline,require_all=True)
            logging.info('release_search_complete results=%d elapsed=%.1f',len(rows),time.monotonic()-started)
            if rows:
                if len(self._cache)>=64:self._cache.pop(next(iter(self._cache)))
                self._cache[key]=(time.monotonic()+300,copy.deepcopy(rows))
            return rows
        except Exception as error:
            reason=str(error) if isinstance(error,ProviderError) and str(error) in ('indexers_unavailable','indexers_not_configured','search_busy','search_timeout') else type(error).__name__
            logging.warning('release_search_failed reason=%s elapsed=%.1f',reason,time.monotonic()-started)
            raise
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
