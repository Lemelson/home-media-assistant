"""Private family chat, media controls and explicit destructive-action consent."""

import re
import base64
import html
import time
from pathlib import Path

from bot.access import AccessRegistry
from bot.jobs import JobStore
from bot.library_dialog import LibraryFlow, matching_items
from bot.rendering import telegram_html, plain_text
from bot.progress import progress_text, progress_markup
from bot.media_labels import status_labels


HOME = {'keyboard': [[{'text': '🎬 Мои фильмы'}, {'text': '⬇️ Загрузки'}],
                     [{'text': '🔎 Найти фильм'}]],
        'resize_keyboard': True, 'is_persistent': True, 'one_time_keyboard': False}


def callback_notice(data):
    if data.startswith('media:'): return 'Ищу раздачи…'
    if data.startswith('release:'): return 'Добавляю загрузку…'
    if data.startswith('priority:'): return 'Меняю приоритет…'
    return 'Обрабатываю…'


def human_size(value):
    return '%.1f ГБ' % (value / 1024**3) if value >= 1024**3 else '%.1f МБ' % (value / 1024**2)


class Dialog:
    def __init__(self, state_dir, telegram, owner_username, mother_phone, media_status, search=None, transcribe=None,
                 media_library=None, owner_id=None, member_id=None):
        state = Path(state_dir)
        self.telegram = telegram
        self.access = AccessRegistry(state / 'access.db', owner_username, mother_phone, owner_id, member_id)
        self.jobs = JobStore(state / 'jobs.db')
        self.media_status = lambda: status_labels(self.jobs, media_status())
        self.search = search
        self.transcribe = transcribe
        self.media_library = media_library
        self.library_flow = LibraryFlow(self)

    def remember(self, uid, role, text):
        self.jobs.append_context(uid, role, text)

    def conversation(self, uid):
        return self.jobs.read_state('conversation:' + str(uid), [])

    def track_markup(self, chat_id, result, markup):
        if markup and markup.get('inline_keyboard') and result.get('message_id'):
            self.jobs.write_state('markup:' + str(chat_id), result['message_id'])

    def retire_markup(self, chat_id, message_id=None):
        key = 'markup:' + str(chat_id)
        message_id = message_id or self.jobs.read_state(key)
        if message_id:
            try:
                self.telegram.call('editMessageReplyMarkup', chat_id=chat_id, message_id=message_id,
                                   reply_markup={'inline_keyboard': []})
            except Exception:
                pass
        self.jobs.write_state(key, None)

    def delete_message(self, chat_id, message_id):
        key='message-cleanup:%s:%s' % (chat_id,message_id)
        self.jobs.write_state(key,{'chat_id':chat_id,'message_id':message_id})
        try:
            self.telegram.call('deleteMessage',chat_id=chat_id,message_id=message_id)
        except Exception:
            return
        self.jobs.write_state(key,None)

    def clean_messages(self):
        pending=[(k,v) for k,v in self.jobs.read_states('message-cleanup:').items() if v]
        for key,item in pending[:3]:
            if not item:continue
            try:self.telegram.call('deleteMessage',**item)
            except Exception as error:
                if 'message to delete not found' not in str(error).lower():continue
            self.jobs.write_state(key,None)

    def send(self, chat_id, text, markup=None):
        payload = {'chat_id': chat_id, 'text': text[:4096]}
        payload['reply_markup'] = HOME if markup is None else markup
        result = self.telegram.call('sendMessage', **payload)
        self.track_markup(chat_id, result, markup)
        self.remember(chat_id, 'assistant', text)
        return result

    def send_html(self, chat_id, text, markup=None):
        text = telegram_html(text, 3900)
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        payload['reply_markup'] = HOME if markup is None else markup
        result = self.telegram.call('sendMessage', **payload)
        self.track_markup(chat_id, result, markup)
        self.remember(chat_id, 'assistant', plain_text(text))
        return result

    def edit_html(self, chat_id, message_id, text, markup=None):
        text = telegram_html(text, 3900)
        result = self.telegram.call('editMessageText', chat_id=chat_id, message_id=message_id,
                                    text=text, parse_mode='HTML',
                                    reply_markup=markup or {'inline_keyboard': []})
        self.remember(chat_id, 'assistant', plain_text(text))
        return {**(result if isinstance(result,dict) else {}), 'message_id': message_id}

    def about(self, chat_id):
        text = 'Домашний кинотеатр — семейная медиатека на Mac.\nПоиск фильмов, голосовые запросы и управление загрузками.'
        images = getattr(self.search, 'images', None)
        if not getattr(images, 'ATTRIBUTION', None):
            return self.send(chat_id, text)
        text += '\n\nПостеры: TMDB\n' + images.SOURCE_URL + '\n' + images.ATTRIBUTION
        result = self.telegram.call('sendMessage', chat_id=chat_id, text=text,
            link_preview_options={'url': images.SOURCE_URL, 'prefer_small_media': True})
        self.remember(chat_id, 'assistant', text)
        return result

    def handle(self, update):
        callback = update.get('callback_query')
        message = callback.get('message', {}) if callback else update.get('message', {})
        user = callback.get('from', {}) if callback else message.get('from', {})
        chat = message.get('chat', {})
        uid = user.get('id')
        if not uid or not chat.get('id'):
            return
        role = self.access.check(uid, user.get('username'), chat.get('type'), message.get('contact'),
                                 'callback' if callback else 'voice' if message.get('voice') else 'message')
        if callback and not update.get('_callback_answered'):
            try:
                self.telegram.call('answerCallbackQuery', callback_query_id=callback['id'], text=callback_notice(callback.get('data','')))
            except Exception:
                pass  # Expired Telegram acknowledgements must never discard the command.
        if role not in ('owner', 'mother'):
            if chat.get('type') != 'private':
                return
            if role == 'needs_contact':
                self.send(chat['id'], 'Это семейный бот. Чтобы подтвердить доступ, отправьте свой контакт кнопкой ниже.',
                          {'keyboard': [[{'text': 'Подтвердить мой номер', 'request_contact': True}]], 'resize_keyboard': True, 'one_time_keyboard': True})
            else:
                self.send(chat['id'], 'Доступ к этому семейному боту закрыт.', {'remove_keyboard': True})
            return
        source = 'tg:' + str(update['update_id'])
        if callback:
            return self.callback(uid, chat['id'], callback.get('data', ''), source)
        if message.get('contact'):
            self.send(chat['id'], 'Доступ подтверждён. Добро пожаловать!', {'remove_keyboard': True})
            return self.send(chat['id'], 'Напиши название фильма или открой медиатеку.', HOME)
        document = message.get('document')
        if document:
            if not document.get('file_name', '').lower().endswith('.torrent') or document.get('file_size', 0) > 2 * 1024 * 1024:
                return self.send(chat['id'], 'Пришли файл .torrent размером до 2 МБ или magnet-ссылку.')
            raw = self.telegram.download_file(document['file_id'], max_bytes=2 * 1024 * 1024)
            self.jobs.enqueue(source, uid, {'action': 'add', 'metainfo': base64.b64encode(raw).decode(), 'kind': 'movie'})
            return self.send(chat['id'], 'Торрент сохранён. Начну загрузку на media disk, когда Mac будет доступен.')
        text = (message.get('text') or message.get('caption') or '').strip()
        if message.get('voice'):
            if self.transcribe is None:
                return self.send(chat['id'], 'Распознавание голоса ещё подключается. Пока напиши запрос текстом.')
            try:
                text = self.transcribe(message['voice'])
            except Exception:
                return self.send(chat['id'], 'Не удалось распознать голос. Пришли сообщение до 10 минут или напиши текстом.')
        if not text:
            return self.send(chat['id'], 'Напиши название или описание фильма; можно прислать голосовое сообщение.')
        # A reply to a bot message is useful context; forwarded text remains user data.
        quoted = message.get('reply_to_message', {})
        if quoted.get('from', {}).get('is_bot') and (quoted.get('text') or quoted.get('caption')):
            self.remember(uid, 'assistant', (quoted.get('text') or quoted.get('caption'))[:4000])
        self.remember(uid, 'user', text)
        if text == '/about':
            return self.about(chat['id'])
        if text.startswith('/start') or text in ('/help', '/menu'):
            return self.send_html(chat['id'], '<b>Домашний кинотеатр</b>\nНапиши название или сюжет фильма, пришли голосовое или перешли сообщение. '
                                  'Можно спросить, что уже скачано, посмотреть загрузки или удалить выбранный фильм с подтверждением. '
                                  'О боте и источниках: /about.', HOME)
        if text in ('/status', '/downloads') or text.casefold() in ('загрузки', 'статус', '⬇️ загрузки'):
            return self.downloads(chat['id'])
        if text == '/library' or text.casefold() in ('медиатека', 'скачанные фильмы', 'мои фильмы', '🎬 мои фильмы'):
            return self.library_flow.show(uid, chat['id'])
        if text in ('🔎 Найти фильм', 'Найти фильм'):
            return self.send(chat['id'], 'Напиши название фильма или сериала.', HOME)
        if text == '/access' and role == 'owner':
            members = self.access.members()
            denials = self.access.recent_denials(10)
            lines = ['Доступ:'] + [str(m['user_id']) + ' — ' + m['role'] for m in members]
            lines += ['Последние попытки без доступа:'] + [str(d['user_id']) + ' @' + d['username'] + ' — ' + d['decision'] for d in denials]
            return self.send(chat['id'], '\n'.join(lines))
        if text.startswith('magnet:?'):
            self.jobs.enqueue(source, uid, {'action': 'add', 'magnet': text, 'kind': 'movie'})
            return self.send(chat['id'], 'Задание сохранено. Начну загрузку на media disk, когда Mac будет доступен.')
        if self.search is None:
            return self.send(chat['id'], 'Поиск по названию ещё подключается. Управление загрузками уже доступно; можно прислать готовую magnet-ссылку.')
        if hasattr(self.search, 'handle_message'):
            return self.search.handle_message(uid, chat['id'], text, self, source, message)
        return self.search(uid, chat['id'], text, self, source=source)

    def callback(self, uid, chat_id, data, source):
        if re.fullmatch(r'download-page:\d{1,6}', data):
            from bot.download_dashboard import publish
            key = 'download-dashboard:' + str(uid)
            dashboard = self.jobs.read_state(key, {})
            dashboard['page'] = int(data.split(':')[1])
            self.jobs.write_state(key, dashboard)
            return publish(self, uid, time.time())
        choice = re.fullmatch(r'(media|release):([a-f0-9]{10}):(\d)', data)
        if choice and self.search is not None:
            stage, nonce, index = choice.groups()
            return self.search.choose(uid, chat_id, stage, nonce, int(index), self)
        if re.fullmatch(r'priority:[a-fA-F0-9]{40}', data):
            h = data.split(':',1)[1]
            job = self.jobs.enqueue_priority_mode(source,uid,h)
            from bot.download_dashboard import CONTROL_WAKE
            CONTROL_WAKE.set()
            return job
        if data == 'downloads':
            return self.downloads(chat_id)
        if data.startswith('downloads-page:'):
            try:
                return self.downloads(chat_id, page=int(data.split(':', 1)[1]))
            except ValueError:
                return
        if re.fullmatch(r'download:[a-fA-F0-9]{40}', data):
            return self.downloads(chat_id, selected=data.split(':', 1)[1])
        if data == 'library':
            return self.library_flow.show(uid, chat_id)
        if data.startswith('library-page:'):
            try:
                page = int(data.split(':', 1)[1])
            except ValueError:
                return
            query = self.jobs.read_state('library:' + str(uid), {}).get('query', '')
            return self.library_flow.show(uid, chat_id, query, page)
        if data.startswith('library-delete:'):
            return self.library_flow.offer(uid, chat_id, data.split(':', 1)[1])
        if data.startswith('cancel-delete:'):
            cancelled = self.jobs.cancel_confirmation(uid, data.split(':', 1)[1])
            return self.send(chat_id, 'Удаление отменено.' if cancelled else
                             'Это подтверждение уже использовано. Если удаление было подтверждено, отменить его этой кнопкой нельзя.')
        if data.startswith('retry:'):
            original = self.jobs.get(data.split(':', 1)[1])
            if (original and original['user_id'] == uid and (original.get('result') or {}).get('error')
                    in ('insufficient_space', 'size_unknown')):
                result = original['result']
                payload = {'action': 'resume', 'hash': result['hash']} if result.get('hash') else original['payload']
                self.jobs.enqueue('retry:' + original['id'] + ':' + source, uid, payload)
                return self.send(chat_id, 'Повторю проверку места перед загрузкой.')
            return self.send(chat_id, 'Это задание больше нельзя повторить этой кнопкой.')
        if data in ('search', 'cancel'):
            if data == 'cancel':
                self.jobs.cancel_confirmation(uid)
            return self.send(chat_id, 'Напиши название фильма или сериала; можно добавить год и сезон.' if data == 'search' else 'Отменено.')
        if data.startswith('confirm:'):
            job_id = self.jobs.confirm_delete(uid, data.split(':', 1)[1])
            return self.send(chat_id, '🗑 Удаляю… Проверю результат и сообщу отдельно. Если сервер недоступен, дождусь подключения.' if job_id else 'Подтверждение истекло или уже использовано. Открой загрузки заново.')
        match = re.fullmatch(r'(pause|resume|delete):([a-fA-F0-9]{40})', data)
        if not match:
            return self.send(chat_id, 'Эта кнопка больше не поддерживается. Открой загрузки заново.')
        action, torrent_hash = match.groups()
        if action == 'delete':
            if self.media_library is not None:
                inventory = self.library_flow.inventory(chat_id)
                if inventory is None:
                    return
                matches = [item for item in inventory.get('items', []) if item.get('torrent_hash') == torrent_hash]
                if len(matches) == 1:
                    return self.library_flow.offer(uid, chat_id, matches[0]['id'], inventory)
                self.send(chat_id, 'Выбери файл или сезон из медиатеки, чтобы удалить только нужное.')
                return self.library_flow.show(uid, chat_id, inventory=inventory)
            token = self.jobs.offer_delete(uid, torrent_hash)
            return self.send(chat_id, 'Удалить выбранную загрузку вместе с файлами с media disk? Подтверждение действует 5 минут.',
                             {'inline_keyboard': [[{'text': 'Да, удалить файлы', 'callback_data': 'confirm:' + token},
                                                   {'text': 'Отмена', 'callback_data': 'cancel'}]]})
        self.jobs.enqueue(source, uid, {'action': action, 'hash': torrent_hash})
        return self.send(chat_id, 'Команда сохранена. Выполню, когда Mac будет доступен.')

    def resolve_intent(self, uid, chat_id, result, source=None):
        action = result.get('action')
        target = str(result.get('target') or '').strip()
        if action == 'library':
            return self.library_flow.show(uid, chat_id, target)
        if action == 'downloads':
            return self.downloads(chat_id)
        if action == 'delete':
            return self.library_flow.request_delete(uid, chat_id, target)
        if action in ('pause', 'resume'):
            try:
                status = self.media_status()
            except Exception:
                return self.send(chat_id, 'Mac сейчас недоступен. Попробуй позже.')
            torrents = status.get('torrents', [])
            matches = matching_items(torrents, target) if target else []
            if len(matches) != 1:
                self.send(chat_id, 'Выбери нужную загрузку кнопкой, чтобы не перепутать фильм.')
                return self.downloads(chat_id)
            self.jobs.enqueue(source or ('intent:' + str(uid)), uid,
                              {'action': action, 'hash': matches[0]['hashString']})
            return self.send(chat_id, 'Поставлю на паузу.' if action == 'pause' else 'Проверю диск и продолжу загрузку.')
        return self.send(chat_id, 'Не удалось определить действие. Напиши, что нужно сделать.')

    def downloads(self, chat_id, page=0, selected=None):
        if not selected and self.jobs.read_state('download-dashboard:' + str(chat_id)):
            from bot.progress import ProgressMonitor
            from bot.download_dashboard import publish
            ProgressMonitor(self).tick()
            return publish(self, chat_id, time.time())
        try:
            status = self.media_status()
        except Exception:
            return self.send(chat_id, 'Mac сейчас недоступен. Сохранённые задания остаются в очереди.')
        if not status.get('disk_ok'):
            return self.send(chat_id, 'Mac на связи, но media disk не подключён или недоступен для записи. Новые загрузки ждут диск.')
        torrents = status.get('torrents', [])
        if not torrents:
            return self.send(chat_id, 'Mac и media disk на связи. Загрузок, добавленных через бота, пока нет.')
        if selected:
            torrent = next((t for t in torrents if t['hashString'] == selected), None)
            if torrent is None:
                return self.send(chat_id, 'Эта загрузка больше не найдена. Открой список заново.')
            state = self.jobs.read_state('transfer:%s:%s' % (chat_id, selected), {'name': torrent['name']})
            text, complete = progress_text(state, torrent, time.time())
            buttons = [] if complete else progress_markup(torrent)['inline_keyboard']
            buttons.append([{'text': 'Удалить…', 'callback_data': 'delete:' + selected},
                            {'text': 'Все загрузки', 'callback_data': 'downloads'}])
            return self.send_html(chat_id, text, {'inline_keyboard': buttons})
        page_size = 8
        page = min(max(0, page), (len(torrents) - 1) // page_size)
        lines = ['<b>Загрузки</b>']
        buttons = []
        for index, torrent in enumerate(torrents[page * page_size:(page + 1) * page_size], page * page_size + 1):
            name = html.escape(str(torrent['name'])[:180])
            _, complete = progress_text({'name': torrent['name']}, torrent, time.time())
            label = ('Ошибка' if torrent.get('errorString') or torrent.get('capacity_error') else
                     'Готово' if complete else 'На паузе' if torrent.get('status') == 0 else 'Загружается')
            lines.append('%d. <b>%s</b>\n%s · %.1f%% · %s' % (
                index, name, label, torrent.get('percentDone', 0) * 100, human_size(torrent.get('totalSize', 0))))
            buttons.append([{'text': 'Управление %d' % index, 'callback_data': 'download:' + torrent['hashString']}])
        navigation = []
        if page:
            navigation.append({'text': '← Назад', 'callback_data': 'downloads-page:' + str(page - 1)})
        if (page + 1) * page_size < len(torrents):
            navigation.append({'text': 'Далее →', 'callback_data': 'downloads-page:' + str(page + 1)})
        if navigation:
            buttons.append(navigation)
        return self.send_html(chat_id, '\n\n'.join(lines), {'inline_keyboard': buttons})
