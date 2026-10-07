"""Create local evaluation identities once, without printing access keys."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.evaluation.contracts import AccessFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tester", action="append", default=[])
    parser.add_argument("--developer", action="append", default=[])
    parser.add_argument("--reviewer", action="append", default=[])
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "var/eval")
    args = parser.parse_args()
    users, credentials = [], []
    for role, identities in (("tester", args.tester), ("developer", args.developer), ("reviewer", args.reviewer)):
        for identity in identities:
            token = secrets.token_urlsafe(36)
            users.append({"tester_id": identity, "role": role, "token_sha256": hashlib.sha256(token.encode()).hexdigest()})
            credentials.append(f"{identity} ({role}): {token}")
    access = AccessFile(users=users)
    key_file, secret_file = args.directory / "access-keys.json", args.directory / "access-credentials.txt"
    if key_file.exists() or secret_file.exists():
        parser.error("Access files already exist; refusing to overwrite identities or credentials.")
    args.directory.mkdir(parents=True, exist_ok=True)
    for path, content in ((key_file, access.model_dump_json(indent=2)), (secret_file, "\n".join(credentials))):
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            handle.write(content + "\n")
    print(f"Server access configuration: {key_file}")
    print(f"Private credentials (open locally; do not commit): {secret_file}")


if __name__ == "__main__":
    main()
