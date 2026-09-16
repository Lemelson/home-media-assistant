import tempfile
import unittest
from bot.dialog import Dialog
from bot.search import SearchFlow

class Telegram:
    def __init__(self): self.calls=[]; self.next_id=1000
    def call(self,method,**payload):
        self.calls.append((method,payload)); self.next_id+=1
        return {'message_id':payload.get('message_id',self.next_id)}

class Resolver:
    def __init__(self): self.contexts=[]
    def identify(self,text,context):
        self.contexts.append((text,context))
        if text=='Ускользающая красота': return {'reply':'Уточни год.', 'candidates':[]}
        title='Мемуары гейши' if text=='Мемуары гейши' else 'Ускользающая красота'
        return {'candidates':[{'title':title,'kind':'movie','year':2005 if title=='Мемуары гейши' else 1996}]}

class Indexer:
    def search(self,q): return [{'title':q+' 1080p','size':1024**3,'seeders':20}]
    def download(self,row): return {'magnet':'magnet:?xt=urn:btih:'+('a' if 'гейши' in row['title'] else 'b')*40}

class MultiFilmTests(unittest.TestCase):
    def test_reply_and_independent_buttons_survive_restart_and_queue_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); resolver=Resolver(); flow=SearchFlow(resolver,Indexer())
            d=Dialog(tmp,tg,'owner','',lambda:{},search=flow)
            def message(i,text,reply=None):
                m={'message_id':i,'from':{'id':10,'username':'owner'},'chat':{'id':10,'type':'private'},'text':text}
                if reply: m['reply_to_message']={'message_id':reply,'from':{'is_bot':True},'text':'Уточни год.'}
                d.handle({'update_id':i,'message':m})
            message(1,'Ускользающая красота'); first=tg.next_id
            message(2,'Мемуары гейши'); geisha=tg.next_id
            geisha_button=tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
            message(3,'1996',first)
            beauty_button=tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
            retired=[p['message_id'] for m,p in tg.calls if m=='editMessageReplyMarkup']
            self.assertNotIn(geisha,retired,'Reply about Beauty must preserve Geisha keyboard')
            context=str(resolver.contexts[-1][1])
            self.assertIn('Ускользающая красота',context)
            self.assertNotIn('Мемуары гейши',context)
            d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(resolver,Indexer()))
            releases=[]
            for button in (geisha_button,beauty_button):
                d.callback(10,10,button,'button:'+button)
                releases.append(tg.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data'])
            for button in releases: d.callback(10,10,button,'release:'+button)
            self.assertEqual(len(d.jobs.pending()),2)
            for button in releases: d.callback(10,10,button,'again:'+button)
            self.assertEqual(len(d.jobs.pending()),2)


class PresentationTests(unittest.TestCase):
    def test_search_status_becomes_its_own_release_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
            d.search(10,10,'Мемуары гейши',d)
            nonce=d.jobs.read_state('search:10')['nonce']
            d.search.choose(10,10,'media',nonce,0,d)
            searching=[p for m,p in tg.calls if m=='sendMessage' and 'Ищу раздачи' in p.get('text','')]
            self.assertIn('<b>«Мемуары гейши»</b>',searching[0]['text'])
            edits=[p for m,p in tg.calls if m=='editMessageText']
            self.assertTrue(any('Выбери вариант' in p['text'] for p in edits))

    def test_library_button_is_persistent_and_uses_real_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); d=Dialog(tmp,tg,'owner','',lambda:{},media_library=lambda:{'disk_ok':True,'items':[{'id':'abc','name':'Film.1999.WEB-DL.1080p.x264.mkv','kind':'movie','size_bytes':1024**3}]})
            d.handle({'update_id':1,'message':{'from':{'id':10,'username':'owner'},'chat':{'id':10,'type':'private'},'text':'/start'}})
            self.assertIn('Мои фильмы',str(tg.calls[-1][1]['reply_markup'].get('keyboard')))
            d.handle({'update_id':2,'message':{'from':{'id':10,'username':'owner'},'chat':{'id':10,'type':'private'},'text':'🎬 Мои фильмы'}})
            text=tg.calls[-1][1]['text']
            self.assertIn('Film (1999)',text); self.assertIn('1080p',text)
            self.assertNotIn('WEB-DL.1080p.x264',text)

