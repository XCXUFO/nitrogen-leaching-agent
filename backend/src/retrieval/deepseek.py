"""DeepSeek's standalone Search/Fetch APIs; official origin only, shared RAG key."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import json

import httpx

from src.retrieval.web import FetchError, PublicFetcher, WebSearch, public_url, global_address

ORIGIN = 'https://api.deepseek.com'
ERRORS = {400: 'invalid_provider_request', 401: 'unauthorized', 402: 'insufficient_balance',
          403: 'provider_forbidden', 404: 'no_content', 408: 'timeout', 413: 'body_too_large',
          429: 'rate_limited', 504: 'timeout'}


class DeepSeekWebSearch(WebSearch):
    provider = 'deepseek'
    query_limit = 128

    def __init__(self, *, api_key='', enabled=False, timeout=30.0, max_queries=2, max_pages=5,
                 max_bytes=1_000_000, transport=None, resolver=None, proxy=None, diagnostic=None):
        super().__init__(enabled=enabled, endpoint=ORIGIN, timeout=timeout, max_queries=max_queries, max_pages=max_pages,
                         fetcher=PublicFetcher(resolver=resolver))
        self._api_key = api_key
        self._diagnostic = diagnostic
        self._transport, self._proxy, self.max_bytes = transport, proxy or None, max_bytes

    @property
    def ready(self):
        return bool(self.enabled and self._api_key.strip())

    async def post(self, operation, body):
        if operation not in {'search', 'fetch'}:
            raise FetchError('invalid_provider_request')
        response_received = False
        try:
            async with asyncio.timeout(min(self.timeout, 10.0)):
                # No redirects: a provider response can never forward the bearer key to another origin.
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=min(self.timeout, 10.0),
                                             transport=self._transport, proxy=self._proxy) as client:
                    async with client.stream('POST', ORIGIN + '/v1/tools/' + operation, json=body, headers={
                        'Authorization': 'Bearer ' + self._api_key, 'Content-Type': 'application/json',
                        'Accept': 'application/json', 'Accept-Encoding': 'identity'}) as response:
                        response_received = True
                        if self._diagnostic:
                            self._diagnostic({'operation': operation, 'http_status': response.status_code,
                                'media_type': 'json' if 'json' in response.headers.get('content-type', '').lower() else 'html' if 'html' in response.headers.get('content-type', '').lower() else 'other'})
                        if response.status_code != 200:
                            # Never persist provider error prose or request headers (may echo credentials).
                            raise FetchError(ERRORS.get(response.status_code, 'provider_unavailable'))
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > self.max_bytes:
                                raise FetchError('body_too_large')
                        if self._diagnostic:
                            self._diagnostic({'operation': operation, 'response_bytes': len(raw)})
                        if raw.lstrip().startswith(b'<'):
                            raise FetchError('unexpected_html_response')
                        value = json.loads(raw)
                        if self._diagnostic:
                            self._diagnostic({'operation': operation, 'json_type': type(value).__name__,
                                'known_fields': [k for k in ('results', 'title', 'content', 'error', 'data', 'code', 'message') if isinstance(value, dict) and k in value]})
                        if not isinstance(value, dict):
                            raise ValueError()
                        return value
        except (TimeoutError, httpx.TimeoutException):
            raise FetchError('timeout') from None
        except (ValueError, UnicodeError) as exc:
            if self._diagnostic:
                import traceback
                frames = traceback.extract_tb(exc.__traceback__)
                self._diagnostic({'operation': operation, 'exception_type': type(exc).__name__, 'frames': [{'file': frame.filename.rsplit('/', 1)[-1], 'line': frame.lineno, 'function': frame.name} for frame in frames[-4:]]})
            raise FetchError('invalid_provider_response' if response_received else 'client_configuration_error') from None
        except (httpx.HTTPError, OSError):
            raise FetchError('provider_unavailable') from None

    async def search_hits(self, question):
        if not question.strip() or len(question) > self.query_limit:
            raise FetchError('invalid_provider_request')
        value = await self.post('search', {'query': question, 'count': self.max_pages, 'need_content': False})
        hits = value.get('results')
        if not isinstance(hits, list):
            raise FetchError('invalid_provider_response')
        # Summary/snippet remain discovery metadata; only Fetch content can become evidence.
        return [{**hit, 'content': hit.get('summary') or hit.get('snippet') or ''} for hit in hits if isinstance(hit, dict)]

    async def read_page(self, url):
        parsed, host = public_url(url)
        # Only the fixed official API is contacted locally. Target DNS/redirects are resolved
        # by DeepSeek Fetch, whose security policy returns 403 for rejected targets.
        # Local DNS may be a proxy's fake-IP range and cannot validate the remote resolver.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*', host, re.I):
                raise FetchError('blocked_address')
        else:
            if not global_address(host):
                raise FetchError('blocked_address')
        value = await self.post('fetch', {'url': url})
        text = value.get('content')
        if not isinstance(text, str):
            raise FetchError('invalid_provider_response')
        encoded = text.encode('utf-8')
        if len(encoded) > self.max_bytes:
            raise FetchError('body_too_large')
        title = value.get('title')
        return {'url': url, 'title': title[:500] if isinstance(title, str) else '', 'text': text,
                'sha256': hashlib.sha256(encoded).hexdigest(), 'content_format': 'markdown',
                'acquisition': 'deepseek_fetch', 'final_url_verified': False}


def create_web_search(settings, *, transport=None, resolver=None, diagnostic=None):
    if settings.web_search_provider == 'deepseek':
        return DeepSeekWebSearch(api_key=settings.deepseek_api_key, enabled=settings.web_search_enabled,
            timeout=settings.web_search_timeout_s, max_queries=settings.web_search_max_queries,
            max_pages=settings.web_search_max_pages, max_bytes=settings.web_page_max_bytes,
            transport=transport, resolver=resolver, proxy=settings.deepseek_proxy, diagnostic=diagnostic)
    return WebSearch(enabled=settings.web_search_enabled, endpoint=settings.web_search_url,
        timeout=settings.web_search_timeout_s, max_queries=settings.web_search_max_queries,
        max_pages=settings.web_search_max_pages,
        fetcher=PublicFetcher(max_bytes=settings.web_page_max_bytes, transport=transport, resolver=resolver))
