from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from newsroom.authority.canonical import (
    canonical_json_bytes,
    validate_sha256_digest,
)

from .contracts import Increment5ContractError
from .decision_validation import object_without_duplicate_names


ADMISSION_ANCHORS_SCHEMA_VERSION = "increment5a-admission-anchors-v1"
ADMISSION_ANCHORS_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_admission_anchors_v1.json"
)
_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "source_manifest_digest",
        "source_bundle_identity",
        "approval_record_digest",
        "main_qualification_record_digest",
    }
)


@dataclass(frozen=True, slots=True)
class Increment5AAdmissionAnchors:
    source_manifest_digest: str
    source_bundle_identity: str
    approval_record_digest: str | None
    main_qualification_record_digest: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "source_manifest_digest",
            "source_bundle_identity",
        ):
            try:
                validate_sha256_digest(
                    getattr(self, field_name),
                    field=field_name,
                )
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not canonical"
                ) from exc
        for field_name in (
            "approval_record_digest",
            "main_qualification_record_digest",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            try:
                validate_sha256_digest(value, field=field_name)
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not canonical"
                ) from exc
        if (
            self.main_qualification_record_digest is not None
            and self.approval_record_digest is None
        ):
            raise Increment5ContractError(
                "main qualification anchor requires owner approval anchor"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": ADMISSION_ANCHORS_SCHEMA_VERSION,
            "source_manifest_digest": self.source_manifest_digest,
            "source_bundle_identity": self.source_bundle_identity,
            "approval_record_digest": self.approval_record_digest,
            "main_qualification_record_digest": (
                self.main_qualification_record_digest
            ),
        }


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(
            "Increment 5A admission anchors must be an object"
        )
    return value


def _optional_digest(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise Increment5ContractError(f"{field} must be a digest or null")
    try:
        return validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise Increment5ContractError(f"{field} is not canonical") from exc


def parse_increment5a_admission_anchors(
    data: bytes,
) -> Increment5AAdmissionAnchors:
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            "Increment 5A admission anchors are invalid JSON"
        ) from exc
    item = _mapping(value)
    if set(item) != _REQUIRED_KEYS:
        raise Increment5ContractError(
            "Increment 5A admission anchor shape differs"
        )
    if data != canonical_json_bytes(item):
        raise Increment5ContractError(
            "Increment 5A admission anchors must be canonical JSON"
        )
    if item.get("schema_version") != ADMISSION_ANCHORS_SCHEMA_VERSION:
        raise Increment5ContractError(
            "Increment 5A admission anchor version differs"
        )
    source_manifest_digest = item.get("source_manifest_digest")
    source_bundle_identity = item.get("source_bundle_identity")
    if not isinstance(source_manifest_digest, str) or not isinstance(
        source_bundle_identity, str
    ):
        raise Increment5ContractError(
            "Increment 5A source anchors must be digests"
        )
    anchors = Increment5AAdmissionAnchors(
        source_manifest_digest=source_manifest_digest,
        source_bundle_identity=source_bundle_identity,
        approval_record_digest=_optional_digest(
            item.get("approval_record_digest"),
            field="approval_record_digest",
        ),
        main_qualification_record_digest=_optional_digest(
            item.get("main_qualification_record_digest"),
            field="main_qualification_record_digest",
        ),
    )
    if anchors.canonical_value() != dict(item):
        raise Increment5ContractError(
            "Increment 5A admission anchors are not normalized"
        )
    return anchors


def load_increment5a_admission_anchors(
    path: Path = ADMISSION_ANCHORS_PATH,
) -> Increment5AAdmissionAnchors:
    expected_path = ADMISSION_ANCHORS_PATH.resolve()
    if path.resolve() != expected_path or path.is_symlink():
        raise Increment5ContractError(
            "Increment 5A admission anchor path differs"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Increment5ContractError(
            "cannot load Increment 5A admission anchors"
        ) from exc
    return parse_increment5a_admission_anchors(data)


INCREMENT5_ADMISSION_ANCHORS = load_increment5a_admission_anchors()
ADMISSION_SOURCE_MANIFEST_DIGEST = (
    INCREMENT5_ADMISSION_ANCHORS.source_manifest_digest
)
ADMISSION_SOURCE_BUNDLE_IDENTITY = (
    INCREMENT5_ADMISSION_ANCHORS.source_bundle_identity
)
APPROVAL_RECORD_DIGEST = INCREMENT5_ADMISSION_ANCHORS.approval_record_digest
MAIN_QUALIFICATION_RECORD_DIGEST = (
    INCREMENT5_ADMISSION_ANCHORS.main_qualification_record_digest
)
