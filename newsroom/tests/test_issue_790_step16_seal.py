"""#790 Step 16 checked sealing path. Output remains non-executable for live apply."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_contract as issue_790_contract_module
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PENDING_PLAN_PATH,
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    Issue790DispositionError,
    _require_approved_plan,
    issue_790_step16_checked_approval,
    seal_issue_790_step16_plan,
    validate_issue_790_plan,
)

_ROOT = Path(__file__).resolve().parents[2]


def _pending_family() -> tuple[dict[str, object], dict[str, object]]:
    pending = json.loads((_ROOT / ISSUE_790_STEP16_PENDING_PLAN_PATH).read_text())
    pre_dispatch = json.loads((_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text())
    return pending, pre_dispatch


def _seal() -> dict[str, object]:
    pending, pre_dispatch = _pending_family()
    return seal_issue_790_step16_plan(
        pending,
        issue_790_step16_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=pre_dispatch,
    )


def _resign(plan: dict[str, object]) -> dict[str, object]:
    unsigned = {key: item for key, item in plan.items() if key != "canonical_digest"}
    plan["canonical_digest"] = digest_canonical(unsigned)
    return plan


def test_checked_step16_seal_passes_validator_and_contract() -> None:
    pending, _pre_dispatch = _pending_family()
    assert pending["executable"] is False
    plan = _seal()
    validate_issue_790_plan(plan)
    bound = _require_approved_plan(plan)
    contract = issue_790_contract_module.issue_790_approved_plan_contract(
        plan["canonical_digest"]
    )
    assert plan["canonical_digest"] == (
        issue_790_contract_module.ISSUE_790_SUCCESS_SEQUENCE_STEP_16_PLAN_DIGEST
    )
    assert bound["sequence"]["sequence_ordinal"] == 16
    assert contract.sequence_ordinal == 16
    assert contract.predecessor_plan_digest == (
        issue_790_contract_module.ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST
    )
    assert contract.projection_policy_digest == plan["sequence"][
        "projection_policy_digest"
    ]
    assert contract.pre_dispatch_operational_requirements_digest == plan["sequence"][
        "pre_dispatch_operational_requirements_digest"
    ]
    assert contract.reviewed_fix_digest == plan["sequence"]["reviewed_fix"][
        "record_digest"
    ]
    assert pending["executable"] is False
    assert "executable" not in plan


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda plan: plan["target"].__setitem__(
                "invocation_id", "sha256:" + "ab" * 32
            ),
            "approved plan",
        ),
        (
            lambda plan: plan.__setitem__("retry_forbidden_events", []),
            "retry exclusions",
        ),
        (
            lambda plan: plan["sequence"]["reviewed_fix"].__setitem__(
                "record_digest", "sha256:" + "cd" * 32
            ),
            "reviewed fix",
        ),
        (
            lambda plan: plan["sequence"].__setitem__(
                "projection_policy_digest", "sha256:" + "ef" * 32
            ),
            "identity fields",
        ),
        (
            lambda plan: plan["sequence"].__setitem__(
                "pre_dispatch_operational_requirements_digest",
                "sha256:" + "11" * 32,
            ),
            "approved plan identity",
        ),
        (
            lambda plan: plan["sequence"]["predecessor"].__setitem__(
                "plan_digest", "sha256:" + "22" * 32
            ),
            "predecessor identity",
        ),
    ],
)
def test_checked_step16_seal_rejects_changed_identities(mutator, match: str) -> None:
    plan = _seal()
    mutator(plan)
    resigned = _resign(plan)
    with pytest.raises(Issue790DispositionError, match=match):
        _require_approved_plan(resigned)


def test_sealer_rejects_changed_pre_dispatch_family() -> None:
    pending, pre_dispatch = _pending_family()
    pre_dispatch = dict(pre_dispatch)
    pre_dispatch["exact_main_commit"] = "0" * 40
    body = {
        key: item for key, item in pre_dispatch.items() if key != "requirements_digest"
    }
    pre_dispatch["requirements_digest"] = digest_canonical(body)
    with pytest.raises(Issue790DispositionError, match="pre-dispatch identity"):
        seal_issue_790_step16_plan(
            pending,
            issue_790_step16_checked_approval(str(pending["canonical_digest"])),
            pre_dispatch=pre_dispatch,
        )
