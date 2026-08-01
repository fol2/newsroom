from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator
import requests

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import UtcTimestamp

from .contracts import (
    Increment5ADecisionPacket,
    Increment5ContractError,
    Increment5ProfileError,
    RetrievalComponentKind,
    RetrievalProfileKind,
)
from .decision import INCREMENT_5A_DECISION_PACKET
from .decision_validation import (
    object_without_duplicate_names,
    require_digest,
    require_exact_keys,
    require_integer,
    require_mapping,
    require_string,
)


APPROVAL_ATTESTATION_SCHEMA_ID = (
    "urn:newsroom:increment5a:owner-approval-attestation:v1"
)
APPROVAL_ATTESTATION_SCHEMA_VERSION = (
    "increment5a-owner-approval-attestation-v1"
)
APPROVAL_ATTESTATION_ID = "increment5a-production-retrieval-owner-approval"
APPROVAL_ATTESTATION_VERSION = "increment5a-owner-approval-v1"
APPROVAL_EFFECT = "IMPLEMENTATION_AND_PRODUCTION_QUALIFICATION_ONLY"
APPROVAL_REPOSITORY = "fol2/newsroom"
APPROVAL_OWNER_GITHUB_LOGIN = "fol2"
APPROVAL_OWNER_GITHUB_USER_ID = 105634418
APPROVAL_ISSUE_NUMBER = 250
APPROVAL_PULL_REQUEST_NUMBER = 255
APPROVAL_NON_EFFECTS = (
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
APPROVAL_ATTESTATION_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_owner_approval_attestation_v1.schema.json"
)
GITHUB_APPROVAL_VERIFIER_CONTRACT = "github-issue-comment-approval-verifier-v1"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_APPROVAL_TIMEOUT_SECONDS = 10.0
GITHUB_APPROVAL_MAX_RESPONSE_BYTES = 128 * 1024
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_BEARER_TOKEN = re.compile(r"^[^\s\x00-\x1f\x7f]{1,4096}$")


APPROVAL_ATTESTATION_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": APPROVAL_ATTESTATION_SCHEMA_ID,
    "type": "object",
    "required": [
        "schema_version",
        "attestation_id",
        "attestation_version",
        "approval_effect",
        "non_effects",
        "proposal",
        "owner",
        "approved_at",
        "repository",
        "issue_number",
        "pull_request_number",
        "evidence",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": APPROVAL_ATTESTATION_SCHEMA_VERSION},
        "attestation_id": {"const": APPROVAL_ATTESTATION_ID},
        "attestation_version": {"const": APPROVAL_ATTESTATION_VERSION},
        "approval_effect": {"const": APPROVAL_EFFECT},
        "non_effects": {"const": list(APPROVAL_NON_EFFECTS)},
        "proposal": {
            "type": "object",
            "required": [
                "decision_id",
                "payload_digest",
                "record_digest",
                "contract_bundle_digest",
                "proposal_production_profile_schema_digest",
                "qualification_production_profile_schema_digest",
                "fixture_replay_profile_schema_digest",
                "component_identity_digests",
            ],
            "additionalProperties": False,
            "properties": {
                "decision_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
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
                "proposal_production_profile_schema_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "qualification_production_profile_schema_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "fixture_replay_profile_schema_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "component_identity_digests": {
                    "type": "object",
                    "required": [
                        item.value for item in RetrievalComponentKind
                    ],
                    "additionalProperties": False,
                    "properties": {
                        item.value: {
                            "type": "string",
                            "pattern": _SHA256_PATTERN,
                        }
                        for item in RetrievalComponentKind
                    },
                },
            },
        },
        "owner": {
            "type": "object",
            "required": ["display_name", "github_login"],
            "additionalProperties": False,
            "properties": {
                "display_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                },
                "github_login": {"const": APPROVAL_OWNER_GITHUB_LOGIN},
            },
        },
        "approved_at": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
        "repository": {"const": APPROVAL_REPOSITORY},
        "issue_number": {"const": APPROVAL_ISSUE_NUMBER},
        "pull_request_number": {"const": APPROVAL_PULL_REQUEST_NUMBER},
        "evidence": {
            "type": "object",
            "required": [
                "kind",
                "repository",
                "issue_number",
                "comment_id",
                "author_login",
                "body_digest",
                "url",
            ],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "GITHUB_ISSUE_COMMENT"},
                "repository": {"const": APPROVAL_REPOSITORY},
                "issue_number": {"const": APPROVAL_ISSUE_NUMBER},
                "comment_id": {"type": "integer", "minimum": 1},
                "author_login": {"const": APPROVAL_OWNER_GITHUB_LOGIN},
                "body_digest": {
                    "type": "string",
                    "pattern": _SHA256_PATTERN,
                },
                "url": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                },
            },
        },
    },
}
Draft202012Validator.check_schema(APPROVAL_ATTESTATION_SCHEMA)
_APPROVAL_VALIDATOR = Draft202012Validator(APPROVAL_ATTESTATION_SCHEMA)
APPROVAL_ATTESTATION_SCHEMA_DIGEST = digest_bytes(
    canonical_json_bytes(APPROVAL_ATTESTATION_SCHEMA)
)


