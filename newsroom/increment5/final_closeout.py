"""Closed-world evidence inventory for the final Increment 5 Tier-M gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ._retrieval_qualification_common import digest, require_token
from ._traceability_model import RETRIEVAL_QUALIFICATION_REQUIREMENTS


class FinalCloseoutLane(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    ACTUAL_NEO4J = "ACTUAL_NEO4J"


class FinalCloseoutCategory(StrEnum):
    QUERY_CONTAINMENT = "QUERY_CONTAINMENT"
    RIGHTS_PURGE = "RIGHTS_PURGE"
    GRAPH_INDEX_RECOVERY = "GRAPH_INDEX_RECOVERY"
    FAILURE_NO_FALSE_SUCCESS = "FAILURE_NO_FALSE_SUCCESS"
    REPLAY_CONTEXT_INTEGRITY = "REPLAY_CONTEXT_INTEGRITY"
    QUALIFICATION_IDENTITY = "QUALIFICATION_IDENTITY"


INCREMENT5_FINAL_REQUIREMENTS = RETRIEVAL_QUALIFICATION_REQUIREMENTS


@dataclass(frozen=True, slots=True)
class FinalCloseoutCase:
    case_id: str
    category: FinalCloseoutCategory
    lane: FinalCloseoutLane
    test_id: str
    requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        require_token(self.case_id, field="closeout case_id")
        if (
            not self.test_id.startswith("newsroom.tests.test_")
            or "::test_" not in self.test_id
            or len(self.test_id) > 512
        ):
            raise RuntimeError("closeout test identity is not canonical")
        if (
            self.requirements != tuple(sorted(set(self.requirements)))
            or not self.requirements
            or not set(self.requirements) <= INCREMENT5_FINAL_REQUIREMENTS
        ):
            raise RuntimeError("closeout requirement inventory differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "category": self.category.value,
            "lane": self.lane.value,
            "test_id": self.test_id,
            "requirements": list(self.requirements),
        }


def _case(
    case_id: str,
    category: FinalCloseoutCategory,
    lane: FinalCloseoutLane,
    module: str,
    test_name: str,
    *requirements: str,
) -> FinalCloseoutCase:
    return FinalCloseoutCase(
        case_id=case_id,
        category=category,
        lane=lane,
        test_id=f"newsroom.tests.{module}::{test_name}",
        requirements=tuple(sorted(requirements)),
    )


_D = FinalCloseoutLane.DETERMINISTIC
_A = FinalCloseoutLane.ACTUAL_NEO4J
_Q = FinalCloseoutCategory.QUERY_CONTAINMENT
_R = FinalCloseoutCategory.RIGHTS_PURGE
_G = FinalCloseoutCategory.GRAPH_INDEX_RECOVERY
_F = FinalCloseoutCategory.FAILURE_NO_FALSE_SUCCESS
_P = FinalCloseoutCategory.REPLAY_CONTEXT_INTEGRITY
_I = FinalCloseoutCategory.QUALIFICATION_IDENTITY


INCREMENT5E2_FINAL_CLOSEOUT_CASES = tuple(
    sorted(
        (
            # Bounded named surface, injection, scope and credential containment.
            _case(
                "Q01_STRICT_REQUEST",
                _Q,
                _D,
                "test_increment5c1_named_tool_contracts",
                "test_unknown_or_extra_fields_fail_closed",
                "GRPROD-015",
            ),
            _case(
                "Q02_DUPLICATE_KEYS",
                _Q,
                _D,
                "test_increment5c1_named_tool_contracts",
                "test_duplicate_json_keys_fail_closed",
                "GRPROD-015",
            ),
            _case(
                "Q03_QUERY_IS_DATA",
                _Q,
                _D,
                "test_increment5c1_named_tool_contracts",
                "test_fulltext_query_is_bounded_data_and_cannot_select_another_tool",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "Q04_NO_MODEL_CREDENTIAL_SURFACE",
                _Q,
                _D,
                "test_increment5c1_named_tool_contracts",
                "test_vector_request_has_no_arbitrary_vector_or_model_surface",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "Q05_SCOPE_CONTAINMENT",
                _Q,
                _D,
                "test_increment5c1_named_tool_contracts",
                "test_typed_scope_cannot_be_widened_by_payload_or_query_content",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "Q06_AUTHORISE_BEFORE_DISPATCH",
                _Q,
                _D,
                "test_increment5c2_named_tool_authority_execution",
                "test_authorization_precedes_authority_dispatch",
                "GRPROD-015",
            ),
            _case(
                "Q07_NO_QUERY_OR_WRITE_SURFACE",
                _Q,
                _D,
                "test_increment5c2_named_tool_authority_execution",
                "test_authority_modules_expose_no_raw_query_or_write_surface",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "Q08_PRINCIPAL_CONFUSION",
                _Q,
                _D,
                "test_increment5d1_hybrid_composer",
                "test_composition_rejects_cross_principal_receipt_mixing",
                "GRAG-056",
            ),
            _case(
                "AQ01_FIXED_READ_PORT",
                _Q,
                _A,
                "test_increment5b4_neo4j_service",
                "test_increment5b4_fixed_port_reads_only_exact_generation_and_allowed_state",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "AQ02_WRONG_CREDENTIAL",
                _Q,
                _A,
                "test_projection_b2_neo4j_service",
                "test_actual_service_wrong_projector_credential_fails_closed_without_secret",
                "GRPROD-015",
            ),
            # Current rights checks, serving-derivative purge and non-resurrection.
            _case(
                "R01_AUTHORITY_RIGHTS_BLOCK",
                _R,
                _D,
                "test_increment5c2_named_tool_authority_execution",
                "test_rights_or_lifecycle_block_is_explicit_policy_block",
                "GRAG-056",
            ),
            _case(
                "R02_CONTEXT_RIGHTS_WITHDRAWAL",
                _R,
                _D,
                "test_increment5d2_retrieval_context",
                "test_current_rights_withdrawal_blocks_context_before_hydration",
                "GRAG-056",
            ),
            _case(
                "R03_GOVERNED_BLOB_TAMPER",
                _R,
                _D,
                "test_increment5d2_retrieval_context",
                "test_governed_blob_tamper_is_integrity_blocked",
                "GRAG-056",
            ),
            _case(
                "R04_RETAINED_CONTEXT_PURGE",
                _R,
                _D,
                "test_increment5d2_retrieval_context",
                "test_rights_purge_removes_retained_context_and_tombstone_blocks_replay",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "R05_EXACT_INDEX_REMOVALS",
                _R,
                _D,
                "test_complete_projection_2b_source_store",
                "test_revoked_evidence_is_never_upserted_and_emits_both_index_removals",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "R06_GOVERNED_BYTES_NON_RESURRECTION",
                _R,
                _D,
                "test_authority_a2b_lifecycle",
                "test_ordered_lifecycle_events_and_deletion_non_resurrection",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "R07_DERIVATIVE_TOMBSTONE_NEW_IDENTITY",
                _R,
                _D,
                "test_increment5d2_retrieval_context",
                "test_rights_purge_blocks_new_request_identity_before_rehydration",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "R08_PURGE_SAFE_STORAGE",
                _R,
                _D,
                "test_increment5d2_retrieval_context",
                "test_rights_purge_rejects_wal_mode_without_false_success",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "R09_EXACT_DERIVATIVE_TOMBSTONE",
                _R,
                _D,
                "test_increment5d2_retrieval_context",
                "test_rights_purge_does_not_tombstone_unselected_sibling_derivative",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AR01_RIGHTS_TOMBSTONE_PURGE",
                _R,
                _A,
                "test_complete_projection_2b_neo4j_service",
                "test_actual_service_revocation_and_tombstone_remove_current_derivatives",
                "GRAG-056",
            ),
            _case(
                "AR02_DELETION_NO_REQUALIFICATION",
                _R,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_governed_deletion_purges_derivative_and_never_requalifies",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AR03_RELATION_REVOCATION",
                _R,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_relation_revocation_changes_later_context_without_rewrite",
                "GRAG-056",
            ),
            _case(
                "AR04_TOMBSTONE_NON_RESURRECTION",
                _R,
                _A,
                "test_projection_b3_neo4j_service",
                "test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
                "GRAG-056",
            ),
            # Deterministic and actual-service graph/index replacement recovery.
            _case(
                "G01_AUTHORITY_ONLY_REBUILD",
                _G,
                _D,
                "test_projection_b3_rebuild",
                "test_rebuild_clears_target_and_replays_retained_authority",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "G02_REBUILD_NO_NEW_AUTHORITY",
                _G,
                _D,
                "test_projection_b3_rebuild",
                "test_exact_rebuild_replay_restores_graph_without_new_authority_events",
                "GRAG-056",
            ),
            _case(
                "G03_GENERATION_SCOPED_CLEANUP",
                _G,
                _D,
                "test_projection_b3_rebuild",
                "test_rebuild_cleanup_is_generation_scoped",
                "GRPROD-015",
            ),
            _case(
                "G04_CHECKPOINT_CONTAINMENT",
                _G,
                _D,
                "test_projection_b3_rebuild",
                "test_rebuild_target_cannot_precede_authoritative_checkpoint",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AG01_GRAPH_LOSS_RESTART",
                _G,
                _A,
                "test_projection_b3_neo4j_service",
                "test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AG02_REBUILD_NAMESPACE",
                _G,
                _A,
                "test_projection_b3_neo4j_service",
                "test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AG03_ISOLATED_REPLACEMENT",
                _G,
                _A,
                "test_increment4e_neo4j_service",
                "test_actual_service_increment4_graph_loss_requires_isolated_replacement",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AG04_AUTHORITY_REPLACEMENT",
                _G,
                _A,
                "test_complete_projection_2b_neo4j_service",
                "test_actual_service_replacement_generation_recovers_from_authority_only",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AG05_GENERATION_WATERMARK_INDEX",
                _G,
                _A,
                "test_complete_projection_2b_neo4j_service",
                "test_actual_service_wrong_watermark_generation_and_vector_dimension_fail_closed",
                "GRPROD-001",
                "GRPROD-015",
            ),
            _case(
                "AG06_FULLTEXT_CONTRACT",
                _G,
                _A,
                "test_complete_projection_2b_neo4j_service",
                "test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-fulltext-analyzer]",
                "GRPROD-001",
                "GRPROD-010",
                "GRPROD-015",
            ),
            # Missing, stale, corrupt or incomplete evidence never becomes success.
            _case(
                "F01_MANDATORY_BRANCH_ABSENT",
                _F,
                _D,
                "test_increment5d1_hybrid_composer",
                "test_missing_mandatory_branch_is_incomplete_not_no_match",
                "GRPROD-001",
                "GRPROD-023",
            ),
            _case(
                "F02_STALE_WATERMARK",
                _F,
                _D,
                "test_increment5d2_retrieval_context",
                "test_stale_authority_watermark_is_not_complete_or_no_match",
                "GRAG-056",
            ),
            _case(
                "F03_NO_MATCH_WITHOUT_CURRENT_COLLISION",
                _F,
                _D,
                "test_increment5d2_retrieval_context",
                "test_complete_no_match_requires_current_unoccupied_collision[False]",
                "GRAG-056",
                "GRPROD-001",
            ),
            _case(
                "F04_NO_MATCH_WITH_CURRENT_COLLISION",
                _F,
                _D,
                "test_increment5d2_retrieval_context",
                "test_complete_no_match_requires_current_unoccupied_collision[True]",
                "GRAG-056",
                "GRPROD-001",
            ),
            _case(
                "F05_AUTHORITY_RECEIPT_TAMPER",
                _F,
                _D,
                "test_increment5d2_retrieval_context",
                "test_tampered_authority_receipt_is_integrity_blocked",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AF01_MISSING_FULLTEXT",
                _F,
                _A,
                "test_retrieval_2c_neo4j_service",
                "test_actual_service_missing_fulltext_index_is_unavailable_not_no_match",
                "GRPROD-001",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "AF02_MISSING_VECTOR",
                _F,
                _A,
                "test_retrieval_2c_neo4j_service",
                "test_actual_service_missing_vector_index_is_unavailable_not_no_match",
                "GRPROD-001",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "AF03_MISSING_GRAPH",
                _F,
                _A,
                "test_retrieval_2c_neo4j_service",
                "test_actual_service_missing_admitted_relation_is_incomplete_not_no_match",
                "GRPROD-001",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "AF04_REQUIRED_GAP",
                _F,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_required_gap_blocks_complete_candidate_proof",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AF05_DEAD_LETTER",
                _F,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_dead_letter_blocks_complete_candidate_proof",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AF06_LOST_FULLTEXT",
                _F,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[fulltext]",
                "GRPROD-001",
                "GRPROD-015",
            ),
            _case(
                "AF07_LOST_RELATION",
                _F,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[relation]",
                "GRPROD-001",
                "GRPROD-015",
            ),
            _case(
                "AF08_LOST_VECTOR",
                _F,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_complete_proof_fails_closed_when_required_surface_is_lost[vector]",
                "GRPROD-001",
                "GRPROD-015",
            ),
            # Byte-identical replay, restart and retained-context integrity.
            _case(
                "P01_CONTEXT_REPLAY",
                _P,
                _D,
                "test_increment5d2_retrieval_context",
                "test_complete_context_replays_and_hydrates_exact_governed_bytes",
                "GRAG-056",
                "GRPROD-001",
            ),
            _case(
                "P02_JOURNAL_RESTART",
                _P,
                _D,
                "test_increment5d1_hybrid_composer",
                "test_journal_restart_replays_exact_bytes_and_rejects_conflict",
                "GRAG-056",
                "GRPROD-001",
            ),
            _case(
                "P03_CONTEXT_JOURNAL_RESTART",
                _P,
                _D,
                "test_increment5d2_retrieval_context",
                "test_retained_context_restart_replays_exact_bytes",
                "GRAG-056",
                "GRPROD-001",
            ),
            _case(
                "P04_CONTEXT_JOURNAL_TAMPER",
                _P,
                _D,
                "test_increment5d2_retrieval_context",
                "test_retained_context_tamper_is_integrity_blocked",
                "GRAG-056",
                "GRPROD-015",
            ),
            _case(
                "AP01_ACTUAL_REPLAY_RESTART",
                _P,
                _A,
                "test_increment_2d_neo4j_service",
                "test_actual_service_complete_increment_2_proof_admits_replays_and_restarts",
                "GRAG-056",
                "GRPROD-001",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "AP02_RETAINED_CONTEXT_RECOVERY",
                _P,
                _A,
                "test_integrated_c1_neo4j_service",
                "test_actual_service_integrated_foundation_replay_recovery_and_tombstone",
                "GRAG-056",
                "GRPROD-015",
            ),
            # Qualification target, corpus and every derived Epoch identity.
            _case(
                "I01_FIVE_SYSTEM_QUALIFICATION",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_complete_fixture_qualification_is_pass_and_ablations_are_separate",
                "GRAG-050",
                "GRAG-051",
                "GRAG-054",
                "GRAG-055",
                "GRPROD-001",
                "GRPROD-010",
                "GRPROD-015",
                "GRPROD-023",
            ),
            _case(
                "I02_GRAPH_RIGHTS",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_safety_and_rights_violations_in_any_executed_system_block[ADMITTED_GRAPH_ONLY-change0]",
                "GRAG-056",
            ),
            _case(
                "I03_EXACT_RIGHTS",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_safety_and_rights_violations_in_any_executed_system_block[EXACT_ONLY-change1]",
                "GRAG-056",
            ),
            _case(
                "I04_FULLTEXT_RIGHTS",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_safety_and_rights_violations_in_any_executed_system_block[FULL_TEXT_ONLY-change2]",
                "GRAG-056",
            ),
            _case(
                "I05_VECTOR_RIGHTS",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_safety_and_rights_violations_in_any_executed_system_block[VECTOR_ONLY-change3]",
                "GRAG-056",
            ),
            _case(
                "I06_CORPUS_CONTENT_IDENTITY",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_caller_modified_corpus_cannot_reuse_stale_content_identities",
                "GRAG-054",
                "GRAG-055",
                "GRAG-056",
            ),
            _case(
                "I07_SOURCE_PROVIDER_IDENTITY",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_every_derived_epoch_identity_is_revalidated_before_evaluation[source_provider_versions_digest]",
                "GRAG-050",
                "GRAG-056",
            ),
            _case(
                "I08_ADAPTER_PARSER_IDENTITY",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_every_derived_epoch_identity_is_revalidated_before_evaluation[adapter_parser_versions_digest]",
                "GRAG-050",
                "GRAG-056",
            ),
            _case(
                "I09_THRESHOLD_IDENTITY",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_every_derived_epoch_identity_is_revalidated_before_evaluation[threshold_set_digest]",
                "GRAG-050",
                "GRAG-056",
            ),
            _case(
                "I10_POLICY_IDENTITY",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_every_derived_epoch_identity_is_revalidated_before_evaluation[policy_set_digest]",
                "GRAG-050",
                "GRAG-056",
            ),
            _case(
                "I11_CODE_TREE_AND_TARGET",
                _I,
                _D,
                "test_increment5e1_retrieval_qualification",
                "test_epoch_code_tree_and_exact_target_are_independently_revalidated",
                "GRAG-050",
                "GRPROD-010",
                "GRPROD-015",
            ),
            _case(
                "AI01_EXACT_TARGET_REPORT",
                _I,
                _A,
                "test_projection_b2_increment5e2_neo4j_service",
                "test_actual_service_increment5e2_target_and_report",
                *sorted(INCREMENT5_FINAL_REQUIREMENTS),
            ),
        ),
        key=lambda item: item.case_id,
    )
)


INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST = digest(
    [case.canonical_value() for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES]
)

INCREMENT5E2_FINAL_NON_EFFECTS = (
    "NO_LIVE_AUTHORITY_MUTATION",
    "NO_LIVE_CANDIDATE_OR_HYPOTHESIS_EFFECT",
    "NO_LIVE_SOURCE_OR_PRODUCTION_PRODUCT_CREDENTIAL_USE",
    "NO_LIVE_SOURCE_OR_PROVIDER_CALL",
    "NO_MODEL_OR_EMBEDDING_CALL",
    "NO_PRODUCT_RUNTIME_NETWORK_EGRESS_OR_SPEND",
    "NO_PUBLICATION_OR_PRODUCTION_ACTIVATION",
    "NO_SHADOW_OR_CANARY_ACTIVATION",
)


def validate_increment5e2_final_closeout_inventory() -> None:
    case_ids = tuple(case.case_id for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES)
    test_ids = tuple(case.test_id for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES)
    if (
        case_ids != tuple(sorted(case_ids))
        or len(case_ids) != len(set(case_ids))
        or len(test_ids) != len(set(test_ids))
    ):
        raise RuntimeError("final closeout cases are not closed and unique")
    if {case.category for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES} != set(
        FinalCloseoutCategory
    ):
        raise RuntimeError("final closeout category inventory differs")
    if {case.lane for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES} != set(
        FinalCloseoutLane
    ):
        raise RuntimeError("final closeout lane inventory differs")
    if {
        requirement
        for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
        for requirement in case.requirements
    } != INCREMENT5_FINAL_REQUIREMENTS:
        raise RuntimeError("final closeout requirement coverage differs")
    for category in FinalCloseoutCategory:
        lanes = {
            case.lane
            for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
            if case.category is category
        }
        if lanes != set(FinalCloseoutLane):
            raise RuntimeError(
                f"final closeout category lacks both evidence lanes: {category.value}"
            )
    if INCREMENT5E2_FINAL_NON_EFFECTS != tuple(sorted(INCREMENT5E2_FINAL_NON_EFFECTS)):
        raise RuntimeError("final closeout non-effects are not canonical")


validate_increment5e2_final_closeout_inventory()


__all__ = [
    "FinalCloseoutCase",
    "FinalCloseoutCategory",
    "FinalCloseoutLane",
    "INCREMENT5E2_FINAL_CLOSEOUT_CASES",
    "INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST",
    "INCREMENT5E2_FINAL_NON_EFFECTS",
    "INCREMENT5_FINAL_REQUIREMENTS",
    "validate_increment5e2_final_closeout_inventory",
]
