"""Preview/download only catalogued literature, with no arbitrary path access."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from src.rag.documents import document_path, documents

router = APIRouter()


@router.get("/documents/{document_id}")
def get_document(document_id: str, request: Request, download: bool = False):
    library = getattr(request.app.state, "literature", None)
    if document_id.startswith("P-") and library is not None:
        try:
            result = library.search_index.public_file(document_id)
        except HTTPException:
            result = None
        if result is None:
            raise HTTPException(404, detail={"code": "document_unavailable", "message": "文献原文暂不可用。"})
        paper, path = result
        return FileResponse(path, media_type="application/pdf", filename=paper["filename"], content_disposition_type="attachment" if download else "inline")
    document = documents().get(document_id)
    path = document_path(document) if document else None
    if path is not None and library is not None and not library.search_index.legacy_file_allowed(document["filename"]):
        path = None
    if path is None:
        raise HTTPException(404, detail={"code": "document_unavailable", "message": "文献原文暂不可用。"})
    title = document["title"] or "文献原文"
    filename = "".join(c for c in title if c not in '/\\' and ord(c) >= 32)[:160] + ".pdf"
    return FileResponse(path, media_type="application/pdf", filename=filename,
                        content_disposition_type="attachment" if download else "inline")
