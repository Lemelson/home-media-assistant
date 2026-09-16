"""One transient card, updated only while its owning operation is active."""
import html
import threading
import time


class RequestProgress:
    def __init__(self,dialog,chat_id,message_id,transcript=None):
        self.dialog,self.chat_id,self.message_id=dialog,chat_id,message_id
        self.transcript=transcript
        self.stopped=threading.Event()
        self.lock=threading.Lock()
        self.stage='';self.details={};self.started=time.monotonic()
        self.thread=None

    def __enter__(self):
        if self.message_id:
            self.thread=threading.Thread(target=self._tick,name='request-progress',daemon=True)
            self.thread.start()
        return self

    def __exit__(self,*args):
        self.stopped.set()
        if self.thread:self.thread.join()
        # Wait for any synchronous stage edit before the caller renders its result.
        with self.lock:pass

    def update(self,stage,details=None):
        with self.lock:
            if self.stopped.is_set():return
            self.stage,self.details,self.started=stage,details or {},time.monotonic()
            self._render()

    def _tick(self):
        while not self.stopped.wait(5):
            with self.lock:
                if not self.stopped.is_set():self._render()

    def _render(self):
        if not self.message_id or not self.stage:return
        elapsed=int(time.monotonic()-self.started)
        if self.stage=='grounding':
            text='🔎 Проверяю название по источникам.'
        elif self.stage=='model':
            model=html.escape(str(self.details.get('model','модель')))
            text='🧠 Разбираю запрос с <b>'+model+'</b>.\nОжидаю ответ модели.'
            estimate=self.details.get('median_seconds')
            count=self.details.get('count',0)
            if estimate is not None and count>=3:
                text+='\nОбычно около %.0f с — медиана %d успешных запросов.' % (estimate,count)
            else:text+='\nСобираю статистику времени обработки.'
        elif self.stage=='resolved':
            text='✅ Ответ модели получен за %.1f с. Готовлю варианты.' % self.details.get('seconds',0)
        elif self.stage=='images':
            text='🖼 Фильмы определены. Подбираю постеры и готовлю кнопки выбора.'
        else:return
        if self.stage!='resolved':text+='\nНа этом этапе прошло %d с.' % elapsed
        if self.transcript:text+='\n<blockquote>'+html.escape(str(self.transcript)[:1000])+'</blockquote>'
        try:self.dialog.edit_html(self.chat_id,self.message_id,text)
        except Exception:pass
