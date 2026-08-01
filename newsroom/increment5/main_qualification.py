from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp
from scripts.sdlc.contracts import SdlcContract, load_contract
from scripts.sdlc.shadow_decision import (
    ShadowDecision,
    ShadowDecisionError,
    validate_shadow_decision,
)

from .contracts import (
    Increment5ADecisionPacket,
    Increment5ContractError,
)
from .decision import INCREMENT_5A_DECISION_PACKET
from .decision_validation import object_without_duplicate_names


MAIN_QUALIFICATION_RECORD_SCHEMA_ID = (
    "urn:newsroom:increment5a:main-qualification-record:v2"
)
MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION = (
    "increment5a-main-qualification-record-v2"
)
MAIN_QUALIFICATION_RECORD_ID = "increment5a-post-merge-main-qualification"
MAIN_QUALIFICATION_RECORD_VERSION = "increment5a-main-qualification-v2"
MAIN_QUALIFICATION_SCOPE = "POST_MERGE_INCREMENT5_IMPLEMENTATION_ADMISSION"
MAIN_QUALIFICATION_EFFECT = "IMPLEMENTATION_OF_ISSUES_251_254_ONLY"
MAIN_QUALIFICATION_NON_EFFECTS = (
    "CANARY",
    "EXTERNAL_EMBEDDING_API_CALLS",
    "LIVE_SOURCE_EXECUTION",
    "PROTECTED_CONTENT_VECTORS",
    "PROVIDER_SPENDING",
    "PUBLICATION",
    "PUBLIC_EFFECT",
    "PRODUCTION_ACTIVATION",
    "SHADOW",
)
MAIN_QUALIFICATION_REPOSITORY = "fol2/newsroom"
MAIN_QUALIFICATION_REPOSITORY_ID = 1153895518
MAIN_QUALIFICATION_BRANCH = "main"
MAIN_QUALIFICATION_REF = "refs/heads/main"
MAIN_QUALIFICATION_ISSUE_NUMBER = 250
MAIN_QUALIFICATION_PULL_REQUEST_NUMBER = 255
MAIN_QUALIFICATION_WORKFLOW_SPECS: dict[str, tuple[int, str]] = {
    "CI": (232327316, "CI"),
    "AUTHORITY_A2A": (315268483, "Authority A2a"),
    "AUTHORITY_A2B": (315287552, "Authority A2b"),
    "PROJECTION_B1": (317445524, "Projection B1"),
    "PROJECTION_B2_B3_C1_NEO4J": (
        317681630,
        "Projection B2/B3/C1 Neo4j",
    ),
    "SDLC_EVIDENCE_SHADOW": (318982302, "SDLC Evidence Shadow"),
}
MAIN_QUALIFICATION_WORKFLOW_EVENTS: dict[str, str] = {
    "CI": "push",
    "AUTHORITY_A2A": "push",
    "AUTHORITY_A2B": "push",
    "PROJECTION_B1": "push",
    "PROJECTION_B2_B3_C1_NEO4J": "push",
    "SDLC_EVIDENCE_SHADOW": "workflow_dispatch",
}
MAIN_QUALIFICATION_WORKFLOW_NAMES = tuple(MAIN_QUALIFICATION_WORKFLOW_SPECS)
MAIN_QUALIFICATION_RECORD_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_main_qualification_record_v2.schema.json"
)
MAIN_QUALIFICATION_RECORD_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_main_qualification_record_v2.json"
)
# A later post-merge admission commit replaces None with the exact canonical
# record digest after the merged 5A commit has passed exact-main qualification.
MAIN_QUALIFICATION_RECORD_DIGEST: str | None = None
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_SDLC_CONTRACT: SdlcContract = load_contract(
    Path(__file__).resolve().parents[2]
)


def _canonical_decision_validator_factory(
    *,
    validator: Callable[..., ShadowDecision] = validate_shadow_decision,
    contract: object = _SDLC_CONTRACT,
) -> Callable[[object], ShadowDecision]:
    captured_validator = validator
    captured_contract = contract

    def validate(value: object) -> ShadowDecision:
        return captured_validator(value, contract=captured_contract)

    return validate


_CANONICAL_DECISION_VALIDATOR = _canonical_decision_validator_factory()

