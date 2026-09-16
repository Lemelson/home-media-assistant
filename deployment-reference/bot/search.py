"""Persisted film confirmation with automatic eligible movie recommendations."""
import re
import secrets
import time
import json
import threading
import weakref
from html import escape
from datetime import datetime
from bot.rendering import telegram_html, plain_text
from bot.search_sessions import SearchSessions
from bot.seasons import parse_seasons, title_seasons
from bot.media_labels import film_card
from bot.candidate_gallery import send_candidate_gallery
from bot.request_progress import RequestProgress
from concurrent.futures import ThreadPoolExecutor


def rank_releases(rows, media=None):
    from bot.release_matching import rejection_reason
    return sorted([r for r in rows if rejection_reason(r,media) is None],
                  key=lambda r:int(r.get('seeders') or 0),reverse=True)



def selection(text):
    words = {'первый':0,'первую':0,'второй':1,'вторую':1,'третий':2,'третью':2,'четвертый':3,'пятый':4}
    clean = text.casefold().strip().replace('ё','е')
    clean = re.sub(r'^(скачай|выбери|давай|загрузи)\s+', '', clean).strip()
    if clean in words:
        return words[clean]
    return int(clean)-1 if re.fullmatch(r'(?:[1-9]|10)',clean) else None


class SearchFlow:
    def __init__(self, resolver, indexer, images=None, role_for=None, details=None, allow_remote_images=True):
        self.allow_remote_images=allow_remote_images
        self.resolver, self.indexer, self.images = resolver, indexer, images
        self.details=details
        self._locks=weakref.WeakValueDictionary();self._lock_guard=threading.Lock()
        self.role_for = role_for or (lambda uid,dialog: next((m['role'] for m in dialog.access.members() if m['user_id']==uid),'owner'))

    def handle_message(self, uid, chat_id, text, dialog, source, message):
        return self(uid, chat_id, text, dialog, source,
                    message_id=message.get('message_id'),
                    reply_to=message.get('reply_to_message', {}).get('message_id'),
                    receipt_id=message.get('_receipt_message_id'),
                    transcript=message.get('_voice_transcript'))

    def _show(self, uid, chat_id, state, dialog, text, markup=None):
        loading = state.pop('loading_message_id', None)
        if state.get('voice_transcript'):
            text = '🎙 <b><i>Распознано</i></b>\n<blockquote>' + escape(state['voice_transcript'][:1000]) + '</blockquote>\n\n' + text
        if loading and hasattr(dialog, 'edit_html'):
            try:
                sent = dialog.edit_html(chat_id, loading, text, markup)
            except Exception:
                sent = send_html(dialog, chat_id, text, markup)
                try:dialog.delete_message(chat_id,loading)
                except Exception:pass
        else:
            sent = send_html(dialog, chat_id, text, markup)
        if state.get('status_message_id'):
            state['status_message_id']=sent.get('message_id')
        sessions = SearchSessions(dialog.jobs, uid)
        if state.get('thread_id'):
            sessions.bind(state, sent.get('message_id'))
        if markup and sent.get('message_id'):
            state['choice_message_id'] = sent['message_id']
            sessions.save(state)
        return sent

    def __call__(self, uid, chat_id, text, dialog, source=None, message_id=None, reply_to=None, receipt_id=None, transcript=None):
        event_key = 'search-event:'+str(uid)+':'+source if source is not None else None
        if event_key and dialog.jobs.read_state(event_key,False):
            return
        # Numeric choices consume mutable menus; retain their existing deduplication.
        # A new lookup has no completed result until rendering returns successfully.
        if event_key and selection(text) is not None:
            dialog.jobs.write_state(event_key,True)
        result = self._handle_request(uid,chat_id,text,dialog,source,message_id,reply_to,receipt_id,transcript)
        if event_key:
            dialog.jobs.write_state(event_key,True)
        return result

    def _handle_request(self, uid, chat_id, text, dialog, source=None, message_id=None, reply_to=None, receipt_id=None, transcript=None):
        sessions = SearchSessions(dialog.jobs, uid)
        latest = dialog.jobs.read_state('search:'+str(uid), {})
        state = sessions.reply(reply_to) if reply_to else {}
        index = selection(text)
        requested_seasons=parse_seasons(text)
        if not state and not reply_to and latest.get('stage')=='season' and latest.get('expires',0)>time.time() and requested_seasons:
            state=latest
        correction = bool(re.match(r'^(?:не тот|не та|ни тот|нет[, .]|я имею в виду|имею в виду|я про|фильм с |с акт[её]р|ты неправильно)', text.strip(), re.I))
        if not state and not reply_to and correction and latest.get('expires',0)>time.time() and latest.get('stage') in ('media','release','season'):
            state = latest
        if not state and not reply_to:
            active = sessions.active()
            if index is not None:
                selectable = [s for s in active if s.get('candidates' if s['stage']=='media' else 'releases')]
                if len(selectable) > 1:
                    return self._show(uid,chat_id,{'loading_message_id':receipt_id,'voice_transcript':transcript},dialog, 'Открыто несколько фильмов. Нажми кнопку под нужным фильмом или ответь на его сообщение.')
                state = selectable[0] if selectable else latest
            elif len(active) == 1 and not active[0].get('candidates'):
                # A year/season/short pronoun is a clarification; a new title starts a new request.
                if re.fullmatch(r'(?:\d{1,4}|(?:сезон|год)\s*\d{1,4}|да|нет)', text.strip(), re.I):
                    state = active[0]
        if reply_to and not state:
            return self._show(uid,chat_id,{'loading_message_id':receipt_id,'voice_transcript':transcript},dialog, 'Не могу связать это старое сообщение с фильмом. Пришли название и уточнение вместе — другие кнопки сохранены.')
        if not state and not reply_to and requested_seasons:
            season_states=[s for s in sessions.active() if s.get('stage')=='season']
            if len(season_states)==1:state=season_states[0]
            elif len(season_states)>1:
                return self._show(uid,chat_id,{'loading_message_id':receipt_id,'voice_transcript':transcript},dialog,'Для какого сериала выбрать сезоны? Ответь на сообщение с его названием.')
        if state.get('stage')=='season':
            if not requested_seasons:
                return self._show(uid,chat_id,{**state,'loading_message_id':receipt_id,'voice_transcript':transcript},dialog,'Укажи сезоны: например, 1–3, 1,5 или первый, третий. До 30 сезонов за один запрос.')
            state.update(stage='done')
            sessions.save(state)
            if receipt_id:
                self._show(uid,chat_id,{'loading_message_id':receipt_id,'voice_transcript':transcript},dialog,'🔎 Ищу раздачи по сезонам: '+', '.join(map(str,requested_seasons))+'. Для каждого будет отдельный выбор.')
            results=[]
            for season in requested_seasons:
                chosen={**state['selected'],'season':season}
                child={'thread_id':secrets.token_hex(5),'nonce':secrets.token_hex(5),'stage':'media',
                       'candidates':[chosen],'context':state.get('context',[]),'expires':time.time()+sessions.TTL}
                sessions.save(child)
                results.append(self.choose(uid,chat_id,'media',child['nonce'],0,dialog))
            return results[-1] if results else None
        if index is not None and state.get('stage') in ('media','release') and state.get('candidates' if state['stage']=='media' else 'releases'):
            return self.choose(uid, chat_id, state['stage'], state['nonce'], index, dialog, receipt_id=receipt_id)
        had_state = bool(state)
        if receipt_id:
            if not state:
                state={'thread_id':secrets.token_hex(5),'stage':'media','nonce':secrets.token_hex(5),
                       'expires':time.time()+sessions.TTL,'context':[]}
                sessions.save(state)
            sessions.bind(state,receipt_id)
            sessions.bind(state,message_id)
        try:
            context = state.get('context', [])
            if not had_state and re.match(r'^(?:удали|удалить|приостанови|пауза|продолжи|покажи|сколько места|что скачано)\b',text,re.I):
                context = dialog.conversation(uid)[-10:] if hasattr(dialog,'conversation') else []
                if context and context[-1].get('content')==text: context=context[:-1]
            if callable(getattr(type(self.resolver),'identify_with_progress',None)):
                with RequestProgress(dialog,chat_id,receipt_id,transcript=transcript) as progress:
                    result=self.resolver.identify_with_progress(text,context,progress.update)
            else:
                result = self.resolver.identify(text, context)
        except Exception:
            return self._show(uid,chat_id,{**state,'loading_message_id':receipt_id,'voice_transcript':transcript},dialog,'Сейчас не удалось проверить фильм. Попробуй ещё раз чуть позже.')
        candidates = result.get('candidates', [])[:5]
        candidates = [c for c in candidates if isinstance(c,dict) and isinstance(c.get('title'),str) and c['title'].strip() and c.get('kind') in ('movie','show')]
        context = (state.get('context', []) + [{'role':'user','content':text[:4000]},
                    {'role':'assistant','content':json.dumps(result,ensure_ascii=False)[:5000]}])
        if len(context)>10: context=context[:1]+context[-9:]
        old_state = state
        state = {'stage':'media','nonce':secrets.token_hex(5),'expires':time.time()+sessions.TTL,
                 'thread_id':state.get('thread_id') or secrets.token_hex(5),
                 'candidates':candidates,'context':context,'loading_message_id':receipt_id,'voice_transcript':transcript}
        sessions.save(state)
        sessions.bind(state, message_id)
        if old_state.get('choice_message_id'):
            dialog.retire_markup(chat_id, old_state['choice_message_id'])
        action=result.get('action','find' if candidates else 'reply')
        if action not in ('find','reply'):
            state['stage']='done'
            sessions.save(state)
            outcome = dialog.resolve_intent(uid,chat_id,result,source=source)
            if receipt_id:
                self._show(uid,chat_id,state,dialog,'Запрос обработан.')
            return outcome
        if not candidates:
            return self._show(uid,chat_id,state,dialog,telegram_html(result.get('reply') or 'Уточни название, год или сюжет.'))
        lines = [telegram_html(result.get('reply') or 'Выбери фильм или сериал:',1500)]
        buttons=[]
        for i,c in enumerate(candidates):
            label = c['title'][:150]
            label = label + (' ('+str(c['year'])+')' if c.get('year') else '')
            label += ' · сериал' if c.get('kind')=='show' else ' · фильм'
            if c.get('season'):label += ' · сезон '+str(c['season'])
            candidate_text='<b>'+str(i+1)+'. '+escape(label)+'</b>'
            if c.get('original_title') and c['original_title']!=c['title']:
                candidate_text+='\n<i>'+escape(c['original_title'])+'</i>'
            lines.append(candidate_text)
            buttons.append([{'text':str(i+1)+'. '+label[:55], 'callback_data':'media:'+state['nonce']+':'+str(i)}])
        lines.append('Можно ответить номером или словами.')
        markup={'inline_keyboard':buttons}
        if transcript:
            return self._show(uid,chat_id,state,dialog,'\n'.join(lines),markup)
        # One relevant poster per identity.
        limit=1
        def collect_photos(c,limit):
            if not self.allow_remote_images:return []
            photos=[]
            if self.images:
                try:
                    if hasattr(self.images,'for_media_gallery'):
                        photos=self.images.for_media_gallery(c,language='ru',limit=limit)
                    elif hasattr(self.images,'for_media'):
                        photos=[self.images.for_media(c,language='en' if self.role_for(uid,dialog)=='owner' else 'ru')]
                    else:
                        photos=[self.images(c['title']+' '+str(c.get('year') or '')+' poster')]
                except Exception:
                    photos=[]
            photos=list(dict.fromkeys(p for p in list(photos)+c.get('source_images',[]) if isinstance(p,str) and p.startswith('https://')))[:limit]
            return photos
        with RequestProgress(dialog,chat_id,receipt_id,transcript=transcript) as progress:
            if self.images:progress.update('images')
            with ThreadPoolExecutor(max_workers=min(3,len(candidates)),thread_name_prefix='posters') as pool:
                galleries=list(pool.map(lambda candidate:collect_photos(candidate,limit),candidates))
        def alternatives():
            return [collect_photos(c,3) for c in candidates]
        rich_lines=list(lines)
        if self.images and hasattr(self.images,'ATTRIBUTION') and any(galleries):
            rich_lines[-1]+=' Постеры: TMDB.'
        sent=send_candidate_gallery(dialog,chat_id,candidates,rich_lines,markup,galleries,
            per_candidate_limit=limit,alternatives=alternatives)
        if sent is not None:
            if hasattr(dialog,'remember'):dialog.remember(uid,'assistant',plain_text('\n'.join(lines)))
            if hasattr(dialog,'track_markup'):dialog.track_markup(chat_id,sent,markup)
            if state.get('loading_message_id'):
                loading=state.pop('loading_message_id')
                try:dialog.edit_html(chat_id,loading,'🎬 Нашёл варианты — выбери фильм ниже.')
                except Exception:pass
            sessions.bind(state,sent.get('message_id'))
            state['choice_message_id']=sent.get('message_id')
            sessions.save(state)
            return sent
        return self._show(uid,chat_id,state,dialog,'\n'.join(lines),markup)


    def _request_lock(self,uid,nonce):
        key=(uid,nonce)
        with self._lock_guard:
            lock=self._locks.get(key)
            if lock is None:lock=threading.RLock();self._locks[key]=lock
            return lock

    def catalog(self,uid,chat_id,state,dialog,enrich=True):
        with self._request_lock(uid,state['nonce']):
            return self._catalog(uid,chat_id,state,dialog,enrich)

    def _catalog(self,uid,chat_id,state,dialog,enrich=True):
        from bot.release_catalog import catalog_page
        from bot.download_forecast import records_for, predict, forecast_line
        if self.details:
            for row in state['releases']:
                cached=self.details.cached(row)
                if cached:row['details']=cached
        indices,page,pages=catalog_page(state)
        state['page']=page
        records=records_for(dialog.jobs,uid)
        lines=[film_card(state['selected'],{},0)+'\nВыбери вариант. Раздач: '+str(len(state['releases']))+
               ' · страница '+str(page+1)+'/'+str(pages)+
               (' · по размеру ↑' if state.get('sort')=='size' else ' · по раздающим ↓')]
        if state.get('search_incomplete'):
            lines.append('Часть запросов не завершилась. Показываю найденные раздачи.')
        buttons=[]
        for i in indices:
            r=state['releases'][i]
            lines.append(release_card(i+1,r)+'\n'+forecast_line(predict(records,r)))
            buttons.append([{'text':release_button(i+1,r),'callback_data':'release:'+state['nonce']+':'+str(i)}])
        if any(state['releases'][i].get('details') for i in indices):lines.append('<i>Параметры из описания раздачи; в сборниках могут отличаться между сериями.</i>')
        if not indices:lines.append('Для этого качества раздач нет. Выбери «Все».')
        def button(label,action):return {'text':label,'callback_data':'catalog:'+state['nonce']+':'+action}
        nav=[]
        if page:nav.append(button('← Назад','p'+str(page-1)))
        if page+1<pages:nav.append(button('Далее →','p'+str(page+1)))
        if nav:buttons.append(nav)
        buttons.append([button('Размер ↑','size'),button('Раздают ↓','seeds')])
        buttons.append([button(label,key) for label,key in [('Все','all'),('4К','uhd'),('Full HD','fhd'),('HD','hd'),('Другие','other')]])
        state['loading_message_id']=state.get('status_message_id') or state.get('choice_message_id') or state.get('loading_message_id')
        SearchSessions(dialog.jobs,uid).save(state)
        sent=self._show(uid,chat_id,state,dialog,'\n\n'.join(lines),{'inline_keyboard':buttons})
        if enrich and self.details:self._enrich_catalog(uid,chat_id,state,indices,dialog)
        return sent

    def _enrich_catalog(self,uid,chat_id,state,indices,dialog):
        from bot.release_details import topic_url
        sessions=SearchSessions(dialog.jobs,uid);nonce=state['nonce'];thread_id=state['thread_id']
        view=(state.get('page',0),state.get('sort'),state.get('quality_filter'))
        def current():
            latest=sessions.load(thread_id)
            return latest.get('stage')=='release' and latest.get('nonce')==nonce and not latest.get('details_suspended') and (latest.get('page',0),latest.get('sort'),latest.get('quality_filter'))==view
        def complete(results):
            lock=self._request_lock(uid,nonce)
            if not lock.acquire(blocking=False):return
            try:
                if not current():return
                latest=sessions.load(thread_id)
                for row in latest['releases']:
                    if topic_url(row) in results:row['details']=results[topic_url(row)]
                self.catalog(uid,chat_id,latest,dialog,enrich=False)
            finally:lock.release()
        rows=[state['releases'][i] for i in indices if topic_url(state['releases'][i]) and self.details.cached(state['releases'][i]) is None]
        if rows:self.details.submit((uid,nonce,view),rows,current,complete)

    def browse(self,uid,chat_id,nonce,action,dialog):
        with self._request_lock(uid,nonce):return self._browse(uid,chat_id,nonce,action,dialog)

    def _browse(self,uid,chat_id,nonce,action,dialog):
        state=SearchSessions(dialog.jobs,uid).choice(nonce)
        if state.get('stage')!='release' or state.get('nonce')!=nonce or state.get('expires',0)<time.time():
            return send_html(dialog,chat_id,'Этот выбор завершён. Остальные сообщения с раздачами работают независимо.')
        if action.startswith('p') and action[1:].isdigit():state['page']=int(action[1:])
        elif action in ('size','seeds'):state.update(sort=action,page=0)
        elif action in ('all','uhd','fhd','hd','other'):state.update(quality_filter=action,page=0)
        else:return
        return self.catalog(uid,chat_id,state,dialog)

    def choose(self,uid,chat_id,stage,nonce,index,dialog,receipt_id=None):
        lock=self._request_lock(uid,nonce)
        if stage=='media':
            if not lock.acquire(blocking=False):return
            try:return self._choose(uid,chat_id,stage,nonce,index,dialog,receipt_id)
            finally:lock.release()
        with lock:return self._choose(uid,chat_id,stage,nonce,index,dialog,receipt_id)

    def _choose(self,uid,chat_id,stage,nonce,index,dialog,receipt_id=None):
        sessions=SearchSessions(dialog.jobs,uid)
        state=sessions.choice(nonce)
        if receipt_id:
            state['loading_message_id']=receipt_id
        if state.get('stage')=='queued':
            name=(state.get('selected') or {}).get('title','Этот фильм')
            return send_html(dialog,chat_id,'<b>'+escape(name)+'</b> уже передан в очередь загрузок. Текущее состояние — в разделе «Загрузки».')
        if state.get('nonce') != nonce or state.get('stage') != stage or state.get('expires',0)<time.time():
            return self._show(uid,chat_id,state,dialog,'Этот выбор уже завершён или устарел. Напиши запрос ещё раз.')
        rows=state.get('candidates' if stage=='media' else 'releases',[])
        if not 0<=index<len(rows):
            return self._show(uid,chat_id,state,dialog,'Выбери номер из показанного списка.')
        row=rows[index]
        if stage=='media':
            if row.get('kind')=='show' and not row.get('season'):
                state.update(stage='season',selected=row,candidates=[])
                sessions.save(state)
                if state.get('choice_message_id'):dialog.retire_markup(chat_id,state['choice_message_id'])
                return self._show(uid,chat_id,state,dialog,'Выбран сериал <b>«'+escape(row['title'])+'»</b>'+(' ('+str(row['year'])+')' if row.get('year') else '')+'. Какие сезоны хочешь посмотреть? Например: 1–3 или 1,5.')
            selection_context={'role':'user','content':'Выбран фильм или сериал: '+str(row)}
            if not state.get('context') or state['context'][-1] != selection_context:
                history=state.get('context',[])+[selection_context]
                state['context']=history if len(history)<=10 else history[:1]+history[-9:]
                sessions.save(state)
            if self.indexer is None:
                return self._show(uid,chat_id,state,dialog,'Фильм определён: '+escape(row['title'])+'. Поиск раздач ещё настраивается. Пока можно прислать magnet-ссылку или файл .torrent.')
            from bot.release_search import find_releases
            retry={'inline_keyboard':[[{'text':'Повторить поиск','callback_data':'media:'+nonce+':'+str(index)}]]}
            def progress(attempt, reason, delay):
                if state.get('status_message_id'):state['loading_message_id']=state['status_message_id']
                text='🔎 Ищу раздачи для <b>«'+escape(row['title'])+'»</b>.\nПопытка '+str(attempt)+'.'
                if reason:
                    text+='\n'+escape(reason)
                    text+=(' Повторяю поиск.' if delay is None else ' Ожидаю восстановления до '+str(delay)+' сек., затем проверю, можно ли повторить поиск.')
                loading=self._show(uid,chat_id,state,dialog,text,{'inline_keyboard':[]})
                state['loading_message_id']=loading.get('message_id')
                state['status_message_id']=loading.get('message_id')
                state['search_attempts']=attempt
                sessions.bind(state,loading.get('message_id'))
                sessions.save(state)
            result=find_releases(self.indexer,row,progress)
            releases=rank_releases(result.rows,row)
            state['search_incomplete']=result.incomplete
            if result.incomplete and not releases:
                state['expires']=time.time()+sessions.TTL
                sessions.save(state)
                return self._show(uid,chat_id,state,dialog,film_card(row,{},0)+'\n\n'+result.reason+
                    '\nНе удалось завершить поиск. Попыток: '+str(result.attempts)+'. Автоматические повторы завершены.'+
                    '\nМожно повторить поиск этого фильма позже — кнопка работает и после других запросов.',retry)
            if not releases:
                return self._show(uid,chat_id,state,dialog,film_card(row,{},0)+'\n\nПоиск выполнен, но подходящих раздач с раздающими не найдено. Можно повторить поиск, уточнить название или прислать свой .torrent.',retry)
            if state.get('choice_message_id'):
                dialog.retire_markup(chat_id,state['choice_message_id'])
            state.update(stage='release',nonce=secrets.token_hex(5),selected=row,releases=releases,expires=time.time()+sessions.TTL)
            sessions.save(state)
            best=releases[0]
            if self.role_for(uid,dialog)=='mother' and suitable_release(best):
                result=self.choose(uid,chat_id,'release',state['nonce'],0,dialog)
                if sessions.load(state['thread_id']).get('stage')=='queued':
                    return result
            return self.catalog(uid,chat_id,state,dialog)
        state['details_suspended']=True
        sessions.save(state)
        # Reuse this request's card for fetching, retry, queue and transfer progress.
        previous_status=state.get('status_message_id') or state.get('choice_message_id')
        if previous_status:
            receipt=state.get('loading_message_id')
            if receipt and receipt!=previous_status:
                try:dialog.delete_message(chat_id,receipt)
                except Exception:pass
            state['loading_message_id']=previous_status
        fetching=self._show(uid,chat_id,state,dialog,
            film_card(state['selected'],release_metadata(row),int(row.get('size') or 0))+
            '\n\n⏳ Получаю торрент. При временном сбое повторяю попытки до 5 минут.',
            {'inline_keyboard':[]})
        state['status_message_id']=fetching.get('message_id')
        state['loading_message_id']=fetching.get('message_id')
        sessions.save(state)
        try:
            payload=self.indexer.download(row)
        except Exception:
            self._show(uid,chat_id,state,dialog,'Не удалось получить торрент после попыток восстановления. Выбор сохранён — повтори или выбери другую раздачу.')
            state.pop('details_suspended',None)
            return self.catalog(uid,chat_id,state,dialog)
        payload.update(action='add',kind=state['selected']['kind'],name=row['title'][:250],
                       season=state['selected'].get('season'))
        size=int(row.get('size') or 0)
        payload['media'] = state['selected']
        payload['quality'] = {**release_metadata(row), 'seeders':int(row.get('seeders') or 0)}
        if row.get('leechers') is not None: payload['quality']['leechers']=int(row['leechers'])
        if size>0:payload['size_bytes']=size
        sent = self._show(uid,chat_id,state,dialog,film_card(state['selected'],payload['quality'],size,int(row.get('seeders') or 0))+
                         '\n\n⏳ Передаю загрузку на сервер медиатеки.')
        if sent.get('message_id'): payload['message_id'] = sent['message_id']
        dialog.jobs.enqueue('choice:'+str(uid)+':'+nonce,uid,payload)
        history=state.get('context',[])+[{'role':'user','content':'Выбрана раздача: '+str(row.get('title',''))}]
        state['context']=history if len(history)<=10 else history[:1]+history[-9:]
        state['stage']='queued'
        sessions.save(state)
        return sent


