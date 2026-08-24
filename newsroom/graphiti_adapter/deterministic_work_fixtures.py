"""Source-safe provider-free qualification fixtures for Graphiti issue #748."""

from __future__ import annotations

from pathlib import Path

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.graphiti_adapter.combined_temporal_contract import build_compact_prompt
from newsroom.graphiti_adapter.combined_temporal_fixtures import FIXTURES
from newsroom.graphiti_adapter.deterministic_sidecar import (
    AuthorityRecordRef,
    DeterministicSidecarInput,
    SemanticRelationProposal,
    collapse_sidecar_duplicates,
    project_deterministic_sidecar,
)
from newsroom.graphiti_adapter.deterministic_summary import (
    AdmittedSummaryAssertion,
    build_deterministic_summary,
)
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_CORE_RELEASE
from newsroom.graphiti_adapter.local_entity_resolution import (
    CanonicalEntityCandidate,
    EntityMentionInput,
    LocalEntityResolutionOutcome,
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

_REPO = Path(__file__).resolve().parents[2]
DETERMINISTIC_WORK_MEASUREMENTS_PATH = (
    _REPO
    / "docs"
    / "research"
    / "2026-08-24-graphiti-deterministic-work-measurements.json"
)

def _authority(
    record_id: str,
    *,
    record_kind: str = "ADMISSION_DECISION",
    **record_fields: object,
) -> AuthorityRecordRef:
    canonical_bytes = canonical_json_bytes(
        {
            "fixture_authority": "ISSUE_748_PROVIDER_FREE",
            "issue": 748,
            "record_id": record_id,
            "record_kind": record_kind,
            "source_safe": True,
            **record_fields,
        }
    )
    return AuthorityRecordRef(
        record_id=record_id,
        canonical_bytes=canonical_bytes,
        canonical_digest=digest_bytes(canonical_bytes),
    )


def _sidecar_input(fixture_name: str) -> DeterministicSidecarInput:
    fixture = next(item for item in FIXTURES if item.name == fixture_name)
    revision = fixture.revision
    source_definition_id = f"source-definition:{revision.source_id}"
    source_item_id = f"source-item:{revision.source_id}:{revision.item_key}"
    source_revision_id = f"source-revision:{revision.revision_id}"
    representation_id = f"representation:{revision.representation_digest}"
    evidence_package_id = f"evidence-package:{revision.revision_id}"
    rights_decision_id = f"rights-decision:{revision.revision_id}"
    chunk_id = f"source-chunk:{revision.revision_id}:{revision.chunk_ordinal}"
    predecessor_revision = (
        None
        if revision.predecessor_revision_id is None
        else _authority(
            f"source-revision:{revision.predecessor_revision_id}",
            record_kind="SOURCE_REVISION",
        )
    )
    predecessor_chunk = (
        None
        if revision.chunk_ordinal == 1
        else _authority(
            f"source-chunk:{revision.revision_id}:{revision.chunk_ordinal - 1}",
            record_kind="SOURCE_CHUNK",
        )
    )
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
            predecessor_revision_id=(
                None
                if predecessor_revision is None
                else predecessor_revision.record_id
            ),
            representation_id=representation_id,
            evidence_package_id=evidence_package_id,
            rights_decision_id=rights_decision_id,
            chunk_id=chunk_id,
            reference_time=revision.reference_time,
        ),
        predecessor_revision=predecessor_revision,
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
            chunk_ordinal=revision.chunk_ordinal,
            predecessor_chunk_id=(
                None
                if predecessor_chunk is None
                else predecessor_chunk.record_id
            ),
        ),
        predecessor_chunk=predecessor_chunk,
        reference_time=revision.reference_time,
        chunk_ordinal=revision.chunk_ordinal,
    )


def _token_range_from_bytes(byte_count: int) -> TokenEstimateRange:
    return TokenEstimateRange(
        low=(byte_count + 3) // 4,
        base=(byte_count + 2) // 3,
        high=(byte_count + 1) // 2,
    )


