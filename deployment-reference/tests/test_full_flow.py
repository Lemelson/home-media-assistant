"""Local integration evidence only: real agent HTTP; no Telegram/provider/network service."""
import base64
import copy
import hashlib
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from bot.delivery import DeliveryWorker
from bot.dialog import Dialog
from bot.search import SearchFlow
from bot.transport import MediaAPI
from mac_agent.media import MediaController
from mac_agent.server import make_handler


class LocalTelegram:
    def __init__(self):
        self.calls = []

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {'message_id': len(self.calls)}

    def button(self, prefix):
        for method, payload in reversed(self.calls):
            for row in payload.get('reply_markup', {}).get('inline_keyboard', []):
                for button in row:
                    if button.get('callback_data', '').startswith(prefix):
                        return button['callback_data'], self.calls.index((method, payload)) + 1
        raise AssertionError('No rendered button with prefix ' + prefix)


class LocalTransmission:
    """Models Transmission's metadata, preallocation, progress, and RPC field selection."""
    HASH = 'a' * 40
    NAME = 'Film (2008).mkv'
    SIZE = 1024

    def __init__(self):
        self.torrents = {}
        self.calls = []

    def call(self, method, arguments=None):
        args = arguments or {}
        self.calls.append((method, copy.deepcopy(args)))
        if method == 'torrent-add':
            raw = base64.b64decode(args['metainfo'], validate=True)
            if b'6:lengthi1024e' not in raw:
                raise ValueError('test torrent missing known metadata')
            destination = Path(args['download-dir'])
            # A fully preallocated filename is still not a completed download.
            (destination / self.NAME).write_bytes(b'\0' * self.SIZE)
            self.torrents[self.HASH] = {
                'hashString': self.HASH, 'name': self.NAME, 'downloadDir': str(destination),
                'status': 0, 'totalSize': self.SIZE, 'sizeWhenDone': self.SIZE,
                'leftUntilDone': self.SIZE, 'percentDone': 0, 'rateDownload': 0,
                'eta': -1, 'errorString': '', 'files': [
                    {'name': self.NAME, 'length': self.SIZE, 'bytesCompleted': 0}]}
            return {'torrent-added': {'hashString': self.HASH, 'name': self.NAME}}
        selected = [value for key, value in self.torrents.items() if not args.get('ids') or key in args['ids']]
        if method == 'torrent-get':
            return {'torrents': [{key: copy.deepcopy(value) for key, value in t.items()
                                  if key in args['fields']} for t in selected]}
        if method == 'torrent-set':
            for torrent in selected: torrent.update({k:v for k,v in args.items() if k!='ids'})
            return {}
        if method in ('torrent-start', 'torrent-start-now', 'torrent-stop'):
            for torrent in selected:
                torrent['status'] = 4 if method in ('torrent-start','torrent-start-now') else 0
            return {}
        if method == 'torrent-remove':
            if args.get('delete-local-data'):
                raise AssertionError('Controller must delete through scoped inventory only')
            for torrent_hash in args['ids']:
                self.torrents.pop(torrent_hash, None)
            return {}
        raise AssertionError('Unexpected RPC method ' + method)

    def advance(self, completed):
        torrent = self.torrents[self.HASH]
        torrent.update(leftUntilDone=self.SIZE - completed, percentDone=completed / self.SIZE,
                       status=6 if completed == self.SIZE else 4, rateDownload=8, eta=60)
        torrent['files'][0]['bytesCompleted'] = completed
        path = Path(torrent['downloadDir']) / self.NAME
        path.write_bytes(b'v' * completed + b'\0' * (self.SIZE - completed))


