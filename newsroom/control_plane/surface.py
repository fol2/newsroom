"""AUTO-012 unpublished Surface Payload. Not a Publication Bundle."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.control_plane.reports import DATELINES
from newsroom.control_plane.veto import VetoError, refuse_public_effect

PAYLOAD_KIND = "unpublished_surface_payload"
LANGUAGE = "ZH_HANT_HK"
STATUS_UNPUBLISHED = "UNPUBLISHED"


@dataclass(frozen=True, slots=True)
class UnpublishedSurfacePayload:
    payload_kind: str
    publication_bundle: bool
    auto_publish: bool
    language: str
    title: str
    body: str
    evidence_package_digest: str
    story_candidate_id: str
    event_hypothesis_id: str
    source_lineage: tuple[str, ...]
    generated_at: str
    status: str
    writer_id: str

    def __post_init__(self) -> None:
        if self.payload_kind != PAYLOAD_KIND:
            raise ValueError("payload_kind must be unpublished_surface_payload")
        if self.publication_bundle is not False:
            raise VetoError("public effect refused: PUBLICATION_BUNDLE")
        if self.auto_publish is not False:
            refuse_public_effect("AUTO_PUBLISH")
        if self.language != LANGUAGE:
            raise ValueError("unpublished payload language must be ZH_HANT_HK")
        if self.status != STATUS_UNPUBLISHED:
            raise ValueError("unpublished payload status must be UNPUBLISHED")
        if not self.evidence_package_digest.startswith("sha256:"):
            raise ValueError("Evidence Package digest required")
        if not self.story_candidate_id or not self.event_hypothesis_id:
            raise ValueError("Story Candidate and Event Hypothesis required")
        if not self.title.strip() or not self.body.strip():
            raise ValueError("title and body required")
        if not self.source_lineage:
            raise ValueError("source lineage required")
        if not self.writer_id.strip():
            raise ValueError("writer identity required")
        lowered = self.body.lstrip()
        for dateline in DATELINES.values():
            if lowered.startswith(dateline):
                raise ValueError("dateline dump is not an original unpublished report")
