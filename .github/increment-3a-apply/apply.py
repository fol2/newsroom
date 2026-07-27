from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_DIR = Path(__file__).resolve().parent
EXPECTED_ARCHIVE_SHA256 = (
    "7087e8ed3b6478d45e98f8b8e0e79f2d865c2ea6b7c1403b8b0014b1d811a04d"
)
EXPECTED_MEMBERS = frozenset(
    {
        "newsroom/sources/_model_common.py",
        "newsroom/authority/_source_registry_store_lineage.py",
        "newsroom/authority/_source_registry_store_read.py",
        "newsroom/authority/_source_registry_store_integrity.py",
        "newsroom/authority/_source_registry_store.py",
        "newsroom/authority/_source_registry_system.py",
        "newsroom/authority/source_registry_system.py",
        "newsroom/tests/source_3a_helpers.py",
        "newsroom/tests/test_source_3a_contracts.py",
        "newsroom/tests/test_source_3a_authority.py",
        "newsroom/tests/test_source_3a_lifecycle_integrity.py",
        "newsroom/tests/test_source_3a_traceability.py",
        "docs/operations/increment-3a-source-registry.md",
        "docs/research/2026-07-27-increment-3a-substantive-review.md",
    }
)

SOURCE_IMPORT = """from .source_registry_migrations import (
    SOURCE_REGISTRY_MIGRATION,
    SOURCE_REGISTRY_MIGRATION_CHECKSUM,
    SOURCE_REGISTRY_MIGRATION_NAME,
    SOURCE_REGISTRY_MIGRATION_STATEMENTS,
    SOURCE_REGISTRY_SCHEMA_VERSION,
)

"""


def _replace_once(text: str, old: str, new: str, *, seam: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"migration seam {seam!r} expected exactly once, found {count}"
        )
    return text.replace(old, new, 1)


def _decode_archive() -> bytes:
    parts = sorted(PAYLOAD_DIR.glob("payload.part*"))
    if [part.name for part in parts] != [
        "payload.part00",
        "payload.part01",
        "payload.part02",
    ]:
        raise RuntimeError("source payload chunks are incomplete or unexpected")
    encoded = "".join(part.read_text(encoding="ascii") for part in parts)
    try:
        archive = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise RuntimeError("source payload is not strict base64") from exc
    actual = hashlib.sha256(archive).hexdigest()
    if actual != EXPECTED_ARCHIVE_SHA256:
        raise RuntimeError(
            f"source payload digest mismatch: expected {EXPECTED_ARCHIVE_SHA256}, "
            f"got {actual}"
        )
    return archive


