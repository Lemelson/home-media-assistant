import json
import unittest
from unittest.mock import MagicMock, patch
from bot.transport import TelegramAPI, APIError

class PersistentTransportTests(unittest.TestCase):
    def connection(self):
        conn=MagicMock()
        response=conn.getresponse.return_value
        response.status=200
        response.read.return_value=json.dumps({'ok':True,'result':{'id':1}}).encode()
        return conn

    def test_reuses_connection_for_successful_calls(self):
        conn=self.connection()
        with patch('http.client.HTTPSConnection',return_value=conn) as factory:
            api=TelegramAPI('test',persistent=True)
            self.assertEqual(api.call('getMe'),{'id':1})
            api.call('getMe')
            self.assertEqual(factory.call_count,1)
            self.assertEqual(conn.request.call_count,2)

    def test_uncertain_send_is_not_retried_and_next_call_reconnects(self):
        failed=self.connection();failed.request.side_effect=OSError('secret URL')
        fresh=self.connection()
        with patch('http.client.HTTPSConnection',side_effect=[failed,fresh]):
            api=TelegramAPI('test',persistent=True)
            with self.assertRaisesRegex(APIError,'^telegram_request_failed:sendMessage$'):
                api.call('sendMessage',chat_id=1,text='hello')
            self.assertEqual(failed.request.call_count,1)
            api.call('getMe')
            self.assertEqual(fresh.request.call_count,1)
