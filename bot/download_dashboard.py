"""One durable Telegram message per chat, with three films per page."""
import html
import math
import re
import threading

PUBLISH_LOCK = threading.RLock()
CONTROL_WAKE = threading.Event()

PAGE_SIZE = 6


def render(states, page=0):
    states = sorted(states, key=lambda s: (s.get('created', 0), s['hash']))
    pages = max(1, math.ceil(len(states) / PAGE_SIZE))
    page = min(max(0, page), pages - 1)
    shown = states[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    blocks = ['<b>⬇️ Загрузки</b>']
    buttons = []
    for index, state in enumerate(shown, page * PAGE_SIZE + 1):
        lines = ['<b>%d. %s</b>' % (index, html.escape(state['name'][:120]))]
        if state.get('completed_notified'):
            lines.append('✅ Фильм скачан')
        else:
            text = state.get('text', '')
            for line in text.splitlines():
                if (line.startswith(('<b>⬇', '<b>⏸', '<b>🔎', '<b>⚠', '<b>⏳', '<b>В очереди', 'Раздают:', 'Скорость:', 'Ожидаемая скорость'))
                        or re.match(r'^\d.* из ', line) or '░' in line or '█' in line or '▌' in line):
                    lines.append(line)
            if 'не найдена' in text:
                lines.append('Загрузка не найдена в Transmission')
            if 'недоступен' in text:
                lines.append('Обновлю прогресс после восстановления связи.')
            estimates = [line for line in text.splitlines() if line.startswith('<i>')]
            if estimates:
                estimate = estimates[-1].removeprefix('<i>').removesuffix('</i>')
                estimate = estimate.split(' · Предварительно')[0]
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
        blocks.append('Кнопка: 🟢 низкий → 🟡 средний → 🔴 высокий → ⏸ пауза → ▶ начать с низким.\nПриоритет каждого фильма независим.')
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

    text, markup, page = render(states, dashboard.get('page',0))
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
        state.update(message_id=message_id,pending_delete=remaining)
        store.write_state(transfer_key,state)