def _require_schema_artifact() -> None:
    try:
        data = APPROVAL_ATTESTATION_SCHEMA_PATH.read_bytes()
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            "cannot load Increment 5A approval-attestation schema artifact"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            "approval-attestation schema artifact must be an object"
        )
    if (
        data != canonical_json_bytes(value)
        or value != APPROVAL_ATTESTATION_SCHEMA
        or digest_bytes(data) != APPROVAL_ATTESTATION_SCHEMA_DIGEST
    ):
        raise Increment5ContractError(
            "approval-attestation schema artifact differs from repository code"
        )


_require_schema_artifact()


def _qualification_schema_digest() -> str:
    from .profiles import QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST

    return QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST


def expected_increment5a_owner_approval_body(
    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,
) -> str:
    if not isinstance(proposal, Increment5ADecisionPacket):
        raise Increment5ContractError(
            "approval statement requires a typed proposal"
        )
    return (
        "I approve Increment 5A proposal payload "
        f"`{proposal.payload_digest}`, proposal record "
        f"`{proposal.record_digest}`, proposal contract bundle "
        f"`{proposal.bundle.contract_digest}`, effective "
        "production-qualification schema "
        f"`{_qualification_schema_digest()}`, approval-attestation schema "
        f"`{APPROVAL_ATTESTATION_SCHEMA_DIGEST}`, and fixture-replay schema "
        f"`{proposal.bundle.fixture_replay_profile_schema_digest}` as the exact "
        "implementation and production-equivalent qualification contract for "
        "issues #251–#254. This approval authorizes no shadow, canary, "
        "production activation, publication, public effect, live-source "
        "execution, external embedding API call, provider spending, or "
        "protected-content vector."
    )


def _parse_canonical_utc(value: str, *, field: str) -> UtcTimestamp:
    try:
        parsed = UtcTimestamp.parse(value)
    except (TypeError, ValueError) as exc:
        raise Increment5ContractError(f"{field} is not valid UTC text") from exc
    if value != parsed.to_text():
        raise Increment5ContractError(f"{field} must be canonical UTC text")
    return parsed


def _parse_github_utc(value: object, *, field: str) -> UtcTimestamp:
    if not isinstance(value, str) or not value:
        raise Increment5ContractError(f"{field} must be timestamp text")
    try:
        return UtcTimestamp.parse(value)
    except (TypeError, ValueError) as exc:
        raise Increment5ContractError(f"{field} is not valid UTC text") from exc


@dataclass(frozen=True, slots=True)
class Increment5AApprovalEvidence:
    comment_id: int
    body_digest: str
    url: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.comment_id, bool)
            or not isinstance(self.comment_id, int)
            or self.comment_id <= 0
        ):
            raise Increment5ContractError(
                "approval evidence comment identity must be positive"
            )
        try:
            validate_sha256_digest(
                self.body_digest,
                field="approval_evidence_body_digest",
            )
        except ValueError as exc:
            raise Increment5ContractError(
                "approval evidence body digest is invalid"
            ) from exc
        expected = (
            f"https://github.com/{APPROVAL_REPOSITORY}/issues/"
            f"{APPROVAL_ISSUE_NUMBER}#issuecomment-{self.comment_id}"
        )
        if self.url != expected:
            raise Increment5ContractError(
                "approval evidence URL differs from the exact issue comment"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": "GITHUB_ISSUE_COMMENT",
            "repository": APPROVAL_REPOSITORY,
            "issue_number": APPROVAL_ISSUE_NUMBER,
            "comment_id": self.comment_id,
            "author_login": APPROVAL_OWNER_GITHUB_LOGIN,
            "body_digest": self.body_digest,
            "url": self.url,
        }


