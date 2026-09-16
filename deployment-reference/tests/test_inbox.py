import tempfile
import threading
import unittest
from bot.inbox import Inbox


def update(i,uid=10,text='film',callback=None):
    message={'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':text}
    if callback:return {'update_id':i,'callback_query':{'id':str(i),'from':{'id':uid},'message':message,'data':callback},'_callback_answered':True}
    return {'update_id':i,'message':message}


class InboxTests(unittest.TestCase):
    def test_blocked_search_does_not_block_other_user_or_own_status_but_own_text_waits(self):
        entered=threading.Event();release=threading.Event();other=threading.Event();status=threading.Event();second=threading.Event()
        def handle(row):
            i=row['update_id']
            if i==1:
                entered.set();self.assertTrue(release.wait(2))
            elif i==2:second.set()
            elif i==3:other.set()
            elif i==4:status.set()
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,handle)
            for row in (update(1),update(2),update(3,20),update(4,callback='downloads')):self.assertTrue(inbox.enqueue(row))
            inbox.pump()
            self.assertTrue(entered.wait(1));self.assertTrue(other.wait(1));self.assertTrue(status.wait(1));self.assertFalse(second.is_set())
            release.set()
            self.assertTrue(inbox.wait_idle(2))
            self.assertTrue(second.is_set());inbox.stop()

    def test_restart_recovers_pending_and_duplicate_id_is_not_replayed(self):
        done=threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            first=Inbox(tmp,lambda row:None);first.enqueue(update(1));first.stop()
            second=Inbox(tmp,lambda row:done.set());self.assertTrue(second.enqueue(update(1)))
            self.assertEqual(second.pending_count(),1);second.pump();self.assertTrue(done.wait(1));self.assertTrue(second.wait_idle(1))
            self.assertTrue(second.enqueue(update(1)));self.assertEqual(second.pending_count(),0);second.stop()

    def test_cap_rejects_new_update_without_losing_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,lambda row:None,max_pending=1)
            self.assertTrue(inbox.enqueue(update(1)));self.assertFalse(inbox.enqueue(update(2)));self.assertTrue(inbox.enqueue(update(1)))
            self.assertEqual(inbox.pending_count(),1);inbox.stop()

    def test_three_failures_notify_once_and_clear_sensitive_payload(self):
        import sqlite3
        calls=[];notifications=[]
        def handle(row):calls.append(row['update_id']);raise RuntimeError('private payload')
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,handle,on_failure=lambda chat:notifications.append(chat));inbox.enqueue(update(1,text='private'))
            inbox.pump();self.assertTrue(inbox.wait_idle(2))
            self.assertEqual(calls,[1,1,1]);self.assertEqual(notifications,[10])
            with sqlite3.connect(tmp+'/inbox.db') as db:self.assertIsNone(db.execute('SELECT payload FROM inbox WHERE update_id=1').fetchone()[0])
            inbox.enqueue(update(1));inbox.pump();self.assertEqual(notifications,[10]);inbox.stop()

    def test_workers_are_daemon_and_never_exceed_four(self):
        release=threading.Event();four_started=threading.Event();lock=threading.Lock();active=0;peak=0;daemon=[]
        def handle(row):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active);daemon.append(threading.current_thread().daemon)
                if active==4:four_started.set()
            release.wait(2)
            with lock:active-=1
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,handle,max_workers=99)
            for i in range(8):inbox.enqueue(update(i,100+i))
            self.assertEqual(inbox.pump(),4);self.assertTrue(four_started.wait(1));self.assertEqual(inbox.pump(),0)
            release.set();self.assertTrue(inbox.wait_idle(2));self.assertEqual(peak,4);self.assertTrue(all(daemon));inbox.stop()

    def test_interrupted_running_row_is_recovered_with_callback_marker(self):
        import sqlite3
        from pathlib import Path
        received=[]
        with tempfile.TemporaryDirectory() as tmp:
            inbox=Inbox(tmp,lambda row:None);inbox.enqueue(update(1,callback='downloads'));inbox.stop()
            with sqlite3.connect(tmp+'/inbox.db') as db:db.execute("UPDATE inbox SET status='running'")
            recovered=Inbox(tmp,received.append);recovered.pump();self.assertTrue(recovered.wait_idle(1))
            self.assertTrue(received[0]['_callback_answered'])
            self.assertEqual(Path(tmp+'/inbox.db').stat().st_mode & 0o777,0o600);recovered.stop()
