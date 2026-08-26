"""Reviewed immutable identities for issue #790's owner-approved operation."""

from __future__ import annotations

from dataclasses import dataclass

ISSUE_790_APPROVED_PLAN_DIGEST = (
    "sha256:ce7ee7fd56c931b147158dad2a74047ada90b805e5a4c545e53db1f4d2ae7383"
)
ISSUE_790_APPROVED_INVOCATION_ID = (
    "sha256:75f14fd50f54c01c852c557291eb7bb92b05a79c937d10d048bb245863b7a196"
)
ISSUE_790_APPROVED_TERMINAL_DIGEST = (
    "sha256:0c73f6a7ad2255f13bfdb617370f0c935464917e0e80c69b2da216ffca60ee0c"
)
ISSUE_790_APPROVED_ALLOCATION_DIGEST = (
    "sha256:800dd0c6155a34cfafe91c1c240dac2d44730f558be9417d5fe34b5fb23780b2"
)
ISSUE_790_APPROVED_SCOPE = (
    "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION"
)
ISSUE_790_APPROVED_BY = "github:fol2"
ISSUE_790_APPROVAL_REFERENCE = (
    "https://github.com/fol2/newsroom/issues/790#issuecomment-5426599150"
)
ISSUE_790_APPROVED_AT = "2026-08-26T14:12:57.000000Z"
ISSUE_790_APPROVED_TERMINAL_OUTCOME = "FAILED"
ISSUE_790_APPROVED_ROUTE_OPEN_REASON = "SYSTEMIC_TRANSPORT"

ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST = (
    "sha256:3347669cc57fcc3740f9e7027cf7c9c6936626dfb1932eeec5ea2018fe6f6308"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST = (
    "sha256:4db4a7d65e6e43739a048a48aa92162966fd386df6310c437a73846139f5ce42"
)


@dataclass(frozen=True, slots=True)
class Issue790ApprovedPlanContract:
    """Exact identities which reviewed code may turn into one authority row."""

    schema_version: str
    plan_digest: str
    invocation_id: str
    terminal_digest: str
    allocation_digest: str
    approved_by: str
    approval_reference: str
    approved_at: str
    scope: str
    terminal_outcome: str
    route_open_reason: str
    root_plan_digest: str
    predecessor_plan_digest: str | None
    sequence_ordinal: int
    controller_timeout_ms: int
    extraction_timeout_ms: int
    cleanup_reserve_ms: int
    fixed_constraints_digest: str | None
    predecessor_causal_report_digest: str | None
    constraint_change: str | None
    reviewed_fix_digest: str | None


_SUCCESS_SEQUENCE_CONTRACTS = (
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST,
        invocation_id=(
            "sha256:8e219f498ee1eff71cd21c5d9dd3d958e5aed62db8f938b0a2bfdba6d4e9de7d"
        ),
        terminal_digest=(
            "sha256:f5e67d327b215c1eda3a320b07e2cee642151880c5fa275686e8d534646ca9b9"
        ),
        allocation_digest=(
            "sha256:468bc90fb8c9114ca8d4fc780d137f676ce69b453fcfda74bef88e0508a15643"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5430967545"
        ),
        approved_at="2026-08-26T20:51:55.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="TIMEOUT",
        route_open_reason="TIMEOUT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        sequence_ordinal=1,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:a3d6a7759c57df52e0a25feae3edcc740ce7ec26064996aae018b276fd36fbb2"
        ),
        predecessor_causal_report_digest=(
            "sha256:cb1b72361e6f17d02e5f8ecce30d2ff53a79e9334ba942728f58fcf8d977f7f2"
        ),
        constraint_change="INITIAL_QUALIFIED_BASELINE",
        reviewed_fix_digest=None,
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST,
        invocation_id=(
            "sha256:98a2abb90c523af7dd314746039810c07227baef136e70b74887604e052e0ddd"
        ),
        terminal_digest=(
            "sha256:78aaae4b8717ecb691a2b63564425ac8fe9fe84dc7742059104e47801b13e91e"
        ),
        allocation_digest=(
            "sha256:203659ac4f8399b5810657425a0f4fde77220e6daf3b07eed456e2cf9a3385bd"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5430967545"
        ),
        approved_at="2026-08-26T20:51:55.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST,
        sequence_ordinal=2,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:a3d6a7759c57df52e0a25feae3edcc740ce7ec26064996aae018b276fd36fbb2"
        ),
        predecessor_causal_report_digest=(
            "sha256:0f06ffa65fc95a8e3278fccc92eed8dc23cebf5517a722d74bce14c73e2984a8"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:1bfba70f2f88eec47da9d8329030239c316cdc995b519c929fe074dcb9b14e32"
        ),
    ),
)


def issue_790_approved_plan_contract(
    plan_digest: str,
) -> Issue790ApprovedPlanContract:
    """Return the exact reviewed contract, including the legacy first plan."""

    if plan_digest == ISSUE_790_APPROVED_PLAN_DIGEST:
        # Keep these aliases live so fixture tests can bind one exact synthetic plan
        # without broadening the production registry.
        return Issue790ApprovedPlanContract(
            schema_version="newsroom.issue-790.conservative-disposition-plan.v1",
            plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
            invocation_id=ISSUE_790_APPROVED_INVOCATION_ID,
            terminal_digest=ISSUE_790_APPROVED_TERMINAL_DIGEST,
            allocation_digest=ISSUE_790_APPROVED_ALLOCATION_DIGEST,
            approved_by=ISSUE_790_APPROVED_BY,
            approval_reference=ISSUE_790_APPROVAL_REFERENCE,
            approved_at=ISSUE_790_APPROVED_AT,
            scope=ISSUE_790_APPROVED_SCOPE,
            terminal_outcome=ISSUE_790_APPROVED_TERMINAL_OUTCOME,
            route_open_reason=ISSUE_790_APPROVED_ROUTE_OPEN_REASON,
            root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
            predecessor_plan_digest=None,
            sequence_ordinal=0,
            controller_timeout_ms=80_000,
            extraction_timeout_ms=180_000,
            cleanup_reserve_ms=20_000,
            fixed_constraints_digest=None,
            predecessor_causal_report_digest=None,
            constraint_change=None,
            reviewed_fix_digest=None,
        )
    for contract in _SUCCESS_SEQUENCE_CONTRACTS:
        if contract.plan_digest == plan_digest:
            return contract
    raise KeyError(plan_digest)


def issue_790_approved_plan_contracts() -> tuple[Issue790ApprovedPlanContract, ...]:
    """Return every exact plan-to-target binding embedded by reviewed code."""

    return (
        issue_790_approved_plan_contract(ISSUE_790_APPROVED_PLAN_DIGEST),
        *_SUCCESS_SEQUENCE_CONTRACTS,
    )

__all__ = [
    "ISSUE_790_APPROVAL_REFERENCE",
    "ISSUE_790_APPROVED_ALLOCATION_DIGEST",
    "ISSUE_790_APPROVED_AT",
    "ISSUE_790_APPROVED_BY",
    "ISSUE_790_APPROVED_INVOCATION_ID",
    "ISSUE_790_APPROVED_PLAN_DIGEST",
    "ISSUE_790_APPROVED_SCOPE",
    "ISSUE_790_APPROVED_TERMINAL_DIGEST",
    "ISSUE_790_APPROVED_TERMINAL_OUTCOME",
    "ISSUE_790_APPROVED_ROUTE_OPEN_REASON",
    "ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST",
    "Issue790ApprovedPlanContract",
    "issue_790_approved_plan_contract",
    "issue_790_approved_plan_contracts",
]
