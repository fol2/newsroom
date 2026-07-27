from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from newsroom.authority import PayloadMode, TrustScope, canonical_json_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    SCHEMA_VERSION,
)
from newsroom.authority.complete_projection_migrations import (
    COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
    COMPLETE_PROJECTION_MIGRATION_NAME,
    COMPLETE_PROJECTION_SCHEMA_VERSION,
)
from newsroom.authority.relation_migrations import (
    RELATION_MIGRATION_CHECKSUM,
    RELATION_MIGRATION_NAME,
    RELATION_SCHEMA_VERSION,
)
from newsroom.relations import (
    INTEGRATED_FIXTURE_V2,
    INTEGRATED_FIXTURE_V2_DIGEST,
    IntegratedFixtureV2BindingId,
    RelationContractError,
    RelationEndpoint,
    RelationPredicate,
    RelationProducer,
    RelationProducerKind,
    RelationProposalId,
    RelationProposalRequest,
    RelationReadPolicy,
    RelationRecordType,
    RelationTemporalScope,
    relation_command_definitions,
    relation_payload_contracts,
)

from .relation_2a_helpers import BINDING_ID, PROPOSAL_ID, RELATION_NOW


def test_fixture_is_checked_canonical_bilingual_repository_owned_data() -> None:
    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "integrated_fixture_v2.json"
    )
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert INTEGRATED_FIXTURE_V2.canonical_bytes == canonical_json_bytes(raw)
    assert INTEGRATED_FIXTURE_V2.manifest_digest == INTEGRATED_FIXTURE_V2_DIGEST
    assert INTEGRATED_FIXTURE_V2.schema_version == "integrated_fixture_v2"
    assert {language for language, _ in INTEGRATED_FIXTURE_V2.aliases} == {
        "en-GB",
        "zh-HK",
    }
    assert raw["rights"] == {
        "basis": "repository_owned_synthetic",
        "contains_personal_data": False,
        "contains_copied_news_expression": False,
        "allowed_use": "project.discovery",
    }
    assert any(item.language == "zh-HK" for item in INTEGRATED_FIXTURE_V2.passages)
    assert any(item.language == "en-GB" for item in INTEGRATED_FIXTURE_V2.passages)
    assert INTEGRATED_FIXTURE_V2.tombstoned_negative_passage_id == (
        "ifv2-tombstoned-negative"
    )


def test_fixture_relation_is_exact_governed_development_contract() -> None:
    relation = INTEGRATED_FIXTURE_V2.relation

    assert relation.predicate is RelationPredicate.DEVELOPMENT_OF
    assert relation.subject.record_type is RelationRecordType.EVENT_HYPOTHESIS_VERSION
    assert relation.object.record_type is RelationRecordType.EVENT_HYPOTHESIS_VERSION
    assert relation.subject != relation.object
    assert relation.producer.kind is RelationProducerKind.DETERMINISTIC_RULE
    assert relation.producer.producer_id == "newsroom.integrated_fixture_v2"
    assert relation.evidence_passage_ids == tuple(
        sorted(relation.evidence_passage_ids)
    )
    assert INTEGRATED_FIXTURE_V2.distractor_predicate is RelationPredicate.SAME_EVENT_AS


def test_relation_predicate_vocabulary_is_closed_and_typed() -> None:
    assert {item.value for item in RelationPredicate} == {
        "SAME_EVENT_AS",
        "DEVELOPMENT_OF",
        "SAME_PROCESS_AS",
        "CORRECTS",
        "SUPERSEDES",
        "SUPPORTS",
        "DISPUTES",
        "CONTRADICTS",
        "ABOUT_EVENT",
    }
    with pytest.raises(ValueError):
        RelationPredicate("CALLER_SELECTED")


def test_typed_records_are_frozen_and_canonical() -> None:
    request = INTEGRATED_FIXTURE_V2.relation.request(
        proposal_id=PROPOSAL_ID,
        fixture_binding_id=BINDING_ID,
        idempotency_key="fixture-proposal",
    )

    assert request.canonical_bytes == canonical_json_bytes(request.canonical_value())
    assert request.proposal_digest.startswith("sha256:")
    assert request.semantic_identity_digest.startswith("sha256:")
    assert request.semantic_slot_digest.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        request.statement = "mutated"  # type: ignore[misc]


