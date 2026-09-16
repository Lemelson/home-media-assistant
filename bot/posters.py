"""Optional TMDB posters selected by media identity, without image downloads."""
from collections import OrderedDict
import re
import threading
import time
from urllib.parse import urlencode

from bot.providers import request_json


class TMDBPosters:
    ATTRIBUTION = 'This product uses the TMDB API but is not endorsed or certified by TMDB.'
    ATTRIBUTION_URL = 'https://developer.themoviedb.org/docs/faq'
    SOURCE_URL = 'https://www.themoviedb.org'

    def __init__(self, key, bearer=True):
        self.key, self.bearer = key, bearer
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def _get(self, path, params):
        headers = {'Authorization': 'Bearer ' + self.key} if self.bearer else {}
        if not self.bearer:
            params = {**params, 'api_key': self.key}
        return request_json('https://api.themoviedb.org/3/' + path + '?' + urlencode(params),
                            None, headers, timeout=12)

    @staticmethod
    def _name(value):
        return ' '.join(re.findall(r'[^\W_]+', str(value).casefold().replace('ё', 'е')))

    def image(self, query):
        title = re.sub(r'\s+poster\s*$', '', str(query), flags=re.I).strip()
        match = re.search(r'\s+(18\d{2}|19\d{2}|20\d{2})$', title)
        year = int(match.group(1)) if match else None
        title = title[:match.start()].strip() if match else title
        return self.for_media({'title': title, 'year': year, 'kind': 'movie'})

    def for_media(self, media, language='ru'):
        gallery = self.for_media_gallery(media, language)
        return gallery[0] if gallery else None

    def for_media_gallery(self, media, language='ru', limit=3):
        """Return up to three images, preferring a poster, for one unambiguous title/year."""
        language = 'en' if language.startswith('en') else 'ru'
        names = tuple(dict.fromkeys(n.strip() for n in
                      (media.get('title'), media.get('original_title')) if isinstance(n, str) and n.strip()))
        kind, year = media.get('kind', 'movie'), media.get('year')
        if not names or kind not in ('movie', 'show'):
            return []
        key = (names, kind, year, language)
        # Serialize lookups so concurrent identical requests also share the cache.
        with self._lock:
            now = time.monotonic()
            if key in self._cache and self._cache[key][0] > now:
                self._cache.move_to_end(key)
                return list(self._cache[key][1])[:limit]
            try:
                gallery = self._find(names, kind, year, language)
            except Exception:
                return []
            self._cache[key] = (time.monotonic() + 86400, tuple(gallery))
            self._cache.move_to_end(key)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
            return gallery[:limit]

    def _find(self, names, kind, year, language):
        endpoint = 'tv' if kind == 'show' else 'movie'
        title_fields = ('name', 'original_name') if kind == 'show' else ('title', 'original_title')
        date_field = 'first_air_date' if kind == 'show' else 'release_date'
        expected = {self._name(n) for n in names}
        matches = {}
        for name in names:
            params = {'query': name, 'language': language, 'include_adult': 'false'}
            if year is not None:
                params['first_air_date_year' if kind == 'show' else 'primary_release_year'] = year
            for row in self._get('search/' + endpoint, params).get('results', []):
                if not expected.intersection(self._name(row.get(field, '')) for field in title_fields):
                    continue
                if year is not None and str(row.get(date_field, ''))[:4] != str(year):
                    continue
                if type(row.get('id')) is int and row['id'] > 0:
                    matches[row['id']] = row
            if matches:
                break
        if len(matches) != 1:
            return []
        media_id = next(iter(matches))
        preference = (language, 'en' if language == 'ru' else 'ru', None)
        data = self._get(f'{endpoint}/{media_id}/images', {'include_image_language': 'ru,en,null'})
        def valid(rows):
            return [p for p in rows if isinstance(p, dict) and p.get('iso_639_1') in preference
                    and isinstance(p.get('file_path'), str)
                    and re.fullmatch(r'/[A-Za-z0-9_-]+\.(?:jpg|png|webp)', p['file_path'])]

        posters = sorted(valid(data.get('posters', [])),
                         key=lambda p: preference.index(p.get('iso_639_1')))
        gallery, seen = [], set()
        if posters:
            path = posters[0]['file_path']
            gallery.append('https://image.tmdb.org/t/p/w500' + path)
            seen.add(path)
        # Stills are from the exact same TMDB identity; never use generic image search hits.
        for row in valid(data.get('backdrops', [])):
            path = row['file_path']
            if path not in seen:
                gallery.append('https://image.tmdb.org/t/p/w780' + path)
                seen.add(path)
            if len(gallery) == 3:
                break
        return gallery