def _workflow_attempt_schema(
    *,
    workflow_id: int,
    workflow_name: str,
    event_name: str,
) -> dict[str, object]:
    return {
        "type": "object",
        "required": [
            "workflow_id",
            "workflow_name",
            "run_id",
            "run_attempt",
            "run_number",
            "repository",
            "repository_id",
            "event",
            "ref",
            "head_branch",
            "head_sha",
            "head_tree_sha",
            "workflow_sha",
            "workflow_ref",
            "status",
            "conclusion",
            "api_url",
            "html_url",
            "created_at",
            "run_started_at",
            "updated_at",
        ],
        "additionalProperties": False,
        "properties": {
            "workflow_id": {"const": workflow_id},
            "workflow_name": {"const": workflow_name},
            "run_id": {"type": "integer", "minimum": 1},
            "run_attempt": {"type": "integer", "minimum": 1},
            "run_number": {"type": "integer", "minimum": 1},
            "repository": {"const": MAIN_QUALIFICATION_REPOSITORY},
            "repository_id": {"const": MAIN_QUALIFICATION_REPOSITORY_ID},
            "event": {"const": event_name},
            "ref": {"const": MAIN_QUALIFICATION_REF},
            "head_branch": {"const": MAIN_QUALIFICATION_BRANCH},
            "head_sha": {"type": "string", "pattern": _COMMIT_PATTERN},
            "head_tree_sha": {
                "type": "string",
                "pattern": _COMMIT_PATTERN,
            },
            "workflow_sha": {"type": "string", "pattern": _COMMIT_PATTERN},
            "workflow_ref": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
            },
            "status": {"const": "completed"},
            "conclusion": {"const": "success"},
            "api_url": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
            },
            "html_url": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
            },
            "created_at": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
            },
            "run_started_at": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
            },
            "updated_at": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
            },
        },
    }


MAIN_QUALIFICATION_RECORD_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": MAIN_QUALIFICATION_RECORD_SCHEMA_ID,
    "type": "object",
    "required": [
        "schema_version",
        "qualification_id",
        "qualification_version",
        "qualification_scope",
        "qualification_effect",
        "non_effects",
        "repository",
        "branch",
        "issue_number",
        "pull_request_number",
        "qualified_main_commit_sha",
        "qualified_main_tree_sha",
        "qualified_main_commit_url",
        "qualified_at",
        "approval_record_digest",
        "proposal",
        "workflow_attempts",
        "signed_decision",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {
            "const": MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION
        },
        "qualification_id": {"const": MAIN_QUALIFICATION_RECORD_ID},
        "qualification_version": {
            "const": MAIN_QUALIFICATION_RECORD_VERSION
        },
        "qualification_scope": {"const": MAIN_QUALIFICATION_SCOPE},
        "qualification_effect": {"const": MAIN_QUALIFICATION_EFFECT},
        "non_effects": {"const": list(MAIN_QUALIFICATION_NON_EFFECTS)},
        "repository": {"const": MAIN_QUALIFICATION_REPOSITORY},
        "branch": {"const": MAIN_QUALIFICATION_BRANCH},
        "issue_number": {"const": MAIN_QUALIFICATION_ISSUE_NUMBER},
        "pull_request_number": {
            "const": MAIN_QUALIFICATION_PULL_REQUEST_NUMBER
        },
        "qualified_main_commit_sha": {
            "type": "string",
            "pattern": _COMMIT_PATTERN,
        },
        "qualified_main_tree_sha": {
            "type": "string",
            "pattern": _COMMIT_PATTERN,
        },
        "qualified_main_commit_url": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
        },
        "qualified_at": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
        "approval_record_digest": {
            "type": "string",
            "pattern": _SHA256_PATTERN,
        },
        "proposal": {
            "type": "object",
            "required": [
                "payload_digest",
                "record_digest",
                "contract_bundle_digest",
                "qualification_profile_schema_digest",
                "main_qualification_record_schema_digest",
            ],
            "additionalProperties": False,
            "properties": {
                "payload_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "record_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "contract_bundle_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "qualification_profile_schema_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "main_qualification_record_schema_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
            },
        },
        "workflow_attempts": {
            "type": "object",
            "required": list(MAIN_QUALIFICATION_WORKFLOW_NAMES),
            "additionalProperties": False,
            "properties": {
                name: _workflow_attempt_schema(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    event_name=(
                        MAIN_QUALIFICATION_WORKFLOW_EVENTS[name]
                    ),
                )
                for name, (
                    workflow_id,
                    workflow_name,
                ) in MAIN_QUALIFICATION_WORKFLOW_SPECS.items()
            },
        },
        "signed_decision": {
            "type": "object",
            "required": [
                "workflow_run_id",
                "workflow_run_attempt",
                "decision_document_digest",
                "decision_identity",
                "result",
                "result_reason",
                "evaluated_sha",
                "evaluated_tree_sha",
                "test_count",
                "skip_count",
                "required_skip_count",
                "failure_count",
                "error_count",
                "decision_document",
            ],
            "additionalProperties": False,
            "properties": {
                "workflow_run_id": {
                    "type": "integer",
                    "minimum": 1,
                },
                "workflow_run_attempt": {
                    "type": "integer",
                    "minimum": 1,
                },
                "decision_document_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "decision_identity": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "result": {"const": "PASS"},
                "result_reason": {"const": "PASS:decision"},
                "evaluated_sha": {
                    "type": "string",
                    "pattern": _COMMIT_PATTERN,
                },
                "evaluated_tree_sha": {
                    "type": "string",
                    "pattern": _COMMIT_PATTERN,
                },
                "test_count": {
                    "type": "integer",
                    "minimum": 1,
                },
                "skip_count": {
                    "type": "integer",
                    "minimum": 0,
                },
                "required_skip_count": {"const": 0},
                "failure_count": {"const": 0},
                "error_count": {"const": 0},
                "decision_document": {"type": "object"},
            },
        },
    },
}
Draft202012Validator.check_schema(MAIN_QUALIFICATION_RECORD_SCHEMA)
_MAIN_QUALIFICATION_VALIDATOR = Draft202012Validator(
    MAIN_QUALIFICATION_RECORD_SCHEMA
)
MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST = digest_bytes(
    canonical_json_bytes(MAIN_QUALIFICATION_RECORD_SCHEMA)
)


