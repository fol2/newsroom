"""#790 Step 16 owner-activation is authenticated and not source-registered."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane import issue_790_contract as issue_790_contract_module
from newsroom.control_plane.issue_790_canary import (
    CANARY_CONSUMPTION_SCHEMA,
    Issue790CanaryIntegrityError,
    Issue790CanaryRepository,
)
from newsroom.control_plane import issue_790_disposition as issue_790_operation
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP16_PENDING_PLAN_PATH,
    ISSUE_790_STEP16_PRE_DISPATCH_PATH,
    Issue790DispositionError,
    _release_step16_expired_open_circuit,
    _require_approved_plan,
    _require_step16_event_circuit,
    _require_step16_runtime_semantics,
    activate_issue_790_step16_plan,
    apply_issue_790_plan,
    finalise_issue_790_step16_plan,
    issue_790_step16_checked_approval,
    load_issue_790_plan,
    qualify_issue_790_step16_readiness,
    require_issue_790_path_outside_git,
    run_issue_790_canary,
    seal_issue_790_step16_plan,
    validate_issue_790_plan,
    validate_issue_790_step16_candidate,
    write_issue_790_canonical_json,
)
from newsroom.control_plane.issue_790_step16_activation import (
    ISSUE_790_STEP16_CIRCUIT_RELEASE_POLICY_VERSION,
    ISSUE_790_STEP16_CIRCUIT_RELEASE_SCHEMA,
    ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    ISSUE_790_STEP16_READINESS_STATUS,
    canonical_step16_owner_approval_comment_body,
    effective_issue_790_plan_contract,
    load_step16_activation_record,
    parse_step16_owner_approval_payload,
    validate_step16_activation_receipt,
    validate_step16_circuit_release_receipt,
)
from newsroom.control_plane.model_usage import ModelUsageService
from newsroom.control_plane.store import connect as connect_unpublished_store
from newsroom.graphiti_adapter.combined_temporal_projection import (
    PROJECTION_POLICY_DIGEST,
    PROJECTION_POLICY_VERSION,
)
from newsroom.graphiti_adapter.combined_temporal_validation import (
    VALIDATOR_CONTRACT_VERSION,
)
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION
from newsroom.graphiti_adapter.types import GraphitiAdapterContractError

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
_REAL_RUNTIME_QUALIFIER = issue_790_operation._qualify_real_graphiti_runtime


@pytest.fixture(autouse=True)
def _real_graphiti_runtime_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    unsigned = {
        "schema_version": "newsroom.issue-790.graphiti-runtime-readiness.v1",
        "framework": "graphiti-core",
        "framework_version": "0.29.3",
        "provider_calls": 0,
        "credential_resolution": False,
    }
    monkeypatch.setattr(
        issue_790_operation,
        "_qualify_real_graphiti_runtime",
        lambda: {**unsigned, "runtime_digest": digest_canonical(unsigned)},
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


def _focus_gate_manifest(payload: dict[str, object]) -> dict[str, object]:
    unsigned = {
        "schema_version": "newsroom.sdlc.focus-route.v1",
        "contract_version": "focus-gates-v1",
        "base_sha": "0" * 40,
        "head_sha": payload["final_main_commit"],
        "base_tree_sha": "1" * 40,
        "head_tree_sha": payload["final_main_tree"],
        "changed_paths": ["newsroom/control_plane/issue_790_step16_activation.py"],
        "gates": ["F0", "F1", "F2"],
        "selected_tests": ["newsroom/tests/test_issue_790_step16_activation.py"],
        "selected_service_tests": [],
        "research_required": False,
        "full_health_required": False,
        "owner_authority_required": False,
        "bootstrap_required": False,
        "reasons": ["issue-790-step16-activation"],
        "execution_budget": {"focus_gate_jobs": 1, "dependency_bootstraps": 0},
    }
    return {**unsigned, "manifest_digest": digest_canonical(unsigned)}


def _review_receipt(payload: dict[str, object]) -> dict[str, object]:
    unsigned = {
        "schema_version": "newsroom.issue-790.code-fix-review-receipt.v1",
        "issue": 790,
        "pull_request_url": (
            f"https://github.com/fol2/newsroom/pull/{payload['final_correction_pr']}"
        ),
        "reviewed_fix_revision": payload["reviewed_head_commit"],
        "verdict": "SHIP_ALLOWED",
        "scope": "step16-owner-activation",
        "findings": ["activation-boundary"],
        "blocking_findings": [],
    }
    return {**unsigned, "review_receipt_digest": digest_canonical(unsigned)}


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
    if "focus_gate_manifest_digest" not in overrides:
        payload["focus_gate_manifest_digest"] = _focus_gate_manifest(payload)[
            "manifest_digest"
        ]
    if "feature_complete_review_receipt" not in overrides:
        payload["feature_complete_review_receipt"] = _review_receipt(payload)[
            "review_receipt_digest"
        ]
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
        *,
        focus_gate_manifest: dict[str, object] | None = None,
        review_receipt: dict[str, object] | None = None,
    ) -> None:
        self.comment = comment
        self.workflow_run = workflow_run if workflow_run is not None else _workflow_run()
        self.calls: list[str] = []
        self.focus_gate_manifest = focus_gate_manifest
        self.review_receipt = review_receipt
        body = comment.get("body")
        if (
            self.focus_gate_manifest is None
            or self.review_receipt is None
        ) and isinstance(body, str):
            try:
                payload = parse_step16_owner_approval_payload(body)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                if self.focus_gate_manifest is None:
                    self.focus_gate_manifest = _focus_gate_manifest(payload)
                if self.review_receipt is None:
                    self.review_receipt = _review_receipt(payload)

    def __call__(self, resource: str) -> dict[str, object]:
        self.calls.append(resource)
        if resource.startswith("repos/fol2/newsroom/issues/comments/"):
            return self.comment
        if resource == (
            f"repos/fol2/newsroom/actions/runs/{self.workflow_run['id']}"
        ):
            return self.workflow_run
        raise Issue790DispositionError("issue #790 GitHub evidence is unavailable")


def _activate(
    tmp_path: Path,
    store: Path | None = None,
    **comment_overrides: object,
) -> dict[str, object]:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    github = _FakeGitHub(_comment(payload, **comment_overrides))
    store = tmp_path / "authority.sqlite" if store is None else store
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


def _provider_free_event_preflight() -> dict[str, object]:
    event = _ready_event()
    unsigned: dict[str, object] = {
        "schema_version": "newsroom.issue-790.candidate-event-qualification.v1",
        "status": "READY_FOR_OWNER_PACKET",
        "event_id": event["event_id"],
        "ledger_seq": event["ledger_seq"],
        "event_manifest_digest": "sha256:" + "12" * 32,
        "event_preflight_digest": "sha256:" + "34" * 32,
        "resolved_unit_count": 1,
        "provider_calls": 0,
        "store_mutations": 0,
        "observed_at": "2026-08-29T12:00:00.000000Z",
    }
    return {**unsigned, "qualification_digest": digest_canonical(unsigned)}


def _empty_proving_store(tmp_path: Path) -> Path:
    path = tmp_path / "proving.sqlite"
    sqlite3.connect(path).close()
    return path


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
    with pytest.raises(
        (Issue790CanaryIntegrityError, Issue790DispositionError),
        match="activation differs|contradicts retained evidence",
    ):
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
    with pytest.raises(Issue790DispositionError, match="payload|owner comment"):
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
            proving_store=tmp_path / "unused-proving.sqlite",
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
            proving_store=tmp_path / "unused-proving.sqlite",
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
            proving_store=tmp_path / "unused-proving.sqlite",
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


def test_positive_readiness_stops_before_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated = _activate(tmp_path)
    monkeypatch.setattr(
        issue_790_operation,
        "qualify_issue_790_candidate_event",
        lambda **_kwargs: _provider_free_event_preflight(),
    )
    receipt = qualify_issue_790_step16_readiness(
        plan=activated["plan"],
        store=activated["store"],
        proving_store=_empty_proving_store(tmp_path),
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
    assert receipt["schema_version"].endswith("readiness.v2")
    assert receipt["event_id"] == _ready_event()["event_id"]
    assert receipt["ledger_seq"] == _ready_event()["ledger_seq"]
    assert receipt["resolved_unit_count"] == 1
    assert receipt["event_preflight_digest"] == (
        _provider_free_event_preflight()["event_preflight_digest"]
    )
    assert receipt["candidate_event_qualification_digest"] == (
        _provider_free_event_preflight()["qualification_digest"]
    )
    assert receipt["runtime_readiness"]["framework_version"] == "0.29.3"
    assert receipt["runtime_readiness"]["provider_calls"] == 0
    path = tmp_path / "activated-plan.json"
    path.write_text(json.dumps(activated["plan"]), encoding="utf-8")
    loaded = load_issue_790_plan(
        path,
        store=activated["store"],
        github_api=activated["github"],
    )
    assert loaded["canonical_digest"] == activated["plan"]["canonical_digest"]


def test_missing_real_runtime_blocks_readiness_before_event_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated = _activate(tmp_path)
    monkeypatch.setattr(
        issue_790_operation.real_graphiti_module,
        "_load_graphiti",
        lambda: (_ for _ in ()).throw(
            GraphitiAdapterContractError(
                "graphiti extra (graphiti-core 0.29.3) is required"
            )
        ),
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_qualify_real_graphiti_runtime",
        _REAL_RUNTIME_QUALIFIER,
    )
    monkeypatch.setattr(
        issue_790_operation,
        "qualify_issue_790_candidate_event",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("event qualification ran without its real runtime")
        ),
    )
    with pytest.raises(
        Issue790DispositionError,
        match="real Graphiti runtime is unavailable",
    ):
        qualify_issue_790_step16_readiness(
            plan=activated["plan"],
            store=activated["store"],
            proving_store=_empty_proving_store(tmp_path),
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            canary_event=_ready_event(),
            observed_at=_OBSERVED,
            github_api=activated["github"],
        )


def test_selected_event_mismatch_cannot_receive_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated = _activate(tmp_path)

    def mismatch(**_kwargs: object) -> dict[str, object]:
        raise Issue790DispositionError(
            "issue #790 selected event is not provider-free ready: "
            "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED"
        )

    monkeypatch.setattr(
        issue_790_operation,
        "qualify_issue_790_candidate_event",
        mismatch,
    )
    with pytest.raises(
        Issue790DispositionError,
        match="selected event is not provider-free ready: "
        "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED",
    ):
        qualify_issue_790_step16_readiness(
            plan=activated["plan"],
            store=activated["store"],
            proving_store=_empty_proving_store(tmp_path),
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            canary_event=_ready_event(),
            observed_at=_OBSERVED,
            github_api=activated["github"],
        )


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


_UNSAFE_PACKET = (
    _ROOT / "newsroom/tests/fixtures/issue_790_comment_5459306524.txt"
)
_CURRENT_PACKET = (
    _ROOT / "newsroom/tests/fixtures/issue_790_comment_5459706010.txt"
)


def _activation_counts(store: Path) -> tuple[int, int, int]:
    if not store.exists():
        return (0, 0, 0)
    connection = sqlite3.connect(str(store))
    try:
        def _count(table: str) -> int:
            present = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if present is None:
                return 0
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(row[0])

        return (
            _count("issue_790_step16_activations"),
            _count("issue_790_bounded_canary_consumptions"),
            _count("issue_790_step16_circuit_releases"),
        )
    finally:
        connection.close()


def _install_event_circuit(
    store: Path,
    *,
    state: str,
    opened_at: str | None = None,
    available_at: str | None = None,
    failure_code: str | None = None,
) -> None:
    connection = sqlite3.connect(str(store))
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS unpublished_graphiti_event_circuit("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "state TEXT NOT NULL CHECK(state IN ('CLOSED','OPEN')),"
            "opened_at TEXT,available_at TEXT,failure_code TEXT)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO unpublished_graphiti_event_circuit("
            "singleton,state,opened_at,available_at,failure_code) VALUES (1,?,?,?,?)",
            (state, opened_at, available_at, failure_code),
        )
        connection.commit()
    finally:
        connection.close()


def _re_sign(record: dict[str, object]) -> dict[str, object]:
    from newsroom.authority.canonical import digest_bytes

    forged = dict(record)
    payload = dict(forged["approval_payload"])
    forged["approval_payload"] = payload
    forged["canonical_approval_payload_digest"] = digest_canonical(payload)
    forged["canonical_body_digest"] = digest_bytes(
        canonical_step16_owner_approval_comment_body(payload).encode("utf-8")
    )
    unsigned = {key: item for key, item in forged.items() if key != "activation_digest"}
    forged["activation_digest"] = digest_canonical(unsigned)
    return forged


def test_unsafe_packet_comment_5459306524_never_authenticates(tmp_path: Path) -> None:
    import re

    from newsroom.authority.canonical import canonical_json_bytes

    body = _UNSAFE_PACKET.read_text(encoding="utf-8")
    assert "NEWSROOM_ISSUE_790_STEP16_OWNER_APPROVAL_V1" in body
    fences = re.findall(r"```json\n(.*)\n```", body, re.DOTALL)
    assert len(fences) == 1
    parsed_json = json.loads(fences[0])
    assert fences[0] == canonical_json_bytes(parsed_json).decode("utf-8")
    assert "not owner approval" in body.lower()
    with pytest.raises(Issue790DispositionError, match="payload"):
        parse_step16_owner_approval_payload(body)
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    comment = _comment(payload, body=body, id=5459306524)
    comment["html_url"] = (
        "https://github.com/fol2/newsroom/issues/790#issuecomment-5459306524"
    )
    comment["url"] = (
        "https://api.github.com/repos/fol2/newsroom/issues/comments/5459306524"
    )
    store = tmp_path / "authority.sqlite"
    with pytest.raises(Issue790DispositionError, match="payload"):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=5459306524,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=_FakeGitHub(comment),
        )
    activations, consumptions, releases = _activation_counts(store)
    assert (activations, consumptions, releases) == (0, 0, 0)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda body: "x" + body,
        lambda body: "# Heading\n" + body,
        lambda body: body + "\n",
        lambda body: body[:-1],
        lambda body: body + "Extra sentence.\n",
        lambda body: body.replace(
            "NEWSROOM_ISSUE_790_STEP16_OWNER_APPROVAL_V1",
            "NEWSROOM_ISSUE_790_STEP16_OWNER_APPROVAL_V1\n\n"
            "NEWSROOM_ISSUE_790_STEP16_OWNER_APPROVAL_V1",
            1,
        ),
        lambda body: body + body,
        lambda body: body.replace("```json\n{", "```json\n{ ", 1),
    ],
)
def test_non_canonical_approval_bodies_fail(mutator) -> None:
    candidate = _seal()
    body = canonical_step16_owner_approval_comment_body(_payload(candidate))
    mutated = mutator(body)
    assert mutated != body
    with pytest.raises(Issue790DispositionError, match="payload"):
        parse_step16_owner_approval_payload(mutated)


def test_exact_canonical_body_authenticates_with_fake_github(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    body = activated["github"].comment["body"]
    parsed = parse_step16_owner_approval_payload(body)
    assert body == canonical_step16_owner_approval_comment_body(parsed)
    assert activated["activation"]["approval_payload"] == parsed
    _require_approved_plan(
        activated["plan"],
        store=activated["store"],
        github_api=activated["github"],
    )


def test_coherent_forged_activation_records_fail_closed(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    legitimate = dict(activated["activation"])
    cases: list[dict[str, object]] = []

    def _rebind(record: dict[str, object]) -> dict[str, object]:
        payload = dict(record["approval_payload"])
        record = dict(record)
        record["approval_payload"] = payload
        manifest = _focus_gate_manifest(payload)
        review = _review_receipt(payload)
        record["focus_gate_evidence"] = manifest
        record["review_evidence"] = review
        payload["focus_gate_manifest_digest"] = manifest["manifest_digest"]
        payload["feature_complete_review_receipt"] = review["review_receipt_digest"]
        record["final_main_commit"] = payload["final_main_commit"]
        record["final_main_tree"] = payload["final_main_tree"]
        record["checked_candidate_digest"] = payload["checked_candidate_digest"]
        return _re_sign(record)

    commit = dict(legitimate)
    commit["approval_payload"] = dict(commit["approval_payload"])
    commit["approval_payload"]["final_main_commit"] = "e" * 40
    cases.append(_rebind(commit))

    tree = dict(legitimate)
    tree["approval_payload"] = dict(tree["approval_payload"])
    tree["approval_payload"]["final_main_tree"] = "f" * 40
    cases.append(_rebind(tree))

    run = dict(legitimate)
    run["approval_payload"] = dict(run["approval_payload"])
    run["approval_payload"]["focus_gate_run_id"] = 1
    run["approval_payload"]["focus_gate_run_url"] = (
        "https://github.com/fol2/newsroom/actions/runs/1"
    )
    cases.append(_rebind(run))

    manifest = dict(legitimate)
    manifest["approval_payload"] = dict(manifest["approval_payload"])
    manifest["approval_payload"]["focus_gate_manifest_digest"] = "sha256:" + "aa" * 32
    cases.append(_re_sign(manifest))

    review = dict(legitimate)
    review["approval_payload"] = dict(review["approval_payload"])
    review["approval_payload"]["feature_complete_review_receipt"] = (
        "sha256:" + "bb" * 32
    )
    cases.append(_re_sign(review))

    candidate = dict(legitimate)
    candidate["approval_payload"] = dict(candidate["approval_payload"])
    candidate["approval_payload"]["checked_candidate_digest"] = "sha256:" + "cc" * 32
    cases.append(_rebind(candidate))

    non_effects = dict(legitimate)
    non_effects["approval_payload"] = dict(non_effects["approval_payload"])
    non_effects["approval_payload"]["non_effects"] = ["NO_PUBLICATION"]
    cases.append(_re_sign(non_effects))

    stop = dict(legitimate)
    stop["approval_payload"] = dict(stop["approval_payload"])
    stop["approval_payload"]["stop_condition"] = "KEEP_GOING"
    cases.append(_re_sign(stop))

    caps = dict(legitimate)
    caps["approval_payload"] = dict(caps["approval_payload"])
    caps["approval_payload"]["retry_cap"] = 1
    cases.append(_re_sign(caps))

    pre = dict(legitimate)
    pre["approval_payload"] = dict(pre["approval_payload"])
    pre["approval_payload"]["pre_dispatch_policy_digest"] = "sha256:" + "dd" * 32
    pre["pre_dispatch_template_digest"] = "sha256:" + "dd" * 32
    cases.append(_re_sign(pre))

    binding_run = dict(legitimate)
    binding_run["approval_payload"] = dict(binding_run["approval_payload"])
    binding_run["approval_payload"]["event_circuit_policy"] = "ALWAYS_CLOSED"
    cases.append(_re_sign(binding_run))

    contract = dict(legitimate)
    contract["contract"] = dict(contract["contract"])
    contract["contract"]["invocation_id"] = "sha256:" + "ee" * 32
    cases.append(_re_sign(contract))

    comment = dict(legitimate)
    comment["comment_id"] = 1
    comment["comment_url"] = (
        "https://github.com/fol2/newsroom/issues/790#issuecomment-1"
    )
    cases.append(_re_sign(comment))

    empty = tmp_path / "empty.sqlite"
    repository = Issue790CanaryRepository(str(empty))
    for forged in cases:
        try:
            repository.retain_step16_activation(forged)
        except (Issue790CanaryIntegrityError, Issue790DispositionError):
            assert _activation_counts(empty)[0] == 0
            continue
        with pytest.raises(Issue790DispositionError):
            _require_approved_plan(
                activated["plan"],
                store=empty,
                github_api=activated["github"],
            )
        connection = sqlite3.connect(str(empty))
        try:
            connection.execute("DELETE FROM issue_790_step16_activations")
            connection.commit()
        finally:
            connection.close()

    connection = sqlite3.connect(str(empty))
    try:
        connection.execute(
            "INSERT INTO issue_790_step16_activations("
            "activation_digest,checked_candidate_digest,plan_digest,comment_id,"
            "payload_digest,created_at,record_json) VALUES (?,?,?,?,?,?,?)",
            (
                legitimate["activation_digest"],
                "sha256:" + "99" * 32,
                legitimate["plan_digest"],
                legitimate["comment_id"],
                legitimate["canonical_approval_payload_digest"],
                legitimate["created_at"],
                json.dumps(legitimate),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(Issue790DispositionError, match="activation differs"):
        load_step16_activation_record(
            sqlite3.connect(str(empty)),
            plan_digest=str(legitimate["plan_digest"]),
        )


def test_legitimate_activation_replay_matches_refetched_payload(tmp_path: Path) -> None:
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
    assert second["activation"] == first["activation"]
    connection = sqlite3.connect(str(first["store"]))
    try:
        loaded = load_step16_activation_record(
            connection,
            plan_digest=str(first["plan"]["canonical_digest"]),
        )
    finally:
        connection.close()
    validated = validate_step16_activation_receipt(
        loaded,
        authenticated=first["activation"] | {
            "payload": first["activation"]["approval_payload"],
            "comment_id": first["activation"]["comment_id"],
            "comment_node_id": first["activation"]["comment_node_id"],
            "comment_url": first["activation"]["comment_url"],
            "created_at": first["activation"]["created_at"],
            "updated_at": first["activation"]["updated_at"],
            "canonical_body_digest": first["activation"]["canonical_body_digest"],
            "canonical_approval_payload_digest": first["activation"][
                "canonical_approval_payload_digest"
            ],
            "checked_candidate_digest": first["activation"]["checked_candidate_digest"],
        },
        plan=first["plan"],
    )
    assert validated["approval_payload"] == parse_step16_owner_approval_payload(
        first["github"].comment["body"]
    )


def _open_circuit() -> dict[str, object]:
    return {
        "state": "OPEN",
        "opened_at": "2026-08-29T10:00:00.000000Z",
        "available_at": "2026-08-29T11:00:00.000000Z",
        "failure_code": "TIMEOUT",
    }


def test_expired_open_circuit_cas_and_receipt(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    store = activated["store"]
    _install_event_circuit(store, **_open_circuit())
    repository = Issue790CanaryRepository(str(store))
    first = repository.release_step16_expired_open_circuit(
        plan_digest=str(activated["plan"]["canonical_digest"]),
        activation_digest=str(activated["activation"]["activation_digest"]),
        event_id="sha256:" + "aa" * 32,
        ledger_seq=2000,
        prior_state=_open_circuit(),
        observed_at=_OBSERVED,
        policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    )
    assert first["provider_calls"] == 0
    assert first["cas_result"]["rowcount"] == 1
    second = repository.release_step16_expired_open_circuit(
        plan_digest=str(activated["plan"]["canonical_digest"]),
        activation_digest=str(activated["activation"]["activation_digest"]),
        event_id="sha256:" + "aa" * 32,
        ledger_seq=2000,
        prior_state=_open_circuit(),
        observed_at=_OBSERVED,
        policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    )
    assert second["release_digest"] == first["release_digest"]
    assert _activation_counts(store)[2] == 1
    connection = sqlite3.connect(str(store))
    try:
        state = connection.execute(
            "SELECT state,opened_at,available_at,failure_code "
            "FROM unpublished_graphiti_event_circuit WHERE singleton=1"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(state) == ("CLOSED", None, None, None)


def test_circuit_cas_prior_row_sql_identity_fails(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    store = activated["store"]
    _install_event_circuit(store, **_open_circuit())
    repository = Issue790CanaryRepository(str(store))
    repository.release_step16_expired_open_circuit(
        plan_digest=str(activated["plan"]["canonical_digest"]),
        activation_digest=str(activated["activation"]["activation_digest"]),
        event_id="sha256:" + "aa" * 32,
        ledger_seq=2000,
        prior_state=_open_circuit(),
        observed_at=_OBSERVED,
        policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    )
    connection = sqlite3.connect(str(store))
    try:
        connection.execute(
            "UPDATE issue_790_step16_circuit_releases SET activation_digest=?",
            ("sha256:" + "00" * 32,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(Issue790CanaryIntegrityError, match="circuit release differs"):
        repository.release_step16_expired_open_circuit(
            plan_digest=str(activated["plan"]["canonical_digest"]),
            activation_digest=str(activated["activation"]["activation_digest"]),
            event_id="sha256:" + "aa" * 32,
            ledger_seq=2000,
            prior_state=_open_circuit(),
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )


def test_circuit_cas_rowcount_zero_and_contradiction_fail(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    store = activated["store"]
    _install_event_circuit(store, **_open_circuit())
    repository = Issue790CanaryRepository(str(store))
    wrong = _open_circuit()
    wrong["opened_at"] = "2026-08-29T09:00:00.000000Z"
    with pytest.raises(Issue790CanaryIntegrityError, match="circuit release differs"):
        repository.release_step16_expired_open_circuit(
            plan_digest=str(activated["plan"]["canonical_digest"]),
            activation_digest=str(activated["activation"]["activation_digest"]),
            event_id="sha256:" + "aa" * 32,
            ledger_seq=2000,
            prior_state=wrong,
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )
    connection = sqlite3.connect(str(store))
    try:
        state = connection.execute(
            "SELECT state FROM unpublished_graphiti_event_circuit WHERE singleton=1"
        ).fetchone()
    finally:
        connection.close()
    assert state[0] == "OPEN"
    repository.release_step16_expired_open_circuit(
        plan_digest=str(activated["plan"]["canonical_digest"]),
        activation_digest=str(activated["activation"]["activation_digest"]),
        event_id="sha256:" + "aa" * 32,
        ledger_seq=2000,
        prior_state=_open_circuit(),
        observed_at=_OBSERVED,
        policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    )
    with pytest.raises(Issue790CanaryIntegrityError, match="circuit release differs"):
        repository.release_step16_expired_open_circuit(
            plan_digest=str(activated["plan"]["canonical_digest"]),
            activation_digest=str(activated["activation"]["activation_digest"]),
            event_id="sha256:" + "aa" * 32,
            ledger_seq=2000,
            prior_state={
                **_open_circuit(),
                "failure_code": "OTHER",
            },
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )


def test_circuit_release_persistence_failure_rolls_back(tmp_path: Path) -> None:
    from newsroom.control_plane.issue_790_step16_activation import (
        STEP16_CIRCUIT_RELEASE_TABLE_SQL,
    )

    activated = _activate(tmp_path)
    store = activated["store"]
    _install_event_circuit(store, **_open_circuit())
    connection = sqlite3.connect(str(store))
    try:
        connection.executescript(STEP16_CIRCUIT_RELEASE_TABLE_SQL)
        connection.execute(
            "CREATE TRIGGER fail_release_insert "
            "BEFORE INSERT ON issue_790_step16_circuit_releases "
            "BEGIN SELECT RAISE(ABORT, 'disk full'); END"
        )
        connection.commit()
    finally:
        connection.close()
    repository = Issue790CanaryRepository(str(store))
    with pytest.raises(sqlite3.IntegrityError, match="disk full"):
        repository.release_step16_expired_open_circuit(
            plan_digest=str(activated["plan"]["canonical_digest"]),
            activation_digest=str(activated["activation"]["activation_digest"]),
            event_id="sha256:" + "aa" * 32,
            ledger_seq=2000,
            prior_state=_open_circuit(),
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )
    connection = sqlite3.connect(str(store))
    try:
        state = connection.execute(
            "SELECT state FROM unpublished_graphiti_event_circuit WHERE singleton=1"
        ).fetchone()
    finally:
        connection.close()
    assert state[0] == "OPEN"
    assert _activation_counts(store)[2] == 0


def test_exception_after_release_leaves_durable_receipt(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    store = activated["store"]
    _install_event_circuit(store, **_open_circuit())
    repository = Issue790CanaryRepository(str(store))
    released = _release_step16_expired_open_circuit(
        store=store,
        plan=activated["plan"],
        circuit_state=_open_circuit(),
        observed_at=_OBSERVED,
        event_id="sha256:" + "aa" * 32,
        ledger_seq=2000,
        repository=repository,
    )
    assert released["provider_calls"] == 0
    resumed = repository.release_step16_expired_open_circuit(
        plan_digest=str(activated["plan"]["canonical_digest"]),
        activation_digest=str(activated["activation"]["activation_digest"]),
        event_id="sha256:" + "aa" * 32,
        ledger_seq=2000,
        prior_state=_open_circuit(),
        observed_at=_OBSERVED,
        policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
    )
    assert resumed["release_digest"] == released["release_digest"]
    assert _activation_counts(store)[2] == 1


def test_coherent_closed_circuit_needs_no_release() -> None:
    assert (
        _require_step16_event_circuit(
            _closed_circuit(),
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )
        == "CLOSED"
    )


def test_missing_or_mismatched_activation_evidence_fails(tmp_path: Path) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    comment = _comment(payload)
    store = tmp_path / "authority.sqlite"
    github = _FakeGitHub(comment)
    github.focus_gate_manifest = None
    with pytest.raises(Issue790DispositionError, match="focus gate evidence"):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=github,
        )
    github = _FakeGitHub(comment)
    github.review_receipt = dict(github.review_receipt)
    github.review_receipt["reviewed_fix_revision"] = "f" * 40
    unsigned = {
        key: item
        for key, item in github.review_receipt.items()
        if key != "review_receipt_digest"
    }
    github.review_receipt["review_receipt_digest"] = digest_canonical(unsigned)
    with pytest.raises(
        Issue790DispositionError, match="feature-complete review receipt"
    ):
        activate_issue_790_step16_plan(
            candidate,
            comment_id=_COMMENT_ID,
            pre_dispatch=pre_dispatch,
            store=store,
            github_api=github,
        )


def test_opened_after_available_is_malformed() -> None:
    with pytest.raises(Issue790DispositionError, match="malformed"):
        _require_step16_event_circuit(
            {
                "state": "OPEN",
                "opened_at": "2026-08-29T12:00:00.000000Z",
                "available_at": "2026-08-29T11:00:00.000000Z",
                "failure_code": "TIMEOUT",
            },
            observed_at=_OBSERVED,
            policy=ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY,
        )


_OWNER = "issue-790-canary:step16-recovery"
_DISPOSITION = "sha256:" + "bb" * 32
_EVENT_ID = "sha256:" + "aa" * 32
_LEDGER = 2000


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _seed_canary_event(
    store: Path,
    *,
    state: str = "QUEUED",
    attempt_count: int = 0,
    provider_dispatched: bool = False,
    claim_owner: str | None = None,
    last_failure_code: str | None = None,
    terminal_at: str | None = None,
    event_id: str = _EVENT_ID,
    ledger_seq: int = _LEDGER,
) -> None:
    connection = connect_unpublished_store(str(store))
    try:
        present = connection.execute(
            "SELECT 1 FROM unpublished_graphiti_revision_events "
            "WHERE event_id=? AND ledger_seq=?",
            (event_id, ledger_seq),
        ).fetchone()
        if present is None:
            manifest = {
                "event_type": "EFFECTIVE_SOURCE_REVISION_LANDED",
                "ledger_seq": ledger_seq,
                "ledger_digest": event_id,
                "unit_refs": [],
            }
            connection.execute(
                "INSERT INTO unpublished_graphiti_revision_events("
                "event_id,ledger_seq,ledger_digest,source_id,item_key,"
                "revision_digest,landed_at,manifest_json,manifest_digest,"
                "unit_count,projector_version,projection_generation,state,"
                "attempt_count,available_at,claim_owner,claim_expires_at,"
                "last_failure_code,provider_dispatched,terminal_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    ledger_seq,
                    event_id,
                    f"source-{ledger_seq}",
                    f"item-{ledger_seq}",
                    "sha256:" + "99" * 32,
                    "2026-08-28T00:00:00.000000Z",
                    _json(manifest),
                    digest_canonical(manifest),
                    0,
                    "test-projector",
                    "test-projection",
                    state,
                    attempt_count,
                    "2026-08-28T00:00:00.000000Z",
                    claim_owner,
                    None,
                    last_failure_code,
                    int(provider_dispatched),
                    terminal_at,
                ),
            )
        else:
            connection.execute(
                "UPDATE unpublished_graphiti_revision_events SET "
                "state=?,attempt_count=?,provider_dispatched=?,claim_owner=?,"
                "last_failure_code=?,terminal_at=? "
                "WHERE event_id=? AND ledger_seq=?",
                (
                    state,
                    attempt_count,
                    int(provider_dispatched),
                    claim_owner,
                    last_failure_code,
                    terminal_at,
                    event_id,
                    ledger_seq,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _insert_consumption(
    store: Path,
    *,
    plan_digest: str,
    circuit_release: dict[str, object] | None = None,
) -> dict[str, object]:
    consumed_at = "2026-08-29T11:00:00.000000Z"
    preflight_unsigned = {
        "schema_version": "newsroom.issue-790.iterative-fresh-event-preflight.v2",
        "event_id": _EVENT_ID,
        "ledger_seq": _LEDGER,
        "provider_calls": 0,
    }
    preflight = {
        **preflight_unsigned,
        "evidence_digest": digest_canonical(preflight_unsigned),
    }
    without_digest: dict[str, object] = {
        "schema_version": CANARY_CONSUMPTION_SCHEMA,
        "approved_plan_digest": plan_digest,
        "disposition_digest": _DISPOSITION,
        "event_id": _EVENT_ID,
        "ledger_seq": _LEDGER,
        "owner_id": _OWNER,
        "preflight_evidence": preflight,
        "preflight_evidence_digest": preflight["evidence_digest"],
        "event_state_before": "QUEUED",
        "attempt_count_before": 0,
        "provider_io_authorised": True,
        "maximum_event_attempts": 1,
        "persistent_worker_must_remain_unloaded": True,
        "public_dispatch_authorised": False,
        "publication_authorised": False,
        "consumed_at": consumed_at,
        "circuit_release": circuit_release,
    }
    record = {
        **without_digest,
        "consumption_digest": digest_canonical(without_digest),
    }
    connection = sqlite3.connect(str(store))
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO issue_790_bounded_canary_consumptions("
            "consumption_digest,approved_plan_digest,disposition_digest,"
            "event_id,ledger_seq,owner_id,consumed_at,record_json) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                record["consumption_digest"],
                plan_digest,
                _DISPOSITION,
                _EVENT_ID,
                _LEDGER,
                _OWNER,
                consumed_at,
                _json(record),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return record


def _seed_primary_leaf(store: Path, *, terminal: bool) -> None:
    invocation_id = "sha256:" + "ab" * 32
    envelope_id = "sha256:" + "cd" * 32
    allocation = {
        "workload_class": "GRAPHITI_CHAT_PRIMARY",
        "provider": "cursor-agent-cli",
        "route": "GRAPHITI_CHAT_PRIMARY",
        "model": "composer-2.5",
    }
    connection = sqlite3.connect(str(store))
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO model_work_envelopes("
            "envelope_id,cycle_id,workload_class,admitted_at,canonical_digest,"
            "record_json) VALUES(?,?,?,?,?,?)",
            (
                envelope_id,
                _EVENT_ID,
                "GRAPHITI_CHAT_PRIMARY",
                "2026-08-29T11:00:00.000000Z",
                "sha256:" + "11" * 32,
                "{}",
            ),
        )
        connection.execute(
            "INSERT INTO model_invocation_allocations("
            "invocation_id,envelope_id,cycle_id,leaf_ordinal,workload_class,"
            "policy_digest,provider,route,model,request_digest,allocated_at,"
            "canonical_digest,record_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                invocation_id,
                envelope_id,
                _EVENT_ID,
                1,
                "GRAPHITI_CHAT_PRIMARY",
                "sha256:" + "22" * 32,
                "cursor-agent-cli",
                "GRAPHITI_CHAT_PRIMARY",
                "composer-2.5",
                "sha256:" + "33" * 32,
                "2026-08-29T11:00:01.000000Z",
                "sha256:" + "44" * 32,
                _json(allocation),
            ),
        )
        connection.execute(
            "INSERT INTO model_transport_observations("
            "observation_digest,invocation_id,observed_at,state,evidence_digest,"
            "record_json) VALUES(?,?,?,?,?,?)",
            (
                "sha256:" + "55" * 32,
                invocation_id,
                "2026-08-29T11:00:02.000000Z",
                "DISPATCH_STARTED",
                "sha256:" + "66" * 32,
                _json({"state": "DISPATCH_STARTED"}),
            ),
        )
        if terminal:
            connection.execute(
                "INSERT INTO model_invocation_terminals("
                "terminal_digest,invocation_id,usage_status,outcome,"
                "failure_class,completed_at,record_json) VALUES(?,?,?,?,?,?,?)",
                (
                    "sha256:" + "77" * 32,
                    invocation_id,
                    "REPORTED",
                    "ACCEPTED",
                    None,
                    "2026-08-29T11:00:03.000000Z",
                    _json(
                        {
                            "usage_status": "REPORTED",
                            "components": {"total_tokens": 12},
                            "outcome": "ACCEPTED",
                        }
                    ),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _table_count(store: Path, table: str) -> int:
    connection = sqlite3.connect(str(store))
    try:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if present is None:
            return 0
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])
    finally:
        connection.close()


def _patch_recovery_bindings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: dict[str, object],
    consume_calls: list[object],
    qualify_calls: list[object],
    route_after: dict[str, object] | None = None,
) -> None:
    retry = plan["retry_forbidden_events"]
    monkeypatch.setattr(issue_790_operation, "_assert_exact_target", lambda *a, **k: None)
    monkeypatch.setattr(
        issue_790_operation,
        "_require_sequence_predecessor",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_require_retry_exclusions",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_require_retry_events_unchanged",
        lambda *a, **k: retry,
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_retry_event_snapshots",
        lambda *a, **k: retry,
    )
    monkeypatch.setattr(
        issue_790_operation,
        "collect_issue_790_operational_evidence",
        lambda **kwargs: _evidence(),
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_validate_operational_evidence",
        lambda evidence, **kwargs: evidence,
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_worker_state",
        lambda: {
            "label": "com.jamesto.newsroom-graphiti-worker",
            "launchctl_loaded": False,
            "process_ids": [],
        },
    )
    monkeypatch.setattr(
        issue_790_operation,
        "_require_issue_790_canary_route",
        lambda **kwargs: None,
    )
    closed = {
        "state": "CLOSED",
        "reason": f"AUTHORISED_OPERATOR_RESET:{_DISPOSITION}",
    }
    calls = {"n": 0}

    def _route(self: object, route: str) -> dict[str, object]:
        calls["n"] += 1
        if route_after is not None and calls["n"] > 1:
            return route_after
        return closed

    monkeypatch.setattr(issue_790_operation.ModelUsageService, "route_state", _route)

    def _no_consume(**kwargs: object) -> None:
        consume_calls.append(kwargs)
        raise AssertionError("recovery dispatched a provider call")

    def _no_qualify(**kwargs: object) -> None:
        qualify_calls.append(kwargs)
        raise AssertionError("recovery qualified a fresh event")

    monkeypatch.setattr(issue_790_operation, "_consume_issue_790_event", _no_consume)
    monkeypatch.setattr(issue_790_operation, "_qualify_issue_790_event", _no_qualify)


def _prepare_recovery_store(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    store = tmp_path / "unpublished.sqlite3"
    ModelUsageService(str(store))
    connection = connect_unpublished_store(str(store))
    connection.close()
    Issue790CanaryRepository(str(store))
    activated = _activate(tmp_path, store=store)
    proving = tmp_path / "proving.sqlite3"
    sqlite3.connect(str(proving)).close()
    activated["proving"] = proving
    return store, activated


def _run_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    store: Path,
    activated: dict[str, object],
    consume_calls: list[object],
    qualify_calls: list[object],
    route_after: dict[str, object] | None = None,
) -> dict[str, object]:
    _patch_recovery_bindings(
        monkeypatch,
        plan=activated["plan"],
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
        route_after=route_after,
    )
    return run_issue_790_canary(
        store=store,
        proving_store=activated["proving"],
        backup_path=tmp_path
        / f"backup-{len(list(tmp_path.glob('backup-*.sqlite3')))}.sqlite3",
        plan=activated["plan"],
        observed_at=_OBSERVED,
        repository_root=tmp_path,
        event_id=_EVENT_ID,
        ledger_seq=_LEDGER,
        disposition_digest=_DISPOSITION,
        github_api=activated["github"],
    )


def _assert_zero_recovery_io(
    receipt: dict[str, object],
    store: Path,
    *,
    consume_calls: list[object],
    qualify_calls: list[object],
) -> None:
    assert receipt["resumed_zero_io_finalisation"] is True
    assert receipt["provider_dispatch_attempted_this_run"] is False
    assert receipt["retry_authorised"] is False
    assert receipt["publication_performed"] is False
    assert receipt["public_dispatch_performed"] is False
    assert receipt["backlog_drain_performed"] is False
    assert consume_calls == []
    assert qualify_calls == []
    assert _table_count(store, "issue_790_bounded_canary_consumptions") == 1
    outcome = receipt["outcome"]
    assert outcome["completion_mode"] == "ZERO_IO_RECOVERY"
    assert outcome["retry_authorised"] is False


def test_fresh_event_gate_blocks_recovery_states(tmp_path: Path) -> None:
    activated = _activate(tmp_path)
    ready = _ready_event()
    _require_step16_runtime_semantics(
        activated["plan"],
        evidence=_evidence(),
        route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
        circuit_state=_closed_circuit(),
        observed_at=_OBSERVED,
        canary_event=ready,
        fresh_event=True,
    )
    for state in (
        "RUNNING",
        "RETRY_HELD",
        "CONFIGURATION_HELD",
        "DEAD_LETTER",
        "TERMINAL",
    ):
        event = dict(ready)
        event["state"] = state
        event["attempt_count"] = 1
        event["provider_dispatched"] = True
        with pytest.raises(Issue790DispositionError, match="not untouched"):
            _require_step16_runtime_semantics(
                activated["plan"],
                evidence=_evidence(),
                route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
                circuit_state=_closed_circuit(),
                observed_at=_OBSERVED,
                canary_event=event,
                fresh_event=True,
            )
        _require_step16_runtime_semantics(
            activated["plan"],
            evidence=_evidence(),
            route_state={"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"},
            circuit_state=_closed_circuit(),
            observed_at=_OBSERVED,
            canary_event=None,
            fresh_event=False,
        )


def test_recovery_after_consumption_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _seed_canary_event(store)
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    receipt = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    _assert_zero_recovery_io(
        receipt, store, consume_calls=consume_calls, qualify_calls=qualify_calls
    )
    assert receipt["outcome"]["attempt_count"] == 0
    assert receipt["outcome"]["process_result"] is None
    assert receipt["event_after"]["event"]["state"] == "CONFIGURATION_HELD"
    assert _table_count(store, "issue_790_bounded_canary_outcomes") == 1


def test_recovery_after_dispatch_started_before_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _seed_canary_event(
        store,
        state="RUNNING",
        attempt_count=1,
        provider_dispatched=False,
        claim_owner=_OWNER,
    )
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    _seed_primary_leaf(store, terminal=False)
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    receipt = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    _assert_zero_recovery_io(
        receipt, store, consume_calls=consume_calls, qualify_calls=qualify_calls
    )
    assert receipt["outcome"]["result_class"] == "UNCLASSIFIED_NON_SUCCESS"
    assert receipt["outcome"]["process_result"]["state"] == "RUNNING"
    assert receipt["outcome"]["provider_dispatched"] is True
    assert receipt["event_after"]["event"]["state"] == "CONFIGURATION_HELD"
    assert receipt["retry_authorised"] is False


def test_recovery_after_terminal_before_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _seed_canary_event(
        store,
        state="TERMINAL",
        attempt_count=1,
        provider_dispatched=True,
        terminal_at="2026-08-29T11:00:03.000000Z",
    )
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    _seed_primary_leaf(store, terminal=True)
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    receipt = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    _assert_zero_recovery_io(
        receipt, store, consume_calls=consume_calls, qualify_calls=qualify_calls
    )
    assert receipt["outcome"]["result_class"] == "TRUTHFUL_PROVIDER_SUCCESS"
    assert receipt["event_after"]["event"]["state"] == "TERMINAL"
    assert receipt["outcome"]["attempt_count"] == 1
    assert receipt["canary_evidence_passed"] is True
    assert receipt["publication_performed"] is False
    assert receipt["public_dispatch_performed"] is False
    assert receipt["backlog_drain_performed"] is False
    assert receipt["worker_remained_unloaded"] is True
    assert _table_count(store, "issue_790_bounded_canary_outcomes") == 1


def test_recovery_after_provider_non_success_before_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _seed_canary_event(
        store,
        state="RETRY_HELD",
        attempt_count=1,
        provider_dispatched=True,
        last_failure_code="TIMEOUT",
    )
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    _seed_primary_leaf(store, terminal=False)
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    receipt = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    _assert_zero_recovery_io(
        receipt, store, consume_calls=consume_calls, qualify_calls=qualify_calls
    )
    assert receipt["outcome"]["result_class"] == "UNCLASSIFIED_NON_SUCCESS"
    assert receipt["outcome"]["retry_authorised"] is False
    assert receipt["event_after"]["event"]["state"] == "CONFIGURATION_HELD"


def test_recovery_replays_existing_outcome_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _seed_canary_event(store)
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    first = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    second = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    _assert_zero_recovery_io(
        second, store, consume_calls=consume_calls, qualify_calls=qualify_calls
    )
    assert second["outcome"] == first["outcome"]
    assert _table_count(store, "issue_790_bounded_canary_outcomes") == 1
    assert _table_count(store, "issue_790_bounded_canary_consumptions") == 1


def test_recovery_fails_closed_if_route_or_circuit_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_dir = tmp_path / "route-change"
    route_dir.mkdir()
    store, activated = _prepare_recovery_store(route_dir)
    _seed_canary_event(store)
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    with pytest.raises(Issue790DispositionError, match="route changed"):
        _run_recovery(
            route_dir,
            monkeypatch,
            store=store,
            activated=activated,
            consume_calls=consume_calls,
            qualify_calls=qualify_calls,
            route_after={"state": "OPEN", "reason": "TIMEOUT"},
        )
    assert consume_calls == []
    assert _table_count(store, "issue_790_bounded_canary_consumptions") == 1

    circuit_dir = tmp_path / "circuit-change"
    circuit_dir.mkdir()
    store, activated = _prepare_recovery_store(circuit_dir)
    _install_event_circuit(store, **_closed_circuit())
    _seed_canary_event(store)
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    original = Issue790CanaryRepository.finalise_without_dispatch

    def _mutate(self: Issue790CanaryRepository, **kwargs: object) -> dict[str, object]:
        _install_event_circuit(store, **_open_circuit())
        return original(self, **kwargs)

    monkeypatch.setattr(
        Issue790CanaryRepository, "finalise_without_dispatch", _mutate
    )
    consume_calls = []
    qualify_calls = []
    with pytest.raises(Issue790DispositionError, match="event circuit changed"):
        _run_recovery(
            circuit_dir,
            monkeypatch,
            store=store,
            activated=activated,
            consume_calls=consume_calls,
            qualify_calls=qualify_calls,
        )
    assert consume_calls == []
    assert _table_count(store, "issue_790_bounded_canary_consumptions") == 1


def test_recovery_does_not_repair_an_open_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, activated = _prepare_recovery_store(tmp_path)
    _install_event_circuit(store, **_open_circuit())
    _seed_canary_event(store)
    _insert_consumption(
        store, plan_digest=str(activated["plan"]["canonical_digest"])
    )
    consume_calls: list[object] = []
    qualify_calls: list[object] = []
    receipt = _run_recovery(
        tmp_path,
        monkeypatch,
        store=store,
        activated=activated,
        consume_calls=consume_calls,
        qualify_calls=qualify_calls,
    )
    _assert_zero_recovery_io(
        receipt, store, consume_calls=consume_calls, qualify_calls=qualify_calls
    )
    assert receipt["event_after"]["circuit"] == _open_circuit()
    assert _table_count(store, "issue_790_step16_circuit_releases") == 0


def test_current_and_historical_packets_cannot_activate(tmp_path: Path) -> None:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    for comment_id, body in (
        (5459706010, _CURRENT_PACKET.read_text(encoding="utf-8")),
        (5459306524, _UNSAFE_PACKET.read_text(encoding="utf-8")),
    ):
        store = tmp_path / f"authority-{comment_id}.sqlite"
        github = _FakeGitHub(
            {
                "id": comment_id,
                "node_id": "IC_packet",
                "html_url": (
                    "https://github.com/fol2/newsroom/issues/790"
                    f"#issuecomment-{comment_id}"
                ),
                "url": (
                    "https://api.github.com/repos/fol2/newsroom/issues/comments/"
                    f"{comment_id}"
                ),
                "issue_url": "https://api.github.com/repos/fol2/newsroom/issues/790",
                "user": {"login": "fol2"},
                "author_association": "OWNER",
                "created_at": "2026-08-29T12:00:00Z",
                "updated_at": "2026-08-29T12:00:00Z",
                "body": body,
            }
        )
        with pytest.raises(Issue790DispositionError):
            activate_issue_790_step16_plan(
                candidate,
                comment_id=comment_id,
                pre_dispatch=pre_dispatch,
                store=store,
                github_api=github,
            )
        assert _activation_counts(store)[0] == 0


def _operator_files(tmp_path: Path) -> tuple[dict[str, Path], dict[str, object]]:
    candidate = _seal()
    _, pre_dispatch = _pending_family()
    payload = _payload(candidate)
    files = {
        "candidate": _write_json(tmp_path / "candidate.json", candidate),
        "pre_dispatch": _write_json(tmp_path / "pre-dispatch.json", pre_dispatch),
        "manifest": _write_json(
            tmp_path / "manifest.json", _focus_gate_manifest(payload)
        ),
        "review": _write_json(tmp_path / "review.json", _review_receipt(payload)),
        "store": tmp_path / "authority.sqlite",
        "plan": tmp_path / "activated-plan.json",
        "receipt": tmp_path / "activation-receipt.json",
    }
    return files, payload


def test_operator_activate_and_qualify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import issue_790_conservative_disposition as cli

    files, payload = _operator_files(tmp_path)
    github = _FakeGitHub(_comment(payload))
    monkeypatch.setattr(issue_790_operation, "_default_github_api", github)
    monkeypatch.setattr(
        issue_790_operation,
        "qualify_issue_790_candidate_event",
        lambda **_kwargs: _provider_free_event_preflight(),
    )
    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 0
    assert files["plan"].is_file()
    assert files["receipt"].is_file()
    assert _activation_counts(files["store"])[0] == 1
    repeated = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert repeated == 0
    evidence = tmp_path / "evidence.json"
    route = tmp_path / "route.json"
    event = tmp_path / "event.json"
    ready = tmp_path / "ready.json"
    _write_json(evidence, _evidence())
    _write_json(route, {"state": "OPEN", "reason": "SYSTEMIC_TRANSPORT"})
    _write_json(event, _ready_event())
    proving = _empty_proving_store(tmp_path)
    rc = cli.main(
        [
            "qualify-step16",
            "--store",
            str(files["store"]),
            "--plan",
            str(files["plan"]),
            "--proving-store",
            str(proving),
            "--evidence",
            str(evidence),
            "--route-state",
            str(route),
            "--canary-event",
            str(event),
            "--circuit-state",
            str(_write_json(tmp_path / "circuit.json", _closed_circuit())),
            "--observed-at",
            "2026-08-29T12:00:00+00:00",
            "--receipt",
            str(ready),
        ]
    )
    assert rc == 0
    receipt = json.loads(ready.read_text(encoding="utf-8"))
    assert receipt["status"] == ISSUE_790_STEP16_READINESS_STATUS
    assert receipt["provider_calls"] == 0
    assert receipt["catalogue_queries"] == 0
    assert receipt["credential_resolution"] is False
    assert receipt["canary_consumed"] is False
    assert _activation_counts(files["store"])[1] == 0


def test_operator_activate_rejects_git_output_and_missing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import issue_790_conservative_disposition as cli

    files, payload = _operator_files(tmp_path)
    github = _FakeGitHub(_comment(payload))
    monkeypatch.setattr(issue_790_operation, "_default_github_api", github)
    git_plan = _ROOT / "activated-plan.json"
    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(git_plan),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 2
    assert _activation_counts(files["store"])[0] == 0
    assert not git_plan.exists()

    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 2
    assert _activation_counts(files["store"])[0] == 0

    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 2
    assert _activation_counts(files["store"])[0] == 0

    _write_json(files["plan"], {"unexpected": True})
    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 2
    assert json.loads(files["plan"].read_text(encoding="utf-8")) == {"unexpected": True}


def test_operator_activate_rejects_wrong_identities_and_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import issue_790_conservative_disposition as cli

    files, payload = _operator_files(tmp_path)
    github = _FakeGitHub(_comment(payload))
    monkeypatch.setattr(issue_790_operation, "_default_github_api", github)
    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID + 1),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 2
    assert _activation_counts(files["store"])[0] == 0

    drifted = json.loads(files["manifest"].read_text(encoding="utf-8"))
    drifted["head_sha"] = "f" * 40
    unsigned = {key: item for key, item in drifted.items() if key != "manifest_digest"}
    drifted["manifest_digest"] = digest_canonical(unsigned)
    _write_json(files["manifest"], drifted)
    rc = cli.main(
        [
            "activate-step16",
            "--store",
            str(files["store"]),
            "--candidate",
            str(files["candidate"]),
            "--pre-dispatch",
            str(files["pre_dispatch"]),
            "--comment-id",
            str(_COMMENT_ID),
            "--focus-gate-manifest",
            str(files["manifest"]),
            "--review-receipt",
            str(files["review"]),
            "--activated-plan",
            str(files["plan"]),
            "--activation-receipt",
            str(files["receipt"]),
        ]
    )
    assert rc == 2
    assert _activation_counts(files["store"])[0] == 0


def test_circuit_release_validator_rejects_sql_drift() -> None:
    prior = {
        "state": "OPEN",
        "opened_at": "2026-08-29T10:00:00.000000Z",
        "available_at": "2026-08-29T11:00:00.000000Z",
        "failure_code": "TIMEOUT",
    }
    unsigned = {
        "schema_version": ISSUE_790_STEP16_CIRCUIT_RELEASE_SCHEMA,
        "policy_version": ISSUE_790_STEP16_CIRCUIT_RELEASE_POLICY_VERSION,
        "plan_digest": "sha256:" + "11" * 32,
        "activation_digest": "sha256:" + "22" * 32,
        "event_id": _EVENT_ID,
        "ledger_seq": _LEDGER,
        "prior_state": prior,
        "released_at": "2026-08-29T12:00:00.000000Z",
        "effect": "IMMEDIATE_CLOSE_EXPIRED_OPEN",
        "provider_calls": 0,
        "cas_result": {
            "singleton": 1,
            "state": "OPEN",
            "rowcount": 1,
            "opened_at": prior["opened_at"],
            "available_at": prior["available_at"],
            "failure_code": prior["failure_code"],
        },
    }
    record = {**unsigned, "release_digest": digest_canonical(unsigned)}
    assert validate_step16_circuit_release_receipt(record) == record
    with pytest.raises(Issue790DispositionError, match="circuit release differs"):
        validate_step16_circuit_release_receipt(
            record,
            sql_identity={
                "release_digest": "sha256:" + "00" * 32,
                "activation_digest": record["activation_digest"],
                "plan_digest": record["plan_digest"],
                "event_id": record["event_id"],
                "ledger_seq": record["ledger_seq"],
                "released_at": record["released_at"],
            },
        )
    drifted = dict(record)
    drifted["provider_calls"] = 1
    with pytest.raises(Issue790DispositionError, match="circuit release differs"):
        validate_step16_circuit_release_receipt(drifted)
