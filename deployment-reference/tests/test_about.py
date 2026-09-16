import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from bot.dialog import Dialog
from bot.posters import TMDBPosters


class AboutTests(unittest.TestCase):
    def test_about_shows_tmdb_notice_and_official_preview_without_provider_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Mock()
            telegram.call.return_value = {}
            dialog = Dialog(tmp, telegram, 'owner', '', lambda: {},
                            search=SimpleNamespace(images=TMDBPosters('secret')))
            dialog.handle({'update_id': 1, 'message': {'from': {'id': 10, 'username': 'owner'},
                'chat': {'id': 10, 'type': 'private'}, 'text': '/about'}})
            payload = telegram.call.call_args.kwargs
            self.assertIn(TMDBPosters.ATTRIBUTION, payload['text'])
            self.assertEqual(payload['link_preview_options']['url'], TMDBPosters.SOURCE_URL)
            self.assertNotIn('secret', str(payload))

    def test_about_does_not_credit_unconfigured_tmdb(self):
        with tempfile.TemporaryDirectory() as tmp:
            telegram = Mock()
            telegram.call.return_value = {}
            dialog = Dialog(tmp, telegram, 'owner', '', lambda: {})
            dialog.handle({'update_id': 2, 'message': {'from': {'id': 10, 'username': 'owner'},
                'chat': {'id': 10, 'type': 'private'}, 'text': '/about'}})
            self.assertIn('Домашний кинотеатр', telegram.call.call_args.kwargs['text'])
            self.assertNotIn('TMDB', telegram.call.call_args.kwargs['text'])
