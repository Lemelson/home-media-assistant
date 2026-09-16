"""Bounded retries for one film; successful query variants survive later failures."""
from dataclasses import dataclass
import logging
import math
import time

from bot.providers import ProviderError
from bot.release_matching import additional_search_queries, rejection_reason, search_queries

BUDGET = 120
ATTEMPT_BUDGET = 45
MAX_ATTEMPTS = 4
RETRY_DELAYS = (10, 20, 30)
TRANSIENT = {'provider_request_failed', 'indexers_unavailable', 'search_busy', 'search_timeout'}
REASONS = {
    'provider_request_failed': 'Ошибка соединения с источником.',
    'indexers_unavailable': 'Источник временно недоступен после сбоя.',
    'search_busy': 'Источник занят другим поиском.',
    'search_timeout': 'Источник не успел ответить.',
    'indexers_not_configured': 'Источники поиска не настроены.',
    'provider_auth_failed': 'Источник отклонил авторизацию.',
}


@dataclass
class SearchResult:
    rows: list
    attempts: int
    incomplete: bool
    reason: str = ''


def find_releases(indexer, media, progress):
    deadline = time.monotonic() + BUDGET
    pending = list(search_queries(media))
    found = {}
    attempts = 0
    reason = ''
    extra_checked = False
    while pending and attempts < MAX_ATTEMPTS and time.monotonic() < deadline:
        attempts += 1
        progress(attempts, reason, None)
        attempt_deadline = min(deadline, time.monotonic() + ATTEMPT_BUDGET)
        error = None
        while pending:
            query = pending[0]
            try:
                if time.monotonic() >= attempt_deadline:
                    raise ProviderError('search_timeout')
                if callable(getattr(type(indexer), 'search_until', None)):
                    rows = indexer.search_until(query, attempt_deadline)
                else:
                    rows = indexer.search(query)
                for row in rows:
                    found[row.get('guid') or row['title']] = row
                pending.pop(0)
                if not pending and not extra_checked:
                    extra_checked = True
                    if media.get('kind') == 'show' and sum(rejection_reason(r, media) is None for r in found.values()) < 8:
                        pending = [q for q in additional_search_queries(media) if q not in search_queries(media)]
            except Exception as exc:
                error = exc
                # An outage affects the source, not just this spelling of the title.
                break
        if not pending:
            return SearchResult(list(found.values()), attempts, False)
        code = str(error) if isinstance(error, ProviderError) else 'provider_request_failed' if isinstance(error, OSError) else 'unexpected'
        reason = REASONS.get(code, 'Не удалось выполнить поиск в источнике.')
        logging.warning('release_retry attempt=%d reason=%s remaining=%.1f', attempts, code if code in REASONS else 'unexpected', max(0, deadline-time.monotonic()))
        if code not in TRANSIENT or attempts >= MAX_ATTEMPTS:
            break
        delay = RETRY_DELAYS[attempts-1]
        retry_at = getattr(error, 'retry_at', None)
        if retry_at is not None:
            delay = max(delay, retry_at - time.time())
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        delay = min(delay, remaining)
        progress(attempts, reason, math.ceil(delay))
        time.sleep(max(0, min(delay, deadline-time.monotonic())))
    return SearchResult(list(found.values()), attempts, True, reason)
