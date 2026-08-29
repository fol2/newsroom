"""Authenticated, content-addressed Step 16 owner-activation (not a plan registry)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.control_plane.issue_790_contract import (
    ISSUE_790_APPROVED_BY,
    ISSUE_790_APPROVED_SCOPE,
    ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION,
    ISSUE_790_STEP16_ACTIVATION_SCHEMA,
    ISSUE_790_STEP16_APPROVAL_MARKER,
    ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST,
    ISSUE_790_STEP16_OWNER_APPROVAL_SCHEMA,
    Issue790ApprovedPlanContract,
    issue_790_approved_plan_contract,
    issue_790_checked_candidate_contract,
)
from newsroom.graphiti_adapter.combined_temporal_projection import (
    PROJECTION_POLICY_DIGEST,
    PROJECTION_POLICY_VERSION,
)
from newsroom.graphiti_adapter.combined_temporal_validation import (
    VALIDATOR_CONTRACT_VERSION,
)
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

GitHubApi = Callable[[str], Mapping[str, object]]

ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY = (
    "CLOSED_COHERENT_OR_EXPIRED_OPEN_IMMEDIATE_CLOSE"
)
ISSUE_790_STEP16_READINESS_STATUS = "READY_FOR_OWNER_AUTHORISED_PROVIDER_IO"
_COMMENT_HTML = re.compile(
    r"https://github\.com/fol2/newsroom/issues/790#issuecomment-([1-9][0-9]*)"
)
_COMMENT_API = re.compile(
    r"https://api\.github\.com/repos/fol2/newsroom/issues/comments/([1-9][0-9]*)"
)
_ISSUE_API = "https://api.github.com/repos/fol2/newsroom/issues/790"
_FOCUS_GATE_RUN = re.compile(
    r"https://github\.com/fol2/newsroom/actions/runs/([1-9][0-9]*)"
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_JSON_FENCE = re.compile(r"```json\n(.*)\n```", re.DOTALL)
_STEP16_OWNER_CAPS = {
    "catalogue_query_cap": 1,
    "fresh_event_cap": 1,
    "provider_dispatch_cap": 1,
    "retry_cap": 0,
    "fallback_cap": 0,
    "backlog_drain_cap": 0,
    "bulk_requeue_cap": 0,
    "publication_cap": 0,
}
_PAYLOAD_KEYS = (
    "schema_version",
    "issue",
    "checked_candidate_digest",
    "final_main_commit",
    "final_main_tree",
    "final_correction_pr",
    "reviewed_head_commit",
    "reviewed_head_tree",
    "focus_gate_run_url",
    "focus_gate_run_id",
    "focus_gate_manifest_digest",
    "feature_complete_review_receipt",
    "projection_policy_version",
    "projection_policy_digest",
    "temporal_policy_version",
    "validator_contract_version",
    "call_shape_policy_version",
    "call_shape_policy_digest",
    "pre_dispatch_policy_digest",
    "catalogue_query_cap",
    "fresh_event_cap",
    "provider_dispatch_cap",
    "retry_cap",
    "fallback_cap",
    "backlog_drain_cap",
    "bulk_requeue_cap",
    "publication_cap",
    "stop_condition",
    "non_effects",
    "event_circuit_policy",
    "activation_policy_version",
)
_OWNER_ACTIVATION_KEYS = (
    "checked_candidate_digest",
    "pre_dispatch_template_digest",
    "final_correction_pr",
    "reviewed_head_commit",
    "reviewed_head_tree",
    "focus_gate_run_url",
    "focus_gate_run_id",
    "focus_gate_manifest_digest",
    "feature_complete_review_receipt",
    "event_circuit_policy",
    "caps",
    "activation_policy_version",
)
_ACTIVATION_TABLE = "issue_790_step16_activations"
STEP16_ACTIVATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS issue_790_step16_activations(
    activation_digest TEXT PRIMARY KEY,
    checked_candidate_digest TEXT NOT NULL UNIQUE,
    plan_digest TEXT NOT NULL UNIQUE,
    comment_id INTEGER NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);
"""


def _fail(message: str) -> None:
    from newsroom.control_plane.issue_790_disposition import Issue790DispositionError

    raise Issue790DispositionError(message)


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"issue #790 {field} differs")
    return value


