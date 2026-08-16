"""Bounded Increment 9B2 integration-controller qualification.

The controller in this module executes canonical fixture/replay records only.  It
has no credential, network, provider, publication, Evidence Intake or production
writer capability and cannot start the 9B3 prospective campaign.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Mapping, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.deployment import (
    DeploymentPlan,
    DeploymentReadinessReceipt,
    IsolatedDeploymentReceipt,
    ReadinessDisposition,
)
from newsroom.increment9.epoch import (
    EFFECTIVE_MANIFEST_IDENTITY_KEYS,
    EffectiveManifest,
    EvaluationEpoch,
    ManifestCohort,
    RunAttempt,
    RunKind,
    ShadowRun,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST
from newsroom.increment9.shadow_contracts import ShadowScope

MAX_RECORD_BYTES = 4_194_304
CONTROLLER_JOURNAL_APPLICATION_ID = 0x49394232
CONTROLLER_JOURNAL_SCHEMA_VERSION = 1
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class ControllerError(ValueError):
    """Controller qualification input or evidence differs from authority."""


class ControllerStage(StrEnum):
    SOURCE = "SOURCE"
    DISCOVERY = "DISCOVERY"
    EXTRACTION = "EXTRACTION"
    GRAPHITI_PROPOSAL = "GRAPHITI_PROPOSAL"
    DETERMINISTIC_ADMISSION = "DETERMINISTIC_ADMISSION"
    NEO4J_PROJECTION = "NEO4J_PROJECTION"
    HYBRID_RETRIEVAL = "HYBRID_RETRIEVAL"
    TRIAGE = "TRIAGE"
    CANDIDATE = "CANDIDATE"
    HANDOFF = "HANDOFF"
    EVALUATION_SINK = "EVALUATION_SINK"


CONTROLLER_STAGES = tuple(ControllerStage)
STAGE_MANIFEST_DIMENSIONS: Mapping[ControllerStage, str] = MappingProxyType(
    {
        ControllerStage.SOURCE: "source",
        ControllerStage.DISCOVERY: "code",
        ControllerStage.EXTRACTION: "code",
        ControllerStage.GRAPHITI_PROPOSAL: "code",
        ControllerStage.DETERMINISTIC_ADMISSION: "ontology",
        ControllerStage.NEO4J_PROJECTION: "projector",
        ControllerStage.HYBRID_RETRIEVAL: "retrieval",
        ControllerStage.TRIAGE: "triage",
        ControllerStage.CANDIDATE: "candidate",
        ControllerStage.HANDOFF: "handoff",
        ControllerStage.EVALUATION_SINK: "operational_profile",
    }
)
_PROPOSAL_STAGES = frozenset({ControllerStage.GRAPHITI_PROPOSAL})
_DECISION_STAGES = frozenset(
    {
        ControllerStage.DETERMINISTIC_ADMISSION,
        ControllerStage.TRIAGE,
        ControllerStage.CANDIDATE,
        ControllerStage.HANDOFF,
        ControllerStage.EVALUATION_SINK,
    }
)


class LedgerKind(StrEnum):
    CONTROL_ENVELOPE = "CONTROL_ENVELOPE"
    BUDGET_RESERVATION = "BUDGET_RESERVATION"
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    PROPOSAL = "PROPOSAL"
    DECISION = "DECISION"
    CHECKPOINT = "CHECKPOINT"
    USAGE = "USAGE"
    COST = "COST"


class RecoveryScenario(StrEnum):
    RESTART_REPLAY = "RESTART_REPLAY"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    LOST_RESPONSE = "LOST_RESPONSE"
    PARTIAL_RESPONSE = "PARTIAL_RESPONSE"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    KILL_SWITCH_PROPAGATION = "KILL_SWITCH_PROPAGATION"
    TEARDOWN_REBUILD = "TEARDOWN_REBUILD"


RECOVERY_SCENARIOS = tuple(RecoveryScenario)


class ScenarioOutcome(StrEnum):
    RECONCILED = "RECONCILED"
    DEDUPLICATED = "DEDUPLICATED"
    BLOCKED_RECONCILED = "BLOCKED_RECONCILED"
    EARLY_STOPPED = "EARLY_STOPPED"
    REBUILT = "REBUILT"


_SCENARIO_OUTCOMES: Mapping[RecoveryScenario, ScenarioOutcome] = MappingProxyType(
    {
        RecoveryScenario.RESTART_REPLAY: ScenarioOutcome.RECONCILED,
        RecoveryScenario.DUPLICATE_REQUEST: ScenarioOutcome.DEDUPLICATED,
        RecoveryScenario.LOST_RESPONSE: ScenarioOutcome.BLOCKED_RECONCILED,
        RecoveryScenario.PARTIAL_RESPONSE: ScenarioOutcome.BLOCKED_RECONCILED,
        RecoveryScenario.AMBIGUOUS_EFFECT: ScenarioOutcome.BLOCKED_RECONCILED,
        RecoveryScenario.KILL_SWITCH_PROPAGATION: ScenarioOutcome.EARLY_STOPPED,
        RecoveryScenario.TEARDOWN_REBUILD: ScenarioOutcome.REBUILT,
    }
)


class CheckOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


CHECK_IDS = (
    "RIGHTS_CURRENT",
    "PURPOSE_BOUND",
    "CREDENTIAL_SEPARATION",
    "EGRESS_DEFAULT_DENY",
    "BUDGET_AND_COST_LEDGER",
    "FRESHNESS_BOUND",
    "WATERMARK_CONTIGUOUS",
    "GAP_VISIBLE",
    "DEAD_LETTER_VISIBLE",
    "SOURCE_REPRESENTATION_EXACT",
    "ONTOLOGY_RELATION_POLICY_EXACT",
    "INDEX_GENERATION_EXACT",
    "OPERATIONAL_PROFILE_EXACT",
    "GRAPHITI_PROPOSAL_ONLY",
    "DETERMINISTIC_AUTHORITIES_SOLE_COMMITTERS",
    "PROHIBITED_PATHS_UNREACHABLE",
    "PRODUCTION_NONMUTATION",
    "KILL_AND_CONTAINMENT_PROPAGATED",
    "RESTART_REPLAY_RECONCILED",
    "TEARDOWN_REBUILD_FROM_AUTHORITY",
    "PRODUCTION_EQUIVALENCE_DIFFERENCES_RETAINED",
)


class ControllerQualificationDisposition(StrEnum):
    READY_FOR_9B3_AUTHORISATION_GATE = "READY_FOR_9B3_AUTHORISATION_GATE"
    NOT_READY = "NOT_READY"


class _NoRuntimeAuthority:
    authorises_live_call = False
    authorises_credentials = False
    authorises_external_egress = False
    authorises_spend = False
    authorises_publication = False
    authorises_evidence_intake = False
    authorises_canary = False
    authorises_production_mutation = False
    authorises_production_activation = False
    authorises_decision_bearing_campaign = False


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise ControllerError("controller JSON names are invalid or duplicated")
        result[key] = value
    return result


def _text(value: object, field: str, maximum: int = 2048) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ControllerError(f"{field} text differs")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if not _TOKEN.fullmatch(value):
        raise ControllerError(f"{field} token differs")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise ControllerError(f"{field} digest differs")
    try:
        validate_sha256_digest(value)
    except (TypeError, ValueError) as exc:
        raise ControllerError(f"{field} digest differs") from exc
    return value


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 64)
    if not _UTC.fullmatch(value):
        raise ControllerError(f"{field} timestamp differs")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ControllerError(f"{field} timestamp differs") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ControllerError(f"{field} integer differs")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ControllerError(f"{field} boolean differs")
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if isinstance(value, kind):
        return value
    if type(value) is not str:
        raise ControllerError(f"{field} enum differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise ControllerError(f"{field} enum differs") from exc


def _mapping(value: object, fields: frozenset[str], field: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ControllerError(f"{field} fields differ")
    return dict(value)


def _digest_mapping(
    value: object, expected_keys: tuple[str, ...], field: str
) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(expected_keys):
        raise ControllerError(f"{field} fields differ")
    return MappingProxyType(
        {key: _digest(value[key], f"{field}.{key}") for key in expected_keys}
    )


def _document(raw: bytes, schema: str, fields: frozenset[str]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise ControllerError("controller record bytes are not bounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except ControllerError:
        raise
    except (UnicodeError, json.JSONDecodeError, CanonicalizationError, RecursionError) as exc:
        raise ControllerError("controller record bytes are invalid") from exc
    if canonical != raw:
        raise ControllerError("controller record bytes must be exact canonical JSON")
    value = _mapping(value, fields | {"schema_version"}, "controller record")
    if value.pop("schema_version") != schema:
        raise ControllerError("controller record schema differs")
    return value


class _Record(_NoRuntimeAuthority):
    schema_version: ClassVar[str]

    def primitive(self) -> dict[str, object]:
        raise NotImplementedError

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class ControllerQualificationPlan(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.controller-qualification-plan.v1"
    qualification_id: str
    owner_plan_digest: str
    scope_digest: str
    shadow_manifest_digest: str
    deployment_plan_digest: str
    deployment_readiness_receipt_digest: str
    isolated_deployment_receipt_digest: str
    epoch_digest: str
    effective_manifest_digest: str
    cohort_digest: str
    run_digest: str
    attempt_digest: str
    production_snapshot_digest: str
    production_nonmutation_before_digest: str
    stage_interface_digests: Mapping[str, str]
    effective_identity_digests: Mapping[str, str]
    production_difference_ids: tuple[str, ...]
    inference_limits: Mapping[str, str]
    run_kind: RunKind
    created_at: str
    expires_at: str
    fixture_replay_only: bool = True
    campaign_started: bool = False

    def __post_init__(self) -> None:
        _token(self.qualification_id, "qualification_id")
        for field in (
            "owner_plan_digest",
            "scope_digest",
            "shadow_manifest_digest",
            "deployment_plan_digest",
            "deployment_readiness_receipt_digest",
            "isolated_deployment_receipt_digest",
            "epoch_digest",
            "effective_manifest_digest",
            "cohort_digest",
            "run_digest",
            "attempt_digest",
            "production_snapshot_digest",
            "production_nonmutation_before_digest",
        ):
            _digest(getattr(self, field), field)
        if self.owner_plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise ControllerError("owner plan digest differs")
        stage_keys = tuple(str(stage) for stage in CONTROLLER_STAGES)
        object.__setattr__(
            self,
            "stage_interface_digests",
            _digest_mapping(self.stage_interface_digests, stage_keys, "stage_interface_digests"),
        )
        identity_keys = tuple(sorted(EFFECTIVE_MANIFEST_IDENTITY_KEYS))
        if set(self.effective_identity_digests) != set(identity_keys):
            raise ControllerError("effective identity fields differ")
        object.__setattr__(
            self,
            "effective_identity_digests",
            _digest_mapping(self.effective_identity_digests, identity_keys, "effective_identity_digests"),
        )
        if any(
            self.stage_interface_digests[str(stage)]
            != self.effective_identity_digests[STAGE_MANIFEST_DIMENSIONS[stage]]
            for stage in CONTROLLER_STAGES
        ):
            raise ControllerError("stage interface does not bind the Effective Manifest")
        if (
            type(self.production_difference_ids) is not tuple
            or not self.production_difference_ids
            or len(set(self.production_difference_ids)) != len(self.production_difference_ids)
        ):
            raise ControllerError("production difference inventory differs")
        differences = tuple(_token(item, "production_difference_id") for item in self.production_difference_ids)
        if tuple(sorted(differences)) != differences:
            raise ControllerError("production difference inventory differs")
        object.__setattr__(self, "production_difference_ids", differences)
        if not isinstance(self.inference_limits, Mapping) or tuple(self.inference_limits) != differences:
            raise ControllerError("inference limit inventory differs")
        object.__setattr__(
            self,
            "inference_limits",
            MappingProxyType({key: _token(self.inference_limits[key], f"inference_limits.{key}") for key in differences}),
        )
        object.__setattr__(self, "run_kind", _enum(RunKind, self.run_kind, "run_kind"))
        if self.run_kind is not RunKind.REPLAY_QUALIFICATION:
            raise ControllerError("9B2 requires a replay qualification Run")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.expires_at, "expires_at")
        if _instant(self.created_at) >= _instant(self.expires_at):
            raise ControllerError("controller plan chronology differs")
        if self.fixture_replay_only is not True or self.campaign_started is not False:
            raise ControllerError("controller plan runtime boundary differs")

    @classmethod
    def build(
        cls,
        *,
        qualification_id: str,
        scope: ShadowScope,
        deployment_plan: DeploymentPlan,
        readiness_receipt: DeploymentReadinessReceipt,
        isolated_deployment_receipt: IsolatedDeploymentReceipt,
        epoch: EvaluationEpoch,
        effective_manifest: EffectiveManifest,
        cohort: ManifestCohort,
        run: ShadowRun,
        attempt: RunAttempt,
        stage_interface_digests: Mapping[ControllerStage | str, str],
        created_at: str,
        expires_at: str,
    ) -> Self:
        if type(scope) is not ShadowScope or type(deployment_plan) is not DeploymentPlan:
            raise ControllerError("controller predecessor type differs")
        if deployment_plan.scope_digest != scope.canonical_digest:
            raise ControllerError("controller scope binding differs")
        if (
            type(readiness_receipt) is not DeploymentReadinessReceipt
            or readiness_receipt.disposition
            is not ReadinessDisposition.READY_FOR_9B2_CONTROLLER_QUALIFICATION
            or readiness_receipt.deployment_plan_digest != deployment_plan.canonical_digest
            or not readiness_receipt.production_nonmutation_proved
            or not readiness_receipt.teardown_complete
        ):
            raise ControllerError("deployment readiness binding differs")
        if (
            type(isolated_deployment_receipt) is not IsolatedDeploymentReceipt
            or isolated_deployment_receipt.deployment_plan_digest
            != deployment_plan.canonical_digest
            or isolated_deployment_receipt.production_snapshot_digest
            != deployment_plan.production_snapshot_digest
        ):
            raise ControllerError("isolated deployment receipt binding differs")
        if (
            type(epoch) is not EvaluationEpoch
            or epoch.plan_digest != deployment_plan.owner_plan_digest
            or epoch.shadow_scope_digest != scope.canonical_digest
        ):
            raise ControllerError("Epoch binding differs")
        if type(effective_manifest) is not EffectiveManifest or not effective_manifest.identity_resolved:
            raise ControllerError("Effective Manifest identities are not resolved")
        if (
            type(cohort) is not ManifestCohort
            or cohort.epoch_digest != epoch.canonical_digest
            or cohort.manifest_digest != effective_manifest.canonical_digest
            or not cohort.decision_bearing
        ):
            raise ControllerError("Manifest Cohort binding differs")
        if (
            type(run) is not ShadowRun
            or run.run_kind is not RunKind.REPLAY_QUALIFICATION
            or run.prospective
            or run.epoch_digest != epoch.canonical_digest
            or run.cohort_digest != cohort.canonical_digest
            or run.manifest_digest != effective_manifest.canonical_digest
            or run.production_snapshot_digest != deployment_plan.production_snapshot_digest
        ):
            raise ControllerError("9B2 replay Run binding differs")
        if (
            type(attempt) is not RunAttempt
            or attempt.run_digest != run.canonical_digest
            or attempt.run_id != run.run_id
            or attempt.ordinal != 1
        ):
            raise ControllerError("9B2 Attempt binding differs")
        created = _instant(_timestamp(created_at, "created_at"))
        expiry = _instant(_timestamp(expires_at, "expires_at"))
        if (
            created < _instant(readiness_receipt.completed_at)
            or created < _instant(isolated_deployment_receipt.created_at)
            or created != _instant(run.started_at)
            or created != _instant(attempt.started_at)
            or expiry > _instant(deployment_plan.expires_at)
            or expiry > _instant(epoch.closes_at)
        ):
            raise ControllerError("controller predecessor chronology differs")
        stage_values = {str(key): value for key, value in stage_interface_digests.items()}
        expected_stage_values = {
            str(stage): effective_manifest.identity_digests[
                STAGE_MANIFEST_DIMENSIONS[stage]
            ]
            for stage in CONTROLLER_STAGES
        }
        if stage_values != expected_stage_values:
            raise ControllerError("stage interface does not bind the Effective Manifest")
        differences = tuple(sorted(scope.production_differences, key=lambda item: item.difference_id))
        return cls(
            qualification_id=qualification_id,
            owner_plan_digest=deployment_plan.owner_plan_digest,
            scope_digest=scope.canonical_digest,
            shadow_manifest_digest=deployment_plan.manifest_digest,
            deployment_plan_digest=deployment_plan.canonical_digest,
            deployment_readiness_receipt_digest=readiness_receipt.canonical_digest,
            isolated_deployment_receipt_digest=isolated_deployment_receipt.canonical_digest,
            epoch_digest=epoch.canonical_digest,
            effective_manifest_digest=effective_manifest.canonical_digest,
            cohort_digest=cohort.canonical_digest,
            run_digest=run.canonical_digest,
            attempt_digest=attempt.canonical_digest,
            production_snapshot_digest=deployment_plan.production_snapshot_digest,
            production_nonmutation_before_digest=run.production_nonmutation_before_digest,
            stage_interface_digests=stage_values,
            effective_identity_digests=effective_manifest.identity_digests,
            production_difference_ids=tuple(item.difference_id for item in differences),
            inference_limits={item.difference_id: item.inference_limit for item in differences},
            run_kind=run.run_kind,
            created_at=created_at,
            expires_at=expires_at,
        )

    def primitive(self) -> dict[str, object]:
        return {
            "attempt_digest": self.attempt_digest,
            "campaign_started": self.campaign_started,
            "cohort_digest": self.cohort_digest,
            "created_at": self.created_at,
            "deployment_plan_digest": self.deployment_plan_digest,
            "deployment_readiness_receipt_digest": self.deployment_readiness_receipt_digest,
            "effective_identity_digests": dict(self.effective_identity_digests),
            "effective_manifest_digest": self.effective_manifest_digest,
            "epoch_digest": self.epoch_digest,
            "expires_at": self.expires_at,
            "fixture_replay_only": self.fixture_replay_only,
            "inference_limits": dict(self.inference_limits),
            "isolated_deployment_receipt_digest": self.isolated_deployment_receipt_digest,
            "owner_plan_digest": self.owner_plan_digest,
            "production_difference_ids": list(self.production_difference_ids),
            "production_nonmutation_before_digest": self.production_nonmutation_before_digest,
            "production_snapshot_digest": self.production_snapshot_digest,
            "qualification_id": self.qualification_id,
            "run_digest": self.run_digest,
            "run_kind": str(self.run_kind),
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
            "shadow_manifest_digest": self.shadow_manifest_digest,
            "stage_interface_digests": dict(self.stage_interface_digests),
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["production_difference_ids"] = tuple(value["production_difference_ids"])
        value["run_kind"] = _enum(RunKind, value["run_kind"], "run_kind")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class StageFixture(_NoRuntimeAuthority):
    stage: ControllerStage
    target_interface_digest: str
    rights_receipt_digest: str
    purpose_digest: str
    credential_scope_digest: str
    egress_receipt_digest: str
    budget_reservation_digest: str
    freshness_digest: str
    request_digest: str
    response_digest: str
    proposal_digest: str | None
    decision_digest: str | None
    checkpoint_digest: str
    usage_digest: str
    cost_digest: str
    watermark: str
    started_at: str
    completed_at: str
    deterministic_replay: bool = True
    outcome: str = "COMPLETE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _enum(ControllerStage, self.stage, "stage"))
        for field in (
            "target_interface_digest",
            "rights_receipt_digest",
            "purpose_digest",
            "credential_scope_digest",
            "egress_receipt_digest",
            "budget_reservation_digest",
            "freshness_digest",
            "request_digest",
            "response_digest",
            "checkpoint_digest",
            "usage_digest",
            "cost_digest",
        ):
            _digest(getattr(self, field), field)
        if (self.proposal_digest is not None) != (self.stage in _PROPOSAL_STAGES):
            raise ControllerError("proposal authority boundary differs")
        if self.proposal_digest is not None:
            _digest(self.proposal_digest, "proposal_digest")
        if (self.decision_digest is not None) != (self.stage in _DECISION_STAGES):
            raise ControllerError("deterministic decision boundary differs")
        if self.decision_digest is not None:
            _digest(self.decision_digest, "decision_digest")
        _token(self.watermark, "watermark")
        _timestamp(self.started_at, "started_at")
        _timestamp(self.completed_at, "completed_at")
        if _instant(self.started_at) > _instant(self.completed_at):
            raise ControllerError("stage chronology differs")
        if self.deterministic_replay is not True or self.outcome != "COMPLETE":
            raise ControllerError("stage fixture outcome differs")

    def primitive(self) -> dict[str, object]:
        return {
            "budget_reservation_digest": self.budget_reservation_digest,
            "checkpoint_digest": self.checkpoint_digest,
            "completed_at": self.completed_at,
            "cost_digest": self.cost_digest,
            "credential_scope_digest": self.credential_scope_digest,
            "decision_digest": self.decision_digest,
            "deterministic_replay": self.deterministic_replay,
            "egress_receipt_digest": self.egress_receipt_digest,
            "freshness_digest": self.freshness_digest,
            "outcome": self.outcome,
            "proposal_digest": self.proposal_digest,
            "purpose_digest": self.purpose_digest,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "rights_receipt_digest": self.rights_receipt_digest,
            "stage": str(self.stage),
            "started_at": self.started_at,
            "target_interface_digest": self.target_interface_digest,
            "usage_digest": self.usage_digest,
            "watermark": self.watermark,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, frozenset(cls.__dataclass_fields__), "stage fixture")
        raw["stage"] = _enum(ControllerStage, raw["stage"], "stage")
        return cls(**raw)  # type: ignore[arg-type]

    @property
    def control_envelope_digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "budget_reservation_digest": self.budget_reservation_digest,
                    "credential_scope_digest": self.credential_scope_digest,
                    "egress_receipt_digest": self.egress_receipt_digest,
                    "freshness_digest": self.freshness_digest,
                    "purpose_digest": self.purpose_digest,
                    "request_digest": self.request_digest,
                    "rights_receipt_digest": self.rights_receipt_digest,
                    "stage": str(self.stage),
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ControllerLedgerEntry(_NoRuntimeAuthority):
    ordinal: int
    stage: ControllerStage
    kind: LedgerKind
    payload_digest: str
    previous_entry_digest: str | None
    persisted_at: str

    def __post_init__(self) -> None:
        _integer(self.ordinal, "ordinal", minimum=1)
        object.__setattr__(self, "stage", _enum(ControllerStage, self.stage, "stage"))
        object.__setattr__(self, "kind", _enum(LedgerKind, self.kind, "kind"))
        _digest(self.payload_digest, "payload_digest")
        if (self.ordinal == 1) != (self.previous_entry_digest is None):
            raise ControllerError("ledger predecessor shape differs")
        if self.previous_entry_digest is not None:
            _digest(self.previous_entry_digest, "previous_entry_digest")
        _timestamp(self.persisted_at, "persisted_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    def primitive(self) -> dict[str, object]:
        return {
            "kind": str(self.kind),
            "ordinal": self.ordinal,
            "payload_digest": self.payload_digest,
            "persisted_at": self.persisted_at,
            "previous_entry_digest": self.previous_entry_digest,
            "stage": str(self.stage),
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, frozenset(cls.__dataclass_fields__), "ledger entry")
        raw["stage"] = _enum(ControllerStage, raw["stage"], "stage")
        raw["kind"] = _enum(LedgerKind, raw["kind"], "kind")
        return cls(**raw)  # type: ignore[arg-type]


_JOURNAL_SCHEMA = """
CREATE TABLE controller_ledger (
    ordinal INTEGER PRIMARY KEY CHECK (ordinal > 0),
    entry_digest TEXT NOT NULL UNIQUE,
    entry_bytes BLOB NOT NULL
);
CREATE TRIGGER controller_ledger_no_update
BEFORE UPDATE ON controller_ledger BEGIN SELECT RAISE(ABORT, 'immutable'); END;
CREATE TRIGGER controller_ledger_no_delete
BEFORE DELETE ON controller_ledger BEGIN SELECT RAISE(ABORT, 'immutable'); END;
"""


def _verify_journal_schema(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    names = tuple(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )
    if (
        application_id != CONTROLLER_JOURNAL_APPLICATION_ID
        or version != CONTROLLER_JOURNAL_SCHEMA_VERSION
        or names
        != (
            "controller_ledger",
            "controller_ledger_no_delete",
            "controller_ledger_no_update",
        )
    ):
        raise ControllerError("controller journal schema differs")


class ControllerEvidenceJournal(_NoRuntimeAuthority):
    """Append-only isolated SQLite journal used before each downstream stage."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if type(connection) is not sqlite3.Connection:
            raise ControllerError("controller journal connection differs")
        _verify_journal_schema(connection)
        self.__connection = connection

    def append(self, entry: ControllerLedgerEntry) -> str:
        if type(entry) is not ControllerLedgerEntry:
            raise ControllerError("controller journal entry type differs")
        try:
            self.__connection.execute("BEGIN IMMEDIATE")
            row = self.__connection.execute(
                "SELECT ordinal, entry_digest FROM controller_ledger "
                "ORDER BY ordinal DESC LIMIT 1"
            ).fetchone()
            expected_ordinal = 1 if row is None else int(row[0]) + 1
            expected_predecessor = None if row is None else str(row[1])
            if (
                entry.ordinal != expected_ordinal
                or entry.previous_entry_digest != expected_predecessor
            ):
                raise ControllerError("controller journal predecessor differs")
            self.__connection.execute(
                "INSERT INTO controller_ledger(ordinal,entry_digest,entry_bytes) "
                "VALUES(?,?,?)",
                (entry.ordinal, entry.canonical_digest, entry.canonical_bytes),
            )
            self.__connection.commit()
        except Exception:
            self.__connection.rollback()
            raise
        return entry.canonical_digest

    def inventory(self) -> tuple[ControllerLedgerEntry, ...]:
        _verify_journal_schema(self.__connection)
        result: list[ControllerLedgerEntry] = []
        for ordinal, stored_digest, raw in self.__connection.execute(
            "SELECT ordinal,entry_digest,entry_bytes "
            "FROM controller_ledger ORDER BY ordinal"
        ):
            try:
                value = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_pairs)
                if canonical_json_bytes(value) != bytes(raw):
                    raise ControllerError("controller journal bytes are not canonical")
                entry = ControllerLedgerEntry.from_primitive(value)
            except ControllerError:
                raise
            except (UnicodeError, json.JSONDecodeError, CanonicalizationError) as exc:
                raise ControllerError("controller journal bytes are invalid") from exc
            if (
                entry.ordinal != ordinal
                or entry.canonical_digest != stored_digest
                or entry.previous_entry_digest
                != (None if not result else result[-1].canonical_digest)
            ):
                raise ControllerError("controller journal inventory differs")
            result.append(entry)
        return tuple(result)


