"""Non-secret identities for answer-affecting code and local data at startup."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.config import BASE_DIR, Settings

MAX_HASH_BYTES = 256 * 1024 * 1024


def tree_identity(path: Path, *, max_hash_bytes: int = MAX_HASH_BYTES) -> dict:
    path = path.resolve()
    if not path.exists():
        return {"path": str(path), "status": "missing", "content_sha256": None}
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    total = sum(item.stat().st_size for item in files)
    metadata = [(str(item.relative_to(path.parent if path.is_file() else path)), item.stat().st_size,
                 item.stat().st_mtime_ns) for item in files]
    metadata_sha = hashlib.sha256(json.dumps(metadata, ensure_ascii=False).encode()).hexdigest()
    if total > max_hash_bytes:
        return {"path": str(path), "status": "metadata_only_size_limit", "content_sha256": None,
                "metadata_sha256": metadata_sha, "file_count": len(files), "total_bytes": total}
    digest = hashlib.sha256()
    for item in files:
        digest.update(str(item.relative_to(path.parent if path.is_file() else path)).encode())
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return {"path": str(path), "status": "content_hashed", "content_sha256": digest.hexdigest(),
            "metadata_sha256": metadata_sha, "file_count": len(files), "total_bytes": total}


def code_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(BASE_DIR)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resolve_model_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def build_manifest(settings: Settings) -> dict:
    agent_paths = sorted((BASE_DIR / "src/agent").glob("*.py")) + sorted(
        (BASE_DIR / "src/model_tools").glob("*.py")) + [
        BASE_DIR / "src/api/chat.py", BASE_DIR / "src/api/chat_schema.py",
        BASE_DIR / "src/api/files.py", BASE_DIR / "src/config.py",
        BASE_DIR / "src/main.py", BASE_DIR / "src/llm/deepseek.py",
        BASE_DIR / "src/operations/public_access.py",
    ]
    prompt_paths = [BASE_DIR / "src/agent/prompt.py", BASE_DIR / "src/agent/composition.py",
                    BASE_DIR / "src/agent/curated_evidence.py"]
    retriever_paths = sorted((BASE_DIR / "src/rag").glob("*.py"))
    config = {key: value for key, value in settings.model_dump().items()
              if key.startswith(("rag_", "chat_")) or key in {"embedding_model", "deepseek_model",
                  "deepseek_timeout_s", "deepseek_max_retries", "public_demo_enabled", "public_max_output_tokens"}}
    manifest = {
        "agent_build_version": settings.agent_build_version,
        "agent_code_sha256": code_digest(agent_paths),
        "prompt_code_sha256": code_digest(prompt_paths),
        "retriever_code_sha256": code_digest(retriever_paths),
        "dependency_lock_sha256": hashlib.sha256((BASE_DIR / "uv.lock").read_bytes()).hexdigest(),
        "answer_config": config,
        "answer_config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "knowledge_index": tree_identity(Path(settings.rag_chroma_dir or settings.chroma_persist_dir))
                           if settings.rag_enabled else {"status": "disabled", "content_sha256": None},
        "embedding_model": tree_identity(resolve_model_path(settings.embedding_model))
                           if settings.rag_enabled else {"status": "not_active", "path": settings.embedding_model},
        "reranker_model": tree_identity(resolve_model_path(settings.rag_reranker_model))
                          if settings.rag_enabled and settings.rag_reranker_enabled else
                          {"status": "not_active", "path": settings.rag_reranker_model},
        "llm_model": {"declared_name": settings.deepseek_model, "provider_content_verified": False},
    }
    manifest["manifest_sha256"] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return manifest
