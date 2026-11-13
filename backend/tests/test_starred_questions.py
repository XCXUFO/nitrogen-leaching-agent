from tests.test_evaluation import client, headers


def test_starred_questions_create_edit_and_persist(client):
    path = "/api/eval/starred-questions"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers()).json() == []
    assert client.post(path, headers=headers(), json={"question": "  ", "answer": ""}).status_code == 422

    first = client.post(path, headers=headers(), json={"question": "第一行\n第二行", "answer": ""})
    second = client.post(path, headers=headers(), json={"question": "另一问题", "answer": "原有答案"})
    assert first.status_code == second.status_code == 201
    first_id, second_id = first.json()["question_id"], second.json()["question_id"]
    assert first.json()["revision"] == 1
    updated = client.put(f"{path}/{first_id}", headers=headers(), json={"question": "第一行\n第二行", "answer": "补录\n答案", "expected_revision": 1})
    assert updated.status_code == 200
    assert updated.json()["answer"] == "补录\n答案"
    assert updated.json()["revision"] == 2
    assert client.put(f"{path}/missing", headers=headers(), json={"question": "问题", "answer": "", "expected_revision": 1}).status_code == 404
    assert client.put(f"{path}/{first_id}", headers=headers(), json={"question": "", "answer": ""}).status_code == 422
    rows = client.get(path, headers=headers()).json()
    assert len(rows) == 2
    assert {row["question_id"]: row["answer"] for row in rows} == {first_id: "补录\n答案", second_id: "原有答案"}
    assert client.app.state.evaluation.store.starred_questions() == rows


def test_developer_edit_conflicts_and_read_only_reload_latest_revision(client):
    path = '/api/eval/starred-questions'
    original = client.post(path, headers=headers(), json={'question': '原始问题', 'answer': '原始答案'}).json()
    stale = client.get(path, headers=headers('bob')).json()[0]
    url = f"{path}/{original['question_id']}"
    assert client.put(url, headers=headers('expert'), json={'question': '不能修改', 'answer': '', 'expected_revision': 1}).status_code == 403
    saved = client.put(url, headers=headers('dev'), json={
        'question': original['question'], 'answer': '专家补录答案', 'expected_revision': original['revision'],
    })
    assert saved.status_code == 200
    assert client.put(url, headers=headers('dev'), json={
        'question': '修改问题措辞', 'answer': stale['answer'], 'expected_revision': stale['revision'],
    }).json()['detail']['code'] == 'starred_question_conflict'
    assert client.put(url, headers=headers('dev'), json={
        'question': '旧客户端', 'answer': stale['answer'],
    }).status_code == 422  # Missing revisions cannot bypass conflict protection.
    latest = client.get(path, headers=headers('bob')).json()[0]
    assert latest['answer'] == '专家补录答案' and latest['revision'] == 2
    merged = client.put(url, headers=headers('dev'), json={
        'question': '修改问题措辞', 'answer': latest['answer'], 'expected_revision': latest['revision'],
    })
    assert merged.status_code == 200
    assert merged.json()['revision'] == 3 and merged.json()['answer'] == '专家补录答案'


def test_legacy_starred_questions_migrate_and_cas_across_connections(tmp_path):
    import sqlite3
    import pytest
    from fastapi import HTTPException
    from src.evaluation.store import EvaluationStore
    from src.storage.run_store import RunStore

    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE eval_starred_questions (question_id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
        db.execute("INSERT INTO eval_starred_questions VALUES ('legacy','原始问题','原始答案','2026-10-16','2026-10-16')")
    first, second = RunStore(path), RunStore(path)
    try:
        a, b = EvaluationStore(first), EvaluationStore(second)
        snapshot = b.starred_questions()[0]
        assert snapshot['revision'] == 1 and snapshot['answer'] == '原始答案'
        a.update_starred_question('legacy', snapshot['question'], '专家补录答案', 1)
        with pytest.raises(HTTPException) as conflict:
            b.update_starred_question('legacy', '修改问题措辞', snapshot['answer'], 1)
        assert conflict.value.status_code == 409
        # Reinitialization must preserve the version and expert's content.
        assert EvaluationStore(second).starred_questions()[0]['revision'] == 2
        assert a.starred_questions()[0]['answer'] == '专家补录答案'
    finally:
        first.close()
        second.close()


def test_reuse_metadata_preserved_for_old_clients_and_cas_protected(client):
    path='/api/eval/starred-questions'
    reuse={'reuse_status':'reference','coverage_scope':'仅解释区分尺度的原因','excluded_scope':'模型构建',
           'source_refs':['材料 T4'],'variants':['为何区分尺度？'],'profile':'scale_models'}
    created=client.post(path,headers=headers(),json={'question':'为何区分农田与区域尺度？','answer':'维护答复','reuse':reuse}).json()
    assert created['reuse']['professional_review']=='unknown'
    url=path+'/'+created['question_id']
    changed=client.put(url,headers=headers(),json={'question':created['question'],'answer':'新答复','expected_revision':1})
    assert changed.status_code==200 and changed.json()['reuse']==created['reuse']
    stale=client.put(url,headers=headers(),json={'question':created['question'],'answer':'旧答复','expected_revision':1,'reuse':{'reuse_status':'pending'}})
    assert stale.status_code==409
    assert client.get(path,headers=headers()).json()[0]['reuse']['reuse_status']=='reference'
    assert client.post(path,headers=headers(),json={'question':'新题','reuse':{'reuse_status':'invalid'}}).status_code==422
    assert client.post(path,headers=headers(),json={'question':'新题','reuse':{'professional_review':'reviewed'}}).status_code==422
