from __future__ import annotations

import json
from typing import Any, Mapping

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

from .contracts import (
    ComponentDisposition,
    Increment5ContractError,
    RetrievalBudgetContract,
    RetrievalComponentKind,
    component_identity,
)


DECISION_PACKET_SCHEMA_VERSION = "increment5a-decision-packet-v1"
PENDING_DECISION_PAYLOAD_DIGEST = (
    "sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56"
)

PAYLOAD_KEYS = frozenset(
    {
        "approved_profiles",
        "authority_boundaries",
        "blocked_profiles",
        "budgets",
        "components",
        "decision_id",
        "decision_status",
        "decision_version",
        "evaluation_plan",
        "implementation_base",
        "issue_number",
        "named_tools",
        "owner",
        "parent_issue_number",
        "pr_boundaries",
        "prepared_at",
        "profile_schema_digests",
        "programme_issue_number",
        "required_modes",
        "rights_matrix",
        "rollback",
        "runtime_authority",
        "unresolved_decisions",
    }
)
COMPONENT_KEYS = frozenset(
    {
        "kind",
        "contract_id",
        "contract_version",
        "implementation_version",
        "disposition",
        "compatibility_rule",
        "change_requires",
        "configuration",
    }
)
BUDGET_KEYS = frozenset(
    {
        "timeout_ms",
        "branch_result_limit",
        "retained_candidate_limit",
        "response_byte_limit",
        "max_external_calls_per_request",
        "max_gross_cost_microunits_per_request",
    }
)


