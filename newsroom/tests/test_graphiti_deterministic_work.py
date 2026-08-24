from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.graphiti_adapter.deterministic_contract import (
    DeterministicWorkContractError,
)
from newsroom.graphiti_adapter.deterministic_sidecar import (
    AuthorityRecordRef,
    DeterministicSidecarInput,
    RelationTriple,
    SemanticRelationProposal,
    SidecarRelationKind,
    collapse_sidecar_duplicates,
    project_deterministic_sidecar,
)
from newsroom.graphiti_adapter.deterministic_summary import (
    AdmittedSummaryAssertion,
    DeterministicSummaryOutcome,
    build_deterministic_summary,
)
from newsroom.graphiti_adapter.deterministic_work_fixtures import (
    DETERMINISTIC_WORK_MEASUREMENTS_PATH,
    run_provider_free_qualification,
)
from newsroom.graphiti_adapter.local_entity_resolution import (
    CanonicalEntityCandidate,
    EntityMentionInput,
    LocalEntityResolutionBasis,
    LocalEntityResolutionOutcome,
    LocalEntityResolutionPolicy,
    resolve_entity_locally,
)
from newsroom.graphiti_adapter.token_effectiveness import (
    ConditionalLeafProfile,
    ConditionalLeafTokenRanges,
    EffectiveRevisionTokenCase,
    EffectiveRevisionTokenOutcome,
    TokenEstimateRange,
    build_token_effectiveness_report,
)


def _authority(
    record_id: str,
    *,
    record_kind: str = "ADMISSION_DECISION",
    **record_fields: object,
) -> AuthorityRecordRef:
    canonical_bytes = canonical_json_bytes(
        {
            "record_id": record_id,
            "record_kind": record_kind,
            **record_fields,
        }
    )
    return AuthorityRecordRef(
        record_id=record_id,
        canonical_bytes=canonical_bytes,
        canonical_digest=digest_bytes(canonical_bytes),
    )


def _sidecar_input() -> DeterministicSidecarInput:
    source_definition_id = "source-definition:hk-legco"
    source_item_id = "source-item:written-answer-42"
    source_revision_id = "source-revision:written-answer-42:r2"
    predecessor_revision_id = "source-revision:written-answer-42:r1"
    representation_id = "representation:written-answer-42:r2"
    evidence_package_id = "evidence-package:written-answer-42:r2"
    rights_decision_id = "rights-decision:written-answer-42:r2"
    chunk_id = "source-chunk:written-answer-42:r2:2"
    predecessor_chunk_id = "source-chunk:written-answer-42:r2:1"
    reference_time = "2026-08-20T00:00:00Z"
    return DeterministicSidecarInput(
        source_definition=_authority(
            source_definition_id,
            record_kind="SOURCE_DEFINITION",
        ),
        source_item=_authority(
            source_item_id,
            record_kind="SOURCE_ITEM",
            source_definition_id=source_definition_id,
        ),
        source_revision=_authority(
            source_revision_id,
            record_kind="SOURCE_REVISION",
            source_item_id=source_item_id,
            predecessor_revision_id=predecessor_revision_id,
            representation_id=representation_id,
            evidence_package_id=evidence_package_id,
            rights_decision_id=rights_decision_id,
            chunk_id=chunk_id,
            reference_time=reference_time,
        ),
        predecessor_revision=_authority(
            predecessor_revision_id,
            record_kind="SOURCE_REVISION",
        ),
        discovery_representation=_authority(
            representation_id,
            record_kind="DISCOVERY_REPRESENTATION",
            source_revision_id=source_revision_id,
            evidence_package_id=evidence_package_id,
        ),
        evidence_package=_authority(
            evidence_package_id,
            record_kind="EVIDENCE_PACKAGE",
            source_revision_id=source_revision_id,
        ),
        rights_decision=_authority(
            rights_decision_id,
            record_kind="RIGHTS_DECISION",
            source_revision_id=source_revision_id,
        ),
        chunk=_authority(
            chunk_id,
            record_kind="SOURCE_CHUNK",
            source_revision_id=source_revision_id,
            chunk_ordinal=2,
            predecessor_chunk_id=predecessor_chunk_id,
        ),
        predecessor_chunk=_authority(
            predecessor_chunk_id,
            record_kind="SOURCE_CHUNK",
        ),
        reference_time=reference_time,
        chunk_ordinal=2,
    )


