import tempfile
import unittest
from unittest.mock import patch

from bot.dialog import Dialog
from bot.providers import ProviderError
from bot.search import SearchFlow
from bot.search_sessions import SearchSessions
from test_multifilm import Telegram


class Resolver:
    def identify(self, text, context):
        return {'candidates': [{'title': text, 'year': 1981, 'kind': 'movie'}]}


class RecoveringIndexer:
    def __init__(self):
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        if len(self.calls) == 1:
            raise ProviderError('provider_request_failed')
        return [{'title': query + ' BDRip 1080p', 'seeders': 20, 'size': 1024**3}]


class SearchRetryTests(unittest.TestCase):
    def test_network_failure_retries_and_updates_the_same_film_card(self):
        indexer = RecoveringIndexer()
        with tempfile.TemporaryDirectory() as tmp, patch('time.sleep'):
            telegram = Telegram()
            dialog = Dialog(tmp, telegram, 'owner', '', lambda: {}, search=SearchFlow(Resolver(), indexer))
            dialog.search(10, 10, 'Мефисто', dialog)
            nonce = dialog.jobs.read_state('search:10')['nonce']
            dialog.search.choose(10, 10, 'media', nonce, 0, dialog)
            state = SearchSessions(dialog.jobs, 10).choice(nonce)
            self.assertEqual(state['stage'], 'release')
            texts = [p['text'] for _, p in telegram.calls if 'text' in p]
            self.assertTrue(any('Попытка 1' in t for t in texts))
            self.assertTrue(any('Попытка 2' in t and 'Повторяю' in t for t in texts))
            self.assertTrue(any('соединени' in t.lower() for t in texts))
            progress = [p for m, p in telegram.calls if m == 'editMessageText' and 'Попытка' in p.get('text', '')]
            self.assertEqual({p['message_id'] for p in progress}, {state['status_message_id']})

class Clock:
    def __init__(self): self.now = 0; self.waits = []
    def monotonic(self): return self.now
    def time(self): return 1_000_000 + self.now
    def sleep(self, seconds): self.waits.append(seconds); self.now += seconds


class RetryPolicyTests(unittest.TestCase):
    def test_four_failures_finish_with_correct_count_and_no_duplicate_queries_after_success(self):
        from bot.release_search import find_releases
        clock = Clock(); progress = []
        class Indexer:
            def search(self, query): raise ProviderError('provider_request_failed')
        with patch('bot.release_search.time', clock):
            result = find_releases(Indexer(), {'title': 'Мефисто', 'year': 1981, 'kind': 'movie'}, lambda *a: progress.append(a))
        self.assertEqual(result.attempts, 4)
        self.assertTrue(result.incomplete)
        self.assertEqual(clock.waits, [10, 20, 30])
        self.assertEqual(clock.now, 60)

    def test_backoff_is_respected_and_recovery_returns_results(self):
        from bot.release_search import find_releases
        clock = Clock(); calls = []
        class Indexer:
            def search(self, query):
                calls.append(clock.now)
                if len(calls) == 1: raise ProviderError('indexers_unavailable', retry_at=clock.time()+40)
                return [{'title': 'Мефисто (1981)', 'seeders': 20}]
        with patch('bot.release_search.time', clock):
            result = find_releases(Indexer(), {'title': 'Мефисто', 'year': 1981, 'kind': 'movie'}, lambda *a: None)
        self.assertFalse(result.incomplete)
        self.assertEqual(calls[:2], [0, 40])

    def test_backoff_past_budget_does_not_issue_another_request(self):
        from bot.release_search import find_releases
        clock = Clock(); calls = []
        class Indexer:
            def search(self, query):
                calls.append(query)
                raise ProviderError('indexers_unavailable', retry_at=clock.time()+300)
        with patch('bot.release_search.time', clock):
            result = find_releases(Indexer(), {'title': 'Мефисто', 'kind': 'movie'}, lambda *a: None)
        self.assertEqual(clock.now, 120)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(calls), 1)

    def test_slow_attempts_share_one_two_minute_budget(self):
        from bot.release_search import find_releases
        clock = Clock(); deadlines = []
        class Indexer:
            def search_until(self, query, deadline):
                deadlines.append(deadline)
                clock.now = deadline
                raise ProviderError('search_timeout')
        with patch('bot.release_search.time', clock):
            result = find_releases(Indexer(), {'title': 'Мефисто', 'kind': 'movie'}, lambda *a: None)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(deadlines, [45, 100])
        self.assertEqual(clock.now, 120)

    def test_partial_success_survives_later_variant_failure(self):
        from bot.release_search import find_releases
        clock = Clock(); calls = []
        good = {'title': 'Мефисто / Mephisto (1981)', 'seeders': 20}
        class Indexer:
            def search(self, query):
                calls.append(query)
                if len(calls) == 1: return [good]
                raise ProviderError('provider_request_failed')
        with patch('bot.release_search.time', clock):
            result = find_releases(Indexer(), {'title': 'Мефисто', 'original_title': 'Mephisto', 'year': 1981, 'kind': 'movie'}, lambda *a: None)
        self.assertTrue(result.incomplete)
        self.assertEqual(result.rows, [good])
        self.assertEqual(calls.count(calls[0]), 1)

    def test_successful_empty_search_and_auth_failure_are_not_retried(self):
        from bot.release_search import find_releases
        for response in ([], ProviderError('provider_auth_failed')):
            clock = Clock()
            class Indexer:
                def search(self, query):
                    if isinstance(response, Exception): raise response
                    return response
            with patch('bot.release_search.time', clock):
                result = find_releases(Indexer(), {'title': 'Film', 'kind': 'movie'}, lambda *a: None)
            self.assertEqual(result.attempts, 1)
            self.assertEqual(clock.waits, [])


