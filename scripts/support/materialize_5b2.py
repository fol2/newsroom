from __future__ import annotations

import base64
import gzip
import hashlib
import io
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = "b067a1e6da3b0c00b294b86b495c5755ad73c0b253fb2cfdc36282f11347c254"
TRACE_PATH = "docs/traceability/increment-5b-branch-atoms.md"
TRACE_BASE_BLOB_SHA1 = "4e16954a7197a450d744c222750301bbd567cb6e"
INTEGRITY_TEST_PATH = "newsroom/tests/test_increment5b2_fulltext_retriever.py"
PAYLOAD_PARTS = (
    "scripts/support/5b2_payload.00a",
    "scripts/support/5b2_payload.00b",
    "scripts/support/5b2_payload.01",
    "scripts/support/5b2_payload.02",
    "scripts/support/5b2_payload.03",
    "scripts/support/5b2_payload.04a",
    "scripts/support/5b2_payload.04b0",
    "scripts/support/5b2_payload.04b1",
    "scripts/support/5b2_payload.04b2",
    "scripts/support/5b2_payload.04b3",
    "scripts/support/5b2_payload.04b4",
    "scripts/support/5b2_payload.04b5",
    "scripts/support/5b2_payload.04b6",
)
EXPECTED_PATHS = (
    "docs/operations/increment-5b2-fulltext-retriever.md",
    TRACE_PATH,
    "newsroom/increment5/fulltext_contracts.py",
    "newsroom/increment5/fulltext_journal.py",
    "newsroom/increment5/fulltext_normalizer.py",
    "newsroom/increment5/fulltext_receipts.py",
    "newsroom/increment5/fulltext_retriever.py",
    "newsroom/tests/increment5b2_helpers.py",
    INTEGRITY_TEST_PATH,
    "newsroom/tests/test_increment5b2_normalizer.py",
)


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _read_archive() -> bytes:
    encoded = "".join(
        (ROOT / relative_path).read_text(encoding="ascii").strip()
        for relative_path in PAYLOAD_PARTS
    )
    try:
        archive = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SystemExit("5B2 payload is not canonical base64") from exc
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit("5B2 payload digest differs from the reviewed archive")
    return archive


def _materialized_member_bytes(name: str, archive_bytes: bytes) -> bytes:
    if name != INTEGRITY_TEST_PATH:
        return archive_bytes
    text = archive_bytes.decode("utf-8", errors="strict")
    old_import = "from newsroom.authority.canonical import digest_canonical\n"
    old_call = '''            idempotency_key=(
                "integrity-" + digest_canonical(rows)[-12:]
            )
'''
    new_call = '            idempotency_key="integrity-case"\n'
    if text.count(old_import) != 1 or text.count(old_call) != 1:
        raise SystemExit("5B2 integrity-test canonicalization boundary differs")
    return text.replace(old_import, "", 1).replace(old_call, new_call, 1).encode("utf-8")


def main() -> None:
    try:
        tar_bytes = gzip.decompress(_read_archive())
    except (OSError, EOFError) as exc:
        raise SystemExit("5B2 payload is not the reviewed gzip stream") from exc

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
        names = tuple(member.name for member in members)
        if names != EXPECTED_PATHS:
            raise SystemExit("5B2 payload file inventory or ordering differs")
        for member in members:
            if not member.isfile() or member.issym() or member.islnk():
                raise SystemExit(f"5B2 payload member is not a regular file: {member.name}")
            if member.mode != 0o644:
                raise SystemExit(f"5B2 payload member mode differs: {member.name}")
            target = (ROOT / member.name).resolve()
            if not target.is_relative_to(ROOT):
                raise SystemExit(f"5B2 payload path escapes the repository: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"5B2 payload member cannot be read: {member.name}")
            archive_data = source.read()
            if len(archive_data) != member.size:
                raise SystemExit(f"5B2 payload member size differs: {member.name}")
            data = _materialized_member_bytes(member.name, archive_data)
            if target.exists():
                current = target.read_bytes()
                if current != data:
                    if member.name != TRACE_PATH or _git_blob_sha1(current) != TRACE_BASE_BLOB_SHA1:
                        raise SystemExit(
                            f"refusing to overwrite non-base repository bytes: {member.name}"
                        )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)


if __name__ == "__main__":
    main()