@dataclass(frozen=True, slots=True)
class Increment5AApprovalAttestation:
    """Canonical but untrusted approval claim pending GitHub verification."""

    approved_at: UtcTimestamp
    evidence: Increment5AApprovalEvidence
    proposal_payload_digest: str
    proposal_record_digest: str
    proposal_contract_bundle_digest: str
    proposal_production_profile_schema_digest: str
    qualification_production_profile_schema_digest: str
    fixture_replay_profile_schema_digest: str
    component_identity_digests: tuple[tuple[str, str], ...]
    owner_display_name: str
    attestation_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.approved_at, UtcTimestamp):
            raise Increment5ContractError("approval time must be typed UTC")
        if not isinstance(self.evidence, Increment5AApprovalEvidence):
            raise Increment5ContractError("approval evidence must be typed")
        if (
            not isinstance(self.owner_display_name, str)
            or not self.owner_display_name
            or self.owner_display_name != self.owner_display_name.strip()
            or len(self.owner_display_name.encode("utf-8")) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.owner_display_name
            )
        ):
            raise Increment5ContractError(
                "approval owner display name is invalid"
            )
        for field_name in (
            "proposal_payload_digest",
            "proposal_record_digest",
            "proposal_contract_bundle_digest",
            "proposal_production_profile_schema_digest",
            "qualification_production_profile_schema_digest",
            "fixture_replay_profile_schema_digest",
            "attestation_digest",
        ):
            try:
                validate_sha256_digest(
                    getattr(self, field_name),
                    field=field_name,
                )
            except ValueError as exc:
                raise Increment5ContractError(
                    f"{field_name} is not a canonical digest"
                ) from exc
        expected_kinds = tuple(item.value for item in RetrievalComponentKind)
        actual_kinds = tuple(item[0] for item in self.component_identity_digests)
        if actual_kinds != expected_kinds:
            raise Increment5ContractError(
                "approval component digest inventory differs"
            )
        for kind, value in self.component_identity_digests:
            if not isinstance(kind, str) or not kind:
                raise Increment5ContractError(
                    "approval component kind is invalid"
                )
            try:
                validate_sha256_digest(
                    value,
                    field="approval_component_identity_digest",
                )
            except ValueError as exc:
                raise Increment5ContractError(
                    "approval component identity digest is invalid"
                ) from exc

    @property
    def component_digest_by_kind(self) -> dict[RetrievalComponentKind, str]:
        return {
            RetrievalComponentKind(kind): digest
            for kind, digest in self.component_identity_digests
        }

    def canonical_value(self, *, proposal_decision_id: str) -> dict[str, object]:
        return {
            "schema_version": APPROVAL_ATTESTATION_SCHEMA_VERSION,
            "attestation_id": APPROVAL_ATTESTATION_ID,
            "attestation_version": APPROVAL_ATTESTATION_VERSION,
            "approval_effect": APPROVAL_EFFECT,
            "non_effects": list(APPROVAL_NON_EFFECTS),
            "proposal": {
                "decision_id": proposal_decision_id,
                "payload_digest": self.proposal_payload_digest,
                "record_digest": self.proposal_record_digest,
                "contract_bundle_digest": self.proposal_contract_bundle_digest,
                "proposal_production_profile_schema_digest": (
                    self.proposal_production_profile_schema_digest
                ),
                "qualification_production_profile_schema_digest": (
                    self.qualification_production_profile_schema_digest
                ),
                "fixture_replay_profile_schema_digest": (
                    self.fixture_replay_profile_schema_digest
                ),
                "component_identity_digests": {
                    kind: value
                    for kind, value in self.component_identity_digests
                },
            },
            "owner": {
                "display_name": self.owner_display_name,
                "github_login": APPROVAL_OWNER_GITHUB_LOGIN,
            },
            "approved_at": self.approved_at.to_text(),
            "repository": APPROVAL_REPOSITORY,
            "issue_number": APPROVAL_ISSUE_NUMBER,
            "pull_request_number": APPROVAL_PULL_REQUEST_NUMBER,
            "evidence": self.evidence.canonical_value(),
        }


