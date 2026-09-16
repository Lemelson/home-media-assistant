import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from bot.dialog import Dialog
from bot.search import SearchFlow
from bot.search_sessions import SearchSessions
from bot.progress import ProgressMonitor, progress_text
from bot.providers import Prowlarr, ProviderError

class Chat:
    def __init__(self): self.messages={}; self.next=0; self.calls=[]
    def call(self, method, **p):
        self.calls.append((method,p))
        if method=='sendMessage':
            self.next+=1; self.messages[self.next]=p; return {'message_id':self.next}
        if method=='editMessageText':
            self.messages[p['message_id']]=p; return {'message_id':p['message_id']}
        if method=='deleteMessage': self.messages.pop(p['message_id'],None)
        return True

class RetryProgressTests(unittest.TestCase):
    proxy='http://127.0.0.1:9696/1/download?link=opaque'
    def test_transient_download_retries_automatically(self):
        opener=MagicMock(); response=MagicMock()
        response.__enter__.return_value.read.return_value=b'd4:infod4:name4:testee'
        opener.open.side_effect=[TimeoutError(),response]
        with patch('bot.providers.urllib.request.build_opener',return_value=opener), patch('bot.providers.time.sleep'):
            result=Prowlarr('test').download({'downloadUrl':self.proxy})
        self.assertIn('metainfo',result)
        self.assertEqual(opener.open.call_count,2)

    def test_retry_deadline_bounds_attempts_and_socket_timeouts(self):
        now=[0.]; timeouts=[]
        def fail(req,timeout):
            timeouts.append(timeout); now[0]+=timeout; raise TimeoutError()
        def sleep(seconds): now[0]+=seconds
        opener=MagicMock(); opener.open.side_effect=fail
        with patch('bot.providers.urllib.request.build_opener',return_value=opener), patch('bot.providers.time.monotonic',side_effect=lambda:now[0]), patch('bot.providers.time.sleep',side_effect=sleep):
            with self.assertRaises(ProviderError): Prowlarr('test').download({'downloadUrl':self.proxy})
        self.assertGreater(len(timeouts),1); self.assertLessEqual(now[0],300)

    def test_failed_proxy_uses_same_release_infohash(self):
        opener=MagicMock(); opener.open.side_effect=TimeoutError()
        with patch('bot.providers.urllib.request.build_opener',return_value=opener):
            result=Prowlarr('test').download({'downloadUrl':self.proxy,'infoHash':'a'*40})
        self.assertEqual(result,{'magnet':'magnet:?xt=urn:btih:'+'a'*40})

    def test_failed_selection_then_success_leaves_one_status(self):
        indexer=MagicMock(); indexer.download.side_effect=[ProviderError('failed'),{'metainfo':'dGVzdA=='}]
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat(); dialog=Dialog(tmp,chat,'','',lambda:{})
            flow=SearchFlow(None,indexer)
            choice=dialog.send_html(1,'Раздачи',{'inline_keyboard':[[{'text':'1','callback_data':'release:abc:0'}]]})
            state=dict(nonce='abc',stage='release',expires=time.time()+3600,selected={'title':'Film','kind':'movie'},releases=[{'title':'Film','size':1000000}],choice_message_id=choice['message_id'])
            SearchSessions(dialog.jobs,1).save(state)
            flow.choose(1,1,'release','abc',0,dialog)
            flow.choose(1,1,'release','abc',0,dialog)
            self.assertFalse(any('Не удалось' in p['text'] for p in chat.messages.values()))
            job=dialog.jobs.pending()[0]
            ProgressMonitor(dialog).register(1,dict(hash='a'*40,name='Film',totalSize=1000000,message_id=job['payload']['message_id']),100)
            self.assertEqual(len(chat.messages),1)
            self.assertIn('0.0%',next(iter(chat.messages.values()))['text'])

    def test_first_card_has_bar_history_speed_and_eta(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat(); dialog=Dialog(tmp,chat,'','',lambda:{})
            dialog.jobs.write_state('transfer:1:old',dict(uid=1,hash='old',speed_history=[[100,1024*1024]]))
            ProgressMonitor(dialog).register(1,dict(hash='new',name='Film',totalSize=1024**3),200)
            text=next(iter(chat.messages.values()))['text']
            for fragment in ('░','0.0%','МБ/с','по истории','Осталось:'): self.assertIn(fragment,text)
            self.assertNotIn('каждые 15',text)

    def test_current_speed_replaces_prior_after_three_minutes(self):
        state={'name':'Film','bootstrap_history':[[100,1024*1024]]}
        torrent=dict(status=4,totalSize=1024**3,percentDone=0,leftUntilDone=1024**3)
        for now in range(100,281,30):
            torrent['leftUntilDone']=1024**3-(now-100)*2*1024**2
            text,_=progress_text(state,torrent,now)
        self.assertIn('Скорость: 2.0 МБ/с',text); self.assertNotIn('Предварительно',text)

    def test_existing_transfer_removes_redundant_queue_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat(); dialog=Dialog(tmp,chat,'','',lambda:{})
            monitor=ProgressMonitor(dialog)
            monitor.register(1,dict(hash='new',name='Film',totalSize=1000),100)
            extra=dialog.send_html(1,'Передаю загрузку')
            monitor.register(1,dict(hash='new',name='Film',message_id=extra['message_id']),110)
            self.assertEqual(len(chat.messages),1)
            self.assertNotIn(extra['message_id'],chat.messages)

    def test_no_history_does_not_invent_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat(); dialog=Dialog(tmp,chat,'','',lambda:{})
            ProgressMonitor(dialog).register(1,dict(hash='new',name='Film',totalSize=1000),100)
            text=next(iter(chat.messages.values()))['text']
            self.assertIn('0.0%',text); self.assertIn('истории пока нет',text)
            self.assertNotIn('Осталось:',text)

    def test_paused_initial_card_has_no_false_eta(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat(); dialog=Dialog(tmp,chat,'','',lambda:{})
            dialog.jobs.write_state('transfer:1:old',dict(uid=1,hash='old',speed_history=[[100,1000]]))
            ProgressMonitor(dialog).register(1,dict(hash='new',name='Film',totalSize=1000,paused=True),100)
            text=next(iter(chat.messages.values()))['text']
            self.assertIn('На паузе',text); self.assertIn('0.0%',text); self.assertNotIn('Осталось:',text)

    def test_edit_fallback_deletion_retries_after_telegram_recovers(self):
        from bot.delivery import DeliveryWorker
        with tempfile.TemporaryDirectory() as tmp:
            chat=Chat(); dialog=Dialog(tmp,chat,'','',lambda:{})
            old=dialog.send_html(1,'Не удалось получить торрент')['message_id']
            state=dict(thread_id='a',nonce='a',loading_message_id=old)
            call=chat.call
            def broken(method,**p):
                if method in ('editMessageText','deleteMessage'):raise RuntimeError('temporary')
                return call(method,**p)
            chat.call=broken
            SearchFlow(None,None)._show(1,1,state,dialog,'Получаю торрент')
            self.assertEqual(len(chat.messages),2)
            chat.call=call
            DeliveryWorker(dialog,MagicMock()).step(100)
            self.assertEqual(len(chat.messages),1)
            self.assertNotIn(old,chat.messages)

    def test_hung_fetch_returns_at_deadline_and_late_result_is_discarded(self):
        import threading
        release=threading.Event(); exited=threading.Event()
        client=Prowlarr('test'); client.DOWNLOAD_BUDGET=.05
        def hung(row,timeout):
            release.wait(1)
            exited.set()
            return {'metainfo':'late'}
        with patch.object(client,'_download_once',side_effect=hung) as request:
            started=time.monotonic()
            try:
                with self.assertRaisesRegex(ProviderError,'torrent_download_timeout'):
                    client.download({'downloadUrl':self.proxy})
                self.assertLess(time.monotonic()-started,.5)
            finally:release.set()
            self.assertTrue(exited.wait(1))
            self.assertEqual(request.call_count,1)
