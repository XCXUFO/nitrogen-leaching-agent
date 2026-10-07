"""P00 session attachments: fresh requests and real source workbooks, no reused reviews."""
from pathlib import Path
import time

import pytest

from tests.test_agent_runtime import client, upload

PACKAGE = Path(__file__).resolve().parents[2] / 'data/demo'


def ask(client, query, tokens=None, session='new-session'):
    payload = {'query': query, 'session_id': session}
    if tokens is not None:
        payload['file_ids'] = tokens
    response = client.post('/api/chat', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def real_upload(client, filename):
    response = client.post('/api/files', params={'filename': filename}, content=(PACKAGE / filename).read_bytes())
    assert response.status_code == 200, response.text
    return response.json()['file_id']


def test_auto_find_multiple_files_and_keep_followup(client):
    n = real_upload(client, 'Nbal_out.xls')
    w = real_upload(client, 'waterbal_out.xls')
    maximum = ask(client, '硝态氮最大值及日序', [w, n])
    assert maximum['file_evidence'][0]['value'] == pytest.approx(3.65926384925842)
    minimum = ask(client, '那最小值呢？')  # Omission retains registered session files.
    fact = minimum['file_evidence'][0]
    assert (fact['value'], fact['model_day'], fact['occurrences'], fact['cell']) == (0, 2, 191, 'Nbal_out!C3')
    rain = ask(client, 'PREC 最大值及日序')
    assert (rain['file_evidence'][0]['value'], rain['file_evidence'][0]['model_day']) == (86, 276)
    combined = ask(client, '硝态氮最大值及日序，PREC 最大值及日序')
    assert len(combined['file_evidence']) == 2
    mismatch = ask(client, 'Nbal_out.xls 中 PREC 最大值')
    assert mismatch['file_evidence'] == mismatch['citations'] == []
    assert 'PREC' in mismatch['answer']
    fresh = ask(client, '那最小值呢？', [], session='another-session')
    assert fresh['citations'] == fresh['file_evidence'] == []
    assert '上传' in fresh['answer']


def test_expired_or_invalid_file_does_not_replace_valid_target(client, tmp_path):
    n = upload(client, tmp_path)
    invalid = upload(client, tmp_path, name='broken.xlsx', edit=lambda sheet: setattr(sheet['C2'], 'value', 'bad'))
    result = ask(client, 'leak_NO3 最大值', [n, invalid, 'expired'])
    assert result['file_evidence'][0]['value'] == 1.5
    assert [item['status'] for item in result['attachments']] == ['ready', 'invalid', 'expired']
    client.app.state.file_store.entries[n].expires_at = time.monotonic() - 1
    result = ask(client, '那最小值呢？')
    assert result['file_evidence'] == result['citations'] == []
    assert '重新上传' in result['answer']


def test_same_named_different_files_are_both_analyzed_and_followup_clarifies(client, tmp_path):
    first = upload(client, tmp_path)
    second = upload(client, tmp_path, edit=lambda sheet: setattr(sheet['C3'], 'value', 9))
    result = ask(client, 'leak_NO3 最大值', [first, second])
    assert [item['value'] for item in result['file_evidence']] == [1.5, 9]
    assert ask(client, '那最小值呢？')['file_evidence'] == []


@pytest.mark.parametrize('query', ['它能解决什么问题？', '这个有什么用？', '那最小值呢？'])
def test_missing_context_never_retrieves_literature(client, query):
    result = ask(client, query, [])
    assert result['route'] == 'clarification'
    assert result['citations'] == []
    assert client.app.state.chat_service.calls == []


def test_pdf_exact_followup_uses_session_inventory_without_literature(client, tmp_path):
    token = upload(client, tmp_path)
    ask(client, '硝态氮最大值及日序', [token])
    result = ask(client, '有其他信息不')
    assert 'Nbal_out.xlsx' in result['answer'] and 'leak_NH4' in result['answer']
    assert '无需再次上传' in result['answer']
    assert result['citations'] == []
    assert client.app.state.chat_service.calls == []
    result = ask(client, '有其他信息不', [], session='empty-session')
    assert result['route'] == 'clarification'
    assert result['citations'] == []


def test_multiple_field_operations_preserve_scope_and_constraints(client):
    n = real_upload(client, 'Nbal_out.xls')
    w = real_upload(client, 'waterbal_out.xls')
    result = ask(client, '硝态氮和 PREC 的最大值及日序', [n, w])
    assert len(result['file_evidence']) == 2
    result = ask(client, 'Nbal_out.xls 中 PREC 最大值，waterbal_out.xls 中硝态氮最大值')
    assert result['file_evidence'] == []
    result = ask(client, '硝态氮最大值和 PREC 最小值')
    assert result['file_evidence'] == []
    result = ask(client, '前10天硝态氮和PREC最大值')
    assert result['file_evidence'] == []


def test_followup_recovers_subject_from_user_history_but_recomputes_values(client, tmp_path):
    token = upload(client, tmp_path)
    result = client.post('/api/chat', json={'query': '那最小值呢？', 'session_id': 'context-session', 'file_ids': [token],
                         'history': [{'role': 'user', 'content': '硝态氮淋失是什么意思？'},
                                     {'role': 'assistant', 'content': '最小值为 999。'}]}).json()
    assert result['file_evidence'][0]['value'] == 0.5
