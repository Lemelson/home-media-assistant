"""Only manage bot-created downloads on the verified external volume."""

import re
from contextlib import contextmanager
import base64
import threading
import logging
import time
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bot.jobs import JobStore
from mac_agent.library import MediaLibrary, HEADROOM
from mac_agent.download_journal import DownloadJournal
from mac_agent.recovery import RecoveryController, RECOVERY_FIELDS


class DiskUnavailable(RuntimeError):
    pass


FIELDS = ['hashString', 'name', 'status', 'percentDone', 'rateDownload', 'rateUpload',
          'eta', 'totalSize', 'sizeWhenDone', 'leftUntilDone', 'downloadDir', 'errorString',
          'peersConnected', 'peersSendingToUs', 'files', 'fileStats', 'bandwidthPriority', 'trackerStats', 'recheckProgress', 'addedDate', 'doneDate', 'secondsDownloading', 'downloadedEver']


def first_episode_index(files):
    candidates = []
    for index, item in enumerate(files):
        name = item.get('name', '').casefold()
        if Path(name).suffix not in ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.ts'):
            continue
        if re.search(r'(^|[\W_])(sample|trailer|трейлер)([\W_]|$)', name):
            continue
        natural = tuple((0, int(part)) if part.isdigit() else (1, part) for part in re.split(r'(\d+)', name))
        candidates.append((natural, index))
    return min(candidates)[1] if candidates else None


