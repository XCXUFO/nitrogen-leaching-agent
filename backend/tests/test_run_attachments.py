from io import BytesIO

import openpyxl
import pymupdf
from tests.test_evaluation import client, headers  # noqa: F401
from src.storage.run_store import RunStore


def submitted(client, raw, filename, session="attachment-review"):
    uploaded = client.post('/api/files', params={'filename': filename, 'session_id': session}, content=raw)
    assert uploaded.status_code == 200, uploaded.text
    receipt = uploaded.json()
    result = client.post('/api/chat', json={'query': '你能做什么？', 'session_id': session,
                                          'file_ids': [receipt['file_id']]})
    assert result.status_code == 200, result.text
    path = f"/api/eval/sessions/{session}/attachments/{result.json()['run_id']}/{receipt['sha256']}"
    return receipt, path


def test_document_preview_and_download_survive_release_and_database_reopen(client, tmp_path):
    raw = '作物：玉米\n灌溉记录：100 mm\n<script>alert(1)</script>'.encode()
    receipt, path = submitted(client, raw, '田间记录.txt')
    staged = client.app.state.file_store.entries[receipt['file_id']].original_path
    assert staged.exists()
    client.post('/api/files/release', json={'session_id': 'attachment-review', 'file_ids': [receipt['file_id']]})
    assert not staged.exists()
    preview = client.get(path + '/preview', headers=headers('alice'))
    assert preview.status_code == 200, preview.text
    assert preview.json() == {'kind': 'text', 'filename': '田间记录.txt', 'text': raw.decode()}
    assert preview.headers['cache-control'] == 'private, no-store'
    original = client.get(path + '/content', headers=headers('dev'))
    assert original.content == raw
    assert original.headers['content-disposition'].startswith("attachment; filename*=UTF-8''")
    assert original.headers['x-content-type-options'] == 'nosniff'
    reopened = RunStore(tmp_path / 'runs.sqlite3')
    try:
        assert reopened.attachments.get(receipt['sha256']) == raw
    finally:
        reopened.close()


def test_pdf_preview_has_real_page_images_and_page_navigation(client):
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50, 50), 'First page')
        pdf.new_page().insert_text((50, 50), 'Second page')
        raw = pdf.tobytes()
    _, path = submitted(client, raw, 'report.pdf')
    first = client.get(path + '/preview', headers=headers()).json()
    second = client.get(path + '/preview?page=2', headers=headers()).json()
    assert first['kind'] == 'pdf' and first['page_count'] == 2 and first['page'] == 1
    assert first['image'].startswith('data:image/png;base64,') and first['image'] != second['image']
    assert second['page'] == 2
    assert client.get(path + '/preview?page=3', headers=headers()).status_code == 422


def test_workbook_preview_preserves_coordinates_sheets_and_pagination_without_domain_validation(client):
    book = openpyxl.Workbook()
    book.active.title = '田间数据'
    for index in range(105):
        book.active.append([index, f'记录{index}', '=1+2'])
    book.create_sheet('其他工作表').append(['第二张表', 42])
    stream = BytesIO(); book.save(stream)
    _, path = submitted(client, stream.getvalue(), '通用数据.xlsx')
    first = client.get(path + '/preview', headers=headers()).json()
    assert first['sheets'] == ['田间数据', '其他工作表']
    assert first['total_rows'] == 105 and first['rows'][0] == [0, '记录0', '=1+2']
    assert len(first['rows']) == 100
    second = client.get(path + '/preview?offset=100', headers=headers()).json()
    assert len(second['rows']) == 5 and second['rows'][0][0] == 100
    other = client.get(path + '/preview?sheet=1', headers=headers()).json()
    assert other['rows'] == [['第二张表', 42]]


def test_preview_requires_login_and_exact_run_membership(client):
    _, first = submitted(client, b'first attachment', 'first.txt', session='first-session')
    receipt, second = submitted(client, b'second attachment', 'second.txt', session='second-session')
    assert client.get(first + '/preview').status_code == 401
    assert client.get(first + '/content').status_code == 401
    wrong_session = first.replace('/first-session/', '/second-session/')
    wrong_hash = first.rsplit('/', 1)[0] + '/' + receipt['sha256']
    for path in (wrong_session, wrong_hash):
        assert client.get(path + '/preview', headers=headers()).status_code == 404
        assert client.get(path + '/content', headers=headers()).status_code == 404
    assert client.get(second + '/preview', headers=headers()).status_code == 200


def test_missing_legacy_original_is_explicit_and_does_not_create_an_archive(client):
    receipt, path = submitted(client, b'removed original', 'legacy.txt')
    store = client.app.state.agent_runtime.runs
    with store._lock, store._connection:
        store._connection.execute('DELETE FROM run_attachment_blobs WHERE sha256=?', (receipt['sha256'],))
    result = client.get(path + '/preview', headers=headers())
    assert result.status_code == 404
    assert result.json()['detail']['code'] == 'attachment_original_missing'


def test_uploaded_but_unsubmitted_original_is_not_retained_in_run_history(client):
    receipt = client.post('/api/files', params={'filename': 'unsent.txt'}, content=b'unsent').json()
    assert client.app.state.agent_runtime.runs.attachments.get(receipt['sha256']) is None
