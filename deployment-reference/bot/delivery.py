"""Deliver durable commands and report actual results separately from queued requests."""

import html
import logging
import time

from bot.library_dialog import human_size
from bot.progress import ProgressMonitor
from bot.media_labels import decorate


class DeliveryWorker:
    def __init__(self, dialog, media, separate_controls=False, separate_progress=False):
        self.separate_progress = separate_progress
        self.separate_controls = separate_controls
        self.dialog = dialog
        self.media = media
        self.monitor = ProgressMonitor(dialog)
        self.last_progress = 0

    def step(self, now=None):
        now = time.time() if now is None else now
        for job in [j for j in self.dialog.jobs.pending() if not self.separate_controls or j['payload'].get('action') != 'bandwidth_priority'][:3]:
            try:
                result = self.media.command(job)
            except Exception:
                break
            self.dialog.jobs.finish(job['id'], result)
        for job in self.dialog.jobs.unnotified():
            if self.separate_controls and job['payload'].get('action') == 'bandwidth_priority':
                continue
            try:
                self.notify(job, now)
                self.dialog.jobs.mark_notified(job['id'])
            except Exception:
                logging.warning('job_notification_failed id=%s', job['id'])
                break
        if now - self.last_progress >= 15:
            self.dialog.clean_messages()
            if self.separate_progress:
                from bot.download_dashboard import cleanup_pending
                for key in self.dialog.jobs.read_states('download-dashboard:'):
                    cleanup_pending(self.dialog, int(key.split(':')[1]))
            if not self.separate_progress:
                self.monitor.tick(now)
            self.last_progress = now

    def control_step(self, now=None):
        now = time.time() if now is None else now
        for job in self.dialog.jobs.pending_priorities()[:3]:
            started = time.monotonic()
            try:
                result = self.media.command(job)
            except Exception:
                break
            self.dialog.jobs.finish(job['id'], result)
            logging.info('priority_command_finished elapsed=%.3f ok=%s', time.monotonic()-started, bool(result.get('ok')))
        for job in self.dialog.jobs.unnotified():
            if job['payload'].get('action') != 'bandwidth_priority':
                continue
            try:
                self.notify(job, now)
                self.dialog.jobs.mark_notified(job['id'])
            except Exception:
                break

    def notify_priority(self, job, now):
        from bot.download_dashboard import publish
        result = job['result']
        updates = result.get('priorities') or {result.get('hash'):result.get('priority')}
        for h, priority in updates.items():
            if h and priority in (-1,0,1):
                self.dialog.jobs.write_state('priority-confirmed:'+h, dict(priority=priority, paused=bool(result.get('paused')) if h==result.get('hash') else False, at=time.time()))
        # Confirmation comes directly from the command result; no slow /status request.
        if publish(self.dialog, job['user_id'], now, cleanup=False, wait=False) is False:
            raise RuntimeError('dashboard_busy')

    def notify(self, job, now):
        result = job['result']
        if result.get('superseded'):return
        uid = job['user_id']
        action = job['payload']['action']
        if result.get('ok'):
            if action == 'add':
                if result.get('selected_seasons') and result.get('hash'):
                    self.dialog.jobs.write_state('naming:'+result['hash'],{})
                if job['payload'].get('media') and result.get('hash'):
                    self.dialog.jobs.write_state('film:'+result['hash'], {
                        'media':job['payload']['media'], 'quality':job['payload'].get('quality',{}),
                        'fallback':job['payload'].get('name','')})
                return self.monitor.register(uid, {**decorate(self.dialog.jobs,result),
                    'totalSize':result.get('size_bytes') or result.get('totalSize') or job['payload'].get('size_bytes',0),
                    'message_id':job['payload'].get('message_id')}, now)
            if action == 'bandwidth_priority':
                return self.notify_priority(job, now)
            if action == 'delete_library':
                title=self.dialog.jobs.read_state('delete-label:'+str(uid)+':'+job['payload']['inventory_id'],{}).get('name','Видео')
                return self.dialog.send_html(uid, '✅ <b>Удалено: «%s»</b>\nВидеофайлов: %d. Освобождено %s.' % (html.escape(title),
                    result.get('deleted_files', 0), human_size(result.get('freed_bytes', 0))))
            return self.dialog.send(uid, '⏸ Загрузка на паузе.' if action == 'pause' else
                                    '▶️ Загрузка продолжена.' if action == 'resume' else 'Команда выполнена.')
        error = result.get('error')
        if error == 'insufficient_space':
            name = html.escape(str(job['payload'].get('name') or 'Новая загрузка')[:180])
            lines = ['<b>Не хватает места для %s</b>' % name,
                     'Нужно: %s · свободно: %s' % (human_size(result.get('required_bytes', 0)), human_size(result.get('free_bytes', 0))),
                     'Зарезервировано другими загрузками: %s. Оставляю запас %s.' % (
                         human_size(result.get('reserved_bytes', 0)), human_size(result.get('headroom_bytes', 0))),
                     '\nМожно удалить скачанное — сначала самые большие:']
            buttons = []
            for index, item in enumerate(sorted(result.get('biggest', []), key=lambda item: item.get('size_bytes', 0), reverse=True)[:5], 1):
                lines.append('%d. <b>%s</b> · %s' % (index, html.escape(str(item['name'])[:160]), human_size(item.get('size_bytes', 0))))
                buttons.append([{'text': '🗑 %d · %s · %s' % (index, str(item['name'])[:25], human_size(item.get('size_bytes', 0))),
                                 'callback_data': 'library-delete:' + item['id']}])
            buttons.append([{'text': 'Проверить место ещё раз', 'callback_data': 'retry:' + job['id']},
                            {'text': 'Вся медиатека', 'callback_data': 'library'}])
            return self.dialog.send_html(uid, '\n'.join(lines), {'inline_keyboard': buttons})
        if error in ('season_files_missing','season_files_ambiguous','season_selection_not_confirmed'):
            text='Не удалось однозначно выбрать файлы нужного сезона. Новые файлы не запускаю. Пришли .torrent с понятными сезонами в именах файлов или выбери другую раздачу.'
            message_id=job['payload'].get('message_id')
            if message_id:return self.dialog.edit_html(uid,message_id,text,{'inline_keyboard':[]})
            return self.dialog.send(uid,text)
        if error == 'size_unknown':
            return self.dialog.send(uid, 'Размер раздачи пока неизвестен. Загрузка оставлена на паузе, чтобы не переполнить диск. '
                                    'Пришли .torrent или выбери раздачу из поиска с известным размером.',
                                    {'inline_keyboard': [[{'text': 'Проверить размер ещё раз', 'callback_data': 'retry:' + job['id']}]]})
        if action == 'add':
            name = html.escape(str(job['payload'].get('name') or 'Фильм')[:180])
            text = 'Не удалось добавить <b>%s</b> в загрузки. Запрос завершился ошибкой; скачивание не подтверждено.' % name
            markup = {'inline_keyboard': [[{'text': 'Загрузки', 'callback_data': 'downloads'},
                                           {'text': 'Новый поиск', 'callback_data': 'search'}]]}
            message_id = job['payload'].get('message_id')
            if message_id:
                return self.dialog.edit_html(uid, message_id, text, markup)
            return self.dialog.send_html(uid, text, markup)
        return self.dialog.send(uid, 'Команда не выполнена. Объект мог измениться; открой актуальный список и выбери его заново.',
                                {'inline_keyboard': [[{'text': 'Медиатека', 'callback_data': 'library'},
                                                      {'text': 'Загрузки', 'callback_data': 'downloads'}]]})
