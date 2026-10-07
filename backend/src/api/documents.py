"""Preview/download only catalogued literature, with no arbitrary path access."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.rag.documents import document_path, documents

router = APIRouter()


@router.get("/documents/{document_id}")
def get_document(document_id: str, download: bool = False):
    document = documents().get(document_id)
    path = document_path(document) if document else None
    if path is None:
        raise HTTPException(404, detail={"code": "document_unavailable", "message": "文献原文暂不可用。"})
    title = document["title"] or "文献原文"
    filename = "".join(c for c in title if c not in '/\\' and ord(c) >= 32)[:160] + ".pdf"
    return FileResponse(path, media_type="application/pdf", filename=filename,
                        content_disposition_type="attachment" if download else "inline")
