import tempfile
import unittest
from bot.dialog import Dialog
from bot.progress import ProgressMonitor

class Chat:
    def __init__(self):
        self.messages = {}; self.next_id = 0; self.fail_delete = False
    def call(self, method, **p):
        if method == 'sendMessage':
            self.next_id += 1
            self.messages[self.next_id] = p['text']
            return {'message_id': self.next_id}
        if method == 'deleteMessage':
            if self.fail_delete: raise RuntimeError('temporary')
            self.messages.pop(p['message_id'], None)
        if method == 'editMessageText':
            self.messages[p['message_id']] = p['text']
        return True

class RotationTests(unittest.TestCase):
    def test_latest_notice_is_edited_and_replaced_until_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Chat()
            t = dict(hashString='a'*40, status=4, percentDone=0, totalSize=1000, leftUntilDone=1000)
            d = Dialog(tmp, tg, '', '', lambda: dict(disk_ok=True, torrents=[t]))
            m = ProgressMonitor(d); m.register(1, dict(hash='a'*40, name='Film'), 100)
            for n, pct in enumerate((.25, .5, .75, .9, .95, .99)):
                now = 160 + n*120
                t.update(percentDone=pct, leftUntilDone=1000*(1-pct))
                m.tick(now)
                self.assertEqual(len(tg.messages), 1)
                latest = next(iter(tg.messages))
                t.update(percentDone=pct+.001, leftUntilDone=1000*(1-pct-.001))
                ProgressMonitor(d).tick(now+60)
                self.assertEqual(list(tg.messages), [latest])
                self.assertIn('%.1f%%' % ((pct+.001)*100), tg.messages[latest])
            tg.fail_delete = True
            t.update(percentDone=1, leftUntilDone=0, status=6)
            m.tick(1000)
            self.assertEqual(len(tg.messages), 1)
            count = tg.next_id
            tg.fail_delete = False
            ProgressMonitor(d).tick(1060)
            self.assertEqual(tg.next_id, count)
            self.assertEqual(len(tg.messages), 1)
            self.assertIn('Фильм скачан', next(iter(tg.messages.values())))
