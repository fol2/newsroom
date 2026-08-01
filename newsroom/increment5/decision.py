from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp

from .contracts import (
    ComponentDisposition,
    DecisionPacketStatus,
    Increment5AContractBundle,
    Increment5ADecisionPacket,
    Increment5ContractError,
    RetrievalBudgetContract,
    RetrievalComponentKind,
    RetrievalMode,
    RetrievalProfileKind,
    RuntimeAuthority,
    component_identity,
)
from .profiles import (
    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    PRODUCTION_PROFILE_SCHEMA_DIGEST,
)


DECISION_PACKET_SCHEMA_VERSION = "increment5a-decision-packet-v1"
DECISION_PACKET_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_production_retrieval_decision_v1.json"
)


def _object_without_duplicate_names(
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


def _parse_canonical_json(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise Increment5ContractError("decision packet bytes are required")
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_names,
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


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    field: str,
) -> None:
    actual = frozenset(value)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise Increment5ContractError(
            f"{field} keys differ; missing={missing!r}, extra={extra!r}"
        )


def _require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    return value


def _require_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise Increment5ContractError(f"{field} must be an array")
    return value


def _require_exact_value(
    value: Mapping[str, Any],
    *,
    field: str,
    expected: Any,
) -> None:
    if value.get(field) != expected:
        raise Increment5ContractError(
            f"{field} differs from the exact Increment 5A decision"
        )


def _component_configuration(
    components: Mapping[RetrievalComponentKind, Mapping[str, Any]],
    kind: RetrievalComponentKind,
) -> Mapping[str, Any]:
    component = components[kind]
    return _require_mapping(
        component.get("configuration"),
        field=f"{kind.value}.configuration",
    )


def _validate_component_semantics(
    components: Mapping[RetrievalComponentKind, Mapping[str, Any]],
) -> None:
    embedding = _component_configuration(
        components,
        RetrievalComponentKind.EMBEDDING,
    )
    for field, expected in {
        "provider_kind": "UNSET",
        "provider": "UNSET",
        "model_id": "UNSET",
        "model_release": "UNSET",
        "destination": "NONE",
        "execution_mode": "DISABLED",
        "dimensions": 0,
        "output_data_type": "UNSET",
        "max_external_calls_per_request": 0,
        "max_gross_cost_microunits_per_request": 0,
        "protected_content_authorized": False,
        "credential_reference": "NONE",
    }.items():
        _require_exact_value(embedding, field=field, expected=expected)

    passage = _component_configuration(
        components,
        RetrievalComponentKind.PASSAGE,
    )
    for field, expected in {
        "offset_unit": "UTF8_BYTE",
        "target_bytes": 3072,
        "maximum_bytes": 4096,
        "maximum_overlap_bytes": 384,
        "cross_representation_allowed": False,
        "cross_revision_allowed": False,
        "authoritative_bytes_mutated": False,
        "identity_contract": (
            "representation-id-digest-start-end-chunker-normalizer"
        ),
    }.items():
        _require_exact_value(passage, field=field, expected=expected)
    if passage.get("boundary_precedence") != [
        "PARAGRAPH",
        "SENTENCE",
        "SAFE_UTF8",
    ]:
        raise Increment5ContractError(
            "passage boundary precedence differs from the exact decision"
        )

    normalization = _component_configuration(
        components,
        RetrievalComponentKind.NORMALIZATION,
    )
    for field, expected in {
        "index_unicode_normalization": "NFKC",
        "line_endings": "LF",
        "latin_casefold": True,
        "collapse_whitespace": True,
        "han_script_conversion": "NONE",
        "free_transliteration": False,
        "authority_aliases_only": True,
        "han_ngram_size": 2,
        "surface_bytes_retained": True,
    }.items():
        _require_exact_value(normalization, field=field, expected=expected)
    if normalization.get("language_modes") != [
        "EN_GB",
        "ZH_HANT_HK",
        "MIXED_EN_GB_ZH_HANT_HK",
    ]:
        raise Increment5ContractError(
            "bilingual normalization modes differ from the exact decision"
        )

    fulltext = _component_configuration(
        components,
        RetrievalComponentKind.FULL_TEXT_INDEX,
    )
    for field, expected in {
        "engine_image": "neo4j:2026.06.0-community-trixie",
        "driver_version": "6.2.0",
        "provider": "fulltext-2.0",
        "analyzer": "standard-no-stop-words",
        "eventually_consistent": False,
        "generation_scoped": True,
        "caller_lucene_syntax_allowed": False,
    }.items():
        _require_exact_value(fulltext, field=field, expected=expected)
    if fulltext.get("indexed_fields") != [
        "authority_aliases",
        "formal_tokens",
        "han_bigrams",
        "latin_terms",
        "retrieval_text",
    ]:
        raise Increment5ContractError(
            "full-text indexed fields differ from the exact decision"
        )

    vector = _component_configuration(
        components,
        RetrievalComponentKind.VECTOR_INDEX,
    )
    for field, expected in {
        "engine_image": "neo4j:2026.06.0-community-trixie",
        "driver_version": "6.2.0",
        "provider": "vector-2026.06",
        "dimensions": 0,
        "output_data_type": "FLOAT32",
        "similarity_function": "COSINE",
        "quantization": "NONE",
        "generation_scoped": True,
        "embedding_contract_required": True,
        "index_creation_allowed": False,
    }.items():
        _require_exact_value(vector, field=field, expected=expected)

    graph = _component_configuration(
        components,
        RetrievalComponentKind.GRAPH_QUERY,
    )
    for field, expected in {
        "engine_image": "neo4j:2026.06.0-community-trixie",
        "driver_version": "6.2.0",
        "maximum_depth": 2,
        "maximum_fanout": 32,
        "date_window_seconds": 2678400,
        "generated_cypher_allowed": False,
        "write_capability_allowed": False,
        "active_complete_generation_required": True,
        "open_gap_count_required": 0,
        "dead_letter_count_required": 0,
    }.items():
        _require_exact_value(graph, field=field, expected=expected)
    if graph.get("allowed_predicates") != [
        "ABOUT_EVENT",
        "CORRECTS",
        "DEVELOPMENT_OF",
        "DISPUTES",
        "SAME_EVENT_AS",
        "SAME_PROCESS_AS",
        "SUPERSEDES",
        "SUPPORTS",
    ]:
        raise Increment5ContractError(
            "graph predicate allow-list differs from the exact decision"
        )
    if graph.get("allowed_trust_scopes") != ["ADMITTED", "OBSERVED"]:
        raise Increment5ContractError(
            "graph trust allow-list differs from the exact decision"
        )

    fusion = _component_configuration(
        components,
        RetrievalComponentKind.FUSION,
    )
    for field, expected in {
        "algorithm": "RECIPROCAL_RANK_FUSION",
        "reciprocal_rank_k": 60,
        "branch_weights": "EQUAL_ONE",
        "score_representation": "REDUCED_RATIONAL",
        "raw_score_comparability_assumed": False,
        "fusion_is_authority": False,
    }.items():
        _require_exact_value(fusion, field=field, expected=expected)
    if fusion.get("required_modes") != [
        "EXACT",
        "FULL_TEXT",
        "VECTOR",
        "ADMITTED_GRAPH",
    ]:
        raise Increment5ContractError(
            "fusion modes differ from the exact decision"
        )

    deduplication = _component_configuration(
        components,
        RetrievalComponentKind.DEDUPLICATION,
    )
    for field, expected in {
        "root": "AUTHORITATIVE_DEPENDENCY_ROOT",
        "best_hit_per_mode": True,
        "merge_branch_receipts": True,
        "retain_exclusion_receipts": True,
        "canonical_tie_break": "DEPENDENCY_ROOT_ID_ASC",
        "candidate_limit_after_deduplication": 12,
        "similarity_does_not_merge_authority": True,
    }.items():
        _require_exact_value(
            deduplication,
            field=field,
            expected=expected,
        )

    hydration = _component_configuration(
        components,
        RetrievalComponentKind.HYDRATION,
    )
    for field, expected in {
        "authority": "sqlite-ledger-and-governed-objects",
        "projection_text_factual_use_allowed": False,
        "rights_recheck_at_read": True,
        "exact_bytes_required": True,
        "immutable_context_required": True,
        "missing_authority_outcome": "INCOMPLETE",
        "rights_denied_outcome": "POLICY_BLOCKED",
        "maximum_context_bytes": 262144,
    }.items():
        _require_exact_value(hydration, field=field, expected=expected)

    degraded = _component_configuration(
        components,
        RetrievalComponentKind.DEGRADED_POLICY,
    )
    for field, expected in {
        "timeout_ms": 5000,
        "branch_result_limit": 8,
        "retained_candidate_limit": 12,
        "maximum_projection_age_seconds": 3600,
        "graph_free_fallback": False,
        "silent_mode_fallback": False,
        "no_match_requires_complete_retrieval": True,
        "exact_fallback_requires_named_route": True,
        "mandatory_reconciliation": True,
        "candidate_collision_check_required": True,
    }.items():
        _require_exact_value(degraded, field=field, expected=expected)
    if degraded.get("explicit_outcomes") != [
        "COMPLETE",
        "DEGRADED",
        "INCOMPLETE",
        "POLICY_BLOCKED",
        "STALE",
        "UNAVAILABLE",
    ]:
        raise Increment5ContractError(
            "degraded outcomes differ from the exact decision"
        )


def _validate_rights_matrix(payload: Mapping[str, Any]) -> None:
    matrix = _require_list(payload.get("rights_matrix"), field="rights_matrix")
    expected_classes = [
        "PERSONAL_DATA",
        "PUBLIC_GOVERNED_SOURCE_TEXT",
        "REPOSITORY_FIXTURE_TEXT",
        "RIGHTS_RESTRICTED_SOURCE_TEXT",
        "SECRETS_AND_CREDENTIALS",
        "TOMBSTONED_OR_REVOKED",
    ]
    classes = [item.get("data_class") for item in matrix if isinstance(item, Mapping)]
    if classes != expected_classes:
        raise Increment5ContractError(
            "rights matrix classes differ from the exact decision"
        )
    by_class = {
        str(item["data_class"]): item
        for item in matrix
        if isinstance(item, Mapping)
    }
    if by_class["REPOSITORY_FIXTURE_TEXT"].get("fixture_replay") != "ALLOWED":
        raise Increment5ContractError("repository fixtures must remain replayable")
    if (
        by_class["REPOSITORY_FIXTURE_TEXT"].get("production_qualification")
        != "PROHIBITED"
    ):
        raise Increment5ContractError(
            "fixture data cannot substitute for production qualification"
        )
    if (
        by_class["RIGHTS_RESTRICTED_SOURCE_TEXT"].get(
            "external_embedding_destination"
        )
        != "PROHIBITED_PENDING_EXPLICIT_DECISION"
    ):
        raise Increment5ContractError(
            "restricted content destination must remain blocked"
        )
    for data_class in ("PERSONAL_DATA", "SECRETS_AND_CREDENTIALS"):
        if by_class[data_class].get("vector_index") != "PROHIBITED":
            raise Increment5ContractError(
                f"{data_class} must not enter the vector index"
            )
    if by_class["TOMBSTONED_OR_REVOKED"].get("required_action") != (
        "PURGE_ALL_DERIVATIVES_AND_PROVE_NON_RESURRECTION"
    ):
        raise Increment5ContractError(
            "tombstoned content must purge every derivative"
        )


def _validate_evaluation_plan(payload: Mapping[str, Any]) -> None:
    plan = _require_mapping(
        payload.get("evaluation_plan"),
        field="evaluation_plan",
    )
    for field, expected in {
        "plan_id": "increment5-retrieval-evaluation-plan-v1",
        "plan_version": "increment5-retrieval-evaluation-v1",
        "calibration_and_qualification_disjoint": True,
        "thresholds_frozen_before_qualification": True,
        "production_vector_qualification_blocked": True,
    }.items():
        _require_exact_value(plan, field=field, expected=expected)
    if set(_require_list(plan.get("ablations"), field="ablations")) != {
        "ADMITTED_GRAPH_ONLY",
        "EXACT_ONLY",
        "FULL_TEXT_ONLY",
        "HYBRID",
        "VECTOR_ONLY",
    }:
        raise Increment5ContractError(
            "evaluation ablation inventory differs from the exact decision"
        )
    slices = _require_list(plan.get("required_slices"), field="required_slices")
    required_slices = {
        "CORRECTION_AND_SUPERSESSION",
        "DISTRACTOR_FALSE_MERGE",
        "EN_GB",
        "LONG_RUNNING_TIMELINE",
        "MIXED_EN_GB_ZH_HANT_HK",
        "RIGHTS_PURGE_AND_REBUILD",
        "SHARED_ORIGIN_DEPENDENCY",
        "TEMPORAL_CUTOFF",
        "ZH_HANT_HK",
    }
    if set(slices) != required_slices:
        raise Increment5ContractError(
            "evaluation required slices differ from the exact decision"
        )
    thresholds = _require_mapping(
        plan.get("thresholds"),
        field="evaluation_plan.thresholds",
    )
    expected_thresholds = {
        "exact_identifier_precision_at_1_ppm": 1_000_000,
        "provenance_completeness_ppm": 1_000_000,
        "trust_label_completeness_ppm": 1_000_000,
        "rights_purge_residual_count": 0,
        "false_no_match_count": 0,
        "scope_escape_count": 0,
        "write_attempt_success_count": 0,
        "aggregate_recall_at_12_min_ppm": 900_000,
        "required_slice_recall_at_12_min_ppm": 800_000,
        "aggregate_mrr_at_12_min_ppm": 750_000,
        "p95_latency_ms_max": 5_000,
    }
    if dict(thresholds) != expected_thresholds:
        raise Increment5ContractError(
            "evaluation thresholds differ from the pre-registered decision"
        )


def _validate_pr_boundaries(payload: Mapping[str, Any]) -> None:
    boundaries = _require_mapping(
        payload.get("pr_boundaries"),
        field="pr_boundaries",
    )
    expected = {
        "5B": {
            "issue": 251,
            "allowed": "TYPED_RETRIEVERS_AND_NON_REAL_VECTOR_SEAM",
            "blocked": "REAL_EMBEDDING_OR_PROTECTED_CONTENT_VECTOR_EXECUTION",
        },
        "5C": {
            "issue": 252,
            "allowed": "BOUNDED_NAMED_READ_ONLY_TOOLS",
            "blocked": "RAW_CYPHER_OR_GENERAL_INDEX_ACCESS",
        },
        "5D": {
            "issue": 253,
            "allowed": "AUTHORITATIVE_HYDRATION_AND_EXPLICIT_DEGRADED_OUTCOMES",
            "blocked": "FALSE_NO_MATCH_OR_UNCHECKED_PROJECTION_TEXT",
        },
        "5E": {
            "issue": 254,
            "allowed": "PRE_REGISTERED_ABLATION_SECURITY_AND_ACTUAL_NEO4J_PROOF",
            "blocked": "PRODUCTION_VECTOR_QUALIFICATION_UNTIL_OWNER_AMENDMENT",
        },
    }
    if dict(boundaries) != expected:
        raise Increment5ContractError(
            "Increment 5 PR boundaries differ from the exact decision"
        )


def _validate_payload_semantics(
    payload: Mapping[str, Any],
    *,
    components: Mapping[RetrievalComponentKind, Mapping[str, Any]],
) -> None:
    _require_exact_value(
        payload,
        field="implementation_base",
        expected="c9e31879421083e82e2538d57087d04e9b454d34",
    )
    if payload.get("required_modes") != [
        "EXACT",
        "FULL_TEXT",
        "VECTOR",
        "ADMITTED_GRAPH",
    ]:
        raise Increment5ContractError(
            "required retrieval modes differ from the exact decision"
        )
    if payload.get("named_tools") != [
        "find_related_event_candidates",
        "get_event_or_process_timeline",
        "find_source_revision_impact",
        "find_shared_origin_dependencies",
        "find_conflicting_relation_candidates",
        "get_candidate_provenance",
    ]:
        raise Increment5ContractError(
            "named retrieval tool inventory differs from the exact decision"
        )
    boundaries = _require_mapping(
        payload.get("authority_boundaries"),
        field="authority_boundaries",
    )
    expected_boundaries = {
        "hydration_system": "sqlite-ledger-and-governed-objects",
        "candidate_collision_system": "sqlite-authoritative-exact-collision",
        "projection_role": "rebuildable-non-authoritative-context",
        "rank_is_authority": False,
        "similarity_is_authority": False,
        "path_is_authority": False,
        "model_is_authority": False,
    }
    if dict(boundaries) != expected_boundaries:
        raise Increment5ContractError(
            "authority boundaries differ from the accepted architecture"
        )
    schema_digests = _require_mapping(
        payload.get("profile_schema_digests"),
        field="profile_schema_digests",
    )
    if dict(schema_digests) != {
        "fixture_replay": FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
        "production": PRODUCTION_PROFILE_SCHEMA_DIGEST,
    }:
        raise Increment5ContractError(
            "profile schema digests differ from repository code"
        )
    _validate_component_semantics(components)
    _validate_rights_matrix(payload)
    _validate_evaluation_plan(payload)
    _validate_pr_boundaries(payload)

    rollback = _require_mapping(payload.get("rollback"), field="rollback")
    expected_rollback = {
        "same_generation_contract_mutation_allowed": False,
        "prior_generation_may_serve_only_if_rights_current": True,
        "rollback_requires_exact_component_digests": True,
        "graph_free_rollback_allowed": False,
        "history_rewrite_allowed": False,
        "disabled_component_derivatives_must_be_purged": True,
    }
    if dict(rollback) != expected_rollback:
        raise Increment5ContractError(
            "rollback contract differs from the exact decision"
        )


def load_increment5a_decision_packet(
    path: Path | None = None,
) -> Increment5ADecisionPacket:
    selected = DECISION_PACKET_PATH if path is None else path
    try:
        data = selected.read_bytes()
    except OSError as exc:
        raise Increment5ContractError(
            f"cannot read Increment 5A decision packet: {selected}"
        ) from exc
    record = _parse_canonical_json(data)
    _require_exact_keys(
        record,
        required=frozenset(
            {
                "schema_version",
                "payload",
                "payload_digest",
                "component_digests",
            }
        ),
        field="decision_record",
    )
    if record["schema_version"] != DECISION_PACKET_SCHEMA_VERSION:
        raise Increment5ContractError("decision packet schema version differs")
    payload = _require_mapping(record["payload"], field="payload")
    payload_digest = digest_bytes(canonical_json_bytes(payload))
    if record["payload_digest"] != payload_digest:
        raise Increment5ContractError(
            "decision payload digest does not match canonical payload bytes"
        )
    component_digests = _require_mapping(
        record["component_digests"],
        field="component_digests",
    )
    component_values = _require_list(
        payload.get("components"),
        field="components",
    )
    if len(component_values) != len(RetrievalComponentKind):
        raise Increment5ContractError(
            "decision packet must contain every component exactly once"
        )

    components: dict[RetrievalComponentKind, Mapping[str, Any]] = {}
    identities = []
    for raw_component in component_values:
        component = _require_mapping(raw_component, field="component")
        _require_exact_keys(
            component,
            required=frozenset(
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
            ),
            field="component",
        )
        try:
            kind = RetrievalComponentKind(str(component["kind"]))
        except ValueError as exc:
            raise Increment5ContractError(
                "decision packet contains an unknown component kind"
            ) from exc
        if kind in components:
            raise Increment5ContractError(
                f"duplicate component kind: {kind.value}"
            )
        components[kind] = component
        expected_digest = digest_bytes(canonical_json_bytes(component))
        if component_digests.get(kind.value) != expected_digest:
            raise Increment5ContractError(
                f"{kind.value} component digest does not match canonical bytes"
            )
        try:
            disposition = ComponentDisposition(str(component["disposition"]))
        except ValueError as exc:
            raise Increment5ContractError(
                f"{kind.value} component disposition is unknown"
            ) from exc
        change_requires = tuple(
            str(item)
            for item in _require_list(
                component["change_requires"],
                field=f"{kind.value}.change_requires",
            )
        )
        identities.append(
            component_identity(
                kind=kind,
                contract_id=str(component["contract_id"]),
                contract_version=str(component["contract_version"]),
                implementation_version=str(component["implementation_version"]),
                disposition=disposition,
                configuration_digest=expected_digest,
                compatibility_rule=str(component["compatibility_rule"]),
                change_requires=change_requires,
            )
        )

    if tuple(components) != tuple(RetrievalComponentKind):
        raise Increment5ContractError(
            "component order must match the canonical typed inventory"
        )
    if frozenset(component_digests) != frozenset(
        item.value for item in RetrievalComponentKind
    ):
        raise Increment5ContractError(
            "component digest inventory differs from the typed components"
        )

    _validate_payload_semantics(payload, components=components)

    budget_values = _require_mapping(payload.get("budgets"), field="budgets")
    budget = RetrievalBudgetContract(
        timeout_ms=int(budget_values["timeout_ms"]),
        branch_result_limit=int(budget_values["branch_result_limit"]),
        retained_candidate_limit=int(
            budget_values["retained_candidate_limit"]
        ),
        response_byte_limit=int(budget_values["response_byte_limit"]),
        max_external_calls_per_request=int(
            budget_values["max_external_calls_per_request"]
        ),
        max_gross_cost_microunits_per_request=int(
            budget_values["max_gross_cost_microunits_per_request"]
        ),
    )

    schema_digests = _require_mapping(
        payload["profile_schema_digests"],
        field="profile_schema_digests",
    )
    authority = _require_mapping(
        payload["authority_boundaries"],
        field="authority_boundaries",
    )
    bundle = Increment5AContractBundle(
        decision_id=str(payload["decision_id"]),
        decision_version=str(payload["decision_version"]),
        implementation_base=str(payload["implementation_base"]),
        production_profile_schema_digest=str(schema_digests["production"]),
        fixture_replay_profile_schema_digest=str(
            schema_digests["fixture_replay"]
        ),
        required_modes=tuple(
            RetrievalMode(str(item))
            for item in _require_list(
                payload["required_modes"],
                field="required_modes",
            )
        ),
        named_tools=tuple(
            str(item)
            for item in _require_list(
                payload["named_tools"],
                field="named_tools",
            )
        ),
        authoritative_hydration_system=str(authority["hydration_system"]),
        candidate_collision_system=str(authority["candidate_collision_system"]),
        components=tuple(identities),
    )

    try:
        status = DecisionPacketStatus(str(payload["decision_status"]))
        runtime_authority = RuntimeAuthority(str(payload["runtime_authority"]))
    except ValueError as exc:
        raise Increment5ContractError(
            "decision status or runtime authority is unknown"
        ) from exc
    packet = Increment5ADecisionPacket(
        schema_version=DECISION_PACKET_SCHEMA_VERSION,
        status=status,
        owner=str(payload["owner"]),
        prepared_at=UtcTimestamp.parse(str(payload["prepared_at"])),
        issue_number=int(payload["issue_number"]),
        parent_issue_number=int(payload["parent_issue_number"]),
        programme_issue_number=int(payload["programme_issue_number"]),
        runtime_authority=runtime_authority,
        approved_profiles=tuple(
            RetrievalProfileKind(str(item))
            for item in _require_list(
                payload["approved_profiles"],
                field="approved_profiles",
            )
        ),
        blocked_profiles=tuple(
            RetrievalProfileKind(str(item))
            for item in _require_list(
                payload["blocked_profiles"],
                field="blocked_profiles",
            )
        ),
        unresolved_decisions=tuple(
            str(item)
            for item in _require_list(
                payload["unresolved_decisions"],
                field="unresolved_decisions",
            )
        ),
        budgets=budget,
        payload_digest=payload_digest,
        record_digest=digest_bytes(data),
        bundle=bundle,
    )
    return packet


INCREMENT_5A_DECISION_PACKET = load_increment5a_decision_packet()
