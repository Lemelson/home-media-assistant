import base64
import io
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from bot.providers import NoRedirect, ProviderError, Prowlarr


class ProwlarrDownloadTests(unittest.TestCase):
    proxy='http://127.0.0.1:9696/1/download?link=opaque&file=Film'
    magnet='magnet:?xt=urn:btih:'+'a'*40

    def test_null_magnet_downloads_torrent_from_proxy(self):
        raw=b'd4:infod4:name4:testee'
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=raw
        with patch('bot.providers.urllib.request.build_opener',return_value=opener):
            result=Prowlarr('test-key').download({'magnetUrl':None,'downloadUrl':self.proxy})
        self.assertEqual(base64.b64decode(result['metainfo']),raw)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,self.proxy)
        self.assertEqual(request.get_header('X-api-key'),'test-key')

    def test_proxy_magnet_redirect_is_returned_without_following(self):
        opener=MagicMock()
        opener.open.side_effect=urllib.error.HTTPError(self.proxy,301,'Moved',{'Location':self.magnet},io.BytesIO())
        with patch('bot.providers.urllib.request.build_opener',return_value=opener):
            result=Prowlarr('test-key').download({'magnetUrl':self.proxy,'downloadUrl':None})
        self.assertEqual(result,{'magnet':self.magnet})
        self.assertEqual(opener.open.call_count,1)
        self.assertEqual(opener.open.call_args.args[0].full_url,self.proxy)

    def test_http_redirect_stays_blocked(self):
        opener=MagicMock()
        opener.open.side_effect=urllib.error.HTTPError(self.proxy,301,'Moved',{'Location':'https://example.invalid/file'},io.BytesIO())
        with patch('bot.providers.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(ProviderError):
                Prowlarr('test-key').download({'downloadUrl':self.proxy})
        self.assertEqual(opener.open.call_count,1)
        self.assertIsNone(NoRedirect().redirect_request(None,None,301,'Moved',{},'https://example.invalid/file'))

    def test_foreign_url_rejected_before_request(self):
        with patch('bot.providers.urllib.request.build_opener') as build:
            with self.assertRaises(ProviderError):
                Prowlarr('test-key').download({'downloadUrl':'https://example.invalid/file'})
            build.assert_not_called()

    def test_direct_magnet_requires_no_request(self):
        with patch('bot.providers.urllib.request.build_opener') as build:
            self.assertEqual(Prowlarr('test-key').download({'magnetUrl':self.magnet}),{'magnet':self.magnet})
            build.assert_not_called()

class ProwlarrConfigurationTests(unittest.TestCase):
    def test_no_indexer_fails_before_search_request(self):
        with patch('bot.providers.request_json', return_value=[]) as request:
            with self.assertRaises(ProviderError):
                Prowlarr('test-key').search('Example')
            self.assertEqual(request.call_count,1)
            self.assertTrue(request.call_args.args[0].endswith('/api/v1/indexer'))
