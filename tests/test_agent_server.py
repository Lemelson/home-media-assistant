import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from mac_agent.server import make_handler


class AgentHTTPTests(unittest.TestCase):
    def test_auth_is_required_before_status_or_commands_are_processed(self):
        class Controller:
            calls = 0
            def status(self):
                self.calls += 1
                return {'ok': True, 'disk_ok': True, 'torrents': []}
        controller = Controller()
        server = HTTPServer(('127.0.0.1', 0), make_handler(controller, 'test-secret'))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = 'http://127.0.0.1:%s/status' % server.server_port
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(url)
            self.assertEqual(denied.exception.code, 401)
            denied.exception.close()
            self.assertEqual(controller.calls, 0)
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': 'Bearer test-secret'})) as response:
                self.assertTrue(json.load(response)['disk_ok'])
            self.assertEqual(controller.calls, 1)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
