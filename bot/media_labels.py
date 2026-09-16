"""Reuse resolved identities and release facts without another model request."""
import re
from html import escape



def clean_name(raw):
    name = re.sub(r'\.(?:mkv|mp4|avi|m4v|mov|ts|webm)$', '', str(raw), flags=re.I)
    name = name.replace('.', ' ').replace('_', ' ')
    year = re.search(r'(?<!\d)((?:19|20)\d{2})(?!\d)', name)
    cut = re.search(r'\b(?:WEB[ -]?DL|WEBRip|BD[ -]?Rip|BDRemux|BluRay|HDRip|DVDRip|1080[pi]|720p|2160p|[xh]26[45]|HEVC|OM)\b', name, re.I)
    stop = min([m.start() for m in (year, cut) if m] or [len(name)])
    title = name[:stop].strip(' []()-') or name.strip()
    return title + (' (' + year.group(1) + ')' if year else '')


def legacy_media(raw):
    title = clean_name(raw)
    year = re.search(r'\((\d{4})\)$',title)
    if year: title=title[:year.start()].strip()
    parts = title.split(' / ',1)
    return {'title':parts[0], 'original_title':parts[1] if len(parts)>1 else '',
            'year':int(year.group(1)) if year else None}


def display_name(media, fallback='Фильм'):
    if not media or not media.get('title'):
        return clean_name(fallback)
    name = str(media['title'])[:180]
    if media.get('year'): name += ' (' + str(media['year']) + ')'
    if media.get('season'): name += ' · сезон ' + str(media['season'])
    return name


def film_card(media, quality, size, seeds=None):
    name = display_name(media)
    lines = ['🎬 <b>' + escape(name) + '</b>']
    original = media.get('original_title')
    if original and original != media.get('title'): lines.append('<i>' + escape(original) + '</i>')
    extra = [', '.join(media.get(k, [])) for k in ('countries','genres') if media.get(k)]
    if extra: lines.append(escape(' · '.join(extra)))
    facts = [quality[k] for k in ('source','resolution','codec','audio','bitrate') if quality.get(k)]
    if size: facts.append('%.1f ГБ' % (size / 1024**3))
    if seeds is not None: facts.append('раздают: %d' % seeds)
    if quality.get('leechers') is not None: facts.append('скачивают: %d' % quality['leechers'])
    if facts: lines.append(escape(' · '.join(facts)))
    return '\n'.join(lines)


def label_record(store, torrent_hash):
    if not torrent_hash: return {}
    saved = store.read_state('film:' + torrent_hash)
    if saved is not None: return saved
    for job in store.successful_adds():
        if job['result'].get('hash') == torrent_hash:
            payload = job['payload']
            from bot.search import release_metadata
            fallback = payload.get('name') or job['result'].get('name','')
            record = {'media': payload.get('media') or legacy_media(fallback),
                      'quality': payload.get('quality') or release_metadata({'title':fallback}),
                      'fallback': fallback}
            store.write_state('film:' + torrent_hash, record)
            return record
    return {}


def decorate(store, item):
    from bot.search import release_metadata
    record = label_record(store, item.get('torrent_hash') or item.get('hashString') or item.get('hash'))
    raw = item.get('raw_name',item.get('name',''))
    media = record.get('media') or item.get('media',{})
    name = display_name(media, record.get('fallback') or raw)
    if item.get('episode'):
        name += ' · серия ' + str(item['episode'])
    quality = {**release_metadata({'title':raw}), **item.get('quality',{}), **record.get('quality',{})}
    return {**item, 'raw_name':raw, 'name':name, 'media':media, 'quality':quality}


def status_labels(store, status):
    return {**status, 'torrents':[decorate(store,t) for t in status.get('torrents',[])]}