def test_relation_request_rejects_unsorted_evidence_and_uncertainty() -> None:
    template = INTEGRATED_FIXTURE_V2.relation
    with pytest.raises(RelationContractError, match="sorted and unique"):
        RelationProposalRequest(
            proposal_id=RelationProposalId.new(),
            fixture_binding_id=IntegratedFixtureV2BindingId.new(),
            subject=template.subject,
            predicate=template.predicate,
            object=template.object,
            temporal_scope=template.temporal_scope,
            evidence_passage_ids=("z", "a"),
            producer=template.producer,
            statement=template.statement,
            uncertainties=template.uncertainties,
            idempotency_key="unsorted-evidence",
        )


def test_relation_endpoint_and_temporal_contract_are_bounded() -> None:
    with pytest.raises(Exception):
        RelationEndpoint(RelationRecordType.SOURCE_REVISION, "not-a-uuid")
    with pytest.raises(RelationContractError, match="follow"):
        RelationTemporalScope(RELATION_NOW, RELATION_NOW)
    with pytest.raises(RelationContractError, match="exact"):
        RelationTemporalScope(RELATION_NOW, None, "DATE_ONLY")
    with pytest.raises(Exception):
        RelationProducer(
            RelationProducerKind.DETERMINISTIC_RULE,
            "invalid producer id with spaces",
            "v1",
            "rule-v1",
        )


def test_payload_contracts_and_commands_are_separate_authority_scopes() -> None:
    contracts = relation_payload_contracts()
    definitions = relation_command_definitions()

    assert len(contracts) == 3
    assert {item.payload_mode for item in contracts} == {PayloadMode.INLINE}
    assert {item.trust_scope for item in definitions} == {
        TrustScope.OBSERVED,
        TrustScope.PROPOSED,
        TrustScope.ADMITTED,
    }
    assert {item.required_scope for item in definitions} == {
        "authority.fixture.v2.bind",
        "authority.relation.propose",
        "authority.relation.admit",
    }
    assert all(item.security_scope == "authority.relation" for item in definitions)


def test_relation_payload_contract_rejects_extra_fields_and_arbitrary_predicate() -> None:
    proposal_contract = next(
        item
        for item in relation_payload_contracts()
        if item.schema_version == "governed_relation_proposal_v1"
    )
    value = INTEGRATED_FIXTURE_V2.relation.request(
        proposal_id=PROPOSAL_ID,
        fixture_binding_id=BINDING_ID,
        idempotency_key="fixture-proposal",
    ).canonical_value()

    invalid = dict(value)
    invalid["predicate"] = "CALLER_SELECTED"
    with pytest.raises(Exception, match="allow-listed"):
        proposal_contract.canonicalize(invalid)

    extra = dict(value)
    extra["cypher"] = "MATCH (n) DELETE n"
    with pytest.raises(Exception, match="fields differ"):
        proposal_contract.canonicalize(extra)


def test_relation_read_policy_is_server_owned_bounded_authority() -> None:
    policy = RelationReadPolicy(
        policy_id="relation-reader-v1",
        purpose="relation.projector",
        metadata_required_scope="authority.relation.metadata.read",
        projection_required_scope="authority.relation.project",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=32,
    )

    policy.require_principal("principal.alpha")
    policy.require_limit(32)
    assert policy.digest.startswith("sha256:")
    with pytest.raises(PermissionError):
        policy.require_principal("principal.beta")
    with pytest.raises(PermissionError):
        policy.require_limit(33)
    with pytest.raises(RelationContractError, match="distinct scopes"):
        RelationReadPolicy(
            policy_id="invalid-relation-reader-v1",
            purpose="relation.projector",
            metadata_required_scope="authority.relation.read",
            projection_required_scope="authority.relation.read",
            allowed_principal_ids=frozenset({"principal.alpha"}),
            max_results=32,
        )


def test_relation_migration_remains_checked_version_six_before_complete_v7() -> None:
    assert RELATION_SCHEMA_VERSION == 6
    assert COMPLETE_PROJECTION_SCHEMA_VERSION == 7
    assert SCHEMA_VERSION >= COMPLETE_PROJECTION_SCHEMA_VERSION
    assert (
        6,
        RELATION_MIGRATION_NAME,
        RELATION_MIGRATION_CHECKSUM,
    ) in EXPECTED_MIGRATION_HISTORY
    assert (
        7,
        COMPLETE_PROJECTION_MIGRATION_NAME,
        COMPLETE_PROJECTION_MIGRATION_CHECKSUM,
    ) in EXPECTED_MIGRATION_HISTORY
