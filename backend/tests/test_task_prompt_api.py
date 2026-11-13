from tests.test_evaluation import client, headers  # noqa: F401
from src.api import explanation_trials
from src.agent.task_prompts import DEFAULT_TASKS


def test_task_versions_are_developer_only_and_scoped_activation_is_explicit(client):
    client.app.include_router(explanation_trials.router, prefix='/api')
    endpoint = '/api/eval/task-prompts'
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=headers('alice')).status_code == 403
    assert client.get(endpoint, headers=headers('expert')).status_code == 403
    initial = client.get(endpoint, headers=headers('dev')).json()
    assert set(initial['active']) == set(DEFAULT_TASKS)
    payload = {'scope': 'concept_explanation', 'label': '入门候选', 'text': '先解释概念，再引导。'}
    assert client.post(endpoint, headers=headers('alice'), json=payload).status_code == 403
    saved = client.post(endpoint, headers=headers('dev'), json=payload)
    assert saved.status_code == 201
    identifier = saved.json()['prompt_id']
    assert client.get(endpoint, headers=headers('dev')).json()['active'] == initial['active']
    activation = endpoint + '/concept_explanation/active'
    assert client.put(activation, headers=headers('alice'), json={'prompt_id': identifier}).status_code == 403
    assert client.put(endpoint + '/knowledge_search/active', headers=headers('dev'), json={'prompt_id': identifier}).status_code == 422
    assert client.put(activation, headers=headers('dev'), json={'prompt_id': identifier}).status_code == 200
    current = client.get(endpoint, headers=headers('dev')).json()
    assert current['active']['concept_explanation']['prompt_id'] == identifier
    assert current['active']['case_assistant'] == initial['active']['case_assistant']
    for field in ('task_prompt_ids', 'prompt_id', 'expression_config'):
        assert client.post('/api/chat', json={'query': 'WHCNS模型', field: 'private'}).status_code == 422
