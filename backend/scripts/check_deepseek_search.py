"""One live Search and at most one Fetch; never print the configured credential."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import settings
from src.retrieval.deepseek import create_web_search
from src.retrieval.web import WebResult, FetchError, now
from urllib.parse import urlsplit


async def check(query, output, fetch_url=None):
    local = settings.model_copy(update={'web_search_provider': 'deepseek', 'web_search_enabled': True,
                                       'web_search_max_queries': 1, 'web_search_max_pages': 1})
    diagnostics = []
    web = create_web_search(local, diagnostic=diagnostics.append)
    if fetch_url:
        result = WebResult('running', provider='deepseek')
        item = {'url': fetch_url, 'status': 'pending', 'retrieved_at': now()}
        result.sources.append(item)
        try:
            page = await web.read_page(fetch_url)
            item.update(page, publisher=urlsplit(fetch_url).hostname, evidence_level='page_text')
            item['text'] = page['text'][:6000]
            item['status'] = 'fetched' if len(page['text']) >= 120 else 'insufficient_body'
            result.status = item['status']
        except FetchError as exc:
            result.status = 'fetch_failed'
            result.errors.append(exc.code)
            item['status'] = exc.code
    else:
        result = await web.search(query)
    report = {**result.snapshot(), 'diagnostics': diagnostics, 'mode': 'live_provider_check', 'model_generation': False,
              'professional_quality': 'not_reviewed', 'limits': {'max_search': 0 if fetch_url else 1, 'max_fetch': 1}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result.status, 'provider': result.provider, 'errors': result.errors, 'diagnostics': diagnostics,
        'sources': [{k: s.get(k) for k in ('url', 'title', 'status', 'acquisition', 'sha256')} for s in result.sources],
        'report': str(output), 'professional_quality': 'not_reviewed'}, ensure_ascii=False, indent=2))
    return 0 if result.status == 'fetched' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-url', help='Fetch one previously discovered URL without another Search')
    parser.add_argument('--query', default='光合作用 基础定义')
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'var/handoff/deepseek-search-check.json')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.query, args.out, args.fetch_url)))


if __name__ == '__main__':
    main()
