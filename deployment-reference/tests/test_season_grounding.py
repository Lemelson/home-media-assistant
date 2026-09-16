import unittest
from bot.providers import validate_resolution
from bot.web_search import ground_resolution

class SeasonGroundingTests(unittest.TestCase):
    def resolve(self, title, excerpt, year=2011, season=2, kind='show'):
        raw={'action':'find','candidates':[{'title':'Чёрное зеркало','original_title':'Black Mirror',
            'year':year,'kind':kind,'season':season,'source_ids':['s1']}]}
        evidence=[{'id':'s1','title':title,'excerpt':excerpt,'url':'https://example.com/show','image':None}]
        return ground_resolution(validate_resolution(raw),raw,evidence)

    def test_season_page_does_not_need_series_premiere_year(self):
        result=self.resolve('Чёрное зеркало — 2 сезон (2013)', 'Все серии второго сезона Black Mirror.')
        self.assertEqual(result['action'],'find')
        self.assertEqual(result['candidates'][0]['season'],2)

    def test_wrong_season_page_cannot_override_request(self):
        self.assertEqual(self.resolve('Чёрное зеркало — 3 сезон (2016)','Black Mirror')['candidates'],[])

    def test_unrelated_title_is_still_rejected(self):
        self.assertEqual(self.resolve('Другой сериал — 2 сезон (2013)','Other show')['candidates'],[])

    def test_movie_remake_year_is_still_enforced(self):
        self.assertEqual(self.resolve('Чёрное зеркало (2013)','Black Mirror',season=None,kind='movie')['candidates'],[])

    def test_unverified_premiere_year_is_not_claimed_as_verified(self):
        candidate=self.resolve('Black Mirror S02 (2013)','Second season')['candidates'][0]
        self.assertIsNone(candidate['year'])

    def test_matching_year_does_not_make_wrong_season_valid(self):
        self.assertEqual(self.resolve('Black Mirror S03 (2011)','Third season')['candidates'],[])

    def test_unknown_year_still_requires_correct_season(self):
        self.assertEqual(self.resolve('Black Mirror S03','Third season',year=None)['candidates'],[])

    def test_matching_series_page_preserves_verified_year(self):
        candidate=self.resolve('Black Mirror (2011)','Television series')['candidates'][0]
        self.assertEqual(candidate['year'],2011)

    def test_year_embedded_in_longer_number_is_not_evidence(self):
        self.assertEqual(self.resolve('Black Mirror','Reference 20112345')['candidates'],[])

    def test_synthetic_season_response_preserves_unverified_year(self):
        import json
        from pathlib import Path
        fixture=json.loads((Path(__file__).parent/'fixtures/season_grounding.json').read_text())
        raw=fixture['raw']
        result=ground_resolution(validate_resolution(raw),raw,fixture['evidence'])
        self.assertEqual(result['action'],'find')
        self.assertEqual(result['candidates'][0]['season'],2)
        self.assertIsNone(result['candidates'][0]['year'])
