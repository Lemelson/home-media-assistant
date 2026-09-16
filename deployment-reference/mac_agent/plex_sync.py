"""Reconcile Plex with the verified media disk, without language-model calls.

TMDB fallback: This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import json
import logging
import plistlib
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


def missing_files(files, root):
    """Only absence of every local version permits removing its Plex record."""
    if not files:
        return False
    for value in files:
        if not value:
            return False
        p = Path(value)
        try:
            relative = p.relative_to(root)
            if relative.parts[0] not in ('Movies', 'TV') or '..' in relative.parts:
                return False
            if any(x.is_symlink() for x in (p, *p.parents)):
                return False
            p.stat()
            return False
        except FileNotFoundError:
            continue
        except (ValueError, OSError, IndexError):
            return False
    return True


def poster_candidates(tree):
    return [p for p in tree if p.get('provider') and
            p.get('ratingKey', '').startswith('https://') and
            'Thumbnails/' not in p.get('ratingKey', '')]


def tmdb_posters(images):
    rank = {'ru': 0, 'en': 1, None: 2}
    valid = [p for p in images if p.get('iso_639_1') in rank and
             re.fullmatch(r'/[A-Za-z0-9]+\.(jpg|png)', p.get('file_path', '')) and
             p.get('height', 0) >= 450 and p.get('width', 0) >= 300 and
             .55 <= p['width'] / p['height'] <= .8]
    return sorted(valid, key=lambda p: (rank[p.get('iso_639_1')], -p.get('vote_average', 0), -p.get('width', 0)))


class TMDB:
    def __init__(self, secret):
        self.secret = Path(secret)

    def posters(self, meta):
        ids = [x.get('id', '') for x in meta.findall('Guid')]
        tmdb = next((x[7:] for x in ids if re.fullmatch(r'tmdb://\d+', x)), None)
        if not tmdb or not self.secret.exists():
            return []
        kind = 'tv' if meta.get('type') == 'show' else 'movie'
        token = json.loads(self.secret.read_text())['token']
        url = 'https://api.themoviedb.org/3/%s/%s/images?include_image_language=ru,en,null' % (kind, tmdb)
        # macOS curl uses the system trust store. Scoped DoH avoids poisoned
        # local DNS without changing network settings; no redirects, no -k.
        try:
            config = 'header = ' + json.dumps('Authorization: Bearer ' + token) + '\n'
            result = subprocess.run(['/usr/bin/curl', '--config', '-', '--doh-url',
                'https://cloudflare-dns.com/dns-query', '--fail', '--silent',
                '--connect-timeout', '5', '--max-time', '15', url],
                input=config, capture_output=True, text=True, timeout=20, check=True)
            data = json.loads(result.stdout)
            return ['https://image.tmdb.org/t/p/original' + x['file_path'] for x in tmdb_posters(data.get('posters', []))]
        except Exception:
            raise RuntimeError('tmdb_unavailable') from None


class RemotePoster(RuntimeError):
    def __init__(self, url):
        super().__init__('poster_requires_local_copy')
        self.url = url


class LocalPlex:
    def __init__(self):
        from mac_agent.naming import Plex
        self.api = Plex()

    def request(self, path, method='GET'):
        if method == 'GET':
            return self.api.request(path, method)
        prefs = Path.home() / 'Library/Preferences/com.plexapp.plexmediaserver.plist'
        token = plistlib.loads(prefs.read_bytes()).get('PlexOnlineToken', '')
        req = urllib.request.Request('http://127.0.0.1:32400' + path, method=method,
            headers={'X-Plex-Token': token})
        with urllib.request.urlopen(req, timeout=15) as response:
            response.read(100000)
        # Plex poster PUT returns successful HTML, not XML.
        return ET.Element('MediaContainer')

    def verify_poster(self, key):
        prefs = Path.home() / 'Library/Preferences/com.plexapp.plexmediaserver.plist'
        token = plistlib.loads(prefs.read_bytes()).get('PlexOnlineToken', '')
        meta = next(iter(self.request('/library/metadata/' + key)), None)
        thumb = meta.get('thumb', '') if meta is not None else ''
        if not thumb.startswith('/library/metadata/' + key + '/thumb/'):
            raise RuntimeError('poster_thumb_missing')
        req = urllib.request.Request('http://127.0.0.1:32400' + thumb, headers={'X-Plex-Token': token})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            try:
                with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as response:
                    data = response.read(8 * 1024 * 1024)
            except urllib.error.HTTPError as error:
                if error.code not in (301, 302, 303, 307, 308):
                    raise
                raise RemotePoster(error.headers.get('Location', '')) from None
            if len(data) < 1000 or not data.startswith((b'\xff\xd8\xff', b'\x89PNG', b'RIFF')):
                raise ValueError('invalid_poster')
        except RemotePoster:
            raise
        except Exception:
            raise RuntimeError('poster_image_unavailable') from None

    def image_bytes(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('image.tmdb.org', 'images.plex.tv', 'metadata-static.plex.tv'):
            raise ValueError('untrusted_image_host')
        urls = [url]
        if parsed.hostname == 'image.tmdb.org':
            # Plex's existing image relay can reach artwork when the CDN route
            # from the home ISP is unavailable. Identity remains the same URL.
            urls.append('https://images.plex.tv/photo?' + urllib.parse.urlencode({
                'width': 1000, 'height': 1500, 'minSize': 1, 'upscale': 0, 'url': url}))
        for candidate in urls:
            try:
                response = subprocess.run(['/usr/bin/curl', '--doh-url', 'https://cloudflare-dns.com/dns-query',
                    '--fail', '--silent', '--location', '--max-redirs', '3', '--proto-redir', '=https', '--connect-timeout', '5', '--max-time', '15', '--max-filesize', '8000000', candidate],
                    capture_output=True, timeout=20, check=True)
                data = response.stdout
                if len(data) >= 1000 and data.startswith((b'\xff\xd8\xff', b'\x89PNG', b'RIFF')):
                    return data
            except (subprocess.SubprocessError, OSError):
                continue
        raise RuntimeError('poster_download_unavailable')

    def upload_poster(self, key, url):
        data = self.image_bytes(url)
        if len(data) < 1000 or not data.startswith((b'\xff\xd8\xff', b'\x89PNG')):
            raise ValueError('invalid_poster')
        prefs = Path.home() / 'Library/Preferences/com.plexapp.plexmediaserver.plist'
        token = plistlib.loads(prefs.read_bytes()).get('PlexOnlineToken', '')
        req = urllib.request.Request('http://127.0.0.1:32400/library/metadata/' + key + '/posters',
            data=data, method='POST', headers={'X-Plex-Token': token, 'Content-Type': 'application/octet-stream'})
        with urllib.request.urlopen(req, timeout=20) as response:
            response.read(100000)



class PlexSync:
    def __init__(self, plex, check_disk, state, clock=time.time):
        self.plex, self.check_disk, self.state, self.clock = plex, check_disk, Path(state), clock
        self.tmdb = TMDB(self.state / 'tmdb-plex.json')
        self.wake = threading.Event()
        self.lock = threading.Lock()
        try:
            self.cache = json.loads((self.state / 'plex-sync.json').read_text())
        except (OSError, ValueError):
            self.cache = {}

    def save(self):
        target = self.state / 'plex-sync.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(self.cache))
        temp.chmod(0o600)
        temp.replace(target)

    def verify_delivery(self, key):
        try:
            self.plex.verify_poster(key)
        except RemotePoster as remote:
            self.plex.upload_poster(key, remote.url)
            self.plex.verify_poster(key)

    def posters(self, meta):
        key = meta.get('ratingKey', '')
        fingerprint = [meta.get('thumb'), meta.get('updatedAt'), meta.get('guid'), 'local-delivery-v1']
        previous = self.cache.get(key, {})
        if previous.get('fingerprint') == fingerprint and previous.get('ok'):
            return
        if previous.get('retry', 0) > self.clock():
            return
        try:
            tree = self.plex.request('/library/metadata/' + key + '/posters')
            selected = next((p for p in tree if p.get('selected') == '1'), None)
            # Preserve catalog art and explicit local artwork. A video thumbnail
            # is identifiable by its media:// source, independently of its crop.
            if (selected is not None and not selected.get('ratingKey', '').startswith('media://')) or (selected is None and meta.get('thumb')):
                try:
                    self.verify_delivery(key)
                    self.cache[key] = {'fingerprint': fingerprint, 'ok': True}
                    return
                except Exception:
                    pass
            urls = [p.get('ratingKey') for p in poster_candidates(tree)]
            for source in ('plex', 'tmdb'):
                if source == 'tmdb':
                    urls = self.tmdb.posters(meta)
                for url in urls[:3]:
                    try:
                        path = '/library/metadata/' + key + ('/poster?' if source == 'plex' else '/posters?') + urllib.parse.urlencode({'url': url})
                        if source == 'plex':
                            self.plex.request(path, 'PUT')
                        else:
                            self.plex.upload_poster(key, url)
                        chosen = self.plex.request('/library/metadata/' + key + '/posters')
                        if not any(p.get('selected') == '1' and (p.get('ratingKey') == url or (source == 'tmdb' and p.get('ratingKey', '').startswith(('upload://', 'metadata://')))) for p in chosen):
                            raise RuntimeError('poster_selection_not_confirmed')
                        self.verify_delivery(key)
                        self.cache[key] = {'fingerprint': fingerprint, 'ok': True, 'source': source}
                        logging.info('plex_poster_verified key=%s source=%s', key, source)
                        return
                    except Exception:
                        continue
            raise RuntimeError('poster_unavailable')
        except Exception as error:
            attempts = previous.get('attempts', 0) + 1
            self.cache[key] = {'attempts': attempts, 'retry': self.clock() + min(3600, 30 * 2 ** min(attempts, 7)), 'ok': False}
            logging.warning('plex_poster_pending key=%s reason=%s', key, type(error).__name__)

    def run_once(self):
        with self.lock:
            root = self.check_disk()
            live = set()
            for section in self.plex.request('/library/sections'):
                kind, sid = section.get('type'), section.get('key', '')
                if kind not in ('movie', 'show') or not sid.isdigit():
                    continue
                locations = [Path(x.get('path', '')) for x in section.findall('Location')]
                if not locations or any(p not in (root / 'Movies', root / 'TV') for p in locations):
                    continue
                suffix = '?type=4' if kind == 'show' else ''
                items = list(self.plex.request('/library/sections/' + sid + '/all' + suffix))
                for item in items:
                    key = item.get('ratingKey', '')
                    if not key.isdigit():
                        continue
                    files = [p.get('file') for p in item.findall('.//Part')]
                    if missing_files(files, root):
                        # Re-read immediately: naming/moving files may have changed
                        # this record since the inventory. Only indexed deletions.
                        fresh = self.plex.request('/library/metadata/' + key).find('Video')
                        if fresh is not None and (fresh.get('deletedAt') or any(p.get('deletedAt') for p in fresh.findall('.//Part'))):
                            if self.check_disk() == root and missing_files([p.get('file') for p in fresh.findall('.//Part')], root):
                                self.plex.request('/library/metadata/' + key, 'DELETE')
                                logging.info('plex_missing_record_deleted key=%s', key)
                        else:
                            self.plex.request('/library/sections/' + sid + '/refresh')
                        continue
                    if kind == 'movie':
                        live.add(key)
                        meta = item
                        if self.cache.get(key, {}).get('fingerprint') != [item.get('thumb'), item.get('updatedAt'), item.get('guid'), 'local-delivery-v1']:
                            meta = self.plex.request('/library/metadata/' + key).find('Video')
                        if meta is not None:
                            self.posters(meta)
                if kind == 'show':
                    for show in self.plex.request('/library/sections/' + sid + '/all'):
                        key = show.get('ratingKey', '')
                        if key.isdigit() and any(i.get('grandparentRatingKey') == key for i in items):
                            live.add(key)
                            self.posters(self.plex.request('/library/metadata/' + key).find('Directory'))
            self.cache = {k: v for k, v in self.cache.items() if k in live}
            self.save()

    def run(self):
        while True:
            self.wake.clear()
            try:
                self.run_once()
            except Exception as error:
                logging.warning('plex_sync_pending reason=%s', type(error).__name__)
            self.wake.wait(30)
