from io import BytesIO
from zipfile import ZipFile
import re
import pytest
from src.model_tools.workbooks import read_workbook, WorkbookError
from src.model_tools.whcns_results import summarize_result
from tests.test_whcns_results import make_nitrogen
from tests.test_literature_http import client, create, upload


def rewrite_sheet(path, dimension):
    with ZipFile(BytesIO(path.read_bytes())) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    entries['xl/worksheets/sheet1.xml'] = re.sub(rb'<dimension[^>]*/>', dimension, entries['xl/worksheets/sheet1.xml'])
    with ZipFile(path, 'w') as target:
        for name, data in entries.items(): target.writestr(name, data)


@pytest.mark.parametrize('dimension', [b'<dimension ref="A1:I2"/>', b'<dimension ref="A1:B2"/>', b'', b'<dimension ref="A1:XFD1048576"/>'])
def test_actual_coordinates_override_dimensions(tmp_path, dimension):
    path = make_nitrogen(tmp_path / 'dimension.xlsx')
    rewrite_sheet(path, dimension)
    sheet = read_workbook(path)['sheets'][0]
    assert (sheet['nrows'], sheet['ncols']) == (3, 9)
    report = summarize_result(path, kind='nitrogen')
    nitrate = next(c for c in report['columns'] if c['header'].startswith('leak_NO3'))
    assert nitrate['raw_column_sum'] == 2 and nitrate['max']['value'] == 1.5


@pytest.mark.parametrize('cell', ['A1048576', 'XFD100'])
def test_sparse_sheet_bounded_before_allocation(tmp_path, cell):
    path = make_nitrogen(tmp_path / 'sparse.xlsx', edit=lambda sheet: setattr(sheet[cell], 'value', 1))
    rewrite_sheet(path, b'<dimension ref="A1"/>')
    with pytest.raises(WorkbookError, match='cell limit'): read_workbook(path)


def test_stale_edit_preserves_metadata_tags_and_file(client):
    paper, raw = create(client, 'original')
    path = f"/api/literature/papers/{paper['id']}"
    dim = client.post('/api/literature/dimensions', json={'name': 'topic'}).json()['id']
    tag = client.post(f'/api/literature/dimensions/{dim}/tags', json={'name': 'A'}).json()['id']
    saved = client.put(path, json={**paper, 'title': 'corrected', 'tag_ids': [tag]}).json()
    assert saved['revision'] == paper['revision'] + 1
    replacement, _ = upload(client, 'replacement')
    stale = client.put(path, json={**paper, 'internal_note': 'stale note', 'upload_id': replacement})
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'paper_revision_conflict'
    current = client.get(path).json()
    assert current['title'] == 'corrected' and current['tag_ids'] == [tag]
    assert current['internal_note'] == '' and current['revision'] == saved['revision']
    assert client.get(path + '/file').content == raw
    assert len(current['events']) == len(saved['events'])
    assert client.put(path, json={'title': 'unversioned'}).status_code == 422
    assert client.put(path, json={**current, 'expected_revision': paper['revision']}).status_code == 409
    assert client.put(path, json={**current, 'internal_note': 'reviewed'}).status_code == 200
    latest = client.get(path).json()
    client.post(path + '/disable', json={'reason': 'archive'})
    assert client.put(path, json=latest).status_code == 409


@pytest.mark.parametrize('prefix', ['created', 'updated'])
def test_beijing_calendar_date_boundaries(client, prefix):
    instants = ['2026-10-10T15:59:59+00:00', '2026-10-10T16:00:00+00:00', '2026-10-11T15:59:59+00:00', '2026-10-11T16:00:00+00:00']
    ids = []
    db = client.app.state.literature.db
    for i, instant in enumerate(instants):
        paper, _ = create(client, f'boundary-{i}')
        ids.append(paper['id'])
        with db: db.execute(f'UPDATE papers SET {prefix}_at=? WHERE id=?', (instant, paper['id']))
    response = client.get('/api/literature/papers', params={prefix + '_from': '2026-10-11', prefix + '_to': '2026-10-11'})
    assert response.status_code == 200
    assert {p['id'] for p in response.json()['items']} == set(ids[1:3])
    for params in [{prefix + '_from': '2026-02-30'}, {prefix + '_from': '2026-10-12', prefix + '_to': '2026-10-11'}]:
        assert client.get('/api/literature/papers', params=params).status_code == 422


def test_existing_library_revision_migration_preserves_record_and_file(tmp_path):
    from src.api.literature import LiteratureStore, PaperInput, create_paper
    from tests.test_literature import FakeRequest, upload_pdf
    from src.evaluation.contracts import Principal
    user = Principal(tester_id='migration-test', role='developer')
    database, files = tmp_path / 'library.sqlite3', tmp_path / 'files'
    db = LiteratureStore(str(database), str(files))
    original = create_paper(FakeRequest(db), PaperInput(upload_id=upload_pdf(db, user)), user)
    db.db.execute('ALTER TABLE papers DROP COLUMN revision')
    db.db.commit()
    db.close()
    migrated = LiteratureStore(str(database), str(files))
    try:
        assert migrated.get_paper(original['id'], full=True) == original
        assert (files / f"blob-{original['sha256']}.pdf").is_file()
    finally: migrated.close()
