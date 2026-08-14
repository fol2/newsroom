"""Checked Increment 8 readiness and pre-measurement numerical decisions.

The canonical record freezes the fixture qualification boundary.  Loading it
does not execute a provider, use a credential, permit egress, or grant shadow,
canary, publication, or production authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment5._traceability_model import (
    DEFERRED_TO_INCREMENT_8_REQUIREMENTS,
)

PRIOR_READINESS_CONTRACT_PATH = Path(__file__).with_name(
    "increment8_readiness_v1.json"
)
READINESS_CONTRACT_PATH = Path(__file__).with_name("increment8_readiness_v2.json")
PRIOR_READINESS_DIGEST = (
    "sha256:52ad9f2d6022e95d738fe24913db2f379a91f6c945319db613b1b50cdea07d4c"
)
EXPECTED_READINESS_DIGEST = (
    "sha256:5fd68e242913561c812a443815bb67b3a7e0faa00ec4e1de657fe38c71078685"
)

EXPECTED_CORRECTION_BASE = {
    "commit": "1c03102dde3a666cf72ee97197bbf339e42f5b4e",
    "tree": "6ea8893cb1f5a0a33d6bf94abced81c9cea9a59c",
    "schema_version": 32,
    "schema_fingerprint": (
        "sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676"
    ),
    "migration_history_digest": (
        "sha256:5a48fd76cd11f266e19a4b48174d0c009f320a8d00d3eeb281a558fc2d561910"
    ),
}

EXPECTED_CORRECTIVE_STATUS = {
    "blocking_issues": (463, 464, 465, 466, 467, 428, 468),
    "increment8_completion_authorised": False,
    "legacy_v1_results_are_qualification_evidence": False,
    "operational_admission_authorised": False,
    "qualification_evidence_acceptance_authorised": False,
    "sole_active_coding_issue": 462,
}

EXPECTED_REQUIRED_SLICE_MANIFEST = (
    {
        "slice_id": "GEOGRAPHY_GLOBAL",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.geography",
            "operator": "EQ",
            "value": "GLOBAL",
        },
    },
    {
        "slice_id": "GEOGRAPHY_HONG_KONG",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.geography",
            "operator": "EQ",
            "value": "HONG_KONG",
        },
    },
    {
        "slice_id": "GEOGRAPHY_UNITED_KINGDOM",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.geography",
            "operator": "EQ",
            "value": "UNITED_KINGDOM",
        },
    },
    {
        "slice_id": "LANGUAGE_EN_GB",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.language",
            "operator": "EQ",
            "value": "EN_GB",
        },
    },
    {
        "slice_id": "LANGUAGE_MIXED_EN_GB_ZH_HANT_HK",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.language",
            "operator": "EQ",
            "value": "MIXED_EN_GB_ZH_HANT_HK",
        },
    },
    {
        "slice_id": "LANGUAGE_ZH_HANT_HK",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.language",
            "operator": "EQ",
            "value": "ZH_HANT_HK",
        },
    },
    {
        "slice_id": "SOURCE_MULTI_DOMAIN_CORROBORATED",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "source_evidence.distinct_domain_count",
            "operator": "GTE",
            "value": 2,
        },
    },
    {
        "slice_id": "TRANSITION_FAILURE_HEAVY",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "fixture.injected_failure_count",
            "operator": "GTE",
            "value": 2,
        },
    },
    {
        "slice_id": "URGENCY_URGENT",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.urgency",
            "operator": "EQ",
            "value": "URGENT",
        },
    },
)

EXPECTED_CASE_STRATA_MANIFEST = (
    {
        "stratum_id": "NEGATIVE",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "expected.candidate_outcome",
            "operator": "EQ",
            "value": "NO_CANDIDATE",
        },
    },
    {
        "stratum_id": "UNCHANGED",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "expected.transition_outcome",
            "operator": "EQ",
            "value": "UNCHANGED",
        },
    },
    {
        "stratum_id": "FAILURE_HEAVY",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "fixture.injected_failure_count",
            "operator": "GTE",
            "value": 2,
        },
    },
)

EXPECTED_REQUIRED_SLICE_POLICY = {
    "all_manifest_slices_required_for_release": True,
    "case_may_match_multiple_slices": True,
    "counting_unit": "DISTINCT_CASE_DIGEST_PER_SLICE",
    "invented_slices_allowed": False,
    "membership_changes_after_first_result_allowed": False,
    "membership_evaluated_from": "FROZEN_CASE_INPUT_MANIFEST_BEFORE_RESULT",
    "policy_changes_after_first_result_allowed": False,
}

EXPECTED_CASE_STRATA_POLICY = {
    "all_manifest_strata_required_for_release": True,
    "case_may_match_multiple_strata": True,
    "counting_unit": "DISTINCT_CASE_DIGEST_PER_STRATUM",
    "invented_strata_allowed": False,
    "membership_changes_after_first_result_allowed": False,
    "membership_evaluated_from": "FROZEN_CASE_INPUT_MANIFEST_BEFORE_RESULT",
    "policy_changes_after_first_result_allowed": False,
}


class Increment8ReadinessError(ValueError):
    """The supplied record is not the reviewed Increment 8R contract."""


class GateTier(StrEnum):
    L = "L"
    S = "S"
    M = "M"


class CorrectiveGate(StrEnum):
    QUALIFICATION_EVIDENCE_ACCEPTANCE = "qualification_evidence_acceptance_authorised"
    OPERATIONAL_ADMISSION = "operational_admission_authorised"
    INCREMENT8_COMPLETION = "increment8_completion_authorised"


@dataclass(frozen=True, slots=True)
class ChildAllocation:
    issue_number: int
    atom: str
    title: str
    dependencies: tuple[int, ...]
    gate_tier: GateTier
    public_modules: tuple[str, ...]
    schema_ids: tuple[str, ...]
    migration_version: int | None
    migration_name: str | None
    migration_module: str | None
    table_names: tuple[str, ...]
    interface_ownership: tuple[str, ...]
    requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Increment8ReadinessContract:
    schema_version: str
    contract_id: str
    contract_version: str
    issue_number: int
    parent_issue_number: int
    accepted_base_commit: str
    accepted_base_tree: str
    accepted_schema_version: int
    accepted_schema_fingerprint: str
    accepted_last_migration_name: str
    accepted_migration_history: tuple[tuple[int, str, str], ...]
    superseded_contract_digest: str
    correction_base_commit: str
    correction_base_tree: str
    correction_base_schema_version: int
    correction_base_schema_fingerprint: str
    correction_base_migration_history_digest: str
    corrective_status: Mapping[str, object]
    effective_when: str
    authority: Mapping[str, object]
    version_manifest: Mapping[str, object]
    evaluation_plan: Mapping[str, object]
    operational_profile: Mapping[str, object]
    allocations: tuple[ChildAllocation, ...]
    parallel_waves: Mapping[int, tuple[int, ...]]
    migration_policy: Mapping[str, object]
    gate_requirements: Mapping[GateTier, tuple[str, ...]]
    exclusions: tuple[str, ...]
    contract_digest: str

    @property
    def allocation_by_issue(self) -> Mapping[int, ChildAllocation]:
        return MappingProxyType({item.issue_number: item for item in self.allocations})


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise Increment8ReadinessError(f"duplicate object name: {name}")
        result[name] = value
    return result


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Increment8ReadinessError(f"{field} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise Increment8ReadinessError(f"{field} fields differ")


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Increment8ReadinessError(f"{field} must be an integer")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise Increment8ReadinessError(f"{field} must contain non-empty strings")
    return tuple(value)


def _integers(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise Increment8ReadinessError(f"{field} must be an array")
    return tuple(_integer(item, field) for item in value)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({name: _freeze(item) for name, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {name: _thaw(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _prior_payload() -> Mapping[str, object]:
    try:
        raw = PRIOR_READINESS_CONTRACT_PATH.read_bytes()
        if digest_bytes(raw) != PRIOR_READINESS_DIGEST:
            raise Increment8ReadinessError("prior readiness bytes differ")
        document = _mapping(
            json.loads(raw.decode("utf-8", errors="strict")), "prior contract"
        )
        return _mapping(document.get("payload"), "prior payload")
    except Increment8ReadinessError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
        raise Increment8ReadinessError("cannot read prior readiness contract") from exc


def _frozen_mapping(value: object, field: str) -> Mapping[str, object]:
    result = _freeze(_mapping(value, field))
    assert isinstance(result, Mapping)
    return result


def _history(value: object) -> tuple[tuple[int, str, str], ...]:
    if not isinstance(value, list):
        raise Increment8ReadinessError("migration_history must be an array")
    result: list[tuple[int, str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, list) or len(item) != 3:
            raise Increment8ReadinessError(f"migration_history[{index}] differs")
        version = _integer(item[0], f"migration_history[{index}].version")
        name, checksum = item[1], item[2]
        if not isinstance(name, str) or not isinstance(checksum, str):
            raise Increment8ReadinessError(f"migration_history[{index}] differs")
        validate_sha256_digest(checksum, field=f"migration_history[{index}].checksum")
        result.append((version, name, checksum))
    return tuple(result)


def _allocation(value: object, index: int) -> ChildAllocation:
    field = f"allocations[{index}]"
    raw = _mapping(value, field)
    _exact_keys(
        raw,
        {
            "issue_number",
            "atom",
            "title",
            "dependencies",
            "gate_tier",
            "public_modules",
            "schema_ids",
            "migration_version",
            "migration_name",
            "migration_module",
            "table_names",
            "interface_ownership",
            "requirement_ids",
        },
        field,
    )
    migration_version = raw["migration_version"]
    if migration_version is not None:
        migration_version = _integer(migration_version, f"{field}.migration_version")
    for name in ("migration_name", "migration_module"):
        if raw[name] is not None and not isinstance(raw[name], str):
            raise Increment8ReadinessError(f"{field}.{name} must be text")
    return ChildAllocation(
        issue_number=_integer(raw["issue_number"], f"{field}.issue_number"),
        atom=str(raw["atom"]),
        title=str(raw["title"]),
        dependencies=_integers(raw["dependencies"], f"{field}.dependencies"),
        gate_tier=GateTier(str(raw["gate_tier"])),
        public_modules=_strings(raw["public_modules"], f"{field}.public_modules"),
        schema_ids=_strings(raw["schema_ids"], f"{field}.schema_ids"),
        migration_version=migration_version,
        migration_name=None
        if raw["migration_name"] is None
        else str(raw["migration_name"]),
        migration_module=None
        if raw["migration_module"] is None
        else str(raw["migration_module"]),
        table_names=_strings(raw["table_names"], f"{field}.table_names"),
        interface_ownership=_strings(
            raw["interface_ownership"], f"{field}.interface_ownership"
        ),
        requirement_ids=_strings(raw["requirement_ids"], f"{field}.requirement_ids"),
    )


def _validate_contract(contract: Increment8ReadinessContract) -> None:
    if contract.schema_version != "newsroom.increment8.readiness.v2":
        raise Increment8ReadinessError("corrective readiness schema differs")
    if contract.contract_version != "increment8-readiness-v2":
        raise Increment8ReadinessError("corrective readiness version differs")
    if contract.superseded_contract_digest != PRIOR_READINESS_DIGEST:
        raise Increment8ReadinessError("superseded readiness identity differs")
    correction_base = {
        "commit": contract.correction_base_commit,
        "tree": contract.correction_base_tree,
        "schema_version": contract.correction_base_schema_version,
        "schema_fingerprint": contract.correction_base_schema_fingerprint,
        "migration_history_digest": contract.correction_base_migration_history_digest,
    }
    if correction_base != EXPECTED_CORRECTION_BASE:
        raise Increment8ReadinessError("corrective base differs")
    if contract.corrective_status != EXPECTED_CORRECTIVE_STATUS:
        raise Increment8ReadinessError("corrective qualification blockade differs")
    if tuple(item.issue_number for item in contract.allocations) != tuple(
        range(462, 469)
    ):
        raise Increment8ReadinessError("Increment 8 child inventory differs")
    requirements = [
        requirement
        for item in contract.allocations
        for requirement in item.requirement_ids
    ]
    if len(requirements) != len(set(requirements)):
        raise Increment8ReadinessError("requirement ownership overlaps")
    if set(requirements) != set(DEFERRED_TO_INCREMENT_8_REQUIREMENTS):
        raise Increment8ReadinessError("Increment 8 requirement ownership differs")
    for attribute in (
        "public_modules",
        "schema_ids",
        "table_names",
        "interface_ownership",
    ):
        values = [
            value for item in contract.allocations for value in getattr(item, attribute)
        ]
        if len(values) != len(set(values)):
            raise Increment8ReadinessError(f"{attribute} ownership overlaps")
    reservations = [
        item for item in contract.allocations if item.migration_version is not None
    ]
    if tuple(item.migration_version for item in reservations) != (30, 31, 32):
        raise Increment8ReadinessError("migration reservation differs")
    for item in contract.allocations:
        migration_fields = (
            item.migration_version,
            item.migration_name,
            item.migration_module,
        )
        if any(value is None for value in migration_fields) != all(
            value is None for value in migration_fields
        ):
            raise Increment8ReadinessError("migration ownership is incomplete")
    wave_by_issue = {
        issue: wave
        for wave, issues in contract.parallel_waves.items()
        for issue in issues
    }
    expected_nodes = set(range(462, 469)) | {428}
    if set(wave_by_issue) != expected_nodes:
        raise Increment8ReadinessError("dependency waves differ")
    for item in contract.allocations:
        for dependency in item.dependencies:
            if (
                dependency in wave_by_issue
                and wave_by_issue[dependency] >= wave_by_issue[item.issue_number]
            ):
                raise Increment8ReadinessError(
                    "dependency wave precedes its dependency"
                )
    authority = contract.authority
    for field in (
        "production_activation_authorised",
        "live_shadow_authorised",
        "provider_execution_authorised",
        "external_egress_authorised",
        "credential_use_authorised",
    ):
        if authority.get(field) is not False:
            raise Increment8ReadinessError(f"{field} must remain false")
    if authority.get("external_spend_pence") != 0:
        raise Increment8ReadinessError("external spend must remain zero")
    if contract.evaluation_plan.get("maximum_unresolved_release_disagreements") != 0:
        raise Increment8ReadinessError("release disagreement limit must remain zero")
    if (
        contract.evaluation_plan.get("required_slice_manifest")
        != EXPECTED_REQUIRED_SLICE_MANIFEST
    ):
        raise Increment8ReadinessError("required slice manifest differs")
    if (
        contract.evaluation_plan.get("case_strata_manifest")
        != EXPECTED_CASE_STRATA_MANIFEST
    ):
        raise Increment8ReadinessError("Case stratum manifest differs")
    if (
        contract.evaluation_plan.get("required_slice_policy")
        != EXPECTED_REQUIRED_SLICE_POLICY
    ):
        raise Increment8ReadinessError("required slice policy differs")
    if (
        contract.evaluation_plan.get("case_strata_policy")
        != EXPECTED_CASE_STRATA_POLICY
    ):
        raise Increment8ReadinessError("Case stratum policy differs")
    if (
        contract.operational_profile.get("capacity", {}).get(
            "maximum_external_spend_pence"
        )
        != 0
    ):  # type: ignore[union-attr]
        raise Increment8ReadinessError("profile external spend must remain zero")
    migration_policy = contract.migration_policy
    if migration_policy.get("additive_migrations_only") is not True:
        raise Increment8ReadinessError("migration policy must remain additive")
    if migration_policy.get("history_preservation_required") is not True:
        raise Increment8ReadinessError("migration history preservation is required")
    if migration_policy.get("policy_versions") != (30, 31, 32):
        raise Increment8ReadinessError("migration policy version scope differs")

    prior = _prior_payload()
    prior_plan = _mapping(prior["evaluation_plan"], "prior evaluation_plan")
    current_plan = _mapping(_thaw(contract.evaluation_plan), "evaluation_plan")
    for name in (
        "required_slice_manifest",
        "required_slice_policy",
        "case_strata_manifest",
        "case_strata_policy",
    ):
        current_plan.pop(name, None)
    if current_plan != prior_plan:
        raise Increment8ReadinessError("accepted numerical Evaluation Plan differs")
    if _thaw(contract.operational_profile) != prior["operational_profile"]:
        raise Increment8ReadinessError("accepted numerical Operational Profile differs")
    if _thaw(contract.authority) != prior["authority"]:
        raise Increment8ReadinessError("accepted non-effect authority differs")
    if list(contract.exclusions) != prior["exclusions"]:
        raise Increment8ReadinessError("accepted exclusions differ")
    prior_migration_policy = _mapping(
        prior["migration_policy"], "prior migration_policy"
    )
    current_migration_policy = _mapping(
        _thaw(contract.migration_policy), "migration_policy"
    )
    for name in (
        "additive_migrations_only",
        "history_preservation_required",
        "policy_versions",
    ):
        current_migration_policy.pop(name, None)
    if current_migration_policy != prior_migration_policy:
        raise Increment8ReadinessError("accepted migration reservations differ")


def load_increment8_readiness_contract(path: Path) -> Increment8ReadinessContract:
    """Load and validate the exact canonical 8R decision record."""

    if not isinstance(path, Path):
        raise Increment8ReadinessError("readiness path must be a pathlib.Path")
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
        )
        canonical = canonical_json_bytes(document)
    except Increment8ReadinessError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, CanonicalizationError) as exc:
        raise Increment8ReadinessError(
            "cannot read canonical Increment 8R contract"
        ) from exc
    if raw != canonical:
        raise Increment8ReadinessError("readiness record must use exact canonical JSON")
    contract_digest = digest_bytes(raw)
    if contract_digest != EXPECTED_READINESS_DIGEST:
        raise Increment8ReadinessError("readiness bytes differ from reviewed v2")

    try:
        top = _mapping(document, "contract")
        _exact_keys(top, {"schema_version", "payload"}, "contract")
        payload = _mapping(top["payload"], "payload")
        _exact_keys(
            payload,
            {
                "contract_id",
                "contract_version",
                "issue_number",
                "parent_issue_number",
                "accepted_base",
                "supersedes",
                "correction_base",
                "corrective_status",
                "effective_when",
                "authority",
                "version_manifest",
                "evaluation_plan",
                "operational_profile",
                "allocations",
                "parallel_waves",
                "migration_policy",
                "gate_requirements",
                "exclusions",
            },
            "payload",
        )
        accepted = _mapping(payload["accepted_base"], "accepted_base")
        _exact_keys(
            accepted,
            {
                "commit",
                "tree",
                "schema_version",
                "schema_fingerprint",
                "last_migration_name",
                "migration_history",
            },
            "accepted_base",
        )
        supersedes = _mapping(payload["supersedes"], "supersedes")
        _exact_keys(
            supersedes,
            {"schema_version", "contract_version", "contract_digest"},
            "supersedes",
        )
        if (
            supersedes["schema_version"] != "newsroom.increment8.readiness.v1"
            or supersedes["contract_version"] != "increment8-readiness-v1"
        ):
            raise Increment8ReadinessError("superseded readiness version differs")
        correction_base = _mapping(payload["correction_base"], "correction_base")
        _exact_keys(
            correction_base,
            {
                "commit",
                "tree",
                "schema_version",
                "schema_fingerprint",
                "migration_history_digest",
            },
            "correction_base",
        )
        corrective_status = _mapping(payload["corrective_status"], "corrective_status")
        raw_allocations = payload["allocations"]
        raw_waves = payload["parallel_waves"]
        if not isinstance(raw_allocations, list) or not isinstance(raw_waves, list):
            raise Increment8ReadinessError("allocations and waves must be arrays")
        waves: dict[int, tuple[int, ...]] = {}
        for index, value in enumerate(raw_waves):
            wave = _mapping(value, f"parallel_waves[{index}]")
            _exact_keys(wave, {"wave", "issues"}, f"parallel_waves[{index}]")
            number = _integer(wave["wave"], f"parallel_waves[{index}].wave")
            if number in waves:
                raise Increment8ReadinessError("duplicate parallel wave")
            waves[number] = _integers(wave["issues"], f"parallel_waves[{index}].issues")
        raw_gates = _mapping(payload["gate_requirements"], "gate_requirements")
        contract = Increment8ReadinessContract(
            schema_version=str(top["schema_version"]),
            contract_id=str(payload["contract_id"]),
            contract_version=str(payload["contract_version"]),
            issue_number=_integer(payload["issue_number"], "issue_number"),
            parent_issue_number=_integer(
                payload["parent_issue_number"], "parent_issue_number"
            ),
            accepted_base_commit=str(accepted["commit"]),
            accepted_base_tree=str(accepted["tree"]),
            accepted_schema_version=_integer(
                accepted["schema_version"], "accepted_base.schema_version"
            ),
            accepted_schema_fingerprint=validate_sha256_digest(
                str(accepted["schema_fingerprint"]), field="schema_fingerprint"
            ),
            accepted_last_migration_name=str(accepted["last_migration_name"]),
            accepted_migration_history=_history(accepted["migration_history"]),
            superseded_contract_digest=validate_sha256_digest(
                str(supersedes["contract_digest"]),
                field="supersedes.contract_digest",
            ),
            correction_base_commit=str(correction_base["commit"]),
            correction_base_tree=str(correction_base["tree"]),
            correction_base_schema_version=_integer(
                correction_base["schema_version"],
                "correction_base.schema_version",
            ),
            correction_base_schema_fingerprint=validate_sha256_digest(
                str(correction_base["schema_fingerprint"]),
                field="correction_base.schema_fingerprint",
            ),
            correction_base_migration_history_digest=validate_sha256_digest(
                str(correction_base["migration_history_digest"]),
                field="correction_base.migration_history_digest",
            ),
            corrective_status=_frozen_mapping(
                corrective_status, "corrective_status"
            ),
            effective_when=str(payload["effective_when"]),
            authority=_frozen_mapping(payload["authority"], "authority"),
            version_manifest=_frozen_mapping(
                payload["version_manifest"], "version_manifest"
            ),
            evaluation_plan=_frozen_mapping(
                payload["evaluation_plan"], "evaluation_plan"
            ),
            operational_profile=_frozen_mapping(
                payload["operational_profile"], "operational_profile"
            ),
            allocations=tuple(
                _allocation(item, index) for index, item in enumerate(raw_allocations)
            ),
            parallel_waves=MappingProxyType(waves),
            migration_policy=_frozen_mapping(
                payload["migration_policy"], "migration_policy"
            ),
            gate_requirements=MappingProxyType(
                {
                    GateTier(name): _strings(value, f"gate_requirements.{name}")
                    for name, value in raw_gates.items()
                }
            ),
            exclusions=_strings(payload["exclusions"], "exclusions"),
            contract_digest=contract_digest,
        )
    except (KeyError, TypeError, ValueError, CanonicalizationError) as exc:
        if isinstance(exc, Increment8ReadinessError):
            raise
        raise Increment8ReadinessError("readiness payload is malformed") from exc
    _validate_contract(contract)
    return contract


INCREMENT_8_READINESS = load_increment8_readiness_contract(READINESS_CONTRACT_PATH)
INCREMENT_8_READINESS_DIGEST = INCREMENT_8_READINESS.contract_digest


def corrective_gate_authorised(gate: CorrectiveGate) -> bool:
    """Return the exact v2 corrective gate without interpreting evidence."""

    if not isinstance(gate, CorrectiveGate):
        raise Increment8ReadinessError("corrective gate identity differs")
    value = INCREMENT_8_READINESS.corrective_status.get(gate.value)
    if not isinstance(value, bool):
        raise Increment8ReadinessError("corrective gate value differs")
    return value
