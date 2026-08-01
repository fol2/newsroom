from __future__ import annotations

from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp

from .contracts import (
    DecisionPacketStatus,
    Increment5AContractBundle,
    Increment5ADecisionPacket,
    Increment5ContractError,
    RetrievalMode,
    RetrievalProfileKind,
    RuntimeAuthority,
)
from .decision_validation import (
    DECISION_PACKET_SCHEMA_VERSION,
    PAYLOAD_KEYS,
    PENDING_DECISION_PAYLOAD_DIGEST,
    parse_budgets,
    parse_canonical_json,
    parse_components,
    require_digest,
    require_exact_keys,
    require_integer,
    require_mapping,
    require_pending_safety_invariants,
    require_string,
    require_string_tuple,
)
from .profiles import (
    PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST,
)


DECISION_PACKET_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_production_retrieval_decision_v1.json"
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

    record = parse_canonical_json(data)
    require_exact_keys(
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
    if require_string(record.get("schema_version"), field="schema_version") != (
        DECISION_PACKET_SCHEMA_VERSION
    ):
        raise Increment5ContractError("decision packet schema version differs")

    payload = require_mapping(record.get("payload"), field="payload")
    require_exact_keys(payload, required=PAYLOAD_KEYS, field="payload")
    payload_digest = digest_bytes(canonical_json_bytes(payload))
    if require_digest(record.get("payload_digest"), field="payload_digest") != (
        payload_digest
    ):
        raise Increment5ContractError(
            "decision payload digest does not match canonical payload bytes"
        )
    if payload_digest != PENDING_DECISION_PAYLOAD_DIGEST:
        raise Increment5ContractError(
            "decision payload differs from the repository-bound pending proposal"
        )

    component_digests = require_mapping(
        record.get("component_digests"),
        field="component_digests",
    )
    identities, configurations = parse_components(
        payload=payload,
        component_digests=component_digests,
    )
    budgets = parse_budgets(payload)

    schemas = require_mapping(
        payload.get("profile_schema_digests"),
        field="profile_schema_digests",
    )
    require_exact_keys(
        schemas,
        required=frozenset({"fixture_replay", "production"}),
        field="profile_schema_digests",
    )
    if (
        schemas.get("production")
        != PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST
    ):
        raise Increment5ContractError(
            "proposal production-profile schema digest differs from repository code"
        )
    if schemas.get("fixture_replay") != PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST:
        raise Increment5ContractError(
            "fixture profile schema digest differs from repository code"
        )

    authority = require_mapping(
        payload.get("authority_boundaries"),
        field="authority_boundaries",
    )
    expected_authority = {
        "candidate_collision_system": "sqlite-authoritative-exact-collision",
        "hydration_system": "sqlite-ledger-and-governed-objects",
        "model_is_authority": False,
        "path_is_authority": False,
        "projection_role": "rebuildable-non-authoritative-context",
        "rank_is_authority": False,
        "similarity_is_authority": False,
    }
    if dict(authority) != expected_authority:
        raise Increment5ContractError(
            "authority boundaries differ from the accepted architecture"
        )

    bundle = Increment5AContractBundle(
        decision_id=require_string(payload.get("decision_id"), field="decision_id"),
        decision_version=require_string(
            payload.get("decision_version"),
            field="decision_version",
        ),
        implementation_base=require_string(
            payload.get("implementation_base"),
            field="implementation_base",
        ),
        production_profile_schema_digest=(
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST
        ),
        fixture_replay_profile_schema_digest=(
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
        ),
        required_modes=tuple(
            RetrievalMode(item)
            for item in require_string_tuple(
                payload.get("required_modes"),
                field="required_modes",
            )
        ),
        named_tools=require_string_tuple(
            payload.get("named_tools"),
            field="named_tools",
        ),
        authoritative_hydration_system=require_string(
            authority.get("hydration_system"),
            field="authority_boundaries.hydration_system",
        ),
        candidate_collision_system=require_string(
            authority.get("candidate_collision_system"),
            field="authority_boundaries.candidate_collision_system",
        ),
        components=identities,
    )

    try:
        status = DecisionPacketStatus(
            require_string(payload.get("decision_status"), field="decision_status")
        )
        runtime_authority = RuntimeAuthority(
            require_string(
                payload.get("runtime_authority"),
                field="runtime_authority",
            )
        )
        approved_profiles = tuple(
            RetrievalProfileKind(item)
            for item in require_string_tuple(
                payload.get("approved_profiles"),
                field="approved_profiles",
            )
        )
        blocked_profiles = tuple(
            RetrievalProfileKind(item)
            for item in require_string_tuple(
                payload.get("blocked_profiles"),
                field="blocked_profiles",
            )
        )
    except ValueError as exc:
        raise Increment5ContractError(
            "decision status, authority or profile kind is unknown"
        ) from exc

    packet = Increment5ADecisionPacket(
        schema_version=DECISION_PACKET_SCHEMA_VERSION,
        status=status,
        owner=require_string(payload.get("owner"), field="owner"),
        prepared_at=UtcTimestamp.parse(
            require_string(payload.get("prepared_at"), field="prepared_at")
        ),
        issue_number=require_integer(
            payload.get("issue_number"),
            field="issue_number",
        ),
        parent_issue_number=require_integer(
            payload.get("parent_issue_number"),
            field="parent_issue_number",
        ),
        programme_issue_number=require_integer(
            payload.get("programme_issue_number"),
            field="programme_issue_number",
        ),
        runtime_authority=runtime_authority,
        approved_profiles=approved_profiles,
        blocked_profiles=blocked_profiles,
        unresolved_decisions=require_string_tuple(
            payload.get("unresolved_decisions"),
            field="unresolved_decisions",
        ),
        budgets=budgets,
        payload_digest=payload_digest,
        record_digest=digest_bytes(data),
        bundle=bundle,
    )
    require_pending_safety_invariants(
        payload=payload,
        configurations=configurations,
    )
    return packet


INCREMENT_5A_DECISION_PACKET = load_increment5a_decision_packet()
