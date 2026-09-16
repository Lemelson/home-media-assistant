"""Persisted film confirmation with automatic eligible movie recommendations."""
import re
import secrets
import time
import json
from html import escape
from datetime import datetime
from bot.rendering import telegram_html, plain_text
from bot.search_sessions import SearchSessions
from bot.media_labels import film_card
from bot.candidate_gallery import send_candidate_gallery


def rank_releases(rows, media=None):
    def normalized(value):
        return ' '.join(re.findall(r'[^\W_]+', value.casefold().replace('ё','е')))
    def matches(row):
        title=row.get('title','')
        if re.search(r'\b(?:EPUB|FB2|PDF|аудиокнига|саундтрек)\b',title,re.I):return False
        video=bool(re.search(r'\b(?:1080[pi]|2160p|720p|WEB-DL|WEBRip|BDRip|BDRemux|HDRip|DVDRip)\b',title,re.I))
        if re.search(r'\b(?:FLAC|MP3)\b',title,re.I) and not video:return False
        if not media:return True
        names=[media.get('title',''),media.get('original_title','')]
        if not any(normalized(n) and (' '+normalized(n)+' ') in (' '+normalized(title)+' ') for n in names):return False
        years=re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',title)
        if media.get('kind')=='movie' and media.get('year') and years and str(media['year']) not in years:return False
        if media.get('kind')=='show' and media.get('season'):
            seasons=set()
            for match in re.finditer(r'(?:\bS|сезоны?\s*[:№]?\s*)(\d{1,2})(?!\d)(?:\s*[-–—]\s*S?(\d{1,2})(?!\d))?',title,re.I):
                start=int(match.group(1))
                end=int(match.group(2)) if match.group(2) else start
                seasons.update(range(start,end+1))
            if len(seasons)!=1 or int(media['season']) not in seasons:return False
        categories=[c['id'] for c in row.get('categories',[]) if isinstance(c,dict) and type(c.get('id')) is int and c['id']<100000]
        if categories:
            low,high=(5000,6000) if media.get('kind')=='show' else (2000,3000)
            if not any(type(c) is int and low<=c<high for c in categories):
                pc_video=all(type(c) is int and 4000<=c<5000 for c in categories)
                identity=(media.get('kind')=='show' and media.get('season')) or (media.get('year') and str(media['year']) in years)
                if not (pc_video and video and identity):return False
        return True
    alive = [r for r in rows if int(r.get('seeders') or 0)>0 and matches(r)]
    def score(row):
        size=int(row.get('size') or 0)/1024**3
        seeds=int(row.get('seeders') or 0)
        hd=bool(re.search(r'1080[pi]',row.get('title',''),re.I))
        known_year=bool(media and media.get('kind')=='movie' and media.get('year') and re.search(r'(?<!\d)'+str(media['year'])+r'(?!\d)',row.get('title','')))
        return (known_year, hd, seeds>=10, 13<=size<=20, 8<=size<=32, 4<=size<=40, min(seeds,500), -abs(size-16))
    return sorted(alive,key=score,reverse=True)[:5]


def selection(text):
    words = {'первый':0,'первую':0,'второй':1,'вторую':1,'третий':2,'третью':2,'четвертый':3,'пятый':4}
    clean = text.casefold().strip().replace('ё','е')
    clean = re.sub(r'^(скачай|выбери|давай|загрузи)\s+', '', clean).strip()
    if clean in words:
        return words[clean]
    return int(clean)-1 if re.fullmatch(r'(?:[1-9]|10)',clean) else None


