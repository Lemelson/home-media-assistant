import tempfile
import unittest
from bot.dialog import Dialog
from bot.progress import ProgressMonitor
from bot.download_dashboard import render
from test_progress_rotation import Chat

class DashboardTests(unittest.TestCase):
    def test_three_films_share_message_and_hash_buttons_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat();rows=[dict(hashString=c*40,name=c,status=4,totalSize=1000,leftUntilDone=500,percentDone=.5) for c in 'abc']
            dialog=Dialog(tmp,chat,'','',lambda:dict(disk_ok=True,torrents=rows))
            for i,row in enumerate(rows):
                receipt=dialog.send_html(1,'Передаю')
                ProgressMonitor(dialog).register(1,dict(hash=row['hashString'],name=row['name'],message_id=receipt['message_id']),100+i)
            ProgressMonitor(dialog).tick(160)
            self.assertEqual(len(chat.messages),1)
            text=next(iter(chat.messages.values()))
            for i,c in enumerate('abc',1):self.assertIn('%d. %s' % (i,c),text)
            state=dialog.jobs.read_state('download-dashboard:1')
            self.assertEqual([b['callback_data'] for row in state['markup']['inline_keyboard'] for b in row],['priority:'+c*40 for c in 'abc'])
            rows[0].update(status=6,percentDone=1,leftUntilDone=0)
            ProgressMonitor(dialog).tick(220)
            self.assertEqual(len(chat.messages),1)
            self.assertIn('Фильм скачан',next(iter(chat.messages.values())))

    def test_pagination_is_bounded_and_does_not_change_hash_identity(self):
        states=[dict(name='Title <&>'*20,hash='%040x'%i,active=True,created=i,text='░'*18+' · 0.0%') for i in range(50)]
        text,markup,page=render(states,5)
        self.assertLess(len(text),4096)
        self.assertEqual(page,5)
        self.assertEqual(markup['inline_keyboard'][0][0]['callback_data'],'priority:%040x'%30)
        self.assertIn('31.',text)

    def test_old_cards_deleted_only_after_successful_shared_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat();dialog=Dialog(tmp,chat,'','',lambda:{})
            for i in range(3):
                old=dialog.send_html(1,'old')['message_id']
                dialog.jobs.write_state('transfer:1:'+str(i),dict(uid=1,hash=str(i),name=str(i),active=True,message_id=old,text='░'*18))
            ProgressMonitor(dialog).tick(100)
            self.assertEqual(len(chat.messages),1)

    def test_new_download_moves_summary_to_new_receipt_and_includes_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat();dialog=Dialog(tmp,chat,'','',lambda:{})
            ProgressMonitor(dialog).register(1,dict(hash='a'*40,name='Active',totalSize=1000),100)
            old=dialog.jobs.read_state('download-dashboard:1')['message_id']
            receipt=dialog.send_html(1,'New download')['message_id']
            ProgressMonitor(dialog).register(1,dict(hash='b'*40,name='Paused',totalSize=2000,paused=True,message_id=receipt),110)
            new=dialog.jobs.read_state('download-dashboard:1')
            self.assertEqual(new['message_id'],receipt);self.assertNotEqual(old,receipt)
            self.assertIn('Active',new['text']);self.assertIn('Paused',new['text'])
            self.assertIn('С нуля:',new['text'])
            self.assertTrue(any('Начать' in x['text'] for row in new['markup']['inline_keyboard'] for x in row))