def test_governed_records_project_exact_lineage_without_model_work() -> None:
    projected = project_deterministic_sidecar(_sidecar_input())

    assert [proposal.kind for proposal in projected.relation_proposals] == [
        SidecarRelationKind.SOURCE_ITEM_LINEAGE,
        SidecarRelationKind.SOURCE_REGISTRY_LINEAGE,
        SidecarRelationKind.REVISION_PREDECESSOR,
        SidecarRelationKind.ORDERED_CHUNK,
        SidecarRelationKind.REFERENCE_TIME,
        SidecarRelationKind.RIGHTS_IDENTITY,
        SidecarRelationKind.REPRESENTATION_LINEAGE,
        SidecarRelationKind.EVIDENCE_PACKAGE_LINEAGE,
    ]
    assert projected.model_leaf_count == 0
    assert projected.authority == "SQLITE_GOVERNED_RECORDS"
    assert projected.proposal_only is True
    assert all(
        proposal.authority_bindings
        for proposal in projected.relation_proposals
    )
    assert all(
        binding.canonical_digest.startswith("sha256:")
        for proposal in projected.relation_proposals
        for binding in proposal.authority_bindings
    )
    assert all(
        digest_bytes(binding.canonical_bytes) == binding.canonical_digest
        for proposal in projected.relation_proposals
        for binding in proposal.authority_bindings
    )
    chunk_proposal = projected.relation_proposals[3]
    assert [binding.record_id for binding in chunk_proposal.authority_bindings] == [
        "source-chunk:written-answer-42:r2:2",
        "source-chunk:written-answer-42:r2:1",
    ]
    assert projected.semantic_output_bytes_avoided == 0
    assert projected.semantic_prompt_bytes_removed == 0


def test_reference_time_must_be_proved_by_bound_revision_authority() -> None:
    authority = _sidecar_input()

    try:
        DeterministicSidecarInput(
            source_definition=authority.source_definition,
            source_item=authority.source_item,
            source_revision=authority.source_revision,
            predecessor_revision=authority.predecessor_revision,
            discovery_representation=authority.discovery_representation,
            evidence_package=authority.evidence_package,
            rights_decision=authority.rights_decision,
            chunk=authority.chunk,
            predecessor_chunk=authority.predecessor_chunk,
            reference_time="2026-08-21T00:00:00Z",
            chunk_ordinal=authority.chunk_ordinal,
        )
    except ValueError as exc:
        assert "reference_time" in str(exc)
    else:
        raise AssertionError("unproved reference_time was accepted")


def test_same_semantic_relation_proposal_collapses_without_losing_attribution() -> None:
    sidecar = project_deterministic_sidecar(_sidecar_input())
    known = sidecar.relation_proposals[0]
    duplicate = SemanticRelationProposal(
        proposal_id="semantic-proposal:1",
        relation=known.relation,
        evidence_segment_ids=(4, 9),
    )
    distinct = SemanticRelationProposal(
        proposal_id="semantic-proposal:2",
        relation=RelationTriple(
            known.relation.subject_ref,
            known.relation.predicate,
            "source-item:another-item",
        ),
        evidence_segment_ids=(5,),
    )

    result = collapse_sidecar_duplicates(sidecar, (duplicate, distinct))

    assert result.sidecar_relation_proposals == sidecar.relation_proposals
    assert result.semantic_relation_proposals == (distinct,)
    assert len(result.collapsed_duplicates) == 1
    collapsed = result.collapsed_duplicates[0]
    assert collapsed.sidecar_proposal_id == known.proposal_id
    assert collapsed.semantic_proposal_id == duplicate.proposal_id
    assert collapsed.semantic_evidence_segment_ids == (4, 9)
    assert collapsed.authority_bindings == known.authority_bindings
    assert result.model_leaf_count == 0


