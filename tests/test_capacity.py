import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collections import namedtuple
from tests.test_media import FakeRPC
from mac_agent.media import MediaController

class CapacityTests(unittest.TestCase):
    def test_space_accounts_for_existing_queue_and_does_not_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=FakeRPC(); rpc.torrents=[{'hashString':'b'*40,'leftUntilDone':500,'downloadDir':str(Path(tmp)/'Movies')}]
            c=MediaController(Path(tmp)/'db',rpc,lambda:Path(tmp))
            usage=namedtuple('Usage','total used free')(10000,0,1000)
            with patch('mac_agent.media.shutil.disk_usage',return_value=usage), patch('mac_agent.media.HEADROOM',100):
                result=c.command('add',{'action':'add','magnet':'magnet:?xt=urn:btih:'+'a'*40,'size_bytes':600})
            self.assertEqual(result['error'],'insufficient_space'); self.assertEqual(result['reserved_bytes'],500)
            self.assertEqual(rpc.downloads,0)

    def test_unknown_metadata_stays_paused(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc=FakeRPC(); calls=[]; original=rpc.call
            def call(method,args=None):
                calls.append(method)
                result=original(method,args)
                for t in rpc.torrents:
                    t.pop('totalSize',None); t.pop('leftUntilDone',None)
                return result
            rpc.call=call; c=MediaController(Path(tmp)/'db',rpc,lambda:Path(tmp))
            result=c.command('add',{'action':'add','magnet':'magnet:?xt=urn:btih:'+'a'*40})
            self.assertEqual(result['error'],'size_unknown'); self.assertNotIn('torrent-start',calls)

    def test_disk_guard_pauses_when_metadata_reveals_larger_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rpc=FakeRPC(); calls=[]
            rpc.torrents=[{'hashString':'a'*40,'downloadDir':str(root/'Movies'),'leftUntilDone':900,'totalSize':900}]
            original=rpc.call
            def call(method,args=None):calls.append((method,args)); return original(method,args)
            rpc.call=call; c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'a'*40:{'destination':str(root/'Movies')}})
            usage=namedtuple('Usage','total used free')(10000,0,950)
            with patch('mac_agent.media.shutil.disk_usage',return_value=usage), patch('mac_agent.media.HEADROOM',100):c.guard_disk()
            self.assertIn(('torrent-stop',{'ids':['a'*40]}),calls)
            self.assertTrue(c.store.read_state('managed')['a'*40]['manual_pause'])

    def test_pending_metadata_keeps_supplied_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rpc=FakeRPC(); rpc.torrents=[{'hashString':'b'*40,'leftUntilDone':0,'totalSize':0,'downloadDir':str(root/'Movies')}]
            c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'b'*40:{'reserved_bytes':800}})
            usage=namedtuple('Usage','total used free')(10000,0,1000)
            with patch('mac_agent.media.shutil.disk_usage',return_value=usage), patch('mac_agent.media.HEADROOM',100):
                result=c.command('add',{'action':'add','magnet':'magnet:?xt=urn:btih:'+'a'*40,'size_bytes':300})
            self.assertEqual(result['error'],'insufficient_space'); self.assertEqual(rpc.downloads,0)

    def test_post_add_insufficient_space_status_keeps_correct_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rpc=FakeRPC(); c=MediaController(root/'db',rpc,lambda:root)
            usage=namedtuple('Usage','total used free')(10000,0,150)
            with patch('mac_agent.media.shutil.disk_usage',return_value=usage), patch('mac_agent.media.HEADROOM',100):
                result=c.command('add',{'action':'add','magnet':'magnet:?xt=urn:btih:'+'a'*40})
            self.assertEqual(result['error'],'insufficient_space')
            self.assertEqual(c.status()['torrents'][0]['capacity_error'],'insufficient_space')

    def test_low_space_guard_does_not_block_completed_transfer_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rpc=FakeRPC(); calls=[]
            rpc.torrents=[{'hashString':'a'*40,'downloadDir':str(root/'Movies'),'leftUntilDone':0,'totalSize':900,'percentDone':1,'status':6},
                          {'hashString':'b'*40,'downloadDir':str(root/'Movies'),'leftUntilDone':900,'totalSize':900,'percentDone':0,'status':4}]
            original=rpc.call
            def call(method,args=None):calls.append((method,args)); return original(method,args)
            rpc.call=call; c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'a'*40:{'destination':str(root/'Movies'),'capacity_pending':True,'capacity_error':'insufficient_space'},
                                          'b'*40:{'destination':str(root/'Movies')}})
            usage=namedtuple('Usage','total used free')(10000,0,50)
            with patch('mac_agent.media.shutil.disk_usage',return_value=usage), patch('mac_agent.media.HEADROOM',100):c.guard_disk()
            stops=[args['ids'] for method,args in calls if method=='torrent-stop']
            self.assertEqual(stops,[['b'*40]])
            completed=c.status()['torrents'][0]
            self.assertNotIn('capacity_error',completed)
