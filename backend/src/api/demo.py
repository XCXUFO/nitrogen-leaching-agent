"""Public, read-only publication. Never query the operational evaluation database."""
from pathlib import Path
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data/demo/catalog.json"
EXAMPLE = ROOT / "data/demo/Nbal_out.xls"
router = APIRouter(prefix="/demo")


@router.get("/catalog")
def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


@router.get("/examples/nitrogen")
def example():
    if not EXAMPLE.is_file():
        raise HTTPException(503, detail={"code": "demo_example_unavailable", "message": "示例文件暂不可用，请查看已保存案例。"})
    return FileResponse(EXAMPLE, filename="Nbal_out.xls", media_type="application/vnd.ms-excel")
