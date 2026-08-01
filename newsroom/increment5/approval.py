from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping

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
APPROVAL_RECORD_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5a_owner_approval_record_v1.json"
)
# The owner-approval materialisation commit replaces None with the exact
# canonical record digest.  Until then, a record at the path is itself an error.
APPROVAL_RECORD_DIGEST: str | None = None
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


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
            "cannot load Increment 5A approval-record schema artifact"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            "approval-record schema artifact must be an object"
        )
    if (
        data != canonical_json_bytes(value)
        or value != APPROVAL_ATTESTATION_SCHEMA
        or digest_bytes(data) != APPROVAL_ATTESTATION_SCHEMA_DIGEST
    ):
        raise Increment5ContractError(
            "approval-record schema artifact differs from repository code"
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
    """Immutable repository-owned owner approval record."""

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
            "approval record builder requires a typed proposal"
        )
    if not isinstance(approved_at, UtcTimestamp):
        raise Increment5ContractError(
            "approval record builder requires typed UTC time"
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
            "owner approval record does not bind the exact proposal"
        )


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
            f"cannot read Increment 5A owner approval record: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise Increment5ContractError(
            "owner approval record root must be an object"
        )
    if data != canonical_json_bytes(value):
        raise Increment5ContractError(
            "owner approval record must be exact canonical JSON"
        )
    errors = _schema_errors(value)
    if errors:
        raise Increment5ContractError(
            "owner approval record schema validation failed: " + errors[0]
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
    approval = Increment5AApprovalAttestation(
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
        approval=approval,
        proposal=proposal,
    )
    return approval


def _repository_loader_factory(
    *,
    path: Path,
    expected_digest: str | None,
) -> Callable[[], Increment5AApprovalAttestation | None]:
    # Capture both values in a closure at import.  Reassigning the public path or
    # digest constants cannot substitute another record for production gates.
    captured_path = path
    captured_digest = expected_digest

    def load() -> Increment5AApprovalAttestation | None:
        if captured_digest is None:
            if captured_path.exists():
                raise Increment5ContractError(
                    "unadmitted repository owner approval record is present"
                )
            return None
        try:
            validate_sha256_digest(
                captured_digest,
                field="approval_record_digest",
            )
        except ValueError as exc:
            raise Increment5ContractError(
                "admitted owner approval record digest is invalid"
            ) from exc
        if not captured_path.is_file():
            raise Increment5ContractError(
                "admitted repository owner approval record is missing"
            )
        approval = load_increment5a_approval_attestation(captured_path)
        if approval.attestation_digest != captured_digest:
            raise Increment5ContractError(
                "repository owner approval record digest differs"
            )
        return approval

    return load


_LOAD_REPOSITORY_APPROVAL = _repository_loader_factory(
    path=APPROVAL_RECORD_PATH,
    expected_digest=APPROVAL_RECORD_DIGEST,
)


def repository_approval_record(
    _load: Callable[
        [], Increment5AApprovalAttestation | None
    ] = _LOAD_REPOSITORY_APPROVAL,
) -> Increment5AApprovalAttestation | None:
    """Return only the source-pinned repository record, never caller evidence."""

    return _load()


def require_repository_approval_record(
    _load: Callable[
        [], Increment5AApprovalAttestation | None
    ] = _LOAD_REPOSITORY_APPROVAL,
) -> Increment5AApprovalAttestation:
    approval = _load()
    if approval is None:
        raise Increment5ProfileError(
            "PRODUCTION is not authorized without the admitted repository "
            "owner approval record"
        )
    return approval


class Increment5ADecisionAuthority:
    """Read-only status facade; production gates trust the repository record."""

    __slots__ = ()

    @property
    def proposal(self) -> Increment5ADecisionPacket:
        return INCREMENT_5A_DECISION_PACKET

    @property
    def production_authorized(self) -> bool:
        return repository_approval_record() is not None

    @property
    def approval_attestation_digest(self) -> str | None:
        approval = repository_approval_record()
        return None if approval is None else approval.attestation_digest

    @property
    def approval_claim_digest(self) -> str | None:
        return self.approval_attestation_digest

    @property
    def effective_contract_digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "contract": "increment5a-effective-decision-authority-v4",
                    "proposal_payload_digest": self.proposal.payload_digest,
                    "proposal_record_digest": self.proposal.record_digest,
                    "proposal_contract_bundle_digest": (
                        self.proposal.bundle.contract_digest
                    ),
                    "approval_record_digest": self.approval_attestation_digest,
                    "qualification_production_profile_schema_digest": (
                        _qualification_schema_digest()
                    ),
                    "protected_content_allowed": False,
                    "approval_effect": (
                        APPROVAL_EFFECT if self.production_authorized else None
                    ),
                }
            )
        )

    def component_authorized(self, kind: RetrievalComponentKind) -> bool:
        if not isinstance(kind, RetrievalComponentKind):
            raise Increment5ProfileError(
                "retrieval component kind must be typed"
            )
        approval = repository_approval_record()
        if approval is None:
            return False
        expected = self.proposal.bundle.component_by_kind[kind].identity_digest
        return approval.component_digest_by_kind.get(kind) == expected

    def require_profile(self, profile: RetrievalProfileKind) -> None:
        if not isinstance(profile, RetrievalProfileKind):
            raise Increment5ProfileError(
                "retrieval profile must be typed"
            )
        if profile is RetrievalProfileKind.FIXTURE_REPLAY:
            self.proposal.require_profile(profile)
            return
        approval = require_repository_approval_record()
        for kind in RetrievalComponentKind:
            expected = self.proposal.bundle.component_by_kind[kind].identity_digest
            if approval.component_digest_by_kind.get(kind) != expected:
                raise Increment5ProfileError(
                    "production qualification component approval is incomplete"
                )


INCREMENT_5A_DECISION_AUTHORITY = Increment5ADecisionAuthority()


def decision_authority() -> Increment5ADecisionAuthority:
    """Return the repository-backed status facade."""

    return INCREMENT_5A_DECISION_AUTHORITY