class MediaController:
    def __init__(self, database, rpc, check_disk):
        self.store = JobStore(database)
        self.rpc = rpc
        self.check_disk = check_disk
        self.lock = threading.Lock()
        self.recovery = RecoveryController(self.store, self.rpc)
        self.media_library = MediaLibrary(check_disk)
        self.journal = DownloadJournal(Path(database).parent / "download-history")

    def status(self):
        try:
            self.check_disk()
            disk_ok = True
        except DiskUnavailable as error:
            disk_ok = None if str(error) in ('disk_probe_timeout','disk_probe_failed','disk_probe_busy') else False
        known = self.store.read_state('managed', {})
        torrents = self.rpc.call('torrent-get', {'fields': FIELDS}).get('torrents', [])
        managed = []
        for t in torrents:
            if t['hashString'] in known:
                t = dict(t)
                t['recovery_note'] = self.recovery.note(t['hashString'])
                trackers = t.pop('trackerStats',[])
                for field, output in (('seederCount','seeders'),('leecherCount','leechers')):
                    counts=[r[field] for r in trackers if isinstance(r.get(field),int) and r[field]>=0]
                    if counts: t[output]=max(counts)
                t['system_pause'] = known[t['hashString']].get('system_pause')
                t['queue_paused'] = bool(known[t['hashString']].get('queue_paused'))
                t['manual_pause'] = bool(known[t['hashString']].get('manual_pause'))
                t['remaining_bytes'] = t.get('leftUntilDone', 0)
                if known[t['hashString']].get('capacity_pending'):
                    t['capacity_error'] = known[t['hashString']].get('capacity_error', 'size_unknown')
                t['downloaded_bytes'] = max(0, t.get('sizeWhenDone', t.get('totalSize', 0)) - t['remaining_bytes'])
                managed.append(t)
        return {'ok': True, 'disk_ok': disk_ok, 'disk_state': 'checking' if disk_ok is None else 'ready' if disk_ok else 'missing', 'torrents': managed,
                'download_history':self.journal.summaries(),'history_storage':self.journal.storage()}

    def collect_history(self):
        known=self.store.read_state('managed',{})
        try:
            snapshots=self.rpc.call('torrent-get',{'fields':FIELDS}).get('torrents',[])
        except Exception:
            self.journal.unavailable()
            raise
        rows=[]
        for t in snapshots:
            if t['hashString'] not in known:continue
            row=dict(t)
            for field,key in (('seederCount','seeders'),('leecherCount','leechers')):
                counts=[v[field] for v in t.get('trackerStats',[]) if isinstance(v.get(field),int) and v[field]>=0]
                if counts:row[key]=max(counts)
            row['quality']=known[t['hashString']].get('quality',{})
            row['system_pause']=known[t['hashString']].get('system_pause')
            rows.append(row)
        self.journal.record(rows)

    def library(self):
        with self.lock:
            torrents = self.rpc.call('torrent-get', {'fields': ['hashString','downloadDir','files']}).get('torrents', [])
            result = self._inventory(torrents)
            owners = {}
            for t in torrents:
                for item in t.get('files', []):
                    owners[Path(t.get('downloadDir','/')) / item.get('name','')] = t['hashString']
            for item in result['items']:
                hashes = {owners[path] for path in self.media_library.selected_paths(item['id']) if path in owners}
                if len(hashes) == 1: item['torrent_hash'] = hashes.pop()
            return result

    def _inventory(self, torrents):
        incomplete = set()
        for torrent in torrents:
            directory = Path(torrent.get('downloadDir', '/'))
            for item in torrent.get('files', []):
                if item.get('bytesCompleted', 0) < item.get('length', 0):
                    incomplete.add(directory / item.get('name', ''))
        return self.media_library.inventory(excluded_paths=incomplete)

    def _capacity(self, root, required, exclude=None):
        free = shutil.disk_usage(root).free
        torrents = self.rpc.call('torrent-get', {'fields': ['hashString','downloadDir','leftUntilDone','totalSize','files']}).get('torrents', [])
        known = self.store.read_state('managed', {})
        reserved = sum(max(0, int(t.get('leftUntilDone', 0)),
                           0 if t.get('totalSize', 0) > 0 else known.get(t.get('hashString'), {}).get('reserved_bytes', 0)) for t in torrents
                       if t.get('hashString') != exclude and Path(t.get('downloadDir', '/')).resolve().is_relative_to(root.resolve()))
        if required + reserved + HEADROOM > free:
            try:
                biggest = self._inventory(torrents)['items'][:10]
            except (ValueError, OSError):
                biggest = []
            return {'ok': False, 'error': 'insufficient_space', 'required_bytes': required,
                    'free_bytes': free, 'reserved_bytes': reserved, 'headroom_bytes': HEADROOM, 'biggest': biggest}
        return None

    def _delete_library(self, payload):
        identity = payload.get('inventory_id')
        if not isinstance(identity, str): raise ValueError('invalid_inventory_id')
        paths = set(self.media_library.selected_paths(identity))
        known = self.store.read_state('managed', {})
        torrents = self.rpc.call('torrent-get', {'fields': ['hashString','downloadDir','files']}).get('torrents', [])
        affected = []
        for t in torrents:
            directory = Path(t.get('downloadDir', '/'))
            if any(directory / f.get('name', '') in paths for f in t.get('files', [])):
                # Remove the transfer without deleting its data: otherwise a later start
                # can recreate a deleted episode. Other episode files remain on disk.
                affected.append(t['hashString'])
        def stop_transfers():
            if affected:
                self.rpc.call('torrent-stop', {'ids': affected})
                self.rpc.call('torrent-remove', {'ids': affected, 'delete-local-data': False})
                for h in affected: known.pop(h, None)
                self.store.write_state('managed', known)
        return self.media_library.delete(identity, before_delete=stop_transfers)

    @contextmanager
    def command_lock(self, payload):
        acquired = self.lock.acquire(timeout=2) if payload.get('action') == 'bandwidth_priority' else self.lock.acquire()
        if not acquired:
            raise RuntimeError('media_busy')
        try:
            yield
        finally:
            self.lock.release()

    def command(self, job_id, payload):
        if not isinstance(job_id, str) or not 1 <= len(job_id) <= 160:
            raise ValueError('invalid_job_id')
        if payload.get('action') == 'naming_status':
            from mac_agent.naming import naming_command
            return naming_command(self, payload)
        with self.command_lock(payload):
            if payload.get('action') == 'naming_apply':
                from mac_agent.naming import naming_command
                return naming_command(self, payload)
            previous = self.store.read_state('result:' + job_id)
            if previous is not None:
                return previous
            action = payload.get('action')
            if action == 'add':
                result = self._add(payload)
            elif action == 'delete_library':
                result = self._delete_library(payload)
            elif action == 'bandwidth_priority' and 'mode' in payload:
                mode=payload['mode'];h=payload.get('hash')
                if type(mode) is not int or mode not in (-1,0,1,2):raise ValueError('invalid_mode')
                known=self.store.read_state('managed',{})
                if h not in known:raise ValueError('unmanaged_torrent')
                if mode==2:
                    result=self._control({**payload,'action':'pause'})
                    result.update(action='bandwidth_priority',priority=known[h].get('queue_priority',0),paused=True)
                else:
                    rows=self.rpc.call('torrent-get',{'ids':[h],'fields':['hashString','status']}).get('torrents',[])
                    row=next(t for t in rows if t['hashString']==h)
                    if known[h].get('manual_pause') or row['status']==0:
                        resumed=self._control({**payload,'action':'resume'})
                        if not resumed.get('ok'):return resumed
                    result=self._control({**payload,'priority':mode})
                    result['paused']=False
            elif action == 'bandwidth_priority' and payload.get('cycle') is True:
                h = payload.get('hash')
                if h not in self.store.read_state('managed',{}):
                    raise ValueError('unmanaged_torrent')
                planned = self.store.read_state('priority-plan:'+job_id)
                if planned is None:
                    rows=self.rpc.call('torrent-get',{'ids':[h],'fields':['hashString','bandwidthPriority','status']}).get('torrents',[])
                    current=next(t for t in rows if t['hashString']==h)
                    info=self.store.read_state('managed',{})[h]
                    planned=-1 if info.get('manual_pause') or (current.get('status')==0 and not info.get('queue_paused')) else {-1:0,0:1,1:2}[current.get('bandwidthPriority',0)]
                    self.store.write_state('priority-plan:'+job_id,planned)
                if planned == 2:
                    result = self._control({**payload,'action':'pause'})
                    result.update(action='bandwidth_priority',priority=1,paused=True)
                else:
                    info=self.store.read_state('managed',{}).get(h,{})
                    if planned == -1:
                        resumed=self._control({**payload,'action':'resume'})
                        if not resumed.get('ok'):return resumed
                    result = self._control({**payload,'priority':planned})
                    result['paused']=False
            elif action in ('pause', 'resume', 'delete', 'priority', 'bandwidth_priority'):
                result = self._control(payload)
            else:
                raise ValueError('unknown_action')
            self.store.write_state('result:' + job_id, result)
            return result

    def _add(self, payload):
        # Multi-season file selection is not supported yet: never start an
        # entire collection when the user requested just one season.
        if payload.get('season_pack'):
            raise ValueError('multi_season_pack_not_supported')
        metainfo = payload.get('metainfo')
        if metainfo is not None:
            if not isinstance(metainfo, str) or len(metainfo) > 2800000 or payload.get('magnet'):
                raise ValueError('invalid_metainfo')
            raw = base64.b64decode(metainfo, validate=True)
            if not raw.startswith(b'd') or not raw.endswith(b'e') or b'4:info' not in raw:
                raise ValueError('invalid_metainfo')
            torrent_input = {'metainfo': metainfo}
        else:
            magnet = payload.get('magnet', '')
            if not isinstance(magnet, str) or len(magnet) > 16384:
                raise ValueError('invalid_magnet')
            parsed = urlsplit(magnet)
            hashes = parse_qs(parsed.query).get('xt', [])
            if parsed.scheme != 'magnet' or not any(re.fullmatch(r'urn:btih:(?:[a-fA-F0-9]{40}|[a-zA-Z2-7]{32})', h) for h in hashes):
                raise ValueError('invalid_magnet')
            torrent_input = {'filename': magnet}
        kind = payload.get('kind', 'movie')
        if kind not in ('movie', 'show'):
            raise ValueError('invalid_kind')
        season = payload.get('season')
        if season is not None and (type(season) is not int or not 1 <= season <= 99):
            raise ValueError('invalid_season')
        root = self.check_disk()
        destination = root / ('TV' if kind == 'show' else 'Movies')
        supplied_size = payload.get('size_bytes')
        if supplied_size is not None and (type(supplied_size) is not int or supplied_size <= 0):
            raise ValueError('invalid_size')
        known = self.store.read_state('managed', {})
        expected_hash = None
        if metainfo is None:
            xt = next(h for h in hashes if re.fullmatch(r'urn:btih:(?:[a-fA-F0-9]{40}|[a-zA-Z2-7]{32})', h))
            encoded_hash = xt.rsplit(':', 1)[1]
            expected_hash = (base64.b32decode(encoded_hash.upper()).hex() if len(encoded_hash) == 32 else encoded_hash.lower())
        if supplied_size and expected_hash not in known and metainfo is None:
            denied = self._capacity(root, supplied_size)
            if denied: return denied
        result = self.rpc.call('torrent-add', {**torrent_input, 'download-dir': str(destination), 'paused': True})
        torrent = result.get('torrent-added') or result.get('torrent-duplicate')
        if not torrent:
            raise RuntimeError('missing_torrent_result')
        torrent_hash = torrent['hashString']
        known = self.store.read_state('managed', {})
        if 'torrent-duplicate' in result and torrent_hash not in known:
            raise ValueError('torrent_exists_outside_bot')
        if 'torrent-duplicate' in result:
            return {'ok': True, 'hash': torrent_hash, 'name': torrent.get('name', ''),
                    'duplicate': True, 'paused': bool(known[torrent_hash].get('manual_pause'))}
        known[torrent_hash] = {'destination': str(destination), 'kind': kind, 'needs_priority': kind == 'show',
                               'quality':payload.get('quality',{}), 'media':payload.get('media',{}),
                               'queue_paused':True, 'queue_priority':0, 'priority_next':1}
        self.journal.register(torrent_hash,payload)
        self.store.write_state('managed', known)
        self.check_disk()
        snapshots = self.rpc.call('torrent-get', {'ids': [torrent_hash], 'fields': ['hashString','totalSize','leftUntilDone']}).get('torrents', [])
        snapshot = next((t for t in snapshots if t.get('hashString') == torrent_hash), {})
        size = max(supplied_size or 0, snapshot.get('totalSize', 0))
        if not size:
            known[torrent_hash]['capacity_pending'] = True
            known[torrent_hash]['manual_pause'] = True
            self.store.write_state('managed', known)
            return {'ok': False, 'error': 'size_unknown', 'hash': torrent_hash, 'name': torrent.get('name', ''), 'paused': True}
        required = max(0, snapshot.get('leftUntilDone', size)) if snapshot.get('totalSize', 0) > 0 else size
        denied = self._capacity(root, required, exclude=torrent_hash)
        if denied:
            known[torrent_hash]['capacity_pending'] = True
            known[torrent_hash]['capacity_error'] = 'insufficient_space'
            known[torrent_hash]['manual_pause'] = True
            self.store.write_state('managed', known)
            return dict(denied, hash=torrent_hash, paused=True)
        known[torrent_hash]['reserved_bytes'] = required
        self.store.write_state('managed', known)
        self.rpc.call('torrent-set', {'ids': [torrent_hash], 'bandwidthPriority': 0})
        self.reconcile_queue()
        return {'ok': True, 'hash': torrent_hash, 'name': torrent.get('name', '')}

    def _control(self, payload):
        torrent_hash = payload.get('hash')
        known = self.store.read_state('managed', {})
        if torrent_hash not in known:
            raise ValueError('unmanaged_torrent')
        action = payload['action']
        if action == 'bandwidth_priority':
            priority = payload.get('priority')
            if type(priority) is not int or priority not in (-1, 0, 1):
                raise ValueError('invalid_bandwidth_priority')
            self.reconcile_queue(torrent_hash, priority, -1 if priority == 0 else 1)
            return {'ok': True, 'hash': torrent_hash, 'action': action, 'priority': priority,
                    'priorities': {torrent_hash:priority}}
        if action == 'resume':
            root = self.check_disk()
            snapshots = self.rpc.call('torrent-get', {'ids': [torrent_hash], 'fields': ['hashString','totalSize','leftUntilDone']}).get('torrents', [])
            snapshot = next((t for t in snapshots if t.get('hashString') == torrent_hash), {})
            required = snapshot.get('leftUntilDone', snapshot.get('totalSize', 0))
            if not snapshot.get('totalSize'):
                return {'ok': False, 'error': 'size_unknown', 'hash': torrent_hash, 'paused': True}
            denied = self._capacity(root, required, exclude=torrent_hash)
            if denied: return dict(denied, hash=torrent_hash, paused=True)
            known[torrent_hash].pop('capacity_pending', None)
            known[torrent_hash].pop('capacity_error', None)
        if action == 'delete':
            raise ValueError('use_library_selection')
        elif action == 'priority':
            indices = payload.get('indices')
            if not isinstance(indices, list) or not indices or not all(type(i) is int and 0 <= i <= 100000 for i in indices):
                raise ValueError('invalid_file_indices')
            self.rpc.call('torrent-set', {'ids': [torrent_hash], 'priority-high': indices})
        else:
            known[torrent_hash].pop('system_pause', None)
            known[torrent_hash].pop('disk_healthy_checks', None)
            known[torrent_hash]['manual_pause'] = action == 'pause'
            self.store.write_state('managed', known)
            self.recovery.observed.pop(torrent_hash, None)
            if action == 'pause':
                self.rpc.call('torrent-stop', {'ids': [torrent_hash]})
            else:
                known[torrent_hash]['queue_paused'] = True
                self.store.write_state('managed', known)
            self.reconcile_queue()
        return {'ok': True, 'hash': torrent_hash, 'action': action}

    def reconcile_queue(self, promote=None, priority=None, next_priority=None):
        from mac_agent.download_queue import reconcile
        self.check_disk()
        reconcile(self.store, self.rpc, promote, priority, next_priority)

    def guard_disk(self):
        """Record disk safety pauses and recover only those after two healthy checks."""
        with self.lock:
            try:
                root = self.check_disk()
            except DiskUnavailable as error:
                if str(error) in ('disk_probe_timeout','disk_probe_failed','disk_probe_busy'):
                    logging.warning('disk_check_uncertain reason=%s', str(error))
                    return
                known = self.store.read_state('managed', {})
                self.recovery.tick([], known)
                snapshots = self.rpc.call('torrent-get', {'ids': list(known), 'fields': ['hashString','status','leftUntilDone']}).get('torrents', []) if known else []
                hashes = []
                for torrent in snapshots:
                    h = torrent['hashString']
                    info = known.get(h, {})
                    if info.get('manual_pause') or info.get('capacity_pending'):
                        continue
                    if torrent.get('status') in (3,4) and torrent.get('leftUntilDone',1)>0:
                        info.update(system_pause='disk_unavailable', disk_healthy_checks=0,
                                    system_pause_at=time.time())
                        hashes.append(h)
                    elif info.get('system_pause'):
                        info['disk_healthy_checks']=0
                self.store.write_state('managed',known)
                if hashes:
                    logging.warning('automatic_pause reason=disk_unavailable count=%d',len(hashes))
                    self.rpc.call('torrent-stop', {'ids': hashes})
                return
            known = self.store.read_state('managed', {})
            # Recheck after metadata arrives and as other programs consume space.
            capacity = self._capacity(root, 0)
            if capacity:
                snapshots = self.rpc.call('torrent-get', {
                    'ids': list(known), 'fields': ['hashString', 'totalSize', 'leftUntilDone', 'percentDone']
                }).get('torrents', []) if known else []
                completed = {t['hashString'] for t in snapshots
                             if t.get('totalSize', 0) > 0 and t.get('leftUntilDone') == 0
                             and t.get('percentDone', 0) >= 1}
                for h in completed & known.keys():
                    known[h].pop('capacity_pending', None)
                    known[h].pop('capacity_error', None)
                hashes = [h for h in known if h not in completed]
                for h in hashes:
                    known[h]['manual_pause'] = True
                    known[h]['capacity_pending'] = True
                    known[h]['capacity_error'] = 'insufficient_space'
                self.store.write_state('managed', known)
                if hashes: self.rpc.call('torrent-stop', {'ids': hashes})
                self.recovery.tick([], known)
                return
            for h, info in known.items():
                if (info.get('system_pause') == 'disk_unavailable' and not info.get('manual_pause')
                        and not info.get('capacity_pending')):
                    info['disk_healthy_checks'] = info.get('disk_healthy_checks',0)+1
                    self.store.write_state('managed',known)
                    if info['disk_healthy_checks'] >= 2:
                        # _capacity above has verified all reserved bytes, not just this file.
                        info['queue_paused'] = True
                        info.pop('system_pause',None)
                        info.pop('disk_healthy_checks',None)
                        logging.info('automatic_resume reason=disk_restored')
            self.store.write_state('managed',known)
            pending = [h for h, info in known.items() if info.get('needs_priority')]
            if pending:
                torrents = self.rpc.call('torrent-get', {'ids': pending, 'fields': ['hashString', 'files']}).get('torrents', [])
                for torrent in torrents:
                    index = first_episode_index(torrent.get('files', []))
                    if index is not None:
                        self.rpc.call('torrent-set', {'ids': [torrent['hashString']], 'priority-high': [index]})
                        known[torrent['hashString']]['needs_priority'] = False
                self.store.write_state('managed', known)

            self.reconcile_queue()
            known = self.store.read_state('managed', {})
            # Queue-owned pauses must not be mistaken for stalled transfers.
            recovery_known = {h: dict(info, manual_pause=True) if info.get('queue_paused') else info
                              for h, info in known.items()}
            try:
                snapshots = self.rpc.call('torrent-get', {'fields': RECOVERY_FIELDS}).get('torrents', []) if known else []
                self.recovery.tick(snapshots, recovery_known)
            except Exception:
                self.recovery.tick([], known)
                raise