def test_replay_reproduces_sidecar_and_collapse_identities() -> None:
    first_sidecar = project_deterministic_sidecar(_sidecar_input())
    second_sidecar = project_deterministic_sidecar(_sidecar_input())
    semantic = SemanticRelationProposal(
        proposal_id="semantic-proposal:replay",
        relation=first_sidecar.relation_proposals[2].relation,
        evidence_segment_ids=(1,),
    )

    first = collapse_sidecar_duplicates(first_sidecar, (semantic,))
    second = collapse_sidecar_duplicates(second_sidecar, (semantic,))

    assert first_sidecar == second_sidecar
    assert first == second
    assert first.digest == second.digest


def _candidate(
    canonical_entity_id: str,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    identifiers: tuple[str, ...] = (),
    similarity_ppm: int = 0,
    source_ids: tuple[str, ...] = ("source:legco",),
) -> CanonicalEntityCandidate:
    return CanonicalEntityCandidate(
        canonical_entity_id=canonical_entity_id,
        canonical_name=name,
        entity_type="ORGANISATION",
        governed_aliases=aliases,
        governed_identifiers=identifiers,
        embedding_similarity_ppm=similarity_ppm,
        permitted_source_ids=source_ids,
    )


def test_exact_name_type_and_governed_alias_resolve_without_provider_leaf() -> None:
    policy = LocalEntityResolutionPolicy()
    exact = resolve_entity_locally(
        EntityMentionInput(
            name="Education Bureau",
            entity_type="ORGANISATION",
            source_id="source:legco",
        ),
        (_candidate("canonical-entity:edb", "Education Bureau"),),
        policy=policy,
    )
    alias = resolve_entity_locally(
        EntityMentionInput(
            name="EDB",
            entity_type="ORGANISATION",
            source_id="source:legco",
        ),
        (
            _candidate(
                "canonical-entity:edb",
                "Education Bureau",
                aliases=("EDB", "教育局"),
            ),
        ),
        policy=policy,
    )

    assert exact.outcome is LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE
    assert exact.selected_canonical_entity_id == "canonical-entity:edb"
    assert exact.basis is LocalEntityResolutionBasis.EXACT_NAME_AND_TYPE
    assert alias.outcome is LocalEntityResolutionOutcome.DETERMINISTIC_EXISTING_NODE
    assert alias.selected_canonical_entity_id == "canonical-entity:edb"
    assert alias.basis is LocalEntityResolutionBasis.GOVERNED_ALIAS_OR_IDENTIFIER
    assert exact.provider_leaf_count == alias.provider_leaf_count == 0


def test_normalised_name_and_identifier_resolve_locally() -> None:
    normalised = resolve_entity_locally(
        EntityMentionInput(
            name="education-bureau",
            entity_type="ORGANISATION",
            source_id="source:legco",
        ),
        (_candidate("canonical-entity:edb", "Education Bureau"),),
    )
    identifier = resolve_entity_locally(
        EntityMentionInput(
            name="The bureau",
            entity_type="ORGANISATION",
            source_id="source:legco",
            governed_identifiers=("org.hk.edb",),
        ),
        (
            _candidate(
                "canonical-entity:edb",
                "Education Bureau",
                identifiers=("org.hk.edb",),
            ),
        ),
    )

    assert normalised.selected_canonical_entity_id == "canonical-entity:edb"
    assert normalised.basis is LocalEntityResolutionBasis.NORMALISED_NAME_AND_TYPE
    assert identifier.selected_canonical_entity_id == "canonical-entity:edb"
    assert (
        identifier.basis
        is LocalEntityResolutionBasis.GOVERNED_ALIAS_OR_IDENTIFIER
    )


