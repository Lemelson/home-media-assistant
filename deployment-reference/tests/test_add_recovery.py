import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mac_agent.media import MediaController
from test_delivery import Telegram, Media
from bot.dialog import Dialog
from bot.delivery import DeliveryWorker

H = 'a' * 40
PAYLOAD = {'action': 'add', 'kind': 'movie', 'size_bytes': 100,
           'metainfo': base64.b64encode(b'd4:infod4:name4:testee').decode()}

class RPC:
    def __init__(self):
        self.rows = []
        self.lose_response = True
    def call(self, method, args=None):
        args = args or {}
        if method == 'torrent-get': return {'torrents': self.rows}
        if method == 'torrent-add':
            if self.rows: return {'torrent-duplicate': self.rows[0]}
            row = dict(hashString=H, name='Film', downloadDir=args['download-dir'],
                       totalSize=100, leftUntilDone=100, status=0, percentDone=0,
                       bandwidthPriority=0)
            self.rows.append(row)
            if self.lose_response:
                self.lose_response = False
                raise TimeoutError('response lost after Transmission added torrent')
            return {'torrent-added': row}
        if method == 'torrent-start-now':
            for row in self.rows:
                if row['hashString'] in args['ids']: row['status'] = 4
        return {}

class RecoveryTests(unittest.TestCase):
    def test_lost_add_response_survives_restart_and_starts_single_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = RPC(); root = Path(tmp)
            first = MediaController(root/'agent.db', rpc, lambda: root)
            with self.assertRaises(TimeoutError): first.command('job', PAYLOAD)
            restarted = MediaController(root/'agent.db', rpc, lambda: root)
            result = restarted.command('job', PAYLOAD)
            self.assertTrue(result['ok'])
            self.assertEqual(len(rpc.rows), 1)
            self.assertIn(H, restarted.store.read_state('managed'))
            self.assertEqual(rpc.rows[0]['status'], 4)
            self.assertEqual(restarted.command('job', PAYLOAD), result)

    def test_magnet_lost_response_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=RPC();root=Path(tmp);controller=MediaController(root/'agent.db',rpc,lambda:root)
            payload={'action':'add','magnet':'magnet:?xt=urn:btih:'+H,'size_bytes':100}
            with self.assertRaises(TimeoutError):controller.command('magnet',payload)
            self.assertTrue(controller.command('magnet',payload)['ok'])
            self.assertEqual(rpc.rows[0]['status'],4)

    def test_changed_job_payload_cannot_claim_pending_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=RPC();root=Path(tmp);controller=MediaController(root/'agent.db',rpc,lambda:root)
            with self.assertRaises(TimeoutError):controller.command('job',PAYLOAD)
            with self.assertRaisesRegex(ValueError,'add_intent_changed'):
                controller.command('job',{**PAYLOAD,'size_bytes':200})
            self.assertNotIn(H,controller.store.read_state('managed',{}))

    def test_preexisting_unmanaged_torrent_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=RPC(); root=Path(tmp)
            rpc.rows=[dict(hashString=H, name='Foreign', downloadDir=str(root/'Movies'), status=0)]
            controller=MediaController(root/'agent.db',rpc,lambda:root)
            with self.assertRaisesRegex(ValueError,'torrent_exists_outside_bot'):
                controller.command('job',PAYLOAD)
            self.assertNotIn(H,controller.store.read_state('managed',{}))
            self.assertEqual(rpc.rows[0]['status'],0)

    def test_interruption_after_managed_write_finishes_setup_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=RPC();rpc.lose_response=False;root=Path(tmp)
            controller=MediaController(root/'agent.db',rpc,lambda:root)
            with patch.object(controller.journal,'register',side_effect=RuntimeError('journal temporarily unavailable')):
                with self.assertRaises(RuntimeError):controller.command('job',PAYLOAD)
            restarted=MediaController(root/'agent.db',rpc,lambda:root)
            self.assertTrue(restarted.command('job',PAYLOAD)['ok'])
            self.assertEqual(rpc.rows[0]['status'],4)

    def test_recovery_does_not_adopt_torrent_moved_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=RPC();root=Path(tmp);controller=MediaController(root/'agent.db',rpc,lambda:root)
            with self.assertRaises(TimeoutError):controller.command('job',PAYLOAD)
            rpc.rows[0]['downloadDir']='/different/location'
            with self.assertRaisesRegex(ValueError,'download_location_changed'):
                controller.command('job',PAYLOAD)
            self.assertNotIn(H,controller.store.read_state('managed',{}))

    def test_recovered_torrent_stays_paused_when_space_is_insufficient(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=RPC();root=Path(tmp);controller=MediaController(root/'agent.db',rpc,lambda:root)
            with self.assertRaises(TimeoutError):controller.command('job',PAYLOAD)
            with patch.object(controller,'_capacity',return_value={'ok':False,'error':'insufficient_space'}):
                result=controller.command('job',PAYLOAD)
            self.assertEqual(result['error'],'insufficient_space')
            self.assertEqual(rpc.rows[0]['status'],0)

class DeliveryFeedbackTests(unittest.TestCase):
    def test_failed_add_replaces_queued_card_with_named_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram();media=Media({'ok':False,'error':'invalid_command'})
            dialog=Dialog(tmp,tg,'','',media.status)
            dialog.jobs.enqueue('film',1,{'action':'add','name':'Eternal Sunshine','message_id':214})
            DeliveryWorker(dialog,media,separate_progress=True).step(now=100)
            edits=[p for m,p in tg.calls if m=='editMessageText' and p.get('message_id')==214]
            self.assertTrue(edits)
            self.assertIn('Eternal Sunshine',edits[-1]['text'])
            self.assertIn('Не удалось',edits[-1]['text'])
