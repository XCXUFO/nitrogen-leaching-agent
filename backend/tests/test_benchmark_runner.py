"""The long evaluation runner renews auth without duplicating submissions."""
import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location('benchmark_runner',
    Path(__file__).resolve().parents[1] / 'scripts/run_github_benchmark.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.asyncio
async def test_expired_auth_replays_same_chat_identity_and_body_once():
    requests = []
    logins = []

    def respond(request):
        if request.url.path == '/api/eval/login':
            logins.append(request)
            return httpx.Response(200, json={'token': f'token-{len(logins)}', 'user': {'tester_id': 'test'}})
        requests.append(request)
        return httpx.Response(401 if request.headers['authorization'] == 'Bearer token-1' else 202,
            json={'run_id': 'same-run'})

    async with runner.RenewingClient(username='test', password='not-real', base_url='http://test',
            transport=httpx.MockTransport(respond)) as client:
        await client.login()
        response = await client.post('/api/chat', json={'request_id': 'stable', 'query': 'test'})
    assert response.status_code == 202
    assert len(logins) == len(requests) == 2
    assert requests[0].content == requests[1].content
    assert json.loads(requests[1].content)['request_id'] == 'stable'


@pytest.mark.asyncio
async def test_rejected_refreshed_credentials_stop_after_one_retry():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'token': 'refreshed', 'user': {}}) if request.url.path.endswith('login') else httpx.Response(401)

    async with runner.RenewingClient(username='test', password='not-real', base_url='http://test',
            transport=httpx.MockTransport(respond)) as client:
        response = await client.get('/api/eval/config')
    assert response.status_code == 401
    assert calls == ['/api/eval/config', '/api/eval/login', '/api/eval/config']


@pytest.mark.asyncio
async def test_simultaneous_auth_failures_share_a_single_renewal():
    logins = 0
    expired = 0
    both_expired = asyncio.Event()

    async def respond(request):
        nonlocal logins, expired
        if request.url.path.endswith('/login'):
            logins += 1
            return httpx.Response(200, json={'token': str(logins), 'user': {}})
        if request.headers['authorization'] == 'Bearer 1':
            expired += 1
            if expired == 2:
                both_expired.set()
            await both_expired.wait()
            return httpx.Response(401)
        return httpx.Response(200)

    async with runner.RenewingClient(username='test', password='not-real', base_url='http://test',
            transport=httpx.MockTransport(respond)) as client:
        await client.login()
        responses = await asyncio.gather(client.get('/api/eval/config'), client.get('/api/chat/runs/stable'))
    assert logins == 2 and expired == 2
    assert all(r.status_code == 200 for r in responses)