def test_similar_distinct_entities_stay_separate_and_low_margin_is_held() -> None:
    distinct = resolve_entity_locally(
        EntityMentionInput(
            name="Bank of East Asia",
            entity_type="ORGANISATION",
            source_id="source:legco",
        ),
        (
            _candidate(
                "canonical-entity:boc",
                "Bank of China",
                similarity_ppm=720_000,
            ),
        ),
    )
    ambiguous = resolve_entity_locally(
        EntityMentionInput(
            name="Lee",
            entity_type="ORGANISATION",
            source_id="source:legco",
        ),
        (
            _candidate("canonical-entity:lee-a", "Lee A", similarity_ppm=930_000),
            _candidate("canonical-entity:lee-b", "Lee B", similarity_ppm=910_000),
        ),
    )

    assert distinct.outcome is LocalEntityResolutionOutcome.DETERMINISTIC_NEW_NODE
    assert distinct.selected_canonical_entity_id is None
    assert ambiguous.outcome is LocalEntityResolutionOutcome.AMBIGUOUS_HOLD
    assert ambiguous.selected_canonical_entity_id is None
    assert ambiguous.provider_leaf_count == 0


def test_short_admitted_assertions_produce_bounded_canonical_summary() -> None:
    result = build_deterministic_summary(
        (
            AdmittedSummaryAssertion(
                assertion_id="assertion:2",
                text="The Education Bureau administers the curriculum.",
                evidence_links=("evidence:2",),
                temporal_links=("temporal:2",),
                admission_decision=_authority("admission-decision:2", admitted_assertion_id="assertion:2"),
            ),
            AdmittedSummaryAssertion(
                assertion_id="assertion:1",
                text="The Legislative Council asked about the curriculum.",
                evidence_links=("evidence:1",),
                temporal_links=("temporal:1",),
                admission_decision=_authority("admission-decision:1", admitted_assertion_id="assertion:1"),
            ),
        )
    )

    assert result.outcome is DeterministicSummaryOutcome.DETERMINISTIC_SUMMARY
    assert result.summary == (
        "The Legislative Council asked about the curriculum.; "
        "The Education Bureau administers the curriculum."
    )
    assert result.assertion_ids == ("assertion:1", "assertion:2")
    assert result.evidence_links == ("evidence:1", "evidence:2")
    assert result.temporal_links == ("temporal:1", "temporal:2")
    assert "evidence:" not in result.summary
    assert "temporal:" not in result.summary
    assert result.provider_leaf_count == 0


def test_overlong_summary_is_held_without_paraphrase_or_provider_dispatch() -> None:
    assertion = AdmittedSummaryAssertion(
        assertion_id="assertion:long",
        text="A" * 200,
        evidence_links=("evidence:long",),
        temporal_links=("temporal:long",),
        admission_decision=_authority("admission-decision:long", admitted_assertion_id="assertion:long"),
    )

    first = build_deterministic_summary((assertion,), maximum_bytes=64)
    second = build_deterministic_summary((assertion,), maximum_bytes=64)

    assert first.outcome is DeterministicSummaryOutcome.OVERLONG_HOLD
    assert first.summary is None
    assert first.requires_separate_policy is True
    assert first.provider_leaf_count == 0
    assert first == second


