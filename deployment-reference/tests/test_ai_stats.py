import tempfile
import unittest
from types import SimpleNamespace
from bot.dialog import Dialog
from bot.model_metrics import ModelMetrics
from tests.test_dialog import Telegram

class AIStatsTests(unittest.TestCase):
    def test_owner_sees_ledger_summary_without_calling_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics=ModelMetrics(tmp+'/metrics.db');metrics.record('test-model','high',2.5,{'cost':.01})
            telegram=Telegram();flow=SimpleNamespace(resolver=SimpleNamespace(metrics=metrics))
            dialog=Dialog(tmp,telegram,'owner','',lambda:{},search=flow)
            dialog.handle({'update_id':1,'message':{'from':{'id':10,'username':'owner'},'chat':{'id':10,'type':'private'},'text':'/ai_stats'}})
            text=telegram.sent[-1][1]['text']
            self.assertIn('test-model',text);self.assertIn('2.5',text);self.assertIn('0.010000',text)