class OldCardTests(unittest.TestCase):
    def test_failed_card_retries_original_film_after_other_requests_and_restart(self):
        class Indexer:
            failed = True
            calls = []
            def search(self, query):
                self.calls.append(query)
                if self.failed: raise ProviderError('provider_request_failed')
                return [{'title': query+' BDRip 1080p', 'seeders': 20}]
        indexer = Indexer(); clock = Clock()
        with tempfile.TemporaryDirectory() as tmp, patch('bot.release_search.time', clock):
            tg = Telegram(); dialog = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(Resolver(), indexer))
            dialog.search(10, 10, 'Мефисто', dialog)
            nonce = dialog.jobs.read_state('search:10')['nonce']
            dialog.search.choose(10, 10, 'media', nonce, 0, dialog)
            last = tg.calls[-1][1]
            self.assertIn('Попыток: 4', last['text'])
            retry = last['reply_markup']['inline_keyboard'][0][0]['callback_data']
            original = SearchSessions(dialog.jobs, 10).choice(nonce)
            card_id = original['status_message_id']
            for title in ('Alien', 'Matrix', 'Arrival'): dialog.search(10, 10, title, dialog)
            self.assertFalse(any(m == 'editMessageReplyMarkup' and p['message_id'] == card_id for m, p in tg.calls))
            indexer.failed = False; indexer.calls = []
            # Reload persistent sessions in a new Dialog, simulating a service restart a day later.
            import time
            tomorrow = time.time() + 86400
            dialog = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(Resolver(), indexer))
            with patch('bot.search_sessions.time.time', return_value=tomorrow):
                dialog.callback(10, 10, retry, 'retry-old-film')
            current = SearchSessions(dialog.jobs, 10).load(original['thread_id'])
            self.assertEqual(current['selected']['title'], 'Мефисто')
            self.assertEqual(current['stage'], 'release')
            self.assertTrue(all('Мефисто' in q for q in indexer.calls))
            self.assertEqual(current['status_message_id'], card_id)


class ProviderRetryTests(unittest.TestCase):
    def test_provider_exposes_backoff_expiry(self):
        import datetime, time
        from bot.providers import Prowlarr
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=40)
        with patch('bot.providers.request_json', side_effect=[[{'id': 1, 'enable': True}], [{'indexerId': 1, 'disabledTill': expires.isoformat()}]]):
            with self.assertRaises(ProviderError) as caught: Prowlarr('test').search('Film')
        self.assertAlmostEqual(caught.exception.retry_at, expires.timestamp(), places=3)

    def test_search_hard_deadline_even_when_transport_stalls(self):
        import threading, time
        from bot.providers import Prowlarr
        gate = threading.Event(); started = threading.Event()
        def stuck(*args, **kwargs): started.set(); gate.wait(2); return []
        try:
            with patch('bot.providers.request_json', side_effect=stuck):
                api = Prowlarr('test'); begin = time.monotonic()
                with self.assertRaises(ProviderError): api.search_until('Film', begin+.05)
                self.assertTrue(started.is_set())
                self.assertLess(time.monotonic()-begin, .5)
        finally: gate.set()


class DuplicateRetryTests(unittest.TestCase):
    def test_clicks_during_search_are_coalesced_but_later_retry_is_accepted(self):
        import threading
        from bot.inbox import Inbox
        from test_inbox import update
        started = threading.Event(); finish = threading.Event(); calls = []
        def handle(row):
            calls.append(row['update_id']); started.set(); finish.wait(2)
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(tmp, handle)
            try:
                inbox.enqueue(update(1, callback='media:aaaaaaaaaa:0')); inbox.pump()
                self.assertTrue(started.wait(1))
                inbox.enqueue(update(2, callback='media:aaaaaaaaaa:0'))
                inbox.enqueue(update(3, callback='media:aaaaaaaaaa:0'))
                finish.set(); self.assertTrue(inbox.wait_idle(2))
                self.assertEqual(calls, [1])
                inbox.enqueue(update(4, callback='media:aaaaaaaaaa:0')); inbox.pump()
                self.assertTrue(inbox.wait_idle(2))
                self.assertEqual(calls, [1, 4])
            finally: finish.set(); inbox.stop()

