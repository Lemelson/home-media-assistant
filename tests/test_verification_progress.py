import unittest
from bot.progress import progress_text
class VerificationProgressTests(unittest.TestCase):
 def test_verification_has_its_own_progress_and_no_download_eta(self):
  text,_=progress_text({'name':'Film'},dict(status=2,percentDone=.99,totalSize=1000,leftUntilDone=10,recheckProgress=.42),100)
  self.assertIn('42.0% проверки',text)
  self.assertIn('99.0% загрузки',text)
  self.assertNotIn('Осталось:',text)
