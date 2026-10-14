"""Create, verify and restore a consistent literature archive into a new directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def connect(path: Path, mode="ro"):
    return sqlite3.connect(path.resolve().as_uri() + f"?mode={mode}", uri=True, timeout=30)


def paper_files(db):
    files = {}
    for identifier, sha in db.execute("SELECT id,sha256 FROM papers"):
        if not re.fullmatch(r"P-[A-F0-9]{16}", identifier) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid paper identifier or file fingerprint")
        files.setdefault(sha, identifier)
    return files


def verify(directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format") != "literature-v1" or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported archive manifest")
    database = directory / "library.sqlite3"
    if database.is_symlink() or digest(database) != manifest["database_sha256"]:
        raise ValueError("Database checksum mismatch")
    with closing(connect(database)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database integrity check failed")
        expected = {f"blob-{sha}.pdf": sha for sha in paper_files(db)}
        if expected != manifest["files"]:
            raise ValueError("Archive file list does not match database references")
        if db.execute("SELECT COUNT(*) FROM uploads WHERE consumed_at IS NULL").fetchone()[0]:
            raise ValueError("Archive contains unfinished uploads")
        count = db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    if (directory / "files").is_symlink():
        raise ValueError("Archive file directory must not be a symlink")
    root = (directory / "files").resolve()
    if {p.name for p in root.iterdir()} != set(expected):
        raise ValueError("Unexpected or missing archive file")
    for name, sha in expected.items():
        path = directory / "files" / name
        if path.is_symlink() or path.resolve().parent != root or digest(path) != sha:
            raise ValueError(f"PDF checksum mismatch: {name}")
    return {"papers_including_deleted": count, "pdf_files": len(expected)}


def backup(database: Path, files: Path, output: Path):
    database, files, output = database.resolve(), files.resolve(), output.absolute()
    if output == files or files in output.parents or output == database:
        raise ValueError("Archive output must be outside the live file directory")
    # Reserve the new destination exclusively. A failed copy intentionally has
    # no manifest and cannot be mistaken for a verified archive.
    with closing(connect(database, "rw")) as guard:
        guard.execute("BEGIN IMMEDIATE")
        try:
            output.mkdir(parents=True, exist_ok=False)
            (output / "files").mkdir()
            with closing(connect(database)) as source, closing(sqlite3.connect(output / "library.sqlite3")) as target:
                source.backup(target)
                with target:
                    target.execute("DELETE FROM uploads WHERE consumed_at IS NULL")
                expected = paper_files(target)
            # The write reservation also excludes cleanup and file replacement
            # in other workers. Copy every record's original, including deleted.
            for sha, identifier in expected.items():
                source = files / f"blob-{sha}.pdf"
                if not source.is_file():
                    source = files / f"{identifier}.pdf"
                if source.is_symlink() or source.resolve().parent != files:
                    raise ValueError("PDF path is outside the configured storage")
                target = output / "files" / f"blob-{sha}.pdf"
                shutil.copyfile(source, target)
                if digest(target) != sha:
                    raise ValueError(f"Original PDF checksum mismatch: {identifier}")
            manifest = {
                "format": "literature-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "database_sha256": digest(output / "library.sqlite3"),
                "files": {f"blob-{sha}.pdf": sha for sha in expected},
            }
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        finally:
            guard.rollback()
    return verify(output)


def restore(archive: Path, output: Path):
    verify(archive)
    if output.absolute() == archive.absolute() or archive.resolve() in output.resolve().parents:
        raise ValueError("Restore destination must be outside the archive")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(archive / "library.sqlite3", output / "library.sqlite3")
    shutil.copytree(archive / "files", output / "files")
    shutil.copyfile(archive / "manifest.json", output / "manifest.json")
    return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup")
    create.add_argument("--db", type=Path, required=True)
    create.add_argument("--files", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("archive", type=Path)
    recover = commands.add_parser("restore")
    recover.add_argument("archive", type=Path)
    recover.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = backup(args.db, args.files, args.output) if args.command == "backup" else restore(args.archive, args.output) if args.command == "restore" else verify(args.archive)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"Archive operation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
