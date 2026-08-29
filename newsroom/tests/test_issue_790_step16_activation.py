"""#790 Step 16 owner-activation is authenticated and not source-registered."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_contract as issue_790_contract_module
from newsroom.control_plane.issue_790_canary import Issue790CanaryRepository
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PENDING_PLAN_PATH,
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    Issue790DispositionError,
    _require_approved_plan,
    _require_step16_event_circuit,
    _require_step16_runtime_semantics,
    activate_issue_790_step16_plan,
    apply_issue_790_plan,
    finalise_issue_790_step16_plan,
    issue_790_step16_checked_approval,
    load_issue_790_plan,
    qualify_issue_790_step16_readiness,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_plan,
    validate_issue_790_step16_candidate,
)
from newsroom.control_plane.issue_790_step16_activation import (
    ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    ISSUE_790_STEP16_READINESS_STATUS,
    canonical_step16_owner_approval_comment_body,
    effective_issue_790_plan_contract,
)
from newsroom.graphiti_adapter.combined_temporal_projection import (
    PROJECTION_POLICY_DIGEST,
    PROJECTION_POLICY_VERSION,
)
from newsroom.graphiti_adapter.combined_temporal_validation import (
    VALIDATOR_CONTRACT_VERSION,
)
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

_ROOT = Path(__file__).resolve().parents[2]
_REVOKED = (
    issue_790_contract_module.ISSUE_790_STEP16_REVOKED_CHECKED_LIVE_PLAN_DIGEST
)
_NON_EFFECTS = [
    "NO_PUBLICATION",
    "NO_PUBLIC_DISPATCH",
    "NO_BACKLOG_DRAIN",
    "NO_BULK_REQUEUE",
    "NO_PRODUCTION_OPERATIONAL_ADMISSION",
    "NO_WIDER_ACTIVATION",
    "NO_PROVIDER_SUBSTITUTION",
    "NO_MODEL_SUBSTITUTION",
    "NO_TOKEN_LIMIT_REMOVAL",
    "NO_UNRELATED_SPEND_DISPOSITION",
]
_COMMENT_ID = 5459000001
_NODE_ID = "IC_kwDOSTEP16ACTIVATION"
_RUN_ID = 33220999999
_REVISION = "a" * 40
_TREE = "b" * 40
_HEAD = "c" * 40
_HEAD_TREE = "d" * 40
_OBSERVED = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


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


def _payload(candidate: dict[str, object], **overrides: object) -> dict[str, object]:
    sequence = candidate["sequence"]
    payload: dict[str, object] = {
        "schema_version": issue_790_contract_module.ISSUE_790_STEP16_OWNER_APPROVAL_SCHEMA,
        "issue": 790,
        "checked_candidate_digest": candidate["canonical_digest"],
        "final_main_commit": _REVISION,
        "final_main_tree": _TREE,
        "final_correction_pr": 845,
        "reviewed_head_commit": _HEAD,
        "reviewed_head_tree": _HEAD_TREE,
        "focus_gate_run_url": (
            f"https://github.com/fol2/newsroom/actions/runs/{_RUN_ID}"
        ),
        "focus_gate_run_id": _RUN_ID,
        "focus_gate_manifest_digest": "sha256:" + "ef" * 32,
        "feature_complete_review_receipt": "sha256:" + "cd" * 32,
        "projection_policy_version": PROJECTION_POLICY_VERSION,
        "projection_policy_digest": PROJECTION_POLICY_DIGEST,
        "temporal_policy_version": TEMPORAL_POLICY_VERSION,
        "validator_contract_version": VALIDATOR_CONTRACT_VERSION,
        "call_shape_policy_version": sequence["call_shape_policy_version"],
        "call_shape_policy_digest": sequence["call_shape_policy_digest"],
        "pre_dispatch_policy_digest": sequence[
            "pre_dispatch_operational_requirements_digest"
        ],
        "catalogue_query_cap": 1,
        "fresh_event_cap": 1,
        "provider_dispatch_cap": 1,
        "retry_cap": 0,
        "fallback_cap": 0,
        "backlog_drain_cap": 0,
        "bulk_requeue_cap": 0,
        "publication_cap": 0,
        "stop_condition": "FIRST_TRUTHFUL_PROVIDER_BACKED_SUCCESS",
        "non_effects": list(_NON_EFFECTS),
        "event_circuit_policy": ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        "activation_policy_version": (
            issue_790_contract_module.ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION
        ),
    }
    payload.update(overrides)
    return payload


def _comment(payload: dict[str, object], **overrides: object) -> dict[str, object]:
    body = canonical_step16_owner_approval_comment_body(payload)
    comment: dict[str, object] = {
        "id": _COMMENT_ID,
        "node_id": _NODE_ID,
        "html_url": (
            f"https://github.com/fol2/newsroom/issues/790#issuecomment-{_COMMENT_ID}"
        ),
        "url": (
            "https://api.github.com/repos/fol2/newsroom/issues/comments/"
            f"{_COMMENT_ID}"
        ),
        "issue_url": "https://api.github.com/repos/fol2/newsroom/issues/790",
        "user": {"login": "fol2"},
        "author_association": "OWNER",
        "created_at": "2026-08-29T12:00:00Z",
        "updated_at": "2026-08-29T12:00:00Z",
        "body": body,
    }
    comment.update(overrides)
    return comment


def _workflow_run(**overrides: object) -> dict[str, object]:
    run: dict[str, object] = {
        "id": _RUN_ID,
        "html_url": f"https://github.com/fol2/newsroom/actions/runs/{_RUN_ID}",
        "head_sha": _REVISION,
        "path": ".github/workflows/focus-gates.yml",
        "name": "Focus Gates",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "updated_at": "2026-08-29T11:00:00Z",
    }
    run.update(overrides)
    return run


class _FakeGitHub:
    def __init__(
        self,
        comment: dict[str, object],
        workflow_run: dict[str, object] | None = None,
    ) -> None:
        self.comment = comment
        self.workflow_run = workflow_run if workflow_run is not None else _workflow_run()
        self.calls: list[str] = []

    def __call__(self, resource: str) -> dict[str, object]:
        self.calls.append(resource)
        if resource.startswith("repos/fol2/newsroom/issues/comments/"):
            return self.comment
        if resource == (
            f"repos/fol2/newsroom/actions/runs/{self.workflow_run['id']}"
        ):
            return self.workflow_run
        raise Issue790DispositionError("issue #790 GitHub evidence is unavailable")


def _activate(tmp_path: Path, **comment_overrides: object) -> dict[str, object]:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    github = _FakeGitHub(_comment(payload, **comment_overrides))
    store = tmp_path / "authority.sqlite"
    return activate_issue_790_step16_plan(
        candidate,
        comment_id=_COMMENT_ID,
        pre_dispatch=pre_dispatch,
        store=store,
        github_api=github,
    ) | {"store": store, "github": github, "candidate": candidate}


def _closed_circuit() -> dict[str, object]:
    return {
        "state": "CLOSED",
        "opened_at": None,
        "available_at": None,
        "failure_code": None,
    }


def _ready_event() -> dict[str, object]:
    return {
        "event_id": "sha256:" + "aa" * 32,
        "ledger_seq": 2000,
        "state": "QUEUED",
        "attempt_count": 0,
        "provider_dispatched": False,
        "claim_owner": None,
        "claim_expires_at": None,
        "terminal_at": None,
        "available_at": "2026-08-28T00:00:00.000000Z",
    }


def _evidence() -> dict[str, object]:
    return {
        "revision": _REVISION,
        "tree": _TREE,
        "github_main_revision": _REVISION,
        "store_quick_check": "ok",
        "worker": {
            "label": "com.jamesto.newsroom-graphiti-worker",
            "launchctl_loaded": False,
            "process_ids": [],
        },
        "ci_test": {
            "name": "focus-gates",
            "status": "completed",
            "conclusion": "success",
            "head_sha": _REVISION,
            "url": f"https://github.com/fol2/newsroom/actions/runs/{_RUN_ID}/job/1",
        },
    }


def test_checked_candidate_still_fails_every_live_gate(tmp_path: Path) -> None:
    candidate = _seal()
    validate_issue_790_step16_candidate(candidate)
    path = tmp_path / "checked.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        _require_approved_plan(candidate)
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        load_issue_790_plan(path)
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        apply_issue_790_plan(
            store=tmp_path / "store.sqlite",
            backup_path=tmp_path / "backup.sqlite",
            plan=json.loads(path.read_text(encoding="utf-8")),
            observed_at=_OBSERVED,
            repository_root=tmp_path,
        )
    with pytest.raises(Issue790DispositionError, match="checked approval is not live"):
        run_issue_790_canary(
            store=tmp_path / "store.sqlite",
            proving_store=tmp_path / "proving.sqlite",
            backup_path=tmp_path / "backup.sqlite",
            plan=candidate,
            observed_at=_OBSERVED,
            repository_root=tmp_path,
            event_id="sha256:" + "aa" * 32,
            ledger_seq=2000,
            disposition_digest="sha256:" + "bb" * 32,
        )
    with pytest.raises(KeyError):
        issue_790_contract_module.issue_790_approved_plan_contract(
            candidate["canonical_digest"]
        )


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda comment: comment.__setitem__("user", {"login": "not-fol2"}), "owner comment"),
        (
            lambda comment: comment.__setitem__("author_association", "MEMBER"),
            "owner comment",
        ),
        (
            lambda comment: comment.__setitem__(
                "issue_url",
                "https://api.github.com/repos/fol2/newsroom/issues/791",
            ),
            "owner comment",
        ),
        (
            lambda comment: comment.__setitem__(
                "html_url",
                f"https://github.com/other/newsroom/issues/790#issuecomment-{_COMMENT_ID}",
            ),
            "owner comment",
        ),
        (
            lambda comment: comment.__setitem__("id", _COMMENT_ID + 1),
            "owner comment",
        ),
        (
            lambda comment: comment.__setitem__("updated_at", "2026-08-29T12:01:00Z"),
            "edited",
        ),
        (
            lambda comment: (
                comment.__setitem__("created_at", "2026-08-29T10:00:00Z"),
                comment.__setitem__("updated_at", "2026-08-29T10:00:00Z"),
            ),
            "precedes reviewed evidence",
        ),
    ],
)
def test_owner_comment_authentication_fails_closed(
    tmp_path: Path,
    mutator,
    match: str,
) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    comment = _comment(payload)
    mutator(comment)
    store = tmp_path / "authority.sqlite"
    with pytest.raises(Issue790DispositionError, match=match):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=_FakeGitHub(comment),
        )


def test_unavailable_github_comment_is_hold(tmp_path: Path) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    store = tmp_path / "authority.sqlite"

    def _missing(_resource: str) -> dict[str, object]:
        raise RuntimeError("network down")

    with pytest.raises(Issue790DispositionError, match="GitHub evidence is unavailable"):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=_missing,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", ".github/workflows/evidence.yml"),
        ("name", "Full Repository Health"),
        ("event", "push"),
    ],
)
def test_focus_gate_workflow_identity_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    store = tmp_path / "authority.sqlite"
    with pytest.raises(Issue790DispositionError, match="focus gate"):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=_FakeGitHub(_comment(payload), _workflow_run(**{field: value})),
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("checked_candidate_digest", "sha256:" + "11" * 32, "payload"),
        ("final_main_commit", "e" * 40, "focus gate"),
        ("catalogue_query_cap", 2, "caps"),
        ("retry_cap", 1, "caps"),
        ("stop_condition", "KEEP_GOING", "payload"),
        ("publication_cap", 1, "caps"),
        ("focus_gate_run_id", 1, "payload"),
        (
            "non_effects",
            [
                "NO_PUBLICATION",
                "NO_PUBLIC_DISPATCH",
                "NO_BACKLOG_DRAIN",
                "NO_BULK_REQUEUE",
                "NO_PRODUCTION_OPERATIONAL_ADMISSION",
                "NO_WIDER_ACTIVATION",
                "NO_PROVIDER_SUBSTITUTION",
                "NO_MODEL_SUBSTITUTION",
                "NO_TOKEN_LIMIT_REMOVAL",
            ],
            "payload",
        ),
    ],
)
def test_owner_payload_identity_and_caps_fail_closed(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate, **{field: value})
    store = tmp_path / "authority.sqlite"
    with pytest.raises(Issue790DispositionError, match=match):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=_FakeGitHub(_comment(payload)),
        )


def test_activation_is_idempotent_and_not_source_registered(tmp_path: Path) -> None:
    first = _activate(tmp_path)
    second = activate_issue_790_step16_plan(
        first["candidate"],
        comment_id=_COMMENT_ID,
        pre_dispatch=json.loads(
            (_ROOT / ISSUE_790_STEP16_PRE_DISPATCH_PATH).read_text()
        ),
        store=first["store"],
        github_api=first["github"],
    )
    plan = first["plan"]
    activation = first["activation"]
    assert second["activation"]["activation_digest"] == activation["activation_digest"]
    assert second["plan"]["canonical_digest"] == plan["canonical_digest"]
    assert plan["sequence"]["owner_activation"]["checked_candidate_digest"] == (
        issue_790_contract_module.ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST
    )
    assert plan["sequence"]["reviewed_correction_revision"] == _REVISION
    with pytest.raises(KeyError):
        issue_790_contract_module.issue_790_approved_plan_contract(
            plan["canonical_digest"]
        )
    assert plan["canonical_digest"] not in {
        contract.plan_digest
        for contract in issue_790_contract_module.issue_790_approved_plan_contracts()
    }
    connection = Issue790CanaryRepository(str(first["store"]))._connection()
    try:
        resolved = effective_issue_790_plan_contract(
            plan["canonical_digest"],
            connection=connection,
        )
    finally:
        connection.close()
    assert resolved.sequence_ordinal == 16
    assert resolved.plan_digest == plan["canonical_digest"]
    _require_approved_plan(
        plan,
        store=first["store"],
        github_api=first["github"],
    )


def test_contradictory_activation_fails_closed(tmp_path: Path) -> None:
    first = _activate(tmp_path)
    forged = dict(first["activation"])
    forged["plan_digest"] = "sha256:" + "99" * 32
    unsigned = {key: item for key, item in forged.items() if key != "activation_digest"}
    forged["activation_digest"] = digest_canonical(unsigned)
    repository = Issue790CanaryRepository(str(first["store"]))
    with pytest.raises(Exception, match="contradicts retained evidence"):
        repository.retain_step16_activation(forged)


def test_final_plan_without_activation_fails_load_apply_canary(tmp_path: Path) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    plan = finalise_issue_790_step16_plan(
        candidate,
        {
            "approved_by": "github:fol2",
            "approval_reference": (
                "https://github.com/fol2/newsroom/issues/790#issuecomment-1"
            ),
            "approved_at": "2026-08-29T00:00:00.000000Z",
            "scope": "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION",
            "reviewed_correction_revision": _REVISION,
            "reviewed_correction_tree": _TREE,
        },
        pre_dispatch=pre_dispatch,
    )
    validate_issue_790_plan(plan)
    path = tmp_path / "finalised.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    empty = tmp_path / "empty.sqlite"
    Issue790CanaryRepository(str(empty))
    with pytest.raises(Issue790DispositionError, match="activation store is absent"):
        load_issue_790_plan(path)
    with pytest.raises(Issue790DispositionError, match="activation is absent"):
        load_issue_790_plan(path, store=empty)
    with pytest.raises(Issue790DispositionError, match="activation is absent"):
        apply_issue_790_plan(
            store=empty,
            backup_path=tmp_path / "backup.sqlite",
            plan=plan,
            observed_at=_OBSERVED,
            repository_root=tmp_path,
        )
    with pytest.raises(Issue790DispositionError, match="activation is absent"):
        run_issue_790_canary(
            store=empty,
            proving_store=tmp_path / "proving.sqlite",
            backup_path=tmp_path / "backup.sqlite",
            plan=plan,
            observed_at=_OBSERVED,
            repository_root=tmp_path,
            event_id="sha256:" + "aa" * 32,
            ledger_seq=2000,
            disposition_digest="sha256:" + "bb" * 32,
        )


def test_forged_and_changed_activation_receipt_fail(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    plan = activated["plan"]
    store = activated["store"]
    connection = Issue790CanaryRepository(str(store))._connection()
    try:
        connection.execute(
            "UPDATE issue_790_step16_activations SET activation_digest=? "
            "WHERE plan_digest=?",
            ("sha256:" + "77" * 32, plan["canonical_digest"]),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(Issue790DispositionError, match="activation differs"):
        _require_approved_plan(plan, store=store, github_api=activated["github"])


def test_changed_comment_body_fails_at_live_gate(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    drifted = dict(activated["github"].comment)
    drifted["body"] = drifted["body"] + "\nextra\n"
    github = _FakeGitHub(drifted, activated["github"].workflow_run)
    with pytest.raises(Issue790DispositionError, match="owner comment evidence"):
        _require_approved_plan(
            activated["plan"],
            store=activated["store"],
            github_api=github,
        )


@pytest.mark.parametrize(
    ("circuit", "match"),
    [
        (None, "not observed"),
        ({"state": "HALF_OPEN"}, "unknown"),
        (
            {
                "state": "OPEN",
                "opened_at": "2026-08-29T11:00:00.000000Z",
                "available_at": "2026-08-29T13:00:00.000000Z",
                "failure_code": "TIMEOUT",
            },
            "future-open",
        ),
        (
            {
                "state": "OPEN",
                "opened_at": None,
                "available_at": "not-a-time",
                "failure_code": "TIMEOUT",
            },
            "malformed",
        ),
        (
            {
                "state": "CLOSED",
                "opened_at": "2026-08-29T11:00:00.000000Z",
                "available_at": None,
                "failure_code": None,
            },
            "malformed",
        ),
    ],
)
def test_event_circuit_policy_holds(circuit, match: str) -> None:
    with pytest.raises(Issue790DispositionError, match=match):
        _require_step16_event_circuit(
            circuit,
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda evidence: evidence["worker"].__setitem__("launchctl_loaded", True),
            "unloaded",
        ),
        (
            lambda evidence: evidence.__setitem__("store_quick_check", "fail"),
            "runtime semantics",
        ),
        (
            lambda evidence: evidence.__setitem__("revision", "f" * 40),
            "reviewed correction",
        ),
    ],
)
def test_runtime_preflight_fails_before_provider(tmp_path: Path, mutator, match: str) -> None:
    activated = _activate(tmp_path)
    evidence = _evidence()
    mutator(evidence)
    with pytest.raises(Issue790DispositionError, match=match):
        qualify_issue_790_step16_readiness(
            plan=activated["plan"],
            store=activated["store"],
            evidence=evidence,
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            canary_event=_ready_event(),
            observed_at=_OBSERVED,
            github_api=activated["github"],
        )


def test_unpermitted_route_and_untouched_event_fail_before_provider(
    tmp_path: Path,
) -> None:
    activated = _activate(tmp_path)
    with pytest.raises(Issue790DispositionError, match="route state"):
        _require_step16_runtime_semantics(
            activated["plan"],
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "NOT_PERMITTED"},
            circuit_state=_closed_circuit(),
            observed_at=_OBSERVED,
            canary_event=_ready_event(),
        )
    claimed = _ready_event()
    claimed["claim_owner"] = "worker-1"
    with pytest.raises(Issue790DispositionError, match="not untouched"):
        _require_step16_runtime_semantics(
            activated["plan"],
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            observed_at=_OBSERVED,
            canary_event=claimed,
        )
    dispatched = _ready_event()
    dispatched["attempt_count"] = 1
    dispatched["provider_dispatched"] = True
    with pytest.raises(Issue790DispositionError, match="not untouched"):
        _require_step16_runtime_semantics(
            activated["plan"],
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            observed_at=_OBSERVED,
            canary_event=dispatched,
        )
    pid_loaded = _evidence()
    worker = dict(pid_loaded["worker"])
    worker["process_ids"] = [1]
    pid_loaded["worker"] = worker
    with pytest.raises(Issue790DispositionError, match="unloaded"):
        _require_step16_runtime_semantics(
            activated["plan"],
            evidence=pid_loaded,
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            observed_at=_OBSERVED,
            canary_event=_ready_event(),
        )
    future_event = _ready_event()
    future_event["available_at"] = "2026-08-29T13:00:00.000000Z"
    with pytest.raises(Issue790DispositionError, match="not untouched"):
        _require_step16_runtime_semantics(
            activated["plan"],
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            observed_at=_OBSERVED,
            canary_event=future_event,
        )


def test_focus_gate_identity_and_duplicate_approval_blocks_fail(
    tmp_path: Path,
) -> None:
    activated = _activate(tmp_path)
    missing = _evidence()
    missing.pop("ci_test")
    with pytest.raises(Issue790DispositionError, match="focus gate evidence"):
        qualify_issue_790_step16_readiness(
            plan=activated["plan"],
            store=activated["store"],
            evidence=missing,
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            canary_event=_ready_event(),
            observed_at=_OBSERVED,
            github_api=activated["github"],
        )
    wrong_run = _evidence()
    ci_test = dict(wrong_run["ci_test"])
    ci_test["url"] = "https://github.com/fol2/newsroom/actions/runs/1/job/1"
    wrong_run["ci_test"] = ci_test
    with pytest.raises(Issue790DispositionError, match="focus gate evidence"):
        qualify_issue_790_step16_readiness(
            plan=activated["plan"],
            store=activated["store"],
            evidence=wrong_run,
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            canary_event=_ready_event(),
            observed_at=_OBSERVED,
            github_api=activated["github"],
        )
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    body = canonical_step16_owner_approval_comment_body(payload)
    duplicated = dict(_comment(payload))
    duplicated["body"] = body + body
    store = tmp_path / "dup.sqlite"
    with pytest.raises(Issue790DispositionError, match="payload"):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=_FakeGitHub(duplicated),
        )


def test_changed_created_at_fails_at_live_gate(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    drifted = dict(activated["github"].comment)
    drifted["created_at"] = "2026-08-29T12:30:00Z"
    drifted["updated_at"] = "2026-08-29T12:30:00Z"
    github = _FakeGitHub(drifted, activated["github"].workflow_run)
    with pytest.raises(Issue790DispositionError, match="owner comment evidence"):
        _require_approved_plan(
            activated["plan"],
            store=activated["store"],
            github_api=github,
        )


def test_positive_readiness_stops_before_provider_io(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    receipt = qualify_issue_790_step16_readiness(
        plan=activated["plan"],
        store=activated["store"],
        evidence=_evidence(),
        route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
        circuit_state=_closed_circuit(),
        canary_event=_ready_event(),
        observed_at=_OBSERVED,
        github_api=activated["github"],
    )
    assert receipt["status"] == ISSUE_790_STEP16_READINESS_STATUS
    assert receipt["provider_calls"] == 0
    assert receipt["catalogue_queries"] == 0
    assert receipt["credential_resolution"] is False
    assert receipt["canary_consumed"] is False
    path = tmp_path / "activated-plan.json"
    path.write_text(json.dumps(activated["plan"]), encoding="utf-8")
    loaded = load_issue_790_plan(
        path,
        store=activated["store"],
        github_api=activated["github"],
    )
    assert loaded["canonical_digest"] == activated["plan"]["canonical_digest"]


def test_step16_call_shape_drift_still_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.control_plane import issue_790_disposition as issue_790_operation

    activated = _activate(tmp_path)
    monkeypatch.setattr(
        issue_790_operation,
        "load_checked_graphiti_call_shape_policy",
        lambda: SimpleNamespace(
            canonical_digest=digest_canonical({"drifted": "call-shape"}),
            version="issue-790-drifted",
            qualified_routes=(),
        ),
        raising=False,
    )
    with pytest.raises(Issue790DispositionError, match="call-shape policy differs"):
        _require_approved_plan(
            activated["plan"],
            store=activated["store"],
            github_api=activated["github"],
        )


def test_historical_static_plans_and_revoked_digest_remain() -> None:
    step_15 = load_issue_790_plan(
        _ROOT / "docs/operations/2026-08-28-issue-790-success-sequence-step-15.json"
    )
    assert step_15["sequence"]["sequence_ordinal"] == 15
    with pytest.raises(KeyError):
        issue_790_contract_module.issue_790_approved_plan_contract(_REVOKED)
    assert (
        issue_790_contract_module.ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST
        in issue_790_contract_module.issue_790_invocation_plan_digests(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        )
    )


def test_cli_passes_activation_store_into_plan_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import issue_790_conservative_disposition as cli

    captured: dict[str, object] = {}

    def _fake_load(path, *, store=None, github_api=None):
        captured["path"] = path
        captured["store"] = store
        raise Issue790DispositionError("stop after load wiring")

    monkeypatch.setattr(cli, "load_issue_790_plan", _fake_load)
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    store = tmp_path / "store.sqlite"
    store.write_bytes(b"")
    rc = cli.main(
        [
            "dry-run",
            "--store",
            str(store),
            "--plan",
            str(plan),
            "--observed-at",
            "2026-08-29T12:00:00+00:00",
            "--receipt",
            str(tmp_path / "receipt.json"),
            "--scratch-store",
            str(tmp_path / "scratch.sqlite"),
        ]
    )
    assert rc == 2
    assert captured["path"] == plan
    assert captured["store"] == store