def test_average_token_model_separates_conditional_zero_token_work() -> None:
    sensitivity = ConditionalLeafTokenRanges(
        timestamp=TokenEstimateRange(30, 40, 50),
        dedupe=TokenEstimateRange(20, 30, 40),
        summary=TokenEstimateRange(10, 20, 30),
        fallback=TokenEstimateRange(40, 60, 80),
    )
    cases = (
        EffectiveRevisionTokenCase(
            case_id="revision:proposals",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=1,
            primary_tokens=TokenEstimateRange(100, 120, 150),
            current=ConditionalLeafProfile(dedupe=2, summary=1),
            target=ConditionalLeafProfile(),
            embedding_tokens=10,
            quality_matches_gold=True,
        ),
        EffectiveRevisionTokenCase(
            case_id="revision:zero",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS,
            primary_leaf_count=1,
            primary_tokens=TokenEstimateRange(100, 120, 150),
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=10,
            quality_matches_gold=True,
        ),
        EffectiveRevisionTokenCase(
            case_id="revision:held",
            outcome=EffectiveRevisionTokenOutcome.HELD_AMBIGUITY,
            primary_leaf_count=1,
            primary_tokens=TokenEstimateRange(100, 120, 150),
            current=ConditionalLeafProfile(dedupe=1),
            target=ConditionalLeafProfile(),
            embedding_tokens=10,
            quality_matches_gold=True,
        ),
    )

    report = build_token_effectiveness_report(cases, sensitivity=sensitivity)

    assert report["effective_revision_count"] == 3
    assert report["mandatory_primary_leaves_per_revision"] == {
        "basis": "MEASURED_EFFECTIVE_REVISION_CASES",
        "expected_count_ppm": 1_000_000,
        "revision_count": 3,
        "total_leaf_count": 3,
    }
    assert report["conditional_leaf_expected_counts_ppm"]["current"] == {
        "timestamp": 0,
        "dedupe": 1_000_000,
        "summary": 333_333,
        "fallback": 0,
    }
    assert report["conditional_leaf_expected_counts_ppm"]["target"] == {
        "timestamp": 0,
        "dedupe": 0,
        "summary": 0,
        "fallback": 0,
    }
    assert report["conditional_leaf_prevalence_ppm"]["current"] == {
        "timestamp": 0,
        "dedupe": 666_666,
        "summary": 333_333,
        "fallback": 0,
    }
    assert report["conditional_leaf_prevalence_ppm"]["target"] == {
        "timestamp": 0,
        "dedupe": 0,
        "summary": 0,
        "fallback": 0,
    }
    assert report["terminal_outcomes"] == {
        "terminal_success_with_proposals": 1,
        "terminal_success_zero_proposals": 1,
        "held_ambiguity": 1,
    }
    assert report["average_total_tokens_per_terminal_effective_revision"][
        "current"
    ] == {"low": 135, "base": 170, "high": 215}
    assert report["average_total_tokens_per_terminal_effective_revision"][
        "target"
    ] == {"low": 110, "base": 130, "high": 160}
    assert report["recommendation"] == "ADOPT_IN_731_IMPLEMENTATION_ATOM"


def test_primary_leaf_average_supports_zero_hits_and_multi_chunk_misses() -> None:
    cases = (
        EffectiveRevisionTokenCase(
            case_id="revision:exact-reuse-hit",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=0,
            primary_tokens=TokenEstimateRange(0, 0, 0),
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        ),
        EffectiveRevisionTokenCase(
            case_id="revision:three-chunk-miss",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=3,
            primary_tokens=TokenEstimateRange(300, 300, 300),
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        ),
    )

    report = build_token_effectiveness_report(
        cases,
        sensitivity=ConditionalLeafTokenRanges.zero(),
    )

    assert report["mandatory_primary_leaves_per_revision"] == {
        "basis": "MEASURED_EFFECTIVE_REVISION_CASES",
        "expected_count_ppm": 1_500_000,
        "revision_count": 2,
        "total_leaf_count": 3,
    }


def test_zero_primary_misses_reject_nonzero_primary_tokens() -> None:
    with pytest.raises(
        DeterministicWorkContractError,
        match="zero primary leaves require an exact zero primary token range",
    ):
        EffectiveRevisionTokenCase(
            case_id="revision:invalid-zero-hit",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=0,
            primary_tokens=TokenEstimateRange(1, 1, 1),
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        )


def test_zero_primary_misses_require_an_exact_zero_token_range() -> None:
    with pytest.raises(
        DeterministicWorkContractError,
        match="zero primary leaves require an exact zero primary token range",
    ):
        EffectiveRevisionTokenCase(
            case_id="revision:unresolved-zero-hit",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=0,
            primary_tokens=None,
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        )


def test_positive_primary_misses_reject_an_exact_zero_token_range() -> None:
    with pytest.raises(
        DeterministicWorkContractError,
        match="positive primary leaves require non-zero or unresolved primary tokens",
    ):
        EffectiveRevisionTokenCase(
            case_id="revision:invalid-positive-miss",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=2,
            primary_tokens=TokenEstimateRange(0, 0, 0),
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        )


