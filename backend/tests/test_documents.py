import json

import httpx
import pytest
from fastapi import FastAPI

from src.api.documents import router
from src.rag import documents as catalog


@pytest.fixture
def library(tmp_path, monkeypatch):
    papers = tmp_path / 'papers'
    papers.mkdir()
    (papers / 'paper.pdf').write_bytes(b'%PDF-1.4\noriginal\n%%EOF')
    manifest = tmp_path / 'catalog.json'
    manifest.write_text(json.dumps([{'file': 'paper.pdf', 'title': '真实文章标题',
                                    'lead_author': 'Li', 'pdf_meta_author': 'Li Ming', 'year': '2024'}]))
    monkeypatch.setattr(catalog, 'PAPERS_DIR', papers)
    monkeypatch.setattr(catalog, 'CATALOG', manifest)
    catalog.documents.cache_clear()
    yield papers
    catalog.documents.cache_clear()


def test_metadata_uses_catalog_and_does_not_invent_missing_fields(library):
    metadata = catalog.citation_metadata(r'data\papers\paper.pdf')
    assert metadata['title'] == '真实文章标题'
    assert metadata['author_hint'] == 'Li Ming'
    assert metadata['year'] == '2024'
    assert metadata['document_available']
    assert catalog.citation_metadata('private_2020_author.pdf')['title'] is None
    (library / 'paper.pdf').unlink()
    assert not catalog.citation_metadata('paper.pdf')['document_available']


@pytest.mark.asyncio
async def test_preview_download_missing_and_path_confinement(library, tmp_path):
    app = FastAPI()
    app.include_router(router, prefix='/api')
    identifier = catalog.citation_metadata('paper.pdf')['document_id']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        preview = await client.get(f'/api/documents/{identifier}')
        assert preview.status_code == 200
        assert preview.headers['content-type'] == 'application/pdf'
        assert preview.headers['content-disposition'].startswith('inline;')
        assert preview.content == (library / 'paper.pdf').read_bytes()
        download = await client.get(f'/api/documents/{identifier}?download=true')
        assert download.headers['content-disposition'].startswith('attachment;')
        assert 'paper.pdf' not in download.headers['content-disposition']
        assert (await client.get('/api/documents/unknown')).status_code == 404
        assert (await client.get('/api/documents/%2e%2e%2fsecrets')).status_code == 404
        (library / 'paper.pdf').unlink()
        assert (await client.get(f'/api/documents/{identifier}')).status_code == 404
        outside = tmp_path / 'outside.pdf'
        outside.write_bytes(b'private')
        (library / 'paper.pdf').symlink_to(outside)
        assert (await client.get(f'/api/documents/{identifier}')).status_code == 404


def test_legacy_filename_number_is_not_an_author(library, monkeypatch):
    monkeypatch.setattr(catalog, 'article_label', lambda _: ('old filename', '022170'))
    catalog.documents.cache_clear()
    assert catalog.citation_metadata('paper.pdf')['author_hint'] == 'Li Ming'


@pytest.mark.asyncio
async def test_chat_enriches_presentation_without_changing_answer_or_citation_count(library):
    from types import SimpleNamespace
    from src.api.chat import router as chat_router
    from src.api.chat_schema import ChatResponse
    from src.agent.chat_service import Citation
    from src.llm.base import ChatUsage

    original = '原回答 [1] 和 [2]'

    async def execute(*args, **kwargs):
        return ChatResponse(answer=original, citations=[
            Citation(index=i, source='paper.pdf', chunk_id=f'chunk-{i}', score=.8, snippet='internal')
            for i in (1, 2)
        ], usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            retrieved_count=2, model='test')

    app = FastAPI()
    app.state.agent_runtime = SimpleNamespace(execute=execute)
    app.include_router(chat_router, prefix='/api')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/chat', json={'query': '查看文献'})
    assert response.status_code == 200
    body = response.json()
    assert body['answer'] == original
    assert len(body['citations']) == 2
    assert body['citations'][0]['document_id'] == body['citations'][1]['document_id']
    assert body['citations'][0]['title'] == '真实文章标题'
    assert body['citations'][0]['year'] == '2024'
    assert body['citations'][0]['document_available']
