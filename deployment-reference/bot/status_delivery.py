"""Retry the latest durable dashboard without requesting remote status."""
import logging
import time
from bot.download_dashboard import publish

class DashboardDelivery:
    def __init__(self, dialog):
        self.dialog = dialog

    def step(self, now=None):
        now = time.time() if now is None else now
        for key in self.dialog.jobs.read_states('download-dashboard:'):
            try:
                publish(self.dialog, int(key.split(':')[1]), now,
                        cleanup=False, wait=False)
            except Exception as error:
                logging.warning('dashboard_delivery_retry type=%s', type(error).__name__)
