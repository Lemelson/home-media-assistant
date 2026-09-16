import tempfile
import unittest
from pathlib import Path
from bot.model_metrics import ModelMetrics

class MetricsTests(unittest.TestCase):
    def test_bounds_rows_and_separates_model_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics=ModelMetrics(Path(tmp)/'metrics.db',limit=3)
            for seconds in (1,2,3,4):
                metrics.record('model-a','high',seconds,{'prompt_tokens':10,'completion_tokens':20,'cost':.001})
            metrics.record('model-b','low',80,{},error='provider_request_failed')
            self.assertEqual(len(metrics.recent()),3)
            self.assertEqual(metrics.summary('model-a','high')['median_seconds'],3.5)
            self.assertIsNone(metrics.summary('model-b','low')['median_seconds'])
            self.assertEqual(ModelMetrics(metrics.path,limit=3).recent()[0]['error'],'provider_request_failed')
            self.assertEqual(metrics.path.stat().st_mode & 0o777,0o600)

    def test_missing_usage_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics=ModelMetrics(Path(tmp)/'metrics.db')
            metrics.record('model','high',2,{})
            row=metrics.recent()[0]
            self.assertIsNone(row['cost_usd'])
            self.assertIsNone(row['prompt_tokens'])