def _hex40(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        _fail(f"issue #790 {field} differs")
    return value


def _natural(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"issue #790 {field} differs")
    return value


def _cap(value: object, *, field: str, maximum: int, exact: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"issue #790 {field} differs")
    if value > maximum:
        _fail("issue #790 owner approval caps differ")
    if exact is not None and value != exact:
        _fail("issue #790 owner approval caps differ")
    return value


def _instant(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        _fail(f"issue #790 {field} differs")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"issue #790 {field} differs")
    if parsed.tzinfo is None:
        _fail(f"issue #790 {field} differs")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_step16_owner_approval_comment_body(payload: Mapping[str, object]) -> str:
    """Return the one allowed comment-body representation of the payload."""

    encoded = canonical_json_bytes(dict(payload)).decode("utf-8")
    return f"{ISSUE_790_STEP16_APPROVAL_MARKER}\n\n```json\n{encoded}\n```\n"


def parse_step16_owner_approval_payload(body: object) -> dict[str, object]:
    """Extract the unique canonical JSON payload from a GitHub comment body."""

    if not isinstance(body, str) or not body:
        _fail("issue #790 owner approval payload differs")
    if body.count(ISSUE_790_STEP16_APPROVAL_MARKER) != 1:
        _fail("issue #790 owner approval payload differs")
    fences = _JSON_FENCE.findall(body)
    if len(fences) != 1:
        _fail("issue #790 owner approval payload differs")
    try:
        parsed = json.loads(fences[0])
    except json.JSONDecodeError:
        _fail("issue #790 owner approval payload differs")
    if not isinstance(parsed, dict):
        _fail("issue #790 owner approval payload differs")
    if fences[0] != canonical_json_bytes(parsed).decode("utf-8"):
        _fail("issue #790 owner approval payload differs")
    return validate_step16_owner_approval_payload(parsed)


def validate_step16_owner_approval_payload(
    value: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(value)
    if tuple(sorted(payload)) != tuple(sorted(_PAYLOAD_KEYS)):
        _fail("issue #790 owner approval payload differs")
    if (
        payload.get("schema_version") != ISSUE_790_STEP16_OWNER_APPROVAL_SCHEMA
        or payload.get("issue") != 790
        or payload.get("activation_policy_version")
        != ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION
        or payload.get("stop_condition") != "FIRST_TRUTHFUL_PROVIDER_BACKED_SUCCESS"
        or payload.get("event_circuit_policy") != ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY
        or payload.get("projection_policy_version") != PROJECTION_POLICY_VERSION
        or payload.get("projection_policy_digest") != PROJECTION_POLICY_DIGEST
        or payload.get("temporal_policy_version") != TEMPORAL_POLICY_VERSION
        or payload.get("validator_contract_version") != VALIDATOR_CONTRACT_VERSION
    ):
        _fail("issue #790 owner approval payload differs")
    _sha256(payload.get("checked_candidate_digest"), field="checked candidate digest")
    _hex40(payload.get("final_main_commit"), field="final main commit")
    _hex40(payload.get("final_main_tree"), field="final main tree")
    _hex40(payload.get("reviewed_head_commit"), field="reviewed head commit")
    _hex40(payload.get("reviewed_head_tree"), field="reviewed head tree")
    _natural(payload.get("final_correction_pr"), field="final correction pr")
    run_url = payload.get("focus_gate_run_url")
    run_id = _natural(payload.get("focus_gate_run_id"), field="focus gate run id")
    matched = _FOCUS_GATE_RUN.fullmatch(str(run_url) if isinstance(run_url, str) else "")
    if matched is None or int(matched.group(1)) != run_id:
        _fail("issue #790 owner approval payload differs")
    _sha256(payload.get("focus_gate_manifest_digest"), field="focus gate manifest digest")
    _sha256(
        payload.get("feature_complete_review_receipt"),
        field="feature-complete review receipt",
    )
    _sha256(payload.get("call_shape_policy_digest"), field="call-shape policy digest")
    _sha256(payload.get("pre_dispatch_policy_digest"), field="pre-dispatch policy digest")
    if not isinstance(payload.get("call_shape_policy_version"), str) or not payload.get(
        "call_shape_policy_version"
    ):
        _fail("issue #790 owner approval payload differs")
    _cap(payload.get("catalogue_query_cap"), field="catalogue query cap", maximum=1, exact=1)
    _cap(payload.get("fresh_event_cap"), field="fresh event cap", maximum=1, exact=1)
    _cap(
        payload.get("provider_dispatch_cap"),
        field="provider dispatch cap",
        maximum=1,
        exact=1,
    )
    for field, exact in (
        ("retry_cap", 0),
        ("fallback_cap", 0),
        ("backlog_drain_cap", 0),
        ("bulk_requeue_cap", 0),
        ("publication_cap", 0),
    ):
        _cap(payload.get(field), field=field.replace("_", " "), maximum=0, exact=exact)
    non_effects = payload.get("non_effects")
    if not isinstance(non_effects, list) or any(
        not isinstance(item, str) or not item for item in non_effects
    ):
        _fail("issue #790 owner approval payload differs")
    return payload


def step16_owner_activation_binding(
    payload: Mapping[str, object],
    *,
    template_digest: str,
) -> dict[str, object]:
    retained = validate_step16_owner_approval_payload(payload)
    binding = {
        "checked_candidate_digest": retained["checked_candidate_digest"],
        "pre_dispatch_template_digest": template_digest,
        "final_correction_pr": retained["final_correction_pr"],
        "reviewed_head_commit": retained["reviewed_head_commit"],
        "reviewed_head_tree": retained["reviewed_head_tree"],
        "focus_gate_run_url": retained["focus_gate_run_url"],
        "focus_gate_run_id": retained["focus_gate_run_id"],
        "focus_gate_manifest_digest": retained["focus_gate_manifest_digest"],
        "feature_complete_review_receipt": retained["feature_complete_review_receipt"],
        "event_circuit_policy": retained["event_circuit_policy"],
        "caps": {
            key: retained[key]
            for key in (
                "catalogue_query_cap",
                "fresh_event_cap",
                "provider_dispatch_cap",
                "retry_cap",
                "fallback_cap",
                "backlog_drain_cap",
                "bulk_requeue_cap",
                "publication_cap",
            )
        },
        "activation_policy_version": retained["activation_policy_version"],
    }
    if tuple(sorted(binding)) != tuple(sorted(_OWNER_ACTIVATION_KEYS)):
        _fail("issue #790 owner activation binding differs")
    if binding["caps"] != _STEP16_OWNER_CAPS:
        _fail("issue #790 owner approval caps differ")
    if template_digest != retained["pre_dispatch_policy_digest"]:
        _fail("issue #790 pre-dispatch identity differs")
    return binding


def validate_step16_owner_activation_binding(
    value: Mapping[str, object],
) -> dict[str, object]:
    binding = dict(value)
    if tuple(sorted(binding)) != tuple(sorted(_OWNER_ACTIVATION_KEYS)):
        _fail("issue #790 owner activation binding differs")
    _sha256(binding.get("checked_candidate_digest"), field="checked candidate digest")
    _sha256(
        binding.get("pre_dispatch_template_digest"),
        field="pre-dispatch template digest",
    )
    _natural(binding.get("final_correction_pr"), field="final correction pr")
    _hex40(binding.get("reviewed_head_commit"), field="reviewed head commit")
    _hex40(binding.get("reviewed_head_tree"), field="reviewed head tree")
    run_url = binding.get("focus_gate_run_url")
    run_id = _natural(binding.get("focus_gate_run_id"), field="focus gate run id")
    matched = _FOCUS_GATE_RUN.fullmatch(str(run_url) if isinstance(run_url, str) else "")
    if matched is None or int(matched.group(1)) != run_id:
        _fail("issue #790 owner activation binding differs")
    _sha256(binding.get("focus_gate_manifest_digest"), field="focus gate manifest digest")
    _sha256(
        binding.get("feature_complete_review_receipt"),
        field="feature-complete review receipt",
    )
    if (
        binding.get("event_circuit_policy") != ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY
        or binding.get("activation_policy_version")
        != ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION
        or binding.get("caps") != _STEP16_OWNER_CAPS
    ):
        _fail("issue #790 owner activation binding differs")
    return binding


def authenticate_step16_owner_comment(
    comment: Mapping[str, object],
    *,
    comment_id: int,
    payload: Mapping[str, object],
    workflow_run: Mapping[str, object],
) -> dict[str, object]:
    """Fail-closed GitHub owner-comment authentication. Time comes from GitHub."""

    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        _fail("issue #790 owner comment identity differs")
    user = comment.get("user")
    html_url = comment.get("html_url")
    api_url = comment.get("url")
    issue_url = comment.get("issue_url")
    html_match = _COMMENT_HTML.fullmatch(str(html_url) if isinstance(html_url, str) else "")
    api_match = _COMMENT_API.fullmatch(str(api_url) if isinstance(api_url, str) else "")
    if (
        comment.get("id") != comment_id
        or html_match is None
        or api_match is None
        or int(html_match.group(1)) != comment_id
        or int(api_match.group(1)) != comment_id
        or issue_url != _ISSUE_API
        or not isinstance(user, dict)
        or user.get("login") != "fol2"
        or comment.get("author_association") != "OWNER"
        or not isinstance(comment.get("node_id"), str)
        or not comment.get("node_id")
    ):
        _fail("issue #790 owner comment identity differs")
    created_at = _instant(comment.get("created_at"), field="owner comment created_at")
    updated_at = _instant(comment.get("updated_at"), field="owner comment updated_at")
    if created_at != updated_at:
        _fail("issue #790 owner comment was edited")
    retained_payload = parse_step16_owner_approval_payload(comment.get("body"))
    if retained_payload != dict(payload):
        _fail("issue #790 owner approval payload differs")
    run_id = retained_payload["focus_gate_run_id"]
    if (
        workflow_run.get("id") != run_id
        or workflow_run.get("html_url") != retained_payload["focus_gate_run_url"]
        or workflow_run.get("head_sha") != retained_payload["final_main_commit"]
        or workflow_run.get("status") != "completed"
        or workflow_run.get("conclusion") != "success"
    ):
        _fail("issue #790 focus gate evidence differs")
    completed_at = _instant(
        workflow_run.get("updated_at"),
        field="focus gate completed_at",
    )
    if created_at <= completed_at:
        _fail("issue #790 owner approval precedes reviewed evidence")
    created_text = _utc_text(created_at)
    updated_text = _utc_text(updated_at)
    body = comment.get("body")
    if not isinstance(body, str):
        _fail("issue #790 owner approval payload differs")
    return {
        "comment_id": comment_id,
        "comment_node_id": str(comment["node_id"]),
        "comment_url": str(html_url),
        "author_login": "fol2",
        "author_association": "OWNER",
        "created_at": created_text,
        "updated_at": updated_text,
        "canonical_body_digest": digest_bytes(body.encode("utf-8")),
        "canonical_approval_payload_digest": digest_canonical(retained_payload),
        "checked_candidate_digest": str(retained_payload["checked_candidate_digest"]),
        "payload": retained_payload,
        "approved_by": ISSUE_790_APPROVED_BY,
        "approval_reference": str(html_url),
        "approved_at": created_text,
        "scope": ISSUE_790_APPROVED_SCOPE,
    }


def fetch_step16_github_json(
    resource: str,
    *,
    github_api: GitHubApi | None,
    default_github_api: GitHubApi,
) -> dict[str, object]:
    fetcher = default_github_api if github_api is None else github_api
    try:
        value = fetcher(resource)
    except Exception:
        _fail("issue #790 GitHub evidence is unavailable")
    if not isinstance(value, Mapping):
        _fail("issue #790 GitHub evidence is unavailable")
    return dict(value)


def fetch_authenticated_step16_owner_comment(
    *,
    comment_id: int,
    github_api: GitHubApi | None,
    default_github_api: GitHubApi,
) -> dict[str, object]:
    raw_comment = fetch_step16_github_json(
        f"repos/fol2/newsroom/issues/comments/{comment_id}",
        github_api=github_api,
        default_github_api=default_github_api,
    )
    payload = parse_step16_owner_approval_payload(raw_comment.get("body"))
    raw_run = fetch_step16_github_json(
        f"repos/fol2/newsroom/actions/runs/{payload['focus_gate_run_id']}",
        github_api=github_api,
        default_github_api=default_github_api,
    )
    return authenticate_step16_owner_comment(
        raw_comment,
        comment_id=comment_id,
        payload=payload,
        workflow_run=raw_run,
    )


def mint_step16_activation_receipt(
    *,
    authenticated: Mapping[str, object],
    plan: Mapping[str, object],
    contract: Issue790ApprovedPlanContract,
    template_digest: str,
    effective_digest: str,
) -> dict[str, object]:
    payload = dict(authenticated["payload"])
    unsigned = {
        "schema_version": ISSUE_790_STEP16_ACTIVATION_SCHEMA,
        "activation_policy_version": ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION,
        "issue": 790,
        "checked_candidate_digest": authenticated["checked_candidate_digest"],
        "plan_digest": plan["canonical_digest"],
        "comment_id": authenticated["comment_id"],
        "comment_node_id": authenticated["comment_node_id"],
        "comment_url": authenticated["comment_url"],
        "author_login": authenticated["author_login"],
        "author_association": authenticated["author_association"],
        "created_at": authenticated["created_at"],
        "updated_at": authenticated["updated_at"],
        "canonical_body_digest": authenticated["canonical_body_digest"],
        "canonical_approval_payload_digest": authenticated[
            "canonical_approval_payload_digest"
        ],
        "approval_payload": payload,
        "pre_dispatch_template_digest": template_digest,
        "pre_dispatch_effective_digest": effective_digest,
        "final_main_commit": payload["final_main_commit"],
        "final_main_tree": payload["final_main_tree"],
        "contract": asdict(contract),
    }
    return {**unsigned, "activation_digest": digest_canonical(unsigned)}


def activation_record_to_contract(
    record: Mapping[str, object],
) -> Issue790ApprovedPlanContract:
    raw = record.get("contract")
    if not isinstance(raw, dict):
        _fail("issue #790 step 16 activation contract differs")
    try:
        return Issue790ApprovedPlanContract(**raw)
    except TypeError:
        _fail("issue #790 step 16 activation contract differs")
        raise


def load_step16_activation_record(
    connection: sqlite3.Connection,
    *,
    plan_digest: str,
) -> dict[str, object]:
    if not (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_ACTIVATION_TABLE,),
        ).fetchone()
    ):
        _fail("issue #790 step 16 activation is absent")
    row = connection.execute(
        "SELECT activation_digest,record_json FROM issue_790_step16_activations "
        "WHERE plan_digest=?",
        (plan_digest,),
    ).fetchone()
    if row is None:
        _fail("issue #790 step 16 activation is absent")
    try:
        record = json.loads(str(row[1]))
    except json.JSONDecodeError:
        _fail("issue #790 step 16 activation differs")
        raise
    if not isinstance(record, dict):
        _fail("issue #790 step 16 activation differs")
    supplied = record.get("activation_digest")
    unsigned = {key: item for key, item in record.items() if key != "activation_digest"}
    if supplied != digest_canonical(unsigned) or supplied != str(row[0]):
        _fail("issue #790 step 16 activation differs")
    return record