def send_html(dialog,chat_id,text,markup=None):
    if hasattr(dialog,'send_html'):
        return dialog.send_html(chat_id,text,markup) if markup is not None else dialog.send_html(chat_id,text)
    return dialog.send(chat_id,plain_text(text),markup) if markup is not None else dialog.send(chat_id,plain_text(text))


def release_metadata(row):
    title=row.get('title','')
    patterns={
        'resolution':r'\b(?:\d{3,4}[pi]|[248][KК]|UHD|Full[ -]?HD|HD|\d{3,5}[xх×]\d{3,5})\b',
        'source':r'\b(?:BDRemux|BDRip(?:-AVC)?|BluRay|BR-DISK|WEB-DL(?:-AVC)?|WEBRip|HDRip|DVDRip(?:-AVC)?|DVD[59])\b',
        'codec':r'\b(?:HEVC|AVC|x26[45]|H[.]26[45])\b',
        'audio':r'\b(?:DTS(?:-HD)?|TrueHD|AAC|AC3|E-AC-3|DDP|FLAC|Dub|DVO|MVO|AVO|Original Eng|Original Rus)\b',
        'bitrate':r'(?<![\w.])\d+(?:[.,]\d+)?\s*(?:Mbps|Mb/s|kbps|kb/s|Мбит/с|Кбит/с)(?!\w)',
    }
    values={}
    for name,pattern in patterns.items():
        found=re.search(pattern,title,re.I)
        if found:values[name]=found.group()
    published=row.get('publishDate')
    if isinstance(published,str):
        try:values['published']=datetime.fromisoformat(published.replace('Z','+00:00')).strftime('%d.%m.%Y')
        except ValueError:pass
    return values


