import tempfile
import unittest
from pathlib import Path
from mac_agent.library import MediaLibrary

class LibraryTests(unittest.TestCase):
    def test_hidden_sidecars_and_hidden_directories_are_not_movies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Movies').mkdir(); (root / 'TV').mkdir()
            (root / 'Movies' / 'Film.mkv').write_bytes(b'video')
            (root / 'Movies' / '._Film.mkv').write_bytes(b'x' * 4096)
            (root / 'Movies' / '.hidden.mp4').write_bytes(b'not public')
            (root / 'Movies' / '.cache').mkdir()
            (root / 'Movies' / '.cache' / 'Cached.mkv').write_bytes(b'cache')
            (root / 'TV' / '.staging').mkdir()
            (root / 'TV' / '.staging' / 'Show.S01E01.mkv').write_bytes(b'partial')
            items = MediaLibrary(lambda: root).inventory()['items']
            self.assertEqual([item['name'] for item in items], ['Film.mkv'])
            self.assertEqual(items[0]['size_bytes'], 5)

    def test_inventory_and_scoped_episode_and_season_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'Movies').mkdir(); (root/'TV'/'Example').mkdir(parents=True)
            (root/'Movies'/'Film.mkv').write_bytes(b'x'*20)
            a=root/'TV'/'Example'/'Example.S02E01.mkv'; a.write_bytes(b'x'*10)
            b=root/'TV'/'Example'/'Example.S02E02.mkv'; b.write_bytes(b'x'*11)
            sentinel=root/'outside.mkv'; sentinel.write_bytes(b'safe')
            (root/'Movies'/'escape.mkv').symlink_to(sentinel)
            lib=MediaLibrary(lambda:root)
            items=lib.inventory()['items']
            self.assertEqual([i['size_bytes'] for i in items], sorted([i['size_bytes'] for i in items],reverse=True))
            self.assertFalse(any(i['name']=='escape.mkv' for i in items))
            episode=next(i for i in items if i.get('episode')==1)
            self.assertNotIn('path',episode)
            lib.delete(episode['id']); self.assertFalse(a.exists()); self.assertTrue(b.exists())
            season=next(i for i in lib.inventory()['items'] if i['kind']=='season')
            lib.delete(season['id']); self.assertFalse(b.exists()); self.assertEqual(sentinel.read_bytes(),b'safe')

    def test_stale_wrong_root_symlink_and_root_ids_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            f=root/'Movies'/'Film.mkv'; f.write_bytes(b'old'); sentinel=root/'outside'; sentinel.write_bytes(b'safe')
            current=[root]; lib=MediaLibrary(lambda:current[0]); item=lib.inventory()['items'][0]
            f.unlink(); f.symlink_to(sentinel)
            with self.assertRaises(ValueError):lib.delete(item['id'])
            self.assertEqual(sentinel.read_bytes(),b'safe')
            for value in ('..','Movies',str(root),'/'):
                with self.assertRaises(ValueError):lib.delete(value)
            f.unlink(); f.write_bytes(b'new'); item=lib.inventory()['items'][0]
            current[0]=root/'Movies'
            with self.assertRaises(ValueError):lib.delete(item['id'])

    def test_directory_symlink_never_inventoried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir(); (root/'outside').mkdir()
            (root/'outside'/'secret.mkv').write_bytes(b'safe')
            (root/'TV'/'escape').symlink_to(root/'outside',target_is_directory=True)
            self.assertEqual(MediaLibrary(lambda:root).inventory()['items'],[])

    def test_changed_file_invalidates_whole_season_before_deleting_any_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            a=root/'TV'/'Show.S01E01.mkv'; a.write_bytes(b'a')
            b=root/'TV'/'Show.S01E02.mkv'; b.write_bytes(b'b')
            lib=MediaLibrary(lambda:root); item=next(i for i in lib.inventory()['items'] if i['kind']=='season')
            b.write_bytes(b'changed')
            with self.assertRaises(ValueError):lib.delete(item['id'])
            self.assertEqual(a.read_bytes(),b'a'); self.assertEqual(b.read_bytes(),b'changed')

    def test_deleting_episode_removes_transfer_without_removing_other_episodes(self):
        from mac_agent.media import MediaController
        from tests.test_media import FakeRPC
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            a=root/'TV'/'Show.S01E01.mkv'; a.write_bytes(b'a')
            b=root/'TV'/'Show.S01E02.mkv'; b.write_bytes(b'b')
            rpc=FakeRPC(); rpc.torrents=[{'hashString':'a'*40,'downloadDir':str(root/'TV'),'files':[{'name':a.name},{'name':b.name}]}]
            calls=[]; original=rpc.call
            def call(method,args=None):calls.append((method,args)); return original(method,args)
            rpc.call=call
            c=MediaController(root/'db',rpc,lambda:root); c.store.write_state('managed',{'a'*40:{'kind':'show'}})
            item=next(i for i in c.library()['items'] if i.get('episode')==1)
            result=c.command('delete',{'action':'delete_library','inventory_id':item['id']})
            self.assertEqual(result['deleted_files'],1); self.assertFalse(a.exists()); self.assertTrue(b.exists())
            self.assertIn(('torrent-remove',{'ids':['a'*40],'delete-local-data':False}),calls)
            with self.assertRaisesRegex(ValueError,'unmanaged_torrent'):c.command('resume',{'action':'resume','hash':'a'*40})

    def test_refresh_does_not_invalidate_existing_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            f=root/'Movies'/'Movie.mkv'; f.write_bytes(b'x')
            lib=MediaLibrary(lambda:root); first=lib.inventory()['items'][0]
            lib.inventory()
            self.assertEqual(lib.delete(first['id'])['deleted_files'],1)

    def test_parent_moved_out_of_media_scope_during_preflight_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            (root/'Movies'/'Movie.mkv').write_bytes(b'safe')
            lib=MediaLibrary(lambda:root); item=lib.inventory()['items'][0]
            def move_parent():
                (root/'Movies').rename(root/'elsewhere'); (root/'Movies').mkdir()
            with self.assertRaises(ValueError):lib.delete(item['id'],before_delete=move_parent)
            self.assertEqual((root/'elsewhere'/'Movie.mkv').read_bytes(),b'safe')

    def test_unknown_show_is_not_invented_from_tv_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            (root/'TV'/'S01E01.mkv').write_bytes(b'x')
            items=MediaLibrary(lambda:root).inventory()['items']
            self.assertEqual(len(items),1); self.assertEqual(items[0]['episode'],1)
            self.assertNotIn('show',items[0])

    def test_partial_transmission_files_excluded_before_season_grouping(self):
        from mac_agent.media import MediaController
        from tests.test_media import FakeRPC
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            for name in ('Show.S01E01.mkv','Show.S01E02.mkv'):(root/'TV'/name).write_bytes(b'x'*10)
            rpc=FakeRPC(); rpc.torrents=[{'hashString':'a'*40,'downloadDir':str(root/'TV'),'files':[
                {'name':'Show.S01E01.mkv','length':10,'bytesCompleted':10},
                {'name':'Show.S01E02.mkv','length':10,'bytesCompleted':5}]}]
            c=MediaController(root/'db',rpc,lambda:root)
            items=c.library()['items']
            self.assertFalse(any(i.get('episode')==2 for i in items))
            self.assertEqual(next(i for i in items if i['kind']=='season')['size_bytes'],10)

    def test_concurrent_lists_keep_existing_confirmation(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Movies').mkdir(); (root/'TV').mkdir()
            (root/'Movies'/'Movie.mkv').write_bytes(b'x')
            lib=MediaLibrary(lambda:root); item=lib.inventory()['items'][0]
            with ThreadPoolExecutor(max_workers=4) as pool:
                lists=list(pool.map(lambda _:lib.inventory(),range(8)))
            self.assertTrue(all(result['items'][0]['id']==item['id'] for result in lists))
            self.assertEqual(lib.delete(item['id'])['deleted_files'],1)


@unittest.skipUnless(__import__('sys').platform == 'darwin', 'Older Darwin Python compatibility')
class LibraryWithoutPythonDirFDTests(LibraryTests):
    """Exercise every scope/race test with the older Air Python API limitations."""
    def setUp(self):
        import os
        from unittest.mock import patch
        from types import SimpleNamespace
        limited_os = SimpleNamespace(**vars(os))
        for name in ('open', 'stat', 'unlink'):
            native = getattr(os, name)
            def unsupported_dir_fd(*args, _native=native, **kwargs):
                if kwargs.get('dir_fd') is not None:
                    raise NotImplementedError('dir_fd unavailable on this Python build')
                return _native(*args, **kwargs)
            setattr(limited_os, name, unsupported_dir_fd)
        native_scandir = os.scandir
        def unsupported_fd_scan(path):
            if isinstance(path, int):
                raise TypeError('scandir requires a path on this Python build')
            return native_scandir(path)
        limited_os.scandir = unsupported_fd_scan
        patched = patch('mac_agent.library.os', limited_os)
        patched.start()
        self.addCleanup(patched.stop)


class DarwinDirectoryABITests(unittest.TestCase):
    def test_intel_inode64_reader_uses_matching_inode64_directory_opener(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from mac_agent import library
        legacy_open = lambda fd: None
        modern_open = lambda fd: None
        modern_read = lambda stream: None
        fake = SimpleNamespace(fdopendir=legacy_open, closedir=lambda stream: None,
                               **{'fdopendir$INODE64': modern_open, 'readdir$INODE64': modern_read})
        library._darwin_directory_api.cache_clear()
        try:
            with patch.object(library, '_posix_at', return_value=fake), patch.object(library.sys, 'platform', 'darwin'), patch.object(library.platform, 'machine', return_value='x86_64'):
                api = library._darwin_directory_api()
                self.assertIs(api[1], modern_open)
                self.assertIs(api[2], modern_read)
        finally:
            library._darwin_directory_api.cache_clear()
