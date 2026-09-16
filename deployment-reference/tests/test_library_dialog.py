import unittest
from bot.library_dialog import matching_items


class LibraryMatchingTests(unittest.TestCase):
    def test_explicit_season_is_not_confused_with_episode_number(self):
        items = [{'name': 'Show.S01E02.mkv', 'show': 'Show', 'kind': 'episode', 'season': 1, 'episode': 2},
                 {'name': 'Show S02', 'show': 'Show', 'kind': 'season', 'season': 2}]
        self.assertEqual(matching_items(items, 'Show сезон 2'), [items[1]])
        self.assertEqual(matching_items(items, 'Show сезон 1 серия 2'), [items[0]])