def _require_schema_artifact() -> None:
    try:
        data = MAIN_QUALIFICATION_RECORD_SCHEMA_PATH.read_bytes()
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            "cannot load Increment 5A main-qualification schema artifact"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            "main-qualification schema artifact must be an object"
        )
    if (
        data != canonical_json_bytes(value)
        or value != MAIN_QUALIFICATION_RECORD_SCHEMA
        or digest_bytes(data) != MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
    ):
        raise Increment5ContractError(
            "main-qualification schema artifact differs from repository code"
        )


_require_schema_artifact()


def _qualification_schema_digest() -> str:
    from .profiles import QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST

    return QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST


def _parse_canonical_utc(value: object, *, field: str) -> UtcTimestamp:
    if not isinstance(value, str):
        raise Increment5ContractError(f"{field} is not valid UTC text")
    try:
        parsed = UtcTimestamp.parse(value)
    except (TypeError, ValueError) as exc:
        raise Increment5ContractError(f"{field} is not valid UTC text") from exc
    if value != parsed.to_text():
        raise Increment5ContractError(f"{field} must be canonical UTC text")
    return parsed


def _require_commit_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(_COMMIT_PATTERN, value) is None:
        raise Increment5ContractError(
            f"{field} must be lowercase 40-hex text"
        )
    if value == "0" * 40:
        raise Increment5ContractError(f"{field} cannot be the null commit")
    return value


def _require_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise Increment5ContractError(f"{field} must be a digest")
    try:
        return validate_sha256_digest(value, field=field)
    except ValueError as exc:
        raise Increment5ContractError(f"{field} is not canonical") from exc


def _require_positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Increment5ContractError(f"{field} must be a positive integer")
    return value


def _require_nonnegative_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Increment5ContractError(
            f"{field} must be a nonnegative integer"
        )
    return value


def _schema_errors(value: Mapping[str, Any]) -> tuple[str, ...]:
    errors = sorted(
        _MAIN_QUALIFICATION_VALIDATOR.iter_errors(value),
        key=lambda item: [str(component) for component in item.absolute_path],
    )
    return tuple(
        (
            "/".join(str(component) for component in error.absolute_path)
            or "<root>"
        )
        + ": "
        + error.message
        for error in errors
    )


