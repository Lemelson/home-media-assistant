import json
import unittest
from unittest.mock import Mock, patch

from bot.providers import DeepSeek
from bot.web_search import ExaSearch


class ExaTests(unittest.TestCase):
    @patch('bot.web_search.request_json')
    def test_bounded_cached_search_uses_original_and_correction_not_assistant_guess(self, request):
        request.return_value = {'results': [{'title':'A Big Bold Beautiful Journey (2025)',
            'url':'https://example.com/movie', 'highlights':['Film 2025'], 'image':'https://example.com/poster.jpg'}]}
        adapter = ExaSearch('secret')
        context = [{'role':'user','content':'Большое смелое красивое путешествие'},
                   {'role':'assistant','content':'Тарзан?' }]
        first = adapter.search('2025', context)
        first[0]['title']='mutated'
        self.assertNotEqual(adapter.search('2025',context)[0]['title'],'mutated')
        self.assertEqual(request.call_count,1)
        payload = request.call_args.args[1]
        self.assertIn('Большое смелое красивое путешествие',payload['query'])
        self.assertIn('2025',payload['query'])
        self.assertNotIn('Тарзан',payload['query'])
        self.assertEqual(payload['numResults'],5)
        self.assertEqual(payload['contents'],{'highlights':True})

    @patch('bot.providers.request_json')
    def test_grounded_one_model_call_with_valid_source_images(self, request):
        source = {'id':'s1','title':'A Big Bold Beautiful Journey (2025)', 'url':'https://example.com/movie',
                  'excerpt':'A Big Bold Beautiful Journey 2025', 'image':'https://example.com/poster.jpg'}
        search = Mock(); search.search.return_value=[source]
        candidate = {'title':'Большое смелое красивое путешествие','original_title':'A Big Bold Beautiful Journey',
                     'year':2025,'kind':'movie','source_ids':['s1','fake']}
        request.return_value={'choices':[{'message':{'content':json.dumps({'action':'find','reply':'Нашел','candidates':[candidate]})}}]}
        result=DeepSeek('secret',web_search=search).identify('Большое смелое красивое путешествие',[])
        self.assertEqual(request.call_count,1)
        self.assertEqual(result['candidates'][0]['source_images'],['https://example.com/poster.jpg'])
        self.assertEqual(result['candidates'][0]['sources'],[{'title':source['title'],'url':source['url']}])

    @patch('bot.providers.request_json')
    def test_unknown_source_or_no_evidence_never_returns_guessed_candidate(self, request):
        search=Mock(); search.search.return_value=[]
        candidate={'title':'Тарзан','year':1999,'kind':'movie','source_ids':['s9']}
        request.return_value={'choices':[{'message':{'content':json.dumps({'action':'find','reply':'Это Тарзан','candidates':[candidate]})}}]}
        result=DeepSeek('secret',web_search=search).identify('Фильм про мальчика',[])
        self.assertEqual(result['candidates'],[])
        self.assertNotIn('Тарзан',result['reply'])
        request.assert_not_called()

    @patch('bot.providers.request_json')
    def test_control_request_skips_web(self, request):
        search=Mock()
        request.return_value={'choices':[{'message':{'content':json.dumps({'action':'pause','reply':'','target':'Фильм','candidates':[]})}}]}
        self.assertEqual(DeepSeek('secret',web_search=search).identify('Поставь фильм на паузу',[])['action'],'pause')
        search.search.assert_not_called()

    @patch('bot.providers.request_json')
    def test_source_for_different_title_or_year_is_rejected(self, request):
        search=Mock(); search.search.return_value=[{'id':'s1','title':'Tarzan (1999)', 'excerpt':'Tarzan 1999',
             'url':'https://example.com/tarzan','image':'https://example.com/t.jpg'}]
        candidate={'title':'Большое путешествие','original_title':'The Big Trip','year':2019,'kind':'movie','source_ids':['s1']}
        request.return_value={'choices':[{'message':{'content':json.dumps({'action':'find','reply':'Нашел','candidates':[candidate]})}}]}
        result=DeepSeek('secret',web_search=search).identify('Большое путешествие',[])
        self.assertEqual(result['candidates'],[])

    @patch('bot.providers.request_json')
    def test_search_failure_does_not_leak_secrets_or_unverified_reply(self, request):
        search=Mock(); search.search.side_effect=RuntimeError('secret')
        request.return_value={'choices':[{'message':{'content':json.dumps({'action':'reply','reply':'Это Тарзан','candidates':[]})}}]}
        result=DeepSeek('secret',web_search=search).identify('фильм',[])
        self.assertNotIn('Тарзан',result['reply'])
        request.assert_not_called()
        self.assertNotIn('secret',result['reply'])

    @patch('bot.web_search.request_json')
    def test_parallel_different_requests_do_not_wait_for_network_lock(self, request):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        barrier=threading.Barrier(2)
        def response(*args,**kwargs):
            barrier.wait(timeout=2)
            return {'results':[]}
        request.side_effect=response
        adapter=ExaSearch('secret')
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(adapter.search,'first',[])
            two=pool.submit(adapter.search,'second',[])
            self.assertEqual(one.result(timeout=3),[])
            self.assertEqual(two.result(timeout=3),[])

    @patch('bot.web_search.request_json')
    def test_image_filter_rejects_obvious_logos_placeholders_and_tiny_thumbnails(self, request):
        images=[
            'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6c/Wiki_letter_w.svg/40px-Wiki_letter_w.svg.png',
            'https://example.com/images/site-logo.png',
            'https://example.com/placeholder.jpg',
            'https://example.com/movie.jpg?w=40',
            'https://images.example.com/poster/123/s718/example.jpg']
        request.return_value={'results':[{'title':'Film','url':'https://example.com/'+str(i),'image':url} for i,url in enumerate(images)]}
        rows=ExaSearch('secret').search('Film',[])
        self.assertEqual([r['image'] for r in rows],[None,None,None,None,images[-1]])

    @patch('bot.web_search.urllib.request.install_opener')
    @patch('bot.web_search.urllib.request.build_opener')
    @patch('bot.web_search.request_json')
    def test_proxy_is_explicit_per_client_and_does_not_change_direct_calls(self, direct, build, install):
        import io
        build.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"results":[]}')
        direct.return_value={'results':[]}
        proxy=ExaSearch('secret',proxy='http://127.0.0.1:18888')
        self.assertEqual(proxy.search('proxy film',[]),[])
        self.assertEqual(build.call_args.args[0].proxies,{'https':'http://127.0.0.1:18888'})
        request=build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.exa.ai/search')
        self.assertEqual(request.get_header('Authorization'),'Bearer secret')
        self.assertEqual(ExaSearch('secret').search('direct film',[]),[])
        direct.assert_called_once()
        install.assert_not_called()

    def test_proxy_config_rejects_nonlocal_or_credential_bearing_endpoints(self):
        for value in ('https://remote.example:443','http://user:secret@127.0.0.1:18888','http://127.0.0.1:18888/path'):
            with self.assertRaises(ValueError):ExaSearch('secret',proxy=value)
