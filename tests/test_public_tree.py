import tempfile
import unittest
from pathlib import Path
from scripts.check_public_tree import audit

class PublicTreeTests(unittest.TestCase):
    def test_rejects_secret_file_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'PUBLIC_FILES.txt').write_text('README.md\n')
            (root/'README.md').write_text('Safe text')
            (root/'.env').write_text('PRIVATE_VALUE=do-not-print')
            issues=audit(root)
            self.assertTrue(issues)
            self.assertNotIn('do-not-print',str(issues))
    def test_rejects_symlink_and_missing_manifest_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'PUBLIC_FILES.txt').write_text('README.md\n')
            (root/'README.md').symlink_to('/etc/hosts')
            self.assertTrue(audit(root))
    def test_clean_small_tree_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'PUBLIC_FILES.txt').write_text('README.md\n')
            (root/'README.md').write_text('Safe synthetic example')
            self.assertEqual(audit(root),[])

    def test_manifest_cannot_allow_a_runtime_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'PUBLIC_FILES.txt').write_text('.env\n')
            (root/'.env').write_text('PASSWORD=not-a-real-secret')
            self.assertTrue(audit(root))

    def test_device_identifier_and_real_network_address_are_rejected(self):
        for content in ('Device: MacBook'+'Air99,99', 'Server: '+'.'.join(('100','80','70','60'))):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/'PUBLIC_FILES.txt').write_text('README.md\n')
                (root/'README.md').write_text(content)
                self.assertTrue(audit(root))

    def test_deleted_secret_in_git_history_still_blocks_publication(self):
        import subprocess
        from scripts.check_public_tree import audit_history
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def git(*args):
                return subprocess.check_output(['git','-C',d,'-c','user.name=Home Media Assistant contributors',
                    '-c','user.email=test@users.noreply.github.com','-c','commit.gpgsign=false',*args],stderr=subprocess.DEVNULL)
            git('init','-b','main')
            (root/'PUBLIC_FILES.txt').write_text('README.md\n')
            (root/'README.md').write_text('12345678:'+('a'*35))
            git('add','.');git('commit','-m','Initial fixture')
            (root/'README.md').write_text('Clean current version')
            git('add','.');git('commit','-m','Remove fixture')
            self.assertEqual(audit(root),[])
            issues=audit_history(root)
            self.assertTrue(issues)
            self.assertNotIn('a'*35,str(issues))

    def test_public_probe_exception_is_limited_to_its_reviewed_module(self):
        from scripts.check_public_tree import content_findings
        address='.'.join(('8','8','8','8'))
        self.assertEqual(content_findings(address,'mac_agent/recovery.py'),[])
        self.assertTrue(content_findings(address,'README.md'))
        self.assertTrue(content_findings('.'.join(('100','80','70','60')),'mac_agent/recovery.py'))
