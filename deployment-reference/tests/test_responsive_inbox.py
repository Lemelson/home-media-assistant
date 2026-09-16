import tempfile
import threading
import unittest
from bot.inbox import Inbox
from tests.test_inbox import update

class ResponsiveInboxTests(unittest.TestCase):
    def test_slow_receipt_does_not_block_ingestion_or_other_lanes(self):
        started=threading.Event();release=threading.Event();handled=threading.Event();accepted=threading.Event();seen=[]
        def receipt(row):
            if row['update_id']==1: started.set();release.wait(3)
            return 100+row['update_id']
        def handle(row):
            seen.append(row['update_id'])
            if row['update_id']==2: handled.set()
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,handle,on_receipt=receipt,async_receipts=True)
            try:
                def enqueue():
                    inbox.enqueue(update(1));inbox.enqueue(update(2,callback='downloads'));accepted.set()
                worker=threading.Thread(target=enqueue);worker.start()
                self.assertTrue(started.wait(1))
                self.assertTrue(accepted.wait(.3),'receipt network I/O blocked intake')
                self.assertTrue(handled.wait(.5),'slow receipt blocked fast control')
                self.assertNotIn(1,seen)
                release.set();worker.join(1);self.assertTrue(inbox.wait_idle(2))
            finally: release.set();inbox.stop()

    def test_receipt_completion_cannot_reorder_same_dialog(self):
        first=threading.Event();second=threading.Event();release=threading.Event();seen=[]
        def receipt(row):
            if row['update_id']==1:first.set();release.wait(2)
            else:second.set()
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,lambda row:seen.append(row['update_id']),on_receipt=receipt,async_receipts=True)
            try:
                inbox.enqueue(update(1));self.assertTrue(first.wait(1))
                inbox.enqueue(update(2));self.assertTrue(second.wait(1));inbox.pump()
                self.assertEqual(seen,[])
                release.set();self.assertTrue(inbox.wait_idle(2));self.assertEqual(seen,[1,2])
            finally:release.set();inbox.stop()

    def test_fast_text_bypasses_two_blocked_receipts(self):
        release=threading.Event();entered=[threading.Event(),threading.Event()];handled=threading.Event()
        def receipt(row):
            if row['update_id']<3:entered[row['update_id']-1].set();release.wait(2)
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,lambda row:handled.set() if row['update_id']==3 else None,on_receipt=receipt,async_receipts=True)
            try:
                inbox.enqueue(update(1));inbox.enqueue(update(2,uid=20))
                self.assertTrue(all(e.wait(1) for e in entered))
                inbox.enqueue(update(3,text='/downloads'))
                self.assertTrue(handled.wait(.3))
            finally:release.set();inbox.wait_idle(2);inbox.stop()

    def test_controls_keep_worker_when_slow_lanes_are_full(self):
        release=threading.Event();entered=[threading.Event() for _ in range(3)];fast=threading.Event()
        def handle(row):
            if row['update_id']<4:
                entered[row['update_id']-1].set();release.wait(2)
            elif row['update_id']==5:fast.set()
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,handle,reserve_controls=True)
            try:
                for i in range(1,5):inbox.enqueue(update(i,uid=i))
                inbox.pump();self.assertTrue(all(e.wait(1) for e in entered))
                inbox.enqueue(update(5,callback='downloads'));inbox.pump()
                self.assertTrue(fast.wait(.3))
            finally:release.set();inbox.wait_idle(2);inbox.stop()
