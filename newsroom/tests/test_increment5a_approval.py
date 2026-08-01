from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp
import newsroom.increment5.approval as approval_module
from newsroom.increment5 import (
    APPROVAL_ATTESTATION_SCHEMA_DIGEST,
    APPROVAL_ATTESTATION_SCHEMA_PATH,
    APPROVAL_NON_EFFECTS,
    GitHubIssueCommentApprovalVerifier,
    INCREMENT5_TRACEABILITY_BY_REQUIREMENT,
    INCREMENT_5A_DECISION_AUTHORITY,
    INCREMENT_5A_DECISION_PACKET,
    Increment5ContractError,
    Increment5DeliveryTrace,
    Increment5ProfileError,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
    QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
    RetrievalProfileKind,
    approval_attestation_value,
    build_production_qualification_manifest,
    decision_authority,
    expected_increment5a_owner_approval_body,
    load_increment5a_approval_attestation,
    validate_profile_manifest,
    verify_increment5a_approval,
)


_COMMENT_ID = 123456789
_CREATED_AT = "2042-03-12T12:00:00Z"
_CANONICAL_CREATED_AT = UtcTimestamp.parse(_CREATED_AT)
_OWNER_BODY = expected_increment5a_owner_approval_body()
_OWNER_BODY_DIGEST = digest_bytes(_OWNER_BODY.encode("utf-8"))
_API_URL = (
    "https://api.github.com/repos/fol2/newsroom/issues/comments/"
    f"{_COMMENT_ID}"
)
_HTML_URL = (
    "https://github.com/fol2/newsroom/issues/250#issuecomment-"
    f"{_COMMENT_ID}"
)
_ISSUE_URL = "https://api.github.com/repos/fol2/newsroom/issues/250"


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        url: str = _API_URL,
        status_code: int = 200,
        content_type: str = "application/json; charset=utf-8",
        history: list[object] | None = None,
    ) -> None:
        self.content = canonical_json_bytes(payload)
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.history = [] if history is None else history


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((url, kwargs))
        return self.response

    def close(self) -> None:
        self.closed = True


def _github_comment(
    *,
    body: str = _OWNER_BODY,
    login: str = "fol2",
    user_id: int = 105634418,
    author_association: str = "OWNER",
    created_at: str = _CREATED_AT,
    updated_at: str = _CREATED_AT,
) -> dict[str, object]:
    return {
        "id": _COMMENT_ID,
        "url": _API_URL,
        "html_url": _HTML_URL,
        "issue_url": _ISSUE_URL,
        "user": {"login": login, "id": user_id},
        "author_association": author_association,
        "body": body,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _approval_value(
    *,
    approved_at: UtcTimestamp = _CANONICAL_CREATED_AT,
) -> dict[str, object]:
    return approval_attestation_value(
        proposal=INCREMENT_5A_DECISION_PACKET,
        approved_at=approved_at,
        comment_id=_COMMENT_ID,
        approval_comment_body_digest=_OWNER_BODY_DIGEST,
    )


def _write_approval(
    tmp_path: Path,
    value: dict[str, object],
) -> Path:
    path = tmp_path / "approval.json"
    path.write_bytes(canonical_json_bytes(value))
    return path


def _verified_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    claim_value: dict[str, object] | None = None,
    comment_value: dict[str, object] | None = None,
):
    claim = load_increment5a_approval_attestation(
        _write_approval(
            tmp_path,
            _approval_value() if claim_value is None else claim_value,
        )
    )
    session = _FakeSession(
        _FakeResponse(
            _github_comment() if comment_value is None else comment_value
        )
    )
    monkeypatch.setattr(
        approval_module.requests,
        "Session",
        lambda: session,
    )
    with GitHubIssueCommentApprovalVerifier(token="test-token") as verifier:
        verified = verify_increment5a_approval(
            claim,
            verifier=verifier,
        )
    return claim, verified, session


def _approved_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _claim, verified, _session = _verified_approval(
        tmp_path,
        monkeypatch,
    )
    return decision_authority(approval=verified)


def test_approval_and_qualification_schema_artifacts_are_canonical() -> None:
    for path, expected_digest in (
        (
            APPROVAL_ATTESTATION_SCHEMA_PATH,
            APPROVAL_ATTESTATION_SCHEMA_DIGEST,
        ),
        (
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_PATH,
            QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
        ),
    ):
        data = path.read_bytes()
        assert data == canonical_json_bytes(
            json.loads(data.decode("utf-8"))
        )
        assert digest_bytes(data) == expected_digest


def test_pending_proposal_remains_immutable_and_non_authorizing() -> None:
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized
    assert (
        INCREMENT_5A_DECISION_AUTHORITY.proposal
        is INCREMENT_5A_DECISION_PACKET
    )
    with pytest.raises(
        Increment5ProfileError,
        match="GitHub-verified owner approval",
    ):
        INCREMENT_5A_DECISION_AUTHORITY.require_profile(
            RetrievalProfileKind.PRODUCTION
        )


def test_unverified_canonical_claim_cannot_create_authority(
    tmp_path: Path,
) -> None:
    claim = load_increment5a_approval_attestation(
        _write_approval(tmp_path, _approval_value())
    )

    with pytest.raises(
        Increment5ContractError,
        match="GitHub-verified owner approval",
    ):
        decision_authority(approval=claim)


