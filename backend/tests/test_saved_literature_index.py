"""Every saved, enabled PDF can supply text, including metadata drafts."""
import re

import pytest

from src.agent.understanding import canonical, terms
from src.api.literature import PaperInput, PaperUpdateInput, ReasonInput, create_paper, update_paper, disable_paper
from tests.test_literature_search_sync import library, USER
from tests.test_literature import FakeRequest, pdf_bytes, upload_pdf


@pytest.mark.parametrize("text", ["", "灌溉施肥影响氮素淋失", "土 壤\n氮素 leaching 12.5", "Maize nitrate 土壤N2O试验", "边界㐀𠀀汉字 mixed_English 1.0"])
def test_overlapping_keyword_extraction_preserves_existing_search_terms(text):
    value = canonical(text)
    expected = set(re.findall(r"[\u4e00-\u9fff]{2}|[a-z_]{2,}|\d+(?:\.\d+)?", value)) | {
        value[i:i+2] for i in range(len(value)-1) if re.fullmatch(r"[\u4e00-\u9fff]{2}", value[i:i+2])}
    assert terms(text) == expected


def save(library, text, name="new.pdf"):
    token = upload_pdf(library, USER, filename=name, raw=pdf_bytes(text))
    return create_paper(FakeRequest(library), PaperInput(upload_id=token, title=name, action="draft"), USER)


def test_saved_new_drafts_are_indexed_without_registration_or_machine_fields(library):
    paper = save(library, "New water and nitrogen study. Irrigation transports nitrate through soil.")
    assert paper["registration"] == "draft" and paper["search_sync"]["status"] == "not_prepared"

    prepared = library.search_index.prepare_pending()

    assert prepared == {"ready": 1, "failed": 0}
    current = library.get_paper(paper["id"])
    assert current["registration"] == "draft" and current["authors"] == []
    assert current["search_sync"]["status"] == "ready" and current["search_sync"]["mode"] == "text"
    hits, _ = library.search_index.search("nitrogen nitrate")
    assert hits and hits[0].metadata["paper_id"] == paper["id"]
    assert "Irrigation transports nitrate" in hits[0].document
    assert library.search_index.public_file(paper["id"])
    assert library.search_index.prepare_pending() == {"ready": 0, "failed": 0}


def test_pending_sync_refreshes_metadata_and_replaced_pdf_but_excludes_disabled(library):
    paper = save(library, "Original nitrogen study.")
    library.search_index.prepare_pending()
    old, _ = library.search_index.search("nitrogen")
    current = library.get_paper(paper["id"])
    token = upload_pdf(library, USER, filename="replacement.pdf", raw=pdf_bytes("Replacement nitrate evidence from irrigation."))
    update_paper(FakeRequest(library), paper["id"], PaperUpdateInput.model_validate({
        **current, "expected_revision": current["revision"], "upload_id": token, "title": "Updated study", "action": "draft",
    }), USER)
    assert not library.search_index.eligible_hit(old[0])

    assert library.search_index.prepare_pending() == {"ready": 1, "failed": 0}
    hits, _ = library.search_index.search("Replacement nitrate")
    assert "Replacement nitrate" in hits[0].document and "Original nitrogen" not in hits[0].document
    assert hits[0].metadata["title"] == "Updated study"
    disable_paper(FakeRequest(library), paper["id"], ReasonInput(reason="exclude source"), USER)
    assert library.search_index.prepare_pending() == {"ready": 0, "failed": 0}
    assert not library.search_index.eligible_hit(hits[0])
    assert library.search_index.search("Replacement nitrate")[0] == []


def test_unreadable_body_stays_failed_until_an_explicit_retry(library):
    paper = save(library, "")
    assert library.search_index.prepare_pending() == {"ready": 0, "failed": 1}
    assert library.get_paper(paper["id"])["search_sync"]["status"] == "failed"
    events = library.events("paper", paper["id"])
    assert library.search_index.prepare_pending() == {"ready": 0, "failed": 0}
    assert library.events("paper", paper["id"]) == events