def _token_cases() -> tuple[EffectiveRevisionTokenCase, ...]:
    cases: list[EffectiveRevisionTokenCase] = []
    for fixture in FIXTURES:
        prompt = build_compact_prompt(fixture.revision)
        byte_count = len(prompt.text.encode("utf-8")) + len(
            canonical_json_bytes(prompt.schema)
        ) + len(canonical_json_bytes(fixture.gold))
        if fixture.name == "zero-result":
            outcome = EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
        elif fixture.name == "same-name":
            outcome = EffectiveRevisionTokenOutcome.HELD_AMBIGUITY
        else:
            outcome = EffectiveRevisionTokenOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
        cases.append(
            EffectiveRevisionTokenCase(
                case_id=fixture.name,
                outcome=outcome,
                primary_tokens=_token_range_from_bytes(byte_count),
                current=ConditionalLeafProfile(),
                target=ConditionalLeafProfile(),
                embedding_tokens=len(fixture.revision.body.split()),
                quality_matches_gold=None,
            )
        )
    return tuple(cases)


def _retained_effective_revision_sensitivity() -> dict[str, object]:
    """Estimate the two retained terminal outcomes without inventing usage."""

    cases = _token_cases()
    primary_total = TokenEstimateRange(0, 0, 0)
    for case in cases:
        if case.primary_tokens is not None:
            primary_total = primary_total.plus(case.primary_tokens)
    primary_average = TokenEstimateRange(
        primary_total.low // len(cases),
        primary_total.base // len(cases),
        primary_total.high // len(cases),
    )
    whitespace_tokens_per_embedding_request = (
        sum(len(fixture.revision.body.split()) for fixture in FIXTURES)
        // len(FIXTURES)
    )
    embedding_per_revision = TokenEstimateRange(
        whitespace_tokens_per_embedding_request * 3 // 2,
        whitespace_tokens_per_embedding_request * 3,
        whitespace_tokens_per_embedding_request * 6,
    )
    retained_additional_chat_leaves = 3
    retained_terminal_revisions = 2
    conditional_per_leaf = TokenEstimateRange(256, 1_024, 4_096)
    conditional_per_revision = TokenEstimateRange(
        conditional_per_leaf.low
        * retained_additional_chat_leaves
        // retained_terminal_revisions,
        conditional_per_leaf.base
        * retained_additional_chat_leaves
        // retained_terminal_revisions,
        conditional_per_leaf.high
        * retained_additional_chat_leaves
        // retained_terminal_revisions,
    )
    target = primary_average.plus(embedding_per_revision)
    current = target.plus(conditional_per_revision)
    return {
        "basis": "TWO_RETAINED_ISSUE_737_GRAIN_TERMINAL_OUTCOMES",
        "terminal_effective_revision_count": retained_terminal_revisions,
        "observed_chat_leaf_counts": [3, 2],
        "observed_additional_chat_leaf_count": retained_additional_chat_leaves,
        "observed_embedding_request_counts": [3, 3],
        "conditional_leaf_classes": "UNRESOLVED",
        "chat_tokens": "UNRESOLVED",
        "unresolved_chat_leaf_count": 5,
        "embedding_tokens": "ESTIMATED_SOURCE_SAFE_WHITESPACE_PROXY",
        "sensitivity_tokens_per_unclassified_conditional_leaf": (
            conditional_per_leaf.canonical_value()
        ),
        "average_total_token_estimate_per_terminal_effective_revision": {
            "current": current.canonical_value(),
            "target": target.canonical_value(),
        },
        "adoption_gate": "HOLD_UNRESOLVED_CLASSES_AND_QUALITY",
    }


