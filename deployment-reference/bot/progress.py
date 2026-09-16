"""Persistent dashboard with recent and lifetime remaining durations."""
import re

import html
import math
import statistics
import time

from bot.library_dialog import human_size
from bot.media_labels import film_card
from bot import remaining_time

MILESTONES=(25,50,75,90,95,99)


def progress_markup(torrent):
    h = torrent.get('hashString') or torrent.get('hash')
    if not h or torrent.get('percentDone',0)>=1:
        return {'inline_keyboard': []}
    priority, emoji = {0:('Средний','🟡'),1:('Высокий','🔴'),-1:('Низкий','🟢')}.get(torrent.get('bandwidthPriority',0),('Средний','🟡'))
    return {'inline_keyboard': [
        [{'text':emoji+' Приоритет: '+priority, 'callback_data':'priority:'+h}]]}


def progress_bar(percent):
    percent=min(100,max(0,float(percent)))
    halves=36 if percent>=100 else min(35,int(percent*36/100+.5))
    full,half=divmod(halves,2)
    return '█'*full+('▌' if half else '')+'░'*(18-full-half)


def progress_text(state, torrent, now):
    name = html.escape(str(torrent.get('name') or state['name'])[:240])
    total = max(0, int(torrent.get('sizeWhenDone') or torrent.get('totalSize') or 0))
    left = max(0, int(torrent.get('remaining_bytes', torrent.get('leftUntilDone', total))))
    complete = (total > 0 and torrent.get('percentDone', 0) >= 1 and left == 0
                and torrent.get('status') not in (1, 2)
                and not torrent.get('errorString') and not torrent.get('capacity_error'))
    if torrent.get('files'):
        complete = complete and all(f.get('bytesCompleted', 0) >= f.get('length', 0) for f in torrent['files'])
    label = '✅ Готово' if complete else '⬇️ Загружается'
    stopped = torrent.get('status') in (0, 1, 2, 3) or torrent.get('errorString') or torrent.get('capacity_error')
    if not complete:
        if torrent.get('capacity_error'):
            label = '⏸ Нужна проверка свободного места' if torrent['capacity_error'] == 'insufficient_space' else '⏸ Ожидаю размер раздачи'
        elif torrent.get('status') in (1, 2):
            label = '🔎 Проверка файлов'
        elif torrent.get('errorString'):
            label = '⚠️ Ошибка загрузки'
        elif torrent.get('system_pause') == 'disk_unavailable':
            label = '⏸ Проверяю диск — продолжу после восстановления'
        elif torrent.get('queue_paused'):
            label = '⏳ В очереди — заняты места для одновременных загрузок'
        elif torrent.get('status') == 0:
            label = '⏸ На паузе'
        elif torrent.get('status') == 3:
            label = 'В очереди Transmission'
    done=max(0,total-left)
    if stopped or complete:
        reset_eta(state)
        estimate={'speed':0,'eta':None,'stalled':False,'unstable':False}
    else:
        # Retain the legacy EMA only for bootstrap history used by new selections.
        estimate=adaptive_eta(state,done,left,now)
    remaining = remaining_time.observe(state, torrent, now)
    if remaining['stalled']:label='⏳ Ожидаю данные от участников'
    percent=min(100,max(0,torrent.get('percentDone',0)*100))
    lines=['<b>%s</b>\n<b>%s</b>' % (name,label),'%s из %s' % (human_size(done),human_size(total))]
    media=torrent.get('media',{})
    if media.get('original_title') and media['original_title']!=media.get('title'):
        lines.insert(1,'<i>'+html.escape(media['original_title'])+'</i>')
    quality=torrent.get('quality',{})
    details=[quality[k] for k in ('source','resolution','audio','bitrate') if quality.get(k)]
    if details: lines.insert(1,html.escape(' · '.join(details)))
    # Tracker counts may describe only a local swarm; -1 means unknown.
    # Show the actual client connections, never a cached search population.
    sending = torrent.get('peersSendingToUs')
    connected = torrent.get('peersConnected')
    if (isinstance(sending, int) and sending >= 0
            and isinstance(connected, int) and connected >= 0):
        peer_line = 'Передают вам: %d · подключено: %d' % (sending, connected)
    else:
        peer_line = 'Участники: нет свежих данных'
    lines.insert(-1, peer_line)
    eta_note='Время будет рассчитано после возобновления загрузки.' if stopped else 'Оцениваю время — нужны первые 30–60 секунд прогресса.'
    if stopped and not complete:
        rate=history_rate(state.get('speed_history',[]),now) or history_rate(state.get('bootstrap_history',[]),now)
        if rate and total:
            from bot.download_forecast import duration
            eta_note='С нуля: ≈ '+duration(total/rate)+' после запуска; ожидание не включено.'
        else:
            eta_note='С нуля: пока недостаточно истории для прогноза.'
    eta_notes = remaining_time.lines(remaining, stopped=stopped or complete)
    if (not stopped and not complete and not remaining['stalled']
            and remaining['recent'] is None and remaining['full'] is None
            and estimate.get('prior_speed') and left > 0):
        from bot.download_forecast import duration
        eta_notes = ['Осталось: ≈ '+duration(left/estimate['prior_speed'])
                     +' · Предварительно по истории; уточняю текущий темп.']

    if torrent.get('errorString'):
        lines.append(html.escape(str(torrent['errorString'])[:300]))
    checking=torrent.get('status') in (1,2)
    if checking:
        lines.append('%.1f%% загрузки' % percent)
        percent=min(100,max(0,torrent.get('recheckProgress',0)*100))
        eta_note='После проверки обновлю прогноз скачивания.'
    elif torrent.get('recovery_note') and not complete and not stopped:
        lines.append(html.escape(str(torrent['recovery_note'])[:300]))
    lines.append(progress_bar(percent)+' · %.1f%%' % percent+(' проверки' if checking else ''))
    for note in (eta_notes or ['Доступно на сервере медиатеки.' if complete else eta_note]):
        lines.append('<i>'+note+'</i>')
    return '\n'.join(lines), complete


