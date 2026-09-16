import unittest
from bot.download_dashboard import render


class PeerVisibilityTests(unittest.TestCase):
    def test_only_fewer_than_three_sending_peers_are_shown(self):
        for sending in (0, 1, 2, 3, 9, 10, 20, 30):
            with self.subTest(sending=sending):
                line = 'Передают вам: %d · подключено: 12' % sending
                state = dict(hash='a'*40, name='Film', active=True,
                             text='<b>⬇️ Загружается</b>\n'+line+'\n1 ГБ из 2 ГБ\n████░░')
                text, markup, _ = render([state], now=100)
                self.assertEqual(line in text, sending < 3)
                self.assertIn('1 ГБ из 2 ГБ', text)
                self.assertEqual(markup['inline_keyboard'][0][0]['callback_data'], 'priority:'+'a'*40)

    def test_unknown_peer_count_is_hidden(self):
        text, _, _ = render([dict(hash='a',name='Film',active=True,
                                 text='Участники: нет свежих данных')], now=100)
        self.assertNotIn('Участники:', text)
