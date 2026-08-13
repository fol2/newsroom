"""Closed-world evidence inventory for the final Increment 6 Tier-M gate.

The inventory names permanent repository tests which exercise the public
Increment 6 authority facades. It introduces no writer or product effect: the
SDLC receipt reconciles their retained JUnit outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes


class Increment6CloseoutLane(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    ACTUAL_NEO4J = "ACTUAL_NEO4J"


class Increment6CloseoutCategory(StrEnum):
    MIGRATION_LIFECYCLE = "MIGRATION_LIFECYCLE"
    WORK_CONTROL = "WORK_CONTROL"
    PROPOSAL_AUTHORITY = "PROPOSAL_AUTHORITY"
    HYPOTHESIS_AND_RELATIONSHIP = "HYPOTHESIS_AND_RELATIONSHIP"
    LINEAGE = "LINEAGE"
    CANDIDATE_ADMISSION = "CANDIDATE_ADMISSION"
    HANDOFF_TRANSPORT = "HANDOFF_TRANSPORT"
    FEEDBACK_RECONCILIATION = "FEEDBACK_RECONCILIATION"
    DISCOVERY_REENTRY = "DISCOVERY_REENTRY"
    RIGHTS_AND_FAILURE = "RIGHTS_AND_FAILURE"
    ACTUAL_SERVICE_SECURITY = "ACTUAL_SERVICE_SECURITY"
    CLOSEOUT_INTEGRITY = "CLOSEOUT_INTEGRITY"


INCREMENT6_FINAL_REQUIREMENTS = frozenset(
    {
        "ACTUAL_SERVICE_IDENTITY_AUTHENTICATED_TRANSPORT",
        "CLOSED_WORLD_RECEIPT_SIGNED_EXACT_MAIN",
        "COLLISION_CANDIDATE_EQUIVALENT_DISTINCT_ADMISSION",
        "CONCURRENT_CLAIM_ADMISSION_HANDOFF_ACK_RETRY",
        "FEEDBACK_OBLIGATION_RECONCILIATION_VISIBILITY",
        "HYPOTHESIS_CREATE_APPEND_RELATIONSHIP_CORRECTION_REVERSAL",
        "LINEAGE_CONSOLIDATION_SPLIT_REVERSAL_SAFETY",
        "MIGRATION_V1_V25_HISTORY_UPGRADE_ROLLBACK_RESTART_REPLAY",
        "PROPOSAL_REJECT_HOLD_ESCALATE_NO_AUTHORITY",
        "RIGHTS_TOMBSTONE_NO_FALSE_SUCCESS_TAMPER_UNAVAILABLE_DEGRADED",
        "SUPPLEMENTAL_DISCOVERY_WATCH_REENTRY",
        "WORK_ITEM_OWNERSHIP_URGENT_DEGRADED_FAIRNESS_STALE",
    }
)


@dataclass(frozen=True, slots=True)
class Increment6CloseoutCase:
    case_id: str
    category: Increment6CloseoutCategory
    lane: Increment6CloseoutLane
    test_id: str
    requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id or not self.case_id.isascii():
            raise RuntimeError("closeout case identity differs")
        if (
            not self.test_id.startswith("newsroom.tests.test_")
            or "::test_" not in self.test_id
            or len(self.test_id) > 512
        ):
            raise RuntimeError("closeout test identity is not canonical")
        if (
            not self.requirements
            or self.requirements != tuple(sorted(set(self.requirements)))
            or not set(self.requirements) <= INCREMENT6_FINAL_REQUIREMENTS
        ):
            raise RuntimeError("closeout requirement inventory differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "category": self.category.value,
            "lane": self.lane.value,
            "requirements": list(self.requirements),
            "test_id": self.test_id,
        }


def _case(
    case_id: str,
    category: Increment6CloseoutCategory,
    lane: Increment6CloseoutLane,
    module: str,
    test_name: str,
    *requirements: str,
) -> Increment6CloseoutCase:
    return Increment6CloseoutCase(
        case_id=case_id,
        category=category,
        lane=lane,
        test_id=f"newsroom.tests.{module}::{test_name}",
        requirements=tuple(sorted(requirements)),
    )


_D = Increment6CloseoutLane.DETERMINISTIC
_A = Increment6CloseoutLane.ACTUAL_NEO4J
_M = Increment6CloseoutCategory.MIGRATION_LIFECYCLE
_W = Increment6CloseoutCategory.WORK_CONTROL
_P = Increment6CloseoutCategory.PROPOSAL_AUTHORITY
_H = Increment6CloseoutCategory.HYPOTHESIS_AND_RELATIONSHIP
_L = Increment6CloseoutCategory.LINEAGE
_C = Increment6CloseoutCategory.CANDIDATE_ADMISSION
_T = Increment6CloseoutCategory.HANDOFF_TRANSPORT
_F = Increment6CloseoutCategory.FEEDBACK_RECONCILIATION
_R = Increment6CloseoutCategory.DISCOVERY_REENTRY
_X = Increment6CloseoutCategory.RIGHTS_AND_FAILURE
_S = Increment6CloseoutCategory.ACTUAL_SERVICE_SECURITY
_Z = Increment6CloseoutCategory.CLOSEOUT_INTEGRITY

_MIGRATION = "MIGRATION_V1_V25_HISTORY_UPGRADE_ROLLBACK_RESTART_REPLAY"
_WORK = "WORK_ITEM_OWNERSHIP_URGENT_DEGRADED_FAIRNESS_STALE"
_PROPOSAL = "PROPOSAL_REJECT_HOLD_ESCALATE_NO_AUTHORITY"
_HYPOTHESIS = "HYPOTHESIS_CREATE_APPEND_RELATIONSHIP_CORRECTION_REVERSAL"
_LINEAGE = "LINEAGE_CONSOLIDATION_SPLIT_REVERSAL_SAFETY"
_CANDIDATE = "COLLISION_CANDIDATE_EQUIVALENT_DISTINCT_ADMISSION"
_HANDOFF = "CONCURRENT_CLAIM_ADMISSION_HANDOFF_ACK_RETRY"
_FEEDBACK = "FEEDBACK_OBLIGATION_RECONCILIATION_VISIBILITY"
_REENTRY = "SUPPLEMENTAL_DISCOVERY_WATCH_REENTRY"
_FAILURE = "RIGHTS_TOMBSTONE_NO_FALSE_SUCCESS_TAMPER_UNAVAILABLE_DEGRADED"
_SERVICE = "ACTUAL_SERVICE_IDENTITY_AUTHENTICATED_TRANSPORT"
_CLOSEOUT = "CLOSED_WORLD_RECEIPT_SIGNED_EXACT_MAIN"


INCREMENT6G_FINAL_CLOSEOUT_CASES = tuple(
    sorted(
        (
            _case(
                "M01_HISTORY",
                _M,
                _D,
                "test_authority_migration_compatibility",
                "test_registry_history_and_statement_pins_are_complete_and_named",
                _MIGRATION,
            ),
            *tuple(
                _case(
                    f"M02_PREDECESSOR_{version}",
                    _M,
                    _D,
                    "test_authority_migration_compatibility",
                    f"test_exact_predecessors_upgrade_to_current[{version}]",
                    _MIGRATION,
                )
                for version in range(13, 25)
            ),
            _case(
                "M03_MULTIHOP",
                _M,
                _D,
                "test_authority_migration_compatibility",
                "test_multihop_upgrade_retains_each_exact_backup_and_digest",
                _MIGRATION,
            ),
            _case(
                "M04_ROLLBACK",
                _M,
                _D,
                "test_authority_migration_compatibility",
                "test_failed_upgrade_rolls_back_to_exact_predecessor",
                _MIGRATION,
            ),
            _case(
                "M05_RESTORE_REUPGRADE",
                _M,
                _D,
                "test_authority_migration_compatibility",
                "test_successful_upgrade_can_restore_exact_backup_then_reupgrade",
                _MIGRATION,
            ),
            _case(
                "W01_CLAIM",
                _W,
                _D,
                "test_increment6b1_execution_store",
                "test_two_connections_converge_on_one_claim_and_reopen_detects_tamper",
                _WORK,
                _HANDOFF,
            ),
            _case(
                "W02_STALE",
                _W,
                _D,
                "test_increment6b1_execution_store",
                "test_different_worker_can_expire_a_stale_work_item_at_the_boundary",
                _WORK,
            ),
            _case(
                "W03_FAIRNESS",
                _W,
                _D,
                "test_increment6b2_scheduling",
                "test_revalidated_starved_routine_gets_next_ordinary_grant_before_fresh_inflow",
                _WORK,
            ),
            _case(
                "W04_DEGRADED_URGENT",
                _W,
                _D,
                "test_increment6b2_scheduling",
                "test_degraded_urgent_is_exact_visible_hold_and_never_downgraded",
                _WORK,
                _FAILURE,
            ),
            _case(
                "P01_MATRIX",
                _P,
                _D,
                "test_increment6c2_dispositions",
                "test_exact_route_outcome_reason_action_matrix_and_cross_route_rejection",
                _PROPOSAL,
            ),
            _case(
                "P02_HOLD",
                _P,
                _D,
                "test_increment6c1_proposals",
                "test_operational_hold_requires_an_inspectable_action_boundary",
                _PROPOSAL,
            ),
            _case(
                "P03_NO_AUTHORITY",
                _P,
                _D,
                "test_increment6c1_proposals",
                "test_content_identity_and_no_authority_boundary_fail_closed",
                _PROPOSAL,
            ),
            _case(
                "H01_CREATE_APPEND",
                _H,
                _D,
                "test_increment6d1_hypotheses",
                "test_version_identity_and_create_append_topology_fail_closed",
                _HYPOTHESIS,
            ),
            _case(
                "H02_RELATIONSHIP",
                _H,
                _D,
                "test_increment6d2_relationships",
                "test_false_merge_split_and_temporal_correction_precedence",
                _HYPOTHESIS,
            ),
            _case(
                "H03_RETAINED",
                _H,
                _D,
                "test_increment6d2_relationship_store",
                "test_retained_receipt_requires_exact_canonical_evidence_and_policy_replay",
                _HYPOTHESIS,
            ),
            _case(
                "L01_CONSOLIDATE",
                _L,
                _D,
                "test_increment6d3_lineage",
                "test_valid_consolidation_consumes_heads_without_mutating_predecessors",
                _LINEAGE,
            ),
            _case(
                "L02_SPLIT",
                _L,
                _D,
                "test_increment6d3_lineage",
                "test_valid_split_and_exact_32_way_pair_coverage_envelope",
                _LINEAGE,
            ),
            _case(
                "L03_REVERSAL",
                _L,
                _D,
                "test_increment6d3_lineage",
                "test_valid_reversal_restores_exact_hypothesis_identities_with_new_versions",
                _LINEAGE,
            ),
            _case(
                "C01_EQUIVALENT_DISTINCT",
                _C,
                _D,
                "test_increment6e2_candidates",
                "test_distinct_and_blocked_collision_results_remain_typed",
                _CANDIDATE,
            ),
            _case(
                "C02_ADMISSION",
                _C,
                _D,
                "test_increment6e2_candidate_authority",
                "test_real_new_candidate_admission_commits_and_exact_replay_skips_providers",
                _CANDIDATE,
                _HANDOFF,
            ),
            _case(
                "C03_COMMIT_RECHECK",
                _C,
                _D,
                "test_increment6e1_collision",
                "test_commit_time_recheck_blocks_current_candidate_drift",
                _CANDIDATE,
            ),
            _case(
                "T01_LOST_DELAYED",
                _T,
                _D,
                "test_increment6f1_handoff_migrations",
                "test_store_correlates_delayed_ack_after_lost_response_and_retry",
                _HANDOFF,
            ),
            _case(
                "T02_AMBIGUOUS",
                _T,
                _D,
                "test_increment6f1_handoffs",
                "test_conflicting_acknowledgement_arrival_orders_remain_ambiguous",
                _HANDOFF,
            ),
            _case(
                "T03_CONCURRENT",
                _T,
                _D,
                "test_increment6f1_handoff_migrations",
                "test_concurrent_replay_allocates_one_logical_handoff_and_attempt",
                _HANDOFF,
            ),
            *tuple(
                _case(
                    f"F01_OBLIGATION_{index:02d}",
                    _F,
                    _D,
                    "test_increment6f2_feedback",
                    "test_every_feedback_reason_creates_one_stable_mandatory_obligation["
                    + suffix
                    + "]",
                    _FEEDBACK,
                )
                for index, suffix in enumerate(
                    (
                        "accepted-intake_accepted-record_intake_acceptance",
                        "inconclusive-insufficient_public_evidence-review_insufficient_public_evidence",
                        "inconclusive-supplemental_discovery_requested-govern_supplemental_discovery",
                        "rejected-candidate_closed-record_candidate_closed",
                        "rejected-duplicate_or_merged_candidate-record_duplicate_or_merge",
                        "rejected-out_of_scope-record_out_of_scope",
                        "rejected-rights_block-record_rights_block",
                        "rejected-stale_candidate-record_stale_candidate",
                    ),
                    start=1,
                )
            ),
            _case(
                "F02_DISPOSITION",
                _F,
                _D,
                "test_increment6f2_feedback",
                "test_disposition_history_is_contiguous_cas_bound_replayable_and_terminal",
                _FEEDBACK,
            ),
            _case(
                "F03_AUTHORITY",
                _F,
                _D,
                "test_increment6f2_feedback_system",
                "test_disposition_is_generic_ledger_anchored_and_replay_precedes_ports",
                _FEEDBACK,
            ),
            _case(
                "R01_WATCH_EXPIRY",
                _R,
                _D,
                "test_increment6a2_work_items",
                "test_watch_reentry_requires_exact_causal_successor_and_matching_condition[EXPIRY-2042-03-14T10:00:00.000000Z]",
                _REENTRY,
            ),
            _case(
                "R01_WATCH_REVIEW",
                _R,
                _D,
                "test_increment6a2_work_items",
                "test_watch_reentry_requires_exact_causal_successor_and_matching_condition[REVIEW-2100-01-01T00:00:00.000000Z]",
                _REENTRY,
            ),
            _case(
                "R02_SUPPLEMENTAL",
                _R,
                _D,
                "test_increment6a2_work_items",
                "test_actual_supplemental_lineage_persists_replays_and_restarts",
                _REENTRY,
            ),
            _case(
                "R03_FEEDBACK_REENTRY",
                _R,
                _D,
                "test_increment6f2_feedback",
                "test_supplemental_fulfilment_requires_exact_governed_reentry",
                _REENTRY,
                _FEEDBACK,
            ),
            _case(
                "X01_RIGHTS",
                _X,
                _D,
                "test_increment6a2_work_items",
                "test_actual_retrieval_journal_is_exact_indexed_and_tamper_or_purge_fails",
                _FAILURE,
            ),
            _case(
                "X02_UNAVAILABLE",
                _X,
                _D,
                "test_increment6e1_collision",
                "test_missing_retained_authority_bytes_fail_closed_as_unavailable",
                _FAILURE,
            ),
            *tuple(
                _case(
                    f"X03_TAMPER_{field.upper()}",
                    _X,
                    _D,
                    "test_increment6f2_feedback_system",
                    "test_retained_namespace_result_and_causation_tamper_fail_closed["
                    + field
                    + "]",
                    _FAILURE,
                )
                for field in ("causation", "namespace", "result")
            ),
            _case(
                "S01_IDENTITY",
                _S,
                _A,
                "test_increment6g_neo4j_service",
                "test_actual_service_increment6g_identity_and_closeout_inventory",
                _SERVICE,
                _CLOSEOUT,
            ),
            _case(
                "S02_AUTH",
                _S,
                _A,
                "test_projection_b2_neo4j_service",
                "test_actual_service_wrong_projector_credential_fails_closed_without_secret",
                _SERVICE,
                _FAILURE,
            ),
            _case(
                "S03_TOMBSTONE",
                _S,
                _A,
                "test_complete_projection_2b_neo4j_service",
                "test_actual_service_revocation_and_tombstone_remove_current_derivatives",
                _SERVICE,
                _FAILURE,
            ),
            _case(
                "Z01_INVENTORY",
                _Z,
                _D,
                "test_increment6g_final_closeout",
                "test_final_closeout_inventory_is_content_addressed_and_exact",
                _CLOSEOUT,
            ),
        ),
        key=lambda item: item.case_id,
    )
)


INCREMENT6G_FINAL_NON_EFFECTS = tuple(
    sorted(
        {
            "EVIDENCE_ACQUISITION",
            "EXTERNAL_EGRESS",
            "LIVE_MODEL_OR_PROVIDER",
            "PRODUCT_AUTHORITY_MUTATION",
            "PRODUCTION_ACTIVATION",
            "PUBLICATION_OR_PUBLIC_EFFECT",
            "SHADOW_OR_CANARY",
        }
    )
)


def _inventory_values() -> list[dict[str, object]]:
    return [case.canonical_value() for case in INCREMENT6G_FINAL_CLOSEOUT_CASES]


INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST = digest_bytes(
    canonical_json_bytes(_inventory_values())
)


def validate_increment6g_final_closeout_inventory() -> None:
    cases = INCREMENT6G_FINAL_CLOSEOUT_CASES
    if not cases or tuple(case.case_id for case in cases) != tuple(
        sorted(case.case_id for case in cases)
    ):
        raise RuntimeError("closeout inventory order differs")
    if len({case.case_id for case in cases}) != len(cases):
        raise RuntimeError("duplicate closeout case identity")
    if len({case.test_id for case in cases}) != len(cases):
        raise RuntimeError("duplicate closeout test identity")
    if {requirement for case in cases for requirement in case.requirements} != (
        INCREMENT6_FINAL_REQUIREMENTS
    ):
        raise RuntimeError("closeout requirements are incomplete")
    if {case.lane for case in cases} != set(Increment6CloseoutLane):
        raise RuntimeError("closeout lanes are incomplete")
    if {case.category for case in cases} != set(Increment6CloseoutCategory):
        raise RuntimeError("closeout categories are incomplete")
    if INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST != digest_bytes(
        canonical_json_bytes(_inventory_values())
    ):
        raise RuntimeError("closeout inventory digest differs")


validate_increment6g_final_closeout_inventory()