def history_rate(history, now):
    # One-minute observations, bounded retention, robust clipping of isolated extremes.
    recent=[(t,r) for t,r in history if 0 <= now-t <= 7*86400 and r>0 and math.isfinite(r)]
    if not recent:return None
    center=statistics.median(r for _,r in recent)
    weights=[math.exp(-(now-t)/1800) for t,_ in recent]
    return sum(w*min(center*3,max(center/3,r)) for w,(_,r) in zip(weights,recent))/sum(weights)


def reset_eta(state):
    state['samples']=[]
    state.pop('eta_model',None)


def _mix(previous,current,dt,tau):
    """Exponential time decay: newer observations always have greater weight."""
    return previous+(current-previous)*(-math.expm1(-dt/tau))


def _value_at(samples,when):
    for first,second in zip(samples,samples[1:]):
        if first[0]<=when<=second[0]:
            return first[1]+(second[1]-first[1])*(when-first[0])/(second[0]-first[0])
    return samples[0][1] if when<=samples[0][0] else samples[-1][1]


def adaptive_eta(state,done,left,now):
    """A smooth EMA forecast; recent measured speed is shown independently.

    Forecast time constant grows from 60 toward 300 seconds. Persistent disagreement
    with a 30-second EMA and proximity to completion smoothly shorten it toward 60s.
    No historical bytes from a pause, outage, counter reset or stall enter the EMA.
    """
    samples=state.get('samples',[])
    model=state.get('eta_model',{})
    if samples and (now<samples[-1][0] or now-samples[-1][0]>180 or done<samples[-1][1]):
        samples=[];model={}
    if not samples:
        model={'start':now,'last_progress':now,'confidence':0.,'variation':0.}
        samples=[[now,done]]
    elif now>samples[-1][0]:
        dt=now-samples[-1][0];delta=done-samples[-1][1]
        if model.get('stalled') and delta>0:
            model={'start':now,'last_progress':now,'confidence':0.,'variation':0.}
            samples=[[now,done]]
        else:
            model.setdefault('start',samples[0][0]);model.setdefault('last_progress',samples[-1][0])
            rate=max(0,delta/dt)
            if delta>0:
                if 'progress_start' not in model:
                    samples=[samples[-1]]
                    model={'start':samples[-1][0],'progress_start':samples[-1][0],
                           'confidence':0.,'variation':0.}
                model['last_progress']=now
            previous=model.get('rate',rate)
            fast=_mix(model.get('fast',previous),rate,dt,30)
            discrepancy=abs(math.log(max(fast,1e-9)/max(previous,1e-9)))
            confidence=_mix(model.get('confidence',0),math.tanh(discrepancy),dt,60)
            prior_fast=model.get('fast',previous)
            variation=abs(rate-prior_fast)/max(rate+prior_fast,1e-9)
            model['variation']=_mix(model.get('variation',0),variation,dt,60)
            base=60+240*(-math.expm1(-(now-model['start'])/240))
            remaining=left/max(previous,1e-9)
            proximity=remaining/(remaining+600)
            tau=60+(base-60)*proximity*math.exp(-7*confidence)
            model.update(rate=_mix(previous,rate,dt,tau),fast=fast,confidence=confidence,tau=tau)
            samples.append([now,done])
    if now-model.get('last_progress',now)>=120:
        model['stalled']=True
    # Exact clipping retains an interpolated boundary, so sampling cadence does not
    # bias the visible one-minute speed or grow persistence indefinitely.
    cutoff=now-300
    if samples[0][0]<cutoff:
        boundary=_value_at(samples,cutoff)
        samples=[[cutoff,boundary]]+[sample for sample in samples if sample[0]>cutoff]
    state['samples']=samples[-302:]
    state['eta_model']=model
    elapsed=now-samples[0][0]
    recent_start=max(samples[0][0],now-60)
    speed=(done-_value_at(samples,recent_start))/(now-recent_start) if now>recent_start and elapsed>=30 else None
    ready=now-model.get('progress_start',now)>=60 and model.get('rate',0)>0
    unstable=model.get('variation',0)>.6
    stalled=model.get('stalled',False)
    history=state.get('speed_history',[])
    prior=history_rate(history,now)
    if prior is None:
        prior=history_rate(state.get('bootstrap_history',[]),now)
    age=max(0,now-model.get('progress_start',now))
    rate=model.get('rate',0)
    preliminary=bool(prior and age<180)
    if prior:
        weight=max(0.,1-age/180)**2
        rate=prior if not ready else prior*weight+rate*(1-weight)
    eta=left/rate if rate>0 and (ready or prior) and not stalled and not unstable else None
    if ready and not stalled and not unstable and (not history or now-history[-1][0]>=60):
        history.append([now,model['rate']])
        state['speed_history']=[v for v in history if now-v[0]<=7*86400][-720:]
    return {'speed':speed,'eta':eta,'stalled':stalled,'unstable':unstable,
            'preliminary':preliminary,'prior_speed':prior,'window':model.get('tau',60)}


