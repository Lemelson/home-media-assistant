import json
import http.client
import io
import logging
import copy
import threading
import time
import urllib.error
import urllib.request


class APIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token, persistent=False):
        self.persistent = persistent
        self._connections = threading.local()
        self.base = 'https://api.telegram.org/bot' + token + '/'
        self._retry_after = 0.0

    def call(self, method, **payload):
        if method in ('sendMessage','editMessageText'):
            payload.setdefault('link_preview_options', {'is_disabled': True})
        if time.monotonic() < self._retry_after:
            raise APIError('telegram_rate_limited')
        request = urllib.request.Request(self.base + method, data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        try:
            timeout = 2 if method in ('answerCallbackQuery','deleteMessage') else 3 if method in ('editMessageText','editMessageReplyMarkup') else 30
            if self.persistent:
                result = self._persistent_json(request, timeout)
            else:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    result = json.loads(response.read(8 * 1024 * 1024))
        except urllib.error.HTTPError as error:
            # Expose only known constant classifications, never credential-bearing URLs.
            try:details=json.loads(error.read(8192))
            except Exception:details={}
            description=str(details.get('description','')).lower()
            if error.code==429:
                delay=details.get('parameters',{}).get('retry_after',5)
                if type(delay) not in (int,float):delay=5
                self._retry_after=time.monotonic()+max(1,min(1200,delay))
                raise APIError('telegram_rate_limited') from None
            for reason in ('message to delete not found','message to edit not found','message is not modified'):
                if reason in description:raise APIError(reason) from None
            raise APIError('telegram_request_failed:' + method) from None
        except Exception:
            raise APIError('telegram_request_failed:' + method) from None
        if not result.get('ok'):
            raise APIError('telegram_rejected:' + method)
        return result['result']

    def _persistent_json(self, request, timeout):
        # One connection per worker: long polling never owns a UI worker's socket.
        conn = getattr(self._connections, 'connection', None)
        if conn is not None and time.monotonic()-getattr(self._connections,'last_used',0)>15:
            conn.close()
            conn=None
        if conn is None:
            conn = http.client.HTTPSConnection('api.telegram.org', timeout=timeout)
            self._connections.connection = conn
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        try:
            conn.request('POST', request.selector, body=request.data,
                         headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('response_too_large')
            if response.status >= 400:
                raise urllib.error.HTTPError('', response.status, '', {}, io.BytesIO(raw))
            self._connections.last_used=time.monotonic()
            return json.loads(raw)
        except Exception:
            conn.close()
            self._connections.connection = None
            # Never retry an uncertain mutation: Telegram may have accepted it.
            raise

    def download_file(self, file_id, max_bytes):
        info = self.call('getFile', file_id=file_id)
        path = info['file_path']
        if '..' in path or path.startswith('/') or '://' in path:
            raise APIError('invalid_file_path')
        url = self.base.replace('/bot', '/file/bot', 1) + path
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(max_bytes + 1)
        except Exception:
            raise APIError('telegram_file_download_failed') from None
        if len(data) > max_bytes:
            raise APIError('file_too_large')
        return data


class MediaAPI:
    def __init__(self, token, base='http://127.0.0.1:18741'):
        self.base = base
        self.token = token
        self._status_condition = threading.Condition()
        self._status_cache = None
        self._status_until = 0.0
        self._status_inflight = False
        self._status_generation = 0
        self._status_failures = 0
        self._status_retry = 0.0

    def request(self, path, payload=None):
        request = urllib.request.Request(self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=35 if path == '/status' else 20) as response:
                return json.loads(response.read(4 * 1024 * 1024))
        except urllib.error.HTTPError as error:
            if error.code == 400:
                return {'ok': False, 'error': 'invalid_command'}
            logging.warning('media_request_failed reason=http_%d',error.code)
            raise APIError('mac_unavailable') from None
        except Exception as error:
            logging.warning('media_request_failed type=%s',type(error).__name__)
            raise APIError('mac_unavailable') from None

    def status(self):
        deadline=time.monotonic()+35
        with self._status_condition:
            while True:
                now=time.monotonic()
                if self._status_cache is not None and now<self._status_until:
                    return copy.deepcopy(self._status_cache)
                if now<self._status_retry:raise APIError('mac_unavailable')
                if not self._status_inflight:
                    self._status_inflight=True
                    generation=self._status_generation
                    break
                remaining=deadline-now
                if remaining<=0:raise APIError('status_refresh_pending')
                self._status_condition.wait(remaining)
        try:
            result=self.request('/status')
            with self._status_condition:
                if generation==self._status_generation:
                    self._status_cache=copy.deepcopy(result)
                    self._status_until=time.monotonic()+2
                self._status_failures=0
                self._status_retry=0
            return result
        except Exception:
            with self._status_condition:
                self._status_failures+=1
                self._status_retry=time.monotonic()+min(10,2**min(self._status_failures,4))
            raise
        finally:
            with self._status_condition:
                self._status_inflight=False
                self._status_condition.notify_all()


    def library(self):
        return self.request('/library')

    def command(self, job):
        try:
            return self.request('/command', {'id': job['id'], 'payload': job['payload']})
        finally:
            with self._status_condition:
                self._status_generation+=1
                self._status_cache=None
                self._status_retry=0
