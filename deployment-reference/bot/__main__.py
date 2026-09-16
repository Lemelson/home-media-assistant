import logging
import html
import json
import os
import signal
import threading
import time
from pathlib import Path

from bot.dialog import Dialog, callback_notice
from bot.providers import DeepSeek, Serper, Prowlarr
from bot.search import SearchFlow
from bot.transport import MediaAPI, TelegramAPI
from bot.delivery import DeliveryWorker
from bot.inbox import Inbox
from bot.speech import OpenRouterTranscriber
from bot.posters import TMDBPosters
from bot.web_search import ExaSearch
from bot.movie_images import MovieImages


def acknowledge_message(dialog, update):
    """Best-effort private intake receipt, outside serialized provider work.

    Do not use Dialog.send here: its history and markup writes belong to the
    per-user worker. Inbox persists the returned ID for that worker to reuse.
    """
    if update.get('callback_query'):
        return None
    message=update.get('message') or {}
    text=str(message.get('text') or '').strip()
    if not message.get('voice') and (not text or text.startswith('/') or text.startswith('magnet:')):
        return None
    if text.casefold() in ('🔎 найти фильм', 'найти фильм', 'медиатека', 'скачанные фильмы'):
        return None
    if Inbox._routing(update)[0].endswith(':fast'):
        return None
    user=message.get('from') or {}; chat=message.get('chat') or {}
    if not chat.get('id') or chat.get('type')!='private':
        return None
    role=dialog.access.check(user.get('id'),user.get('username'),chat.get('type'),event='receipt')
    if role not in ('owner','mother'):
        return None
    excerpt=' '.join(text.split())
    if len(excerpt)>160:excerpt=excerpt[:159]+'…'
    payload={'chat_id':chat['id'], 'text':'🔎 Разбираю запрос <b>«'+html.escape(excerpt)+'»</b>.',
             'parse_mode':'HTML'}
    if message.get('voice'):
        payload['text'] = '🎙 <b><i>Голосовое принято</i></b>'
    if message.get('message_id'):
        payload['reply_parameters']={'message_id':message['message_id'],'allow_sending_without_reply':True}
    result=dialog.telegram.call('sendMessage',**payload)
    return result.get('message_id')


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    from bot.config import settings
    config = settings(os.environ)
    state = Path(os.environ.get('STATE_DIRECTORY', './runtime'))
    telegram = TelegramAPI(os.environ['TELEGRAM_BOT_TOKEN'], persistent=True)
    media = MediaAPI(os.environ['MEDIA_AGENT_TOKEN'], base=config['agent_url'])
    identity = telegram.call('getMe')
    if not identity.get('is_bot'):
        raise RuntimeError('unexpected_bot_identity')
    search = None
    if os.environ.get('OPENROUTER_API_KEY'):
        exa=ExaSearch(os.environ['EXA_API_KEY'],proxy=os.environ.get('EXA_HTTP_PROXY')) if os.environ.get('EXA_API_KEY') else None
        from bot.model_metrics import ModelMetrics
        resolver = DeepSeek(os.environ['OPENROUTER_API_KEY'], os.environ['OPENROUTER_MODEL'], os.environ.get('OPENROUTER_REASONING_EFFORT', 'high'),
                            web_search=exa, metrics=ModelMetrics(state/'model-metrics.db'))
        indexer = Prowlarr(os.environ['PROWLARR_API_KEY']) if os.environ.get('PROWLARR_API_KEY') else None
        if not config['images']:
            images=None
        elif exa:
            images=MovieImages(exa)
        elif os.environ.get('TMDB_READ_ACCESS_TOKEN'):
            images = TMDBPosters(os.environ['TMDB_READ_ACCESS_TOKEN'])
        elif os.environ.get('TMDB_API_KEY'):
            images = TMDBPosters(os.environ['TMDB_API_KEY'], bearer=False)
        else:
            images = Serper(os.environ['SERPER_API_KEY']).image if os.environ.get('SERPER_API_KEY') else None
        search = SearchFlow(resolver, indexer, images, allow_remote_images=config['images'])
    transcribe = None
    if config['voice'] and os.environ.get('OPENROUTER_API_KEY'):
        transcribe = OpenRouterTranscriber(os.environ['OPENROUTER_API_KEY'], telegram,
                                          os.environ.get('OPENROUTER_STT_MODEL', 'openai/whisper-large-v3-turbo'))
    dialog = Dialog(state, telegram, '', '', media.status, search=search,
                    transcribe=transcribe, media_library=media.library,
                    owner_id=config['owner_id'], member_id=config['member_id'])
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())

    delivery = DeliveryWorker(dialog, media, separate_controls=True, separate_progress=True)
    inbox = Inbox(state, dialog.handle, on_failure=lambda chat_id: dialog.send(
        chat_id, 'Не удалось обработать сообщение. Напиши ещё раз; сохранённые загрузки остаются в очереди.'),
        on_receipt=lambda update: acknowledge_message(dialog, update), async_receipts=True, reserve_controls=True)

    def deliver():
        while not stopping.is_set():
            try:
                delivery.step()
            except Exception:
                logging.warning('delivery_iteration_failed')
            stopping.wait(3)

    def controls():
        while not stopping.is_set():
            try: delivery.control_step()
            except Exception: logging.warning('priority_delivery_failed')
            stopping.wait(.5)

    def heartbeat():
        temporary = state / 'heartbeat.tmp'
        temporary.write_text(json.dumps({'revision': Path.cwd().name, 'time': time.time()}))
        temporary.replace(state / 'heartbeat')

    threading.Thread(target=deliver, daemon=True).start()
    threading.Thread(target=controls, daemon=True).start()
    def refresh_status():
        while not stopping.is_set():
            try: delivery.monitor.tick(publish_updates=False)
            except Exception as error:
                logging.warning('status_refresh_failed type=%s', type(error).__name__)
            stopping.wait(15)
    threading.Thread(target=refresh_status, daemon=True).start()

    def control_display():
        from bot.download_dashboard import CONTROL_WAKE
        from bot.status_delivery import DashboardDelivery
        display = DashboardDelivery(dialog)
        while not stopping.is_set():
            CONTROL_WAKE.wait(3)
            CONTROL_WAKE.clear()
            display.step()
    threading.Thread(target=control_display,daemon=True).start()

    if search is not None:
        from bot.naming_worker import NamingWorker, NamingAPI
        naming = NamingWorker(dialog.jobs, NamingAPI(media), resolver)
        def organize_media():
            while not stopping.is_set():
                try:
                    naming.step()
                except Exception as error:
                    logging.warning('media_naming_unavailable type=%s', type(error).__name__)
                stopping.wait(60)
        threading.Thread(target=organize_media, daemon=True).start()
    inbox.pump()
    heartbeat()
    logging.info('bot_ready username=%s', identity['username'])
    while not stopping.is_set():
        try:
            offset = dialog.jobs.read_state('telegram_offset', 0)
            updates = telegram.call('getUpdates', offset=offset, timeout=10, allowed_updates=['message', 'callback_query'])
            for update in updates:
                if update['update_id'] < offset:
                    continue
                callback = update.get('callback_query')
                if callback:
                    try:
                        telegram.call('answerCallbackQuery', callback_query_id=callback['id'], text=callback_notice(callback.get('data','')))
                        update['_callback_answered'] = True
                    except Exception:
                        pass
                if not inbox.enqueue(update):
                    break
                dialog.jobs.write_state('telegram_offset', update['update_id'] + 1)
            inbox.pump()
            heartbeat()
        except Exception:
            logging.warning('telegram_poll_failed')
            stopping.wait(5)
    inbox.stop()


if __name__ == '__main__':
    main()