def eta_description(eta,now):
    from bot.download_forecast import duration
    return 'Осталось: ≈ '+duration(eta)


class ProgressMonitor:
    def __init__(self, dialog):
        self.dialog = dialog
        self.store = dialog.jobs

    def register(self, uid, result, now=None, adopted=False):
        now = time.time() if now is None else now
        torrent_hash = result.get('hash')
        if not torrent_hash:
            return
        key = 'transfer:%s:%s' % (uid, torrent_hash)
        previous = self.store.read_state(key)
        if previous and previous.get('active'):
            redundant = result.get('message_id')
            if redundant and redundant != previous.get('message_id'):
                previous['pending_delete'] = list(dict.fromkeys(previous.get('pending_delete', []) + [redundant]))
                self.store.write_state(key, previous)
            from bot.download_dashboard import publish
            publish(self.dialog, uid, now)
            return
        name = str(result.get('name') or 'Фильм')
        own_history=(previous or {}).get('speed_history',[])
        bootstrap=[]
        for old in self.store.read_states('transfer:').values():
            if old.get('uid')==uid and old.get('hash')!=torrent_hash:
                history=old.get('speed_history',[])
                rate=history_rate(history,now)
                if rate:bootstrap.append([history[-1][0],rate])
        from bot.download_forecast import records_for, predict
        prior=predict(records_for(self.store,uid), {'size':result.get('totalSize',0),
                      'seeders':result.get('quality',{}).get('seeders'),
                      'leechers':result.get('quality',{}).get('leechers')},now)
        if prior:bootstrap=[[now,prior['speed']]]
        state={'uid':uid,'hash':torrent_hash,'name':name,
            'speed_history':own_history,'bootstrap_history':bootstrap[-50:],
            'created':now,'last_edit':now,'samples':[],'active':True,'completed_notified':False,
            'markup':progress_markup(result),
            'milestones':[m for m in MILESTONES if adopted and m<=result.get('percentDone',0)*100]}
        total=result.get('sizeWhenDone') or result.get('totalSize') or 0
        torrent={**result,'status':result.get('status',0 if result.get('paused') else 4),
            'totalSize':total,'percentDone':result.get('percentDone',0),
            'leftUntilDone':result.get('leftUntilDone',int(total*(1-result.get('percentDone',0))))}
        text,_=progress_text(state,torrent,now)
        state.update(text=text, priority=result.get('bandwidthPriority',0), paused=bool(result.get('paused')), message_id=result.get('message_id'))
        self.store.write_state(key,state)
        from bot.download_dashboard import publish
        publish(self.dialog,uid,now,preferred=result.get('message_id'),fresh=not adopted)

    def tick(self, now=None, publish_updates=True):
        live_clock = now is None
        now = time.time() if now is None else now
        all_states = self.store.read_states('transfer:')
        states = {key: state for key, state in all_states.items() if state.get('active')}
        old_jobs=getattr(self.store,'successful_adds',lambda:[])()
        if not all_states and not old_jobs:
            return
        status = {}
        try:
            status = self.dialog.media_status()
            if live_clock: now = time.time()
            from bot.history_storage import sync_history
            try:sync_history(self.dialog,status,now)
            except Exception:pass
            available = status.get('disk_ok') is not False
            torrents = {t['hashString']: t for t in status.get('torrents', [])}
        except Exception:
            if live_clock: now = time.time()
            available = False
            torrents = {}
        from bot.queue_eta import observe as observe_queue
        queue_history = self.store.read_state('queue-eta-history', {})
        disk = dict(status.get('disk_summary') or {}, at=now)
        if status.get('disk_ok') is True:
            disk['forecast'] = observe_queue(queue_history, list(torrents.values()), now, disk)
            self.store.write_state('queue-eta-history', queue_history)
        self.store.write_state('disk-summary', disk)
        if available:
            for job in old_jobs:
                result=job.get('result') or {}
                torrent=torrents.get(result.get('hash'))
                uid=job.get('user_id')
                key='transfer:%s:%s' % (uid,result.get('hash'))
                if (not torrent or torrent.get('percentDone',0)>=1 or self.store.read_state(key) is not None):
                    continue
                try:
                    self.register(uid,{**result,**torrent,'name':torrent.get('name') or result.get('name'),
                                       'paused':torrent.get('status')==0,'percentDone':torrent.get('percentDone',0)},now,adopted=True)
                except Exception:continue
            states={key:state for key,state in self.store.read_states('transfer:').items() if state.get('active')}
        for key, state in states.items():
            try:
                torrent = torrents.get(state['hash'])
                complete = False
                state['status_unavailable'] = not available
                state['disk_missing'] = status.get('disk_ok') is False
                if not available:
                    since=state.setdefault('status_failure_since',now)
                    state['status_failure_count']=state.get('status_failure_count',0)+1
                    disk_missing=status.get('disk_ok') is False
                    if disk_missing:state.pop('remaining_model', None)
                    # A short status outage can span a valid byte-delta interval.
                    # remaining_time rejects gaps over 90s when fresh data returns.
                    prolonged=now-since>=45 and state['status_failure_count']>=3
                    label = '⏸ Диск недоступен' if disk_missing else '⏳ Служба загрузок не отвечает' if prolonged else '⏳ Обновление статуса задерживается'
                    text = '<b>%s</b>\n%s\nСтатус временно недоступен; загрузка могла продолжиться.' % (label, html.escape(state['name'][:240]))
                    if not disk_missing and not prolonged:
                        text='<b>%s</b>\n%s\nЖду свежие данные; загрузка могла продолжиться.' % (label,html.escape(state['name'][:240]))
                    snapshot=state.get('snapshot_text','')
                    details=[line for line in snapshot.splitlines() if re.match(r'^\d.* из ',line) or any(symbol in line for symbol in ('░','█','▌'))]
                    if details:text+='\n'+'\n'.join(details)+'\n<i>Последние полученные данные; жду обновления.</i>'
                    if disk_missing or prolonged:reset_eta(state)
                    history_key='download-history:%s:%s' % (state['uid'],state['hash'])
                    record=self.store.read_state(history_key,{})
                    record.pop('last',None)
                    if record:self.store.write_state(history_key,record)
                elif torrent is None:
                    state.pop('remaining_model', None)
                    text = '<b>Загрузка не найдена в Transmission</b>\n%s' % html.escape(state['name'][:240])
                    reset_eta(state)
                    state['missing_count'] = state.get('missing_count', 0) + 1
                else:
                    state.pop('status_failure_since',None)
                    state.pop('status_failure_count',None)
                    state['missing_count'] = 0
                    state['name'] = torrent.get('name') or state['name']
                    from bot.download_forecast import observe
                    history_key='download-history:%s:%s' % (state['uid'],state['hash'])
                    record=self.store.read_state(history_key,{})
                    record['hash']=state['hash']
                    observe(record,torrent,now)
                    self.store.write_state(history_key,record)
                    state['remaining_history'] = {k:record.get(k,0) for k in ('bytes','seconds')}
                    state['remaining_workload'] = remaining_time.workload(torrents.values())
                    text, complete = progress_text(state, torrent, now)
                if available and torrent:
                    state['snapshot_at'] = now
                    state['snapshot_text'] = text
                state.update(text=text, priority=(torrent or {}).get('bandwidthPriority',state.get('priority',0)), paused=(torrent.get('status')==0 and not torrent.get('queue_paused')) if torrent else state.get('paused',False))
                if complete:
                    state.update(completed_notified=True, active=False, completed_at=now)
                elif state.get('missing_count',0) >= 3:
                    state['active'] = False
                self.store.write_state(key,state)
            except Exception:
                continue
        if not publish_updates:
            return
        from bot.download_dashboard import publish
        uids = {s['uid'] for s in self.store.read_states('transfer:').values()}
        for uid in uids:
            try:
                publish(self.dialog,uid,now)
            except Exception:
                # Persisted per-film state allows retry after an edit failure or restart.
                continue