@dataclass(frozen=True, slots=True)
class WorkflowAttemptEvidence:
    key: str
    workflow_id: int
    workflow_name: str
    event: str
    run_id: int
    run_attempt: int
    run_number: int
    head_sha: str
    head_tree_sha: str
    workflow_sha: str
    workflow_ref: str
    api_url: str
    html_url: str
    created_at: UtcTimestamp
    run_started_at: UtcTimestamp
    updated_at: UtcTimestamp

    def __post_init__(self) -> None:
        expected = MAIN_QUALIFICATION_WORKFLOW_SPECS.get(self.key)
        if expected != (self.workflow_id, self.workflow_name):
            raise Increment5ContractError(
                "workflow attempt identity differs from permanent workflow"
            )
        expected_event = MAIN_QUALIFICATION_WORKFLOW_EVENTS.get(self.key)
        if self.event != expected_event:
            raise Increment5ContractError(
                "workflow attempt event differs from permanent workflow"
            )
        for field_name in ("run_id", "run_attempt", "run_number"):
            _require_positive_integer(
                getattr(self, field_name),
                field=f"workflow_attempt.{field_name}",
            )
        for field_name in ("head_sha", "head_tree_sha", "workflow_sha"):
            _require_commit_sha(
                getattr(self, field_name),
                field=f"workflow_attempt.{field_name}",
            )
        expected_api_url = (
            f"https://api.github.com/repos/{MAIN_QUALIFICATION_REPOSITORY}/"
            f"actions/runs/{self.run_id}/attempts/{self.run_attempt}"
        )
        expected_html_url = (
            f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/"
            f"actions/runs/{self.run_id}"
        )
        if self.api_url != expected_api_url:
            raise Increment5ContractError(
                "workflow attempt API URL differs"
            )
        if self.html_url != expected_html_url:
            raise Increment5ContractError(
                "workflow attempt HTML URL differs"
            )
        if not (
            self.workflow_ref.startswith(
                f"{MAIN_QUALIFICATION_REPOSITORY}/"
            )
            and self.workflow_ref.endswith(f"@{MAIN_QUALIFICATION_REF}")
        ):
            raise Increment5ContractError(
                "workflow ref is not exact main"
            )
        if self.created_at.value > self.run_started_at.value:
            raise Increment5ContractError(
                "workflow attempt starts before creation"
            )
        if self.run_started_at.value > self.updated_at.value:
            raise Increment5ContractError(
                "workflow attempt completes before start"
            )

    @property
    def identity(self) -> tuple[int, int]:
        return self.run_id, self.run_attempt


@dataclass(frozen=True, slots=True)
class Increment5AMainQualificationRecord:
    qualified_main_commit_sha: str
    qualified_main_tree_sha: str
    qualified_at: UtcTimestamp
    approval_record_digest: str
    proposal_payload_digest: str
    proposal_record_digest: str
    proposal_contract_bundle_digest: str
    qualification_profile_schema_digest: str
    main_qualification_record_schema_digest: str
    workflow_attempts: tuple[WorkflowAttemptEvidence, ...]
    decision_document_digest: str
    decision_identity: str
    test_count: int
    skip_count: int
    record_digest: str

    def __post_init__(self) -> None:
        _require_commit_sha(
            self.qualified_main_commit_sha,
            field="qualified_main_commit_sha",
        )
        _require_commit_sha(
            self.qualified_main_tree_sha,
            field="qualified_main_tree_sha",
        )
        if not isinstance(self.qualified_at, UtcTimestamp):
            raise Increment5ContractError(
                "main qualification time must be typed UTC"
            )
        for field_name in (
            "approval_record_digest",
            "proposal_payload_digest",
            "proposal_record_digest",
            "proposal_contract_bundle_digest",
            "qualification_profile_schema_digest",
            "main_qualification_record_schema_digest",
            "decision_document_digest",
            "decision_identity",
            "record_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        if (
            self.main_qualification_record_schema_digest
            != MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
        ):
            raise Increment5ContractError(
                "main qualification schema digest differs"
            )
        actual_names = tuple(item.key for item in self.workflow_attempts)
        if actual_names != MAIN_QUALIFICATION_WORKFLOW_NAMES:
            raise Increment5ContractError(
                "main qualification workflow inventory differs"
            )
        identities = [item.identity for item in self.workflow_attempts]
        if len(set(identities)) != len(identities):
            raise Increment5ContractError(
                "workflow attempt identities must be distinct"
            )
        for attempt in self.workflow_attempts:
            if (
                attempt.head_sha != self.qualified_main_commit_sha
                or attempt.workflow_sha != self.qualified_main_commit_sha
                or attempt.head_tree_sha != self.qualified_main_tree_sha
            ):
                raise Increment5ContractError(
                    "workflow attempt is not bound to qualified main"
                )
        _require_positive_integer(self.test_count, field="test_count")
        _require_nonnegative_integer(self.skip_count, field="skip_count")

    @property
    def workflow_attempt_by_name(self) -> dict[str, WorkflowAttemptEvidence]:
        return {item.key: item for item in self.workflow_attempts}

    @property
    def qualified_main_commit_url(self) -> str:
        return (
            f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"
            f"{self.qualified_main_commit_sha}"
        )


