"""Read-only capacity estimate for the media volume's complete download queue."""
import shutil
from pathlib import Path


def collect(root, torrents, known, headroom):
    free = shutil.disk_usage(root).free
    remaining = rate = unknown = 0
    for torrent in torrents:
        directory = torrent.get('downloadDir')
        if not directory or not Path(directory).resolve().is_relative_to(root.resolve()):
            continue
        total = torrent.get('sizeWhenDone') or torrent.get('totalSize') or 0
        left = torrent.get('leftUntilDone')
        if total <= 0 or left is None:
            unknown += 1
            left = max(left or 0, known.get(torrent.get('hashString'), {}).get('reserved_bytes', 0))
        remaining += max(0, int(left))
        if torrent.get('status') == 4 and not torrent.get('errorString'):
            rate += max(0, torrent.get('rateDownload', 0))
    return dict(free_bytes=free, remaining_bytes=remaining, rate_bytes=rate,
                unknown_count=unknown, headroom_bytes=headroom)
