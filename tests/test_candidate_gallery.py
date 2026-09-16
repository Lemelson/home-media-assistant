import unittest
from types import SimpleNamespace
from bot.candidate_gallery import send_candidate_gallery


class Telegram:
    def __init__(self, bad=(), reject_all=False):
        self.bad=set(bad); self.reject_all=reject_all; self.calls=[]
    def call(self, method, **payload):
        self.calls.append((method,payload))
        photos=[b['photo']['media'] for b in payload['rich_message']['blocks'] if b['type']=='photo']
        if self.reject_all or self.bad.intersection(photos): raise RuntimeError('opaque Telegram rejection')
        return {'message_id':42}


class CandidateGalleryTests(unittest.TestCase):
    def render(self, galleries, telegram, **options):
        candidates=[{'title':'Фильм '+str(i)} for i in range(len(galleries))]
        lines=['Найдено <b>несколько</b> вариантов']+['<b>'+c['title']+'</b>' for c in candidates]+['Выбери фильм.']
        markup={'inline_keyboard':[[{'text':c['title'],'callback_data':'media:'+str(i)}] for i,c in enumerate(candidates)]}
        result=send_candidate_gallery(SimpleNamespace(telegram=telegram),10,candidates,lines,markup,galleries,**options)
        return result,markup

    def test_one_candidate_keeps_three_photos_and_keyboard(self):
        tg=Telegram(); result,markup=self.render([['https://img.test/a','https://img.test/b','https://img.test/c']],tg)
        self.assertEqual(result,{'message_id':42}); self.assertEqual(len(tg.calls),1)
        payload=tg.calls[0][1]; self.assertEqual(payload['reply_markup'],markup)
        self.assertEqual([b['photo']['media'] for b in payload['rich_message']['blocks'] if b['type']=='photo'],['https://img.test/a','https://img.test/b','https://img.test/c'])

    def test_multiple_candidates_keep_photos_with_their_own_heading(self):
        tg=Telegram(); self.render([['https://img.test/a'],['https://img.test/b'],['https://img.test/c']],tg)
        blocks=tg.calls[0][1]['rich_message']['blocks']
        self.assertEqual([b['type'] for b in blocks],['paragraph','paragraph','photo','paragraph','photo','paragraph','photo','paragraph'])
        for index,photo in enumerate(('a','b','c')):
            self.assertEqual(blocks[1+2*index]['text'],{'type':'bold','text':'Фильм '+str(index)})
            self.assertEqual(blocks[2+2*index]['photo']['media'],'https://img.test/'+photo)

    def test_bad_photo_does_not_discard_two_good_photos(self):
        tg=Telegram(bad=['https://img.test/c']); result,markup=self.render([['https://img.test/a','https://img.test/b','https://img.test/c']],tg)
        self.assertEqual(result,{'message_id':42}); self.assertLessEqual(len(tg.calls),4)
        payload=tg.calls[-1][1]
        self.assertEqual(payload['reply_markup'],markup)
        self.assertEqual([b['photo']['media'] for b in payload['rich_message']['blocks'] if b['type']=='photo'],['https://img.test/a','https://img.test/b'])

    def test_bad_candidate_photo_keeps_all_headings_and_other_candidate_photos(self):
        tg=Telegram(bad=['https://img.test/b']); result,markup=self.render([['https://img.test/a'],['https://img.test/b'],['https://img.test/c']],tg)
        self.assertIsNotNone(result)
        payload=tg.calls[-1][1]; blocks=payload['rich_message']['blocks']
        self.assertEqual(payload['reply_markup'],markup)
        self.assertEqual([(b['text']['text'] if isinstance(b['text'],dict) else b['text']) for b in blocks if b['type']=='paragraph'],['Найдено несколько вариантов','Фильм 0','Фильм 1','Фильм 2','Выбери фильм.'])
        self.assertEqual([b['photo']['media'] for b in blocks if b['type']=='photo'],['https://img.test/a','https://img.test/c'])

    def test_all_rejected_returns_none_in_four_calls(self):
        tg=Telegram(reject_all=True); result,_=self.render([['https://img.test/a','https://img.test/b','https://img.test/c']],tg)
        self.assertIsNone(result); self.assertEqual(len(tg.calls),4)

    def test_no_photos_uses_callers_text_fallback(self):
        tg=Telegram(); result,_=self.render([[]],tg)
        self.assertIsNone(result); self.assertEqual(tg.calls,[])

    def test_lazy_alternative_preserves_one_photo_for_every_candidate(self):
        tg=Telegram(bad=['https://img.test/series-first']); requested=[]
        def alternatives():
            requested.append(True)
            return [['https://img.test/series-first','https://img.test/series-second'],
                    ['https://img.test/film-first']]
        result,markup=self.render([['https://img.test/series-first'],['https://img.test/film-first']],tg,
                                  per_candidate_limit=1,alternatives=alternatives)
        self.assertEqual(result,{'message_id':42}); self.assertEqual(requested,[True]); self.assertEqual(len(tg.calls),2)
        blocks=tg.calls[-1][1]['rich_message']['blocks']
        self.assertEqual(tg.calls[-1][1]['reply_markup'],markup)
        self.assertEqual(blocks[1]['text']['text'],'Фильм 0'); self.assertEqual(blocks[2]['photo']['media'],'https://img.test/series-second')
        self.assertEqual(blocks[3]['text']['text'],'Фильм 1'); self.assertEqual(blocks[4]['photo']['media'],'https://img.test/film-first')

    def test_success_never_fetches_alternatives_and_limit_selects_first_photo(self):
        def forbidden():raise AssertionError('unnecessary lookup')
        tg=Telegram(); result,_=self.render([['https://img.test/a','https://img.test/b'],['https://img.test/c']],tg,
            per_candidate_limit=1,alternatives=forbidden)
        self.assertEqual(result,{'message_id':42}); self.assertEqual(len(tg.calls),1)
        photos=[b['photo']['media'] for b in tg.calls[0][1]['rich_message']['blocks'] if b['type']=='photo']
        self.assertEqual(photos,['https://img.test/a','https://img.test/c'])

    def test_alternatives_are_bounded_even_if_every_url_fails(self):
        tg=Telegram(reject_all=True); requested=[]
        def alternatives():
            requested.append(True)
            return [['https://img.test/a','https://img.test/b','https://img.test/c'],
                    ['https://img.test/d','https://img.test/e','https://img.test/f']]
        result,_=self.render([['https://img.test/a'],['https://img.test/d']],tg,per_candidate_limit=1,alternatives=alternatives)
        self.assertIsNone(result); self.assertEqual(requested,[True]); self.assertEqual(len(tg.calls),4)

    def test_alternative_provider_error_still_allows_smaller_gallery(self):
        def fail():raise TimeoutError('lookup failed')
        tg=Telegram(bad=['https://img.test/a'])
        result,_=self.render([['https://img.test/a'],['https://img.test/b']],tg,per_candidate_limit=1,alternatives=fail)
        self.assertEqual(result,{'message_id':42}); self.assertLessEqual(len(tg.calls),4)

    def test_partial_alternative_results_keep_other_candidates_primary_photo(self):
        tg=Telegram(bad=['https://img.test/a'])
        result,_=self.render([['https://img.test/a'],['https://img.test/c']],tg,
            per_candidate_limit=1,alternatives=lambda:[['https://img.test/a','https://img.test/b'],[]])
        self.assertIsNotNone(result)
        photos=[b['photo']['media'] for b in tg.calls[-1][1]['rich_message']['blocks'] if b['type']=='photo']
        self.assertEqual(photos,['https://img.test/b','https://img.test/c'])
