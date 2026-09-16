import unittest
from bot.release_matching import rejection_reason,search_queries,additional_search_queries
from bot.search import release_card

class SeriesYearTests(unittest.TestCase):
 def test_season_year_is_not_series_premiere_year(self):
  for name,year,season_year in [('Black Mirror',2011,2013),('Fallout',2024,2025),('Breaking Bad',2008,2009),('South Park',1997,2000),('Game of Thrones',2011,2012)]:
   media={'title':name,'original_title':name,'year':year,'kind':'show','season':2}
   row={'title':f'{name} / S02 [ {season_year}, WEB-DL 1080p]','seeders':10,'categories':[{'id':5040}]}
   self.assertIsNone(rejection_reason(row,media))
   self.assertEqual(search_queries(media),[name])
   self.assertTrue(all(str(year) not in q for q in additional_search_queries(media)))

class DetailsTests(unittest.TestCase):
 def test_video_bitrate_does_not_use_audio_or_overall(self):
  from bot.release_details import parse_details
  text='''Общий битрейт: 12 Мбит/с
Видео: MPEG-4 AVC, 1920x1080, 23.976 fps, 8 500 Кбит/с
Аудио #1: Русский, AC3, 640 Кбит/с
Аудио #2: English, DTS, 1509 Кбит/с'''
  details=parse_details(text)
  self.assertEqual(details['height'],1080)
  self.assertAlmostEqual(details['video_mbps'],8.5)
  self.assertEqual(details['languages'],['Русский','Английский'])
 def test_mediainfo_sections_and_missing_video_rate(self):
  from bot.release_details import parse_details
  details=parse_details('Video\nWidth : 3 840 pixels\nHeight : 2 160 pixels\nBit rate : 22.4 Mb/s\nAudio\nBit rate : 640 kb/s\nLanguage : Russian')
  self.assertAlmostEqual(details['video_mbps'],22.4)
  self.assertEqual(details['height'],2160)
  self.assertNotIn('video_mbps',parse_details('Видео: H.264, 1280x720\nАудио: AC3 640 kbps'))
 def test_card_uses_details_not_long_genres(self):
  row={'title':'Black Mirror / Season 1 [драма, фантастика, WEB-DL]','seeders':3,'size':1024**3,'details':{'height':1080,'width':1920,'video_mbps':8.5,'languages':['Русский','Английский']}}
  card=release_card(1,row)
  self.assertIn('Full HD',card)
  self.assertIn('8.5 Мбит/с',card)
  self.assertNotIn('фантастика',card)
  self.assertIn('Русский',card)

class DetailsSafetyTests(unittest.TestCase):
 def test_inline_audio_rate_is_not_video_rate(self):
  from bot.release_details import parse_details
  self.assertNotIn('video_mbps',parse_details('Видео: H.264 1920x1080; Аудио: Русский AC3 640 Кбит/с'))
 def test_old_same_named_show_is_not_new_remake(self):
  m={'title':'Сегун','original_title':'Shogun','year':2024,'verified_series_year':2024,'season':1,'kind':'show'}
  r={'title':'Сегун / Shogun / S01 [1980, BDRip 720p]','seeders':10}
  self.assertEqual(rejection_reason(r,m),'older_series')
 def test_only_first_post_is_parsed(self):
  from bot.release_details import post_text
  html='<div class="post_body"><b>Видео:</b> H264<br>1280x720<div>Аудио: English</div></div><div class="post_body">Видео: 4K, 500 Мбит/с</div>'
  text=post_text(html)
  self.assertIn('1280x720',text);self.assertNotIn('500',text)

class RealLayoutTests(unittest.TestCase):
 def test_mediainfo_format_and_duration_do_not_end_video_section(self):
  from bot.release_details import parse_details
  d=parse_details('Видео\nФормат : AVC\nПродолжительность : 1 ч.\nБитрейт : 8 773 Кбит/сек\nШирина : 1 920 пикселей\nВысота : 800 пикселей\nАудио RUS: AC3, 640 kbps')
  self.assertEqual(d['height'],800);self.assertAlmostEqual(d['video_mbps'],8.773)
  self.assertEqual(d['languages'],['Русский'])
 def test_cropped_video_is_still_full_hd_or_4k(self):
  from bot.release_catalog import quality_label
  for w,h,label in [(1920,800,'Full HD'),(1918,802,'Full HD'),(3840,1600,'4К'),(1280,536,'HD'),(1248,520,'HD'),(7680,4320,'8К')]:
   self.assertIn(label,quality_label({'details':{'width':w,'height':h}}))

class EnrichmentFlowTests(unittest.TestCase):
 def test_late_details_do_not_restore_buttons_after_download_choice(self):
  import tempfile,time
  from bot.dialog import Dialog
  from bot.search import SearchFlow
  from bot.search_sessions import SearchSessions
  from test_multifilm import Telegram
  class Details:
   def cached(self,row):return None
   def submit(self,key,rows,current,complete):self.current=current;self.complete=complete
  class Indexer:
   def download(self,row):return {'magnet':'magnet:?xt=urn:btih:'+'a'*40}
  with tempfile.TemporaryDirectory() as tmp:
   details=Details();tg=Telegram();flow=SearchFlow(None,Indexer(),details=details);d=Dialog(tmp,tg,'owner','',lambda:{},search=flow)
   row={'title':'Film (2000) WEB-DL','size':1000,'seeders':3,'infoUrl':'https://tracker.example.invalid/forum/viewtopic.php?t=123'}
   state={'thread_id':'aaaaaaaaaa','nonce':'aaaaaaaaaa','stage':'release','selected':{'title':'Film','kind':'movie'},'releases':[row],'expires':time.time()+3600}
   ss=SearchSessions(d.jobs,10);ss.save(state);flow.catalog(10,10,state,d)
   original=ss.load(state['thread_id'])['choice_message_id']
   details.complete({row['infoUrl']:{'height':1080,'width':1920,'video_mbps':8.5}})
   self.assertEqual(ss.load(state['thread_id'])['choice_message_id'],original)
   self.assertIn('8.5 Мбит/с',tg.calls[-1][1]['text'])
   flow.choose(10,10,'release',state['nonce'],0,d)
   before=len(tg.calls);details.complete({row['infoUrl']:{'height':720}})
   self.assertEqual(len(tg.calls),before);self.assertFalse(details.current())
   self.assertEqual(ss.load(state['thread_id'])['stage'],'queued')

class TopicURLTests(unittest.TestCase):
 def test_untrusted_topic_urls_are_rejected(self):
  from bot.release_details import topic_url
  for url in ['http://127.0.0.1/admin','https://tracker.example.invalid.evil.com/forum/viewtopic.php?t=123','https://tracker.example.invalid/forum/viewtopic.php?t=123&t=124','https://tracker.example.invalid/forum/login.php?t=123']:
   self.assertIsNone(topic_url({'infoUrl':url}))

class MixedResolutionTests(unittest.TestCase):
 def test_different_episode_dimensions_are_preserved(self):
  from bot.release_details import parse_details
  from bot.release_catalog import quality_label
  d=parse_details('Видео: AVC, 1248x520 / 5 и 6 серии — 1280x720, ~3 331 kbps')
  self.assertEqual(d['resolutions'],[[1248,520],[1280,720]])
  self.assertIn('HD',quality_label({'details':d}))
  d=parse_details('Видео: 1280x720, 4 Mbps\nВидео: 1920x1080, 8 Mbps')
  self.assertIn('Разные',quality_label({'details':d}))
