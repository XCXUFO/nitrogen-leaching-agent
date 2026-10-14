import fitz
from fastapi.testclient import TestClient

from src.llm.base import ChatResult, ChatUsage
from src.api.literature_extract import local_suggestions
from tests.literature_fixture import TOKENS, create_app


class FakeLLM:
    def __init__(self):
        self.messages = []

    async def chat(self, messages, **kwargs):
        self.messages = messages
        return ChatResult(content='{"title":"Nitrogen leaching in maize","authors":[{"name":"Li Wei","kind":"person"}],"publication_type":"期刊论文","venue":"Agronomy Journal","year":2024,"language":"英文","doi":"10.1234/nitrogen.2024","abstract":"Field results show nitrogen leaching patterns."}', model="test", usage=ChatUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20))


def pdf_bytes(text: str, metadata: dict[str, str] | None = None) -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    if metadata:
        document.set_metadata(metadata)
    result = document.tobytes()
    document.close()
    return result


def test_extract_owned_upload_and_existing_paper_without_saving(tmp_path):
    app = create_app(tmp_path)
    llm = FakeLLM()
    app.state.llm = llm
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        raw = pdf_bytes("Nitrogen leaching in maize. Li Wei. Agronomy Journal 2024. DOI 10.1234/nitrogen.2024. Field results show nitrogen leaching patterns.")
        upload = client.post("/api/literature/uploads?filename=paper.pdf", content=raw).json()
        denied = client.post("/api/literature/extract", headers={"Authorization": f"Bearer {TOKENS['reviewer']}"}, json={"upload_id": upload["upload_id"]})
        assert denied.status_code == 404
        extracted = client.post("/api/literature/extract", json={"upload_id": upload["upload_id"]})
        assert extracted.status_code == 200, extracted.text
        assert extracted.json()["fields"]["authors"] == [{"name": "Li Wei", "kind": "person"}]
        assert "Nitrogen leaching" in llm.messages[1].content
        paper = client.post("/api/literature/papers", json={"upload_id": upload["upload_id"], "title": "Original title"}).json()
        again = client.post("/api/literature/extract", json={"paper_id": paper["id"]})
        assert again.status_code == 200
        assert client.get(f"/api/literature/papers/{paper['id']}").json()["title"] == "Original title"
        assert client.post("/api/literature/extract", json={"upload_id": upload["upload_id"], "paper_id": paper["id"]}).status_code == 400
    app.state.literature.close()


def test_extract_reports_scanned_pdf_and_unavailable_ai(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        upload = client.post("/api/literature/uploads?filename=scan.pdf", content=pdf_bytes(" ")).json()
        no_ai = client.post("/api/literature/extract", json={"upload_id": upload["upload_id"]})
        assert no_ai.status_code == 422
        app.state.llm = FakeLLM()
        scanned = client.post("/api/literature/extract", json={"upload_id": upload["upload_id"]})
        assert scanned.status_code == 422
        assert scanned.json()["detail"]["code"] == "pdf_text_unavailable"
    app.state.literature.close()


def test_extract_uses_pdf_metadata_when_model_connection_fails(tmp_path):
    class BrokenLLM:
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            raise ConnectionError("model unreachable")

    app = create_app(tmp_path)
    llm = BrokenLLM()
    app.state.llm = llm
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        raw = pdf_bytes(
            "Journal of Agronomy 42 (2024). Nitrogen leaching in maize fields. "
            "This paper examines field data and reports significant nitrogen losses.",
            {"title": "Nitrogen leaching in maize fields", "author": "Li Wei, Zhang Qiang",
             "subject": "Journal of Agronomy, 42 (2024). doi:10.1234/maize.2024"},
        )
        upload = client.post("/api/literature/uploads?filename=paper.pdf", content=raw).json()
        response = client.post("/api/literature/extract", json={"upload_id": upload["upload_id"]})
        assert response.status_code == 200, response.text
        assert response.json()["method"] == "local"
        assert response.json()["fields"]["title"] == "Nitrogen leaching in maize fields"
        assert response.json()["fields"]["doi"] == "10.1234/maize.2024"
        assert response.json()["fields"]["year"] == 2024
        assert [author["name"] for author in response.json()["fields"]["authors"]] == ["Li Wei", "Zhang Qiang"]
        again = client.post("/api/literature/extract", json={"upload_id": upload["upload_id"]})
        assert again.status_code == 200
        assert llm.calls == 1
    app.state.literature.close()


def test_local_metadata_failure_does_not_block_online_extraction(tmp_path):
    app = create_app(tmp_path)
    app.state.llm = FakeLLM()
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        raw = pdf_bytes("Nitrogen leaching in maize fields. A study with sufficient selectable text.",
                        {"subject": "doi:10.1234/" + "x" * 301})
        upload = client.post("/api/literature/uploads?filename=paper.pdf", content=raw).json()
        response = client.post("/api/literature/extract", json={"upload_id": upload["upload_id"]})
        assert response.status_code == 200, response.text
        assert response.json()["method"] == "ai"
        assert response.json()["fields"]["title"] == "Nitrogen leaching in maize"
    app.state.literature.close()


def test_invalid_model_output_does_not_disable_next_extraction(tmp_path):
    class OnceInvalidLLM(FakeLLM):
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("invalid JSON for this paper")
            return await super().chat(messages, **kwargs)

    app = create_app(tmp_path)
    app.state.llm = OnceInvalidLLM()
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKENS['tester']}"
        raw = pdf_bytes("Nitrogen leaching in maize fields. A study with sufficient selectable text.")
        upload = client.post("/api/literature/uploads?filename=paper.pdf", content=raw).json()
        target = {"upload_id": upload["upload_id"]}
        first = client.post("/api/literature/extract", json=target)
        assert first.status_code == 200 and first.json()["method"] == "local"
        assert "未通过校验" in first.json()["warning"]
        second = client.post("/api/literature/extract", json=target)
        assert second.status_code == 200 and second.json()["method"] == "ai"
        assert app.state.llm.calls == 2
    app.state.literature.close()


def test_local_abstract_in_heading_block_does_not_pick_introduction(tmp_path):
    document = fitz.open()
    page = document.new_page()
    abstract = "We measured nitrate losses in maize fields under several irrigation treatments. " * 2
    intro = "This introduction describes earlier research and the motivation for this study. " * 2
    page.insert_textbox(fitz.Rect(72, 110, 500, 220), "Abstract\n" + abstract)
    page.insert_textbox(fitz.Rect(72, 250, 500, 370), "1 Introduction\n" + intro)
    path = tmp_path / "inline-abstract.pdf"
    document.save(path)
    document.close()
    fields = local_suggestions(path)
    assert fields.abstract == abstract.strip()
    assert "introduction" not in fields.abstract
