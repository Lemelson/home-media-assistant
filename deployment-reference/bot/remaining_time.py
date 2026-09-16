"""Remaining durations from useful byte deltas; no network or control operations."""
import math
from bot.download_forecast import duration

MAX_WINDOW = 4 * 3600
MAX_GAP = 90


def recent_window(active_seconds):
    if active_seconds <= 3600:
        return max(60, active_seconds / 4)
    for threshold, window in ((10800, 900), (21600, 1800), (43200, 3600), (86400, 7200)):
        if active_seconds <= threshold:
            return window
    return MAX_WINDOW


def workload(torrents):
    """Use scheduled competitors, not fluctuating instantaneous peer speeds."""
    return sorted([t.get('hashString', ''), t.get('bandwidthPriority', 0)]
                  for t in torrents if running(t) and t.get('percentDone', 0) < 1)


def running(torrent):
    return (torrent.get('status') == 4 and not any(torrent.get(key) for key in
            ('errorString', 'capacity_error', 'system_pause', 'queue_paused')))


def percentile(values, fraction):
    target = sum(weight for _, weight in values) * fraction
    cumulative = 0
    for value, weight in sorted(values):
        cumulative += weight
        if cumulative >= target:
            return value
    return values[-1][0]


def observe(state, torrent, now):
    total = max(0, torrent.get('sizeWhenDone') or torrent.get('totalSize') or 0)
    left = max(0, torrent.get('remaining_bytes', torrent.get('leftUntilDone', total)))
    done = max(0, total-left)
    model = state.setdefault('remaining_model', {})
    # Native counters survive bot restarts and include stalls, but not manual pauses.
    # Cap transferred bytes by useful data to avoid optimism from retransmissions.
    seconds = torrent.get('secondsDownloading', 0)
    amount = min(done, torrent.get('downloadedEver', 0))
    full = left * seconds / amount if seconds >= 60 and amount > 0 else None
    lifetime_label = 'По всей загрузке:'
    if full is None:
        lifetime_label = 'По наблюдениям бота:'
        record = state.get('remaining_history', {})
        seconds = record.get('seconds', 0)
        amount = record.get('bytes', 0)
        full = left * seconds / amount if seconds >= 60 and amount > 0 else None
    result = dict(full=full, lifetime_label=lifetime_label, recent=None, low=None, high=None, window=0, stalled=False)
    previous = model.pop('last', None)
    if not running(torrent) or left == 0:
        model.clear()
        return result
    context = [torrent.get('bandwidthPriority', 0), state.get('remaining_workload', [])]
    valid = (previous is not None and 0 < now-previous[0] <= MAX_GAP
             and done >= previous[1] and model.get('context') == context)
    # Repeated cached observations at the same timestamp must not erase history.
    if previous and now == previous[0] and done == previous[1] and model.get('context') == context:
        valid = True
    if not valid:
        model.clear()
        model.update(context=context, buckets=[], last_progress=now)
    elif now > previous[0]:
        start, old_done = previous
        delta = done-old_done
        if delta > 0 and now-model.get('last_progress', start) >= 120:
            model['buckets'] = []  # A recovered stall starts a fresh recent estimate.
        if delta > 0:
            model['last_progress'] = now
        rate = delta/(now-start)
        buckets = model['buckets']
        # Integrate into minute bins; independent of polling cadence and bounded to 4h.
        while start < now:
            end = min(now, (math.floor(start/60)+1)*60)
            if buckets and buckets[-1][1] == start and math.floor(buckets[-1][0]/60) == math.floor(start/60):
                buckets[-1][1] = end
                buckets[-1][2] += rate*(end-start)
            else:
                buckets.append([start, end, rate*(end-start)])
            start = end
    model['last'] = [now, done]
    model['buckets'] = [b for b in model['buckets'] if b[1] > now-MAX_WINDOW]
    result['stalled'] = now-model['last_progress'] >= 120
    window = recent_window(seconds)
    values = []
    for start, end, amount in model['buckets']:
        covered = end-max(start, now-window)
        if covered > 0:
            values.append((amount/(end-start), covered))
    coverage = sum(weight for _, weight in values)
    result['window'] = coverage
    if coverage >= 60 and not result['stalled']:
        rate = sum(rate*weight for rate, weight in values)/coverage
        if rate > 0:
            result['recent'] = left/rate
            # Empirical tempo envelope, not a statistical confidence interval.
            # Include zero-progress intervals; never promise a finite upper bound
            # when the lower tempo quartile is zero. Keep 15% minimum headroom.
            fast = max(rate*1.15, percentile(values, .75))
            slow = min(rate*.85, percentile(values, .25))
            result['low'] = left/fast
            result['high'] = left/slow if slow > 0 else None
    return result


def lines(estimate, stopped=False):
    if stopped:
        return []
    if estimate['stalled']:
        notes = ['Данных нет около двух минут. Уточню время после возобновления.']
    elif estimate['recent'] is not None:
        window = max(1, int(estimate['window']//60))
        if estimate['high'] is None:
            notes = ['Осталось: ≈ %s; с перебоями — дольше (за %d мин).' %
                     (duration(estimate['recent']), window)]
        else:
            low, high = duration(estimate['low']), duration(estimate['high'])
            span = low if low == high else low+'–'+high
            notes = ['Осталось: ≈ %s (за %d мин).' % (span, window)]
    else:
        notes = ['Осталось: уточняю по текущим условиям, нужны 1–2 мин.']
    if estimate['full'] is not None:
        notes.append('%s ≈ %s%s.' % (estimate['lifetime_label'], duration(estimate['full']),
                     ' после возобновления' if estimate['stalled'] else ''))
    return notes