def _parse_workflow_attempt(
    *,
    key: str,
    value: Mapping[str, Any],
    qualified_main_commit_sha: str,
    qualified_main_tree_sha: str,
) -> WorkflowAttemptEvidence:
    workflow_id, workflow_name = MAIN_QUALIFICATION_WORKFLOW_SPECS[key]
    if value.get("repository") != MAIN_QUALIFICATION_REPOSITORY:
        raise Increment5ContractError(
            "workflow attempt repository differs"
        )
    if value.get("repository_id") != MAIN_QUALIFICATION_REPOSITORY_ID:
        raise Increment5ContractError(
            "workflow attempt repository identity differs"
        )
    expected_event = MAIN_QUALIFICATION_WORKFLOW_EVENTS[key]
    if value.get("event") != expected_event:
        raise Increment5ContractError(
            f"workflow attempt event differs for {key}"
        )
    if value.get("ref") != MAIN_QUALIFICATION_REF:
        raise Increment5ContractError(
            "workflow attempt ref differs from main"
        )
    if value.get("head_branch") != MAIN_QUALIFICATION_BRANCH:
        raise Increment5ContractError(
            "workflow attempt branch differs from main"
        )
    if value.get("status") != "completed" or value.get("conclusion") != "success":
        raise Increment5ContractError(
            "workflow attempt did not complete successfully"
        )
    attempt = WorkflowAttemptEvidence(
        key=key,
        workflow_id=_require_positive_integer(
            value.get("workflow_id"),
            field=f"workflow_attempts.{key}.workflow_id",
        ),
        workflow_name=str(value.get("workflow_name")),
        event=str(value.get("event")),
        run_id=_require_positive_integer(
            value.get("run_id"),
            field=f"workflow_attempts.{key}.run_id",
        ),
        run_attempt=_require_positive_integer(
            value.get("run_attempt"),
            field=f"workflow_attempts.{key}.run_attempt",
        ),
        run_number=_require_positive_integer(
            value.get("run_number"),
            field=f"workflow_attempts.{key}.run_number",
        ),
        head_sha=_require_commit_sha(
            value.get("head_sha"),
            field=f"workflow_attempts.{key}.head_sha",
        ),
        head_tree_sha=_require_commit_sha(
            value.get("head_tree_sha"),
            field=f"workflow_attempts.{key}.head_tree_sha",
        ),
        workflow_sha=_require_commit_sha(
            value.get("workflow_sha"),
            field=f"workflow_attempts.{key}.workflow_sha",
        ),
        workflow_ref=str(value.get("workflow_ref")),
        api_url=str(value.get("api_url")),
        html_url=str(value.get("html_url")),
        created_at=_parse_canonical_utc(
            value.get("created_at"),
            field=f"workflow_attempts.{key}.created_at",
        ),
        run_started_at=_parse_canonical_utc(
            value.get("run_started_at"),
            field=f"workflow_attempts.{key}.run_started_at",
        ),
        updated_at=_parse_canonical_utc(
            value.get("updated_at"),
            field=f"workflow_attempts.{key}.updated_at",
        ),
    )
    if (attempt.workflow_id, attempt.workflow_name) != (
        workflow_id,
        workflow_name,
    ):
        raise Increment5ContractError(
            "workflow attempt differs from permanent workflow"
        )
    if (
        attempt.head_sha != qualified_main_commit_sha
        or attempt.workflow_sha != qualified_main_commit_sha
        or attempt.head_tree_sha != qualified_main_tree_sha
    ):
        raise Increment5ContractError(
            "workflow attempt is not bound to qualified main"
        )
    return attempt


def _parse_workflow_attempts(
    *,
    value: Mapping[str, Any],
    qualified_main_commit_sha: str,
    qualified_main_tree_sha: str,
) -> tuple[WorkflowAttemptEvidence, ...]:
    attempts = tuple(
        _parse_workflow_attempt(
            key=key,
            value=_require_mapping(
                value[key],
                field=f"workflow_attempts.{key}",
            ),
            qualified_main_commit_sha=qualified_main_commit_sha,
            qualified_main_tree_sha=qualified_main_tree_sha,
        )
        for key in MAIN_QUALIFICATION_WORKFLOW_NAMES
    )
    identities = [item.identity for item in attempts]
    if len(set(identities)) != len(identities):
        raise Increment5ContractError(
            "workflow attempt identities must be distinct"
        )
    return attempts


