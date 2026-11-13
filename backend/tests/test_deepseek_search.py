import json

import httpx
import pytest

from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.config import Settings
from src.evaluation.versioning import build_manifest
from src.retrieval.deepseek import DeepSeekWebSearch, create_web_search, ORIGIN
from src.retrieval.web import WebSearch
from tests.test_web_retrieval import public_dns
from tests.test_web_answers import Model, Local, QUOTE, BODY

KEY = 'synthetic-secret-never-export'
URL = 'https://university.example/lesson'


def adapter(handler, **kwargs):
    return DeepSeekWebSearch(enabled=True, api_key=KEY, transport=httpx.MockTransport(handler), resolver=public_dns, **kwargs)


@pytest.mark.asyncio
async def test_official_post_schemas_shared_key_real_fetch_not_search_summary():
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(ORIGIN + '/v1/tools/') and request.method == 'POST'
        assert request.headers['Authorization'] == 'Bearer ' + KEY
        data = json.loads(request.content)
        if request.url.path.endswith('/search'):
            assert data['count'] == 5 and data['need_content'] is False and len(data['query']) <= 128
            return httpx.Response(200, json={'results': [{'url': URL, 'title': '搜索题名', 'summary': '只是摘要', 'content': '不能当成已读正文'}]})
        assert data == {'url': URL}
        return httpx.Response(200, json={'title': '实际 Fetch 题名', 'content': BODY})
    result = await adapter(handler).search('解释光合作用')
    assert len(calls) == 2 and result.status == 'fetched' and result.provider == 'deepseek'
    page = result.sources[0]
    assert page['title'] == '实际 Fetch 题名' and page['text'] == BODY and page['search_summary'] == '只是摘要'
    assert page['acquisition'] == 'deepseek_fetch' and page['content_format'] == 'markdown'
    assert page['final_url_verified'] is False
    assert KEY not in json.dumps(result.snapshot(), ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401, 'unauthorized'), (402, 'insufficient_balance'), (429, 'rate_limited'), (500, 'provider_unavailable')])
async def test_provider_failures_are_sanitized_and_not_retried(status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': KEY}})
    result = await adapter(handler).search('光合作用')
    assert result.status == 'provider_unavailable' and result.errors == [code] and len(calls) == 1
    assert KEY not in json.dumps(result.snapshot())


@pytest.mark.asyncio
async def test_query_limit_pages_empty_results_and_no_key():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'results': []})
    result = await adapter(handler).search('氮' * 400)
    assert result.status == 'no_results' and len(calls) == 2
    assert all(len(c['query']) <= 128 for c in calls)
    assert (await DeepSeekWebSearch(enabled=True).search('test')).status == 'not_configured'
    assert not DeepSeekWebSearch(enabled=False, api_key=KEY).ready


@pytest.mark.asyncio
async def test_redirect_does_not_forward_credentials_and_private_target_is_not_fetched():
    calls = []
    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location': 'https://attacker.example/'})
    result = await adapter(redirect).search('光合作用')
    assert result.status == 'provider_unavailable' and len(calls) == 1
    async def private(host, port):
        return ['127.0.0.1']
    calls.clear()
    def search(request):
        calls.append(request)
        return httpx.Response(200, json={'results': [{'url': 'http://127.0.0.1/admin'}]})
    web = DeepSeekWebSearch(enabled=True, api_key=KEY, resolver=private, transport=httpx.MockTransport(search))
    result = await web.search('光合作用')
    assert all(r.url.path.endswith('/search') for r in calls)
    assert result.sources[0]['status'] == 'blocked_address'


@pytest.mark.asyncio
async def test_fetch_short_body_and_provider_auth_failure_stop_additional_pages():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'results': [{'url': URL}, {'url': URL + '/next'}]})
        return httpx.Response(402, json={'error': {'message': KEY}})
    result = await adapter(handler).search('光合作用')
    assert len(calls) == 2 and result.errors == ['insufficient_balance']
    def short(request):
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'results': [{'url': URL}]})
        return httpx.Response(200, json={'title': '只有标题', 'content': ''})
    result = await adapter(short).search('光合作用')
    assert result.status == 'insufficient_body' and not any(p['status'] == 'fetched' for p in result.sources)


