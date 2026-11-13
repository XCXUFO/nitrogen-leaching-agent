"""Verify and receive the supplemental originals without changing live data."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import fitz

from src.storage.case_content import parse_html


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative_path(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or path.as_posix() != name:
        raise ValueError("unsafe package path")
    return path


def verify_files(root):
    root = Path(root)
    manifest = read_json(root / "manifest.json")
    listed = set()
    for item in manifest["files"]:
        path = relative_path(item["path"])
        if str(path) in listed or str(path) == "manifest.json":
            raise ValueError("duplicate manifest entry")
        listed.add(str(path))
        target = root / path
        if target.is_symlink() or not target.is_file() or root.resolve() not in target.resolve().parents:
            raise ValueError(f"missing or unsafe source: {path}")
        if target.stat().st_size != item["bytes"] or digest(target) != item["sha256"]:
            raise ValueError(f"source hash mismatch: {path}")
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if actual != listed | {"manifest.json"}:
        raise ValueError("unlisted or missing package files")
    return manifest


def receive_archive(archive, destination):
    """Validate in staging, then publish once. A repeat cannot replace originals."""
    archive, destination = Path(archive), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as source:
        entries = [item for item in source.infolist() if not item.is_dir()]
        if len(entries) > 1000 or sum(item.file_size for item in entries) > 512 * 1024 * 1024:
            raise ValueError("package exceeds receipt budget")
        manifests = [item for item in entries if PurePosixPath(item.filename).name == "manifest.json"]
        if len(manifests) != 1:
            raise ValueError("expected one package manifest")
        prefix = str(PurePosixPath(manifests[0].filename).parent)
        prefix = "" if prefix == "." else prefix + "/"
        names = set()
        with TemporaryDirectory(prefix=".materials-", dir=destination.parent) as staging:
            staging = Path(staging)
            for item in entries:
                if not item.filename.startswith(prefix) or stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError("unsafe zip entry")
                name = str(relative_path(item.filename[len(prefix):]))
                if name in names:
                    raise ValueError("duplicate zip entry")
                names.add(name)
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
            verify_files(staging)
            if destination.exists():
                verify_files(destination)
                if digest(destination / "manifest.json") != digest(staging / "manifest.json"):
                    raise ValueError("immutable material package changed")
                return False
            staging.rename(destination)
    return True


def normalized_text(value):
    return re.sub(r"\s+", "", value)


def audit_materials(root, prior_sources):
    """Check actual records and files; export assertions alone are not evidence."""
    root = Path(root)
    manifest = verify_files(root)
    index = read_json(root / "index.json")
    reviewed = {r["id"]: r for r in read_json(root / "conversations/reviewed-cases.json")["records"]}
    prior = {r["id"]: r for r in read_json(prior_sources / "data/reviewed-cases.json")["records"]}
    if set(reviewed) != set(prior) or len(reviewed) != 8:
        raise ValueError("reviewed conversation IDs changed")
    for identifier, record in reviewed.items():
        for key in ("source_session_id", "source_review_status", "target_turn", "evaluation_mode", "user_turns"):
            if record[key] != prior[identifier][key]:
                raise ValueError(f"original source changed: {identifier}/{key}")
    rounds = index["rounds"]
    if len(rounds) != 21 or len({r["run_id"] for r in rounds}) != 21:
        raise ValueError("expected 21 distinct original runs")
    materials = {m["id"]: m for m in index["materials"]}
    if len(materials) != 41 or sum(m["kind"] == "literature" for m in materials.values()) != 35:
        raise ValueError("unexpected original material counts")
    checks, referenced_pdfs, case_versions = [], {}, {}
    for item in rounds:
        identifier = item["case_id"]
        run_path = root / relative_path(item["raw_path"])
        text = run_path.read_text(encoding="utf-8")
        run = json.loads(text)
        conversation = read_json(root / f"conversations/{identifier}.json")
        declared = {r["id"]: r["size"] for r in conversation["runs"]}
        if declared.get(run["run_id"]) != len(text) or run["run_id"] != item["run_id"] or run["input"] != item["query"]:
            raise ValueError(f"run identity/length mismatch: {identifier}")
        if item["session_id"] != reviewed[identifier]["source_session_id"]:
            raise ValueError("conversation source mismatch")
        if run["history_count"] != len(run["request_snapshot"]["history"]) or run["history_count"] != item["history_count"]:
            raise ValueError("recorded history mismatch")
        evidence_ids = []
        for evidence in run["evidence"]:
            source_id = evidence["source_id"].split(":")[0]
            if evidence["source_type"] == "literature":
                if source_id not in materials:
                    raise ValueError("missing cited literature")
                file_hash = evidence["provenance"].get("file_sha256")
                if file_hash:
                    referenced_pdfs.setdefault(source_id, set()).add(file_hash)
            if evidence["source_type"] in {"literature", "case"}:
                evidence_ids.append(source_id)
        for retrieval in run["retrieval"]:
            if retrieval["source_type"] == "case":
                for candidate in retrieval["candidates"]:
                    if candidate.get("snippet"):
                        case_versions[(candidate["id"], candidate["fingerprint"])] = candidate
        checks.append({"case_id": identifier, "turn": item["turn"], "run_id": run["run_id"],
                       "query": run["input"], "history_count": run["history_count"],
                       "evidence_material_ids": list(dict.fromkeys(evidence_ids)),
                       "retrieval_candidate_count": sum(len(r["candidates"]) for r in run["retrieval"]),
                       "raw_length_verified": True})
    pdf_checks = []
    for identifier, material in materials.items():
        if material["kind"] != "literature":
            continue
        path = root / relative_path(material["original_pdf"])
        sha = digest(path)
        expected = set(material["expected_file_sha256"]) | referenced_pdfs.get(identifier, set())
        info = read_json(root / f"literature/{identifier}.pdf-info.json")
        if expected != {sha} or info["sha256"] != sha:
            raise ValueError(f"PDF historical hash mismatch: {identifier}")
        with fitz.open(path) as document:
            if len(document) != info["pages"]:
                raise ValueError("PDF page count mismatch")
        pdf_checks.append({"id": identifier, "sha256": sha, "pages": info["pages"],
                           "pages_without_extractable_text": info["pages_without_extractable_text"]})
    case_checks = []
    for (identifier, fingerprint), candidate in sorted(case_versions.items()):
        historical = read_json(root / f"cases/historical/{identifier}@{fingerprint}.json")["candidate"]
        current = read_json(root / f"cases/{identifier}.json")
        if historical["snippet"] != candidate["snippet"]:
            raise ValueError("historical case snapshot mismatch")
        if normalized_text("".join(parse_html(candidate["snippet"]).text)) != normalized_text(current["bodyText"]):
            raise ValueError(f"case historical body mismatch: {identifier}")
        case_checks.append({"id": identifier, "historical_fingerprint": fingerprint,
                            "revision": candidate["revision"], "body_text_matches": True})
    if len(case_checks) != 6:
        raise ValueError("expected six historical case snapshots")
    target = next(r for r in rounds if r["case_id"] == "FIX-05" and r["turn"] == 2)
    seed = read_json(root / target["raw_path"])["request_snapshot"]["history"]
    if len(seed) != 2:
        raise ValueError("FIX-05 fixed history missing")
    return {"schema_version": "material-receipt-v1", "prepared_on": manifest["prepared_on"],
            "manifest_sha256": digest(root / "manifest.json"), "verified_files": len(manifest["files"]),
            "original_conversations": len(reviewed), "original_runs": len(checks),
            "pdfs": len(pdf_checks), "pdf_pages": sum(p["pages"] for p in pdf_checks),
            "cases": len(case_checks), "rounds": checks, "pdf_checks": pdf_checks, "case_checks": case_checks,
            "fixed_history": {"FIX-05": seed}, "scope": "linked_materials_subset",
            "new_model_runs": 0, "professional_review": "pending", "original_reviews_changed": False}
