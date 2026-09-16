"""Render a fresh capacity snapshot without blocking Telegram on remote I/O."""
from bot.download_forecast import duration


def gb(value):
    return '%.1f ГБ' % (value / 1024**3)


def render(snapshot, now):
    if (not snapshot or snapshot.get('free_bytes') is None
            or not 0 <= now - snapshot.get('at', 0) <= 45):
        return '<b>💾 Диск</b>: нет свежих данных. Обновляю свободное место и прогноз.'
    free = snapshot['free_bytes']
    left = snapshot['remaining_bytes']
    rate = snapshot['rate_bytes']
    reserve = snapshot['headroom_bytes']
    unknown = snapshot['unknown_count']
    lines = ['<b>💾 Диск · вся очередь, включая паузу</b>',
             'Свободно сейчас: <b>%s</b>' % gb(free),
             'Осталось скачать: %s%s' % ('не менее ' if unknown else '', gb(left))]
    if unknown:
        lines.append('Размер части загрузок ещё неизвестен; итог уточняется.')
    if left > free:
        lines.append('⚠️ Не хватит: <b>%s</b>%s' % (gb(left-free), ' или больше' if unknown else ''))
    elif not unknown:
        lines.append('После завершения свободно: <b>%s</b>' % gb(free-left))
    if left + reserve > free:
        lines.append('С запасом %s нужно освободить %s; защитная пауза может сработать раньше заполнения.'
                     % (gb(reserve), gb(left+reserve-free)))
    if left <= 0 and not unknown:
        lines.append('Вся очередь скачана.')
    elif rate <= 0:
        lines.append('⏱ Прогноз времени недоступен: нет текущей скорости.')
    else:
        lines.append('⏱ Общий темп: %.1f МБ/с' % (rate / 1024**2))
        if left > free:
            lines.append('До заполнения диска при этом темпе: ≈ %s.' % duration(free/rate))
        elif not unknown:
            lines.append('До скачивания оставшегося объёма при этом темпе: ≈ %s.' % duration(left/rate))
        lines.append('<i>Ориентир при сохранении общего темпа; паузы и ожидание участников увеличат срок.</i>')
    return '\n'.join(lines)
