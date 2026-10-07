"""Bounded, ephemeral uploads. Tokens are capabilities, not user-supplied paths."""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, HTTPException, Query, Request, Response
from loguru import logger
from pydantic import BaseModel, Field
from typing import Annotated
from typing import Literal

from src.model_tools.whcns_results import summarize_result
from src.model_tools.workbooks import WorkbookError, read_workbook

router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TTL_SECONDS = 1800
MAX_FILES = 32
MAX_STORED_BYTES = 64 * 1024 * 1024


class FileReceipt(BaseModel):
    file_id: str
    filename: str
    kind: str | None = None
    rows: int | None = None
    status: Literal["pending", "ready", "invalid"] = "pending"
    sha256: str
    format: str
    expires_in_seconds: int = TTL_SECONDS


class FileStatusRequest(BaseModel):
    file_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=5)


@router.post("/files/status")
async def file_status(request: Request, body: FileStatusRequest, response: Response):
    """Check capabilities without parsing or renewing them; never expose another visitor's files."""
    store = file_store(request)
    store.prune()
    visitor = getattr(request.state, "public_visitor", None)
    response.headers["Cache-Control"] = "no-store"
    statuses = []
    for token in dict.fromkeys(body.file_ids):
        entry = store.entries.get(token)
        available = entry is not None and (visitor is None or entry.owner == visitor)
        statuses.append({"file_id": token, "status": "available" if available else "expired"})
    return {"files": statuses}


@dataclass
class FileEntry:
    expires_at: float
    filename: str
    raw: bytes | None
    sha256: str
    format: str
    report: dict | None = None
    error: str | None = None
    owner: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def state(self) -> dict:
        return {"filename": self.filename,
                "status": "invalid" if self.error else "ready" if self.report else "pending",
                "rows": self.report["rows"] if self.report else None,
                "kind": self.report["kind"] if self.report else None}


class FileStore:
    def __init__(self):
        self.entries: dict[str, FileEntry] = {}
        self.upload_slots = asyncio.Semaphore(2)

    def prune(self):
        now = time.monotonic()
        self.entries = {k: v for k, v in self.entries.items() if v.expires_at > now}

    def put(self, raw: bytes, profile: dict) -> str:
        self.prune()
        if len(self.entries) >= MAX_FILES:
            raise failure(503, "file_store_full", "临时文件空间已满，请稍后重试。")
        if sum(len(entry.raw or b"") for entry in self.entries.values()) + len(raw) > MAX_STORED_BYTES:
            raise failure(503, "file_store_full", "临时附件容量已满，请稍后重试。")
        token = secrets.token_urlsafe(32)
        self.entries[token] = FileEntry(time.monotonic() + TTL_SECONDS, profile["file"], raw,
                                        profile["sha256"], profile["format"])
        return token

    def get(self, token: str) -> FileEntry:
        self.prune()
        if token not in self.entries:
            raise failure(404, "file_not_found", "文件已过期或不可用，请重新上传。")
        entry = self.entries[token]
        # Expiry measures inactivity, not time since upload. Never revive a
        # pruned token, but keep a file available while its session uses it.
        entry.expires_at = time.monotonic() + TTL_SECONDS
        return entry

    async def inspect(self, token: str) -> dict:
        entry = self.get(token)
        async with entry.lock:
            self.get(token)  # May have expired while waiting for another inspection.
            if entry.report is not None:
                return entry.report
            if entry.error is None:
                async with self.upload_slots:
                    self.get(token)
                    try:
                        report = await finish_thread(parse_upload, entry.raw, entry.filename)
                    except ImportError as exc:
                        raise failure(503, "file_tools_unavailable", "文件读取依赖未安装，请联系管理员。") from exc
                    except WorkbookError as exc:
                        entry.error = business_error_message(str(exc))
                    except Exception:
                        logger.exception("Workbook analysis failed")
                        raise failure(503, "file_analysis_failed", "文件分析暂时失败，请重试。")
                    else:
                        self.get(token)  # A result computed after expiry cannot revive the attachment.
                        entry.report = report
                    entry.raw = None  # Keep only the result or diagnostic after validation.
            self.get(token)
            if entry.error:
                raise HTTPException(status_code=422, detail={"code": "invalid_result_file",
                                    "message": entry.error, "attachment": entry.state()})
            return entry.report


async def finish_thread(function, *args):
    """Keep the parse slot occupied until the worker finishes, even on cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


def business_error_message(message: str) -> str:
    replacements = {
        "required columns or exact units missing:": "字段缺失或单位不匹配：",
        "finite numeric value required at": "此单元格需要有效数值：",
        "Excel error at": "此单元格包含 Excel 错误：",
        "expected exactly one Nbal_out or WtaBal_out result sheet": "需要且只能包含一张受支持的 Nbal_out 或 WtaBal_out 结果表",
    }
    for old, new in replacements.items():
        message = message.replace(old, new)
    return f"结果表暂时无法用于计算：{message}。请检查后重新上传。"


def file_store(request: Request) -> FileStore:
    if not hasattr(request.app.state, "file_store"):
        request.app.state.file_store = FileStore()
    return request.app.state.file_store


def failure(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def parse_upload(raw: bytes, filename: str) -> dict:
    with TemporaryDirectory(prefix="whcns-upload-") as directory:
        path = Path(directory) / filename
        path.write_bytes(raw)
        return summarize_result(path)


def inspect_upload(raw: bytes, filename: str) -> dict:
    with TemporaryDirectory(prefix="whcns-upload-") as directory:
        path = Path(directory) / filename
        path.write_bytes(raw)
        # Structural/resource checks only; fields, units and numeric values are
        # checked when a file skill is actually requested.
        book = read_workbook(path, reject_cell_errors=False)
        return {key: book[key] for key in ("file", "sha256", "format")}


@router.post("/files", response_model=FileReceipt)
async def upload_file(request: Request, filename: str = Query(..., min_length=1, max_length=200)):
    # Never use a client path for storage, including Windows paths on Linux.
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if (Path(filename).suffix.lower() not in {".xls", ".xlsx"}
            or any(ord(c) < 32 or ord(c) == 127 for c in filename)):
        raise failure(415, "unsupported_file", "请上传 .xls 或 .xlsx 格式的 WHCNS 氮/水平衡输出表。")
    store = file_store(request)
    async with store.upload_slots:
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
                raise failure(413, "file_too_large", "文件超过 10 MiB，请使用较小的结果表。")
            raw.extend(chunk)
        try:
            profile = await finish_thread(inspect_upload, bytes(raw), filename)
        except ImportError as exc:
            raise failure(503, "file_tools_unavailable", "文件读取依赖未安装，请联系管理员安装 model-tools。") from exc
        except WorkbookError as exc:
            raise failure(422, "invalid_result_file", f"结果表校验失败：{exc}") from exc
        except Exception as exc:
            logger.opt(exception=exc).warning("Workbook parsing failed")
            raise failure(422, "invalid_result_file", "文件无法读取，请检查工作簿是否损坏。") from exc
        token = store.put(bytes(raw), profile)
        store.entries[token].owner = getattr(request.state, "public_visitor", None)
    return FileReceipt(file_id=token, filename=filename, sha256=profile["sha256"], format=profile["format"])
