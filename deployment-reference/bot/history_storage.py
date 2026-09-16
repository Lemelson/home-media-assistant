"""Cache Mac summaries and deliver owner-only storage reminders durably."""

def sync_history(dialog,status,now):
    if 'download_history' in status:
        dialog.jobs.write_state('mac-download-history',dict(updated=now,records=status['download_history']))
    storage=status.get('history_storage')
    if not storage:return
    state=dialog.jobs.read_state('history-storage-notice',{})
    events=storage.get('events',[])
    latest=max([e['id'] for e in events]+[0])
    if not storage.get('over_limit'):
        dialog.jobs.write_state('history-storage-notice',dict(over=False,event=latest))
        return
    owners=[m['user_id'] for m in dialog.access.members() if m['role']=='owner']
    if not owners:return
    pending=[e for e in events if e.get('over_limit') and e['id']>state.get('event',0)]
    if not pending and state.get('over'):return
    notices=pending or [dict(id=latest)]
    for event in notices:
        dialog.send(owners[0], '🗃 История загрузок на Mac занимает %.1f МБ — больше 300 МБ. '
                    'Пора проверить и настроить это хранилище. Историю сохраняю; буду напоминать с каждым новым фильмом.' % (storage['bytes']/1_000_000))
        state=dict(over=True,event=event['id'])
        dialog.jobs.write_state('history-storage-notice',state)