@pytest.mark.asyncio
async def test_adapter_reaches_existing_answer_evidence_and_account_failure_preserves_local():
    def handler(request):
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'results': [{'url': URL}]})
        return httpx.Response(200, json={'title': '实际 Fetch 题名', 'content': BODY})
    runtime = AgentRuntime(web=adapter(handler))
    response = await runtime.execute(ChatRequest(query='联网查菜地N2O排放规律'), service=Local(), get_report=None, llm=Model())
    assert response.citations[0].snippet == QUOTE and response.citations[0].source == URL
    trace = runtime.runs.get(response.run_id)
    assert any(r.get('provider') == 'deepseek' for r in trace.web_retrieval)
    runtime.web = adapter(lambda request: httpx.Response(401, json={'error': {'message': KEY}}))
    response = await runtime.execute(ChatRequest(query='联网查菜地N2O排放规律'), service=Local(), get_report=None, llm=Model())
    assert '原有可支持内容' in response.answer and '鉴权失败' in response.answer
    assert KEY not in response.model_dump_json()
    runtime.runs.close()


def test_factory_defaults_backward_compatibility_and_manifest_does_not_export_key():
    settings = Settings(_env_file=None, web_search_enabled=True, web_search_provider='deepseek', deepseek_api_key=KEY)
    web = create_web_search(settings)
    assert isinstance(web, DeepSeekWebSearch) and web.ready
    assert KEY not in json.dumps(build_manifest(settings))
    settings.web_search_provider = 'searxng'
    settings.web_search_url = 'https://search.example/search'
    assert type(create_web_search(settings)) is WebSearch


@pytest.mark.asyncio
async def test_empty_proxy_matches_existing_rag_client_and_diagnostics_never_export_key():
    diagnostics = []
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer ' + KEY
        return httpx.Response(200, json={'results': []})
    web = DeepSeekWebSearch(enabled=True, api_key=KEY, proxy='', transport=httpx.MockTransport(handler), diagnostic=diagnostics.append)
    result = await web.search('光合作用')
    assert result.status == 'no_results'
    assert diagnostics and KEY not in json.dumps(diagnostics)


@pytest.mark.asyncio
async def test_invalid_json_oversized_payload_and_fetch_no_content_remain_distinct():
    invalid = await adapter(lambda r: httpx.Response(200, content=b'not json')).search('光合作用')
    assert invalid.errors == ['invalid_provider_response']
    oversized = await adapter(lambda r: httpx.Response(200, json={'results': [], 'content': 'x' * 200}), max_bytes=100).search('光合作用')
    assert oversized.errors == ['body_too_large']
    def missing(request):
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'results': [{'url': URL}]})
        return httpx.Response(404, json={'error': {'message': KEY}})
    result = await adapter(missing).search('光合作用')
    assert result.sources[0]['status'] == 'no_content' and not any(s['status'] == 'fetched' for s in result.sources)


@pytest.mark.asyncio
async def test_remote_fetch_does_not_use_local_proxy_fake_dns_and_still_rejects_literal_private_urls():
    calls = []
    async def fake_dns(*args):
        raise AssertionError('remote Fetch must not resolve the target through local fake DNS')
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'title': '正文题名', 'content': BODY})
    web = DeepSeekWebSearch(enabled=True, api_key=KEY, transport=httpx.MockTransport(handler), resolver=fake_dns)
    page = await web.read_page(URL)
    assert page['text'] == BODY and len(calls) == 1
    from src.retrieval.web import FetchError
    for url in ('http://127.0.0.1/secret', 'http://169.254.169.254/', 'http://[::1]/', 'http://2130706433/', 'http://0177.0.0.1/'):
        with pytest.raises(FetchError):
            await web.read_page(url)
    assert len(calls) == 1
