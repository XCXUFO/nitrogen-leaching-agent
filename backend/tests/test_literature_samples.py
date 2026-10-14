"""Engineering acceptance using repository papers, without changing the live library."""
import hashlib
from pathlib import Path

import fitz
import pytest

from tests.test_literature_http import client  # noqa: F401: shared isolated HTTP fixture

PAPERS = Path(__file__).resolve().parents[2] / "data" / "papers"
SAMPLES = [
    {
        "file": "001_liang_2014_whcns_model_construction.pdf",
        "title": "土壤-作物-大气系统水热碳氮过程耦合模型构建",
        "authors": ["梁浩", "胡克林", "李保国", "刘海涛"],
        "venue": "农业工程学报", "year": 2014, "language": "中文",
        "doi": "10.3969/j.issn.1002-6819.2014.24.007", "pages": 13,
    },
    {
        "file": "051_jiang_2021_is_rice_field_nitrogen_source_sink_environment.pdf",
        "title": "Is rice field a nitrogen source or sink for the environment?",
        "authors": ["Wenjun Jiang", "Weichen Huang", "Hao Liang", "Yali Wu", "Xinrui Shi", "Jin Fu", "Qihui Wang", "Kelin Hu", "Lei Chen", "Hongbin Liu", "Feng Zhou"],
        "venue": "Environmental Pollution", "year": 2021, "language": "英文",
        "doi": "10.1016/j.envpol.2021.117122", "pages": 12,
    },
]


@pytest.mark.parametrize("sample", SAMPLES, ids=["chinese-paper", "english-paper"])
def test_real_paper_registration_and_rendering(client, sample):
    path = PAPERS / sample["file"]
    if not path.is_file(): pytest.skip("Repository paper sample unavailable")
    raw = path.read_bytes()
    uploaded = client.post("/api/literature/uploads", params={"filename": path.name}, content=raw)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["sha256"] == hashlib.sha256(raw).hexdigest()
    saved = client.post("/api/literature/papers", json={
        **{k: v for k, v in sample.items() if k not in {"file", "pages"}},
        "upload_id": uploaded.json()["upload_id"], "publication_type": "期刊论文",
        "source_note": f"仓库已有论文；登记字段人工核对原文首页：data/papers/{path.name}", "action": "register",
    })
    assert saved.status_code == 200, saved.text
    paper = saved.json()
    assert [a["name"] for a in paper["authors"]] == sample["authors"]
    found = client.get("/api/literature/papers", params={"keyword": sample["doi"], "field": "doi"}).json()
    assert found["total"] == 1 and found["items"][0]["id"] == paper["id"]
    preview = client.get(f"/api/literature/papers/{paper['id']}/file").content
    download = client.get(f"/api/literature/papers/{paper['id']}/file?download=true").content
    assert preview == download == raw
    with fitz.open(stream=raw, filetype="pdf") as original, fitz.open(stream=preview, filetype="pdf") as restored:
        assert len(restored) == sample["pages"]
        for index in (0, len(restored) - 1):
            assert original[index].get_pixmap().digest == restored[index].get_pixmap().digest


def test_scan_only_pdf_needs_no_extracted_text(client):
    path = PAPERS / SAMPLES[0]["file"]
    if not path.is_file(): pytest.skip("Repository paper sample unavailable")
    with fitz.open(path) as original, fitz.open() as scan:
        page = scan.new_page(width=original[0].rect.width, height=original[0].rect.height)
        page.insert_image(page.rect, pixmap=original[0].get_pixmap())
        assert not page.get_text().strip()
        raw = scan.tobytes()
    upload = client.post("/api/literature/uploads?filename=scan-fixture.pdf", content=raw)
    assert upload.status_code == 200, upload.text
    saved = client.post("/api/literature/papers", json={"upload_id": upload.json()["upload_id"], "title": "扫描验收夹具（原论文第一页）"})
    assert saved.status_code == 200, saved.text
    preview = client.get(f"/api/literature/papers/{saved.json()['id']}/file").content
    assert preview == raw
    with fitz.open(stream=preview, filetype="pdf") as restored:
        assert not restored[0].get_text().strip()
        assert restored[0].get_images()