def initialise_controller_journal(
    connection: sqlite3.Connection,
) -> ControllerEvidenceJournal:
    if type(connection) is not sqlite3.Connection:
        raise ControllerError("controller journal connection differs")
    existing = tuple(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        )
    )
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if existing or application_id != 0 or version != 0:
        raise ControllerError("controller journal is not pristine")
    connection.executescript(_JOURNAL_SCHEMA)
    connection.execute(f"PRAGMA application_id={CONTROLLER_JOURNAL_APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={CONTROLLER_JOURNAL_SCHEMA_VERSION}")
    connection.commit()
    return ControllerEvidenceJournal(connection)


@dataclass(frozen=True, slots=True)
class ScenarioEvidence(_NoRuntimeAuthority):
    scenario: RecoveryScenario
    outcome: ScenarioOutcome
    checkpoint_digest: str
    evidence_digest: str
    original_failure_retained: bool
    resumed_decision_bearing: bool = False
    public_effect_count: int = 0
    production_mutation_count: int = 0
    orphan_resource_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", _enum(RecoveryScenario, self.scenario, "scenario"))
        object.__setattr__(self, "outcome", _enum(ScenarioOutcome, self.outcome, "outcome"))
        _digest(self.checkpoint_digest, "checkpoint_digest")
        _digest(self.evidence_digest, "evidence_digest")
        _boolean(self.original_failure_retained, "original_failure_retained")
        _boolean(self.resumed_decision_bearing, "resumed_decision_bearing")
        for field in ("public_effect_count", "production_mutation_count", "orphan_resource_count"):
            _integer(getattr(self, field), field)

    def primitive(self) -> dict[str, object]:
        return {
            "checkpoint_digest": self.checkpoint_digest,
            "evidence_digest": self.evidence_digest,
            "original_failure_retained": self.original_failure_retained,
            "orphan_resource_count": self.orphan_resource_count,
            "outcome": str(self.outcome),
            "production_mutation_count": self.production_mutation_count,
            "public_effect_count": self.public_effect_count,
            "resumed_decision_bearing": self.resumed_decision_bearing,
            "scenario": str(self.scenario),
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, frozenset(cls.__dataclass_fields__), "scenario evidence")
        raw["scenario"] = _enum(RecoveryScenario, raw["scenario"], "scenario")
        raw["outcome"] = _enum(ScenarioOutcome, raw["outcome"], "outcome")
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ControllerCheck(_NoRuntimeAuthority):
    check_id: str
    outcome: CheckOutcome
    evidence_digest: str

    def __post_init__(self) -> None:
        _token(self.check_id, "check_id")
        if self.check_id not in CHECK_IDS:
            raise ControllerError("controller check identity differs")
        object.__setattr__(self, "outcome", _enum(CheckOutcome, self.outcome, "outcome"))
        _digest(self.evidence_digest, "evidence_digest")

    def primitive(self) -> dict[str, object]:
        return {"check_id": self.check_id, "evidence_digest": self.evidence_digest, "outcome": str(self.outcome)}

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, frozenset(cls.__dataclass_fields__), "controller check")
        raw["outcome"] = _enum(CheckOutcome, raw["outcome"], "outcome")
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EquivalenceObservation(_NoRuntimeAuthority):
    difference_id: str
    inference_limit: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _token(self.difference_id, "difference_id")
        _token(self.inference_limit, "inference_limit")
        _digest(self.evidence_digest, "evidence_digest")

    def primitive(self) -> dict[str, object]:
        return {
            "difference_id": self.difference_id,
            "evidence_digest": self.evidence_digest,
            "inference_limit": self.inference_limit,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        return cls(**_mapping(value, frozenset(cls.__dataclass_fields__), "equivalence observation"))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ControllerEvidenceBundle(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.controller-evidence-bundle.v1"
    evidence_id: str
    controller_plan_digest: str
    stages: tuple[StageFixture, ...]
    ledger: tuple[ControllerLedgerEntry, ...]
    scenarios: tuple[ScenarioEvidence, ...]
    checks: tuple[ControllerCheck, ...]
    equivalence_observations: tuple[EquivalenceObservation, ...]
    production_nonmutation_before_digest: str
    production_nonmutation_after_digest: str
    sealed_at: str
    proposal_authority_commit_count: int = 0
    deterministic_authority_commit_count: int = 5
    external_request_count: int = 0
    provider_call_count: int = 0
    credential_use_count: int = 0
    gross_monetary_minor_units: int = 0
    decision_bearing_case_count: int = 0
    public_effect_count: int = 0
    production_mutation_count: int = 0
    evidence_intake_count: int = 0

    def __post_init__(self) -> None:
        _token(self.evidence_id, "evidence_id")
        _digest(self.controller_plan_digest, "controller_plan_digest")
        if type(self.stages) is not tuple or any(type(item) is not StageFixture for item in self.stages):
            raise ControllerError("controller stage evidence type differs")
        if tuple(item.stage for item in self.stages) != CONTROLLER_STAGES:
            raise ControllerError("controller stage inventory differs")
        if type(self.ledger) is not tuple or not self.ledger or any(type(item) is not ControllerLedgerEntry for item in self.ledger):
            raise ControllerError("controller ledger type differs")
        if type(self.scenarios) is not tuple or tuple(item.scenario for item in self.scenarios) != RECOVERY_SCENARIOS:
            raise ControllerError("recovery scenario inventory differs")
        if type(self.checks) is not tuple or tuple(item.check_id for item in self.checks) != CHECK_IDS:
            raise ControllerError("controller check inventory differs")
        if type(self.equivalence_observations) is not tuple or not self.equivalence_observations:
            raise ControllerError("production equivalence inventory differs")
        _digest(self.production_nonmutation_before_digest, "production_nonmutation_before_digest")
        _digest(self.production_nonmutation_after_digest, "production_nonmutation_after_digest")
        _timestamp(self.sealed_at, "sealed_at")
        if any(_instant(item.completed_at) > _instant(self.sealed_at) for item in self.stages):
            raise ControllerError("controller evidence predates a stage")
        for field in (
            "proposal_authority_commit_count",
            "deterministic_authority_commit_count",
            "external_request_count",
            "provider_call_count",
            "credential_use_count",
            "gross_monetary_minor_units",
            "decision_bearing_case_count",
            "public_effect_count",
            "production_mutation_count",
            "evidence_intake_count",
        ):
            _integer(getattr(self, field), field)

    def primitive(self) -> dict[str, object]:
        return {
            "checks": [item.primitive() for item in self.checks],
            "controller_plan_digest": self.controller_plan_digest,
            "credential_use_count": self.credential_use_count,
            "decision_bearing_case_count": self.decision_bearing_case_count,
            "deterministic_authority_commit_count": self.deterministic_authority_commit_count,
            "equivalence_observations": [item.primitive() for item in self.equivalence_observations],
            "evidence_id": self.evidence_id,
            "evidence_intake_count": self.evidence_intake_count,
            "external_request_count": self.external_request_count,
            "gross_monetary_minor_units": self.gross_monetary_minor_units,
            "ledger": [item.primitive() for item in self.ledger],
            "production_mutation_count": self.production_mutation_count,
            "production_nonmutation_after_digest": self.production_nonmutation_after_digest,
            "production_nonmutation_before_digest": self.production_nonmutation_before_digest,
            "proposal_authority_commit_count": self.proposal_authority_commit_count,
            "provider_call_count": self.provider_call_count,
            "public_effect_count": self.public_effect_count,
            "scenarios": [item.primitive() for item in self.scenarios],
            "schema_version": self.schema_version,
            "sealed_at": self.sealed_at,
            "stages": [item.primitive() for item in self.stages],
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        for field, kind in (
            ("stages", StageFixture),
            ("ledger", ControllerLedgerEntry),
            ("scenarios", ScenarioEvidence),
            ("checks", ControllerCheck),
            ("equivalence_observations", EquivalenceObservation),
        ):
            items = value[field]
            if type(items) is not list:
                raise ControllerError(f"{field} must be an array")
            value[field] = tuple(kind.from_primitive(item) for item in items)
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ControllerQualificationReceipt(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.controller-qualification-receipt.v1"
    receipt_id: str
    controller_plan_digest: str
    controller_evidence_digest: str
    disposition: ControllerQualificationDisposition
    reason: str
    production_nonmutation_proved: bool
    full_teardown_rebuild_proved: bool
    completed_at: str
    runtime_campaign_authority_still_required: bool = True
    campaign_started: bool = False

    def __post_init__(self) -> None:
        _token(self.receipt_id, "receipt_id")
        _digest(self.controller_plan_digest, "controller_plan_digest")
        _digest(self.controller_evidence_digest, "controller_evidence_digest")
        object.__setattr__(self, "disposition", _enum(ControllerQualificationDisposition, self.disposition, "disposition"))
        _token(self.reason, "reason")
        _boolean(self.production_nonmutation_proved, "production_nonmutation_proved")
        _boolean(self.full_teardown_rebuild_proved, "full_teardown_rebuild_proved")
        _timestamp(self.completed_at, "completed_at")
        if self.runtime_campaign_authority_still_required is not True or self.campaign_started is not False:
            raise ControllerError("9B2 receipt cannot grant or claim campaign authority")
        if self.disposition is ControllerQualificationDisposition.READY_FOR_9B3_AUTHORISATION_GATE:
            if (
                self.reason != "CONTROLLER_QUALIFICATION_COMPLETE"
                or not self.production_nonmutation_proved
                or not self.full_teardown_rebuild_proved
            ):
                raise ControllerError("ready controller receipt differs")
        elif self.reason != "CONTROLLER_EVIDENCE_INCOMPLETE_OR_FAILED":
            raise ControllerError("not-ready controller receipt differs")

    def primitive(self) -> dict[str, object]:
        return {
            "campaign_started": self.campaign_started,
            "completed_at": self.completed_at,
            "controller_evidence_digest": self.controller_evidence_digest,
            "controller_plan_digest": self.controller_plan_digest,
            "disposition": str(self.disposition),
            "full_teardown_rebuild_proved": self.full_teardown_rebuild_proved,
            "production_nonmutation_proved": self.production_nonmutation_proved,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "runtime_campaign_authority_still_required": self.runtime_campaign_authority_still_required,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["disposition"] = _enum(ControllerQualificationDisposition, value["disposition"], "disposition")
        return cls(**value)  # type: ignore[arg-type]


class ReplayIntegrationController(_NoRuntimeAuthority):
    """Execute the exact integrated path with content-addressed replay fixtures."""

    def __init__(
        self,
        plan: ControllerQualificationPlan,
        journal: ControllerEvidenceJournal,
    ) -> None:
        if type(plan) is not ControllerQualificationPlan:
            raise ControllerError("controller plan type differs")
        if type(journal) is not ControllerEvidenceJournal:
            raise ControllerError("controller journal type differs")
        if journal.inventory():
            raise ControllerError("controller qualification requires an empty journal")
        self.__plan = plan
        self.__journal = journal

    def qualify(
        self,
        *,
        fixtures: tuple[StageFixture, ...],
        scenario_evidence_digests: Mapping[RecoveryScenario | str, str],
        check_evidence_digests: Mapping[str, str],
        equivalence_evidence_digests: Mapping[str, str],
        sealed_at: str,
        production_nonmutation_after_digest: str,
    ) -> ControllerEvidenceBundle:
        if type(fixtures) is not tuple or tuple(item.stage for item in fixtures) != CONTROLLER_STAGES:
            raise ControllerError("controller stage inventory differs")
        scenario_digests = {str(key): value for key, value in scenario_evidence_digests.items()}
        if set(scenario_digests) != {str(item) for item in RECOVERY_SCENARIOS}:
            raise ControllerError("recovery scenario evidence inventory differs")
        check_digests = dict(check_evidence_digests)
        if set(check_digests) != set(CHECK_IDS):
            raise ControllerError("controller check evidence inventory differs")
        equivalence_digests = dict(equivalence_evidence_digests)
        if set(equivalence_digests) != set(self.__plan.production_difference_ids):
            raise ControllerError("production equivalence evidence inventory differs")
        previous_response: str | None = None
        previous_completed_at: str | None = None
        ledger: list[ControllerLedgerEntry] = []
        for fixture in fixtures:
            if type(fixture) is not StageFixture:
                raise ControllerError("controller stage fixture type differs")
            if fixture.target_interface_digest != self.__plan.stage_interface_digests[str(fixture.stage)]:
                raise ControllerError("controller target interface differs")
            if previous_response is not None and fixture.request_digest != previous_response:
                raise ControllerError("controller stage chain differs")
            if previous_completed_at is not None and _instant(fixture.started_at) < _instant(previous_completed_at):
                raise ControllerError("controller downstream stage predates persisted evidence")
            if _instant(fixture.started_at) < _instant(self.__plan.created_at):
                raise ControllerError("controller stage predates plan")
            payloads: list[tuple[LedgerKind, str]] = [
                (LedgerKind.CONTROL_ENVELOPE, fixture.control_envelope_digest),
                (LedgerKind.BUDGET_RESERVATION, fixture.budget_reservation_digest),
                (LedgerKind.REQUEST, fixture.request_digest),
                (LedgerKind.RESPONSE, fixture.response_digest),
            ]
            if fixture.proposal_digest is not None:
                payloads.append((LedgerKind.PROPOSAL, fixture.proposal_digest))
            if fixture.decision_digest is not None:
                payloads.append((LedgerKind.DECISION, fixture.decision_digest))
            payloads.extend(
                (
                    (LedgerKind.CHECKPOINT, fixture.checkpoint_digest),
                    (LedgerKind.USAGE, fixture.usage_digest),
                    (LedgerKind.COST, fixture.cost_digest),
                )
            )
            for kind, payload in payloads:
                entry = ControllerLedgerEntry(
                    ordinal=len(ledger) + 1,
                    stage=fixture.stage,
                    kind=kind,
                    payload_digest=payload,
                    previous_entry_digest=None
                    if not ledger
                    else ledger[-1].canonical_digest,
                    persisted_at=fixture.completed_at
                    if kind
                    not in {
                        LedgerKind.CONTROL_ENVELOPE,
                        LedgerKind.BUDGET_RESERVATION,
                        LedgerKind.REQUEST,
                    }
                    else fixture.started_at,
                )
                self.__journal.append(entry)
                ledger.append(entry)
            previous_response = fixture.response_digest
            previous_completed_at = fixture.completed_at
        if self.__journal.inventory() != tuple(ledger):
            raise ControllerError("controller journal replay differs")
        terminal = ledger[-1].canonical_digest
        scenarios = tuple(
            ScenarioEvidence(
                scenario=scenario,
                outcome=_SCENARIO_OUTCOMES[scenario],
                checkpoint_digest=terminal,
                evidence_digest=_digest(
                    scenario_digests[str(scenario)],
                    f"scenario_evidence_digests.{scenario}",
                ),
                original_failure_retained=_SCENARIO_OUTCOMES[scenario]
                in {ScenarioOutcome.BLOCKED_RECONCILED, ScenarioOutcome.EARLY_STOPPED},
            )
            for scenario in RECOVERY_SCENARIOS
        )
        checks = tuple(
            ControllerCheck(
                check_id=check_id,
                outcome=CheckOutcome.PASS,
                evidence_digest=_digest(
                    check_digests[check_id], f"check_evidence_digests.{check_id}"
                ),
            )
            for check_id in CHECK_IDS
        )
        differences = tuple(
            EquivalenceObservation(
                difference_id=difference_id,
                inference_limit=self.__plan.inference_limits[difference_id],
                evidence_digest=_digest(
                    equivalence_digests[difference_id],
                    f"equivalence_evidence_digests.{difference_id}",
                ),
            )
            for difference_id in self.__plan.production_difference_ids
        )
        return ControllerEvidenceBundle(
            evidence_id=f"{self.__plan.qualification_id}-evidence",
            controller_plan_digest=self.__plan.canonical_digest,
            stages=fixtures,
            ledger=tuple(ledger),
            scenarios=scenarios,
            checks=checks,
            equivalence_observations=differences,
            production_nonmutation_before_digest=self.__plan.production_nonmutation_before_digest,
            production_nonmutation_after_digest=production_nonmutation_after_digest,
            sealed_at=sealed_at,
        )


def _ledger_is_exact(bundle: ControllerEvidenceBundle) -> bool:
    position = 0
    previous: ControllerLedgerEntry | None = None
    for fixture in bundle.stages:
        expected = [
            (
                LedgerKind.CONTROL_ENVELOPE,
                fixture.control_envelope_digest,
                fixture.started_at,
            ),
            (
                LedgerKind.BUDGET_RESERVATION,
                fixture.budget_reservation_digest,
                fixture.started_at,
            ),
            (LedgerKind.REQUEST, fixture.request_digest, fixture.started_at),
            (LedgerKind.RESPONSE, fixture.response_digest, fixture.completed_at),
        ]
        if fixture.proposal_digest is not None:
            expected.append(
                (LedgerKind.PROPOSAL, fixture.proposal_digest, fixture.completed_at)
            )
        if fixture.decision_digest is not None:
            expected.append(
                (LedgerKind.DECISION, fixture.decision_digest, fixture.completed_at)
            )
        expected.extend(
            (
                (LedgerKind.CHECKPOINT, fixture.checkpoint_digest, fixture.completed_at),
                (LedgerKind.USAGE, fixture.usage_digest, fixture.completed_at),
                (LedgerKind.COST, fixture.cost_digest, fixture.completed_at),
            )
        )
        entries = bundle.ledger[position : position + len(expected)]
        if len(entries) != len(expected) or any(
            entry.stage is not fixture.stage
            or entry.kind is not kind
            or entry.payload_digest != payload
            or entry.persisted_at != persisted_at
            for entry, (kind, payload, persisted_at) in zip(
                entries, expected, strict=True
            )
        ):
            return False
        for entry in entries:
            if entry.ordinal != position + 1:
                return False
            if entry.previous_entry_digest != (None if previous is None else previous.canonical_digest):
                return False
            previous = entry
            position += 1
    return position == len(bundle.ledger)


def _stage_chain_is_exact(stages: tuple[StageFixture, ...]) -> bool:
    for previous, current in zip(stages, stages[1:], strict=False):
        if (
            current.request_digest != previous.response_digest
            or _instant(current.started_at) < _instant(previous.completed_at)
        ):
            return False
    return True


def qualify_controller(
    plan: ControllerQualificationPlan,
    evidence: ControllerEvidenceBundle,
    *,
    receipt_id: str,
) -> ControllerQualificationReceipt:
    """Create a non-activating 9B2 receipt from one closed evidence bundle."""

    if type(plan) is not ControllerQualificationPlan or type(evidence) is not ControllerEvidenceBundle:
        raise ControllerError("controller qualification types differ")
    scenario_exact = all(
        item.outcome is _SCENARIO_OUTCOMES[item.scenario]
        and not item.resumed_decision_bearing
        and item.public_effect_count == 0
        and item.production_mutation_count == 0
        and item.orphan_resource_count == 0
        and (
            item.original_failure_retained
            if item.outcome in {ScenarioOutcome.BLOCKED_RECONCILED, ScenarioOutcome.EARLY_STOPPED}
            else True
        )
        for item in evidence.scenarios
    )
    equivalence_exact = tuple(item.difference_id for item in evidence.equivalence_observations) == plan.production_difference_ids and all(
        item.inference_limit == plan.inference_limits[item.difference_id]
        for item in evidence.equivalence_observations
    )
    exact = (
        evidence.controller_plan_digest == plan.canonical_digest,
        tuple(item.stage for item in evidence.stages) == CONTROLLER_STAGES,
        all(item.target_interface_digest == plan.stage_interface_digests[str(item.stage)] for item in evidence.stages),
        all(item.outcome == "COMPLETE" and item.deterministic_replay for item in evidence.stages),
        _stage_chain_is_exact(evidence.stages),
        _ledger_is_exact(evidence),
        scenario_exact,
        all(item.outcome is CheckOutcome.PASS for item in evidence.checks),
        equivalence_exact,
        evidence.production_nonmutation_before_digest == plan.production_nonmutation_before_digest,
        evidence.production_nonmutation_after_digest == evidence.production_nonmutation_before_digest,
        _instant(evidence.sealed_at) <= _instant(plan.expires_at),
        evidence.proposal_authority_commit_count == 0,
        evidence.deterministic_authority_commit_count == len(_DECISION_STAGES),
        evidence.external_request_count == 0,
        evidence.provider_call_count == 0,
        evidence.credential_use_count == 0,
        evidence.gross_monetary_minor_units == 0,
        evidence.decision_bearing_case_count == 0,
        evidence.public_effect_count == 0,
        evidence.production_mutation_count == 0,
        evidence.evidence_intake_count == 0,
    )
    passed = all(exact)
    teardown = next(item for item in evidence.scenarios if item.scenario is RecoveryScenario.TEARDOWN_REBUILD)
    return ControllerQualificationReceipt(
        receipt_id=receipt_id,
        controller_plan_digest=plan.canonical_digest,
        controller_evidence_digest=evidence.canonical_digest,
        disposition=(
            ControllerQualificationDisposition.READY_FOR_9B3_AUTHORISATION_GATE
            if passed
            else ControllerQualificationDisposition.NOT_READY
        ),
        reason=(
            "CONTROLLER_QUALIFICATION_COMPLETE"
            if passed
            else "CONTROLLER_EVIDENCE_INCOMPLETE_OR_FAILED"
        ),
        production_nonmutation_proved=(
            evidence.production_nonmutation_before_digest
            == evidence.production_nonmutation_after_digest
            and evidence.production_mutation_count == 0
        ),
        full_teardown_rebuild_proved=(
            teardown.outcome is ScenarioOutcome.REBUILT
            and teardown.orphan_resource_count == 0
        ),
        completed_at=evidence.sealed_at,
    )


__all__ = [
    "CHECK_IDS",
    "CONTROLLER_STAGES",
    "RECOVERY_SCENARIOS",
    "STAGE_MANIFEST_DIMENSIONS",
    "CheckOutcome",
    "ControllerCheck",
    "ControllerError",
    "ControllerEvidenceBundle",
    "ControllerEvidenceJournal",
    "ControllerLedgerEntry",
    "ControllerQualificationDisposition",
    "ControllerQualificationPlan",
    "ControllerQualificationReceipt",
    "ControllerStage",
    "EquivalenceObservation",
    "LedgerKind",
    "RecoveryScenario",
    "ReplayIntegrationController",
    "ScenarioEvidence",
    "ScenarioOutcome",
    "StageFixture",
    "qualify_controller",
    "initialise_controller_journal",
]