def _safe_member_path(name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise RuntimeError(f"unsafe source payload path: {name!r}")
    if pure.parts[0] not in {"newsroom", "docs"}:
        raise RuntimeError(f"source payload path escapes allowed roots: {name!r}")
    target = ROOT.joinpath(*pure.parts)
    resolved_parent = target.parent.resolve()
    root = ROOT.resolve()
    if root not in (resolved_parent, *resolved_parent.parents):
        raise RuntimeError(f"source payload path escapes repository: {name!r}")
    return target


def _extract_archive(archive: bytes) -> None:
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            if not member.isfile():
                raise RuntimeError(
                    f"source payload member is not a regular file: {member.name!r}"
                )
            if member.name in seen:
                raise RuntimeError(
                    f"source payload contains duplicate member: {member.name!r}"
                )
            seen.add(member.name)
            if member.name not in EXPECTED_MEMBERS:
                raise RuntimeError(
                    f"source payload contains unexpected member: {member.name!r}"
                )
            target = _safe_member_path(member.name)
            extracted = bundle.extractfile(member)
            if extracted is None:
                raise RuntimeError(
                    f"source payload member cannot be read: {member.name!r}"
                )
            data = extracted.read()
            if len(data) != member.size:
                raise RuntimeError(
                    f"source payload member size mismatch: {member.name!r}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    if seen != set(EXPECTED_MEMBERS):
        missing = sorted(EXPECTED_MEMBERS - seen)
        raise RuntimeError(f"source payload is missing members: {missing!r}")


def _patch_migration_chain() -> None:
    path = ROOT / "newsroom" / "authority" / "migrations.py"
    text = path.read_text(encoding="utf-8")
    if "SOURCE_REGISTRY_SCHEMA_VERSION" in text:
        raise RuntimeError(
            "source registry migration is already present; refusing an ambiguous rerun"
        )

    text = _replace_once(
        text,
        "BASE_SCHEMA_VERSION = 1\n",
        SOURCE_IMPORT + "BASE_SCHEMA_VERSION = 1\n",
        seam="source migration import",
    )
    text = _replace_once(
        text,
        "SCHEMA_VERSION = DEVELOPMENT_CANDIDATE_SCHEMA_VERSION\n",
        "SCHEMA_VERSION = SOURCE_REGISTRY_SCHEMA_VERSION\n",
        seam="current schema version",
    )
    text = _replace_once(
        text,
        "    DEVELOPMENT_CANDIDATE_MIGRATION,\n)\n\ndef _expected_fingerprint",
        "    DEVELOPMENT_CANDIDATE_MIGRATION,\n"
        "    SOURCE_REGISTRY_MIGRATION,\n"
        ")\n\ndef _expected_fingerprint",
        seam="migration manifest",
    )
    text = _replace_once(
        text,
        "            current = DEVELOPMENT_CANDIDATE_SCHEMA_VERSION\n"
        "        conn.execute(f\"PRAGMA user_version={current}\")",
        "            current = DEVELOPMENT_CANDIDATE_SCHEMA_VERSION\n"
        "        if current == DEVELOPMENT_CANDIDATE_SCHEMA_VERSION:\n"
        "            for statement in SOURCE_REGISTRY_MIGRATION_STATEMENTS:\n"
        "                conn.execute(statement)\n"
        "            conn.execute(\n"
        "                \"INSERT INTO authority_migrations(\"\n"
        "                \"version,name,checksum,applied_at) \"\n"
        "                \"VALUES(?,?,?,?)\",\n"
        "                (\n"
        "                    SOURCE_REGISTRY_SCHEMA_VERSION,\n"
        "                    SOURCE_REGISTRY_MIGRATION_NAME,\n"
        "                    SOURCE_REGISTRY_MIGRATION_CHECKSUM,\n"
        "                    applied_at,\n"
        "                ),\n"
        "            )\n"
        "            current = SOURCE_REGISTRY_SCHEMA_VERSION\n"
        "        conn.execute(f\"PRAGMA user_version={current}\")",
        seam="migration application chain",
    )
    text = _replace_once(
        text,
        "    (\n"
        "        DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,\n"
        "        DEVELOPMENT_CANDIDATE_MIGRATION_NAME,\n"
        "        DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,\n"
        "    ),\n"
        ")\n",
        "    (\n"
        "        DEVELOPMENT_CANDIDATE_SCHEMA_VERSION,\n"
        "        DEVELOPMENT_CANDIDATE_MIGRATION_NAME,\n"
        "        DEVELOPMENT_CANDIDATE_MIGRATION_CHECKSUM,\n"
        "    ),\n"
        "    (\n"
        "        SOURCE_REGISTRY_SCHEMA_VERSION,\n"
        "        SOURCE_REGISTRY_MIGRATION_NAME,\n"
        "        SOURCE_REGISTRY_MIGRATION_CHECKSUM,\n"
        "    ),\n"
        ")\n",
        seam="expected migration history",
    )
    path.write_text(text, encoding="utf-8")


def _verify_generated_tree() -> None:
    subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "newsroom"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from newsroom.authority.migrations import "
                "EXPECTED_MIGRATION_HISTORY, SCHEMA_VERSION; "
                "assert SCHEMA_VERSION == 10; "
                "assert EXPECTED_MIGRATION_HISTORY[-1][0] == 10"
            ),
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    archive = _decode_archive()
    _extract_archive(archive)
    _patch_migration_chain()
    _verify_generated_tree()
    print("Increment 3A source-registry payload applied and verified")


if __name__ == "__main__":
    main()
