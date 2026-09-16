import tempfile
import unittest
from pathlib import Path
from bot.dialog import Dialog
from bot.search import SearchFlow
from tests.test_dialog import Telegram

class SearchStageTests(unittest.TestCase):
    def test_stage_visible_before_model_and_image_work(self):
        telegram=Telegram()
        class Resolver:
            def identify_with_progress(self,text,context,progress):
                progress('model',{'model':'deepseek/test','median_seconds':3,'count':4})
                self_outer.assertTrue(any('deepseek/test' in p.get('text','') for _,p in telegram.sent))
                progress('resolved',{'seconds':2})
                return {'candidates':[{'title':'Film','kind':'movie','year':2000}]}
        def images(query):
            self.assertTrue(any('постер' in p.get('text','').lower() for _,p in telegram.sent))
            return None
        self_outer=self
        with tempfile.TemporaryDirectory() as tmp:
            flow=SearchFlow(Resolver(),None,images)
            dialog=Dialog(Path(tmp),telegram,'owner','',lambda:{},search=flow)
            flow(10,10,'film',dialog,receipt_id=99)
            self.assertTrue(any(p.get('reply_markup',{}).get('inline_keyboard') for _,p in telegram.sent))