def _require_mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    return value


def _validate_decision_document(
    *,
    summary: Mapping[str, Any] | None,
    document: Mapping[str, Any],
    qualified_main_commit_sha: str,
    qualified_main_tree_sha: str,
    sdlc_attempt: WorkflowAttemptEvidence,
    _validate: Callable[[object], ShadowDecision] = (
        _CANONICAL_DECISION_VALIDATOR
    ),
) -> tuple[dict[str, object], str, str, int, int]:
    document_copy = deepcopy(dict(document))
    document_digest = digest_bytes(canonical_json_bytes(document_copy))
    if (
        summary is not None
        and summary.get("decision_document_digest") != document_digest
    ):
        raise Increment5ContractError(
            "signed decision document digest differs"
        )

    try:
        validated = _validate(document_copy)
    except ShadowDecisionError as exc:
        raise Increment5ContractError(
            "signed decision is not canonical SDLC evidence"
        ) from exc

    canonical_document = validated.as_dict()
    if canonical_document != document_copy:
        raise Increment5ContractError(
            "signed decision differs from canonical SDLC output"
        )
    if validated.result != "PASS":
        raise Increment5ContractError(
            "signed decision result is not PASS"
        )
    if validated.result_reason != "PASS:decision":
        raise Increment5ContractError(
            "signed decision reason is not PASS"
        )
    if validated.first_failure is not None:
        raise Increment5ContractError(
            "PASS decision cannot retain a first failure"
        )

    decision_identity = _require_digest(
        validated.decision_identity,
        field="signed_decision.decision_identity",
    )
    context = validated.context.as_dict()
    if validated.event is None:
        raise Increment5ContractError(
            "signed PASS decision has no workflow event"
        )
    event = validated.event.as_dict()
    expected_event = sdlc_attempt.event
    for field_name, expected in (
        ("repository", MAIN_QUALIFICATION_REPOSITORY),
        ("event_name", expected_event),
        ("ref", MAIN_QUALIFICATION_REF),
        ("evaluated_sha", qualified_main_commit_sha),
        ("evaluated_tree_sha", qualified_main_tree_sha),
    ):
        if context.get(field_name) != expected:
            raise Increment5ContractError(
                f"signed decision context {field_name} differs"
            )
        if event.get(field_name) != expected:
            raise Increment5ContractError(
                f"signed decision event {field_name} differs"
            )
    if context.get("workflow_sha") != qualified_main_commit_sha:
        raise Increment5ContractError(
            "signed decision workflow SHA differs from qualified main"
        )
    if context.get("run_id") != sdlc_attempt.run_id:
        raise Increment5ContractError(
            "signed decision run differs from SDLC attempt"
        )
    if context.get("run_attempt") != sdlc_attempt.run_attempt:
        raise Increment5ContractError(
            "signed decision attempt differs from SDLC attempt"
        )
    if context.get("workflow_ref") != sdlc_attempt.workflow_ref:
        raise Increment5ContractError(
            "signed decision workflow ref differs"
        )

    test_count = _require_positive_integer(
        validated.totals.test_count,
        field="signed_decision.test_count",
    )
    skip_count = _require_nonnegative_integer(
        validated.totals.skip_count,
        field="signed_decision.skip_count",
    )
    if (
        validated.totals.required_skip_count != 0
        or validated.totals.failure_count != 0
        or validated.totals.error_count != 0
    ):
        raise Increment5ContractError(
            "signed PASS decision has nonzero failure totals"
        )

    gates = tuple(
        gate
        for lane in validated.lanes
        for gate in lane.receipt.gate_decisions
    )
    if not gates or any(gate.result != "PASS" for gate in gates):
        raise Increment5ContractError(
            "signed PASS decision contains a non-PASS gate"
        )
    source_integrity = tuple(
        gate for gate in gates if gate.gate_id == "source-integrity"
    )
    if len(source_integrity) != 1:
        raise Increment5ContractError(
            "signed PASS decision lacks exact source-integrity evidence"
        )

    expected_summary = {
        "workflow_run_id": sdlc_attempt.run_id,
        "workflow_run_attempt": sdlc_attempt.run_attempt,
        "decision_document_digest": document_digest,
        "decision_identity": decision_identity,
        "result": "PASS",
        "result_reason": "PASS:decision",
        "evaluated_sha": qualified_main_commit_sha,
        "evaluated_tree_sha": qualified_main_tree_sha,
        "test_count": test_count,
        "skip_count": skip_count,
        "required_skip_count": 0,
        "failure_count": 0,
        "error_count": 0,
    }
    if summary is not None:
        if {
            key: summary.get(key)
            for key in expected_summary
        } != expected_summary:
            raise Increment5ContractError(
                "signed decision summary differs from canonical artifact"
            )
        if summary.get("decision_document") != canonical_document:
            raise Increment5ContractError(
                "signed decision document differs from canonical artifact"
            )
    return (
        canonical_document,
        document_digest,
        decision_identity,
        test_count,
        skip_count,
    )