@dataclass(frozen=True, slots=True)
class GitHubApprovalComment:
    comment_id: int
    api_url: str
    html_url: str
    issue_url: str
    author_login: str
    author_id: int
    author_association: str
    body: str
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    def __post_init__(self) -> None:
        if (
            isinstance(self.comment_id, bool)
            or not isinstance(self.comment_id, int)
            or self.comment_id <= 0
        ):
            raise Increment5ContractError("GitHub approval comment ID is invalid")
        expected_api = (
            f"{GITHUB_API_BASE}/repos/{APPROVAL_REPOSITORY}/issues/comments/"
            f"{self.comment_id}"
        )
        expected_html = (
            f"https://github.com/{APPROVAL_REPOSITORY}/issues/"
            f"{APPROVAL_ISSUE_NUMBER}#issuecomment-{self.comment_id}"
        )
        expected_issue = (
            f"{GITHUB_API_BASE}/repos/{APPROVAL_REPOSITORY}/issues/"
            f"{APPROVAL_ISSUE_NUMBER}"
        )
        if self.api_url != expected_api:
            raise Increment5ContractError("GitHub approval API URL differs")
        if self.html_url != expected_html:
            raise Increment5ContractError("GitHub approval HTML URL differs")
        if self.issue_url != expected_issue:
            raise Increment5ContractError("GitHub approval issue URL differs")
        if self.author_login != APPROVAL_OWNER_GITHUB_LOGIN:
            raise Increment5ContractError("GitHub approval author login differs")
        if self.author_id != APPROVAL_OWNER_GITHUB_USER_ID:
            raise Increment5ContractError("GitHub approval author identity differs")
        if self.author_association != "OWNER":
            raise Increment5ContractError(
                "GitHub approval author is not the repository owner"
            )
        if (
            not isinstance(self.body, str)
            or not self.body
            or len(self.body.encode("utf-8")) > 16 * 1024
            or "\x00" in self.body
        ):
            raise Increment5ContractError("GitHub approval body is invalid")
        if not isinstance(self.created_at, UtcTimestamp) or not isinstance(
            self.updated_at, UtcTimestamp
        ):
            raise Increment5ContractError(
                "GitHub approval timestamps must be typed UTC"
            )
        if self.updated_at != self.created_at:
            raise Increment5ContractError(
                "edited GitHub approval comments are not admissible"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "comment_id": self.comment_id,
            "api_url": self.api_url,
            "html_url": self.html_url,
            "issue_url": self.issue_url,
            "author_login": self.author_login,
            "author_id": self.author_id,
            "author_association": self.author_association,
            "body_digest": digest_bytes(self.body.encode("utf-8")),
            "created_at": self.created_at.to_text(),
            "updated_at": self.updated_at.to_text(),
        }


