from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .packages import PackageIntegrityError, parse_json_bytes


@dataclass(frozen=True, slots=True)
class RecordingAdapterResult:
    status: str
    metadata: Mapping[str, Any]


class RecordingOnlyPublisher:
    """Local adapter that records receipt metadata and has no public capability."""

    def record(
        self,
        *,
        publication_bytes: bytes,
        intent_id: str,
    ) -> RecordingAdapterResult:
        value = parse_json_bytes(publication_bytes)
        if not isinstance(value, dict) or value.get("schema_version") != "publication_package_v1":
            raise PackageIntegrityError("recording adapter requires a publication package")
        if value.get("outcome") != "AUTO_PUBLISH" or value.get("target") != "shadow-recording":
            raise PackageIntegrityError("recording adapter package is not shadow-eligible")
        digest = "sha256:" + hashlib.sha256(publication_bytes).hexdigest()
        return RecordingAdapterResult(
            status="RECORDED_NOT_PUBLISHED",
            metadata={
                "schema_version": "recording_adapter_receipt_v1",
                "adapter": "recording-only-v1",
                "intent_id": intent_id,
                "publication_digest": digest,
                "byte_size": len(publication_bytes),
                "public_effect": False,
            },
        )
