import importlib.machinery
import json
import tempfile
import unittest
from pathlib import Path

deploy = importlib.machinery.SourceFileLoader('home_deploy', str(Path(__file__).parents[1] / 'deploy/home-media-deploy')).load_module()


class DeploymentTests(unittest.TestCase):
    def test_old_process_heartbeat_cannot_mark_new_release_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat = Path(tmp) / 'heartbeat'
            heartbeat.write_text(json.dumps({'revision': 'old', 'time': 200}))
            self.assertFalse(deploy.healthy_release('new', heartbeat, started=100))
            heartbeat.write_text(json.dumps({'revision': 'new', 'time': 99}))
            self.assertFalse(deploy.healthy_release('new', heartbeat, started=100))
            heartbeat.write_text(json.dumps({'revision': 'new', 'time': 101}))
            self.assertTrue(deploy.healthy_release('new', heartbeat, started=100))
            heartbeat.write_text('{')
            self.assertFalse(deploy.healthy_release('new', heartbeat, started=100))
