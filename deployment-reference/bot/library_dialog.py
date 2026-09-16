"""Present real inventory and turn a named choice into explicit, expiring consent."""

import html
import re
from bot.media_labels import decorate


def human_size(value):
    return '%.1f ГБ' % (value / 1024**3) if value >= 1024**3 else '%.1f МБ' % (value / 1024**2)


def words(value):
    return re.findall(r'[^\W_]+', str(value).casefold().replace('ё', 'е'))


def matching_items(items, query):
    if not query:
        return items
    ignored = {'удали', 'удалить', 'пожалуйста', 'фильм', 'сериал', 'этот', 'этого', 'сезон',
               'сезона', 'серию', 'серия', 'скачанный', 'скачанные', 'покажи', 'мне', 'из'}
    season_pattern = r'(?:сезон[а-я]*|season|\bS)\s*[:№]?\s*(\d{1,2})(?!\d)'
    episode_pattern = r'(?:сери[яюи]|эпизод|episode|\bE)\s*[:№]?\s*(\d{1,3})(?!\d)'
    season_match = re.search(season_pattern, query, re.I)
    episode_match = re.search(episode_pattern, query, re.I)
    clean = re.sub(episode_pattern, '', re.sub(season_pattern, '', query, flags=re.I), flags=re.I)
    tokens = [w for w in words(clean) if w not in ignored]
    if not tokens and not season_match and not episode_match:
        return []
    matches = []
    for item in items:
        if season_match and item.get('season') != int(season_match.group(1)):
            continue
        if episode_match and item.get('episode') != int(episode_match.group(1)):
            continue
        parts = words(' '.join(str(item.get(k, '')) for k in ('name', 'show', 'season', 'episode', 'raw_name')) + ' ' + str(item.get('media',{}).get('original_title','')))
        if all(t in parts or (len(t) > 3 and any(t in part for part in parts)) for t in tokens):
            matches.append(item)
    if season_match and not episode_match:
        seasons = [item for item in matches if item.get('kind') == 'season']
        if seasons:
            return seasons
    return matches


