import unittest
from bot.progress import progress_text
from bot.download_dashboard import render

class LivePeersTests(unittest.TestCase):
    def text(self, **extra):
        torrent = dict(name='Film', status=4, sizeWhenDone=1000,
                       leftUntilDone=500, percentDone=.5, **extra)
        return progress_text({'name':'Film'}, torrent, 100)[0]

    def test_local_tracker_zero_does_not_hide_live_senders(self):
        text = self.text(seeders=0, leechers=1, peersSendingToUs=3, peersConnected=4)
        self.assertIn('Передают вам: 3 · подключено: 4', text)
        self.assertNotIn('Раздают:', text)
        self.assertNotIn('скачивают:', text)
        dashboard = render([{'hash':'a'*40,'name':'Film','text':text,'snapshot_at':100}], now=100)[0]
        self.assertIn('Передают вам: 3 · подключено: 4', dashboard)

    def test_unknown_live_counts_do_not_use_old_search_counts(self):
        text = self.text(seeders=0, leechers=1, quality={'seeders':42,'leechers':5})
        self.assertIn('Участники: нет свежих данных', text)
        self.assertNotIn('Раздают:', text)

    def test_real_zero_remains_zero(self):
        self.assertIn('Передают вам: 0 · подключено: 0',
                      self.text(peersSendingToUs=0, peersConnected=0))

    def test_stale_dashboard_hides_live_peer_counts(self):
        text = self.text(peersSendingToUs=3, peersConnected=4)
        dashboard = render([{'hash':'a'*40,'name':'Film','text':text,'snapshot_at':100}], now=200)[0]
        self.assertNotIn('Передают вам:', dashboard)

if __name__ == '__main__': unittest.main()