class FullFlowTests(unittest.TestCase):
    def test_owner_selects_download_tracks_progress_and_confirms_scoped_deletion(self):
        class Resolver:
            def identify(self, text, context):
                if text == 'удали Film':
                    return {'action': 'delete', 'target': 'Film'}
                return {'candidates': [{'title': 'Film', 'year': 2008, 'kind': 'movie'}]}

        class Indexer:
            def search(self, query):
                return [{'title': 'Film (2008) BDRip 1080p release%d' % i,
                         'guid': 'release%d' % i, 'seeders': 20 - i, 'size': 1024,
                         'categories': [{'id': 2000}]} for i in range(7)]

            def download(self, row):
                return {'metainfo': base64.b64encode(
                    b'd4:infod6:lengthi1024e4:name15:Film (2008).mkv12:piece lengthi16384e6:pieces20:'
                    + hashlib.sha1(b'v' * 1024).digest() + b'ee').decode()}

        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            root = temp / 'MediaServer'
            (root / 'Movies').mkdir(parents=True)
            (root / 'TV').mkdir()
            sentinel = temp / 'outside.mkv'
            sentinel.write_bytes(b'external sentinel')
            (root / 'Movies' / 'escape.mkv').symlink_to(sentinel)
            subtitle = root / 'Movies' / 'Film (2008).srt'
            subtitle.write_text('Keep this subtitle')
            rpc = LocalTransmission()
            controller = MediaController(temp / 'agent.db', rpc, lambda: root)
            server = HTTPServer(('127.0.0.1', 0), make_handler(controller, 'local-test-token'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                api = MediaAPI('local-test-token', 'http://127.0.0.1:%d' % server.server_port)
                telegram = LocalTelegram()
                dialog = Dialog(temp / 'bot', telegram, 'owner', '', api.status,
                                search=SearchFlow(Resolver(), Indexer()), media_library=api.library)
                worker = DeliveryWorker(dialog, api)
                event = [0]

                def message(text):
                    event[0] += 1
                    dialog.handle({'update_id': event[0], 'message': {
                        'from': {'id': 10, 'username': 'owner'},
                        'chat': {'id': 10, 'type': 'private'}, 'text': text}})

                def press(prefix):
                    data, message_id = telegram.button(prefix)
                    event[0] += 1
                    dialog.handle({'update_id': event[0], 'callback_query': {
                        'id': 'callback%d' % event[0], 'from': {'id': 10, 'username': 'owner'},
                        'data': data, 'message': {'message_id': message_id,
                        'chat': {'id': 10, 'type': 'private'}}}})

                message('Найди Film 2008')
                self.assertEqual(dialog.jobs.pending(), [])
                press('media:')
                selection = dialog.jobs.read_state('search:10')
                self.assertEqual(len(selection['releases']), 7)
                self.assertEqual(dialog.jobs.pending(), [], 'Owner must explicitly pick a release')
                press('release:')
                self.assertEqual(len(dialog.jobs.pending()), 1)
                worker.step(now=100)
                self.assertEqual(dialog.jobs.pending(), [])
                video = root / 'Movies' / rpc.NAME
                self.assertTrue(video.exists())
                self.assertEqual(api.status()['torrents'][0]['remaining_bytes'], rpc.SIZE)
                self.assertEqual(api.library()['items'], [], 'Preallocated partial files must stay hidden')
                rpc.advance(512)
                api._status_until=0  # Simulated minute advances beyond the two-second cache.
                worker.step(now=160)
                edits = [p for method, p in telegram.calls if method == 'editMessageText' and '50.0%' in p['text']]
                self.assertEqual(len(edits), 1)
                self.assertIn('50.0%', edits[0]['text'])
                rpc.advance(1024)
                api._status_until=0
                worker.step(now=220)
                notices = [p for method, p in telegram.calls if method == 'editMessageText' and 'Фильм скачан' in p['text']]
                self.assertEqual(len(notices), 1)
                DeliveryWorker(dialog, api).step(now=280)
                self.assertEqual(len([p for method, p in telegram.calls if method == 'editMessageText' and 'Фильм скачан' in p['text']]), 1)
                message('/library')
                inventory = api.library()['items']
                self.assertEqual(len(inventory), 1)
                self.assertEqual(inventory[0]['name'], rpc.NAME)
                message('удали Film')
                self.assertEqual(dialog.jobs.pending(), [])
                self.assertTrue(video.exists(), 'Offering deletion must not delete anything')
                press('confirm:')
                self.assertEqual(len(dialog.jobs.pending()), 1)
                self.assertTrue(video.exists(), 'Confirmation queues; delivery performs deletion')
                worker.step(now=340)
                self.assertFalse(video.exists())
                self.assertEqual(sentinel.read_bytes(), b'external sentinel')
                self.assertEqual(subtitle.read_text(), 'Keep this subtitle')
                self.assertEqual(api.library()['items'], [])
                self.assertEqual(api.status()['torrents'], [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
