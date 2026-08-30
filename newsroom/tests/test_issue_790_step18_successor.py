"""#790 Step 18 binds the checked event after Step 17's pre-consumption stop."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_contract as contract_module
from newsroom.control_plane.issue_790_canary import (
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP18_PENDING_PLAN_PATH,
    Issue790DispositionError,
    _require_sequence_predecessor,
    activate_issue_790_step16_plan,
    issue_790_checked_approval,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_plan,
    validate_issue_790_step16_candidate,
)
from newsroom.tests.test_issue_790_step16_activation import (
    _COMMENT_ID,
    _FakeGitHub,
    _comment,
    _payload,
)
from newsroom.tests.test_issue_790_step17_successor import _pre_dispatch

_ROOT = Path(__file__).resolve().parents[2]
_EVENT_8834 = (
    "sha256:cac05a3829b4283a12330c38b7ea3e4d1e998024e4b3ed2e73508c476996a04b"
)
_EVENT_13284 = (
    "sha256:fb49a59d1c421c261bab4586873680e50e8181acfd0d6ebc03a14f889147d896"
)


def _seal18() -> dict[str, object]:
    pending = json.loads((_ROOT / ISSUE_790_STEP18_PENDING_PLAN_PATH).read_text())
    return seal_issue_790_step16_plan(
        pending,
        issue_790_checked_approval(str(pending["canonical_digest"])),
        pre_dispatch=_pre_dispatch(),
    )


def _activate18_with_predecessor(tmp_path: Path) -> dict[str, object]:
    candidate = _seal18()
    comment_id = _COMMENT_ID + 18
    payload = _payload(candidate, final_correction_pr=850)
    comment = _comment(payload)
    comment["id"] = comment_id
    comment["html_url"] = (
        f"https://github.com/fol2/newsroom/issues/790#issuecomment-{comment_id}"
    )
    comment["url"] = (
        "https://api.github.com/repos/fol2/newsroom/issues/comments/"
        f"{comment_id}"
    )
    github_api = _FakeGitHub(comment)
    store = tmp_path / "authority.sqlite"
    activated = activate_issue_790_step16_plan(
        candidate,
        comment_id=comment_id,
        pre_dispatch=_pre_dispatch(),
        store=store,
        github_api=github_api,
    )
    return {**activated, "store": store, "candidate": candidate, "github_api": github_api}


def test_step18_is_a_new_non_executable_candidate_bound_to_exact_event() -> None:
    candidate = _seal18()
    validate_issue_790_step16_candidate(candidate)
    assert candidate["canonical_digest"] == (
        contract_module.ISSUE_790_STEP18_CHECKED_CANDIDATE_DIGEST
    )
    assert candidate["canonical_digest"] != (
        contract_module.ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST
    )
    sequence = candidate["sequence"]
    assert isinstance(sequence, dict)
    assert sequence["sequence_ordinal"] == 18
    assert sequence["predecessor"]["plan_digest"] == (
        contract_module.ISSUE_790_STEP17_ACTIVATED_PLAN_DIGEST
    )
    assert sequence["predecessor_activation_digest"] == (
        contract_module.ISSUE_790_STEP17_ACTIVATION_DIGEST
    )
    qualification = sequence["candidate_event_qualification"]
    assert qualification["event_id"] == _EVENT_13284
    assert qualification["ledger_seq"] == 13284
    assert qualification["provider_calls"] == 0
    assert qualification["store_mutations"] == 0
    assert candidate["executable"] is False
    assert candidate["live_canary_authorised"] is False


def test_step18_activation_accepts_exhausted_step17_without_fake_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated = _activate18_with_predecessor(tmp_path)
    plan = activated["plan"]
    validate_issue_790_plan(plan)
    assert plan["sequence"]["sequence_ordinal"] == 18
    repository = Issue790CanaryRepository.open_existing(str(activated["store"]))
    monkeypatch.setattr(
        "newsroom.control_plane.issue_790_disposition."
        "step16_activation_module.load_step16_activation_record",
        lambda _connection, *, plan_digest: {
            "activation_digest": contract_module.ISSUE_790_STEP17_ACTIVATION_DIGEST,
            "checked_candidate_digest": (
                contract_module.ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST
            ),
            "plan_digest": plan_digest,
        },
    )
    predecessor = _require_sequence_predecessor(repository, plan=plan)
    assert predecessor is not None
    assert predecessor["activation"]["activation_digest"] == (
        contract_module.ISSUE_790_STEP17_ACTIVATION_DIGEST
    )
    assert predecessor["gate_outcome"]["authority_consumed"] is False
    assert repository.existing_consumption(
        approved_plan_digest=contract_module.ISSUE_790_STEP17_ACTIVATED_PLAN_DIGEST
    ) is None


def test_step18_plan_rejects_candidate_or_gate_drift(tmp_path: Path) -> None:
    plan = _activate18_with_predecessor(tmp_path)["plan"]
    qualification = plan["sequence"]["candidate_event_qualification"]
    qualification["event_id"] = "sha256:" + "ab" * 32
    plan["canonical_digest"] = digest_canonical(
        {key: item for key, item in plan.items() if key != "canonical_digest"}
    )
    with pytest.raises(Issue790DispositionError, match="candidate qualification"):
        validate_issue_790_plan(plan)


def test_step18_live_entry_rejects_any_other_event_before_io(tmp_path: Path) -> None:
    activated = _activate18_with_predecessor(tmp_path)
    with pytest.raises(
        Issue790DispositionError,
        match="bounded canary candidate identity differs",
    ):
        run_issue_790_canary(
            store=activated["store"],
            proving_store=tmp_path / "unused-proving.sqlite3",
            backup_path=tmp_path / "unused-backup.sqlite3",
            plan=activated["plan"],
            observed_at=datetime(2026, 8, 30, 7, tzinfo=UTC),
            repository_root=_ROOT,
            event_id="sha256:" + "ab" * 32,
            ledger_seq=13285,
            disposition_digest="sha256:" + "cd" * 32,
            github_api=activated["github_api"],
        )


def test_step17_target_is_now_durably_retry_forbidden(tmp_path: Path) -> None:
    store = tmp_path / "canary.sqlite"
    repository = Issue790CanaryRepository(str(store))
    with pytest.raises(Issue790CanaryIntegrityError, match="retained failure"):
        repository.consume(
            approved_plan_digest="sha256:" + "ab" * 32,
            disposition_digest="sha256:" + "cd" * 32,
            event_id=_EVENT_8834,
            ledger_seq=8834,
            owner_id="issue-790-canary:test",
            preflight_evidence={},
            consumed_at=datetime(2026, 8, 30, tzinfo=UTC),
        )