def release_details(row):
    from bot.release_catalog import size_icon
    parts=[size_icon(row)+' %.1f ГБ' % (int(row.get('size') or 0)/1024**3), 'раздают: %d' % int(row.get('seeders') or 0)]
    if row.get('leechers') is not None:parts.append('скачивают: %d' % int(row['leechers']))
    metadata=release_metadata(row)
    parts.extend(metadata[key] for key in ('codec','audio') if key in metadata)
    return ' · '.join(parts)


def release_card(index,row):
    metadata=release_metadata(row)
    from bot.release_catalog import quality_label
    quality=quality_label(row)+' · '+metadata.get('source','Раздача')
    size,_,details=release_details(row).partition(' · ')
    lines=['<b>%d. %s</b>' % (index,escape(quality)), '<b>'+escape(size)+'</b> · '+escape(details)]
    if metadata.get('published'):lines.append('Раздача: '+metadata['published'])
    technical=row.get('details',{})
    if technical.get('width') and technical.get('height'):lines.append('📐 '+' / '.join(str(w)+'×'+str(h) for w,h in (technical.get('resolutions') or [[technical['width'],technical['height']]])[:4])+((' · '+escape(technical['video_codec'])) if technical.get('video_codec') else ''))
    if technical.get('video_mbps'):lines.append('🎥 Видео ≈ '+str(technical['video_mbps'])+' Мбит/с')
    if technical.get('languages'):lines.append('🗣 Указаны языки: '+escape(', '.join(technical['languages'])))
    from bot.release_details import topic_url
    url=topic_url(row)
    if url:lines.append('<a href="'+escape(url,quote=True)+'">Открыть раздачу</a>')
    return '\n'.join(lines)


def suitable_release(row):
    return (bool(re.search(r'1080[pi]',row.get('title',''),re.I))
            and int(row.get('seeders') or 0)>=10
            and 8<=int(row.get('size') or 0)/1024**3<=32)


def release_button(index,row):
    from bot.release_catalog import quality_label, size_icon
    resolution=quality_label(row)+' '+size_icon(row)
    return '⬇ %d · %s · %.1f ГБ · ↑%d' % (index,resolution,int(row.get('size') or 0)/1024**3,int(row.get('seeders') or 0))