class GitHubIssueCommentApprovalVerifier:
    """Fetch exact owner-comment evidence from authenticated GitHub REST."""

    __slots__ = ("_session", "_token", "_timeout_seconds")

    def __init__(
        self,
        *,
        token: str,
        timeout_seconds: float = GITHUB_APPROVAL_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(token, str) or _BEARER_TOKEN.fullmatch(token) is None:
            raise Increment5ContractError(
                "GitHub approval verifier requires a bounded bearer token"
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds > GITHUB_APPROVAL_TIMEOUT_SECONDS
        ):
            raise Increment5ContractError(
                "GitHub approval verifier timeout is invalid"
            )
        self._token = token
        self._timeout_seconds = float(timeout_seconds)
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> GitHubIssueCommentApprovalVerifier:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def fetch_issue_comment(self, comment_id: int) -> GitHubApprovalComment:
        if (
            isinstance(comment_id, bool)
            or not isinstance(comment_id, int)
            or comment_id <= 0
        ):
            raise Increment5ContractError(
                "GitHub approval comment identity must be positive"
            )
        url = (
            f"{GITHUB_API_BASE}/repos/{APPROVAL_REPOSITORY}/issues/comments/"
            f"{comment_id}"
        )
        try:
            response = self._session.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._token}",
                    "User-Agent": "fol2-newsroom-increment5a-approval-verifier",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                },
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise Increment5ContractError(
                "authenticated GitHub approval lookup failed"
            ) from exc
        if response.history or response.url != url:
            raise Increment5ContractError(
                "GitHub approval lookup redirected unexpectedly"
            )
        if response.status_code != 200:
            raise Increment5ContractError(
                "GitHub approval comment is unavailable or unauthorized"
            )
        content_type = response.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            raise Increment5ContractError(
                "GitHub approval response has an unexpected content type"
            )
        data = response.content
        if (
            not isinstance(data, bytes)
            or not data
            or len(data) > GITHUB_APPROVAL_MAX_RESPONSE_BYTES
        ):
            raise Increment5ContractError(
                "GitHub approval response exceeds its bounded contract"
            )
        try:
            value = json.loads(
                data.decode("utf-8", errors="strict"),
                object_pairs_hook=object_without_duplicate_names,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Increment5ContractError(
                "GitHub approval response is not strict JSON"
            ) from exc
        root = require_mapping(value, field="github_approval_comment")
        user = require_mapping(root.get("user"), field="github_approval_comment.user")
        return GitHubApprovalComment(
            comment_id=require_integer(
                root.get("id"),
                field="github_approval_comment.id",
            ),
            api_url=require_string(
                root.get("url"),
                field="github_approval_comment.url",
            ),
            html_url=require_string(
                root.get("html_url"),
                field="github_approval_comment.html_url",
            ),
            issue_url=require_string(
                root.get("issue_url"),
                field="github_approval_comment.issue_url",
            ),
            author_login=require_string(
                user.get("login"),
                field="github_approval_comment.user.login",
            ),
            author_id=require_integer(
                user.get("id"),
                field="github_approval_comment.user.id",
            ),
            author_association=require_string(
                root.get("author_association"),
                field="github_approval_comment.author_association",
            ),
            body=require_string(
                root.get("body"),
                field="github_approval_comment.body",
                maximum_bytes=16 * 1024,
            ),
            created_at=_parse_github_utc(
                root.get("created_at"),
                field="github_approval_comment.created_at",
            ),
            updated_at=_parse_github_utc(
                root.get("updated_at"),
                field="github_approval_comment.updated_at",
            ),
        )


def _verified_approval_factory():
    capability = object()

    @dataclass(frozen=True, slots=True)
    class _VerifiedIncrement5AApproval:
        claim: Increment5AApprovalAttestation
        comment: GitHubApprovalComment
        verification_digest: str
        _capability: object

        def __post_init__(self) -> None:
            if self._capability is not capability:
                raise Increment5ContractError(
                    "verified approval cannot be constructed directly"
                )
            if not isinstance(self.claim, Increment5AApprovalAttestation):
                raise Increment5ContractError(
                    "verified approval claim must be typed"
                )
            if not isinstance(self.comment, GitHubApprovalComment):
                raise Increment5ContractError(
                    "verified approval comment must be typed"
                )
            try:
                validate_sha256_digest(
                    self.verification_digest,
                    field="approval_verification_digest",
                )
            except ValueError as exc:
                raise Increment5ContractError(
                    "approval verification digest is invalid"
                ) from exc

    def make(
        *,
        claim: Increment5AApprovalAttestation,
        comment: GitHubApprovalComment,
        verification_digest: str,
    ) -> _VerifiedIncrement5AApproval:
        return _VerifiedIncrement5AApproval(
            claim=claim,
            comment=comment,
            verification_digest=verification_digest,
            _capability=capability,
        )

    return _VerifiedIncrement5AApproval, make


_VerifiedIncrement5AApproval, _make_verified_approval = (
    _verified_approval_factory()
)


def _require_approval_binds_proposal(
    *,
    approval: Increment5AApprovalAttestation,
    proposal: Increment5ADecisionPacket,
) -> None:
    expected_components = tuple(
        (
            kind.value,
            proposal.bundle.component_by_kind[kind].identity_digest,
        )
        for kind in RetrievalComponentKind
    )
    expected_body_digest = digest_bytes(
        expected_increment5a_owner_approval_body(proposal).encode("utf-8")
    )
    expected = (
        approval.proposal_payload_digest == proposal.payload_digest
        and approval.proposal_record_digest == proposal.record_digest
        and approval.proposal_contract_bundle_digest
        == proposal.bundle.contract_digest
        and approval.proposal_production_profile_schema_digest
        == proposal.bundle.production_profile_schema_digest
        and approval.qualification_production_profile_schema_digest
        == _qualification_schema_digest()
        and approval.fixture_replay_profile_schema_digest
        == proposal.bundle.fixture_replay_profile_schema_digest
        and approval.component_identity_digests == expected_components
        and approval.owner_display_name == proposal.owner
        and approval.evidence.body_digest == expected_body_digest
    )
    if not expected:
        raise Increment5ContractError(
            "owner approval attestation does not bind the exact proposal"
        )


def verify_increment5a_approval(
    approval: Increment5AApprovalAttestation,
    *,
    verifier: GitHubIssueCommentApprovalVerifier,
    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,
):
    if not isinstance(approval, Increment5AApprovalAttestation):
        raise Increment5ContractError(
            "approval verification requires a typed attestation claim"
        )
    if type(verifier) is not GitHubIssueCommentApprovalVerifier:
        raise Increment5ContractError(
            "approval verification requires the repository GitHub verifier"
        )
    if not isinstance(proposal, Increment5ADecisionPacket):
        raise Increment5ContractError(
            "approval verification requires a typed proposal"
        )
    _require_approval_binds_proposal(approval=approval, proposal=proposal)
    comment = verifier.fetch_issue_comment(approval.evidence.comment_id)
    expected_body = expected_increment5a_owner_approval_body(proposal)
    if comment.html_url != approval.evidence.url:
        raise Increment5ContractError(
            "GitHub approval URL differs from the attestation claim"
        )
    if comment.body != expected_body:
        raise Increment5ContractError(
            "GitHub approval body differs from the exact owner statement"
        )
    if digest_bytes(comment.body.encode("utf-8")) != approval.evidence.body_digest:
        raise Increment5ContractError(
            "GitHub approval body digest differs from the attestation claim"
        )
    if approval.approved_at != comment.created_at:
        raise Increment5ContractError(
            "approval time differs from canonical GitHub comment creation time"
        )
    verification_digest = digest_bytes(
        canonical_json_bytes(
            {
                "contract": GITHUB_APPROVAL_VERIFIER_CONTRACT,
                "attestation_digest": approval.attestation_digest,
                "proposal_payload_digest": proposal.payload_digest,
                "proposal_record_digest": proposal.record_digest,
                "comment": comment.canonical_value(),
                "expected_body_digest": digest_bytes(
                    expected_body.encode("utf-8")
                ),
            }
        )
    )
    return _make_verified_approval(
        claim=approval,
        comment=comment,
        verification_digest=verification_digest,
    )


@dataclass(frozen=True, slots=True)
class Increment5ADecisionAuthority:
    proposal: Increment5ADecisionPacket
    approval: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, Increment5ADecisionPacket):
            raise Increment5ContractError(
                "effective Increment 5A authority requires a typed proposal"
            )
        if self.approval is not None:
            if not isinstance(self.approval, _VerifiedIncrement5AApproval):
                raise Increment5ContractError(
                    "effective authority requires GitHub-verified owner approval"
                )
            _require_approval_binds_proposal(
                approval=self.approval.claim,
                proposal=self.proposal,
            )

    @property
    def production_authorized(self) -> bool:
        return self.approval is not None

    @property
    def approval_attestation_digest(self) -> str | None:
        return (
            None
            if self.approval is None
            else self.approval.verification_digest
        )

    @property
    def approval_claim_digest(self) -> str | None:
        return (
            None
            if self.approval is None
            else self.approval.claim.attestation_digest
        )

    @property
    def effective_contract_digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "contract": "increment5a-effective-decision-authority-v2",
                    "proposal_payload_digest": self.proposal.payload_digest,
                    "proposal_record_digest": self.proposal.record_digest,
                    "proposal_contract_bundle_digest": (
                        self.proposal.bundle.contract_digest
                    ),
                    "approval_claim_digest": self.approval_claim_digest,
                    "approval_verification_digest": (
                        self.approval_attestation_digest
                    ),
                    "qualification_production_profile_schema_digest": (
                        _qualification_schema_digest()
                    ),
                    "protected_content_allowed": False,
                    "approval_effect": (
                        None if self.approval is None else APPROVAL_EFFECT
                    ),
                }
            )
        )

    def component_authorized(self, kind: RetrievalComponentKind) -> bool:
        if not isinstance(kind, RetrievalComponentKind):
            raise Increment5ProfileError(
                "retrieval component kind must be typed"
            )
        if self.approval is None:
            return False
        expected = self.proposal.bundle.component_by_kind[kind].identity_digest
        return (
            self.approval.claim.component_digest_by_kind.get(kind) == expected
        )

    def require_profile(self, profile: RetrievalProfileKind) -> None:
        if not isinstance(profile, RetrievalProfileKind):
            raise Increment5ProfileError(
                "retrieval profile must be typed"
            )
        if profile is RetrievalProfileKind.FIXTURE_REPLAY:
            self.proposal.require_profile(profile)
            return
        if not self.production_authorized:
            raise Increment5ProfileError(
                "PRODUCTION is not authorized without GitHub-verified owner approval"
            )
        if not all(
            self.component_authorized(kind)
            for kind in RetrievalComponentKind
        ):
            raise Increment5ProfileError(
                "production qualification component approval is incomplete"
            )


