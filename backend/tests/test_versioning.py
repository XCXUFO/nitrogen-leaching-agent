from pathlib import Path

from src.config import Settings
from src.evaluation.versioning import build_manifest, tree_identity


def test_tree_identity_detects_content_changes_without_size_change(tmp_path: Path):
    source = tmp_path / "index"
    source.mkdir()
    (source / "part.bin").write_bytes(b"first")
    before = tree_identity(source)
    (source / "part.bin").write_bytes(b"other")
    after = tree_identity(source)
    assert before["status"] == after["status"] == "content_hashed"
    assert before["content_sha256"] != after["content_sha256"]


def test_large_tree_identity_is_explicitly_metadata_only(tmp_path: Path):
    path = tmp_path / "model.bin"
    path.write_bytes(b"model bytes")
    identity = tree_identity(path, max_hash_bytes=4)
    assert identity["status"] == "metadata_only_size_limit"
    assert identity["content_sha256"] is None
    assert identity["metadata_sha256"] and identity["total_bytes"] == 11


def test_manifest_excludes_credentials_and_has_stable_digest():
    settings = Settings(rag_enabled=False, deepseek_api_key="sensitive-test-key")
    first = build_manifest(settings)
    second = build_manifest(settings)
    assert first == second
    assert "sensitive-test-key" not in str(first)
    assert first["manifest_sha256"] and first["agent_code_sha256"]
    assert first["knowledge_index"]["status"] == "disabled"
