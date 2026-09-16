"""One dashboard; paginate only when its content exceeds Telegram limits."""
import html
import math
import re
import threading
import time

PUBLISH_LOCK = threading.RLock()
CONTROL_WAKE = threading.Event()

MESSAGE_BUDGET = 3800
MAX_BUTTONS = 80


def _stale(state, now):
    if state.get('completed_notified') or state.get('missing_count') or not state.get('active', True):
        return False
    return (state.get('status_unavailable', False)
            or (state.get('snapshot_at') is not None and now-state['snapshot_at'] > 45))


def render(states, page=0, now=None, disk_summary=None):
    now = time.time() if now is None else now
    # Count HTML and UTF-16 conservatively; leave room below Telegram's limit.
    for page_size in range(max(1, min(len(states), MAX_BUTTONS)), 0, -1):
        pages = max(1, math.ceil(len(states) / page_size))
        if all(len(_render_page(states, index, page_size, now, disk_summary)[0].encode('utf-16-le')) // 2 <= MESSAGE_BUDGET
               for index in range(pages)):
            return _render_page(states, page, page_size, now, disk_summary)
    return _render_page(states, page, 1, now, disk_summary)


def _render_page(states, page, page_size, now, disk_summary):
    states = sorted(states, key=lambda s: (s.get('created', 0), s['hash']))
    pages = max(1, math.ceil(len(states) / page_size))
    page = min(max(0, page), pages - 1)
    shown = states[page * page_size:(page + 1) * page_size]
    blocks = ['<b>⬇️ Загрузки</b>']
    if disk_summary is not None:
        from bot.disk_summary import render as render_disk
        blocks.append(render_disk(disk_summary, now))
    stale = [s for s in states if _stale(s, now)]
    if stale:
        ages = [max(0, now-s['snapshot_at']) for s in stale if s.get('snapshot_at') is not None]
        age = max(ages, default=0)
        if any(s.get('disk_missing') for s in stale):
            notice = '⏸ Диск недоступен. Проверяю подключение.'
        elif age >= 90 or any(now-s.get('status_failure_since', now) >= 90 for s in stale):
            notice = '⏳ Нет свежего статуса. Проверяю связь со службой загрузок.'
        else:
            notice = 'Обновляю данные.'
        stamp = ('Данные получены %d с назад.' % (int(age)//15*15) if ages
                 else 'Свежих данных пока нет.')
        blocks.append('<i>'+notice+' '+stamp+' Скорость и прогноз появятся после обновления.</i>')
    buttons = []
    for index, state in enumerate(shown, page * page_size + 1):
        lines = ['<b>%d. %s</b>' % (index, html.escape(state['name'][:120]))]
        if state.get('completed_notified'):
            lines.append('✅ Фильм скачан')
        else:
            text = state.get('text', '')
            if _stale(state, now):
                # Only durable quantities from the last successful snapshot; no stale rate/ETA.
                snapshot = state.get('snapshot_text', text)
                text = '\n'.join(line for line in snapshot.splitlines()
                                 if re.match(r'^\d.* из ', line)
                                 or any(symbol in line for symbol in ('░', '█', '▌')))
                if not text: text = '<i>Ожидаю первые данные.</i>'
            for line in text.splitlines():
                if (line.startswith(('<b>⬇', '<b>⏸', '<b>🔎', '<b>⚠', '<b>⏳', '<b>В очереди', 'Передают вам:', 'Участники:'))
                        or re.match(r'^\d.* из ', line) or '░' in line or '█' in line or '▌' in line):
                    lines.append(line)
            if 'не найдена' in text:
                lines.append('Загрузка не найдена в Transmission')
            if 'недоступен' in text:
                lines.append('Обновлю прогресс после восстановления связи.')
            estimates = [line for line in text.splitlines() if line.startswith('<i>')]
            timing = [line for line in estimates if line.startswith(('<i>Осталось:', '<i>По всей загрузке:', '<i>По наблюдениям бота:', '<i>Данных нет'))]
            for estimate_line in (timing or estimates[-1:]):
                estimate = estimate_line.removeprefix('<i>').removesuffix('</i>')
                lines.append('<i>' + estimate + '</i>')
            priority = state.get('priority', 0)
            label=('⏸ Пауза' if state.get('priority_pending') else '▶ Начать') if state.get('paused') else {1:'🔴 Высокий',0:'🟡 Средний',-1:'🟢 Низкий'}.get(priority,'🟡 Средний')
            buttons.append({'text':'%d %s%s'%(index,'⏳ ' if state.get('priority_pending') else '',label),'callback_data':'priority:'+state['hash']})
        blocks.append('\n'.join(lines))
    if not shown:
        blocks.append('Сейчас нет загрузок.')
    keyboard = [buttons[i:i+2] for i in range(0,len(buttons),2)]
    if pages > 1:
        keyboard.append([{'text':'‹', 'callback_data':'download-page:%d' % ((page-1)%pages)},
                         {'text':'%d / %d' % (page+1,pages),'callback_data':'download-page:%d' % page},
                         {'text':'›','callback_data':'download-page:%d' % ((page+1)%pages)}])
    if any(s.get('priority_pending') for s in shown):
        blocks.append('⏳ Смена приоритета сохранена. Жду подтверждения от Mac.')
    if buttons:
        blocks.append('Кнопка: 🟢 низкий → 🟡 средний → 🔴 высокий → ⏸ пауза → ▶ начать с низким.')
    return '\n\n'.join(blocks), {'inline_keyboard':keyboard}, page


CLEANUP_LOCK = threading.Lock()

def cleanup_pending(dialog, uid):
    if not CLEANUP_LOCK.acquire(blocking=False):return
    try:
        states={k:v for k,v in dialog.jobs.read_states('transfer:').items() if v.get('uid')==uid}
        current=dialog.jobs.read_state('download-dashboard:'+str(uid),{}).get('message_id')
        targets=list(dict.fromkeys(old for v in states.values() for old in v.get('pending_delete',[]) if old!=current))[:3]
        for old in targets:
            try:dialog.telegram.call('deleteMessage',chat_id=uid,message_id=old)
            except Exception as error:
                if 'message to delete not found' not in str(error).lower():continue
            with PUBLISH_LOCK:
                for key in states:
                    state=dialog.jobs.read_state(key,{})
                    state['pending_delete']=[x for x in state.get('pending_delete',[]) if x!=old]
                    dialog.jobs.write_state(key,state)
    finally:CLEANUP_LOCK.release()

def publish(dialog, uid, now, preferred=None, fresh=False, cleanup=True, wait=True, controls_only=False):
    if not PUBLISH_LOCK.acquire(blocking=wait):return False
    try:_publish(dialog, uid, now, preferred, fresh, False, controls_only)
    finally:PUBLISH_LOCK.release()
    if cleanup:cleanup_pending(dialog,uid)
    return True


def _publish(dialog, uid, now, preferred=None, fresh=False, cleanup=True, controls_only=False):
    store = dialog.jobs
    key = 'download-dashboard:' + str(uid)
    dashboard = store.read_state(key, {})
    all_states = {k:s for k,s in store.read_states('transfer:').items() if s.get('uid') == uid}
    states = [s for s in all_states.values() if s.get('active') or (s.get('completed_at') is not None and s['completed_at'] > now-300)]
    pending = {j['payload'].get('hash') for j in store.pending_priorities()}
    for original in states:
        confirmed = store.read_state('priority-confirmed:'+original['hash'], {})
        if confirmed.get('at',0) > original.get('snapshot_at',0):
            original['priority'] = confirmed['priority']
            original['paused'] = confirmed.get('paused',False)
        original['priority_pending'] = original['hash'] in pending
        desired=store.read_state('priority-desired:%s:%s'%(uid,original['hash']),{})
        job=store.get(desired['job_id']) if desired.get('job_id') else None
        if job and job['result'] is None:
            original['priority']=1 if desired['mode']==2 else desired['mode']
            original['paused']=desired['mode']==2
            original['priority_pending']=True

    text, markup, page = render(states, dashboard.get('page',0), now, store.read_state('disk-summary', {}))
    message_id = preferred or (None if fresh else dashboard.get('message_id'))
    if controls_only:
        if message_id and markup != dashboard.get('markup'):
            try:dialog.telegram.call('editMessageReplyMarkup',chat_id=uid,message_id=message_id,reply_markup=markup)
            except Exception as error:
                if 'message is not modified' not in str(error).lower():raise
            dashboard.update(markup=markup,last_control_edit=now)
            store.write_state(key,dashboard)
        return
    if fresh or text != dashboard.get('text') or markup != dashboard.get('markup') or not message_id:
        if message_id:
            try:
                dialog.telegram.call('editMessageText',chat_id=uid,message_id=message_id,
                                     text=text,parse_mode='HTML',reply_markup=markup)
            except Exception as exc:
                # Retry transient failures on the same message; replace only a deleted message.
                error = str(exc).lower()
                if 'message is not modified' in error:
                    pass
                elif 'message to edit not found' in error or 'message_not_found' in error:
                    message_id = dialog.send_html(uid,text,markup)['message_id']
                else:
                    raise
        else:
            message_id = dialog.send_html(uid,text,markup)['message_id']
        dashboard.update(message_id=message_id,text=text,markup=markup,page=page,last_edit=now)
        store.write_state(key,dashboard)
    deleted=set();attempted=set()
    # Migrate old cards only after the shared message is successfully persisted.
    for transfer_key, state in all_states.items():
        pending = list(state.get('pending_delete', []))
        old = state.get('message_id')
        if old and old != message_id:
            pending.append(old)
        remaining = []
        for old in dict.fromkeys(pending):
            if old == message_id:
                continue
            if old in deleted:
                continue
            if not cleanup or old in attempted or len(attempted)>=3:
                remaining.append(old)
                continue
            attempted.add(old)
            try:
                dialog.telegram.call('deleteMessage',chat_id=uid,message_id=old)
                deleted.add(old)
            except Exception as exc:
                if 'message to delete not found' in str(exc).lower():
                    deleted.add(old)
                else:
                    remaining.append(old)
        if state.get('message_id') != message_id or state.get('pending_delete', []) != remaining:
            latest = store.read_state(transfer_key, state)
            latest.update(message_id=message_id, pending_delete=remaining)
            store.write_state(transfer_key, latest)
