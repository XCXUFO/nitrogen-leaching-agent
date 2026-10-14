"""Provision the six CAU V1.0 accounts; preserve existing evaluation identities."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.evaluation.auth import password_hash
from src.evaluation.contracts import AccessEntry, AccessFile


def private_write(path: Path, content: str):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        handle.write(content)


def provision(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    access_path = directory / "access-keys.json"
    credentials_path = directory / "account-credentials.txt"
    if credentials_path.exists():
        raise ValueError("Account credentials already exist; refusing to reset passwords.")
    old = AccessFile.model_validate_json(access_path.read_text()) if access_path.exists() else None
    expected_legacy = {"local-developer": "developer", "local-tester": "tester"}
    if old and any(u.tester_id not in expected_legacy or u.role != expected_legacy[u.tester_id] or u.username for u in old.users):
        raise ValueError("Unexpected identities; migrate explicitly instead of replacing accounts.")
    specs = [("cau_dev", "developer", "local-developer", "CauDev"),
             ("cau_expert1", "reviewer", "cau_expert1", "CauExpert"),
             ("cau_expert2", "reviewer", "cau_expert2", "CauExpert"),
             ("cau_tester1", "tester", "local-tester", "CauTest"),
             ("cau_tester2", "tester", "cau_tester2", "CauTest"),
             ("cau_tester3", "tester", "cau_tester3", "CauTest")]
    entries, lines = [], ["CAU 工作台 V1.0 私有登录凭据（勿提交或公开）"]
    for username, role, identity, prefix in specs:
        password = f"{prefix}{secrets.randbelow(1000000):06d}"
        entries.append(AccessEntry(tester_id=identity, role=role, username=username,
                                   password_hash=password_hash(password)))
        lines.append(f"{username} ({role}): {password}")
    access = AccessFile(users=entries)
    if old:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        private_write(directory / f"access-keys.pre-accounts-{stamp}.json", access_path.read_text())
    private_write(credentials_path, "\n".join(lines) + "\n")
    temp = directory / f".access-{secrets.token_hex(8)}.tmp"
    private_write(temp, access.model_dump_json(indent=2, exclude_none=True) + "\n")
    temp.replace(access_path)
    return access_path, credentials_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "var/eval")
    args = parser.parse_args()
    try:
        access, credentials = provision(args.directory)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Created 1 developer, 2 reviewers, 3 testers. Configuration: {access}")
    print(f"Open private credentials locally: {credentials}")
    print("Restart the backend to load accounts. Previous key login is disabled after restart.")


if __name__ == "__main__":
    main()