def step16_activation_contract_from_connection(
    connection: sqlite3.Connection,
    plan_digest: str,
) -> Issue790ApprovedPlanContract:
    return activation_record_to_contract(
        load_step16_activation_record(connection, plan_digest=plan_digest)
    )


def effective_issue_790_plan_contract(
    plan_digest: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> Issue790ApprovedPlanContract:
    try:
        return issue_790_approved_plan_contract(plan_digest)
    except KeyError:
        if connection is None:
            raise
        try:
            return step16_activation_contract_from_connection(connection, plan_digest)
        except Exception as exc:
            raise KeyError(plan_digest) from exc


def effective_issue_790_invocation_plan_digests(
    invocation_id: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> frozenset[str]:
    from newsroom.control_plane.issue_790_contract import (
        issue_790_invocation_plan_digests,
    )

    digests = set(issue_790_invocation_plan_digests(invocation_id))
    if connection is None or not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (_ACTIVATION_TABLE,),
    ).fetchone():
        return frozenset(digests)
    for row in connection.execute(
        "SELECT plan_digest,record_json FROM issue_790_step16_activations"
    ):
        try:
            record = json.loads(str(row[1]))
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        contract = record.get("contract")
        if isinstance(contract, dict) and contract.get("invocation_id") == invocation_id:
            digests.add(str(row[0]))
    return frozenset(digests)


def require_step16_candidate_matches_payload(
    *,
    candidate: Mapping[str, object],
    payload: Mapping[str, object],
) -> None:
    candidate_digest = candidate.get("canonical_digest")
    if candidate_digest != payload.get("checked_candidate_digest"):
        _fail("issue #790 owner approval payload differs")
    if candidate_digest != ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST:
        _fail("issue #790 candidate identity differs")
    try:
        contract = issue_790_checked_candidate_contract(str(candidate_digest))
    except KeyError:
        _fail("issue #790 candidate identity differs")
        raise
    sequence = candidate.get("sequence")
    if not isinstance(sequence, dict):
        _fail("issue #790 candidate identity differs")
    if (
        payload.get("projection_policy_version") != contract.projection_policy_version
        or payload.get("projection_policy_digest") != contract.projection_policy_digest
        or payload.get("temporal_policy_version") != contract.temporal_policy_version
        or payload.get("validator_contract_version") != contract.validator_contract_version
        or payload.get("pre_dispatch_policy_digest")
        != contract.pre_dispatch_operational_requirements_digest
        or payload.get("call_shape_policy_version")
        != sequence.get("call_shape_policy_version")
        or payload.get("call_shape_policy_digest")
        != sequence.get("call_shape_policy_digest")
    ):
        _fail("issue #790 owner approval payload differs")


def require_step16_plan_matches_activation(
    plan: Mapping[str, object],
    record: Mapping[str, object],
) -> Issue790ApprovedPlanContract:
    contract = activation_record_to_contract(record)
    sequence = plan.get("sequence")
    approval = plan.get("approval")
    target = plan.get("target")
    binding = sequence.get("owner_activation") if isinstance(sequence, dict) else None
    payload = record.get("approval_payload")
    if (
        not isinstance(sequence, dict)
        or not isinstance(approval, dict)
        or not isinstance(target, dict)
        or not isinstance(binding, dict)
        or not isinstance(payload, dict)
        or plan.get("canonical_digest") != record.get("plan_digest")
        or binding.get("checked_candidate_digest")
        != record.get("checked_candidate_digest")
        or sequence.get("pre_dispatch_operational_requirements_digest")
        != record.get("pre_dispatch_effective_digest")
        or binding.get("pre_dispatch_template_digest")
        != record.get("pre_dispatch_template_digest")
        or sequence.get("reviewed_correction_revision") != record.get("final_main_commit")
        or sequence.get("reviewed_correction_tree") != record.get("final_main_tree")
        or approval.get("approval_reference") != record.get("comment_url")
        or approval.get("approved_at") != record.get("created_at")
        or approval.get("approved_by") != ISSUE_790_APPROVED_BY
        or payload.get("non_effects") != plan.get("non_effects")
        or payload.get("stop_condition") != sequence.get("stop_condition")
    ):
        _fail("issue #790 step 16 activation differs")
    validate_step16_owner_activation_binding(binding)
    if (
        contract.plan_digest != plan.get("canonical_digest")
        or contract.invocation_id != target.get("invocation_id")
        or contract.terminal_digest != target.get("terminal_digest")
        or contract.allocation_digest != target.get("allocation_digest")
        or contract.approved_by != approval.get("approved_by")
        or contract.approval_reference != approval.get("approval_reference")
        or contract.approved_at != approval.get("approved_at")
        or contract.sequence_ordinal != 16
    ):
        _fail("issue #790 step 16 activation contract differs")
    return contract


__all__ = [
    "ISSUE_790_STEP16_EVENT_CIRCUIT_POLICY",
    "ISSUE_790_STEP16_READINESS_STATUS",
    "STEP16_ACTIVATION_TABLE_SQL",
    "GitHubApi",
    "activation_record_to_contract",
    "authenticate_step16_owner_comment",
    "canonical_step16_owner_approval_comment_body",
    "effective_issue_790_invocation_plan_digests",
    "effective_issue_790_plan_contract",
    "fetch_authenticated_step16_owner_comment",
    "fetch_step16_github_json",
    "load_step16_activation_record",
    "mint_step16_activation_receipt",
    "parse_step16_owner_approval_payload",
    "require_step16_candidate_matches_payload",
    "require_step16_plan_matches_activation",
    "step16_activation_contract_from_connection",
    "step16_owner_activation_binding",
    "validate_step16_owner_activation_binding",
    "validate_step16_owner_approval_payload",
]
