import tempfile
import unittest
from pathlib import Path
from bot.access import AccessRegistry

class PublicAccessTests(unittest.TestCase):
    def test_numeric_allowlist_rejects_username_impersonation_and_groups(self):
        with tempfile.TemporaryDirectory() as d:
            access = AccessRegistry(Path(d)/'access.db', '', '', owner_id=101, member_id=202)
            self.assertEqual(access.check(303,'owner','private'),'denied')
            self.assertEqual(access.check(101,None,'group'),'denied')
            self.assertEqual(access.check(101,None,'private'),'owner')
            self.assertEqual(access.check(202,None,'private'),'mother')
            self.assertEqual(access.check(303,None,'private'),'denied')
    def test_removed_member_loses_access_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'access.db'
            access=AccessRegistry(path,'','',owner_id=101,member_id=202)
            self.assertEqual(access.check(202,None,'private'),'mother')
            access=AccessRegistry(path,'','',owner_id=101)
            self.assertEqual(access.check(202,None,'private'),'denied')

class PublicConfigTests(unittest.TestCase):
    def test_defaults_do_not_enable_external_services(self):
        from bot.config import settings
        data=settings({'TELEGRAM_BOT_TOKEN':'test-token','MEDIA_AGENT_TOKEN':'x'*40,'OWNER_TELEGRAM_ID':'101'})
        self.assertFalse(data['images'])
        self.assertFalse(data['voice'])
        self.assertEqual(data['agent_url'],'http://127.0.0.1:18742')
    def test_startup_rejects_missing_owner_and_short_shared_secret(self):
        from bot.config import settings
        for env in ({},{'TELEGRAM_BOT_TOKEN':'test-token','MEDIA_AGENT_TOKEN':'short','OWNER_TELEGRAM_ID':'101'}):
            with self.assertRaises(ValueError): settings(env)
    def test_rejects_remote_plaintext_agent(self):
        from bot.config import settings
        with self.assertRaises(ValueError):
            settings({'TELEGRAM_BOT_TOKEN':'test-token','MEDIA_AGENT_TOKEN':'x'*40,'OWNER_TELEGRAM_ID':'101','MEDIA_AGENT_URL':'http://example.com:18742'})

class PublicTelegramTests(unittest.TestCase):
    def test_text_messages_disable_link_previews_by_default(self):
        import json
        from unittest.mock import patch, MagicMock
        from bot.transport import TelegramAPI
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"ok":true,"result":{}}'
        with patch('bot.transport.urllib.request.urlopen',return_value=response) as request:
            TelegramAPI('test-token').call('sendMessage',chat_id=101,text='https://example.com')
        payload=json.loads(request.call_args.args[0].data)
        self.assertTrue(payload['link_preview_options']['is_disabled'])

class PublicReferenceTests(unittest.TestCase):
    def test_ai_requires_an_explicit_model(self):
        from bot.config import settings
        with self.assertRaisesRegex(ValueError, 'OPENROUTER_MODEL'):
            settings({'TELEGRAM_BOT_TOKEN':'test-token','MEDIA_AGENT_TOKEN':'x'*40,
                      'OWNER_TELEGRAM_ID':'101','OPENROUTER_API_KEY':'example'})

    def test_disabled_images_do_not_fetch_or_send_grounded_posters(self):
        from unittest.mock import Mock
        from bot.dialog import Dialog
        from bot.search import SearchFlow
        from test_multifilm import Telegram
        class Resolver:
            def identify(self, *args):
                return {'candidates':[{'title':'Example Movie','kind':'movie','source_images':['https://example.invalid/poster.jpg']}]}
        with tempfile.TemporaryDirectory() as tmp:
            images=Mock(); tg=Telegram()
            flow=SearchFlow(Resolver(),None,images=images,allow_remote_images=False)
            dialog=Dialog(tmp,tg,'','',lambda:{},search=flow,owner_id=101)
            flow(101,101,'Example Movie',dialog)
            images.assert_not_called()
            self.assertFalse(any(method in ('sendPhoto','sendMediaGroup','sendRichMessage') for method,payload in tg.calls))
