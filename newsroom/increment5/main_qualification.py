from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp

from .contracts import (
    Increment5ADecisionPacket,
    Increment5ContractError,
)
from .decision import INCREMENT_5A_DECISION_PACKET
from .decision_validation import object_without_duplicate_names


MAIN_QUALIFICATION_RECORD_SCHEMA_ID = (
    "urn:newsroom:increment5a:main-qualification-record:v1"
)
MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION = (
    "increment5a-main-qualification-record-v1"
)
MAIN_QUALIFICATION_RECORD_ID = "increment5a-post-merge-main-qualification"
MAIN_QUALIFICATION_RECORD_VERSION = "increment5a-main-qualification-v1"
MAIN_QUALIFICATION_SCOPE = "POST_MERGE_INCREMENT5_IMPLEMENTATION_ADMISSION"
MAIN_QUALIFICATION_REPOSITORY = "fol2/newsroom"
MAIN_QUALIFICATION_BRANCH = "main"
MAIN_QUALIFICATION_ISSUE_NUMBER = 250
MAIN_QUALIFICATION_PULL_REQUEST_NUMBER = 255
MAIN_QUALIFICATION_WORKFLOW_NAMES = (
    "CI",
    "AUTHORITY_A2A",
    "AUTHORITY_A2B",
    "PROJECTION_B1",
    "PROJECTION_B2_B3_C1_NEO4J",
    "SDLC_EVIDENCE_SHADOW",
)
MAIN_QUALIFICATION_RECORD_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_main_qualification_record_v1.schema.json"
)
MAIN_QUALIFICATION_RECORD_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_main_qualification_record_v1.json"
)
# A later post-merge admission commit replaces None with the exact canonical
# record digest after the merged 5A commit has passed exact-main qualification.
MAIN_QUALIFICATION_RECORD_DIGEST: str | None = None
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"


