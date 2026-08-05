from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = "b067a1e6da3b0c00b294b86b495c5755ad73c0b253fb2cfdc36282f11347c254"
OVERLAY_ARCHIVE_SHA256 = "48164f812ea7fb4fb6b90b652d50be98d2f0f39e77ce76abf39623ef74fb0373"
OVERLAY_SHA256 = "2f89d8510e9314be09d3bfbfd043739285b29636683f7e4f45de8ff918b3de1f"
OVERLAY_PARTS = (
    "scripts/support/5b2_refactor_overlay.00",
    "scripts/support/5b2_refactor_overlay.01a",
    "scripts/support/5b2_refactor_overlay.01b",
    "scripts/support/5b2_refactor_overlay.01c",
    "scripts/support/5b2_refactor_overlay.01d",
    "scripts/support/5b2_refactor_overlay.02a",
    "scripts/support/5b2_refactor_overlay.02b",
    "scripts/support/5b2_refactor_overlay.02c",
    "scripts/support/5b2_refactor_overlay.02d",
    "scripts/support/5b2_refactor_overlay.03",
    "scripts/support/5b2_refactor_overlay.04",
    "scripts/support/5b2_refactor_overlay.05",
    "scripts/support/5b2_refactor_overlay.06",
)
TRACE_PATH = "docs/traceability/increment-5b-branch-atoms.md"
TRACE_BASE_BLOB_SHA1 = "4e16954a7197a450d744c222750301bbd567cb6e"
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
EXPECTED_ARCHIVE_PATHS = (
    "docs/operations/increment-5b2-fulltext-retriever.md",
    TRACE_PATH,
    "newsroom/increment5/fulltext_contracts.py",
    "newsroom/increment5/fulltext_journal.py",
    "newsroom/increment5/fulltext_normalizer.py",
    "newsroom/increment5/fulltext_receipts.py",
    "newsroom/increment5/fulltext_retriever.py",
    "newsroom/tests/increment5b2_helpers.py",
    "newsroom/tests/test_increment5b2_fulltext_retriever.py",
    "newsroom/tests/test_increment5b2_normalizer.py",
)
OVERLAY_FILE_PATHS = frozenset(
    {
        "docs/operations/increment-5b2-fulltext-retriever.md",
        "newsroom/authority/neo4j_fulltext_reader.py",
        "newsroom/increment5/fulltext_retriever.py",
        "newsroom/tests/increment5b2_helpers.py",
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
    }
)
OVERLAY_REPLACEMENT_PATHS = frozenset(
    {
        "newsroom/authority/_neo4j_projection_system.py",
        "newsroom/projection/neo4j/_adapter.py",
    }
)


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _safe_target(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise SystemExit("5B2 materializer received an empty repository path")
    target = (ROOT / relative_path).resolve()
    if not target.is_relative_to(ROOT):
        raise SystemExit(f"5B2 payload path escapes the repository: {relative_path}")
    return target


def _read_joined(parts: tuple[str, ...], *, identity: str) -> bytes:
    try:
        return "".join(
            (ROOT / relative_path).read_text(encoding="ascii").strip()
            for relative_path in parts
        ).encode("ascii")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"{identity} cannot be read") from exc


def _read_archive() -> bytes:
    encoded = _read_joined(PAYLOAD_PARTS, identity="5B2 payload")
    try:
        archive = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SystemExit("5B2 payload is not canonical base64") from exc
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit("5B2 payload digest differs from the reviewed archive")
    return archive


def _read_overlay() -> dict[str, Any]:
    try:
        encoded = _read_joined(
            OVERLAY_PARTS,
            identity="5B2 refactor overlay",
        )
        archive = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SystemExit("5B2 refactor overlay is not canonical base64") from exc
    if hashlib.sha256(archive).hexdigest() != OVERLAY_ARCHIVE_SHA256:
        raise SystemExit("5B2 refactor overlay archive digest differs")
    try:
        raw = gzip.decompress(archive)
    except (OSError, EOFError) as exc:
        raise SystemExit("5B2 refactor overlay is not the reviewed gzip stream") from exc
    if hashlib.sha256(raw).hexdigest() != OVERLAY_SHA256:
        raise SystemExit("5B2 refactor overlay digest differs")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("5B2 refactor overlay is not canonical JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "files", "replacements"}
        or value["schema_version"]
        != "newsroom.support.increment5b2-refactor-overlay.v1"
        or not isinstance(value["files"], dict)
        or not isinstance(value["replacements"], dict)
    ):
        raise SystemExit("5B2 refactor overlay contract differs")
    if frozenset(value["files"]) != OVERLAY_FILE_PATHS:
        raise SystemExit("5B2 refactor overlay file inventory differs")
    if frozenset(value["replacements"]) != OVERLAY_REPLACEMENT_PATHS:
        raise SystemExit("5B2 refactor overlay replacement inventory differs")
    return value


