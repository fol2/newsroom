"""Immutable observation and report evidence for Increment 5E1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import uuid

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._retrieval_qualification_common import (
    MODE_ORDER,
    RESULT_LIMIT,
    QualificationDecision,
    QualificationMode,
    QualificationOutcome,
    QualificationSystem,
    RetrievalQualificationError,
    digest,
    freeze,
    parse_utc,
    require_digest,
    require_token,
    require_tree_sha,
    require_uint,
    thaw,
    unique_object,
)


@dataclass(frozen=True, slots=True)
class QualificationObservation:
    case_id: str
    system: QualificationSystem
    outcome: QualificationOutcome
    ranked_roots: tuple[str, ...]
    contributing_modes: tuple[QualificationMode, ...]
    latency_ms: int
    provenance_complete: bool
    trust_labels_complete: bool
    temporal_correct: bool
    rights_purge_residual_count: int = 0
    scope_escape_count: int = 0
    write_attempt_success_count: int = 0
    rebuild_reproducibility_mismatch_count: int = 0
    candidate_disposition_count: int = 0
    truncated: bool = False
    external_call_count: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    candidate_created: bool = False
    hypothesis_created: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        require_token(self.case_id, field="observation case")
        require_uint(self.latency_ms, field="latency_ms")
        if self.latency_ms > 5_000:
            raise RetrievalQualificationError("observation exceeds timeout")
        if len(self.ranked_roots) > RESULT_LIMIT:
            raise RetrievalQualificationError("observation exceeds result limit")
        if len(set(self.ranked_roots)) != len(self.ranked_roots):
            raise RetrievalQualificationError("observation roots duplicate")
        for root in self.ranked_roots:
            require_token(root, field="observation root")
        expected_modes = tuple(
            mode
            for mode in MODE_ORDER
            if mode in set(self.contributing_modes)
        )
        if self.contributing_modes != expected_modes:
            raise RetrievalQualificationError("observation modes are not canonical")
        if self.outcome is not QualificationOutcome.COMPLETE and (
            self.ranked_roots or self.contributing_modes
        ):
            raise RetrievalQualificationError("non-complete observation exposes results")
        for field_name in (
            "provenance_complete",
            "trust_labels_complete",
            "temporal_correct",
            "truncated",
            "candidate_created",
            "hypothesis_created",
            "production_activation_authorized",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise RetrievalQualificationError(
                    f"{field_name} must be boolean"
                )
        for field_name in (
            "rights_purge_residual_count",
            "scope_escape_count",
            "write_attempt_success_count",
            "rebuild_reproducibility_mismatch_count",
            "candidate_disposition_count",
            "external_call_count",
            "provider_spend_micros",
        ):
            require_uint(getattr(self, field_name), field=field_name)
        if (
            self.external_call_count
            or self.provider_spend_micros
            or self.authority_effect != "NONE"
            or self.candidate_created
            or self.hypothesis_created
            or self.production_activation_authorized
        ):
            raise RetrievalQualificationError("observation claims a forbidden effect")


@dataclass(frozen=True, slots=True)
class QualificationReport:
    report_id: str
    run_id: str
    epoch_digest: str
    code_tree_sha: str
    target_manifest_digest: str
    corpus_spec_digest: str
    dataset_manifest_digest: str
    started_at: str
    completed_at: str
    decision: QualificationDecision
    reason: str
    metrics: Mapping[str, object]
    blockers: tuple[str, ...]
    observation_count: int
    expected_observation_count: int
    comparative_results_decision_bearing: bool = False
    vector_quality_scope: str = "DETERMINISTIC_FIXED_POINT_FIXTURE_REPLAY_ONLY"
    embedding_quality_qualified: bool = False
    human_label_or_adjudication_programme: bool = False
    external_call_count: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    candidate_created: bool = False
    hypothesis_created: bool = False
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", freeze(thaw(self.metrics)))
        for value in (self.report_id, self.run_id):
            try:
                if str(uuid.UUID(value)) != value:
                    raise ValueError
            except ValueError as exc:
                raise RetrievalQualificationError(
                    "report identities must be canonical UUIDs"
                ) from exc
        for value in (
            self.epoch_digest,
            self.target_manifest_digest,
            self.corpus_spec_digest,
            self.dataset_manifest_digest,
        ):
            require_digest(value, field="report digest")
        require_tree_sha(self.code_tree_sha, field="report code tree")
        if parse_utc(self.completed_at, field="completed_at") < parse_utc(
            self.started_at,
            field="started_at",
        ):
            raise RetrievalQualificationError("report completion precedes start")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise RetrievalQualificationError("report blockers are not canonical")
        require_token(self.reason, field="report reason")
        require_uint(self.observation_count, field="observation_count")
        require_uint(
            self.expected_observation_count,
            field="expected_observation_count",
        )
        require_uint(self.external_call_count, field="external_call_count")
        require_uint(self.provider_spend_micros, field="provider_spend_micros")
        expected_metric_keys = {
            "exposure",
            "systems",
            "mandatory_families",
            "required_slices",
            "triage_error_classes",
            "branch_contributions",
        }
        if set(self.metrics) != expected_metric_keys:
            raise RetrievalQualificationError("report metric inventory differs")
        if self.decision is not QualificationDecision.NOT_EVALUATED and (
            self.observation_count != self.expected_observation_count
        ):
            raise RetrievalQualificationError(
                "evaluated report observation coverage differs"
            )
        if self.decision is QualificationDecision.PASS:
            if self.reason != "PASS" or self.blockers:
                raise RetrievalQualificationError("PASS report is inconsistent")
        elif self.reason == "PASS" or not self.blockers:
            raise RetrievalQualificationError("non-PASS report lacks blockers")
        forbidden_bools = (
            self.comparative_results_decision_bearing,
            self.embedding_quality_qualified,
            self.human_label_or_adjudication_programme,
            self.candidate_created,
            self.hypothesis_created,
            self.production_activation_authorized,
        )
        if any(type(value) is not bool or value for value in forbidden_bools):
            raise RetrievalQualificationError("report claims a forbidden effect")
        if (
            self.external_call_count
            or self.provider_spend_micros
            or self.authority_effect != "NONE"
        ):
            raise RetrievalQualificationError(
                "report claims external or authority effect"
            )
        require_token(self.vector_quality_scope, field="vector quality scope")
        expected_report_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(
                    (
                        self.run_id,
                        self.epoch_digest,
                        self.decision.value,
                        self.reason,
                        self.evidence_digest,
                    )
                ),
            )
        )
        if self.report_id != expected_report_id:
            raise RetrievalQualificationError(
                "report identity differs from evidence"
            )

    @property
    def evidence_digest(self) -> str:
        return digest(
            {
                "metrics": thaw(self.metrics),
                "blockers": list(self.blockers),
                "observation_count": self.observation_count,
                "expected_observation_count": self.expected_observation_count,
            }
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.retrieval-qualification-report.v1",
            "report_id": self.report_id,
            "run_id": self.run_id,
            "epoch_digest": self.epoch_digest,
            "code_tree_sha": self.code_tree_sha,
            "target_manifest_digest": self.target_manifest_digest,
            "corpus_spec_digest": self.corpus_spec_digest,
            "dataset_manifest_digest": self.dataset_manifest_digest,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "decision": self.decision.value,
            "reason": self.reason,
            "metrics": thaw(self.metrics),
            "blockers": list(self.blockers),
            "observation_count": self.observation_count,
            "expected_observation_count": self.expected_observation_count,
            "comparative_results_decision_bearing": (
                self.comparative_results_decision_bearing
            ),
            "vector_quality_scope": self.vector_quality_scope,
            "embedding_quality_qualified": self.embedding_quality_qualified,
            "human_label_or_adjudication_programme": (
                self.human_label_or_adjudication_programme
            ),
            "external_call_count": self.external_call_count,
            "provider_spend_micros": self.provider_spend_micros,
            "authority_effect": self.authority_effect,
            "candidate_created": self.candidate_created,
            "hypothesis_created": self.hypothesis_created,
            "production_activation_authorized": (
                self.production_activation_authorized
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def report_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "QualificationReport":
        try:
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=unique_object,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RetrievalQualificationError(
                "retained report is not JSON"
            ) from exc
        if (
            not isinstance(value, dict)
            or canonical_json_bytes(value) != raw
            or value.pop("schema_version", None)
            != "newsroom.increment5.retrieval-qualification-report.v1"
        ):
            raise RetrievalQualificationError(
                "retained report is not canonical v1"
            )
        try:
            value["decision"] = QualificationDecision(value["decision"])
            value["blockers"] = tuple(value["blockers"])
            return cls(**value)
        except RetrievalQualificationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise RetrievalQualificationError(
                "retained report shape differs"
            ) from exc