def _signed_decision_value(
    *,
    document: Mapping[str, Any],
    qualified_main_commit_sha: str,
    qualified_main_tree_sha: str,
    sdlc_attempt: WorkflowAttemptEvidence,
) -> dict[str, object]:
    (
        canonical_document,
        document_digest,
        decision_identity,
        test_count,
        skip_count,
    ) = _validate_decision_document(
        summary=None,
        document=document,
        qualified_main_commit_sha=qualified_main_commit_sha,
        qualified_main_tree_sha=qualified_main_tree_sha,
        sdlc_attempt=sdlc_attempt,
    )
    return {
        "workflow_run_id": sdlc_attempt.run_id,
        "workflow_run_attempt": sdlc_attempt.run_attempt,
        "decision_document_digest": document_digest,
        "decision_identity": decision_identity,
        "result": "PASS",
        "result_reason": "PASS:decision",
        "evaluated_sha": qualified_main_commit_sha,
        "evaluated_tree_sha": qualified_main_tree_sha,
        "test_count": test_count,
        "skip_count": skip_count,
        "required_skip_count": 0,
        "failure_count": 0,
        "error_count": 0,
        "decision_document": canonical_document,
    }

def main_qualification_record_value(
    *,
    proposal: Increment5ADecisionPacket,
    approval_record_digest: str,
    qualified_main_commit_sha: str,
    qualified_main_tree_sha: str,
    qualified_at: UtcTimestamp,
    workflow_attempts: Mapping[str, Mapping[str, Any]],
    decision_document: Mapping[str, Any],
) -> dict[str, object]:
    if not isinstance(proposal, Increment5ADecisionPacket):
        raise Increment5ContractError(
            "main qualification builder requires a typed proposal"
        )
    if not isinstance(qualified_at, UtcTimestamp):
        raise Increment5ContractError(
            "main qualification builder requires typed UTC time"
        )
    commit_sha = _require_commit_sha(
        qualified_main_commit_sha,
        field="qualified_main_commit_sha",
    )
    tree_sha = _require_commit_sha(
        qualified_main_tree_sha,
        field="qualified_main_tree_sha",
    )
    approval_digest = _require_digest(
        approval_record_digest,
        field="approval_record_digest",
    )
    if set(workflow_attempts) != set(MAIN_QUALIFICATION_WORKFLOW_NAMES):
        raise Increment5ContractError(
            "main qualification workflow inventory differs"
        )
    ordered_attempt_values = {
        name: deepcopy(dict(workflow_attempts[name]))
        for name in MAIN_QUALIFICATION_WORKFLOW_NAMES
    }
    parsed_attempts = _parse_workflow_attempts(
        value=ordered_attempt_values,
        qualified_main_commit_sha=commit_sha,
        qualified_main_tree_sha=tree_sha,
    )
    sdlc_attempt = {
        item.key: item for item in parsed_attempts
    }["SDLC_EVIDENCE_SHADOW"]
    signed_decision = _signed_decision_value(
        document=decision_document,
        qualified_main_commit_sha=commit_sha,
        qualified_main_tree_sha=tree_sha,
        sdlc_attempt=sdlc_attempt,
    )
    return {
        "schema_version": MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION,
        "qualification_id": MAIN_QUALIFICATION_RECORD_ID,
        "qualification_version": MAIN_QUALIFICATION_RECORD_VERSION,
        "qualification_scope": MAIN_QUALIFICATION_SCOPE,
        "qualification_effect": MAIN_QUALIFICATION_EFFECT,
        "non_effects": list(MAIN_QUALIFICATION_NON_EFFECTS),
        "repository": MAIN_QUALIFICATION_REPOSITORY,
        "branch": MAIN_QUALIFICATION_BRANCH,
        "issue_number": MAIN_QUALIFICATION_ISSUE_NUMBER,
        "pull_request_number": MAIN_QUALIFICATION_PULL_REQUEST_NUMBER,
        "qualified_main_commit_sha": commit_sha,
        "qualified_main_tree_sha": tree_sha,
        "qualified_main_commit_url": (
            f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"
            f"{commit_sha}"
        ),
        "qualified_at": qualified_at.to_text(),
        "approval_record_digest": approval_digest,
        "proposal": {
            "payload_digest": proposal.payload_digest,
            "record_digest": proposal.record_digest,
            "contract_bundle_digest": proposal.bundle.contract_digest,
            "qualification_profile_schema_digest": (
                _qualification_schema_digest()
            ),
            "main_qualification_record_schema_digest": (
                MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
            ),
        },
        "workflow_attempts": ordered_attempt_values,
        "signed_decision": signed_decision,
    }


