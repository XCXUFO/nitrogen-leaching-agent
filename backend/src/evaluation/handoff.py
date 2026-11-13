"""Verified, immutable offline source snapshots; never manufacture agent runs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from src.agent.contracts import CaseStep, EvalCase


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_package(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = (directory / entry["path"]).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("manifest path outside package")
        content = path.read_bytes()
        if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"package checksum mismatch: {entry['path']}")
    data = {name: json.loads((directory / "data" / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("reviewed-cases", "baseline-answers")}
    records = data["reviewed-cases"]["records"]
    baselines = data["baseline-answers"]["records"]
    if len({r["id"] for r in records}) != len(records) or len({r["id"] for r in baselines}) != len(baselines):
        raise ValueError("duplicate source case IDs")
    baseline_by_id = {r["id"]: r for r in baselines}
    if set(baseline_by_id) != {r["id"] for r in records}:
        raise ValueError("source and baseline IDs differ")
    counts = manifest["counts"]
    actual = (len(records), sum(len(r["turns"]) for r in baselines),
              sum(r["source_review_status"] == "needs_changes" for r in records),
              sum(r["source_review_status"] == "passed" for r in records),
              sum(bool(t["is_evaluation_target"]) for r in baselines for t in r["turns"]))
    expected = tuple(counts[k] for k in ("source_conversations", "source_turns", "repair_conversations", "passed_conversations", "target_turns"))
    if actual != expected:
        raise ValueError(f"package counts differ: {actual} != {expected}")
    snapshots = []
    for record in records:
        baseline = baseline_by_id[record["id"]]
        if record["source_session_id"] != baseline["source_session_id"]:
            raise ValueError("source session mismatch")
        if record["new_run_ids"] or record["new_result"] != "未运行":
            raise ValueError("source package must not contain candidate runs")
        targets = [t for t in baseline["turns"] if t["is_evaluation_target"]]
        if [t["user"] for t in targets] != record["user_turns"]:
            raise ValueError("target questions differ from baseline")
        if [t["source_run_id"] for t in targets] != record["baseline"]["run_ids"]:
            raise ValueError("target run IDs differ from baseline")
        mode = record["evaluation_mode"]
        if mode not in {"single_turn", "fixed_history_target_turn", "multi_turn_trajectory"}:
            raise ValueError("unsupported evaluation mode")
        history = record["seed_history"]
        if mode == "fixed_history_target_turn":
            prior = [message for t in baseline["turns"] if t["turn"] < record["target_turn"]
                     for message in ({"role": "user", "content": t["user"]},
                                     {"role": "assistant", "content": t["assistant_visible_text"]})]
            if history != prior:
                raise ValueError("fixed history differs from source conversation")
        elif history:
            raise ValueError("unexpected seed history")
        local_id = f"handoff-{manifest['prepared_on']}-v{manifest['version']}-{record['id']}"
        case = EvalCase(case_id=local_id, version=1, category="NEW", title=record["conversation_title"],
                        steps=[CaseStep(action="query", instruction=q, input=q) for q in record["user_turns"]],
                        preconditions=record["prerequisites"], expected=record["acceptance_draft"],
                        priority="P1", source=record["source_url"])
        snapshots.append({"local_id": local_id, "source": record, "baseline": baseline,
                          "case": case.model_dump(mode="json"), "seed_history": history,
                          "evaluation_mode": mode, "new_run_ids": [], "new_result": "未运行",
                          "missing_fields": ["historical_prompt_versions", "historical_model_parameters", "full_retrieval_evidence"],
                          "professional_review": "pending", "source_kind": "authenticated_ui_snapshot"})
    return {"package_id": f"handoff-{manifest['prepared_on']}-v{manifest['version']}",
            "manifest": manifest, "snapshots": snapshots}


def import_package(directory: Path, database: Path) -> dict:
    """Import only into a dedicated archive, rejecting existing application databases."""
    package = load_package(directory)
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables - {"handoff_packages", "handoff_sources"}:
            raise ValueError("use a dedicated handoff database, not an application database")
        db.execute("CREATE TABLE IF NOT EXISTS handoff_packages (package_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS handoff_sources (local_id TEXT PRIMARY KEY, package_id TEXT NOT NULL, payload TEXT NOT NULL)")
        items = [("handoff_packages", "package_id", package["package_id"], package["manifest"])]
        items += [("handoff_sources", "local_id", s["local_id"], s) for s in package["snapshots"]]
        inserted = 0
        for table, key, identifier, payload in items:
            raw = encode(payload)
            old = db.execute(f"SELECT payload FROM {table} WHERE {key}=?", (identifier,)).fetchone()
            if old and old[0] != raw:
                raise ValueError(f"immutable handoff changed: {identifier}")
            if not old:
                if table == "handoff_packages":
                    db.execute("INSERT INTO handoff_packages VALUES (?,?)", (identifier, raw))
                else:
                    db.execute("INSERT INTO handoff_sources VALUES (?,?,?)", (identifier, package["package_id"], raw))
                    inserted += 1
    return {"package_id": package["package_id"], "inserted": inserted,
            "conversations": len(package["snapshots"]),
            "turns": sum(len(s["baseline"]["turns"]) for s in package["snapshots"]),
            "new_model_runs": 0, "database": str(database)}