def test_unresolved_usage_is_never_rendered_as_zero() -> None:
    case = EffectiveRevisionTokenCase(
        case_id="revision:unresolved",
        outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS,
        primary_leaf_count=None,
        primary_tokens=None,
        current=ConditionalLeafProfile(),
        target=ConditionalLeafProfile(),
        embedding_tokens=None,
        quality_matches_gold=True,
        unresolved_chat_leaves=1,
    )

    report = build_token_effectiveness_report(
        (case,),
        sensitivity=ConditionalLeafTokenRanges.zero(),
    )

    assert report["chat_tokens"]["unresolved"] == "UNRESOLVED"
    assert report["chat_tokens"]["estimated_primary"] == "UNRESOLVED"
    assert report["chat_tokens"]["unresolved_leaf_count"] == "UNRESOLVED"
    assert report["embedding_tokens"] == "UNRESOLVED"
    assert report["average_total_tokens_per_terminal_effective_revision"] == (
        "UNRESOLVED"
    )
    assert report["mandatory_primary_leaves_per_revision"] == "UNRESOLVED"
    assert report["recommendation"] == "HOLD_UNRESOLVED_USAGE"


def test_unknown_primary_tokens_derive_unresolved_leaf_count() -> None:
    case = EffectiveRevisionTokenCase(
        case_id="revision:two-unreported-primary-misses",
        outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
        primary_leaf_count=2,
        primary_tokens=None,
        current=ConditionalLeafProfile(),
        target=ConditionalLeafProfile(),
        embedding_tokens=0,
        quality_matches_gold=True,
    )

    report = build_token_effectiveness_report(
        (case,),
        sensitivity=ConditionalLeafTokenRanges.zero(),
    )

    assert report["chat_tokens"]["estimated_primary"] == "UNRESOLVED"
    assert report["chat_tokens"]["unresolved"] == "UNRESOLVED"
    assert report["chat_tokens"]["unresolved_leaf_count"] == 2
    assert report["recommendation"] == "HOLD_UNRESOLVED_USAGE"


def test_held_case_unresolved_usage_blocks_terminal_case_adoption() -> None:
    cases = (
        EffectiveRevisionTokenCase(
            case_id="revision:improving-terminal",
            outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
            primary_leaf_count=1,
            primary_tokens=TokenEstimateRange(100, 100, 100),
            current=ConditionalLeafProfile(dedupe=1),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        ),
        EffectiveRevisionTokenCase(
            case_id="revision:held-unreported-primary",
            outcome=EffectiveRevisionTokenOutcome.HELD_AMBIGUITY,
            primary_leaf_count=1,
            primary_tokens=None,
            current=ConditionalLeafProfile(),
            target=ConditionalLeafProfile(),
            embedding_tokens=0,
            quality_matches_gold=True,
        ),
    )

    report = build_token_effectiveness_report(
        cases,
        sensitivity=ConditionalLeafTokenRanges(
            timestamp=TokenEstimateRange(0, 0, 0),
            dedupe=TokenEstimateRange(10, 10, 10),
            summary=TokenEstimateRange(0, 0, 0),
            fallback=TokenEstimateRange(0, 0, 0),
        ),
    )

    assert report["chat_tokens"]["unresolved"] == "UNRESOLVED"
    assert report["chat_tokens"]["unresolved_leaf_count"] == 1
    assert report["recommendation"] == "HOLD_UNRESOLVED_USAGE"


def test_adoption_requires_strict_improvement_in_every_sensitivity_scenario() -> None:
    case = EffectiveRevisionTokenCase(
        case_id="revision:adversarial",
        outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
        primary_leaf_count=1,
        primary_tokens=TokenEstimateRange(100, 100, 100),
        current=ConditionalLeafProfile(dedupe=1),
        target=ConditionalLeafProfile(summary=1),
        embedding_tokens=0,
        quality_matches_gold=True,
    )
    report = build_token_effectiveness_report(
        (case,),
        sensitivity=ConditionalLeafTokenRanges(
            timestamp=TokenEstimateRange(0, 0, 0),
            dedupe=TokenEstimateRange(1, 100, 1_000),
            summary=TokenEstimateRange(0, 50, 1_100),
            fallback=TokenEstimateRange(0, 0, 0),
        ),
    )

    assert report["average_total_tokens_per_terminal_effective_revision"] == {
        "current": {"low": 101, "base": 200, "high": 1_100},
        "target": {"low": 100, "base": 150, "high": 1_200},
    }
    assert report["recommendation"] == "HOLD_NO_MEASURED_IMPROVEMENT"


