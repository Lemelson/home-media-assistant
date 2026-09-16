import tempfile
import unittest
from pathlib import Path
from bot.search import SearchFlow, rank_releases
from bot.dialog import Dialog
from tests.test_dialog import Telegram


class SearchTests(unittest.TestCase):
    def test_release_ranking_separates_seeders_and_rejects_dead(self):
        rows = [dict(title='dead', seeders=0, leechers=900, size=6*1024**3),
                dict(title='small', seeders=40, size=2*1024**3),
                dict(title='good', seeders=12, size=6*1024**3)]
        self.assertEqual([r['title'] for r in rank_releases(rows)], ['good', 'small'])

    def test_text_choice_keeps_context_and_requires_release_selection(self):
        class Resolver:
            def identify(self, text, context):
                return {'reply':'Какой фильм?', 'candidates':[{'title':'Film', 'year':2008, 'kind':'movie'}, {'title':'Other', 'year':2020, 'kind':'movie'}]}
        class Indexer:
            def search(self, query):
                return [{'title':'Film 1080p', 'seeders':12, 'size':6*1024**3, 'guid':'release1'}]
            def download(self, row):
                return {'magnet':'magnet:?xt=urn:btih:'+'a'*40}
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(), Indexer())
            d=Dialog(Path(tmp), Telegram(), 'owner','',lambda:{},search=flow)
            flow(10,10,'какой-то фильм',d)
            flow(10,10,'первый',d)
            self.assertEqual(d.jobs.pending(), [])
            flow(10,10,'скачай первый',d)
            self.assertEqual(len(d.jobs.pending()),1)
            self.assertEqual(d.jobs.pending()[0]['payload']['kind'],'movie')
            flow(10,10,'скачай первый',d)
            self.assertEqual(len(d.jobs.pending()),1)

    def test_another_user_cannot_use_selection(self):
        class Resolver:
            def identify(self,text,context):return {'reply':'Напиши название', 'candidates':[]}
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(),None)
            d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            flow.choose(11,11,'release','missing',0,d)
            self.assertEqual(d.jobs.pending(),[])

    def test_user_examples_reject_music_and_prefer_reasonable_1080p_size(self):
        media={'title':'Красота по-американски','original_title':'American Beauty','year':1999,'kind':'movie'}
        def row(title,size,seeds):return dict(title=title,size=int(size*1024**3),seeders=seeds)
        rows=[row('Grateful Dead - American Beauty (1970) FLAC',.3,100),
              row('Красота по-американски / American Beauty (1999) BDRip 1080p',16.26,75),
              row('American Beauty (1999) BDRemux 1080p',31.37,70),
              row('American Beauty (1999) WEB-DLRip',2.08,123),
              row('American Beauty (2017) MP3',.7,300)]
        ranked=rank_releases(rows,media)
        self.assertEqual(ranked[0]['size'],int(16.26*1024**3))
        self.assertEqual(len(ranked),3)

    def test_wrong_series_season_is_not_offered(self):
        media={'title':'Example','year':2020,'kind':'show','season':2}
        rows=[dict(title='Example (2020) S01 1080p',seeders=80,size=15*1024**3),
              dict(title='Example (2020) Сезон 2 1080p',seeders=30,size=16*1024**3)]
        self.assertEqual(len(rank_releases(rows,media)),1)
        self.assertIn('Сезон 2',rank_releases(rows,media)[0]['title'])

    def test_numeric_season_clarification_reaches_resolver(self):
        class Resolver:
            def __init__(self): self.calls=[]
            def identify(self,text,context):
                self.calls.append(text)
                return {'reply':'Какой сезон?', 'candidates':[]}
        resolver=Resolver()
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(resolver,None)
            d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            flow(10,10,'Example',d)
            flow(10,10,'2',d)
            self.assertEqual(resolver.calls,['Example','2'])

    def test_replayed_text_film_choice_cannot_choose_release_after_restart(self):
        class Resolver:
            def identify(self,text,context):
                return {'candidates':[{'title':'Film','kind':'movie','year':2008}]}
        class Indexer:
            def search(self,query):
                return [{'title':'Film (2008) 1080p','seeders':20,'size':31*1024**3}]
            def download(self,row):
                return {'magnet':'magnet:?xt=urn:btih:'+'a'*40}
        def update(i,text):
            return {'update_id':i,'message':{'from':{'id':10,'username':'owner'},
                'chat':{'id':10,'type':'private'},'text':text}}
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(),Indexer())
            d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            d.handle(update(1,'Film'))
            d.handle(update(2,'1'))
            self.assertEqual(d.jobs.pending(),[])
            d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            d.handle(update(2,'1'))
            self.assertEqual(d.jobs.pending(),[])
            d.handle(update(3,'1'))
            self.assertEqual(len(d.jobs.pending()),1)
            context=d.jobs.read_state('search:10')['context']
            self.assertTrue(any('Выбран фильм или сериал:' in c['content'] for c in context))
            self.assertTrue(any('Выбрана раздача:' in c['content'] for c in context))

    def test_multiseason_packs_are_not_offered_for_one_season(self):
        media={'title':'Example','kind':'show','season':2}
        titles=['Example Сезоны: 1-5 1080p','Example S01-S05 1080p',
                'Example Сезон 3 1080p','Example S03-S05 1080p']
        rows=[dict(title=title,seeders=20,size=15*1024**3) for title in titles]
        self.assertEqual(rank_releases(rows,media),[])

    def test_title_matches_complete_tokens(self):
        media={'title':'Up','kind':'movie','year':2009}
        rows=[dict(title=title,seeders=20,size=15*1024**3)
              for title in ['Upstream (2009) 1080p','Up (2009) 1080p']]
        self.assertEqual([r['title'] for r in rank_releases(rows,media)],['Up (2009) 1080p'])

    def test_owner_eligible_movie_keeps_explicit_selection(self):
        self.run_auto_case('Film (2008) 1080p',16,20,expected_jobs=0)

    def test_poor_or_oversized_releases_keep_manual_choice(self):
        for title,size,seeds in [('Film (2008) 1080p',31,20),
                                 ('Film (2008) 1080p',16,2),
                                 ('Film (2008) 720p',16,20)]:
            with self.subTest(title=title,size=size,seeds=seeds):
                self.run_auto_case(title,size,seeds,expected_jobs=0)

    def test_eligible_series_keeps_manual_choice(self):
        self.run_auto_case('Film (2008) S02 1080p',16,20,expected_jobs=0,kind='show')

    def test_indexer_error_never_autoqueues(self):
        self.run_auto_case('Film (2008) 1080p',16,20,expected_jobs=0,error=True)

    def run_auto_case(self,title,size,seeds,expected_jobs,kind='movie',error=False):
        class Resolver:
            def identify(self,text,context):
                return {'candidates':[{'title':'Фильм','original_title':'Film','year':2008,'kind':kind,'season':2 if kind=='show' else None}]}
        class Indexer:
            def __init__(self):self.queries=[];self.downloads=[]
            def search(self,query):
                self.queries.append(query)
                if error:raise RuntimeError('indexer unavailable')
                return [{'title':title,'size':size*1024**3,'seeders':seeds,'guid':'same-release'}]
            def download(self,row):
                self.downloads.append(row)
                return {'magnet':'magnet:?xt=urn:btih:'+'a'*40}
        def update(i,text):
            return {'update_id':i,'message':{'from':{'id':10,'username':'owner'},
                'chat':{'id':10,'type':'private'},'text':text}}
        with tempfile.TemporaryDirectory() as tmp:
            indexer=Indexer();telegram=Telegram();flow=SearchFlow(Resolver(),indexer)
            d=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow)
            d.handle(update(1,'Film'))
            self.assertEqual(d.jobs.pending(),[])
            media_nonce=d.jobs.read_state('search:10')['nonce']
            d.handle(update(2,'1'))
            self.assertEqual(len(d.jobs.pending()),expected_jobs)
            if not error:self.assertEqual(indexer.queries,['Фильм','Film'])
            if expected_jobs:
                text=telegram.sent[-1][1]['text']
                for value in (title,'16.0','20','очеред'):
                    self.assertIn(value,text)
            elif not error:
                self.assertEqual(d.jobs.read_state('search:10')['stage'],'release')
                self.assertIn('Выбери',telegram.sent[-1][1]['text'])
            d=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow)
            d.handle(update(2,'1'))
            if expected_jobs:flow.choose(10,10,'media',media_nonce,0,d)
            self.assertEqual(len(d.jobs.pending()),expected_jobs)
            self.assertEqual(len(indexer.downloads),expected_jobs)