MAIN_QUALIFICATION_RECORD_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": MAIN_QUALIFICATION_RECORD_SCHEMA_ID,
    "type": "object",
    "required": [
        "schema_version",
        "qualification_id",
        "qualification_version",
        "qualification_scope",
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
        "evidence",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION},
        "qualification_id": {"const": MAIN_QUALIFICATION_RECORD_ID},
        "qualification_version": {"const": MAIN_QUALIFICATION_RECORD_VERSION},
        "qualification_scope": {"const": MAIN_QUALIFICATION_SCOPE},
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
            },
        },
        "evidence": {
            "type": "object",
            "required": ["workflow_runs", "signed_decision"],
            "additionalProperties": False,
            "properties": {
                "workflow_runs": {
                    "type": "object",
                    "required": list(MAIN_QUALIFICATION_WORKFLOW_NAMES),
                    "additionalProperties": False,
                    "properties": {
                        name: {"type": "integer", "minimum": 1}
                        for name in MAIN_QUALIFICATION_WORKFLOW_NAMES
                    },
                },
                "signed_decision": {
                    "type": "object",
                    "required": [
                        "run_id",
                        "decision_digest",
                        "test_count",
                        "skip_count",
                        "required_skip_count",
                        "failure_count",
                        "error_count",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "run_id": {"type": "integer", "minimum": 1},
                        "decision_digest": {
                            "type": "string",
                            "pattern": _SHA256_PATTERN,
                        },
                        "test_count": {"type": "integer", "minimum": 1},
                        "skip_count": {"type": "integer", "minimum": 0},
                        "required_skip_count": {"const": 0},
                        "failure_count": {"const": 0},
                        "error_count": {"const": 0},
                    },
                },
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


def _parse_canonical_utc(value: str, *, field: str) -> UtcTimestamp:
    try:
        parsed = UtcTimestamp.parse(value)
    except (TypeError, ValueError) as exc:
        raise Increment5ContractError(f"{field} is not valid UTC text") from exc
    if value != parsed.to_text():
        raise Increment5ContractError(f"{field} must be canonical UTC text")
    return parsed


def _require_commit_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(_COMMIT_PATTERN, value) is None:
        raise Increment5ContractError(f"{field} must be lowercase 40-hex text")
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
class Increment5AMainQualificationRecord:
    qualified_main_commit_sha: str
    qualified_main_tree_sha: str
    qualified_at: UtcTimestamp
    approval_record_digest: str
    proposal_payload_digest: str
    proposal_record_digest: str
    proposal_contract_bundle_digest: str
    qualification_profile_schema_digest: str
    workflow_run_ids: tuple[tuple[str, int], ...]
    signed_sdlc_decision_digest: str
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
            "signed_sdlc_decision_digest",
            "record_digest",
        ):
            _require_digest(getattr(self, field_name), field=field_name)
        actual_names = tuple(name for name, _run_id in self.workflow_run_ids)
        if actual_names != MAIN_QUALIFICATION_WORKFLOW_NAMES:
            raise Increment5ContractError(
                "main qualification workflow inventory differs"
            )
        run_ids: list[int] = []
        for name, run_id in self.workflow_run_ids:
            if (
                name not in MAIN_QUALIFICATION_WORKFLOW_NAMES
                or isinstance(run_id, bool)
                or not isinstance(run_id, int)
                or run_id <= 0
            ):
                raise Increment5ContractError(
                    "main qualification workflow evidence is invalid"
                )
            run_ids.append(run_id)
        if len(set(run_ids)) != len(run_ids):
            raise Increment5ContractError(
                "main qualification workflow run identities must be distinct"
            )
        if (
            isinstance(self.test_count, bool)
            or not isinstance(self.test_count, int)
            or self.test_count <= 0
            or isinstance(self.skip_count, bool)
            or not isinstance(self.skip_count, int)
            or self.skip_count < 0
        ):
            raise Increment5ContractError(
                "main qualification signed test totals are invalid"
            )

    @property
    def workflow_run_id_by_name(self) -> dict[str, int]:
        return dict(self.workflow_run_ids)

    @property
    def qualified_main_commit_url(self) -> str:
        return (
            f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"
            f"{self.qualified_main_commit_sha}"
        )


def main_qualification_record_value(
    *,
    proposal: Increment5ADecisionPacket,
    approval_record_digest: str,
    qualified_main_commit_sha: str,
    qualified_main_tree_sha: str,
    qualified_at: UtcTimestamp,
    workflow_run_ids: Mapping[str, int],
    signed_sdlc_decision_digest: str,
    test_count: int,
    skip_count: int,
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
    decision_digest = _require_digest(
        signed_sdlc_decision_digest,
        field="signed_sdlc_decision_digest",
    )
    if set(workflow_run_ids) != set(MAIN_QUALIFICATION_WORKFLOW_NAMES):
        raise Increment5ContractError(
            "main qualification workflow inventory differs"
        )
    ordered_runs: dict[str, int] = {}
    for name in MAIN_QUALIFICATION_WORKFLOW_NAMES:
        run_id = workflow_run_ids[name]
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise Increment5ContractError(
                "main qualification workflow run identity is invalid"
            )
        ordered_runs[name] = run_id
    if len(set(ordered_runs.values())) != len(ordered_runs):
        raise Increment5ContractError(
            "main qualification workflow run identities must be distinct"
        )
    if (
        isinstance(test_count, bool)
        or not isinstance(test_count, int)
        or test_count <= 0
        or isinstance(skip_count, bool)
        or not isinstance(skip_count, int)
        or skip_count < 0
    ):
        raise Increment5ContractError(
            "main qualification signed test totals are invalid"
        )
    return {
        "schema_version": MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION,
        "qualification_id": MAIN_QUALIFICATION_RECORD_ID,
        "qualification_version": MAIN_QUALIFICATION_RECORD_VERSION,
        "qualification_scope": MAIN_QUALIFICATION_SCOPE,
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
        },
        "evidence": {
            "workflow_runs": ordered_runs,
            "signed_decision": {
                "run_id": ordered_runs["SDLC_EVIDENCE_SHADOW"],
                "decision_digest": decision_digest,
                "test_count": test_count,
                "skip_count": skip_count,
                "required_skip_count": 0,
                "failure_count": 0,
                "error_count": 0,
            },
        },
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

    proposal_value = value["proposal"]
    evidence = value["evidence"]
    workflow_runs = evidence["workflow_runs"]
    signed_decision = evidence["signed_decision"]
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
    expected_proposal = {
        "payload_digest": proposal.payload_digest,
        "record_digest": proposal.record_digest,
        "contract_bundle_digest": proposal.bundle.contract_digest,
        "qualification_profile_schema_digest": (
            _qualification_schema_digest()
        ),
    }
    if proposal_value != expected_proposal:
        raise Increment5ContractError(
            "main qualification record does not bind the exact proposal"
        )
    ordered_runs = tuple(
        (name, workflow_runs[name])
        for name in MAIN_QUALIFICATION_WORKFLOW_NAMES
    )
    if signed_decision["run_id"] != dict(ordered_runs)[
        "SDLC_EVIDENCE_SHADOW"
    ]:
        raise Increment5ContractError(
            "signed decision run differs from workflow evidence"
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
        workflow_run_ids=ordered_runs,
        signed_sdlc_decision_digest=signed_decision["decision_digest"],
        test_count=signed_decision["test_count"],
        skip_count=signed_decision["skip_count"],
        record_digest=digest_bytes(data),
    )