def test_authenticated_github_comment_authorizes_exact_proposal_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim, verified, session = _verified_approval(
        tmp_path,
        monkeypatch,
    )
    authority = decision_authority(approval=verified)

    assert authority.production_authorized
    assert authority.proposal is INCREMENT_5A_DECISION_PACKET
    assert authority.proposal.status.value == "PENDING_OWNER_REVIEW"
    assert authority.approval is verified
    assert authority.approval_claim_digest == claim.attestation_digest
    assert authority.approval_attestation_digest == verified.verification_digest
    assert tuple(APPROVAL_NON_EFFECTS) == (
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
    authority.require_profile(RetrievalProfileKind.PRODUCTION)

    assert session.closed
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == _API_URL
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 10.0
    assert kwargs["headers"] == {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer test-token",
        "User-Agent": "fol2-newsroom-increment5a-approval-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def test_production_manifest_requires_verified_attestation_and_denies_protected_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _approved_authority(tmp_path, monkeypatch)
    manifest = build_production_qualification_manifest(
        authority=authority
    )
    validated = validate_profile_manifest(
        manifest,
        packet=authority,
    )

    assert validated.profile is RetrievalProfileKind.PRODUCTION
    assert validated.qualification_eligible
    assert validated.approval_attestation_digest == (
        authority.approval_attestation_digest
    )
    assert manifest["rights"]["protected_content_allowed"] is False

    tampered = deepcopy(manifest)
    tampered["rights"]["protected_content_allowed"] = True
    with pytest.raises(
        Increment5ProfileError,
        match="schema validation failed",
    ):
        validate_profile_manifest(tampered, packet=authority)


def test_production_manifest_cannot_use_bare_pending_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _approved_authority(tmp_path, monkeypatch)
    manifest = build_production_qualification_manifest(
        authority=authority
    )
    with pytest.raises(
        Increment5ProfileError,
        match="owner approval authority",
    ):
        validate_profile_manifest(
            manifest,
            packet=INCREMENT_5A_DECISION_PACKET,
        )


def test_attestation_tampering_cannot_approve_another_proposal(
    tmp_path: Path,
) -> None:
    value = _approval_value()
    proposal = value["proposal"]
    assert isinstance(proposal, dict)
    proposal["payload_digest"] = (
        "sha256:"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    with pytest.raises(
        Increment5ContractError,
        match="does not bind the exact proposal",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


def test_attestation_cannot_drop_non_effects(
    tmp_path: Path,
) -> None:
    value = _approval_value()
    non_effects = value["non_effects"]
    assert isinstance(non_effects, list)
    non_effects.remove("PROTECTED_CONTENT_VECTORS")
    with pytest.raises(
        Increment5ContractError,
        match="schema validation failed",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


def test_attestation_requires_canonical_utc_text(tmp_path: Path) -> None:
    value = _approval_value()
    value["approved_at"] = "2042-03-12T12:00:00Z"

    with pytest.raises(
        Increment5ContractError,
        match="canonical UTC text",
    ):
        load_increment5a_approval_attestation(
            _write_approval(tmp_path, value)
        )


@pytest.mark.parametrize(
    ("comment", "message"),
    (
        (
            _github_comment(login="attacker"),
            "author login differs",
        ),
        (
            _github_comment(user_id=999),
            "author identity differs",
        ),
        (
            _github_comment(author_association="CONTRIBUTOR"),
            "not the repository owner",
        ),
        (
            _github_comment(updated_at="2042-03-12T12:00:01Z"),
            "edited GitHub approval comments",
        ),
    ),
)
def test_github_verifier_rejects_wrong_or_edited_owner_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    comment: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(Increment5ContractError, match=message):
        _verified_approval(
            tmp_path,
            monkeypatch,
            comment_value=comment,
        )


def test_github_verifier_rejects_wrong_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        Increment5ContractError,
        match="body differs from the exact owner statement",
    ):
        _verified_approval(
            tmp_path,
            monkeypatch,
            comment_value=_github_comment(body="I approve something else."),
        )


def test_github_verifier_binds_claim_time_to_comment_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_value = _approval_value(
        approved_at=UtcTimestamp.parse(
            "2042-03-12T12:00:01.000000Z"
        )
    )
    with pytest.raises(
        Increment5ContractError,
        match="approval time differs",
    ):
        _verified_approval(
            tmp_path,
            monkeypatch,
            claim_value=claim_value,
        )


def test_github_verifier_rejects_redirects_and_non_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = load_increment5a_approval_attestation(
        _write_approval(tmp_path, _approval_value())
    )
    response = _FakeResponse(
        _github_comment(),
        url="https://example.invalid/redirect",
        history=[object()],
    )
    session = _FakeSession(response)
    monkeypatch.setattr(approval_module.requests, "Session", lambda: session)
    with GitHubIssueCommentApprovalVerifier(token="test-token") as verifier:
        with pytest.raises(
            Increment5ContractError,
            match="redirected unexpectedly",
        ):
            verify_increment5a_approval(claim, verifier=verifier)

    response = _FakeResponse(
        _github_comment(),
        content_type="text/html",
    )
    session = _FakeSession(response)
    monkeypatch.setattr(approval_module.requests, "Session", lambda: session)
    with GitHubIssueCommentApprovalVerifier(token="test-token") as verifier:
        with pytest.raises(
            Increment5ContractError,
            match="unexpected content type",
        ):
            verify_increment5a_approval(claim, verifier=verifier)


def test_dops_072_remains_deferred_to_5e_qualification() -> None:
    row = INCREMENT5_TRACEABILITY_BY_REQUIREMENT["DOPS-072"]
    assert (
        row.delivery_trace
        is Increment5DeliveryTrace.DEFERRED_TO_5E
    )
    assert row.delivery_issue == 254