class IntegratedOutageTests(unittest.TestCase):
    def test_real_provider_failure_backoff_recovery_and_dialog_results(self):
        import datetime
        from bot.providers import Prowlarr
        clock = Clock(); search_times = []
        expiry = datetime.datetime.fromtimestamp(clock.time()+40, datetime.timezone.utc).isoformat()
        def request(url, *args, **kwargs):
            if url.endswith('/indexer'): return [{'id': 1, 'enable': True}]
            if url.endswith('/indexerstatus'):
                return [{'indexerId': 1, 'disabledTill': expiry}] if search_times and clock.now < 40 else []
            search_times.append(clock.now)
            if len(search_times) == 1: return []
            return [{'title': 'Мефисто / Mephisto (1981) BDRip 1080p', 'seeders': 20}]
        with tempfile.TemporaryDirectory() as tmp, patch('bot.release_search.time', clock), patch('bot.providers.time', clock), patch('bot.providers.request_json', side_effect=request):
            tg = Telegram(); dialog = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(Resolver(), Prowlarr('test')))
            dialog.search(10, 10, 'Мефисто', dialog)
            nonce = dialog.jobs.read_state('search:10')['nonce']
            dialog.search.choose(10, 10, 'media', nonce, 0, dialog)
            state = SearchSessions(dialog.jobs, 10).choice(nonce)
            self.assertEqual(state['stage'], 'release')
            self.assertEqual(state['search_attempts'], 2)
            self.assertEqual(search_times[:2], [0, 40])
            self.assertIn('Мефисто', state['releases'][0]['title'])
            self.assertTrue(any('Попытка 2' in p.get('text', '') for _, p in tg.calls))

    def test_partial_results_are_visible_in_final_catalog(self):
        class Indexer:
            calls = 0
            def search(self, query):
                self.calls += 1
                if self.calls == 1: return [{'title': 'Мефисто (1981) BDRip 1080p', 'seeders': 20}]
                raise ProviderError('provider_request_failed')
        class TranslatedResolver:
            def identify(self, text, context):
                return {'candidates': [{'title': 'Мефисто', 'original_title': 'Mephisto', 'kind': 'movie', 'year': 1981}]}
        with tempfile.TemporaryDirectory() as tmp, patch('bot.release_search.time', Clock()):
            tg = Telegram(); dialog = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(TranslatedResolver(), Indexer()))
            dialog.search(10, 10, 'Мефисто', dialog)
            nonce = dialog.jobs.read_state('search:10')['nonce']
            dialog.search.choose(10, 10, 'media', nonce, 0, dialog)
            state = SearchSessions(dialog.jobs, 10).choice(nonce)
            self.assertEqual(state['stage'], 'release')
            self.assertEqual(len(state['releases']), 1)
            self.assertIn('Часть запросов не завершилась', tg.calls[-1][1]['text'])

    def test_direct_concurrent_click_returns_without_a_second_search(self):
        import threading
        started = threading.Event(); finish = threading.Event(); calls = []
        class Indexer:
            def search(self, query):
                calls.append(query); started.set(); finish.wait(2)
                raise ProviderError('provider_auth_failed')
        with tempfile.TemporaryDirectory() as tmp:
            tg = Telegram(); dialog = Dialog(tmp, tg, 'owner', '', lambda: {}, search=SearchFlow(Resolver(), Indexer()))
            dialog.search(10, 10, 'Мефисто', dialog)
            nonce = dialog.jobs.read_state('search:10')['nonce']
            worker = threading.Thread(target=dialog.search.choose, args=(10, 10, 'media', nonce, 0, dialog))
            worker.start()
            try:
                self.assertTrue(started.wait(1))
                dialog.search.choose(10, 10, 'media', nonce, 0, dialog)
                self.assertEqual(len(calls), 1)
            finally: finish.set(); worker.join(2)

    def test_coalescing_preserves_different_films_and_different_users(self):
        from bot.inbox import Inbox
        from test_inbox import update
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Inbox(tmp, lambda row: calls.append(row['update_id']))
            try:
                inbox.enqueue(update(1, callback='media:aaaaaaaaaa:0'))
                inbox.enqueue(update(2, callback='media:aaaaaaaaaa:0'))
                inbox.enqueue(update(3, callback='media:bbbbbbbbbb:0'))
                inbox.enqueue(update(4, uid=20, callback='media:aaaaaaaaaa:0'))
                inbox.pump(); self.assertTrue(inbox.wait_idle(2))
                self.assertEqual(set(calls), {1, 3, 4})
            finally: inbox.stop()

    def test_http_auth_is_not_retried_but_server_error_is_transient(self):
        import urllib.error
        from bot.providers import request_json
        for status, reason in ((401, 'provider_auth_failed'), (403, 'provider_auth_failed'), (400, 'provider_request_rejected'), (429, 'provider_request_failed'), (502, 'provider_request_failed')):
            with patch('bot.providers.urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://example.invalid/?secret=hidden', status, 'failed', {}, None)):
                with self.assertRaises(ProviderError) as caught: request_json('https://example.invalid', None, {})
                self.assertEqual(str(caught.exception), reason)
                self.assertNotIn('secret', str(caught.exception))