def _decode_overlay_bytes(value: object, *, field: str) -> bytes:
    if not isinstance(value, str):
        raise SystemExit(f"5B2 overlay {field} must be base64 text")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise SystemExit(f"5B2 overlay {field} is not canonical base64") from exc


def _materialize_archive() -> None:
    try:
        tar_bytes = gzip.decompress(_read_archive())
    except (OSError, EOFError) as exc:
        raise SystemExit("5B2 payload is not the reviewed gzip stream") from exc

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
        names = tuple(member.name for member in members)
        if names != EXPECTED_ARCHIVE_PATHS:
            raise SystemExit("5B2 payload file inventory or ordering differs")
        for member in members:
            if not member.isfile() or member.issym() or member.islnk():
                raise SystemExit(
                    f"5B2 payload member is not a regular file: {member.name}"
                )
            if member.mode != 0o644:
                raise SystemExit(f"5B2 payload member mode differs: {member.name}")
            target = _safe_target(member.name)
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"5B2 payload member cannot be read: {member.name}")
            data = source.read()
            if len(data) != member.size:
                raise SystemExit(f"5B2 payload member size differs: {member.name}")
            if target.exists():
                current = target.read_bytes()
                if current != data:
                    if (
                        member.name != TRACE_PATH
                        or _git_blob_sha1(current) != TRACE_BASE_BLOB_SHA1
                    ):
                        raise SystemExit(
                            "refusing to overwrite non-base repository bytes: "
                            + member.name
                        )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)


def _apply_overlay() -> None:
    overlay = _read_overlay()
    files = overlay["files"]
    for relative_path in sorted(files):
        record = files[relative_path]
        if (
            not isinstance(record, dict)
            or set(record) != {"b64", "mode", "sha256"}
            or record["mode"] != 0o644
            or not isinstance(record["sha256"], str)
        ):
            raise SystemExit(f"5B2 overlay file contract differs: {relative_path}")
        data = _decode_overlay_bytes(record["b64"], field=relative_path)
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise SystemExit(f"5B2 overlay file digest differs: {relative_path}")
        target = _safe_target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)

    replacements = overlay["replacements"]
    for relative_path in sorted(replacements):
        contract = replacements[relative_path]
        if (
            not isinstance(contract, dict)
            or set(contract) != {"base_blob_sha1", "items"}
            or not isinstance(contract["base_blob_sha1"], str)
            or not isinstance(contract["items"], list)
            or not contract["items"]
        ):
            raise SystemExit(
                f"5B2 overlay replacement contract differs: {relative_path}"
            )
        target = _safe_target(relative_path)
        data = target.read_bytes()
        if _git_blob_sha1(data) != contract["base_blob_sha1"]:
            raise SystemExit(
                f"5B2 overlay replacement base differs: {relative_path}"
            )
        for index, item in enumerate(contract["items"]):
            if not isinstance(item, dict) or set(item) != {"new_b64", "old_b64"}:
                raise SystemExit(
                    f"5B2 overlay replacement item differs: {relative_path}:{index}"
                )
            old = _decode_overlay_bytes(
                item["old_b64"],
                field=f"{relative_path}:{index}:old",
            )
            new = _decode_overlay_bytes(
                item["new_b64"],
                field=f"{relative_path}:{index}:new",
            )
            if not old or data.count(old) != 1:
                raise SystemExit(
                    f"5B2 overlay replacement anchor differs: {relative_path}:{index}"
                )
            data = data.replace(old, new, 1)
        target.write_bytes(data)
        target.chmod(0o644)


def main() -> None:
    _materialize_archive()
    _apply_overlay()


if __name__ == "__main__":
    main()
