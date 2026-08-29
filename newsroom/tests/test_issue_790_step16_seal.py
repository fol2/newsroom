"""#790 Step 16 checked candidate is not live authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_contract as issue_790_contract_module
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PENDING_PLAN_PATH,
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    Issue790DispositionError,
    _require_approved_plan,
    _require_step16_code_identity,
    _require_step16_runtime_semantics,
    apply_issue_790_plan,
    finalise_issue_790_step16_plan,
    issue_790_step16_checked_approval,
    load_issue_790_plan,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_plan,
    validate_issue_790_step16_candidate,
)

_ROOT = Path(__file__).resolve().parents[2]
_REVOKED_CHECKED_LIVE_PLAN_DIGEST = (
    "sha256:72723b72b71f12fee2a9ec31c2b4145e5cbac4ac55f8ddbc51319248e94c21f9"
)


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


def _resign_candidate(candidate: dict[str, object]) -> dict[str, object]:
    unsigned = {
        key: item for key, item in candidate.items() if key != "canonical_digest"
    }
    candidate["canonical_digest"] = digest_canonical(unsigned)
    return candidate


def _owner_tuple(*, revision: str, tree: str) -> dict[str, str]:
    return {
        "approved_by": "github:fol2",
        "approval_reference": (
            "https://github.com/fol2/newsroom/issues/790#issuecomment-1"
        ),
        "approved_at": "2026-08-29T00:00:00.000000Z",
        "scope": "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION",
        "reviewed_correction_revision": revision,
        "reviewed_correction_tree": tree,
    }


def test_checked_step16_candidate_is_seal_proof_not_live_authority() -> None:
    pending, _pre_dispatch = _pending_family()
    assert pending["executable"] is False
    candidate = _seal()
    validate_issue_790_step16_candidate(candidate)
    assert candidate["canonical_digest"] == (
        issue_790_contract_module.ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST
    )
    assert candidate["executable"] is False
    assert candidate["live_canary_authorised"] is False
    assert candidate["plan_status"] == "CHECKED_CANDIDATE"
    assert "NO_LIVE_CANARY_WITHOUT_OWNER_APPROVAL" in candidate["non_effects"]
    contract = issue_790_contract_module.issue_790_checked_candidate_contract(
        candidate["canonical_digest"]
    )
    assert contract.sequence_ordinal == 16
    assert contract.pending_digest == pending["canonical_digest"]
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        _require_approved_plan(candidate)
    with pytest.raises(Issue790DispositionError, match="plan fields differ"):
        validate_issue_790_plan(candidate)
    with pytest.raises(KeyError):
        issue_790_contract_module.issue_790_approved_plan_contract(
            candidate["canonical_digest"]
        )
    with pytest.raises(KeyError):
        issue_790_contract_module.issue_790_approved_plan_contract(
            _REVOKED_CHECKED_LIVE_PLAN_DIGEST
        )


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda plan: plan["target"].__setitem__(
                "invocation_id", "sha256:" + "ab" * 32
            ),
            "candidate",
        ),
        (
            lambda plan: plan.__setitem__("retry_forbidden_events", []),
            "candidate",
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
            "candidate",
        ),
        (
            lambda plan: plan["sequence"].__setitem__(
                "pre_dispatch_operational_requirements_digest",
                "sha256:" + "11" * 32,
            ),
            "candidate",
        ),
        (
            lambda plan: plan["sequence"]["predecessor"].__setitem__(
                "plan_digest", "sha256:" + "22" * 32
            ),
            "candidate",
        ),
    ],
)
def test_checked_step16_candidate_rejects_changed_identities(
    mutator, match: str
) -> None:
    candidate = _seal()
    mutator(candidate)
    resigned = _resign_candidate(candidate)
    with pytest.raises(Issue790DispositionError, match=match):
        validate_issue_790_step16_candidate(resigned)


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


def test_in_memory_and_materialised_checked_candidate_cannot_apply_or_canary(
    tmp_path: Path,
) -> None:
    candidate = _seal()
    path = tmp_path / "checked-candidate.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    observed_at = datetime(2026, 8, 29, tzinfo=UTC)
    store = tmp_path / "store.sqlite"
    proving = tmp_path / "proving.sqlite"
    backup = tmp_path / "backup.sqlite"
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        load_issue_790_plan(path)
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        apply_issue_790_plan(
            store=store,
            backup_path=backup,
            plan=candidate,
            observed_at=observed_at,
            repository_root=tmp_path,
        )
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        run_issue_790_canary(
            store=store,
            proving_store=proving,
            backup_path=backup,
            plan=json.loads(path.read_text(encoding="utf-8")),
            observed_at=observed_at,
            repository_root=tmp_path,
            event_id="sha256:" + "aa" * 32,
            ledger_seq=1,
            disposition_digest="sha256:" + "bb" * 32,
        )


def test_owner_finalise_is_not_live_registered_and_binds_named_main() -> None:
    pending, pre_dispatch = _pending_family()
    candidate = _seal()
    revision = "a" * 40
    tree = "b" * 40
    plan = finalise_issue_790_step16_plan(
        candidate,
        _owner_tuple(revision=revision, tree=tree),
        pre_dispatch=pre_dispatch,
    )
    assert plan["approval"]["approved_by"] == "github:fol2"
    assert plan["sequence"]["reviewed_correction_revision"] == revision
    assert plan["sequence"]["reviewed_correction_tree"] == tree
    assert plan["sequence"]["pre_dispatch_operational_requirements"][
        "exact_main_commit"
    ] == revision
    with pytest.raises(Issue790DispositionError, match="activation store is absent"):
        _require_approved_plan(plan)
    evidence = {
        "revision": revision,
        "tree": tree,
        "github_main_revision": revision,
        "worker": {
            "label": "com.jamesto.newsroom-graphiti-worker",
            "launchctl_loaded": False,
            "process_ids": [],
        },
        "store_quick_check": "ok",
        "ci_test": {
            "name": "focus-gates",
            "status": "completed",
            "conclusion": "success",
            "head_sha": revision,
            "url": "https://github.com/fol2/newsroom/actions/runs/1/job/1",
        },
    }
    _require_step16_code_identity(plan, evidence=evidence)
    observed_at = datetime(2026, 8, 29, tzinfo=UTC)
    _require_step16_runtime_semantics(
        plan,
        evidence=evidence,
        route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
        circuit_state={
            "state": "CLOSED",
            "opened_at": None,
            "available_at": None,
            "failure_code": None,
        },
        observed_at=observed_at,
        canary_event={
            "event_id": "sha256:" + "aa" * 32,
            "ledger_seq": 2000,
            "state": "QUEUED",
            "attempt_count": 0,
            "provider_dispatched": False,
            "claim_owner": None,
            "claim_expires_at": None,
            "terminal_at": None,
            "available_at": "2026-08-28T00:00:00.000000Z",
        },
    )
    drifted = dict(evidence)
    drifted["revision"] = "c" * 40
    drifted["github_main_revision"] = "c" * 40
    with pytest.raises(Issue790DispositionError, match="reviewed correction identity"):
        _require_step16_code_identity(plan, evidence=drifted)


def test_owner_finalise_rejects_checked_tuple() -> None:
    pending, pre_dispatch = _pending_family()
    candidate = _seal()
    checked = issue_790_step16_checked_approval(str(pending["canonical_digest"]))
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        finalise_issue_790_step16_plan(
            candidate,
            {
                **checked,
                "reviewed_correction_revision": "a" * 40,
                "reviewed_correction_tree": "b" * 40,
            },
            pre_dispatch=pre_dispatch,
        )


def test_owner_finalise_rejects_changed_pre_dispatch_family() -> None:
    _pending, pre_dispatch = _pending_family()
    candidate = _seal()
    pre_dispatch = dict(pre_dispatch)
    pre_dispatch["exact_main_commit"] = "0" * 40
    body = {
        key: item for key, item in pre_dispatch.items() if key != "requirements_digest"
    }
    pre_dispatch["requirements_digest"] = digest_canonical(body)
    with pytest.raises(Issue790DispositionError, match="pre-dispatch identity"):
        finalise_issue_790_step16_plan(
            candidate,
            _owner_tuple(revision="a" * 40, tree="b" * 40),
            pre_dispatch=pre_dispatch,
        )
