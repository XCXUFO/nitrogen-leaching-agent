import json

import pytest
from fastapi.testclient import TestClient

from src.llm.base import ChatResult, ChatUsage
from tests.literature_fixture import TOKENS, create_app
from tests.test_literature_extract import pdf_bytes


class TagLLM:
    tag_ids = []
    messages = []
    response = None

    async def chat(self, messages, **kwargs):
        self.messages = messages
        return ChatResult(content=self.response or json.dumps({"tag_ids": self.tag_ids}), model="test",
                          usage=ChatUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20))


@pytest.fixture
def tagging(tmp_path):
    app = create_app(tmp_path)
    app.state.llm = TagLLM()
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['developer']}"
        yield client, app.state.llm
    app.state.literature.close()


def dimension(client, name, selection="multiple", enabled=True):
    return client.post("/api/literature/dimensions", json={"name": name, "selection": selection, "enabled": enabled}).json()["id"]


def tag(client, dim, name, parent=None, enabled=True):
    return client.post(f"/api/literature/dimensions/{dim}/tags", json={"name": name, "parent_id": parent, "enabled": enabled}).json()["id"]


def upload(client):
    response = client.post("/api/literature/uploads?filename=tagging.pdf", content=pdf_bytes(
        "Nitrogen leaching in maize fields. Irrigation influenced nitrate losses at the study site."))
    assert response.status_code == 200
    return response.json()["upload_id"]


def test_tagging_uses_existing_enabled_labels_preserves_manual_selection_and_saves(tagging):
    client, llm = tagging
    crop = dimension(client, "作物", "single")
    maize, wheat = tag(client, crop, "玉米"), tag(client, crop, "小麦")
    topic = dimension(client, "主题")
    parent = tag(client, topic, "氮")
    child = tag(client, topic, "氮素淋失", parent)
    disabled = tag(client, topic, "已停用", enabled=False)
    hidden = tag(client, dimension(client, "停用维度", enabled=False), "不可选")
    paper = client.post("/api/literature/papers", json={"upload_id": upload(client), "tag_ids": [maize]}).json()
    llm.tag_ids = [wheat, parent, child, child, disabled, hidden, "invented-tag"]
    body = {"paper_id": paper["id"], "tag_ids": [maize], "title": "人工标题", "abstract": "人工摘要", "conclusion": "人工结论"}
    response = client.post("/api/literature/suggest-tags", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["tag_ids"] == [maize, child]
    assert response.json()["added_tag_ids"] == [child]
    sent = json.loads(llm.messages[1].content)
    assert sent["fields"]["conclusion"] == "人工结论"
    assert "Nitrogen leaching" in sent["pdf_text"]
    assert disabled not in [item["id"] for item in sent["taxonomy"]["tags"]]
    assert hidden not in [item["id"] for item in sent["taxonomy"]["tags"]]
    path = f"/api/literature/papers/{paper['id']}"
    assert client.get(path).json()["tag_ids"] == [maize]
    saved = client.put(path, json={**paper, "tag_ids": response.json()["tag_ids"]})
    assert saved.status_code == 200, saved.text
    assert set(client.get(path).json()["tag_ids"]) == {maize, child}
    # A manual parent tag stays selected when AI suggests a descendant.
    response = client.post("/api/literature/suggest-tags", json={**body, "tag_ids": [maize, parent]})
    assert response.json()["tag_ids"] == [maize, parent]


def test_tagging_requires_login_owned_file_taxonomy_and_available_ai(tagging):
    client, llm = tagging
    target = {"upload_id": upload(client)}
    path = "/api/literature/suggest-tags"
    assert client.post(path, json=target, headers={"Authorization": ""}).status_code == 401
    assert client.post(path, json=target, headers={"Authorization": f"Bearer {TOKENS['reviewer']}"}).status_code == 403
    assert client.post(path, json=target, headers={"Authorization": f"Bearer {TOKENS['other-developer']}"}).status_code == 404
    assert client.post(path, json=target).json()["detail"]["code"] == "no_available_tags"
    label = tag(client, dimension(client, "主题"), "氮素淋失")
    assert client.post(path, json={**target, "tag_ids": ["missing"]}).status_code == 422
    client.app.state.llm = None
    assert client.post(path, json=target).status_code == 503
    client.app.state.llm = llm
    llm.response = "not JSON"
    assert client.post(path, json={**target, "tag_ids": [label]}).status_code == 502
    llm.response = '{"tag_ids": []}'
    assert client.post(path, json={**target, "tag_ids": [label]}).json()["tag_ids"] == [label]


def test_single_dimension_and_taxonomy_changes_during_inference(tagging):
    client, llm = tagging
    dim = dimension(client, "作物", "single")
    maize, wheat = tag(client, dim, "玉米"), tag(client, dim, "小麦")
    target = {"upload_id": upload(client)}
    llm.tag_ids = [maize, wheat]
    assert client.post("/api/literature/suggest-tags", json=target).json()["tag_ids"] == [maize]

    class DisablingLLM(TagLLM):
        async def chat(self, messages, **kwargs):
            with client.app.state.literature.write():
                client.app.state.literature.db.execute("UPDATE tags SET enabled=0 WHERE id=?", (maize,))
            self.tag_ids = [maize, wheat]
            return await super().chat(messages, **kwargs)

    client.app.state.llm = DisablingLLM()
    assert client.post("/api/literature/suggest-tags", json=target).json()["tag_ids"] == [wheat]
