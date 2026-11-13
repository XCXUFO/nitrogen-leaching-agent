"""SearXNG JSON search and bounded public-page extraction, with pinned public DNS."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx


def now():
    return datetime.now(timezone.utc).isoformat()


class FetchError(Exception):
    def __init__(self, code):
        self.code = code


def public_url(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').encode('idna').decode('ascii')
        if (parsed.scheme not in {'http', 'https'} or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 80, 443}
                or len(url) > 3000 or any(ord(c) < 33 for c in url)
                or host.lower().rstrip('.').endswith(('.localhost', '.local', '.internal'))
                or host.lower().rstrip('.') == 'localhost'):
            raise ValueError()
        return parsed, host
    except (ValueError, UnicodeError, TypeError):
        raise FetchError('blocked_url') from None


def global_address(value):
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast and not (
        isinstance(address, ipaddress.IPv6Address) and (address.ipv4_mapped or address.sixtofour or address.teredo))


class PublicFetcher:
    def __init__(self, *, max_bytes=1_000_000, timeout=6.0, transport=None, resolver=None):
        self.max_bytes, self.timeout = max_bytes, timeout
        self.transport, self.resolver = transport, resolver

    async def addresses(self, host, port):
        if self.resolver:
            addresses = await self.resolver(host, port)
        else:
            records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(row[4][0] for row in records))
        try:
            allowed = bool(addresses) and all(global_address(ip) for ip in addresses)
        except ValueError:
            allowed = False
        if not allowed:
            raise FetchError('blocked_address')
        return addresses

    async def get(self, url, *, json_response=False):
        try:
            # Bounds DNS, redirects, headers, streaming and decoding together.
            async with asyncio.timeout(self.timeout):
                for redirect in range(4):
                    parsed, host = public_url(url)
                    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                    addresses = await self.addresses(host, port)
                    # Connect only to the validated IP; retain original TLS identity and Host.
                    ip = addresses[0]
                    authority = f'[{ip}]' if ':' in ip else ip
                    pinned = urlunsplit((parsed.scheme, f'{authority}:{port}', parsed.path or '/', parsed.query, ''))
                    host_header = f'[{host}]' if ':' in host else host
                    if parsed.port:
                        host_header += f':{port}'
                    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, transport=self.transport,
                                                 timeout=self.timeout) as client:
                        async with client.stream('GET', pinned, headers={
                            'Host': host_header, 'Accept-Encoding': 'identity',
                            'Accept': 'application/json' if json_response else 'text/html,text/plain',
                            'User-Agent': 'NitrogenResearchAssistant/1.0'}, extensions={'sni_hostname': host}) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                if redirect == 3 or not response.headers.get('location'):
                                    raise FetchError('redirect_limit')
                                url = urljoin(url, response.headers['location'])
                                continue
                            if response.status_code != 200:
                                raise FetchError('http_error')
                            content_type = response.headers.get('content-type', '').lower()
                            if not any(t in content_type for t in (['application/json'] if json_response else ['text/html', 'text/plain', 'application/xhtml+xml'])):
                                raise FetchError('unsupported_content')
                            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                                raise FetchError('unsupported_encoding')
                            data = bytearray()
                            async for chunk in response.aiter_raw():
                                data.extend(chunk)
                                if len(data) > self.max_bytes:
                                    raise FetchError('body_too_large')
                            charset = re.search(r'charset=["\']?([\w-]+)', content_type)
                            try:
                                text = data.decode(charset.group(1) if charset else 'utf-8', errors='replace')
                            except LookupError:
                                text = data.decode('utf-8', errors='replace')
                            return {'url': urlunsplit((*urlsplit(url)[:4], '')), 'text': text,
                                    'sha256': hashlib.sha256(data).hexdigest(), 'content_type': content_type}
        except (TimeoutError, httpx.TimeoutException):
            raise FetchError('timeout') from None
        except (httpx.HTTPError, OSError):
            raise FetchError('fetch_failed') from None
        raise FetchError('fetch_failed')


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.body, self.title = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data):
        if 'title' in self.stack:
            self.title.append(data)
        elif not set(self.stack) & {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'head', 'svg', 'form'}:
            value = ' '.join(data.split())
            if value:
                self.body.append(value)


def extract_page(document):
    if 'html' in document['content_type']:
        parser = PageText()
        parser.feed(document['text'])
        return ' '.join(parser.title).strip(), '\n'.join(parser.body)
    return '', document['text'].strip()


@dataclass
class WebResult:
    status: str
    queries: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    provider: str = 'searxng'

    def snapshot(self):
        return {'status': self.status, 'queries': self.queries, 'sources': self.sources,
                'errors': self.errors, 'provider': self.provider}


class WebSearch:
    provider = 'searxng'
    query_limit = 400
    def __init__(self, *, enabled=False, endpoint='', timeout=30.0, max_queries=2, max_pages=5, fetcher=None):
        self.enabled, self.endpoint = enabled, endpoint
        self.timeout, self.max_queries, self.max_pages = timeout, max_queries, max_pages
        self.fetcher = fetcher or PublicFetcher()
        self._slots = asyncio.Semaphore(2)

    @property
    def ready(self):
        return bool(self.enabled and self.endpoint)

    async def search_hits(self, question):
        separator = '&' if '?' in self.endpoint else '?'
        response = await self.fetcher.get(self.endpoint + separator + urlencode({'q': question, 'format': 'json'}), json_response=True)
        data = json.loads(response['text'])
        hits = data.get('results', [])
        if not isinstance(hits, list):
            raise ValueError()
        return hits

    async def read_page(self, url):
        public_url(url)
        page = await self.fetcher.get(url)
        title, text = extract_page(page)
        return {**page, 'title': title, 'text': text}

    async def search(self, query):
        if not self.ready:
            return WebResult('not_configured', provider=self.provider)
        result = WebResult('running', provider=self.provider)
        seen = set()
        try:
            async with asyncio.timeout(self.timeout):
                async with self._slots:
                    for round_index in range(self.max_queries):
                        # Second query is a bounded source-oriented refinement, not an endless retry.
                        suffix = ' 教材 大学 科研' if round_index else ''
                        question = query.strip()[:self.query_limit - len(suffix)] + suffix
                        result.queries.append(question)
                        try:
                            hits = await self.search_hits(question)
                        except FetchError as exc:
                            result.errors.append(exc.code)
                            result.status = 'timeout' if exc.code == 'timeout' else 'provider_unavailable'
                            break
                        except (ValueError, TypeError, AttributeError):
                            result.errors.append('invalid_provider_response')
                            result.status = 'provider_unavailable'
                            break
                        # Prefer institutions, without claiming their content is correct by domain alone.
                        hits = sorted([h for h in hits if isinstance(h, dict)], key=lambda h: not bool(re.search(r'\.(?:edu|gov|ac)(?:\.|/)', str(h.get('url', '')))))
                        for hit in hits[:20]:
                            if len(result.sources) >= self.max_pages:
                                break
                            url = hit.get('url')
                            if not isinstance(url, str) or url in seen:
                                continue
                            seen.add(url)
                            item = {'url': url, 'title': str(hit.get('title', ''))[:500], 'publisher': '',
                                    'status': 'pending', 'retrieved_at': now(), 'evidence_level': 'search_summary',
                                    'search_summary': str(hit.get('content', ''))[:1500]}
                            result.sources.append(item)
                            try:
                                page = await self.read_page(url)
                                title, text = page['title'], page['text']
                                item.update(url=page['url'], title=title or item['title'], publisher=urlsplit(page['url']).hostname, retrieved_at=now(),
                                            sha256=page['sha256'], status='fetched' if len(text.strip()) >= 120 else 'insufficient_body',
                                            evidence_level='page_text', text=text[:6000], location='抽取页面文本字符 0..' + str(min(len(text), 6000)),
                                            acquisition=page.get('acquisition', 'direct_http'), content_format=page.get('content_format', 'text'),
                                            final_url_verified=page.get('final_url_verified', True))
                            except FetchError as exc:
                                item['status'] = exc.code
                                if exc.code in {'unauthorized', 'insufficient_balance', 'rate_limited'}:
                                    result.status = 'provider_unavailable'
                                    result.errors.append(exc.code)
                                    break
                        if result.status != 'running':
                            break
                        if any(s['status'] == 'fetched' for s in result.sources) or len(result.sources) >= self.max_pages:
                            break
        except TimeoutError:
            result.errors.append('total_timeout')
            result.status = 'timeout'
            for item in result.sources:
                if item['status'] == 'pending':
                    item['status'] = 'timeout'
        if result.status == 'running':
            result.status = ('fetched' if any(s['status'] == 'fetched' for s in result.sources) else 'no_results' if not result.sources
                             else 'timeout' if all(s['status'] == 'timeout' for s in result.sources)
                             else 'insufficient_body' if any(s['status'] == 'insufficient_body' for s in result.sources) else 'fetch_failed')
        return result
