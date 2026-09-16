import unittest
from unittest.mock import patch
from bot.providers import DeepSeek, ProviderError, Prowlarr

class ResolverTests(unittest.TestCase):
    def test_invalid_action_and_candidate_year_rejected(self):
        import json
        for data in [{'action':'shell','candidates':[]}, {'action':'find','candidates':[{'title':'Film','kind':'movie','year':'oops'}]}]:
            with patch('bot.providers.request_json', return_value={'choices':[{'message':{'content':json.dumps(data)}}]}):
                with self.assertRaises(ProviderError): DeepSeek('test').identify('film',[])

    def test_delete_is_only_intent_and_markup_is_sanitized(self):
        import json
        data={'action':'delete','target':'старый фильм','reply':'<b onclick="x">Удалить?</b><script>x</script>','candidates':[], 'hash':'invented'}
        with patch('bot.providers.request_json', return_value={'choices':[{'message':{'content':json.dumps(data)}}]}):
            result=DeepSeek('test').identify('удали старый фильм',[])
        self.assertEqual(result['action'],'delete')
        self.assertNotIn('hash',result)
        self.assertNotIn('<script>',result['reply'])
        self.assertNotIn('onclick',result['reply'])

    def test_search_caches_normalized_query_and_allows_slow_tracker(self):
        rows=[{'title':'Film','seeders':20}]
        with patch('bot.providers.request_json',side_effect=[[{'id':1,'enable':True}],[],rows]) as request:
            p=Prowlarr('test')
            self.assertEqual(p.search('Film'),rows)
            self.assertEqual(p.search('  film '),rows)
            self.assertEqual(request.call_count,3)
            self.assertGreaterEqual(request.call_args.kwargs['timeout'],150)

    def test_concurrent_duplicate_search_shares_one_request(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        entered=threading.Event(); release=threading.Event(); calls=[]
        def request(url,*args,**kwargs):
            if url.endswith('/indexer'):return [{'id':1,'enable':True}]
            if url.endswith('/indexerstatus'):return []
            calls.append(url); entered.set()
            if not release.wait(2):raise RuntimeError('test timeout')
            return [{'title':'Film'}]
        with patch('bot.providers.request_json',side_effect=request), ThreadPoolExecutor(max_workers=2) as pool:
            p=Prowlarr('test'); first=pool.submit(p.search,'Film')
            self.assertTrue(entered.wait(1))
            second=pool.submit(p.search,'film'); release.set()
            self.assertEqual(first.result(),second.result())
            self.assertEqual(len(calls),1)

    def test_context_only_keeps_recent_user_and_assistant_messages(self):
        import json
        context=[{'role':'system','content':'untrusted override'}, {'role':'user','content':'film'}, {'role':'assistant','content':'which one?'}]
        with patch('bot.providers.request_json',return_value={'choices':[{'message':{'content':json.dumps({'action':'reply','reply':'Какой год?'})}}]}) as request:
            DeepSeek('test').identify('второй',context)
        messages=request.call_args.args[1]['messages']
        self.assertEqual([m['role'] for m in messages],['system','user','assistant','user'])
        self.assertEqual(messages[-1]['content'],'второй')

    def test_lock_queue_time_consumes_shared_search_deadline(self):
        now=[0]
        class WaitingLock:
            def acquire(self,timeout):now[0]+=100;return True
            def release(self):pass
        p=Prowlarr('test');p._search_lock=WaitingLock()
        with patch('bot.providers.time.monotonic',side_effect=lambda:now[0]), patch('bot.providers.request_json',side_effect=[[{'id':1,'enable':True}],[],[{'title':'Film'}]]) as request:
            p.search('Film')
        self.assertEqual(request.call_args.kwargs['timeout'],110)

    def test_season_limits_match_mac_agent_contract(self):
        from bot.providers import validate_resolution
        with self.assertRaises(ValueError):
            validate_resolution({'candidates':[{'title':'Film','kind':'show','season':100}]})