def load_increment5a_main_qualification_record(
    path: Path,
    *,
    approval_record_digest: str,
    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,
) -> Increment5AMainQualificationRecord:
    expected_approval_digest = _require_digest(
        approval_record_digest,
        field="approval_record_digest",
    )
    try:
        data = path.read_bytes()
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            f"cannot read Increment 5A main qualification record: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            "main qualification record root must be an object"
        )
    if data != canonical_json_bytes(value):
        raise Increment5ContractError(
            "main qualification record must be exact canonical JSON"
        )
    errors = _schema_errors(value)
    if errors:
        raise Increment5ContractError(
            "main qualification record schema validation failed: " + errors[0]
        )

    commit_sha = _require_commit_sha(
        value["qualified_main_commit_sha"],
        field="qualified_main_commit_sha",
    )
    tree_sha = _require_commit_sha(
        value["qualified_main_tree_sha"],
        field="qualified_main_tree_sha",
    )
    expected_url = (
        f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"
        f"{commit_sha}"
    )
    if value["qualified_main_commit_url"] != expected_url:
        raise Increment5ContractError(
            "main qualification commit URL differs"
        )
    if value["approval_record_digest"] != expected_approval_digest:
        raise Increment5ContractError(
            "main qualification approval digest differs"
        )
    proposal_value = _require_mapping(
        value["proposal"],
        field="main_qualification.proposal",
    )
    expected_proposal = {
        "payload_digest": proposal.payload_digest,
        "record_digest": proposal.record_digest,
        "contract_bundle_digest": proposal.bundle.contract_digest,
        "qualification_profile_schema_digest": (
            _qualification_schema_digest()
        ),
        "main_qualification_record_schema_digest": (
            MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
        ),
    }
    if dict(proposal_value) != expected_proposal:
        raise Increment5ContractError(
            "main qualification record does not bind the exact proposal"
        )
    attempts = _parse_workflow_attempts(
        value=_require_mapping(
            value["workflow_attempts"],
            field="main_qualification.workflow_attempts",
        ),
        qualified_main_commit_sha=commit_sha,
        qualified_main_tree_sha=tree_sha,
    )
    sdlc_attempt = {
        item.key: item for item in attempts
    }["SDLC_EVIDENCE_SHADOW"]
    signed_decision = _require_mapping(
        value["signed_decision"],
        field="main_qualification.signed_decision",
    )
    decision_document = _require_mapping(
        signed_decision["decision_document"],
        field="main_qualification.signed_decision.decision_document",
    )
    (
        _canonical_document,
        decision_document_digest,
        decision_identity,
        test_count,
        skip_count,
    ) = _validate_decision_document(
        summary=signed_decision,
        document=decision_document,
        qualified_main_commit_sha=commit_sha,
        qualified_main_tree_sha=tree_sha,
        sdlc_attempt=sdlc_attempt,
    )
    return Increment5AMainQualificationRecord(
        qualified_main_commit_sha=commit_sha,
        qualified_main_tree_sha=tree_sha,
        qualified_at=_parse_canonical_utc(
            value["qualified_at"],
            field="qualified_at",
        ),
        approval_record_digest=expected_approval_digest,
        proposal_payload_digest=proposal_value["payload_digest"],
        proposal_record_digest=proposal_value["record_digest"],
        proposal_contract_bundle_digest=proposal_value[
            "contract_bundle_digest"
        ],
        qualification_profile_schema_digest=proposal_value[
            "qualification_profile_schema_digest"
        ],
        main_qualification_record_schema_digest=proposal_value[
            "main_qualification_record_schema_digest"
        ],
        workflow_attempts=attempts,
        decision_document_digest=decision_document_digest,
        decision_identity=decision_identity,
        test_count=test_count,
        skip_count=skip_count,
        record_digest=digest_bytes(data),
    )
