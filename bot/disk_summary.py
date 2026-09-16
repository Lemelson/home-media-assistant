"""Render a fresh capacity snapshot without blocking Telegram on remote I/O."""
import math
from bot.download_forecast import duration


def gb(value):
    return '%.1f ГБ' % (value / 1024**3)


def render(snapshot, now):
    if (not snapshot or snapshot.get('free_bytes') is None
            or not 0 <= now - snapshot.get('at', 0) <= 45):
        return '💾 Обновляю данные о диске…'
    free = snapshot['free_bytes']
    left = snapshot['remaining_bytes']
    reserve = snapshot['headroom_bytes']
    unknown = snapshot['unknown_count']
    lines = ['💾 Свободно: <b>%s</b>' % gb(free)]
    if unknown:
        lines[0] += ' · после загрузок: уточняется'
    elif left <= free:
        lines[0] += ' → после загрузок: <b>%s</b>' % gb(free-left)
    if left > free:
        lines.append('⚠️ Не хватит: <b>%s</b>%s. Возможна защитная пауза.'
                     % (gb(left-free), ' или больше' if unknown else ''))
    elif left + reserve > free:
        lines.append('⚠️ Для запаса освободите %s. Возможна защитная пауза.' % gb(left+reserve-free))
    if left <= 0 and not unknown:
        lines.append('✅ Всё скачано')
    else:
        lines.append(forecast_line(snapshot.get('forecast'), left > free))
    return '\n'.join(lines)


def _span(estimate):
    # Round the lower edge down and upper edge up, not both upwards.
    low_minutes = max(1, math.floor(estimate['low']/300)*5)
    low = ('%d ч %02d мин' % divmod(low_minutes, 60)) if low_minutes >= 60 else '%d мин' % low_minutes
    if estimate['high'] is None:
        return 'от %s; верхняя граница неизвестна' % low
    high = duration(max(estimate['high'], (low_minutes+1)*60))
    return '≈ %s–%s' % (low, high)


def forecast_line(estimate, shortage=False):
    if not estimate:
        return '⏱ Собираю 10 мин истории'
    if shortage:
        if estimate.get('fill'):
            return '⏱ До заполнения: %s (за 10 мин)' % _span(estimate['fill'])
        return '⏱ До заполнения: пока неизвестно'
    if estimate.get('complete'):
        return '⏱ %s (за 10 мин)' % _span(estimate['complete'])
    notes = []
    if estimate.get('paused'):
        notes.append('пауза: %d' % estimate['paused'])
    waiting = estimate.get('waiting', 0)+estimate.get('stalled', 0)
    if waiting:
        notes.append('ждут: %d' % waiting)
    if estimate.get('warming'):
        notes.append('собираю 10 мин')
    if estimate.get('unknown'):
        notes.append('часть очереди уточняется')
    if estimate.get('active'):
        return '⏱ Активные: %s (за 10 мин) · %s' % (_span(estimate['active']), ' · '.join(notes))
    return '⏱ '+(' · '.join(notes) if notes else 'Срок пока неизвестен')
