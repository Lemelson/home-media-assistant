import tempfile
import unittest
from unittest.mock import patch
from bot.providers import DeepSeek,ProviderError
from bot.model_metrics import ModelMetrics

class ModelStagesTests(unittest.TestCase):
    def test_reports_model_stage_before_network_and_records_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics=ModelMetrics(tmp+'/metrics.db');stages=[]
            resolver=DeepSeek('test',metrics=metrics)
            def request(*args,**kwargs):
                self.assertEqual(stages[-1][0],'model')
                return {'choices':[{'message':{'content':'{"reply":"Уточни год","candidates":[]}'}}],
                        'usage':{'prompt_tokens':12,'completion_tokens':9}}
            with patch('bot.providers.request_json',side_effect=request):
                resolver.identify_with_progress('film',[],lambda *args:stages.append(args))
            self.assertEqual(metrics.recent()[0]['prompt_tokens'],12)
            self.assertEqual(stages[-1][0],'resolved')

    def test_invalid_model_response_is_recorded_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics=ModelMetrics(tmp+'/metrics.db');resolver=DeepSeek('test',metrics=metrics)
            with patch('bot.providers.request_json',return_value={'choices':[]}):
                with self.assertRaises(ProviderError):resolver.identify('film',[])
            self.assertEqual(metrics.recent()[0]['error'],'invalid_model_response')
