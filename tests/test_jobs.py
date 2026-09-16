import tempfile
import unittest
import sqlite3
from pathlib import Path

from bot.jobs import JobStore


class JobTests(unittest.TestCase):
    def test_notification_migration_does_not_replay_old_completed_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            store = JobStore(path)
            old = store.enqueue('old', 42, {'action': 'pause'})
            store.finish(old, {'ok': True})
            with sqlite3.connect(path) as db:
                db.execute('DROP TABLE job_notifications')
            upgraded = JobStore(path)
            self.assertEqual(upgraded.unnotified(), [])
            new = upgraded.enqueue('new', 42, {'action': 'resume'})
            upgraded.finish(new, {'ok': True})
            self.assertEqual([job['id'] for job in upgraded.unnotified()], [new])

    def test_library_delete_payload_is_bound_to_user_and_cancel_revokes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / 'jobs.db')
            payload = {'action': 'delete_library', 'inventory_id': 'opaque-item'}
            token = store.offer_action(42, payload, now=100)
            self.assertIsNone(store.confirm_delete(99, token, now=101))
            job = store.confirm_delete(42, token, now=102)
            self.assertEqual(store.get(job)['payload'], payload)
            cancelled = store.offer_action(42, payload, now=100)
            store.cancel_confirmation(42, cancelled)
            self.assertIsNone(store.confirm_delete(42, cancelled, now=101))
            with self.assertRaises(ValueError):
                store.offer_action(42, {'action': 'shell', 'command': 'rm -rf /'})

    def test_offline_job_survives_restart_and_duplicate_update_is_one_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            store = JobStore(path)
            job = store.enqueue('tg:100:download', 42, {'action': 'add', 'magnet': 'magnet:?xt=urn:btih:' + 'a' * 40})
            self.assertEqual(store.enqueue('tg:100:download', 42, {'action': 'add'}), job)
            store = JobStore(path)
            self.assertEqual(len(store.pending()), 1)
            self.assertEqual(store.pending()[0]['payload']['action'], 'add')
            store.finish(job, {'ok': True, 'hash': 'a' * 40})
            self.assertEqual(JobStore(path).pending(), [])
            self.assertEqual(store.get(job)['result']['hash'], 'a' * 40)

    def test_delete_requires_same_user_fresh_confirmation_and_cannot_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / 'jobs.db')
            token = store.offer_delete(42, 'a' * 40, now=100)
            self.assertIsNone(store.confirm_delete(99, token, now=101))
            job = store.confirm_delete(42, token, now=102)
            self.assertEqual(store.get(job)['payload'], {'action': 'delete', 'hash': 'a' * 40})
            self.assertIsNone(store.confirm_delete(42, token, now=103))
            expired = store.offer_delete(42, 'b' * 40, now=100)
            self.assertIsNone(store.confirm_delete(42, expired, now=1000))