class ReceiptAndCorrectionTests(unittest.TestCase):
    @staticmethod
    def message(dialog, number, text, receipt=None):
        message={'message_id':number,'from':{'id':10,'username':'owner'},
                 'chat':{'id':10,'type':'private'},'text':text}
        if receipt: message['_receipt_message_id']=receipt
        return dialog.handle({'update_id':number,'message':message})

    def test_receipt_is_edited_into_candidates_and_bound_for_a_reply(self):
        from bot.search_sessions import SearchSessions
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
            self.message(d,1,'Мемуары гейши',receipt=55)
            edits=[p for method,p in tg.calls if method=='editMessageText']
            self.assertEqual(len(edits),1)
            self.assertEqual(edits[0]['message_id'],55)
            self.assertIn('Мемуары гейши',edits[0]['text'])
            self.assertTrue(edits[0]['reply_markup']['inline_keyboard'])
            state=SearchSessions(d.jobs,10).reply(55)
            self.assertEqual(state['candidates'][0]['title'],'Мемуары гейши')

    def test_provider_error_finishes_receipt_without_raising_or_breaking_other_keyboard(self):
        class FailingResolver(Resolver):
            def identify(self,text,context):
                if text=='Недоступный фильм': raise TimeoutError('provider unavailable')
                return super().identify(text,context)
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(FailingResolver(),Indexer()))
            self.message(d,1,'Мемуары гейши',receipt=55)
            self.message(d,2,'Недоступный фильм',receipt=56)
            errors=[p for method,p in tg.calls if method=='editMessageText' and p['message_id']==56]
            self.assertEqual(len(errors),1)
            self.assertIn('не удалось',errors[0]['text'])
            retired=[p['message_id'] for method,p in tg.calls if method=='editMessageReplyMarkup']
            self.assertNotIn(55,retired)

    def test_failed_receipt_edit_sends_fallback_candidates(self):
        class CannotEdit(Telegram):
            def call(self,method,**payload):
                if method=='editMessageText': raise RuntimeError('message cannot be edited')
                return super().call(method,**payload)
        with tempfile.TemporaryDirectory() as tmp:
            tg=CannotEdit(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
            self.message(d,1,'Мемуары гейши',receipt=55)
            sent=[p for method,p in tg.calls if method=='sendMessage']
            self.assertTrue(any('Мемуары гейши' in p['text'] and p.get('reply_markup',{}).get('inline_keyboard') for p in sent))

    def test_seven_corrections_keep_original_query_and_unrelated_film_button(self):
        class RecordingResolver:
            def __init__(self): self.contexts=[]
            def identify(self,text,context):
                self.contexts.append((text,list(context)))
                title='Мемуары гейши' if text=='Мемуары гейши' else 'Большое смелое красивое путешествие'
                return {'candidates':[{'title':title,'kind':'movie','year':2005 if text=='Мемуары гейши' else 2025}]}
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); resolver=RecordingResolver(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(resolver,Indexer()))
            self.message(d,1,'Мемуары гейши',receipt=55)
            original='Большое смелое красивое путешествие'
            self.message(d,2,original,receipt=56)
            thread=d.jobs.read_state('search:10')['thread_id']
            for i in range(7):
                self.message(d,3+i,'Не тот и не другой, уточнение '+str(i),receipt=57+i)
                self.assertEqual(d.jobs.read_state('search:10')['thread_id'],thread)
                context=resolver.contexts[-1][1]
                self.assertEqual(context[0],{'role':'user','content':original})
                self.assertNotIn('Мемуары гейши',str(context))
            retired=[p['message_id'] for method,p in tg.calls if method=='editMessageReplyMarkup']
            self.assertNotIn(55,retired)
            self.assertLessEqual(len(d.jobs.read_state('search:10')['context']),10)
            state=d.jobs.read_state('search:10')
            d.search.choose(10,10,'media',state['nonce'],0,d)
            self.assertEqual(d.jobs.read_state('search:10')['context'][0],{'role':'user','content':original})

    def test_textual_selection_finishes_its_intake_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); d=Dialog(tmp,tg,'owner','',lambda:{},search=SearchFlow(Resolver(),Indexer()))
            self.message(d,1,'Мемуары гейши',receipt=55)
            self.message(d,2,'1',receipt=56)
            finished=[p for method,p in tg.calls if method=='editMessageText' and p.get('message_id')==56]
            self.assertTrue(finished,'Textual selection must complete its intake acknowledgement')

    def test_natural_control_keeps_history_and_finishes_receipt(self):
        class ControlResolver:
            def __init__(self):self.context=None
            def identify(self,text,context):
                self.context=context
                return {'action':'downloads','target':'','reply':'','candidates':[]}
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram(); resolver=ControlResolver()
            d=Dialog(tmp,tg,'owner','',lambda:{'disk_ok':True,'torrents':[]},search=SearchFlow(resolver,Indexer()))
            d.remember(10,'assistant','Последний выбранный фильм — Мемуары гейши.')
            self.message(d,1,'покажи загрузки',receipt=56)
            self.assertIn('Мемуары гейши',str(resolver.context))
            finished=[p for method,p in tg.calls if method=='editMessageText' and p.get('message_id')==56]
            self.assertTrue(finished,'Natural controls must complete their intake acknowledgement')

if __name__=='__main__': unittest.main()
