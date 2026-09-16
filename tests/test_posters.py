import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from bot.posters import TMDBPosters


class TMDBPosterTests(unittest.TestCase):
    @patch('bot.posters.request_json')
    def test_matching_remake_year_and_russian_poster(self, request):
        request.side_effect = [
            {'results': [{'id': 1, 'title': 'Солярис', 'release_date': '2002-01-01'},
                         {'id': 2, 'title': 'Солярис', 'release_date': '1972-03-20'}]},
            {'posters': [{'file_path': '/english.jpg', 'iso_639_1': 'en'},
                         {'file_path': '/russian.jpg', 'iso_639_1': 'ru'}]}]
        adapter = TMDBPosters('secret')
        self.assertEqual(adapter.for_media({'title': 'Солярис', 'year': 1972, 'kind': 'movie'}),
                         'https://image.tmdb.org/t/p/w500/russian.jpg')
        self.assertIn('/movie/2/images', request.call_args.args[0])
        self.assertEqual(request.call_args.args[2], {'Authorization': 'Bearer secret'})

    @patch('bot.posters.request_json')
    def test_selects_exact_title_among_other_films(self, request):
        request.side_effect = [{'results': [
            {'id': 1, 'title': 'Солярис возвращается', 'release_date': '1972-01-01'},
            {'id': 2, 'title': 'Солярис', 'release_date': '1972-03-20'}]},
            {'posters': [{'file_path': '/correct.jpg', 'iso_639_1': None}]}]
        self.assertTrue(TMDBPosters('secret').image('Солярис 1972 poster').endswith('/correct.jpg'))

    @patch('bot.posters.request_json')
    def test_wrong_movie_or_ambiguous_remake_returns_none(self, request):
        adapter = TMDBPosters('secret')
        request.return_value = {'results': [{'id': 1, 'title': 'Другой фильм', 'release_date': '1972-01-01'}]}
        self.assertIsNone(adapter.image('Солярис 1972 poster'))
        request.return_value = {'results': [{'id': 1, 'title': 'Солярис', 'release_date': '1972-01-01'},
                                              {'id': 2, 'title': 'Солярис', 'release_date': '2002-01-01'}]}
        self.assertIsNone(adapter.image('Солярис poster'))

    @patch('bot.posters.request_json')
    def test_show_uses_tv_and_english_preference(self, request):
        request.side_effect = [{'results': [{'id': 3, 'name': 'Тед Лассо', 'first_air_date': '2020-08-14'}]},
                              {'posters': [{'file_path': '/ru.jpg', 'iso_639_1': 'ru'},
                                           {'file_path': '/en.jpg', 'iso_639_1': 'en'}]}]
        poster = TMDBPosters('secret').for_media({'title': 'Тед Лассо', 'kind': 'show', 'year': 2020}, 'en')
        self.assertTrue(poster.endswith('/en.jpg'))
        self.assertIn('/search/tv?', request.call_args_list[0].args[0])

    @patch('bot.posters.request_json')
    def test_cached_result_expires_and_cache_is_bounded(self, request):
        request.side_effect = lambda url, *args, **kwargs: ({'posters': [{'file_path': '/ok.jpg', 'iso_639_1': 'ru'}]}
            if '/images?' in url else {'results': [{'id': 1, 'title': parse_qs(urlsplit(url).query)['query'][0]}]})
        adapter = TMDBPosters('secret')
        with patch('bot.posters.time.monotonic', return_value=100):
            self.assertEqual(adapter.image('Фильм poster'), 'https://image.tmdb.org/t/p/w500/ok.jpg')
            self.assertEqual(adapter.image('Фильм poster'), 'https://image.tmdb.org/t/p/w500/ok.jpg')
            self.assertEqual(request.call_count, 2)
            for number in range(65):adapter.image(f'Фильм {number} poster')
        before = request.call_count
        with patch('bot.posters.time.monotonic', return_value=101):adapter.image('Фильм poster')
        self.assertEqual(request.call_count, before + 2)
        with patch('bot.posters.time.monotonic', return_value=90000):adapter.image('Фильм poster')
        self.assertEqual(request.call_count, before + 4)

    @patch('bot.posters.request_json')
    def test_provider_failure_is_optional_and_does_not_expose_key(self, request):
        request.side_effect = RuntimeError('sensitive-url?api_key=secret')
        self.assertIsNone(TMDBPosters('secret', bearer=False).image('Солярис 1972 poster'))
        self.assertEqual(parse_qs(urlsplit(request.call_args.args[0]).query)['api_key'], ['secret'])
        self.assertEqual(request.call_args.args[2], {})

    @patch('bot.posters.request_json')
    def test_gallery_has_preferred_poster_and_unique_backdrops_for_exact_identity(self, request):
        request.side_effect = [
            {'results': [{'id': 7, 'title': 'Фильм', 'release_date': '2025-01-01'}]},
            {'posters': [{'file_path': '/en.jpg', 'iso_639_1': 'en'},
                         {'file_path': '/ru.jpg', 'iso_639_1': 'ru'}],
             'backdrops': [{'file_path': '/scene1.jpg', 'iso_639_1': None},
                           {'file_path': '/scene1.jpg', 'iso_639_1': None},
                           {'file_path': '/scene2.jpg', 'iso_639_1': None},
                           {'file_path': '/scene3.jpg', 'iso_639_1': None},
                           {'file_path': '//evil.test/a.jpg', 'iso_639_1': None}]}]
        adapter = TMDBPosters('secret')
        media = {'title': 'Фильм', 'year': 2025, 'kind': 'movie'}
        gallery = adapter.for_media_gallery(media)
        self.assertEqual(gallery, ['https://image.tmdb.org/t/p/w500/ru.jpg',
                                  'https://image.tmdb.org/t/p/w780/scene1.jpg',
                                  'https://image.tmdb.org/t/p/w780/scene2.jpg'])
        self.assertEqual(adapter.for_media(media), gallery[0])
        gallery.clear()
        self.assertEqual(len(adapter.for_media_gallery(media)), 3)
        self.assertEqual(request.call_count, 2)

    @patch('bot.posters.request_json')
    def test_gallery_never_uses_images_for_mismatched_title(self, request):
        request.return_value = {'results': [{'id': 7, 'title': 'Другой фильм', 'release_date': '2025-01-01'}]}
        self.assertEqual(TMDBPosters('secret').for_media_gallery({'title': 'Фильм', 'year': 2025}), [])
        self.assertEqual(request.call_count, 1)