class SearchFlow:
    def __init__(self, resolver, indexer, images=None, role_for=None, allow_remote_images=True):
        self.allow_remote_images = allow_remote_images
        self.resolver, self.indexer, self.images = resolver, indexer, images
        self.role_for = role_for or (lambda uid,dialog: next((m['role'] for m in dialog.access.members() if m['user_id']==uid),'owner'))

    def handle_message(self, uid, chat_id, text, dialog, source, message):
        return self(uid, chat_id, text, dialog, source,
                    message_id=message.get('message_id'),
                    reply_to=message.get('reply_to_message', {}).get('message_id'),
                    receipt_id=message.get('_receipt_message_id'))

    def _show(self, uid, chat_id, state, dialog, text, markup=None):
        loading = state.pop('loading_message_id', None)
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

    def __call__(self, uid, chat_id, text, dialog, source=None, message_id=None, reply_to=None, receipt_id=None):
        event_key = 'search-event:'+str(uid)+':'+source if source is not None else None
        if event_key and dialog.jobs.read_state(event_key,False):
            return
        # Numeric choices consume mutable menus; retain their existing deduplication.
        # A new lookup has no completed result until rendering returns successfully.
        if event_key and selection(text) is not None:
            dialog.jobs.write_state(event_key,True)
        result = self._handle_request(uid,chat_id,text,dialog,source,message_id,reply_to,receipt_id)
        if event_key:
            dialog.jobs.write_state(event_key,True)
        return result

    def _handle_request(self, uid, chat_id, text, dialog, source=None, message_id=None, reply_to=None, receipt_id=None):
        sessions = SearchSessions(dialog.jobs, uid)
        latest = dialog.jobs.read_state('search:'+str(uid), {})
        state = sessions.reply(reply_to) if reply_to else {}
        index = selection(text)
        season_number = re.fullmatch(r'(?:сезон\s*)?([1-9]\d?)',text.strip(),re.I)
        if not state and not reply_to and latest.get('stage')=='season' and latest.get('expires',0)>time.time() and season_number:
            state=latest
        correction = bool(re.match(r'^(?:не тот|не та|ни тот|нет[, .]|я имею в виду|имею в виду|я про|фильм с |с акт[её]р|ты неправильно)', text.strip(), re.I))
        if not state and not reply_to and correction and latest.get('expires',0)>time.time() and latest.get('stage') in ('media','release','season'):
            state = latest
        if not state and not reply_to:
            active = sessions.active()
            if index is not None:
                selectable = [s for s in active if s.get('candidates' if s['stage']=='media' else 'releases')]
                if len(selectable) > 1:
                    return self._show(uid,chat_id,{'loading_message_id':receipt_id},dialog, 'Открыто несколько фильмов. Нажми кнопку под нужным фильмом или ответь на его сообщение.')
                state = selectable[0] if selectable else latest
            elif len(active) == 1 and not active[0].get('candidates'):
                # A year/season/short pronoun is a clarification; a new title starts a new request.
                if re.fullmatch(r'(?:\d{1,4}|(?:сезон|год)\s*\d{1,4}|да|нет)', text.strip(), re.I):
                    state = active[0]
        if reply_to and not state:
            return self._show(uid,chat_id,{'loading_message_id':receipt_id},dialog, 'Не могу связать это старое сообщение с фильмом. Пришли название и уточнение вместе — другие кнопки сохранены.')
        if state.get('stage')=='season' and season_number:
            chosen={**state['selected'],'season':int(season_number.group(1))}
            state.update(stage='media',candidates=[chosen])
            sessions.save(state)
            sessions.bind(state,message_id)
            return self.choose(uid,chat_id,'media',state['nonce'],0,dialog,receipt_id=receipt_id)
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
            result = self.resolver.identify(text[:4000], context)
        except Exception:
            return self._show(uid,chat_id,{**state,'loading_message_id':receipt_id},dialog,'Сейчас не удалось проверить фильм. Попробуй ещё раз чуть позже.')
        candidates = result.get('candidates', [])[:5]
        candidates = [c for c in candidates if isinstance(c,dict) and isinstance(c.get('title'),str) and c['title'].strip() and c.get('kind') in ('movie','show')]
        context = (state.get('context', []) + [{'role':'user','content':text[:4000]},
                    {'role':'assistant','content':json.dumps(result,ensure_ascii=False)[:5000]}])
        if len(context)>10: context=context[:1]+context[-9:]
        old_state = state
        state = {'stage':'media','nonce':secrets.token_hex(5),'expires':time.time()+sessions.TTL,
                 'thread_id':state.get('thread_id') or secrets.token_hex(5),
                 'candidates':candidates,'context':context,'loading_message_id':receipt_id}
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
            sources=c.get('sources',[])[:2]
            if sources:
                candidate_text+='\n'+ ' · '.join('<a href="'+escape(x['url'],quote=True)+'">Источник '+str(j+1)+'</a>' for j,x in enumerate(sources))
            lines.append(candidate_text)
            buttons.append([{'text':str(i+1)+'. '+label[:55], 'callback_data':'media:'+state['nonce']+':'+str(i)}])
        lines.append('Можно ответить номером или словами.')
        markup={'inline_keyboard':buttons}
        # One identity gets three photos; ambiguous choices get one photo per identity.
        limit=3 if len(candidates)==1 else 1
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
        galleries=[collect_photos(c,limit) for c in candidates]
        def alternatives():
            return [collect_photos(c,3) for c in candidates]
        rich_lines=list(lines)
        if self.images and hasattr(self.images,'ATTRIBUTION') and any(galleries):
            rich_lines[-1]+=' Постеры: TMDB.'
        sent=send_candidate_gallery(dialog,chat_id,candidates,rich_lines,markup,galleries,
            per_candidate_limit=limit,alternatives=alternatives if len(candidates)>1 else None)
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

    def choose(self,uid,chat_id,stage,nonce,index,dialog,receipt_id=None):
        sessions=SearchSessions(dialog.jobs,uid)
        state=sessions.choice(nonce)
        if receipt_id:
            state['loading_message_id']=receipt_id
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
                return self._show(uid,chat_id,state,dialog,'Выбран сериал <b>«'+escape(row['title'])+'»</b>'+(' ('+str(row['year'])+')' if row.get('year') else '')+'. Какой сезон хочешь посмотреть?')
            selection_context={'role':'user','content':'Выбран фильм или сериал: '+str(row)}
            if not state.get('context') or state['context'][-1] != selection_context:
                history=state.get('context',[])+[selection_context]
                state['context']=history if len(history)<=10 else history[:1]+history[-9:]
                sessions.save(state)
            if self.indexer is None:
                return self._show(uid,chat_id,state,dialog,'Фильм определён: '+escape(row['title'])+'. Поиск раздач ещё настраивается. Пока можно прислать magnet-ссылку или файл .torrent.')
            loading = self._show(uid,chat_id,state,dialog,'🔎 Ищу раздачи для <b>«'+escape(row['title'])+'»</b>.\n<i>Иногда это занимает несколько минут.</i>')
            state['loading_message_id'] = loading.get('message_id')
            sessions.bind(state, loading.get('message_id'))
            sessions.save(state)
            retry={'inline_keyboard':[[{'text':'Повторить поиск','callback_data':'media:'+nonce+':'+str(index)}]]}
            queries=list(dict.fromkeys(n for n in [row['title'],row.get('original_title')] if n))
            try:
                found={}
                for query in queries:
                    for release in self.indexer.search(query):
                        found[release.get('guid') or release['title']]=release
                    ranked=rank_releases(list(found.values()),row)
                    if len(ranked)>2 and suitable_release(ranked[0]):break
                releases=rank_releases(list(found.values()),row)
            except Exception:
                return self._show(uid,chat_id,state,dialog,'Поиск раздач сейчас недоступен. Выбор фильма сохранён — можно повторить поиск.',retry)
            if not releases:
                return self._show(uid,chat_id,state,dialog,'Подходящих вариантов с раздающими не нашлось. Можно уточнить название или прислать свой .torrent.',retry)
            if state.get('choice_message_id'):
                dialog.retire_markup(chat_id,state['choice_message_id'])
            state.update(stage='release',nonce=secrets.token_hex(5),selected=row,releases=releases)
            sessions.save(state)
            best=releases[0]
            if self.role_for(uid,dialog)=='mother' and suitable_release(best):
                result=self.choose(uid,chat_id,'release',state['nonce'],0,dialog)
                if dialog.jobs.read_state('search:'+str(uid),{}).get('stage')=='queued':
                    return result
            selected_name=(row.get('original_title') or row['title']) if self.role_for(uid,dialog)=='owner' else row['title']
            heading=selected_name+(' ('+str(row['year'])+')' if row.get('year') else '')
            if row.get('season'):heading+=' · сезон '+str(row['season'])
            lines=[film_card(row,{},0)+'\nВыбери вариант. Прогноз — по истории загрузок этого сервера; скорость может меняться.']
            from bot.download_forecast import records_for, predict, forecast_line
            records=records_for(dialog.jobs,uid)
            buttons=[]
            for i,r in enumerate(releases):
                lines.append(release_card(i+1,r)+'\n'+forecast_line(predict(records,r)))
                buttons.append([{'text':release_button(i+1,r),'callback_data':'release:'+state['nonce']+':'+str(i)}])
            return self._show(uid,chat_id,state,dialog,'\n\n'.join(lines),{'inline_keyboard':buttons})
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
            return self._show(uid,chat_id,state,dialog,'Не удалось получить торрент после попыток восстановления. Можно повторить или выбрать другую раздачу.',
                               {'inline_keyboard':[[{'text':release_button(i+1,rows[i]),'callback_data':'release:'+nonce+':'+str(i)}] for i in range(len(rows))]})
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
        'resolution':r'\b(?:2160p|1080[pi]|720p|\d{3,4}x\d{3,4})\b',
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
    parts=['%.1f ГБ' % (int(row.get('size') or 0)/1024**3), 'раздают: %d' % int(row.get('seeders') or 0)]
    if row.get('leechers') is not None:parts.append('скачивают: %d' % int(row['leechers']))
    metadata=release_metadata(row)
    parts.extend(metadata[key] for key in ('codec','audio','bitrate') if key in metadata)
    return ' · '.join(parts)


def release_card(index,row):
    metadata=release_metadata(row)
    quality=' · '.join(metadata[key] for key in ('source','resolution') if key in metadata) or 'Раздача'
    size,_,details=release_details(row).partition(' · ')
    lines=['<b>%d. %s</b>' % (index,escape(quality)), '<b>'+escape(size)+'</b> · '+escape(details)]
    if metadata.get('published'):lines.append('Раздача: '+metadata['published'])
    title=row.get('title','')
    label=title[:130]+('…' if len(title)>130 else '')
    lines.append('<i>'+escape(label)+'</i>')
    return '\n'.join(lines)


def suitable_release(row):
    return (bool(re.search(r'1080[pi]',row.get('title',''),re.I))
            and int(row.get('seeders') or 0)>=10
            and 8<=int(row.get('size') or 0)/1024**3<=32)


def release_button(index,row):
    resolution=release_metadata(row).get('resolution','формат не указан')
    return '⬇ %d · %s · %.1f ГБ · ↑%d' % (index,resolution,int(row.get('size') or 0)/1024**3,int(row.get('seeders') or 0))
