"""Transmission RPC, authenticated locally, with the required session handshake."""

import base64
import json
import threading
import urllib.error
import urllib.request


class TransmissionRPC:
    def __init__(self, username, password):
        self.headers = {
            'Authorization': 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode(),
            'Content-Type': 'application/json',
        }
        self.lock = threading.Lock()

    def call(self, method, arguments=None):
        data = json.dumps({'method': method, 'arguments': arguments or {}}).encode()
        with self.lock:
            for attempt in range(2):
                req = urllib.request.Request('http://127.0.0.1:9091/transmission/rpc', data=data, headers=self.headers)
                try:
                    with urllib.request.urlopen(req, timeout=15) as response:
                        result = json.loads(response.read(4 * 1024 * 1024))
                except urllib.error.HTTPError as error:
                    if error.code == 409 and attempt == 0:
                        self.headers['X-Transmission-Session-Id'] = error.headers['X-Transmission-Session-Id']
                        continue
                    raise RuntimeError('transmission_http_' + str(error.code)) from None
                if result.get('result') != 'success':
                    raise RuntimeError('transmission_command_failed')
                return result.get('arguments', {})
        raise RuntimeError('transmission_session_failed')
