"""Bounded media inventory; deletion accepts only an observed opaque selection."""
import os
import ctypes
import errno
import platform
import sys
from contextlib import contextmanager
from functools import lru_cache
import re
import secrets
import shutil
import stat
import threading
import time
from pathlib import Path

MEDIA_SUFFIXES = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.ts', '.webm', '.mpg', '.mpeg'}
HEADROOM = 2 * 1024 ** 3


@lru_cache(maxsize=1)
def _posix_at():
    """Old macOS Python builds omit dir_fd even when the OS supports POSIX *at."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.openat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    libc.openat.restype = ctypes.c_int
    libc.unlinkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    libc.unlinkat.restype = ctypes.c_int
    return libc


def _relative_name(name):
    name = os.fsencode(name)
    if not name or b'/' in name or b'\0' in name or name in (b'.', b'..'):
        raise ValueError('invalid_media_scope')
    return name


def _open_at(name, flags, directory_fd):
    encoded = _relative_name(name)
    try:
        return os.open(name, flags, dir_fd=directory_fd)
    except NotImplementedError:
        fd = _posix_at().openat(directory_fd, encoded, flags | getattr(os, 'O_CLOEXEC', 0))
        if fd < 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        try:
            os.set_inheritable(fd, False)
        except BaseException:
            os.close(fd)
            raise
        return fd


def _stat_at(name, directory_fd):
    # fstat uses Python's native struct stat conversion, avoiding a ctypes ABI
    # guess. O_NOFOLLOW rejects symlink leaves; O_NONBLOCK cannot hang on a FIFO.
    fd = _open_at(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, directory_fd)
    try:
        return os.fstat(fd)
    finally:
        os.close(fd)


def _unlink_at(name, directory_fd):
    encoded = _relative_name(name)
    try:
        os.unlink(name, dir_fd=directory_fd)
    except NotImplementedError:
        if _posix_at().unlinkat(directory_fd, encoded, 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))


class _DarwinDirent64(ctypes.Structure):
    # Apple SDK sys/dirent.h, __DARWIN_STRUCT_DIRENTRY. Read only the header;
    # d_reclen/d_namlen bound the following variable-length name.
    _fields_ = [('ino', ctypes.c_uint64), ('seekoff', ctypes.c_uint64),
                ('reclen', ctypes.c_uint16), ('namlen', ctypes.c_uint16),
                ('type', ctypes.c_uint8), ('name', ctypes.c_char * 1)]


@lru_cache(maxsize=1)
def _darwin_directory_api():
    if sys.platform != 'darwin':
        raise NotImplementedError('descriptor_scanning_not_supported')
    libc = _posix_at()
    # Intel Darwin keeps a legacy readdir ABI; request INODE64 explicitly.
    intel = platform.machine() == 'x86_64'
    reader = getattr(libc, 'readdir$INODE64') if intel else libc.readdir
    opener = getattr(libc, 'fdopendir$INODE64') if intel else libc.fdopendir
    reader.argtypes = [ctypes.c_void_p]
    reader.restype = ctypes.c_void_p
    opener.argtypes = [ctypes.c_int]
    opener.restype = ctypes.c_void_p
    libc.closedir.argtypes = [ctypes.c_void_p]
    libc.closedir.restype = ctypes.c_int
    return libc, opener, reader


@contextmanager
def _scan_at(directory_fd):
    try:
        scan = os.scandir(directory_fd)
    except (TypeError, NotImplementedError):
        scan = None
    if scan is not None:
        with scan:
            yield ((entry.name, entry.stat(follow_symlinks=False)) for entry in scan)
        return
    libc, opener, reader = _darwin_directory_api()
    duplicate = os.dup(directory_fd)
    stream = opener(duplicate)
    if not stream:
        code = ctypes.get_errno()
        os.close(duplicate)
        raise OSError(code, os.strerror(code))
    def entries():
        while True:
            ctypes.set_errno(0)
            pointer = reader(stream)
            if not pointer:
                code = ctypes.get_errno()
                if code: raise OSError(code, os.strerror(code))
                return
            header = ctypes.cast(pointer, ctypes.POINTER(_DarwinDirent64)).contents
            offset = _DarwinDirent64.name.offset
            if not 1 <= header.namlen <= 1023 or header.reclen < offset + header.namlen + 1:
                raise ValueError('invalid_directory_entry')
            name = ctypes.string_at(pointer + offset, header.namlen + 1)
            if name[-1:] != b'\0' or b'\0' in name[:-1]:
                raise ValueError('invalid_directory_entry')
            name = name[:-1]
            if name in (b'.', b'..'): continue
            _relative_name(name)
            try:
                info = _stat_at(name, directory_fd)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOENT):
                    yield os.fsdecode(name), None
                    continue
                raise
            yield os.fsdecode(name), info
    try:
        yield entries()
    finally:
        libc.closedir(stream)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class MediaLibrary:
    def __init__(self, check_disk):
        self.check_disk = check_disk
        self.selections = {}
        self.lock = threading.RLock()

    def _open_directory(self, root, parts):
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                next_fd = _open_at(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, fd)
                os.close(fd); fd = next_fd
            return fd
        except BaseException:
            os.close(fd)
            raise

    def inventory(self, excluded_paths=()):
        with self.lock:
            root = self.check_disk()
            excluded_paths = set(excluded_paths)
            root_identity = fingerprint(root.stat())[:2]
            now = time.monotonic()
            selections = {key:value for key,value in self.selections.items() if now - value[3] < 3600}
            stable_ids = {(value[0], value[1], tuple(value[2])): key for key, value in selections.items()}
            items = []; groups = {}; count = 0; truncated = False
            def add(kind, name, records, **metadata):
                snapshot = (str(root), root_identity, records)
                identity = stable_ids.get((str(root), root_identity, tuple(records))) or secrets.token_hex(16)
                selections[identity] = (*snapshot, now)
                items.append(dict(id=identity, kind=kind, name=name,
                                  size_bytes=sum(r[1][2] for r in records), file_count=len(records), deletion_scope='video_files_only', **metadata))
            for category in ('Movies', 'TV'):
                base = root / category
                if base.is_symlink() or not base.is_dir():
                    raise ValueError('media_root_changed')
                stack = [(base, 0)]
                while stack:
                    directory, depth = stack.pop()
                    # No follow-links, plus per-entry lstat. Delete reopens every parent with O_NOFOLLOW.
                    fd = self._open_directory(root, directory.relative_to(root).parts)
                    try:
                        with _scan_at(fd) as scan:
                            entries = []
                            for entry_name, entry_info in scan:
                                if len(entries) + count > 10000:
                                    truncated = True
                                    break
                                entries.append((entry_name, entry_info))
                    finally:
                        os.close(fd)
                    if entries:
                        for entry_name, info in entries:
                            count += 1
                            if count > 10000:
                                truncated = True; stack.clear(); break
                            # Finder AppleDouble sidecars retain the video's suffix;
                            # hidden folders may also contain cached or partial media.
                            if entry_name.startswith('.'):
                                continue
                            if info is None or stat.S_ISLNK(info.st_mode):
                                continue
                            if stat.S_ISDIR(info.st_mode):
                                if depth < 8: stack.append(((directory / entry_name), depth + 1))
                                else: truncated = True
                                continue
                            if not stat.S_ISREG(info.st_mode) or Path(entry_name).suffix.lower() not in MEDIA_SUFFIXES or info.st_uid != os.getuid():
                                continue
                            if directory / entry_name in excluded_paths:
                                continue
                            relative = (directory / entry_name).relative_to(root)
                            record = (relative.parts, fingerprint(info))
                            match = re.search(r'(?i)(?<![a-z0-9])S(\d{1,2})E(\d{1,3})(?:\b|[^0-9])', entry_name)
                            if category == 'TV' and match:
                                season, episode = map(int, match.groups())
                                show = entry_name[:match.start()].strip(' ._-') or (relative.parent.name if len(relative.parts) > 2 else None)
                                metadata = {'season': season, 'episode': episode}
                                if show: metadata['show'] = show
                                add('episode', entry_name, [record], **metadata)
                                if show: groups.setdefault((str(relative.parent), show, season), []).append(record)
                            else:
                                add('movie' if category == 'Movies' else 'episode', entry_name, [record])
            for (_, show, season), records in groups.items():
                add('season', f'{show} S{season:02}', records, show=show, season=season)
            self.selections = dict(sorted(selections.items(), key=lambda pair: pair[1][3])[-20000:])
            return {'ok': True, 'disk_ok': True, 'free_bytes': shutil.disk_usage(root).free,
                    'headroom_bytes': HEADROOM, 'items': sorted(items, key=lambda x:x['size_bytes'], reverse=True), 'truncated': truncated}

    def selected_paths(self, identity):
        selection = self.selections.get(identity)
        if selection is None or time.monotonic() - selection[3] >= 3600: raise ValueError('stale_inventory_id')
        return [Path(selection[0]).joinpath(*parts) for parts, _ in selection[2]]

    def delete(self, identity, before_delete=None):
        with self.lock:
            selection = self.selections.get(identity)
            if selection is None or time.monotonic() - selection[3] >= 3600: raise ValueError('stale_inventory_id')
            root = self.check_disk()
            if str(root) != selection[0] or fingerprint(root.stat())[:2] != selection[1]:
                raise ValueError('media_root_changed')
            opened = []
            try:
                for parts, expected in selection[2]:
                    if len(parts)<2 or parts[0] not in ('Movies','TV') or any(p in ('','..','.') for p in parts):
                        raise ValueError('invalid_media_scope')
                    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        for part in parts[:-1]:
                            next_fd = _open_at(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, fd)
                            os.close(fd); fd=next_fd
                        info = _stat_at(parts[-1], fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or fingerprint(info)!=expected:
                            raise ValueError('stale_inventory_id')
                        opened.append((fd, parts, expected)); fd=None
                    finally:
                        if fd is not None: os.close(fd)
                # Preflight all members before removing any. Never remove directories or invoke Trash.
                if before_delete is not None:
                    before_delete()
                freed=0
                for fd, parts, expected in opened:
                    fresh_fd = self._open_directory(root, parts[:-1])
                    try:
                        if fingerprint(os.fstat(fresh_fd))[:2] != fingerprint(os.fstat(fd))[:2]:
                            raise ValueError('media_root_changed')
                    finally:
                        os.close(fresh_fd)
                    name = parts[-1]
                    if fingerprint(_stat_at(name, fd)) != expected:
                        raise ValueError('stale_inventory_id')
                    _unlink_at(name, fd); freed += expected[2]
                self.selections.pop(identity, None)
                return {'ok':True,'deleted_files':len(opened),'freed_bytes':freed}
            except OSError:
                raise ValueError('stale_inventory_id') from None
            finally:
                for fd, _, _ in opened: os.close(fd)
