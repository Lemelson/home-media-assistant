"""Integration contract: grounded Exa images work without a separate image provider."""
import tempfile
import unittest
from pathlib import Path
from bot.dialog import Dialog
from bot.search import SearchFlow


class SourceGalleryTests(unittest.TestCase):
    def run_flow(self, images, broken=False):
        class Resolver:
            def identify(self,text,context):
                return {'action':'find','reply':'Нашёл фильм.', 'candidates':[{
                    'title':'Большое смелое красивое путешествие',
                    'original_title':'A Big Bold Beautiful Journey','year':2025,'kind':'movie',
                    'sources':[{'title':'Film 2025','url':'https://example.com/movie'}],
                    'source_images':images}]}
        class Telegram:
            def __init__(self):self.calls=[]
            def call(self,method,**payload):
                self.calls.append((method,payload))
                if broken and method=='sendRichMessage':raise RuntimeError('remote image not found')
                return {'message_id':payload.get('message_id',100+len(self.calls))}
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        telegram=Telegram()
        flow=SearchFlow(Resolver(),None,images=None)
        dialog=Dialog(Path(tmp.name),telegram,'owner','',lambda:{},search=flow)
        flow(10,10,'Большое смелое красивое путешествие',dialog,message_id=50,receipt_id=83)
        return telegram.calls,dialog.jobs.read_state('search:10')

    def assert_candidate_button(self,payload,state):
        buttons=payload['reply_markup']['inline_keyboard']
        self.assertEqual(len(buttons),1)
        self.assertEqual(buttons[0][0]['callback_data'],'media:'+state['nonce']+':0')
        self.assertIn('Большое смелое красивое путешествие',buttons[0][0]['text'])

    def test_source_images_rich_card_preserves_button_and_finishes_receipt(self):
        photos=['https://example.com/poster.jpg','https://example.com/still.jpg']
        calls,state=self.run_flow(photos)
        rich=[p for m,p in calls if m=='sendRichMessage']
        self.assertEqual(len(rich),1)
        self.assertEqual([b['photo']['media'] for b in rich[0]['rich_message']['blocks'] if b['type']=='photo'],photos[:1])
        self.assert_candidate_button(rich[0],state)
        edits=[p for m,p in calls if m=='editMessageText']
        self.assertEqual(len(edits),1)
        self.assertEqual(edits[0]['message_id'],83)
        self.assertIn('Нашёл варианты',edits[0]['text'])
        self.assertNotIn('loading_message_id',state)

    def test_missing_images_uses_finished_text_receipt_with_same_button(self):
        calls,state=self.run_flow([])
        self.assertFalse(any(m=='sendRichMessage' for m,p in calls))
        edits=[p for m,p in calls if m=='editMessageText']
        self.assertEqual(len(edits),1)
        self.assertEqual(edits[0]['message_id'],83)
        self.assertIn('A Big Bold Beautiful Journey',edits[0]['text'])
        self.assert_candidate_button(edits[0],state)
        self.assertNotIn('loading_message_id',state)

    def test_remote_image_failure_falls_back_to_text_without_losing_button(self):
        calls,state=self.run_flow(['https://example.com/broken.jpg'],broken=True)
        rich=[p for m,p in calls if m=='sendRichMessage']
        edits=[p for m,p in calls if m=='editMessageText']
        self.assertEqual(len(rich),1)
        self.assertEqual(len(edits),1)
        self.assertEqual(edits[0]['message_id'],83)
        self.assertEqual(edits[0]['reply_markup'],rich[0]['reply_markup'])
        self.assert_candidate_button(edits[0],state)
        self.assertIn('A Big Bold Beautiful Journey',edits[0]['text'])
        self.assertNotIn('loading_message_id',state)