def _schema_errors(value: Mapping[str, Any]) -> tuple[str, ...]:
    errors = sorted(
        _APPROVAL_VALIDATOR.iter_errors(value),
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


def approval_attestation_value(
    *,
    proposal: Increment5ADecisionPacket,
    approved_at: UtcTimestamp,
    comment_id: int,
    approval_comment_body_digest: str,
) -> dict[str, object]:
    if not isinstance(proposal, Increment5ADecisionPacket):
        raise Increment5ContractError(
            "approval attestation builder requires a typed proposal"
        )
    if not isinstance(approved_at, UtcTimestamp):
        raise Increment5ContractError(
            "approval attestation builder requires typed UTC time"
        )
    try:
        validate_sha256_digest(
            approval_comment_body_digest,
            field="approval_comment_body_digest",
        )
    except ValueError as exc:
        raise Increment5ContractError(
            "approval comment body digest is invalid"
        ) from exc
    expected_body_digest = digest_bytes(
        expected_increment5a_owner_approval_body(proposal).encode("utf-8")
    )
    if approval_comment_body_digest != expected_body_digest:
        raise Increment5ContractError(
            "approval comment digest differs from the exact owner statement"
        )
    if (
        isinstance(comment_id, bool)
        or not isinstance(comment_id, int)
        or comment_id <= 0
    ):
        raise Increment5ContractError(
            "approval comment identity must be positive"
        )
    return {
        "schema_version": APPROVAL_ATTESTATION_SCHEMA_VERSION,
        "attestation_id": APPROVAL_ATTESTATION_ID,
        "attestation_version": APPROVAL_ATTESTATION_VERSION,
        "approval_effect": APPROVAL_EFFECT,
        "non_effects": list(APPROVAL_NON_EFFECTS),
        "proposal": {
            "decision_id": proposal.bundle.decision_id,
            "payload_digest": proposal.payload_digest,
            "record_digest": proposal.record_digest,
            "contract_bundle_digest": proposal.bundle.contract_digest,
            "proposal_production_profile_schema_digest": (
                proposal.bundle.production_profile_schema_digest
            ),
            "qualification_production_profile_schema_digest": (
                _qualification_schema_digest()
            ),
            "fixture_replay_profile_schema_digest": (
                proposal.bundle.fixture_replay_profile_schema_digest
            ),
            "component_identity_digests": {
                kind.value: proposal.bundle.component_by_kind[
                    kind
                ].identity_digest
                for kind in RetrievalComponentKind
            },
        },
        "owner": {
            "display_name": proposal.owner,
            "github_login": APPROVAL_OWNER_GITHUB_LOGIN,
        },
        "approved_at": approved_at.to_text(),
        "repository": APPROVAL_REPOSITORY,
        "issue_number": APPROVAL_ISSUE_NUMBER,
        "pull_request_number": APPROVAL_PULL_REQUEST_NUMBER,
        "evidence": {
            "kind": "GITHUB_ISSUE_COMMENT",
            "repository": APPROVAL_REPOSITORY,
            "issue_number": APPROVAL_ISSUE_NUMBER,
            "comment_id": comment_id,
            "author_login": APPROVAL_OWNER_GITHUB_LOGIN,
            "body_digest": approval_comment_body_digest,
            "url": (
                f"https://github.com/{APPROVAL_REPOSITORY}/issues/"
                f"{APPROVAL_ISSUE_NUMBER}#issuecomment-{comment_id}"
            ),
        },
    }


def load_increment5a_approval_attestation(
    path: Path,
    *,
    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,
) -> Increment5AApprovalAttestation:
    try:
        data = path.read_bytes()
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Increment5ContractError(
            f"cannot read Increment 5A owner approval attestation: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            "owner approval attestation root must be an object"
        )
    if data != canonical_json_bytes(value):
        raise Increment5ContractError(
            "owner approval attestation must be exact canonical JSON"
        )
    errors = _schema_errors(value)
    if errors:
        raise Increment5ContractError(
            "owner approval attestation schema validation failed: "
            + errors[0]
        )

    proposal_value = require_mapping(
        value.get("proposal"),
        field="approval.proposal",
    )
    owner = require_mapping(value.get("owner"), field="approval.owner")
    evidence_value = require_mapping(
        value.get("evidence"),
        field="approval.evidence",
    )
    component_values = require_mapping(
        proposal_value.get("component_identity_digests"),
        field="approval.proposal.component_identity_digests",
    )
    require_exact_keys(
        component_values,
        required=frozenset(item.value for item in RetrievalComponentKind),
        field="approval.proposal.component_identity_digests",
    )
    approved_at_text = require_string(
        value.get("approved_at"),
        field="approval.approved_at",
    )
    evidence = Increment5AApprovalEvidence(
        comment_id=require_integer(
            evidence_value.get("comment_id"),
            field="approval.evidence.comment_id",
        ),
        body_digest=require_digest(
            evidence_value.get("body_digest"),
            field="approval.evidence.body_digest",
        ),
        url=require_string(
            evidence_value.get("url"),
            field="approval.evidence.url",
        ),
    )
    attestation = Increment5AApprovalAttestation(
        approved_at=_parse_canonical_utc(
            approved_at_text,
            field="approval.approved_at",
        ),
        evidence=evidence,
        proposal_payload_digest=require_digest(
            proposal_value.get("payload_digest"),
            field="approval.proposal.payload_digest",
        ),
        proposal_record_digest=require_digest(
            proposal_value.get("record_digest"),
            field="approval.proposal.record_digest",
        ),
        proposal_contract_bundle_digest=require_digest(
            proposal_value.get("contract_bundle_digest"),
            field="approval.proposal.contract_bundle_digest",
        ),
        proposal_production_profile_schema_digest=require_digest(
            proposal_value.get(
                "proposal_production_profile_schema_digest"
            ),
            field=(
                "approval.proposal."
                "proposal_production_profile_schema_digest"
            ),
        ),
        qualification_production_profile_schema_digest=require_digest(
            proposal_value.get(
                "qualification_production_profile_schema_digest"
            ),
            field=(
                "approval.proposal."
                "qualification_production_profile_schema_digest"
            ),
        ),
        fixture_replay_profile_schema_digest=require_digest(
            proposal_value.get("fixture_replay_profile_schema_digest"),
            field=(
                "approval.proposal."
                "fixture_replay_profile_schema_digest"
            ),
        ),
        component_identity_digests=tuple(
            (
                kind.value,
                require_digest(
                    component_values.get(kind.value),
                    field=(
                        "approval.proposal.component_identity_digests."
                        + kind.value
                    ),
                ),
            )
            for kind in RetrievalComponentKind
        ),
        owner_display_name=require_string(
            owner.get("display_name"),
            field="approval.owner.display_name",
            maximum_bytes=256,
        ),
        attestation_digest=digest_bytes(data),
    )
    if (
        require_string(
            proposal_value.get("decision_id"),
            field="approval.proposal.decision_id",
        )
        != proposal.bundle.decision_id
    ):
        raise Increment5ContractError(
            "owner approval decision identity differs from proposal"
        )
    _require_approval_binds_proposal(
        approval=attestation,
        proposal=proposal,
    )
    return attestation


def decision_authority(
    *,
    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,
    approval: object | None = None,
) -> Increment5ADecisionAuthority:
    return Increment5ADecisionAuthority(
        proposal=proposal,
        approval=approval,
    )


INCREMENT_5A_DECISION_AUTHORITY = decision_authority()
