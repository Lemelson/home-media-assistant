import unittest
from unittest.mock import Mock,patch
from bot.movie_images import MovieImages

MEDIA={'title':'Мемуары гейши','original_title':'Memoirs of a Geisha','year':2005,'kind':'movie'}
def row(image,title='Мемуары гейши (2005)'):
    return {'title':title,'excerpt':title,'url':'https://example.com/film','image':'https://example.com/'+image}

class MovieImageTests(unittest.TestCase):
    def test_three_images_russian_then_english_then_second_russian_with_two_calls(self):
        exa=Mock();exa.search.side_effect=[[row('ru1.jpg'),row('ru2.jpg')],[row('en1.jpg','Memoirs of a Geisha (2005)')]]
        adapter=MovieImages(exa)
        result=adapter.for_media_gallery(MEDIA,limit=3)
        self.assertEqual(result,['https://example.com/ru1.jpg','https://example.com/en1.jpg','https://example.com/ru2.jpg'])
        self.assertEqual(exa.search.call_count,2)
        self.assertIn('русский',exa.search.call_args_list[0].args[0])
        self.assertIn('English',exa.search.call_args_list[1].args[0])
        result.clear()
        self.assertEqual(len(adapter.for_media_gallery(MEDIA)),3)
        self.assertEqual(exa.search.call_count,2)

    def test_one_image_stops_after_russian_search_and_can_expand_without_repeating(self):
        exa=Mock();exa.search.side_effect=[[row('ru1.jpg'),row('ru2.jpg')],[row('en1.jpg')]]
        adapter=MovieImages(exa)
        self.assertEqual(adapter.for_media_gallery(MEDIA,limit=1),['https://example.com/ru1.jpg'])
        self.assertEqual(exa.search.call_count,1)
        self.assertEqual(len(adapter.for_media_gallery(MEDIA,limit=3)),3)
        self.assertEqual(exa.search.call_count,2)

    def test_wrong_identity_year_duplicates_and_unusable_images_are_excluded(self):
        exa=Mock();exa.search.side_effect=[[
            row('wrong.jpg','Другой фильм (2005)'),row('remake.jpg','Мемуары гейши (2025)'),
            row('logo.png'),row('poster.webp'),row('ru.jpg'),row('ru.jpg')],[]]
        result=MovieImages(exa).for_media_gallery(MEDIA)
        self.assertEqual(result,['https://example.com/ru.jpg'])

    def test_provider_failure_and_missing_images_never_invents_url(self):
        exa=Mock();exa.search.side_effect=RuntimeError('private key')
        adapter=MovieImages(exa)
        self.assertEqual(adapter.for_media_gallery(MEDIA),[])
        self.assertEqual(adapter.for_media_gallery(MEDIA),[])
        self.assertEqual(exa.search.call_count,2)

    def test_cache_expires(self):
        exa=Mock();exa.search.return_value=[row('ru.jpg')]
        adapter=MovieImages(exa)
        with patch('bot.movie_images.time.monotonic',return_value=1):adapter.for_media_gallery(MEDIA,limit=1)
        with patch('bot.movie_images.time.monotonic',return_value=90000):adapter.for_media_gallery(MEDIA,limit=1)
        self.assertEqual(exa.search.call_count,2)

    def test_multiple_film_candidates_are_independent_and_unknown_year_requires_title(self):
        exa=Mock();exa.search.return_value=[row('wrong.jpg','Мемуарыгейши (2005)'),row('right.jpg')]
        adapter=MovieImages(exa)
        unknown={**MEDIA,'year':None}
        self.assertEqual(adapter.for_media_gallery(unknown,limit=1),['https://example.com/right.jpg'])
        other={'title':'Другой фильм','original_title':'Other','year':2008,'kind':'movie'}
        self.assertEqual(adapter.for_media_gallery(other,limit=1),[])
        self.assertEqual(exa.search.call_count,3)

    def test_one_russian_miss_can_use_english_without_retry_loop(self):
        exa=Mock();exa.search.side_effect=[[],[row('en.jpg','Memoirs of a Geisha (2005)')]]
        adapter=MovieImages(exa)
        self.assertEqual(adapter.for_media_gallery(MEDIA,limit=1),['https://example.com/en.jpg'])
        self.assertEqual(adapter.for_media_gallery(MEDIA,limit=3),['https://example.com/en.jpg'])
        self.assertEqual(exa.search.call_count,2)
