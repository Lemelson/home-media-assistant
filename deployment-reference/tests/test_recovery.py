import tempfile
import unittest
from pathlib import Path
from bot.jobs import JobStore
from mac_agent.recovery import RecoveryController

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=JobStore(Path(self.tmp.name)/'state.db');self.now=10000;self.calls=[];self.online=True;self.fresh=None
        self.t=dict(hashString='a'*40,status=4,percentDone=.96,leftUntilDone=10000000,downloadedEver=100000,
                    rateDownload=1000,peersConnected=3,desiredAvailable=10000000,downloadDir='/media/Movies',errorString='')
        self.managed={self.t['hashString']:dict(destination='/media/Movies')};self.torrents=[self.t]
        self.c=RecoveryController(self.store,self,lambda:self.now,network_ok=lambda:self.online)
    def call(self,method,args):
        if method=='torrent-get':return {'torrents':self.fresh if self.fresh is not None else [dict(t) for t in self.torrents]}
        self.calls.append((method,args));return {}
    def advance(self,seconds,rate=1000):
        for _ in range(seconds//10):
            self.now+=10
            for t in self.torrents:
                t['rateDownload']=rate;t['downloadedEver']+=rate*10;t['leftUntilDone']-=rate*10
            self.c.tick(self.torrents,self.managed)
    def warm(self):
        self.c.tick(self.torrents,self.managed);self.advance(310)
    def verifies(self):return [c for c in self.calls if c[0]=='torrent-verify']
    def test_zero_three_minutes_after_warmup(self):
        self.warm();self.advance(170,0);self.assertFalse(self.verifies())
        self.advance(20,0);self.assertEqual(len(self.verifies()),1)
    def test_sustained_fivefold_slowdown_and_frozen_baseline(self):
        self.warm();self.advance(290,100);self.assertFalse(self.verifies())
        self.advance(20,100);self.assertEqual(len(self.verifies()),1)
    def test_new_or_early_download_never_checks(self):
        self.advance(600,0);self.assertFalse(self.verifies())
        self.t['percentDone']=.5;self.warm();self.advance(600,0);self.assertFalse(self.verifies())
    def test_brief_drop_and_recovery_cancel(self):
        self.warm();self.advance(120,0);self.advance(60);self.advance(120,0);self.assertFalse(self.verifies())
    def test_pause_and_errors_excluded(self):
        self.warm()
        for patch in ({'status':0},{'status':3},{'errorString':'disk error'},{'percentDone':1}):
            old=dict(self.t);self.t.update(patch);self.advance(600,0);self.assertFalse(self.verifies());self.t.update(old)
    def test_manual_pause_excluded(self):
        self.warm();self.managed[self.t['hashString']]['manual_pause']=True
        self.advance(600,0);self.assertFalse(self.verifies())
    def test_offline_then_reannounce_and_grace(self):
        self.warm();self.online=False;self.advance(190,0);self.assertFalse(self.verifies())
        self.online=True;self.advance(40,0);self.assertTrue(any(m=='torrent-reannounce' for m,_ in self.calls))
        self.advance(80,0);self.assertFalse(self.verifies())
    def test_missing_pieces_wait_instead_of_verify(self):
        self.warm();self.t['desiredAvailable']=0;self.advance(600,0);self.assertFalse(self.verifies())
    def test_one_check_for_many_torrents_and_existing_check_blocks(self):
        other={**self.t,'hashString':'b'*40};self.torrents.append(other);self.managed[other['hashString']]=dict(destination='/media/Movies')
        self.warm();self.advance(190,0);self.assertEqual(len(self.verifies()),1)
        self.t['status']=2;self.advance(200,0);self.assertEqual(len(self.verifies()),1)
    def test_fresh_pause_or_recovery_cancels_dispatch(self):
        self.warm();self.fresh=[{**self.t,'status':0}];self.advance(190,0);self.assertFalse(self.verifies())
    def test_restart_preserves_attempt_cap(self):
        self.store.write_state('recovery:'+self.t['hashString'],{'attempts':2,'next_attempt':0})
        self.warm();self.advance(600,0);self.assertFalse(self.verifies())
    def test_observation_gap_excludes_unseen_downtime(self):
        self.warm();self.now+=10000;self.t['rateDownload']=0;self.c.tick(self.torrents,self.managed)
        self.advance(300,0);self.assertFalse(self.verifies())
    def test_ambiguous_rpc_failure_consumes_attempt_and_does_not_repeat(self):
        self.warm();original=self.call
        def fail(method,args):
            if method=='torrent-verify':raise OSError('lost response')
            return original(method,args)
        self.call=fail
        with self.assertRaises(OSError):self.advance(190,0)
        self.assertEqual(self.store.read_state('recovery:'+self.t['hashString'])['attempts'],1)
        self.call=original;self.warm();self.advance(190,0);self.assertFalse(self.verifies())
    def test_fresh_bytes_cancel_even_when_speed_is_low(self):
        self.warm();self.fresh=[{**self.t,'rateDownload':0,'downloadedEver':self.t['downloadedEver']+1}]
        self.advance(190,0);self.assertFalse(self.verifies())
    def test_unmanaged_manual_verification_blocks_queue(self):
        self.warm();self.fresh=[dict(self.t),{'hashString':'c'*40,'status':2}]
        self.advance(190,0);self.assertFalse(self.verifies())
    def test_backoff_survives_restart(self):
        self.warm();self.advance(190,0);self.assertEqual(len(self.verifies()),1)
        self.c=RecoveryController(self.store,self,lambda:self.now,network_ok=lambda:True)
        self.warm();self.advance(190,0);self.assertEqual(len(self.verifies()),1)
    def test_existing_download_can_recover_after_agent_restart(self):
        self.t.update(secondsDownloading=3600,rateDownload=0)
        self.c.tick(self.torrents,self.managed);self.advance(190,0)
        self.assertEqual(len(self.verifies()),1)
