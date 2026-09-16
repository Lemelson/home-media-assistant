"""Ten-minute useful-byte history and conditional per-film tempo envelopes.

Minute-bin quartiles plus a minimum 15% spread describe observed variability;
they are not statistical confidence bounds. No instantaneous RPC rate is used.
"""
import math
from bot.remaining_time import percentile

WINDOW = 600
MAX_GAP = 90


def _measure(model, done, total, now):
    previous = model.get('last')
    if previous and now == previous[0] and done == previous[1] and total == previous[2]:
        pass
    elif (previous and 0 < now-previous[0] <= MAX_GAP
          and done >= previous[1] and total == previous[2]):
        start, old_done, _ = previous
        rate = (done-old_done)/(now-start)
        if done > old_done:
            model['last_progress'] = now
        buckets = model.setdefault('buckets', [])
        while start < now:
            end = min(now, (math.floor(start/60)+1)*60)
            if (buckets and buckets[-1][1] == start
                    and math.floor(buckets[-1][0]/60) == math.floor(start/60)):
                buckets[-1][1] = end
                buckets[-1][2] += rate*(end-start)
            else:
                buckets.append([start, end, rate*(end-start)])
            start = end
    else:
        model.clear()
        model.update(buckets=[], last_progress=now)
    model['last'] = [now, done, total]
    trimmed = []
    for start, end, amount in model['buckets']:
        begin = max(start, now-WINDOW)
        if end > begin:
            trimmed.append([begin, end, amount*(end-begin)/(end-start)])
    model['buckets'] = trimmed
    values = [(amount/(end-start), end-start) for start, end, amount in trimmed]
    coverage = sum(weight for _, weight in values)
    rate = sum(value*weight for value, weight in values)/coverage if coverage else 0
    if coverage < WINDOW-0.001:
        return coverage, rate, None, None
    fast = max(rate*1.15, percentile(values, .75))
    slow = min(rate*.85, percentile(values, .25))
    return coverage, rate, fast, slow


def _envelope(rows):
    if not rows or any(row['low'] is None for row in rows):
        return None
    return dict(low=max(row['low'] for row in rows),
                high=None if any(row['high'] is None for row in rows)
                else max(row['high'] for row in rows))


def observe(history, torrents, now, disk=None):
    models = history.setdefault('films', {})
    films = {}
    for torrent in torrents:
        h = torrent['hashString']
        total = torrent.get('sizeWhenDone') or torrent.get('totalSize') or 0
        left = torrent.get('leftUntilDone')
        if left == 0 and total > 0:
            continue
        row = dict(left=left, coverage=0, rate=0, fast=0, slow=0, low=None, high=None)
        films[h] = row
        if total <= 0 or left is None or left < 0 or left > total:
            models.pop(h, None)
            row['state'] = 'unknown'
            continue
        model = models.setdefault(h, {})
        coverage, rate, fast, slow = _measure(model, total-left, total, now)
        row.update(coverage=coverage, rate=rate, fast=fast or 0, slow=slow or 0)
        if torrent.get('manual_pause') or (torrent.get('status') == 0 and not torrent.get('queue_paused')
                                          and not torrent.get('system_pause') and not torrent.get('capacity_error')):
            row['state'] = 'paused'
        elif (torrent.get('status') != 4 or any(torrent.get(k) for k in
              ('errorString', 'capacity_error', 'system_pause', 'queue_paused'))):
            row['state'] = 'waiting'
        elif coverage < WINDOW-0.001:
            row['state'] = 'warming'
        elif now-model.get('last_progress', now) >= 120 or rate <= 0:
            row['state'] = 'stalled'
        else:
            row['state'] = 'ready'
        if fast and coverage >= WINDOW-0.001:
            row['low'] = left/fast
            row['high'] = left/slow if slow and row['state'] == 'ready' else None
    history['films'] = {h: model for h, model in models.items() if h in films}
    counts = {state: sum(row['state'] == state for row in films.values())
              for state in ('paused', 'waiting', 'warming', 'unknown', 'stalled')}
    ready = [row for row in films.values() if row['state'] == 'ready']
    result = dict(films=films, **counts, active=_envelope(ready), complete=None, fill=None)
    if ready and len(ready) == len(films):
        result['complete'] = result['active']
    if disk:
        known_left = sum(row['left'] or 0 for row in films.values())
        # The disk queue can include downloads outside the bot's managed set.
        if disk.get('unknown_count') or disk.get('remaining_bytes', 0) > known_left:
            result['unknown'] += 1
            result['complete'] = None
        free = disk.get('free_bytes')
        if free is not None and disk.get('remaining_bytes', 0) > free and ready:
            low = fill_time([(r['left'], r['fast']) for r in ready], free)
            high = fill_time([(r['left'], r['slow']) for r in ready], free)
            if low is not None:
                result['fill'] = dict(low=low, high=high)
    return result


def fill_time(rows, amount):
    """Time until amount arrives, removing each film's speed when it finishes."""
    if amount <= 0:
        return 0
    rows = [(left, rate) for left, rate in rows if rate > 0 and left > 0]
    if sum(left for left, _ in rows) < amount:
        return None
    elapsed = received = 0
    speed = sum(rate for _, rate in rows)
    for end, rate in sorted((left/rate, rate) for left, rate in rows):
        gained = (end-elapsed)*speed
        if received+gained >= amount:
            return elapsed+(amount-received)/speed
        received += gained
        elapsed = end
        speed -= rate
    return elapsed
