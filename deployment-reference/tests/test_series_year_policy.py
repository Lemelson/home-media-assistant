import unittest
from bot.providers import validate_resolution
from bot.web_search import ground_resolution
from bot.release_matching import rejection_reason

class SeriesYearPolicyTests(unittest.TestCase):
    def test_guessed_late_year_does_not_hide_matching_season(self):
        # Synthetic release labels: exercise both earlier and later model years.
        for name,season,release_year in [('Black Mirror',2,2013),('Breaking Bad',3,2010),('Game of Thrones',4,2014),('Sherlock',2,2012),('The Office',1,2005)]:
            for guessed_year in (release_year-5,release_year,release_year+5,None):
                with self.subTest(name=name,year=guessed_year):
                    media={'title':name,'original_title':name,'kind':'show','season':season,'year':guessed_year}
                    row={'title':f'{name} / S{season:02d} [{release_year}, WEB-DL 1080p]','seeders':5}
                    self.assertIsNone(rejection_reason(row,media))

    def test_confirmed_remake_premiere_still_rejects_old_series(self):
        media={'title':'Shogun','kind':'show','season':1,'year':2024,'verified_series_year':2024}
        row={'title':'Shogun / S01 [1980, BDRip 720p]','seeders':5}
        self.assertEqual(rejection_reason(row,media),'older_series')

    def ground(self,title,excerpt,year):
        raw={'action':'find','candidates':[{'title':'Sherlock','kind':'show','season':2,'year':year,'source_ids':['s1']}]}
        evidence=[{'id':'s1','title':title,'excerpt':excerpt,'url':'https://example.com/show','image':None}]
        return ground_resolution(validate_resolution(raw),raw,evidence)['candidates'][0]

    def test_season_year_is_not_promoted_to_confirmed_premiere(self):
        c=self.ground('Sherlock — Season 2 (2012)','TV series, season 2',2012)
        self.assertIsNone(c['year'])
        self.assertNotIn('verified_series_year',c)

    def test_general_series_source_can_confirm_premiere(self):
        c=self.ground('Sherlock (TV series, 2010)','British television series',2010)
        self.assertEqual(c.get('verified_series_year'),2010)

    def test_model_cannot_self_certify_year(self):
        raw={'action':'find','candidates':[{'title':'Sherlock','kind':'show','season':2,'year':2012,'verified_series_year':2012}]}
        self.assertNotIn('verified_series_year',validate_resolution(raw)['candidates'][0])

    def test_wrong_season_title_and_movie_year_remain_blocked(self):
        m={'title':'Sherlock','kind':'show','season':2,'year':2020}
        self.assertEqual(rejection_reason({'title':'Sherlock / S03 [2014, WEB-DL]','seeders':5},m),'different_season')
        self.assertEqual(rejection_reason({'title':'Other / S02 [2012, WEB-DL]','seeders':5},m),'different_title')
        self.assertEqual(rejection_reason({'title':'Film (1980) WEB-DL','seeders':5},{'title':'Film','kind':'movie','year':2024}),'different_year')

    def test_complete_grounding_to_release_path_across_series(self):
        for name,season,season_year in [('Black Mirror',2,2013),('Breaking Bad',3,2010),('Game of Thrones',4,2014),('Sherlock',2,2012),('The Office',1,2005)]:
            for guessed_year in (season_year-5,season_year,season_year+5,None):
                with self.subTest(name=name,year=guessed_year):
                    raw={'action':'find','candidates':[{'title':name,'kind':'show','season':season,'year':guessed_year,'source_ids':['s1']}]}
                    title=f'{name} / S{season:02d} [{season_year}, WEB-DL 1080p]'
                    source={'id':'s1','title':title,'excerpt':'Television series','url':'https://example.com/season','image':None}
                    candidate=ground_resolution(validate_resolution(raw),raw,[source])['candidates'][0]
                    self.assertIsNone(candidate['year'])
                    self.assertIsNone(rejection_reason({'title':title,'seeders':5},candidate))

    def test_grounded_premiere_protects_against_old_same_title(self):
        c=self.ground('Sherlock (TV series, 2010)','British television series',2010)
        self.assertEqual(rejection_reason({'title':'Sherlock / S02 [1980, WEB-DL]','seeders':5},c),'older_series')
