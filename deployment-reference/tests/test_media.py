import tempfile
import base64
import unittest
from pathlib import Path

from mac_agent.media import MediaController, DiskUnavailable, first_episode_index


class FakeRPC:
    def __init__(self):
        self.torrents = []
        self.downloads = 0

    def call(self, method, arguments=None):
        arguments = arguments or {}
        if method == 'torrent-get':
            return {'torrents': self.torrents}
        if method == 'torrent-add':
            self.downloads += 1
            item = {'hashString': 'a' * 40, 'name': 'Test movie', 'totalSize': 100, 'leftUntilDone': 100, 'downloadDir': arguments['download-dir']}
            self.torrents.append(item)
            return {'torrent-added': item}
        return {}


class MediaTests(unittest.TestCase):
    def test_first_episode_ignores_samples_and_sorts_episode_numbers_naturally(self):
        files = [{'name': 'Show/S01E10.mkv'}, {'name': 'Show/sample.mkv'},
                 {'name': 'Show/S01E02.mkv'}, {'name': 'Show/S01E01.mkv'}, {'name': 'cover.jpg'}]
        self.assertEqual(first_episode_index(files), 3)
        self.assertEqual(first_episode_index([{'name': '10.mkv'}, {'name': '2.mkv'}, {'name': '1.mkv'}]), 2)
        self.assertIsNone(first_episode_index([{'name': 'cover.jpg'}]))

    def test_torrent_bytes_are_sent_as_metainfo_without_requesting_a_remote_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRPC()
            controller = MediaController(Path(tmp) / 'state.db', rpc, lambda: Path(tmp))
            raw = b'd4:infod4:name4:teste e'.replace(b' ', b'')
            result = controller.command('file', {'action': 'add', 'metainfo': base64.b64encode(raw).decode(), 'kind': 'show'})
            self.assertTrue(result['ok'])
            self.assertEqual(rpc.torrents[0]['downloadDir'], str(Path(tmp) / 'TV'))
            with self.assertRaises(ValueError):
                controller.command('invalid-file', {'action': 'add', 'metainfo': 'not base64!'})

    def test_disk_absent_refuses_add_and_retry_of_same_job_does_not_add_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRPC()
            present = [False]
            def check_disk():
                if not present[0]:
                    raise DiskUnavailable('disk_missing')
                return Path(tmp)
            controller = MediaController(Path(tmp) / 'state.db', rpc, check_disk)
            payload = {'action': 'add', 'magnet': 'magnet:?xt=urn:btih:' + 'a' * 40, 'kind': 'movie'}
            with self.assertRaises(DiskUnavailable):
                controller.command('job1', payload)
            self.assertEqual(rpc.downloads, 0)
            present[0] = True
            first = controller.command('job1', payload)
            restarted = MediaController(Path(tmp) / 'state.db', rpc, check_disk)
            self.assertEqual(restarted.command('job1', payload), first)
            self.assertEqual(rpc.downloads, 1)

    def test_unmanaged_torrent_cannot_be_deleted_and_arbitrary_urls_cannot_be_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRPC()
            controller = MediaController(Path(tmp) / 'state.db', rpc, lambda: Path(tmp))
            with self.assertRaises(ValueError):
                controller.command('bad-delete', {'action': 'delete', 'hash': 'f' * 40})
            for url in ['file:///etc/passwd', 'http://127.0.0.1/', 'https://example.com/test.torrent']:
                with self.assertRaises(ValueError):
                    controller.command('bad-url-' + url, {'action': 'add', 'magnet': url})
            self.assertEqual(rpc.downloads, 0)

    def test_pause_intent_survives_rpc_failure_and_only_resume_clears_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=FakeRPC();controller=MediaController(Path(tmp)/'state.db',rpc,lambda:Path(tmp))
            h='a'*40
            controller.command('add',{'action':'add','magnet':'magnet:?xt=urn:btih:'+h})
            original=rpc.call
            def deferred_stop(method,arguments=None):
                if method=='torrent-stop':
                    self.assertTrue(controller.store.read_state('managed')[h]['manual_pause'])
                    raise RuntimeError('lost_response')
                return original(method,arguments)
            rpc.call=deferred_stop
            with self.assertRaises(RuntimeError):controller.command('pause',{'action':'pause','hash':h})
            restarted=MediaController(Path(tmp)/'state.db',rpc,lambda:Path(tmp))
            self.assertTrue(restarted.store.read_state('managed')[h]['manual_pause'])
            restarted.command('resume',{'action':'resume','hash':h})
            self.assertFalse(restarted.store.read_state('managed')[h]['manual_pause'])

    def test_multiseason_pack_waits_for_files_before_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRPC()
            controller = MediaController(Path(tmp) / 'state.db', rpc, lambda: Path(tmp))
            result=controller.command('pack', {'action': 'add', 'kind': 'show', 'season': 2,
                'season_pack': True, 'magnet': 'magnet:?xt=urn:btih:' + 'a' * 40})
            self.assertFalse(result['ok'])
            self.assertTrue(result['paused'])
            self.assertTrue(controller.store.read_state('managed')['a'*40]['file_selection_pending'])

    def test_multiseason_metainfo_waits_for_files_before_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRPC()
            controller = MediaController(Path(tmp) / 'state.db', rpc, lambda: Path(tmp))
            result=controller.command('pack', {'action': 'add', 'kind': 'show', 'season': 2,
                'season_pack': True, 'metainfo': base64.b64encode(b'd4:infod4:name4:testee').decode()})
            self.assertFalse(result['ok'])
            self.assertTrue(result['paused'])
            self.assertTrue(controller.store.read_state('managed')['a'*40]['file_selection_pending'])

    def test_legacy_hash_delete_cannot_bypass_inventory_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=FakeRPC(); c=MediaController(Path(tmp)/'db',rpc,lambda:Path(tmp))
            c.store.write_state('managed',{'a'*40:{'destination':str(Path(tmp)/'Movies')}})
            with self.assertRaisesRegex(ValueError,'use_library_selection'):
                c.command('delete',{'action':'delete','hash':'a'*40})

    def test_duplicate_preserves_manual_pause_without_capacity_for_full_size(self):
        from unittest.mock import patch
        from collections import namedtuple
        with tempfile.TemporaryDirectory() as tmp:
            rpc=FakeRPC(); calls=[]; h='a'*40
            rpc.torrents=[{'hashString':h,'name':'Existing','totalSize':5000,'leftUntilDone':0}]
            original=rpc.call
            def call(method,args=None):
                calls.append(method)
                if method=='torrent-add':return {'torrent-duplicate':rpc.torrents[0]}
                return original(method,args)
            rpc.call=call; c=MediaController(Path(tmp)/'db',rpc,lambda:Path(tmp))
            original_state={'destination':str(Path(tmp)/'Movies'),'manual_pause':True,'kind':'movie'}
            c.store.write_state('managed',{h:original_state})
            usage=namedtuple('Usage','total used free')(10000,0,1000)
            with patch('mac_agent.media.shutil.disk_usage',return_value=usage),patch('mac_agent.media.HEADROOM',100):
                result=c.command('dup',{'action':'add','magnet':'magnet:?xt=urn:btih:'+h,'size_bytes':5000})
            self.assertTrue(result['ok']); self.assertTrue(result['paused'])
            self.assertEqual(c.store.read_state('managed')[h],original_state)
            self.assertNotIn('torrent-start',calls)
