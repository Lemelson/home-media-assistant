"""Independent priorities and durable pause ownership; caller serializes mutations with the media lock."""
import time

FIELDS = ['hashString', 'status', 'percentDone', 'leftUntilDone', 'bandwidthPriority', 'addedDate']


def reconcile(store, rpc, promote=None, priority=None, next_priority=None):
    rows = rpc.call('torrent-get', {'fields': FIELDS}).get('torrents', [])
    known = store.read_state('managed', {})
    live = {r['hashString']: r for r in rows if r['hashString'] in known
            and r.get('percentDone', 0) < 1 and r.get('status') not in (5, 6)}
    for index, (h, row) in enumerate(live.items()):
        info = known[h]
        info.setdefault('queue_order', row.get('addedDate') or time.time() + index / 1000)
        info.setdefault('queue_priority', row.get('bandwidthPriority', 0))
        info.setdefault('priority_next', 1)
    if promote in live:
        known[promote].update(queue_priority=priority, priority_next=next_priority)
    eligible = [h for h, r in live.items()
                if not known[h].get('manual_pause') and not known[h].get('capacity_pending')
                and not known[h].get('system_pause') and r.get('status') not in (1, 2)
                and (r.get('status') in (3, 4) or known[h].get('queue_paused'))]
    eligible.sort(key=lambda h: (-known[h]['queue_priority'], known[h]['queue_order'], h))
    winners = set(eligible)
    losers = [h for h in eligible if h not in winners]
    for h in losers:
        known[h]['queue_paused'] = True
    # Persist pause ownership before RPC, so a retry can safely resume a stopped loser.
    store.write_state('managed', known)
    stop = [h for h in losers if live[h].get('status') in (3, 4)]
    if stop:
        rpc.call('torrent-stop', {'ids': stop})
    for h, row in live.items():
        if row.get('bandwidthPriority', 0) != known[h]['queue_priority']:
            rpc.call('torrent-set', {'ids': [h], 'bandwidthPriority': known[h]['queue_priority']})
    start = [h for h in eligible if h in winners and live[h].get('status') != 4]
    if start:
        rpc.call('torrent-start-now', {'ids': start})
    for h in winners:
        known[h].pop('queue_paused', None)
    store.write_state('managed', known)
