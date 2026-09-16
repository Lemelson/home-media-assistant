import tempfile
import threading
import unittest
from types import SimpleNamespace

from bot.access import AccessRegistry
from bot.inbox import Inbox
from bot.__main__ import acknowledge_message


def update(i, text='Мемуары гейши', uid=10, chat_type='private'):
    return {'update_id': i, 'message': {'message_id': i, 'from': {'id': uid, 'username': 'owner' if uid == 10 else 'stranger'}, 'chat': {'id': uid, 'type': chat_type}, 'text': text}}


class Telegram:
    def __init__(self): self.calls = []
    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {'message_id': 100 + len(self.calls)}


class ImmediateAcknowledgementTests(unittest.TestCase):
    def test_second_receipt_is_visible_while_first_search_is_blocked_and_survives_replay(self):
        entered = threading.Event(); release = threading.Event(); handled = []; receipts = []
        def handle(row):
            handled.append(row)
            if row['update_id'] == 1:
                entered.set(); release.wait(2)
        def receipt(row):
            receipts.append(row['update_id']); return row['update_id'] + 100
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(tmp, handle, on_receipt=receipt)
            try:
                inbox.enqueue(update(1)); inbox.pump(); self.assertTrue(entered.wait(1))
                inbox.enqueue(update(2)); inbox.enqueue(update(2))
                self.assertEqual(receipts, [1, 2])
                self.assertEqual(len(handled), 1)
                release.set(); self.assertTrue(inbox.wait_idle(2))
                self.assertEqual(handled[1]['message']['_receipt_message_id'], 102)
            finally: release.set(); inbox.stop()
            recovered = Inbox(tmp, handled.append, on_receipt=receipt)
            try:
                recovered.enqueue(update(2)); self.assertEqual(receipts, [1, 2])
            finally: recovered.stop()

    def test_receipt_network_call_does_not_hold_scheduler_or_start_its_handler(self):
        sending = threading.Event(); release = threading.Event(); handled = []
        def receipt(row):
            if row['update_id'] == 2:
                sending.set(); release.wait(2)
            return 100 + row['update_id']
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(tmp, handled.append, on_receipt=receipt)
            sender = threading.Thread(target=lambda: inbox.enqueue(update(2)))
            try:
                inbox.enqueue(update(1)); sender.start(); self.assertTrue(sending.wait(1))
                self.assertEqual(inbox.pump(), 1)
                self.assertFalse(any(row["update_id"] == 2 for row in handled))
                release.set(); sender.join(1)
                inbox.pump(); self.assertTrue(inbox.wait_idle(1))
                self.assertEqual([row['update_id'] for row in handled], [1, 2])
            finally: release.set(); sender.join(1); inbox.stop()

    def test_receipt_reuses_message_after_pending_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(tmp, lambda row: None, on_receipt=lambda row: 101)
            inbox.enqueue(update(1)); inbox.stop()
            rows = []; receipts = []
            recovered = Inbox(tmp, rows.append, on_receipt=receipts.append)
            try:
                recovered.pump(); self.assertTrue(recovered.wait_idle(1))
                self.assertEqual(rows[0]['message']['_receipt_message_id'], 101)
                self.assertEqual(receipts, [])
            finally: recovered.stop()

    def test_receipt_failure_does_not_lose_or_block_request(self):
        def fail(row): raise TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            rows = []; inbox = Inbox(tmp, rows.append, on_receipt=fail)
            try:
                self.assertTrue(inbox.enqueue(update(1))); inbox.pump()
                self.assertTrue(inbox.wait_idle(1)); self.assertEqual(len(rows), 1)
            finally: inbox.stop()

    def test_private_authorization_escaping_and_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            dialog = SimpleNamespace(access=AccessRegistry(tmp+'/access.db', 'owner', ''), telegram=Telegram())
            for row in (update(1, uid=20), update(2, chat_type='group'), update(3, '/start'), update(4, '🎬 Мои фильмы')):
                self.assertIsNone(acknowledge_message(dialog, row))
            self.assertEqual(dialog.telegram.calls, [])
            result = acknowledge_message(dialog, update(5, '<b>Фильм & кино</b>' + 'я'*1000))
            self.assertEqual(result, 101)
            payload = dialog.telegram.calls[0][1]
            self.assertIn('&lt;b&gt;Фильм &amp; кино&lt;/b&gt;', payload['text'])
            self.assertLess(len(payload['text']), 300)
            self.assertEqual(payload['reply_parameters'], {'message_id': 5, 'allow_sending_without_reply': True})
