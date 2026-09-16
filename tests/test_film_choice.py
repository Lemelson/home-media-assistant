import unittest
from bot.providers import validate_resolution

class FilmChoiceTests(unittest.TestCase):
    def test_show_without_season_does_not_discard_movie_alternative(self):
        result=validate_resolution({'action':'find','reply':'Есть фильм и сериал.','candidates':[
            {'title':'Линкольн для адвоката','original_title':'The Lincoln Lawyer','kind':'show','year':2022},
            {'title':'Линкольн для адвоката','original_title':'The Lincoln Lawyer','kind':'movie','year':2011}]})
        self.assertEqual(result['action'],'find')
        self.assertEqual([(c['kind'],c['year']) for c in result['candidates']],[('show',2022),('movie',2011)])
        self.assertNotIn('Какой сезон',result['reply'])

class SeasonFlowTests(unittest.TestCase):
    def test_season_is_asked_only_after_show_selection(self):
        import tempfile
        from unittest.mock import Mock
        from bot.dialog import Dialog
        from bot.search import SearchFlow
        from test_multifilm import Telegram
        show={'title':'Линкольн для адвоката','original_title':'The Lincoln Lawyer','kind':'show','year':2022,'season':None}
        movie={**show,'kind':'movie','year':2011}
        resolver=Mock();resolver.identify.return_value={'action':'find','candidates':[movie,show]}
        indexer=Mock();indexer.search.return_value=[{'title':'Линкольн для адвоката 2022 S01 1080p','size':1000,'seeders':3}]
        with tempfile.TemporaryDirectory() as tmp:
            tg=Telegram();flow=SearchFlow(resolver,indexer);d=Dialog(tmp,tg,'owner','',lambda:{},search=flow)
            flow(10,10,'Линкольн для адвоката',d)
            self.assertIn('фильм',tg.calls[-1][1]['text'])
            self.assertIn('сериал',tg.calls[-1][1]['text'])
            self.assertNotIn('Какой сезон',tg.calls[-1][1]['text'])
            state=d.jobs.read_state('search:10')
            flow.choose(10,10,'media',state['nonce'],1,d)
            indexer.search.assert_not_called()
            self.assertEqual(d.jobs.read_state('search:10')['stage'],'season')
            self.assertIn('2022',tg.calls[-1][1]['text'])
            flow(10,10,'1',d)
            self.assertEqual(resolver.identify.call_count,1)
            self.assertEqual(d.jobs.read_state('search:10')['selected']['season'],1)
            self.assertTrue(indexer.search.called)
