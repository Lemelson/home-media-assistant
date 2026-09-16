import tempfile
import unittest
from pathlib import Path
from bot.jobs import JobStore
from bot.media_labels import decorate,film_card

class LabelTests(unittest.TestCase):
    def test_existing_obscure_filename_uses_saved_download_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=JobStore(Path(tmp)/'db')
            j=store.enqueue('old',1,{'action':'add','name':'Мемуары гейши / Memoirs of a Geisha [2005, США, мелодрама, драма, BDRip 1080p] Dub + Original Eng'})
            store.finish(j,{'ok':True,'hash':'a'*40,'name':'hns-mog.mkv'})
            item=decorate(store,{'name':'hns-mog.mkv','torrent_hash':'a'*40})
            self.assertEqual(item['name'],'Мемуары гейши (2005)')
            self.assertEqual(item['media']['original_title'],'Memoirs of a Geisha')
            self.assertEqual(item['quality']['resolution'],'1080p')
            self.assertEqual(item['quality']['audio'],'Dub')

    def test_metadata_from_confirmation_survives_result_and_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=JobStore(Path(tmp)/'db')
            media={'title':'Ускользающая красота','original_title':'Stealing Beauty','year':1996,'kind':'movie'}
            quality={'resolution':'1080p','audio':'MVO','seeders':54,'leechers':4}
            j=store.enqueue('new',1,{'action':'add','media':media,'quality':quality})
            store.finish(j,{'ok':True,'hash':'a'*40,'name':'file.mkv'})
            for field in ('torrent_hash','hashString','hash'):
                row=decorate(store,{'name':'file.mkv',field:'a'*40})
                self.assertEqual(row['name'],'Ускользающая красота (1996)')
                self.assertEqual(row['quality'],quality)
            text=film_card(media,quality,8*1024**3,54)
            self.assertIn('MVO',text)
            self.assertIn('скачивают: 4',text)
            self.assertNotIn('file.mkv',text)