def _candidate(
    canonical_entity_id: str,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    identifiers: tuple[str, ...] = (),
    similarity_ppm: int = 0,
) -> CanonicalEntityCandidate:
    return CanonicalEntityCandidate(
        canonical_entity_id=canonical_entity_id,
        canonical_name=name,
        entity_type="ORGANISATION",
        governed_aliases=aliases,
        governed_identifiers=identifiers,
        embedding_similarity_ppm=similarity_ppm,
        permitted_source_ids=("newsroom-fixture",),
    )


def _resolution_evidence() -> dict[str, dict[str, object]]:
    exact = resolve_entity_locally(
        EntityMentionInput(
            "Education Bureau", "ORGANISATION", "newsroom-fixture"
        ),
        (_candidate("canonical-entity:edb", "Education Bureau"),),
    )
    alias = resolve_entity_locally(
        EntityMentionInput("教育局", "ORGANISATION", "newsroom-fixture"),
        (
            _candidate(
                "canonical-entity:edb",
                "Education Bureau",
                aliases=("EDB", "教育局"),
            ),
        ),
    )
    normalised = resolve_entity_locally(
        EntityMentionInput(
            "education-bureau", "ORGANISATION", "newsroom-fixture"
        ),
        (_candidate("canonical-entity:edb", "Education Bureau"),),
    )
    identifier = resolve_entity_locally(
        EntityMentionInput(
            "The bureau",
            "ORGANISATION",
            "newsroom-fixture",
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
    distinct = resolve_entity_locally(
        EntityMentionInput(
            "Bank of East Asia", "ORGANISATION", "newsroom-fixture"
        ),
        (_candidate("canonical-entity:boc", "Bank of China", similarity_ppm=720_000),),
    )
    ambiguous_candidates = (
        _candidate("canonical-entity:lee-a", "Lee A", similarity_ppm=930_000),
        _candidate("canonical-entity:lee-b", "Lee B", similarity_ppm=910_000),
    )
    ambiguous_mention = EntityMentionInput(
        "Lee", "ORGANISATION", "newsroom-fixture"
    )
    ambiguous = resolve_entity_locally(ambiguous_mention, ambiguous_candidates)
    values = {
        "exact_name_type": exact,
        "governed_alias": alias,
        "normalised_name": normalised,
        "governed_identifier": identifier,
        "similar_distinct": distinct,
        "low_margin": ambiguous,
    }
    return {
        name: {
            "outcome": result.outcome.value,
            "selected_canonical_entity_id": result.selected_canonical_entity_id,
            "basis": result.basis.value,
            "provider_leaf_count": result.provider_leaf_count,
            "digest": result.digest,
        }
        for name, result in values.items()
    }


def run_provider_free_qualification() -> dict[str, object]:
    """Run the complete source-safe #748 qualification with no external I/O."""

    sidecars = tuple(
        project_deterministic_sidecar(_sidecar_input(fixture.name))
        for fixture in FIXTURES
    )
    duplicate_sidecar = sidecars[0]
    duplicate_proposal = duplicate_sidecar.relation_proposals[0]
    collapse = collapse_sidecar_duplicates(
        duplicate_sidecar,
        (
            SemanticRelationProposal(
                proposal_id="semantic:fixture-duplicate",
                relation=duplicate_proposal.relation,
                evidence_segment_ids=(0,),
            ),
        ),
    )
    short_summary = build_deterministic_summary(
        (
            AdmittedSummaryAssertion(
                assertion_id="assertion:1",
                text="The Legislative Council asked about the curriculum.",
                evidence_links=("evidence:1",),
                temporal_links=("temporal:1",),
                admission_decision=_authority("admission-decision:1", admitted_assertion_id="assertion:1"),
            ),
            AdmittedSummaryAssertion(
                assertion_id="assertion:2",
                text="The Education Bureau administers the curriculum.",
                evidence_links=("evidence:2",),
                temporal_links=("temporal:2",),
                admission_decision=_authority("admission-decision:2", admitted_assertion_id="assertion:2"),
            ),
        )
    )
    overlong_summary = build_deterministic_summary(
        (
            AdmittedSummaryAssertion(
                assertion_id="assertion:long",
                text="A" * 200,
                evidence_links=("evidence:long",),
                temporal_links=("temporal:long",),
                admission_decision=_authority("admission-decision:long", admitted_assertion_id="assertion:long"),
            ),
        ),
        maximum_bytes=64,
    )
    sensitivity = ConditionalLeafTokenRanges(
        timestamp=TokenEstimateRange(756, 1_008, 1_511),
        dedupe=TokenEstimateRange(512, 1_024, 2_048),
        summary=TokenEstimateRange(256, 512, 1_024),
        fallback=TokenEstimateRange(1_024, 2_048, 4_096),
    )
    token_effectiveness = {
        **build_token_effectiveness_report(
            _token_cases(),
            sensitivity=sensitivity,
            distribution_measured=False,
        ),
        "conditional_probability_basis": (
            "UNRESOLVED_NO_EXECUTED_EFFECTIVE_REVISION_TRACE"
        ),
        "average_token_basis": (
            "UNRESOLVED_PENDING_ISSUE_731_RUNTIME_MEASUREMENT"
        ),
        "scope": "PROVIDER_FREE_ISSUE_747_FIXTURE_SAMPLE",
        "retained_effective_revision_sensitivity": (
            _retained_effective_revision_sensitivity()
        ),
    }
    token_effectiveness["chat_tokens"] = {
        **token_effectiveness["chat_tokens"],
        "reported_basis": "NO_PROVIDER_CALLS_IN_FIXTURE",
    }
    resolution = _resolution_evidence()
    replayed_sidecars = tuple(
        project_deterministic_sidecar(_sidecar_input(fixture.name))
        for fixture in FIXTURES
    )
    acceptance = {
        "sidecar_exact_and_no_loss": all(
            sidecar.model_leaf_count == 0
            and sidecar.authority == "SQLITE_GOVERNED_RECORDS"
            and all(
                proposal.authority_bindings
                for proposal in sidecar.relation_proposals
            )
            for sidecar in sidecars
        ),
        "authority_bytes_and_digests_verified": all(
            digest_bytes(binding.canonical_bytes) == binding.canonical_digest
            for sidecar in sidecars
            for proposal in sidecar.relation_proposals
            for binding in proposal.authority_bindings
        ),
        "semantic_duplicate_collapsed_with_attribution": (
            len(collapse.collapsed_duplicates) == 1
            and not collapse.semantic_relation_proposals
            and collapse.sidecar_relation_proposals
            == duplicate_sidecar.relation_proposals
        ),
        "common_entity_resolution_zero_provider_leaves": all(
            evidence["provider_leaf_count"] == 0
            for evidence in resolution.values()
        ),
        "similar_distinct_entities_separate": (
            resolution["similar_distinct"]["outcome"]
            == LocalEntityResolutionOutcome.DETERMINISTIC_NEW_NODE.value
        ),
        "ambiguity_held_not_guessed": (
            resolution["low_margin"]["outcome"]
            == LocalEntityResolutionOutcome.AMBIGUOUS_HOLD.value
        ),
        "short_summary_zero_provider_leaves": (
            short_summary.summary is not None
            and short_summary.provider_leaf_count == 0
        ),
        "overlong_summary_explicitly_held": (
            overlong_summary.summary is None
            and overlong_summary.requires_separate_policy
            and overlong_summary.provider_leaf_count == 0
        ),
        "replay_identities_identical": sidecars == replayed_sidecars,
        "combined_temporal_gold_quality": "EXTERNAL_RUN_REQUIRED",
        "existing_regression_suites": "EXTERNAL_RUN_REQUIRED",
        "conditional_leaf_probabilities": "UNRESOLVED",
    }
    return {
        "schema_version": "newsroom.graphiti-deterministic-work-qualification.v1",
        "issue": 748,
        "parent_issue": 739,
        "implementation_atom": 731,
        "graphiti_core_version": GRAPHITI_CORE_RELEASE,
        "qualification_basis": "PROVIDER_FREE_SOURCE_SAFE_FIXTURES",
        "provider_leaf_count": 0,
        "live_graph_mutation_count": 0,
        "effective_revision_distribution": {
            "grain": "ISSUE_737_EFFECTIVE_REVISION",
            "distribution_basis": "UNRESOLVED_NO_EXECUTED_TRACE",
            "case_count": len(FIXTURES),
            "case_ids": [fixture.name for fixture in FIXTURES],
        },
        "sidecar": {
            "schema_version": "newsroom.graphiti-deterministic-sidecar.v1",
            "authority": "SQLITE_GOVERNED_RECORDS",
            "proposal_only": True,
            "relation_proposal_count": sum(
                len(sidecar.relation_proposals) for sidecar in sidecars
            ),
            "semantic_prompt_bytes_removed": sum(
                sidecar.semantic_prompt_bytes_removed for sidecar in sidecars
            ),
            "semantic_output_bytes_avoided": sum(
                sidecar.semantic_output_bytes_avoided for sidecar in sidecars
            ),
            "projection_digests": [sidecar.digest for sidecar in sidecars],
        },
        "duplicate_collapse": {
            "collapse_count": len(collapse.collapsed_duplicates),
            "semantic_relation_proposal_count_after_collapse": len(
                collapse.semantic_relation_proposals
            ),
            "sidecar_relation_proposal_count_after_collapse": len(
                collapse.sidecar_relation_proposals
            ),
            "collapse_digest": collapse.digest,
        },
        "local_entity_resolution": resolution,
        "deterministic_summary": {
            "short_outcome": short_summary.outcome.value,
            "short_digest": short_summary.digest,
            "overlong_outcome": overlong_summary.outcome.value,
            "overlong_digest": overlong_summary.digest,
            "evidence_and_temporal_links_outside_summary": True,
        },
        "token_effectiveness": token_effectiveness,
        "live_evidence_context": {
            "terminal_effective_revision_count": 2,
            "chat_leaves": [3, 2],
            "embedding_requests": [3, 3],
            "semantic_leaf_classes": "UNRESOLVED",
            "chat_tokens": "UNRESOLVED",
            "unresolved_chat_leaf_count": 5,
        },
        "fallback_and_retry_policy": {
            "authority": "INHERIT_ISSUE_731_DISTINCT_REQUEST_POLICY",
            "unchanged_prompt_schema_redispatch_permitted": False,
            "maximum_typed_fallbacks_per_distinct_request": 1,
            "fallback_eligible_outcomes": ["MALFORMED_OUTPUT"],
            "fallback_ineligible_outcomes": [
                "AUTHENTICATION_FAILURE",
                "CONFIGURATION_FAILURE",
                "TIMEOUT",
                "CANCELLATION",
                "SYSTEMIC_PROVIDER_FAILURE",
            ],
            "route_circuit_after_systemic_or_repeated_no_result": True,
            "new_fallback_authority_created": False,
        },
        "acceptance": acceptance,
        "recommendation": {
            "decision": "HOLD_FOR_731_RUNTIME_MEASUREMENT",
            "runtime_activation_authorised": False,
            "remaining_exceptional_leaves": (
                "DISTINCT_QUALIFIED_RECEIPTED_ONLY"
            ),
        },
        "non_effects": [
            "NO_PROVIDER_CALL",
            "NO_MODEL_DOWNLOAD_OR_LOAD",
            "NO_PRODUCTION_GRAPHITI_MUTATION",
            "NO_ADD_TRIPLET",
            "NO_GING_010_AMENDMENT",
            "NO_PUBLICATION",
            "NO_BACKLOG_ACTIVATION",
        ],
    }


__all__ = [
    "DETERMINISTIC_WORK_MEASUREMENTS_PATH",
    "run_provider_free_qualification",
]