def test_adoption_rejects_any_conditional_expected_count_regression() -> None:
    case = EffectiveRevisionTokenCase(
        case_id="revision:expected-count-regression",
        outcome=EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS,
        primary_leaf_count=1,
        primary_tokens=TokenEstimateRange(100, 100, 100),
        current=ConditionalLeafProfile(fallback=1),
        target=ConditionalLeafProfile(dedupe=1),
        embedding_tokens=0,
        quality_matches_gold=True,
    )
    report = build_token_effectiveness_report(
        (case,),
        sensitivity=ConditionalLeafTokenRanges(
            timestamp=TokenEstimateRange(0, 0, 0),
            dedupe=TokenEstimateRange(1, 1, 1),
            summary=TokenEstimateRange(0, 0, 0),
            fallback=TokenEstimateRange(10, 10, 10),
        ),
    )

    assert report["average_total_tokens_per_terminal_effective_revision"] == {
        "current": {"low": 110, "base": 110, "high": 110},
        "target": {"low": 101, "base": 101, "high": 101},
    }
    assert report["recommendation"] == "HOLD_NO_MEASURED_IMPROVEMENT"


def test_provider_free_packet_covers_issue_748_acceptance() -> None:
    packet = cast(dict[str, Any], run_provider_free_qualification())

    assert packet["issue"] == 748
    assert packet["provider_leaf_count"] == 0
    assert packet["live_graph_mutation_count"] == 0
    assert packet["effective_revision_distribution"]["case_count"] == 11
    assert packet["acceptance"]["sidecar_exact_and_no_loss"] is True
    assert packet["acceptance"]["authority_bytes_and_digests_verified"] is True
    assert packet["acceptance"]["existing_regression_suites"] == (
        "EXTERNAL_RUN_REQUIRED"
    )
    assert packet["acceptance"]["combined_temporal_gold_quality"] == (
        "EXTERNAL_RUN_REQUIRED"
    )
    assert packet["acceptance"]["conditional_leaf_expected_counts"] == "UNRESOLVED"
    assert packet["acceptance"]["conditional_leaf_prevalence"] == "UNRESOLVED"
    assert packet["token_effectiveness"]["recommendation"] == (
        "HOLD_UNMEASURED_EFFECTIVE_REVISION_DISTRIBUTION"
    )
    assert packet["token_effectiveness"]["conditional_leaf_expected_counts_ppm"][
        "target"
    ] == "UNRESOLVED"
    assert packet["token_effectiveness"]["mandatory_primary_leaves_per_revision"] == (
        "UNRESOLVED"
    )
    assert packet["recommendation"]["decision"] == (
        "HOLD_FOR_731_RUNTIME_MEASUREMENT"
    )
    retained_sensitivity = packet["token_effectiveness"][
        "retained_effective_revision_sensitivity"
    ]
    assert retained_sensitivity["unresolved_chat_leaf_count"] == 5
    assert retained_sensitivity[
        "average_total_token_estimate_per_terminal_effective_revision"
    ] == {
        "current": {"low": 1_738, "base": 3_454, "high": 9_189},
        "target": {"low": 1_354, "base": 1_918, "high": 3_045},
    }
    assert retained_sensitivity["adoption_gate"] == (
        "HOLD_UNRESOLVED_CLASSES_AND_QUALITY"
    )
    assert packet["live_evidence_context"] == {
        "terminal_effective_revision_count": 2,
        "chat_leaves": [3, 2],
            "embedding_requests": [3, 3],
            "semantic_leaf_classes": "UNRESOLVED",
            "chat_tokens": "UNRESOLVED",
            "unresolved_chat_leaf_count": 5,
        }


def test_checked_in_packet_is_exact_replay_of_provider_free_qualification() -> None:
    retained = json.loads(Path(DETERMINISTIC_WORK_MEASUREMENTS_PATH).read_text())

    assert retained == run_provider_free_qualification()
