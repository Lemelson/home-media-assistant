import tempfile
import unittest
from pathlib import Path
from mac_agent.media import MediaController
from test_transfer_controls import RPC

class PriorityLockTests(unittest.TestCase):
    def test_busy_priority_request_returns_without_waiting_for_download(self):
        class Lock:
            def acquire(self,timeout=None):
                self.timeout=timeout
                return False
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=MediaController(root/'db',RPC(root),lambda:root);c.lock=Lock()
            with self.assertRaisesRegex(RuntimeError,'media_busy'):
                c.command('test',dict(action='bandwidth_priority',hash='a'*40,cycle=True))
            self.assertEqual(c.lock.timeout,2)

    def test_command_confirms_only_target_without_demoting_previous_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rpc=RPC(root);c=MediaController(root/'db',rpc,lambda:root)
            c.store.write_state('managed',{'a'*40:{},'b'*40:{}})
            c.command('one',dict(action='bandwidth_priority',hash='a'*40,priority=1))
            result=c.command('two',dict(action='bandwidth_priority',hash='b'*40,priority=1))
            self.assertEqual(result['priorities'],{'b'*40:1})
            self.assertEqual(rpc.rows[0]['bandwidthPriority'],1)
