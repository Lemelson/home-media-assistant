"""Loopback-only HTTP agent, reached from a remote server through an SSH reverse tunnel."""

import hmac
import json
import logging
import os
import plistlib
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from mac_agent.media import DiskUnavailable, MediaController
from mac_agent.rpc import TransmissionRPC


def make_handler(controller, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            actual = self.headers.get('Authorization', '').encode()
            if not hmac.compare_digest(actual, ('Bearer ' + token).encode()):
                self.respond(401, {'error': 'unauthorized'})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if self.path not in ('/status', '/library'):
                self.respond(404, {'error': 'not_found'})
                return
            try:
                self.respond(200, controller.library() if self.path == '/library' else controller.status())
            except DiskUnavailable:
                self.respond(503, {'error': 'disk_missing'})
            except Exception:
                self.respond(503, {'error': 'transmission_unavailable'})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/command':
                self.respond(404, {'error': 'not_found'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 3 * 1024 * 1024:
                    raise ValueError('invalid_body_size')
                payload = json.loads(self.rfile.read(length))
                result = controller.command(payload['id'], payload['payload'])
                self.respond(200, result)
            except DiskUnavailable:
                self.respond(503, {'error': 'disk_missing'})
            except (ValueError, KeyError, TypeError):
                self.respond(400, {'error': 'invalid_command'})
            except Exception:
                self.respond(503, {'error': 'transmission_unavailable'})
    return Handler


def volume_guard(volume_path, expected_uuid):
    volume = Path(volume_path)
    def check():
        # A transient diskutil timeout is not evidence that the mounted disk
        # vanished. Retry once, checking the mount again; never use cached UUIDs.
        for attempt in range(2):
            if not os.path.ismount(volume):
                raise DiskUnavailable('disk_missing')
            started = time.monotonic()
            try:
                info = plistlib.loads(subprocess.check_output(
                    ['/usr/sbin/diskutil', 'info', '-plist', str(volume)], timeout=8, stderr=subprocess.DEVNULL))
                break
            except subprocess.TimeoutExpired:
                reason = 'disk_probe_timeout'
            except subprocess.SubprocessError:
                reason = 'disk_probe_failed'
            except (ValueError, plistlib.InvalidFileException):
                raise DiskUnavailable('disk_probe_invalid') from None
            logging.warning('%s attempt=%d elapsed=%.2f', reason, attempt + 1, time.monotonic() - started)
            if attempt:
                raise DiskUnavailable(reason) from None
        if not isinstance(info, dict):
            raise DiskUnavailable('disk_probe_invalid')
        if info.get('VolumeUUID') != expected_uuid or info.get('MountPoint') != str(volume) or not info.get('Writable'):
            raise DiskUnavailable('wrong_or_readonly_disk')
        root = volume / 'MediaServer'
        if root.is_symlink() or not root.is_dir():
            raise DiskUnavailable('media_folder_missing')
        for name in ('Movies', 'TV', 'Downloads/Incomplete'):
            folder = root / name
            if not folder.is_dir() or folder.resolve() != folder:
                raise DiskUnavailable('media_folder_changed')
        return root
    return check


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    state = Path(os.environ.get('AGENT_STATE_DIRECTORY', str(Path.home() / 'Library/Application Support/HomeMediaAssistant')))
    config = json.loads((state / 'agent.json').read_text())
    if len(config.get('token', '')) < 32:
        raise ValueError('agent token must contain at least 32 characters')
    rpc_config = json.loads((state / 'transmission-rpc.json').read_text())
    rpc = TransmissionRPC(**rpc_config)
    controller = MediaController(state / 'agent.db', rpc, volume_guard(config['volume'], config['volume_uuid']))
    def watch():
        while True:
            try:
                controller.guard_disk()
            except DiskUnavailable as error:
                logging.warning('disk_guard_unavailable reason=%s', str(error))
            except Exception as error:
                logging.warning('disk_guard_transmission_unavailable type=%s', type(error).__name__)
            try:
                controller.collect_history()
            except Exception as error:
                logging.warning('history_collection_failed type=%s',type(error).__name__)
            time.sleep(10)
    threading.Thread(target=watch, daemon=True).start()
    server = HTTPServer(('127.0.0.1', 18742), make_handler(controller, config['token']))
    logging.info('agent_ready_loopback_18742')
    server.serve_forever()


if __name__ == '__main__':
    main()