def object_without_duplicate_names(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise Increment5ContractError(
                f"decision packet contains duplicate object name: {key}"
            )
        value[key] = item
    return value


def parse_canonical_json(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise Increment5ContractError("decision packet bytes are required")
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            "decision packet is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError("decision packet root must be an object")
    if data != canonical_json_bytes(value):
        raise Increment5ContractError(
            "decision packet must be stored as exact canonical JSON bytes"
        )
    return value


def require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    field: str,
) -> None:
    actual = frozenset(value)
    if actual != required:
        raise Increment5ContractError(
            f"{field} keys differ; "
            f"missing={sorted(required - actual)!r}, "
            f"extra={sorted(actual - required)!r}"
        )


def require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    return value


def require_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise Increment5ContractError(f"{field} must be an array")
    return value


def require_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise Increment5ContractError(f"{field} must be a string")
    return value


def require_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Increment5ContractError(f"{field} must be an integer")
    return value


def require_digest(value: Any, *, field: str) -> str:
    candidate = require_string(value, field=field)
    try:
        validate_sha256_digest(candidate, field=field)
    except ValueError as exc:
        raise Increment5ContractError(f"{field} must be a canonical digest") from exc
    return candidate


def require_string_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    return tuple(
        require_string(item, field=f"{field}[{index}]")
        for index, item in enumerate(require_list(value, field=field))
    )


def parse_components(
    *,
    payload: Mapping[str, Any],
    component_digests: Mapping[str, Any],
) -> tuple[tuple[object, ...], dict[RetrievalComponentKind, Mapping[str, Any]]]:
    expected_kinds = tuple(RetrievalComponentKind)
    if frozenset(component_digests) != frozenset(
        item.value for item in expected_kinds
    ):
        raise Increment5ContractError(
            "component digest inventory differs from the typed components"
        )

    identities: list[object] = []
    configurations: dict[RetrievalComponentKind, Mapping[str, Any]] = {}
    actual_kinds: list[RetrievalComponentKind] = []
    for index, raw_component in enumerate(
        require_list(payload.get("components"), field="components")
    ):
        component = require_mapping(raw_component, field=f"components[{index}]")
        require_exact_keys(
            component,
            required=COMPONENT_KEYS,
            field=f"components[{index}]",
        )
        raw_kind = require_string(
            component.get("kind"),
            field=f"components[{index}].kind",
        )
        try:
            kind = RetrievalComponentKind(raw_kind)
        except ValueError as exc:
            raise Increment5ContractError(
                f"unknown retrieval component kind: {raw_kind}"
            ) from exc
        if kind in configurations:
            raise Increment5ContractError(f"duplicate component kind: {kind.value}")
        actual_kinds.append(kind)

        configuration = require_mapping(
            component.get("configuration"),
            field=f"{kind.value}.configuration",
        )
        expected_digest = digest_bytes(canonical_json_bytes(component))
        if require_digest(
            component_digests.get(kind.value),
            field=f"component_digests.{kind.value}",
        ) != expected_digest:
            raise Increment5ContractError(
                f"{kind.value} component digest does not match canonical bytes"
            )
        try:
            disposition = ComponentDisposition(
                require_string(
                    component.get("disposition"),
                    field=f"{kind.value}.disposition",
                )
            )
        except ValueError as exc:
            raise Increment5ContractError(
                f"unknown {kind.value} component disposition"
            ) from exc

        identities.append(
            component_identity(
                kind=kind,
                contract_id=require_string(
                    component.get("contract_id"),
                    field=f"{kind.value}.contract_id",
                ),
                contract_version=require_string(
                    component.get("contract_version"),
                    field=f"{kind.value}.contract_version",
                ),
                implementation_version=require_string(
                    component.get("implementation_version"),
                    field=f"{kind.value}.implementation_version",
                ),
                disposition=disposition,
                configuration_digest=expected_digest,
                compatibility_rule=require_string(
                    component.get("compatibility_rule"),
                    field=f"{kind.value}.compatibility_rule",
                ),
                change_requires=require_string_tuple(
                    component.get("change_requires"),
                    field=f"{kind.value}.change_requires",
                ),
            )
        )
        configurations[kind] = configuration

    if tuple(actual_kinds) != expected_kinds:
        raise Increment5ContractError(
            "component order differs from the canonical typed inventory"
        )
    return tuple(identities), configurations


def parse_budgets(payload: Mapping[str, Any]) -> RetrievalBudgetContract:
    raw = require_mapping(payload.get("budgets"), field="budgets")
    require_exact_keys(raw, required=BUDGET_KEYS, field="budgets")
    return RetrievalBudgetContract(
        timeout_ms=require_integer(raw.get("timeout_ms"), field="timeout_ms"),
        branch_result_limit=require_integer(
            raw.get("branch_result_limit"),
            field="branch_result_limit",
        ),
        retained_candidate_limit=require_integer(
            raw.get("retained_candidate_limit"),
            field="retained_candidate_limit",
        ),
        response_byte_limit=require_integer(
            raw.get("response_byte_limit"),
            field="response_byte_limit",
        ),
        max_external_calls_per_request=require_integer(
            raw.get("max_external_calls_per_request"),
            field="max_external_calls_per_request",
        ),
        max_gross_cost_microunits_per_request=require_integer(
            raw.get("max_gross_cost_microunits_per_request"),
            field="max_gross_cost_microunits_per_request",
        ),
    )


def require_pending_safety_invariants(
    *,
    payload: Mapping[str, Any],
    configurations: Mapping[RetrievalComponentKind, Mapping[str, Any]],
) -> None:
    embedding = configurations[RetrievalComponentKind.EMBEDDING]
    required_embedding = {
        "provider_kind": "SELF_HOSTED_LOCAL_MODEL",
        "provider": "sentence-transformers",
        "provider_version": "5.6.0",
        "model_id": "BAAI/bge-m3",
        "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
        "destination": "LOCAL_PROCESS_ONLY",
        "execution_mode": "DISABLED_PENDING_OWNER_DECISION",
        "dimensions": 1024,
        "maximum_input_tokens": 8192,
        "pooling": "CLS",
        "normalize_embeddings": True,
        "model_download_at_request_time": False,
        "remote_code_allowed": False,
        "max_external_calls_per_request": 0,
        "max_gross_cost_microunits_per_request": 0,
        "protected_content_authorized": False,
        "credential_reference": "NONE",
    }
    for field, expected in required_embedding.items():
        actual = embedding.get(field)
        if type(actual) is not type(expected) or actual != expected:
            raise Increment5ContractError(
                f"embedding.{field} differs from the digest-bound pending proposal"
            )

    vector = configurations[RetrievalComponentKind.VECTOR_INDEX]
    if (
        vector.get("dimensions") != 1024
        or vector.get("index_creation_allowed") is not False
    ):
        raise Increment5ContractError(
            "vector index must remain dimension-bound and disabled pending approval"
        )

    evaluation = require_mapping(
        payload.get("evaluation_plan"),
        field="evaluation_plan",
    )
    if evaluation.get("production_vector_qualification_blocked") is not True:
        raise Increment5ContractError(
            "pending decision must block production vector qualification"
        )

    rights_rows = require_list(payload.get("rights_matrix"), field="rights_matrix")
    rights_by_class: dict[str, Mapping[str, Any]] = {}
    for index, raw_row in enumerate(rights_rows):
        row = require_mapping(raw_row, field=f"rights_matrix[{index}]")
        data_class = require_string(
            row.get("data_class"),
            field=f"rights_matrix[{index}].data_class",
        )
        if data_class in rights_by_class:
            raise Increment5ContractError(f"duplicate rights data class: {data_class}")
        rights_by_class[data_class] = row
    if rights_by_class.get("PERSONAL_DATA", {}).get("vector_index") != "PROHIBITED":
        raise Increment5ContractError("personal data vectors must remain prohibited")
    if (
        rights_by_class.get("RIGHTS_RESTRICTED_SOURCE_TEXT", {}).get("vector_index")
        != "PROHIBITED_IN_INCREMENT_5_V1"
    ):
        raise Increment5ContractError(
            "rights-restricted vectors must remain prohibited in Increment 5 v1"
        )
    if (
        rights_by_class.get("REPOSITORY_FIXTURE_TEXT", {}).get(
            "production_qualification"
        )
        != "PROHIBITED"
    ):
        raise Increment5ContractError(
            "fixture replay cannot become production qualification"
        )