class LibraryFlow:
    PAGE_SIZE = 8

    def __init__(self, dialog):
        self.dialog = dialog

    def inventory(self, chat_id):
        if self.dialog.media_library is None:
            self.dialog.send(chat_id, 'Просмотр медиатеки ещё не подключён.')
            return None
        try:
            inventory = self.dialog.media_library()
        except Exception:
            self.dialog.send(chat_id, 'Mac сейчас недоступен. Попробуй открыть медиатеку позже.')
            return None
        if not inventory.get('disk_ok'):
            self.dialog.send(chat_id, 'media disk сейчас недоступен. Список и удаление станут доступны после подключения диска.')
            return None
        return {**inventory, 'items':[decorate(self.dialog.jobs,item) for item in inventory.get('items',[])]}

    def show(self, uid, chat_id, query='', page=0, inventory=None):
        inventory = inventory or self.inventory(chat_id)
        if inventory is None:
            return
        all_items = [decorate(self.dialog.jobs,item) for item in inventory.get('items', [])]
        items = sorted(matching_items(all_items, query), key=lambda item: item.get('size_bytes', 0), reverse=True)
        self.dialog.jobs.write_state('library:' + str(uid), {'items': items, 'query': query})
        if not items:
            return self.dialog.send(chat_id, 'В медиатеке нет совпадений.' if query else 'В папках Movies и TV пока нет скачанных видео.')
        page = min(max(0, page), (len(items) - 1) // self.PAGE_SIZE)
        start = page * self.PAGE_SIZE
        lines = ['🎬 <b>Мои фильмы</b> · свободно ' + human_size(inventory.get('free_bytes', 0)),
                 '<i>Скачано на сервер медиатеки. Сначала самые большие.</i>']
        buttons = []
        for index, item in enumerate(items[start:start + self.PAGE_SIZE], start + 1):
            label = html.escape(str(item['name'])[:160])
            kind = {'movie': 'фильм', 'season': 'сезон', 'episode': 'серия'}.get(item.get('kind'), 'видео')
            lines.append('%d. <b>%s</b>\n%s · %s' % (index, label, human_size(item.get('size_bytes', 0)), kind))
            quality=item.get('quality',{})
            facts=[quality[k] for k in ('resolution','bitrate') if quality.get(k)]
            if facts: lines[-1]+=' · '+html.escape(' · '.join(facts))
            prefix = '%d. ' % index
            suffix = ' — ' + human_size(item.get('size_bytes', 0)).replace('.', ',')
            name = str(item['name'])
            available = max(1, 60 - len(prefix) - len(suffix))
            if len(name) > available:
                name = name[:available - 1].rstrip() + '…'
            buttons.append([{'text': prefix + name + suffix, 'callback_data': 'library-delete:' + item['id']}])
        navigation = []
        if page:
            navigation.append({'text': '← Назад', 'callback_data': 'library-page:' + str(page - 1)})
        if start + self.PAGE_SIZE < len(items):
            navigation.append({'text': 'Далее →', 'callback_data': 'library-page:' + str(page + 1)})
        if navigation:
            buttons.append(navigation)
        if inventory.get('truncated'):
            lines.append('<i>Показана часть медиатеки. Уточни название, чтобы найти нужное.</i>')
        return self.dialog.send_html(chat_id, '\n\n'.join(lines), {'inline_keyboard': buttons})

    def request_delete(self, uid, chat_id, target):
        previous = self.dialog.jobs.read_state('library:' + str(uid), {}).get('items', [])
        ordinal = {'первый': 1, 'первую': 1, 'второй': 2, 'вторую': 2,
                   'третий': 3, 'третью': 3}.get(target.casefold())
        if target.isdigit():
            ordinal = int(target)
        if ordinal and 0 < ordinal <= len(previous):
            return self.offer(uid, chat_id, previous[ordinal - 1]['id'])
        inventory = self.inventory(chat_id)
        if inventory is None:
            return
        matches = matching_items(inventory.get('items', []), target)
        if len(matches) == 1:
            return self.offer(uid, chat_id, matches[0]['id'], inventory)
        if not matches:
            self.dialog.send(chat_id, 'Не нашёл однозначного совпадения. Выбери нужный фильм, сезон или серию из медиатеки.')
            return self.show(uid, chat_id, inventory=inventory)
        self.dialog.send(chat_id, 'Нашлось несколько вариантов. Выбери, что именно удалить.')
        return self.show(uid, chat_id, target, inventory=inventory)

    def offer(self, uid, chat_id, inventory_id, inventory=None):
        inventory = inventory or self.inventory(chat_id)
        if inventory is None:
            return
        item = next((item for item in inventory.get('items', []) if item['id'] == inventory_id), None)
        if item is None:
            return self.dialog.send(chat_id, 'Этот пункт медиатеки изменился. Открой список заново.')
        token = self.dialog.jobs.offer_action(uid, {'action': 'delete_library', 'inventory_id': inventory_id})
        self.dialog.jobs.write_state('delete-label:'+str(uid)+':'+inventory_id, {'name':str(item['name'])[:240]})
        title = html.escape(str(item['name'])[:240])
        text = '<b>Удалить %s?</b>\n%s · видеофайлов: %d\n\nВидео будет удалено окончательно, без корзины. '
        text += 'Субтитры и обложки останутся. Подтверждение действует 5 минут.'
        text = text % (title, human_size(item.get('size_bytes', 0)), item.get('file_count', 1))
        return self.dialog.send_html(chat_id, text, {'inline_keyboard': [[
            {'text': 'Да, удалить окончательно', 'callback_data': 'confirm:' + token},
            {'text': 'Отмена', 'callback_data': 'cancel-delete:' + token}]]})