class RoleSearchTests(unittest.TestCase):
    def test_mother_autoqueues_acceptable_large_release(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':'Film','kind':'movie','year':2008}]}
        class Indexer:
            def search(self,query):return [{'title':'Film (2008) 1080p','seeders':20,'size':31*1024**3}]
            def download(self,row):return {'magnet':'magnet:?xt=urn:btih:'+'a'*40}
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(),Indexer(),role_for=lambda uid,dialog:'mother')
            d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d)
            flow(10,10,'1',d)
            self.assertEqual(len(d.jobs.pending()),1)

    def test_show_category_is_rejected_for_movie_and_results_limited_to_five(self):
        media={'title':'Film','kind':'movie','year':2008}
        wrong={'title':'Film (2008) 1080p','seeders':100,'size':15*1024**3,'categories':[{'id':5000}]}
        self.assertEqual(rank_releases([wrong],media),[])
        rows=[{'title':'Film (2008) 1080p '+str(i),'seeders':20,'size':15*1024**3} for i in range(8)]
        self.assertEqual(len(rank_releases(rows,media)),5)

    def test_multiple_candidate_images_are_one_numbered_rich_message(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':name,'kind':'movie','year':2008} for name in ('Film','Other')]}
        with tempfile.TemporaryDirectory() as tmp:
            telegram=Telegram();flow=SearchFlow(Resolver(),None,images=lambda q:'https://images.example/'+q.split()[0]+'.jpg')
            d=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d)
            self.assertEqual(len(telegram.sent),1)
            self.assertEqual(telegram.sent[0][0],'sendRichMessage')
            blocks=telegram.sent[0][1]['rich_message']['blocks']
            photos=[b['photo']['media'] for b in blocks if b['type']=='photo']
            self.assertEqual(photos,['https://images.example/Film.jpg','https://images.example/Other.jpg'])
            self.assertEqual(len(telegram.sent[0][1]['reply_markup']['inline_keyboard']),2)

    def test_known_matching_year_precedes_unknown_year_release(self):
        media={'title':'Film','kind':'movie','year':2008}
        rows=[{'title':'Film 1080p','seeders':200,'size':16*1024**3},
              {'title':'Film (2008) 1080p','seeders':20,'size':16*1024**3}]
        self.assertIn('(2008)',rank_releases(rows,media)[0]['title'])

    def test_flac_audio_in_real_video_is_not_mistaken_for_music(self):
        media={'title':'Film','kind':'movie','year':2008}
        row={'title':'Film (2008) BDRip 1080p FLAC','seeders':20,'size':16*1024**3,'categories':[{'id':2000}]}
        self.assertEqual(rank_releases([row],media),[row])

    def test_misclassified_pc_video_needs_identity_and_video_evidence(self):
        media={'title':'Film','kind':'movie','year':2008}
        def row(title,category=4000):return {'title':title,'seeders':20,'size':16*1024**3,'categories':[{'id':category}]}
        good=row('Film (2008) WEB-DL 1080p')
        self.assertEqual(rank_releases([good,row('Film 1080p'),row('Film (2008) game'),row('Film (2008) 1080p',3000)],media),[good])

    def test_search_failure_returns_working_retry_keyboard(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':'Film','kind':'movie','year':2008}]}
        class Indexer:
            def search(self,query):raise RuntimeError('offline')
        with tempfile.TemporaryDirectory() as tmp:
            telegram=Telegram();flow=SearchFlow(Resolver(),Indexer());d=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d); state=d.jobs.read_state('search:10')
            flow.choose(10,10,'media',state['nonce'],0,d)
            button=telegram.sent[-1][1]['reply_markup']['inline_keyboard'][0][0]
            self.assertEqual(button['callback_data'],'media:'+state['nonce']+':0')

    def test_queued_release_includes_known_capacity_and_season(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':'Film','kind':'show','season':2}]}
        class Indexer:
            def search(self,query):return [{'title':'Film S02 1080p','seeders':20,'size':16*1024**3}]
            def download(self,row):return {'magnet':'magnet:?xt=urn:btih:'+'a'*40}
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(),Indexer());d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d); flow(10,10,'1',d); flow(10,10,'1',d)
            payload=d.jobs.pending()[0]['payload']
            self.assertEqual(payload['size_bytes'],16*1024**3)
            self.assertEqual(payload['season'],2)
            self.assertEqual(payload['name'],'Film S02 1080p')

    def test_pc_video_with_custom_tracker_category_is_accepted(self):
        media={'title':'Film','kind':'movie','year':2008}
        row={'title':'Film (2008) WEB-DL 1080p','seeders':20,'size':16*1024**3,'categories':[{'id':4050},{'id':102000}]}
        self.assertEqual(rank_releases([row],media),[row])

    def test_structured_posters_use_identity_language_and_attribution(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':'Фильм','original_title':'Film','kind':'movie','year':2008}]}
        class Posters:
            ATTRIBUTION='TMDB attribution'
            def __init__(self):self.calls=[]
            def for_media(self,media,language):self.calls.append((media,language));return 'https://image.tmdb.org/t/p/w500/poster.jpg'
        for role,language in [('owner','en'),('mother','ru')]:
            with tempfile.TemporaryDirectory() as tmp:
                posters=Posters();telegram=Telegram();flow=SearchFlow(Resolver(),None,posters,role_for=lambda uid,d:role)
                d=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow);flow(10,10,'film',d)
                self.assertEqual(posters.calls[0][1],language)
                self.assertEqual(posters.calls[0][0]['year'],2008)
                self.assertIn('Постеры: TMDB',str(telegram.sent[-1]))

    def test_release_card_uses_verified_metadata_and_safe_compact_title(self):
        from bot.search import release_card
        row={'title':'Film <script> (2008) WEB-DL 1080p HEVC AC3 12 Mbps','size':16*1024**3,'seeders':20,'leechers':3,'publishDate':'2026-09-14T12:00:00Z'}
        card=release_card(1,row)
        self.assertIn('<b>1. WEB-DL · 1080p</b>',card)
        self.assertIn('12 Mbps',card);self.assertIn('Раздача: 14.09.2026',card)
        self.assertIn('&lt;script&gt;',card);self.assertNotIn('<script>',card)
        self.assertNotIn('2008</b>',card)
        plain=release_card(1,{'title':'Film (2008)','size':0,'seeders':1})
        self.assertNotIn('Раздача:',plain);self.assertNotIn('Mbps',plain)

    def test_release_choices_are_separate_paragraphs_with_informative_buttons(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':'Film','kind':'movie','year':2008}]}
        class Indexer:
            def search(self,query):return [{'title':'Film (2008) WEB-DL 1080p '+str(i),'seeders':20+i,'size':16*1024**3,'leechers':3} for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            telegram=Telegram();flow=SearchFlow(Resolver(),Indexer());d=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d);flow(10,10,'1',d)
            message=telegram.sent[-1][1]
            self.assertIn('\n\n<b>2.',message['text'])
            self.assertIn('<b>16.0 ГБ</b>',message['text'])
            buttons=message['reply_markup']['inline_keyboard']
            self.assertEqual(len(buttons),5)
            self.assertIn('1080p',buttons[0][0]['text']);self.assertIn('16.0 ГБ',buttons[0][0]['text']);self.assertIn('↑24',buttons[0][0]['text'])
            self.assertTrue(buttons[0][0]['text'].startswith('⬇ 1'))

    def test_unknown_release_size_is_omitted_for_agent_torrent_derivation(self):
        class Resolver:
            def identify(self,text,context):return {'candidates':[{'title':'Film','kind':'movie','year':2008}]}
        class Indexer:
            def search(self,query):return [{'title':'Film (2008) 1080p','seeders':20}]
            def download(self,row):return {'metainfo':'dGVzdA=='}
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(),Indexer());d=Dialog(Path(tmp),Telegram(),'owner','',lambda:{},search=flow)
            flow(10,10,'Film',d);flow(10,10,'1',d);flow(10,10,'1',d)
            self.assertNotIn('size_bytes',d.jobs.pending()[0]['payload'])
