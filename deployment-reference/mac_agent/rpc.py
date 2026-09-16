"""Transmission RPC, authenticated locally, with the required session handshake."""

import base64
import json
import logging
import time
import threading
import urllib.error
import urllib.request


LOCK_TIMEOUT = 2


class TransmissionRPC:
    def __init__(self, username, password):
        self.headers = {
            'Authorization': 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode(),
            'Content-Type': 'application/json',
        }
        self.lock = threading.Lock()
        self.session_lock = threading.Lock()

    def call(self, method, arguments=None):
        data = json.dumps({'method': method, 'arguments': arguments or {}}).encode()
        # Read-only snapshots must not wait behind unrelated controller commands.
        # Mutations remain serialized; session headers have their own short lock.
        serialize = method not in ('torrent-get', 'session-get')
        started = time.monotonic()
        if serialize and not self.lock.acquire(timeout=LOCK_TIMEOUT):
            raise RuntimeError('transmission_busy')
        try:
            for attempt in range(2):
                with self.session_lock:
                    headers = dict(self.headers)
                req = urllib.request.Request('http://127.0.0.1:9091/transmission/rpc', data=data, headers=headers)
                try:
                    timeout = 15 if serialize else 30-(time.monotonic()-started)
                    if timeout<=0:raise TimeoutError('transmission_read_deadline')
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        result = json.loads(response.read(4 * 1024 * 1024))
                except urllib.error.HTTPError as error:
                    if error.code == 409 and attempt == 0:
                        with self.session_lock:
                            self.headers['X-Transmission-Session-Id'] = error.headers['X-Transmission-Session-Id']
                        continue
                    raise RuntimeError('transmission_http_' + str(error.code)) from None
                if result.get('result') != 'success':
                    raise RuntimeError('transmission_command_failed')
                return result.get('arguments', {})
        except Exception as error:
            logging.warning('transmission_rpc_failed type=%s elapsed=%.2f',type(error).__name__,time.monotonic()-started)
            raise
        finally:
            if serialize:self.lock.release()
            elapsed=time.monotonic()-started
            if elapsed>=3:logging.warning('transmission_rpc_slow elapsed=%.2f read_only=%s',elapsed,not serialize)
        raise RuntimeError('transmission_session_failed')
