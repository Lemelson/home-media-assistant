import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_agent.media import DiskUnavailable
from mac_agent.server import volume_guard


class VolumeGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.volume = Path(self.tmp.name).resolve()
        self.root = self.volume / 'MediaServer'
        for folder in ('Movies', 'TV', 'Downloads/Incomplete'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.info = {'VolumeUUID': 'expected', 'MountPoint': str(self.volume), 'Writable': True}

    def check(self):
        return volume_guard(self.volume, 'expected')()

    @patch('mac_agent.server.os.path.ismount', return_value=True)
    def test_transient_diskutil_timeout_is_revalidated_before_pausing(self, mount):
        with patch('mac_agent.server.subprocess.check_output', side_effect=[
            subprocess.TimeoutExpired('diskutil', 8), plistlib.dumps(self.info),
        ]) as probe:
            self.assertEqual(self.check(), self.root)
            self.assertEqual(probe.call_count, 2)

    @patch('mac_agent.server.os.path.ismount', return_value=True)
    def test_persistent_timeout_remains_unavailable(self, mount):
        with patch('mac_agent.server.subprocess.check_output', side_effect=subprocess.TimeoutExpired('diskutil', 8)):
            with self.assertRaisesRegex(DiskUnavailable, 'disk_probe_timeout'):
                self.check()

    def test_unmount_during_retry_is_not_trusted(self):
        with patch('mac_agent.server.os.path.ismount', side_effect=[True, False]):
            with patch('mac_agent.server.subprocess.check_output', side_effect=subprocess.TimeoutExpired('diskutil', 8)) as probe:
                with self.assertRaisesRegex(DiskUnavailable, 'disk_missing'):
                    self.check()
                self.assertEqual(probe.call_count, 1)

    @patch('mac_agent.server.os.path.ismount', return_value=True)
    def test_wrong_volume_or_readonly_is_never_retried(self, mount):
        for overrides in ({'VolumeUUID': 'wrong'}, {'MountPoint': '/elsewhere'}, {'Writable': False}):
            with self.subTest(overrides=overrides):
                with patch('mac_agent.server.subprocess.check_output', return_value=plistlib.dumps(self.info | overrides)) as probe:
                    with self.assertRaisesRegex(DiskUnavailable, 'wrong_or_readonly_disk'):
                        self.check()
                    self.assertEqual(probe.call_count, 1)

    @patch('mac_agent.server.os.path.ismount', return_value=True)
    def test_symlink_destination_is_rejected(self, mount):
        (self.root / 'Movies').rmdir()
        (self.root / 'Movies').symlink_to(self.root / 'TV', target_is_directory=True)
        with patch('mac_agent.server.subprocess.check_output', return_value=plistlib.dumps(self.info)):
            with self.assertRaisesRegex(DiskUnavailable, 'media_folder_changed'):
                self.check()
