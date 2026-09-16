"""Render a fresh capacity snapshot without blocking Telegram on remote I/O."""
from bot.download_forecast import duration


def gb(value):
    return '%.1f ГБ' % (value / 1024**3)


def render(snapshot, now):
    if (not snapshot or snapshot.get('free_bytes') is None
            or not 0 <= now - snapshot.get('at', 0) <= 45):
        return '💾 Обновляю данные о диске…'
    free = snapshot['free_bytes']
    left = snapshot['remaining_bytes']
    rate = snapshot['rate_bytes']
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
    elif rate <= 0:
        lines.append('⏱ Жду скорость для прогноза')
    elif left > free:
        lines.append('⏱ До заполнения: ≈ %s при текущем темпе' % duration(free/rate))
    elif not unknown:
        lines.append('⏱ При текущем темпе: ≈ %s' % duration(left/rate))
    return '\n'.join(lines)
