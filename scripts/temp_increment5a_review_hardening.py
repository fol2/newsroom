from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST as OLD_PUBLIC_FIXTURE_DIGEST,
    expected_increment5a_owner_approval_body,
)


ROOT = Path(__file__).resolve().parents[1]
OLD_OWNER_BODY = expected_increment5a_owner_approval_body()
OLD_OWNER_BODY_DIGEST = digest_bytes(OLD_OWNER_BODY.encode("utf-8"))


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    *,
    label: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker absent")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: end marker absent")
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# Authenticated GitHub workflow-attempt transport
# ---------------------------------------------------------------------------

github_transport_path = ROOT / "scripts" / "sdlc" / "github_transport.py"
github_transport = github_transport_path.read_text(encoding="utf-8")
github_transport = replace_once(
    github_transport,
    dedent(
        '''
            def fetch_run(self, run_id: int) -> Mapping[str, object]:
                run = _positive(run_id, "run_id")
                value = self._get_json(f"{_API_PREFIX}/actions/runs/{run}")
                _run_identity(value, expected_run_id=run)
                return value

            def fetch_jobs(self, run_id: int, run_attempt: int) -> Mapping[str, object]:
        '''
    ).strip("\n"),
    dedent(
        '''
            def fetch_run(self, run_id: int) -> Mapping[str, object]:
                run = _positive(run_id, "run_id")
                value = self._get_json(f"{_API_PREFIX}/actions/runs/{run}")
                _run_identity(value, expected_run_id=run)
                return value

            def fetch_run_attempt(
                self,
                run_id: int,
                run_attempt: int,
            ) -> Mapping[str, object]:
                run = _positive(run_id, "run_id")
                attempt = _positive(run_attempt, "run_attempt")
                value = self._get_json(
                    f"{_API_PREFIX}/actions/runs/{run}/attempts/{attempt}"
                )
                identity = _run_identity(value, expected_run_id=run)
                if identity[1] != attempt:
                    raise GitHubTransportError("run_attempt")
                return value

            def fetch_git_commit(self, commit_sha: str) -> Mapping[str, object]:
                sha = _text(commit_sha, "commit_sha", maximum=40)
                if _GIT_SHA.fullmatch(sha) is None:
                    raise GitHubTransportError("commit_sha")
                value = self._get_json(f"{_API_PREFIX}/git/commits/{sha}")
                tree = _mapping(value.get("tree"), "commit_tree")
                tree_sha = _text(tree.get("sha"), "commit_tree_sha", maximum=40)
                if value.get("sha") != sha or _GIT_SHA.fullmatch(tree_sha) is None:
                    raise GitHubTransportError("commit_identity")
                return value

            def fetch_jobs(self, run_id: int, run_attempt: int) -> Mapping[str, object]:
        '''
    ).strip("\n"),
    label="GitHub run-attempt and commit fetchers",
)
write_text(github_transport_path, github_transport)


github_attempts_path = ROOT / "newsroom" / "increment5" / "github_attempts.py"
write_text(
    github_attempts_path,
    dedent(
        '''
        from __future__ import annotations

        from collections.abc import Callable, Mapping
        from typing import Any

        from newsroom.authority.types import UtcTimestamp
        from scripts.sdlc.github_transport import (
            GitHubActionsClient,
            GitHubTransportError,
        )

        from .contracts import Increment5ContractError
        from .main_qualification import (
            MAIN_QUALIFICATION_REF,
            MAIN_QUALIFICATION_REPOSITORY,
            MAIN_QUALIFICATION_REPOSITORY_ID,
            MAIN_QUALIFICATION_WORKFLOW_PATHS,
            Increment5AMainQualificationRecord,
            WorkflowAttemptEvidence,
        )


        _API_PREFIX = (
            "https://api.github.com/repos/"
            + MAIN_QUALIFICATION_REPOSITORY
        )


        def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
            if not isinstance(value, Mapping):
                raise Increment5ContractError(f"{field} must be an object")
            return value


        def _canonical_github_time(value: object, *, field: str) -> UtcTimestamp:
            if not isinstance(value, str) or not value:
                raise Increment5ContractError(f"{field} must be timestamp text")
            try:
                return UtcTimestamp.parse(value)
            except (TypeError, ValueError) as exc:
                raise Increment5ContractError(
                    f"{field} is not valid UTC text"
                ) from exc


        def _workflow_path(value: object, *, expected: str) -> str:
            if not isinstance(value, str) or not value:
                raise Increment5ContractError(
                    "authenticated workflow path is absent"
                )
            path, separator, ref = value.partition("@")
            if path != expected or (separator and ref != MAIN_QUALIFICATION_REF):
                raise Increment5ContractError(
                    "authenticated workflow path differs"
                )
            return path


        def validate_github_workflow_attempt_payload(
            *,
            attempt: WorkflowAttemptEvidence,
            payload: Mapping[str, Any],
        ) -> None:
            if not isinstance(attempt, WorkflowAttemptEvidence):
                raise Increment5ContractError(
                    "GitHub verification requires typed workflow evidence"
                )
            value = _mapping(payload, field="github.workflow_attempt")
            repository = _mapping(
                value.get("repository"),
                field="github.workflow_attempt.repository",
            )
            head_repository = _mapping(
                value.get("head_repository"),
                field="github.workflow_attempt.head_repository",
            )
            expected_path = MAIN_QUALIFICATION_WORKFLOW_PATHS[attempt.key]
            expected_workflow_ref = (
                f"{MAIN_QUALIFICATION_REPOSITORY}/{expected_path}"
                f"@{MAIN_QUALIFICATION_REF}"
            )
            expected_run_url = f"{_API_PREFIX}/actions/runs/{attempt.run_id}"
            expected_attempt_url = (
                expected_run_url + f"/attempts/{attempt.run_attempt}"
            )
            expected = {
                "id": attempt.run_id,
                "workflow_id": attempt.workflow_id,
                "name": attempt.workflow_name,
                "run_number": attempt.run_number,
                "run_attempt": attempt.run_attempt,
                "event": attempt.event,
                "status": "completed",
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": attempt.head_sha,
                "head_repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
                "url": expected_run_url,
                "html_url": attempt.html_url,
            }
            actual = {key: value.get(key) for key in expected}
            if actual != expected:
                raise Increment5ContractError(
                    "authenticated workflow attempt metadata differs"
                )
            if attempt.api_url != expected_attempt_url:
                raise Increment5ContractError(
                    "workflow attempt API URL differs from authenticated endpoint"
                )
            if (
                repository.get("id") != MAIN_QUALIFICATION_REPOSITORY_ID
                or repository.get("full_name")
                != MAIN_QUALIFICATION_REPOSITORY
                or head_repository.get("id")
                != MAIN_QUALIFICATION_REPOSITORY_ID
                or head_repository.get("full_name")
                != MAIN_QUALIFICATION_REPOSITORY
            ):
                raise Increment5ContractError(
                    "authenticated workflow repository identity differs"
                )
            _workflow_path(value.get("path"), expected=expected_path)
            if attempt.workflow_ref != expected_workflow_ref:
                raise Increment5ContractError(
                    "workflow attempt ref differs from permanent workflow"
                )
            for field_name in (
                "created_at",
                "run_started_at",
                "updated_at",
            ):
                authenticated = _canonical_github_time(
                    value.get(field_name),
                    field=f"github.workflow_attempt.{field_name}",
                )
                if authenticated != getattr(attempt, field_name):
                    raise Increment5ContractError(
                        "authenticated workflow attempt timestamp differs"
                    )


        def validate_github_commit_payload(
            *,
            record: Increment5AMainQualificationRecord,
            payload: Mapping[str, Any],
        ) -> None:
            if not isinstance(record, Increment5AMainQualificationRecord):
                raise Increment5ContractError(
                    "GitHub verification requires typed main admission"
                )
            value = _mapping(payload, field="github.commit")
            tree = _mapping(value.get("tree"), field="github.commit.tree")
            expected_url = (
                f"{_API_PREFIX}/git/commits/"
                f"{record.qualified_main_commit_sha}"
            )
            if (
                value.get("sha") != record.qualified_main_commit_sha
                or value.get("url") != expected_url
                or tree.get("sha") != record.qualified_main_tree_sha
            ):
                raise Increment5ContractError(
                    "authenticated GitHub commit/tree identity differs"
                )


        def _repository_authenticator_factory(
            *,
            client_factory: Callable[[], GitHubActionsClient] = (
                GitHubActionsClient.from_environment
            ),
        ) -> Callable[
            [Increment5AMainQualificationRecord],
            Increment5AMainQualificationRecord,
        ]:
            captured_client_factory = client_factory
            authenticated_record_digest: str | None = None

            def authenticate(
                record: Increment5AMainQualificationRecord,
            ) -> Increment5AMainQualificationRecord:
                nonlocal authenticated_record_digest
                if not isinstance(record, Increment5AMainQualificationRecord):
                    raise Increment5ContractError(
                        "repository admission requires typed main qualification"
                    )
                if authenticated_record_digest == record.record_digest:
                    return record
                try:
                    client = captured_client_factory()
                    commit = client.fetch_git_commit(
                        record.qualified_main_commit_sha
                    )
                    validate_github_commit_payload(
                        record=record,
                        payload=commit,
                    )
                    for attempt in record.workflow_attempts:
                        payload = client.fetch_run_attempt(
                            attempt.run_id,
                            attempt.run_attempt,
                        )
                        validate_github_workflow_attempt_payload(
                            attempt=attempt,
                            payload=payload,
                        )
                except GitHubTransportError as exc:
                    raise Increment5ContractError(
                        "authenticated GitHub workflow evidence is unavailable"
                    ) from exc
                authenticated_record_digest = record.record_digest
                return record

            return authenticate


        _AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION = (
            _repository_authenticator_factory()
        )
        del _repository_authenticator_factory


        def authenticate_repository_main_qualification_record(
            record: Increment5AMainQualificationRecord,
        ) -> Increment5AMainQualificationRecord:
            """Authenticate the source-pinned admission against live GitHub."""

            return _AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION(record)
        '''
    ).lstrip(),
)


# ---------------------------------------------------------------------------
# Complete SDLC and workflow identity binding
# ---------------------------------------------------------------------------

main_path = ROOT / "newsroom" / "increment5" / "main_qualification.py"
main = main_path.read_text(encoding="utf-8")
main = replace_once(
    main,
    dedent(
        '''
        MAIN_QUALIFICATION_WORKFLOW_EVENTS: dict[str, str] = {
            "CI": "push",
            "AUTHORITY_A2A": "push",
            "AUTHORITY_A2B": "push",
            "PROJECTION_B1": "push",
            "PROJECTION_B2_B3_C1_NEO4J": "push",
            "SDLC_EVIDENCE_SHADOW": "workflow_dispatch",
        }
        MAIN_QUALIFICATION_WORKFLOW_NAMES = tuple(MAIN_QUALIFICATION_WORKFLOW_SPECS)
        '''
    ).strip("\n"),
    dedent(
        '''
        MAIN_QUALIFICATION_WORKFLOW_EVENTS: dict[str, str] = {
            "CI": "push",
            "AUTHORITY_A2A": "push",
            "AUTHORITY_A2B": "push",
            "PROJECTION_B1": "push",
            "PROJECTION_B2_B3_C1_NEO4J": "push",
            "SDLC_EVIDENCE_SHADOW": "workflow_dispatch",
        }
        MAIN_QUALIFICATION_WORKFLOW_PATHS: dict[str, str] = {
            "CI": ".github/workflows/ci.yml",
            "AUTHORITY_A2A": ".github/workflows/authority-a2a.yml",
            "AUTHORITY_A2B": ".github/workflows/authority-a2b.yml",
            "PROJECTION_B1": ".github/workflows/projection-b1.yml",
            "PROJECTION_B2_B3_C1_NEO4J": (
                ".github/workflows/projection-b2-neo4j.yml"
            ),
            "SDLC_EVIDENCE_SHADOW": ".github/workflows/evidence.yml",
        }
        MAIN_QUALIFICATION_WORKFLOW_NAMES = tuple(MAIN_QUALIFICATION_WORKFLOW_SPECS)
        '''
    ).strip("\n"),
    label="permanent workflow paths",
)
main = replace_once(
    main,
    dedent(
        '''
                if not (
                    self.workflow_ref.startswith(
                        f"{MAIN_QUALIFICATION_REPOSITORY}/"
                    )
                    and self.workflow_ref.endswith(f"@{MAIN_QUALIFICATION_REF}")
                ):
                    raise Increment5ContractError(
                        "workflow ref is not exact main"
                    )
        '''
    ).strip("\n"),
    dedent(
        '''
                expected_workflow_ref = (
                    f"{MAIN_QUALIFICATION_REPOSITORY}/"
                    f"{MAIN_QUALIFICATION_WORKFLOW_PATHS[self.key]}"
                    f"@{MAIN_QUALIFICATION_REF}"
                )
                if self.workflow_ref != expected_workflow_ref:
                    raise Increment5ContractError(
                        "workflow ref is not the exact permanent main workflow"
                    )
        '''
    ).strip("\n"),
    label="exact workflow ref",
)
main = replace_once(
    main,
    dedent(
        '''
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
        '''
    ).strip("\n"),
    dedent(
        '''
            for field_name, expected in (
                ("repository", MAIN_QUALIFICATION_REPOSITORY),
                ("repository_id", MAIN_QUALIFICATION_REPOSITORY_ID),
                ("head_repository", MAIN_QUALIFICATION_REPOSITORY),
                ("head_repository_id", MAIN_QUALIFICATION_REPOSITORY_ID),
                ("event_name", expected_event),
                ("event_sha", qualified_main_commit_sha),
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
        '''
    ).strip("\n"),
    label="complete SDLC provenance",
)
main = replace_once(
    main,
    dedent(
        '''
        def main_qualification_record_value(
            *,
        '''
    ).strip("\n"),
    dedent(
        '''
        def main_qualification_record_value(
            *,
        '''
    ).strip("\n"),
    label="main claim builder marker",
)
main = replace_once(
    main,
    dedent(
        '''
        ) -> dict[str, object]:
            if not isinstance(proposal, Increment5ADecisionPacket):
        '''
    ).strip("\n"),
    dedent(
        '''
        ) -> dict[str, object]:
            """Build an untrusted canonical claim pending live GitHub authentication."""

            if not isinstance(proposal, Increment5ADecisionPacket):
        '''
    ).strip("\n"),
    label="untrusted main claim documentation",
)
write_text(main_path, main)


# ---------------------------------------------------------------------------
# Source-pinned loader must authenticate claims against live GitHub
# ---------------------------------------------------------------------------

approval_path = ROOT / "newsroom" / "increment5" / "approval.py"
approval = approval_path.read_text(encoding="utf-8")
approval = replace_once(
    approval,
    dedent(
        '''
        from .main_qualification import (
            MAIN_QUALIFICATION_RECORD_DIGEST,
            MAIN_QUALIFICATION_RECORD_PATH,
            Increment5AMainQualificationRecord,
            load_increment5a_main_qualification_record,
        )
        '''
    ).strip("\n"),
    dedent(
        '''
        from .main_qualification import (
            MAIN_QUALIFICATION_RECORD_DIGEST,
            MAIN_QUALIFICATION_RECORD_PATH,
            Increment5AMainQualificationRecord,
            load_increment5a_main_qualification_record,
        )
        from .github_attempts import (
            authenticate_repository_main_qualification_record,
        )
        '''
    ).strip("\n"),
    label="authenticated main loader import",
)
approval = replace_once(
    approval,
    dedent(
        '''
        def _qualification_schema_digest() -> str:
            from .profiles import QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST

            return QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST


        def expected_increment5a_owner_approval_body(
        '''
    ).strip("\n"),
    dedent(
        '''
        def _qualification_schema_digest() -> str:
            from .profiles import QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST

            return QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST


        def _fixture_schema_digest() -> str:
            from .profiles import FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST

            return FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST


        def expected_increment5a_owner_approval_body(
        '''
    ).strip("\n"),
    label="effective fixture digest helper",
)
approval = approval.replace(
    "f`{proposal.bundle.fixture_replay_profile_schema_digest}`",
    "f`{_fixture_schema_digest()}`",
)
approval = replace_once(
    approval,
    dedent(
        '''
                    "fixture_replay_profile_schema_digest": (
                        proposal.bundle.fixture_replay_profile_schema_digest
                    ),
        '''
    ).strip("\n"),
    dedent(
        '''
                    "fixture_replay_profile_schema_digest": (
                        _fixture_schema_digest()
                    ),
        '''
    ).strip("\n"),
    label="approval binds effective fixture schema",
)
approval = replace_once(
    approval,
    dedent(
        '''
                and approval.fixture_replay_profile_schema_digest
                == proposal.bundle.fixture_replay_profile_schema_digest
        '''
    ).strip("\n"),
    dedent(
        '''
                and approval.fixture_replay_profile_schema_digest
                == _fixture_schema_digest()
        '''
    ).strip("\n"),
    label="approval verifies effective fixture schema",
)
approval = replace_once(
    approval,
    dedent(
        '''
        def _main_qualification_loader_factory(
            *,
            path: Path,
            expected_digest: str | None,
            approval_record_digest: str | None,
            parser: Callable[..., Increment5AMainQualificationRecord] = (
                load_increment5a_main_qualification_record
            ),
        ) -> Callable[[], Increment5AMainQualificationRecord | None]:
            captured_path = path
            captured_digest = expected_digest
            captured_approval_digest = approval_record_digest
            captured_parser = parser
        '''
    ).strip("\n"),
    dedent(
        '''
        def _main_qualification_loader_factory(
            *,
            path: Path,
            expected_digest: str | None,
            approval_record_digest: str | None,
            parser: Callable[..., Increment5AMainQualificationRecord] = (
                load_increment5a_main_qualification_record
            ),
            authenticator: Callable[
                [Increment5AMainQualificationRecord],
                Increment5AMainQualificationRecord,
            ] = authenticate_repository_main_qualification_record,
        ) -> Callable[[], Increment5AMainQualificationRecord | None]:
            captured_path = path
            captured_digest = expected_digest
            captured_approval_digest = approval_record_digest
            captured_parser = parser
            captured_authenticator = authenticator
        '''
    ).strip("\n"),
    label="capture live workflow authenticator",
)
approval = replace_once(
    approval,
    dedent(
        '''
                if qualification.record_digest != captured_digest:
                    raise Increment5ContractError(
                        "post-merge main qualification record digest differs"
                    )
                return qualification
        '''
    ).strip("\n"),
    dedent(
        '''
                if qualification.record_digest != captured_digest:
                    raise Increment5ContractError(
                        "post-merge main qualification record digest differs"
                    )
                authenticated = captured_authenticator(qualification)
                if authenticated is not qualification:
                    raise Increment5ContractError(
                        "GitHub authenticator substituted main admission"
                    )
                return qualification
        '''
    ).strip("\n"),
    label="enforce live GitHub authentication",
)
write_text(approval_path, approval)


# ---------------------------------------------------------------------------
# Harden public fixture-replay schema, preserve proposal v1 explicitly
# ---------------------------------------------------------------------------

profiles_path = ROOT / "newsroom" / "increment5" / "profiles.py"
profiles = profiles_path.read_text(encoding="utf-8")
profiles = replace_once(
    profiles,
    dedent(
        '''
        FIXTURE_REPLAY_PROFILE_SCHEMA = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA
        FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
        FIXTURE_REPLAY_PROFILE_SCHEMA_ID = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_ID
        FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_PATH
        FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION = _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION

        QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_ID = "urn:newsroom:increment5:production-qualification-profile:v2"
        '''
    ).strip("\n"),
    dedent(
        '''
        PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA = (
            _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA
        )
        PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = (
            _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
        )
        PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_ID = (
            _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_ID
        )
        PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = (
            _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_PATH
        )
        PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION = (
            _proposal.FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION
        )

        FIXTURE_REPLAY_PROFILE_SCHEMA_ID = (
            "urn:newsroom:increment5:fixture-replay-profile:v2"
        )
        FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION = (
            "increment5-fixture-replay-profile-v2"
        )
        FIXTURE_REPLAY_PROFILE_SCHEMA_PATH = (
            Path(__file__).resolve().parent
            / "data"
            / "increment5_fixture_replay_profile_v2.schema.json"
        )

        QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_ID = "urn:newsroom:increment5:production-qualification-profile:v2"
        '''
    ).strip("\n"),
    label="historical and effective fixture profile names",
)
profiles = replace_once(
    profiles,
    dedent(
        '''
        _SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
        _REQUIRED_MODES = tuple(item.value for item in RetrievalMode)

        RepositoryApprovalBinding = tuple[
        '''
    ).strip("\n"),
    dedent(
        '''
        _SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
        _REQUIRED_MODES = tuple(item.value for item in RetrievalMode)

        _fixture_replay_schema = deepcopy(
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA
        )
        _fixture_replay_schema["$id"] = FIXTURE_REPLAY_PROFILE_SCHEMA_ID
        _fixture_properties = _fixture_replay_schema["properties"]
        assert isinstance(_fixture_properties, dict)
        _fixture_properties["schema_version"] = {
            "const": FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION
        }
        _fixture_budgets = deepcopy(_fixture_properties["budgets"])
        assert isinstance(_fixture_budgets, dict)
        _fixture_budget_properties = _fixture_budgets["properties"]
        assert isinstance(_fixture_budget_properties, dict)
        _fixture_budget_properties["max_external_calls_per_request"] = {
            "const": 0
        }
        _fixture_budget_properties[
            "max_gross_cost_microunits_per_request"
        ] = {"const": 0}
        _fixture_properties["budgets"] = _fixture_budgets
        _fixture_rights = deepcopy(_fixture_properties["rights"])
        assert isinstance(_fixture_rights, dict)
        _fixture_rights_properties = _fixture_rights["properties"]
        assert isinstance(_fixture_rights_properties, dict)
        _fixture_rights_properties["protected_content_allowed"] = {
            "const": False
        }
        _fixture_properties["rights"] = _fixture_rights
        FIXTURE_REPLAY_PROFILE_SCHEMA: dict[str, object] = (
            _fixture_replay_schema
        )
        Draft202012Validator.check_schema(FIXTURE_REPLAY_PROFILE_SCHEMA)
        _FIXTURE_REPLAY_VALIDATOR = Draft202012Validator(
            FIXTURE_REPLAY_PROFILE_SCHEMA
        )
        FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST = digest_bytes(
            canonical_json_bytes(FIXTURE_REPLAY_PROFILE_SCHEMA)
        )


        def _require_fixture_schema_artifact() -> None:
            try:
                data = FIXTURE_REPLAY_PROFILE_SCHEMA_PATH.read_bytes()
                value = json.loads(data.decode("utf-8", errors="strict"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise Increment5ContractError(
                    "cannot load effective fixture-replay schema artifact"
                ) from exc
            if not isinstance(value, dict):
                raise Increment5ContractError(
                    "effective fixture-replay schema artifact must be an object"
                )
            if (
                data != canonical_json_bytes(value)
                or value != FIXTURE_REPLAY_PROFILE_SCHEMA
                or digest_bytes(data)
                != FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
            ):
                raise Increment5ContractError(
                    "effective fixture-replay schema artifact differs from code"
                )


        _require_fixture_schema_artifact()

        RepositoryApprovalBinding = tuple[
        '''
    ).strip("\n"),
    label="effective fixture-replay v2 schema",
)
profiles = replace_once(
    profiles,
    dedent(
        '''
            if profile is RetrievalProfileKind.FIXTURE_REPLAY:
                proposal = _proposal_for_fixture(packet)
                validated = _proposal.validate_profile_manifest(document, packet=proposal)
                return ValidatedRetrievalProfile(
                    profile=validated.profile,
                    decision_payload_digest=validated.decision_payload_digest,
                    contract_bundle_digest=validated.contract_bundle_digest,
                    manifest_digest=validated.manifest_digest,
                    qualification_eligible=False,
                )
        '''
    ).strip("\n"),
    dedent(
        '''
            if profile is RetrievalProfileKind.FIXTURE_REPLAY:
                proposal = _proposal_for_fixture(packet)
                errors = _schema_errors(_FIXTURE_REPLAY_VALIDATOR, document)
                if errors:
                    raise Increment5ProfileError(
                        "retrieval profile schema validation failed: "
                        + errors[0]
                    )
                historical = deepcopy(dict(document))
                historical["schema_version"] = (
                    PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION
                )
                validated = _proposal.validate_profile_manifest(
                    historical,
                    packet=proposal,
                )
                return ValidatedRetrievalProfile(
                    profile=validated.profile,
                    decision_payload_digest=validated.decision_payload_digest,
                    contract_bundle_digest=validated.contract_bundle_digest,
                    manifest_digest=digest_bytes(
                        canonical_json_bytes(document)
                    ),
                    qualification_eligible=False,
                )
        '''
    ).strip("\n"),
    label="public fixture validator",
)
profiles = replace_once(
    profiles,
    dedent(
        '''
        def build_fixture_replay_manifest(
            *,
            packet: object,
            fixture_id: str,
            fixture_manifest_digest: str,
        ) -> dict[str, object]:
            return _proposal.build_fixture_replay_manifest(
                packet=_proposal_for_fixture(packet),
                fixture_id=fixture_id,
                fixture_manifest_digest=fixture_manifest_digest,
            )
        '''
    ).strip("\n"),
    dedent(
        '''
        def build_fixture_replay_manifest(
            *,
            packet: object,
            fixture_id: str,
            fixture_manifest_digest: str,
        ) -> dict[str, object]:
            document = _proposal.build_fixture_replay_manifest(
                packet=_proposal_for_fixture(packet),
                fixture_id=fixture_id,
                fixture_manifest_digest=fixture_manifest_digest,
            )
            document["schema_version"] = (
                FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION
            )
            errors = _schema_errors(_FIXTURE_REPLAY_VALIDATOR, document)
            if errors:
                raise Increment5ProfileError(
                    "fixture-replay schema validation failed: " + errors[0]
                )
            return document
        '''
    ).strip("\n"),
    label="public fixture builder",
)
write_text(profiles_path, profiles)


fixture_v1_path = (
    ROOT
    / "newsroom"
    / "increment5"
    / "data"
    / "increment5_fixture_replay_profile_v1.schema.json"
)
fixture_v2_path = fixture_v1_path.with_name(
    "increment5_fixture_replay_profile_v2.schema.json"
)
fixture_v2 = json.loads(fixture_v1_path.read_text(encoding="utf-8"))
fixture_v2["$id"] = "urn:newsroom:increment5:fixture-replay-profile:v2"
fixture_v2["properties"]["schema_version"] = {
    "const": "increment5-fixture-replay-profile-v2"
}
fixture_v2["properties"]["budgets"]["properties"][
    "max_external_calls_per_request"
] = {"const": 0}
fixture_v2["properties"]["budgets"]["properties"][
    "max_gross_cost_microunits_per_request"
] = {"const": 0}
fixture_v2["properties"]["rights"]["properties"][
    "protected_content_allowed"
] = {"const": False}
fixture_v2_path.write_bytes(canonical_json_bytes(fixture_v2))


# Public exports retain explicit historical proposal names.
init_path = ROOT / "newsroom" / "increment5" / "__init__.py"
init_text = init_path.read_text(encoding="utf-8")
init_text = replace_once(
    init_text,
    dedent(
        '''
            FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA,
        '''
    ).strip("\n"),
    dedent(
        '''
            FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_ID,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA,
        '''
    ).strip("\n"),
    label="fixture proposal imports",
)
init_text = replace_once(
    init_text,
    '    "PROPOSAL_PRODUCTION_PROFILE_SCHEMA",\n',
    dedent(
        '''
            "PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA",
            "PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST",
            "PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_ID",
            "PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_PATH",
            "PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION",
            "PROPOSAL_PRODUCTION_PROFILE_SCHEMA",
        '''
    ),
    label="fixture proposal exports",
)
init_text = replace_once(
    init_text,
    '    MAIN_QUALIFICATION_WORKFLOW_NAMES,\n    MAIN_QUALIFICATION_WORKFLOW_SPECS,\n',
    '    MAIN_QUALIFICATION_WORKFLOW_NAMES,\n    MAIN_QUALIFICATION_WORKFLOW_PATHS,\n    MAIN_QUALIFICATION_WORKFLOW_SPECS,\n',
    label="workflow paths import",
)
init_text = replace_once(
    init_text,
    '    "MAIN_QUALIFICATION_WORKFLOW_NAMES",\n    "MAIN_QUALIFICATION_WORKFLOW_SPECS",\n',
    '    "MAIN_QUALIFICATION_WORKFLOW_NAMES",\n    "MAIN_QUALIFICATION_WORKFLOW_PATHS",\n    "MAIN_QUALIFICATION_WORKFLOW_SPECS",\n',
    label="workflow paths export",
)
write_text(init_path, init_text)


# ---------------------------------------------------------------------------
# Truthful DOPS-074 deferral
# ---------------------------------------------------------------------------

trace_path = ROOT / "newsroom" / "increment5" / "traceability.py"
trace = trace_path.read_text(encoding="utf-8")
trace = replace_once(
    trace,
    '            "DOPS-075",\n',
    '            "DOPS-074",\n            "DOPS-075",\n',
    label="defer DOPS-074 to 5E",
)
trace = replace_once(
    trace,
    '            "DOPS-074",\n            "DOPS-076",\n',
    '            "DOPS-076",\n',
    label="remove DOPS-074 from 5A",
)
trace = replace_once(
    trace,
    '    "DOPS-074": _DECISION_PACKET + "#/payload/rights_matrix",\n',
    '    "DOPS-074": (\n        "issue:#254:deferred:rights-terms-pricing-access-"\n        "credential-change-review-evidence"\n    ),\n',
    label="truthful DOPS-074 anchor",
)
write_text(trace_path, trace)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

github_attempts_test = ROOT / "newsroom" / "tests" / "test_increment5a_github_attempts.py"
write_text(
    github_attempts_test,
    dedent(
        '''
        from __future__ import annotations

        from copy import deepcopy
        import inspect

        import pytest

        import newsroom.increment5.approval as approval_module
        from newsroom.authority.types import UtcTimestamp
        from newsroom.increment5 import Increment5ContractError
        from newsroom.increment5.github_attempts import (
            authenticate_repository_main_qualification_record,
            validate_github_commit_payload,
            validate_github_workflow_attempt_payload,
        )
        from newsroom.increment5.main_qualification import (
            MAIN_QUALIFICATION_REPOSITORY,
            MAIN_QUALIFICATION_REPOSITORY_ID,
            MAIN_QUALIFICATION_WORKFLOW_PATHS,
            Increment5AMainQualificationRecord,
            WorkflowAttemptEvidence,
        )


        _COMMIT = "1" * 40
        _TREE = "2" * 40
        _CREATED = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
        _STARTED = UtcTimestamp.parse("2042-03-12T12:00:01.000000Z")
        _UPDATED = UtcTimestamp.parse("2042-03-12T12:20:00.000000Z")


        def _attempt() -> WorkflowAttemptEvidence:
            return WorkflowAttemptEvidence(
                key="CI",
                workflow_id=232327316,
                workflow_name="CI",
                event="push",
                run_id=1001,
                run_attempt=2,
                run_number=2001,
                head_sha=_COMMIT,
                head_tree_sha=_TREE,
                workflow_sha=_COMMIT,
                workflow_ref=(
                    f"{MAIN_QUALIFICATION_REPOSITORY}/"
                    f"{MAIN_QUALIFICATION_WORKFLOW_PATHS['CI']}"
                    "@refs/heads/main"
                ),
                api_url=(
                    "https://api.github.com/repos/fol2/newsroom/"
                    "actions/runs/1001/attempts/2"
                ),
                html_url=(
                    "https://github.com/fol2/newsroom/actions/runs/1001"
                ),
                created_at=_CREATED,
                run_started_at=_STARTED,
                updated_at=_UPDATED,
            )


        def _payload() -> dict[str, object]:
            return {
                "id": 1001,
                "workflow_id": 232327316,
                "name": "CI",
                "run_number": 2001,
                "run_attempt": 2,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": _COMMIT,
                "head_repository_id": MAIN_QUALIFICATION_REPOSITORY_ID,
                "path": MAIN_QUALIFICATION_WORKFLOW_PATHS["CI"],
                "url": (
                    "https://api.github.com/repos/fol2/newsroom/"
                    "actions/runs/1001"
                ),
                "html_url": (
                    "https://github.com/fol2/newsroom/actions/runs/1001"
                ),
                "created_at": "2042-03-12T12:00:00Z",
                "run_started_at": "2042-03-12T12:00:01Z",
                "updated_at": "2042-03-12T12:20:00Z",
                "repository": {
                    "id": MAIN_QUALIFICATION_REPOSITORY_ID,
                    "full_name": MAIN_QUALIFICATION_REPOSITORY,
                },
                "head_repository": {
                    "id": MAIN_QUALIFICATION_REPOSITORY_ID,
                    "full_name": MAIN_QUALIFICATION_REPOSITORY,
                },
            }


        def _record() -> Increment5AMainQualificationRecord:
            attempt = _attempt()
            return Increment5AMainQualificationRecord(
                qualified_main_commit_sha=_COMMIT,
                qualified_main_tree_sha=_TREE,
                qualified_at=_UPDATED,
                approval_record_digest="sha256:" + "a" * 64,
                proposal_payload_digest="sha256:" + "b" * 64,
                proposal_record_digest="sha256:" + "c" * 64,
                proposal_contract_bundle_digest="sha256:" + "d" * 64,
                qualification_profile_schema_digest="sha256:" + "e" * 64,
                main_qualification_record_schema_digest=(
                    __import__(
                        "newsroom.increment5.main_qualification",
                        fromlist=["MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST"],
                    ).MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST
                ),
                workflow_attempts=(
                    attempt,
                    *(
                        WorkflowAttemptEvidence(
                            key=key,
                            workflow_id=workflow_id,
                            workflow_name=workflow_name,
                            event=(
                                "workflow_dispatch"
                                if key == "SDLC_EVIDENCE_SHADOW"
                                else "push"
                            ),
                            run_id=1001 + index,
                            run_attempt=1,
                            run_number=2001 + index,
                            head_sha=_COMMIT,
                            head_tree_sha=_TREE,
                            workflow_sha=_COMMIT,
                            workflow_ref=(
                                f"{MAIN_QUALIFICATION_REPOSITORY}/"
                                f"{MAIN_QUALIFICATION_WORKFLOW_PATHS[key]}"
                                "@refs/heads/main"
                            ),
                            api_url=(
                                "https://api.github.com/repos/fol2/newsroom/"
                                f"actions/runs/{1001 + index}/attempts/1"
                            ),
                            html_url=(
                                "https://github.com/fol2/newsroom/actions/runs/"
                                f"{1001 + index}"
                            ),
                            created_at=_CREATED,
                            run_started_at=_STARTED,
                            updated_at=_UPDATED,
                        )
                        for index, (key, workflow_id, workflow_name) in enumerate(
                            (
                                ("AUTHORITY_A2A", 315268483, "Authority A2a"),
                                ("AUTHORITY_A2B", 315287552, "Authority A2b"),
                                ("PROJECTION_B1", 317445524, "Projection B1"),
                                (
                                    "PROJECTION_B2_B3_C1_NEO4J",
                                    317681630,
                                    "Projection B2/B3/C1 Neo4j",
                                ),
                                (
                                    "SDLC_EVIDENCE_SHADOW",
                                    318982302,
                                    "SDLC Evidence Shadow",
                                ),
                            ),
                            start=1,
                        )
                    ),
                ),
                decision_document_digest="sha256:" + "f" * 64,
                decision_identity="sha256:" + "1" * 64,
                test_count=1,
                skip_count=0,
                record_digest="sha256:" + "2" * 64,
            )


        def test_exact_authenticated_workflow_attempt_is_accepted() -> None:
            validate_github_workflow_attempt_payload(
                attempt=_attempt(),
                payload=_payload(),
            )


        @pytest.mark.parametrize(
            ("path", "replacement"),
            (
                (("id",), 9999),
                (("workflow_id",), 1),
                (("event",), "workflow_dispatch"),
                (("conclusion",), "failure"),
                (("head_sha",), "3" * 40),
                (("head_repository_id",), 1),
                (("path",), ".github/workflows/other.yml"),
                (("repository", "id"), 1),
                (("repository", "full_name"), "other/repo"),
                (("head_repository", "id"), 1),
                (("head_repository", "full_name"), "other/repo"),
                (("created_at",), "2042-03-12T12:00:02Z"),
            ),
        )
        def test_fabricated_workflow_metadata_is_rejected(
            path: tuple[str, ...],
            replacement: object,
        ) -> None:
            payload = deepcopy(_payload())
            target: dict[str, object] = payload
            for component in path[:-1]:
                nested = target[component]
                assert isinstance(nested, dict)
                target = nested
            target[path[-1]] = replacement
            with pytest.raises(
                Increment5ContractError,
                match="authenticated workflow",
            ):
                validate_github_workflow_attempt_payload(
                    attempt=_attempt(),
                    payload=payload,
                )


        def test_authenticated_commit_must_bind_exact_tree() -> None:
            record = _record()
            valid = {
                "sha": _COMMIT,
                "url": (
                    "https://api.github.com/repos/fol2/newsroom/"
                    f"git/commits/{_COMMIT}"
                ),
                "tree": {"sha": _TREE},
            }
            validate_github_commit_payload(record=record, payload=valid)
            tampered = deepcopy(valid)
            tree = tampered["tree"]
            assert isinstance(tree, dict)
            tree["sha"] = "3" * 40
            with pytest.raises(
                Increment5ContractError,
                match="commit/tree identity differs",
            ):
                validate_github_commit_payload(
                    record=record,
                    payload=tampered,
                )


        def test_synthetic_claim_cannot_authenticate_without_github_token(
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
            monkeypatch.delenv("GITHUB_TOKEN", raising=False)
            with pytest.raises(
                Increment5ContractError,
                match="GitHub workflow evidence is unavailable",
            ):
                authenticate_repository_main_qualification_record(_record())


        def test_source_pinned_loader_captures_the_authenticator() -> None:
            source = inspect.getsource(
                approval_module._main_qualification_loader_factory
            )
            assert "captured_authenticator" in source
            assert "captured_authenticator(qualification)" in source
        '''
    ).lstrip(),
)


# Extend public fixture-schema and owner-binding regressions.
approval_test_path = ROOT / "newsroom" / "tests" / "test_increment5a_approval.py"
approval_test = approval_test_path.read_text(encoding="utf-8")
approval_test = replace_once(
    approval_test,
    dedent(
        '''
            PRODUCTION_PROFILE_SCHEMA_PATH,
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA,
        '''
    ).strip("\n"),
    dedent(
        '''
            PRODUCTION_PROFILE_SCHEMA_PATH,
            FIXTURE_REPLAY_PROFILE_SCHEMA,
            FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
            FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            PROPOSAL_PRODUCTION_PROFILE_SCHEMA,
        '''
    ).strip("\n"),
    label="fixture approval test imports",
)
approval_test = replace_once(
    approval_test,
    dedent(
        '''
        def test_pending_repository_record_is_fail_closed() -> None:
        '''
    ).strip("\n"),
    dedent(
        '''
        def test_generic_fixture_schema_is_only_the_hardened_v2_surface() -> None:
            assert FIXTURE_REPLAY_PROFILE_SCHEMA is not (
                PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA
            )
            assert FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST != (
                PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
            )
            assert FIXTURE_REPLAY_PROFILE_SCHEMA_PATH != (
                PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_PATH
            )
            budgets = FIXTURE_REPLAY_PROFILE_SCHEMA["properties"][
                "budgets"
            ]["properties"]
            rights = FIXTURE_REPLAY_PROFILE_SCHEMA["properties"][
                "rights"
            ]["properties"]
            assert budgets["max_external_calls_per_request"] == {"const": 0}
            assert budgets[
                "max_gross_cost_microunits_per_request"
            ] == {"const": 0}
            assert rights["protected_content_allowed"] == {"const": False}
            value = _approval_value()
            proposal = value["proposal"]
            assert isinstance(proposal, dict)
            assert proposal["fixture_replay_profile_schema_digest"] == (
                FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST
            )


        def test_pending_repository_record_is_fail_closed() -> None:
        '''
    ).strip("\n"),
    label="public fixture approval regression",
)
write_text(approval_test_path, approval_test)


zero_budget_path = ROOT / "newsroom" / "tests" / "test_increment5a_zero_budget_schema.py"
zero_budget = zero_budget_path.read_text(encoding="utf-8")
zero_budget = replace_once(
    zero_budget,
    dedent(
        '''
            INCREMENT_5A_DECISION_PACKET,
            PRODUCTION_PROFILE_SCHEMA,
        '''
    ).strip("\n"),
    dedent(
        '''
            INCREMENT_5A_DECISION_PACKET,
            FIXTURE_REPLAY_PROFILE_SCHEMA,
            FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
            FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
            FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
            PRODUCTION_PROFILE_SCHEMA,
        '''
    ).strip("\n"),
    label="fixture zero-budget imports",
)
zero_budget = replace_once(
    zero_budget,
    dedent(
        '''
        def test_public_v2_schema_artifact_is_exact_canonical_zero_budget_contract() -> None:
        '''
    ).strip("\n"),
    dedent(
        '''
        def test_public_fixture_v2_schema_is_standalone_zero_budget_and_unprotected() -> None:
            schema = FIXTURE_REPLAY_PROFILE_SCHEMA
            budgets = schema["properties"]["budgets"]["properties"]
            rights = schema["properties"]["rights"]["properties"]
            assert budgets["max_external_calls_per_request"] == {"const": 0}
            assert budgets[
                "max_gross_cost_microunits_per_request"
            ] == {"const": 0}
            assert rights["protected_content_allowed"] == {"const": False}

            proposal = INCREMENT_5A_DECISION_PACKET
            manifest = {
                "schema_version": FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
                "profile": RetrievalProfileKind.FIXTURE_REPLAY.value,
                "decision_payload_digest": proposal.payload_digest,
                "contract_bundle_digest": proposal.bundle.contract_digest,
                "runtime_authority": "CONTRACT_AND_FIXTURE_REPLAY_ONLY",
                "qualification_eligible": False,
                "required_modes": schema["properties"]["required_modes"]["const"],
                "graph_free_fallback": False,
                "silent_mode_fallback": False,
                "components": {
                    kind.value: {
                        "contract_id": identity.contract_id,
                        "contract_version": identity.contract_version,
                        "implementation_version": identity.implementation_version,
                        "configuration_digest": identity.configuration_digest,
                        "identity_digest": identity.identity_digest,
                        "implementation_kind": "REPOSITORY_FIXTURE",
                        "approval_status": "NON_QUALIFYING",
                    }
                    for kind, identity in proposal.bundle.component_by_kind.items()
                },
                "budgets": proposal.budgets.canonical_value(),
                "rights": {
                    "protected_content_allowed": False,
                    "rights_rechecked_at_hydration": True,
                    "purge_required": True,
                    "rebuild_must_not_resurrect": True,
                },
                "fixture": {
                    "fixture_id": "fixture-v2",
                    "fixture_manifest_digest": "sha256:" + "f" * 64,
                    "protected_content_present": False,
                    "production_substitution_allowed": False,
                },
            }
            validator = Draft202012Validator(schema)
            assert not tuple(validator.iter_errors(manifest))
            for path, replacement in (
                (("budgets", "max_external_calls_per_request"), 1),
                (("budgets", "max_gross_cost_microunits_per_request"), 1),
                (("rights", "protected_content_allowed"), True),
            ):
                tampered = deepcopy(manifest)
                parent = tampered[path[0]]
                assert isinstance(parent, dict)
                parent[path[1]] = replacement
                assert tuple(validator.iter_errors(tampered))

            data = FIXTURE_REPLAY_PROFILE_SCHEMA_PATH.read_bytes()
            assert data == canonical_json_bytes(
                json.loads(data.decode("utf-8"))
            )
            assert digest_bytes(data) == FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST


        def test_public_v2_schema_artifact_is_exact_canonical_zero_budget_contract() -> None:
        '''
    ).strip("\n"),
    label="standalone fixture schema regression",
)
write_text(zero_budget_path, zero_budget)


trace_test_path = ROOT / "newsroom" / "tests" / "test_increment5a_traceability.py"
trace_test = trace_test_path.read_text(encoding="utf-8")
trace_test = trace_test.replace(
    "for requirement_id in (\"DEVAL-073\", \"DOPS-064\", \"DOPS-072\"):",
    "for requirement_id in (\n        \"DEVAL-073\",\n        \"DOPS-064\",\n        \"DOPS-072\",\n        \"DOPS-074\",\n    ):",
)
trace_test = trace_test.replace(
    "assert counts[Increment5DeliveryTrace.DELIVERED_IN_5A] == 24",
    "assert counts[Increment5DeliveryTrace.DELIVERED_IN_5A] == 23",
)
trace_test = trace_test.replace(
    "assert counts[Increment5DeliveryTrace.DEFERRED_TO_5E] == 41",
    "assert counts[Increment5DeliveryTrace.DEFERRED_TO_5E] == 42",
)
trace_test = replace_once(
    trace_test,
    '        "DOPS-074": packet + "#/payload/rights_matrix",\n',
    dedent(
        '''
                "DOPS-074": (
                    "issue:#254:deferred:rights-terms-pricing-access-"
                    "credential-change-review-evidence"
                ),
        '''
    ),
    label="DOPS-074 test anchor",
)
write_text(trace_test_path, trace_test)


main_test_path = ROOT / "newsroom" / "tests" / "test_increment5a_main_qualification.py"
main_test = main_test_path.read_text(encoding="utf-8")
main_test = replace_once(
    main_test,
    dedent(
        '''
        def test_main_qualification_record_rejects_noncanonical_time(
        '''
    ).strip("\n"),
    dedent(
        '''
        def test_signed_decision_requires_complete_repository_and_event_identity() -> None:
            source = Path(approval_module.__file__).with_name(
                "main_qualification.py"
            ).read_text(encoding="utf-8")
            for field_name in (
                "repository_id",
                "head_repository",
                "head_repository_id",
                "event_sha",
            ):
                assert f'(\"{field_name}\",' in source


        def test_main_qualification_record_rejects_noncanonical_time(
        '''
    ).strip("\n"),
    label="complete SDLC provenance regression",
)
write_text(main_test_path, main_test)


# ---------------------------------------------------------------------------
# Durable documentation
# ---------------------------------------------------------------------------

attempt_doc_path = (
    ROOT
    / "docs"
    / "decisions"
    / "2026-08-01-increment-5a-attempt-bound-main-admission.md"
)
attempt_doc = attempt_doc_path.read_text(encoding="utf-8")
attempt_doc = replace_once(
    attempt_doc,
    dedent(
        '''
        All attempts must be distinct and bind the same declared merged-main
        commit/tree.
        '''
    ).strip("\n"),
    dedent(
        '''
        All attempts must be distinct and bind the same declared merged-main
        commit/tree. Before the source-pinned record can return authority, its loader
        performs authenticated GitHub REST reads for the exact attempt endpoint of
        every workflow and the exact Git commit endpoint. Missing credentials,
        nonexistent runs, failed or unrelated attempts, changed workflow paths,
        repository mismatch, timestamp mismatch, or a wrong commit tree fail closed.
        '''
    ).strip("\n"),
    label="authenticated attempt documentation",
)
write_text(attempt_doc_path, attempt_doc)

postmerge_doc_path = (
    ROOT
    / "docs"
    / "decisions"
    / "2026-08-01-increment-5a-post-merge-qualification-gate.md"
)
postmerge_doc = postmerge_doc_path.read_text(encoding="utf-8")
postmerge_doc = replace_once(
    postmerge_doc,
    "The post-merge record is a separate admission artifact. ",
    (
        "The post-merge record is a separate admission artifact. Its "
        "source-pinned loader authenticates every claimed run attempt and the "
        "qualified commit tree against GitHub REST before returning authority. "
    ),
    label="post-merge live authentication documentation",
)
write_text(postmerge_doc_path, postmerge_doc)

trace_doc_path = ROOT / "docs" / "traceability" / "increment-5-production-retrieval.md"
trace_doc = trace_doc_path.read_text(encoding="utf-8")
trace_doc = replace_once(
    trace_doc,
    "`DEVAL-073`, `DOPS-064` and `DOPS-072` are deliberately assigned to 5E,",
    "`DEVAL-073`, `DOPS-064`, `DOPS-072` and `DOPS-074` are deliberately assigned to 5E,",
    label="DOPS-074 documentation deferral",
)
write_text(trace_doc_path, trace_doc)

owner_doc_path = (
    ROOT
    / "docs"
    / "decisions"
    / "2026-08-01-increment-5a-owner-approval-attestation.md"
)
owner_doc = owner_doc_path.read_text(encoding="utf-8")
owner_doc = replace_once(
    owner_doc,
    "- the fixture-replay profile schema digest;\n",
    "- the hardened effective fixture-replay profile schema digest;\n",
    label="effective fixture owner binding documentation",
)
write_text(owner_doc_path, owner_doc)


# ---------------------------------------------------------------------------
# Compute effective identities in a fresh interpreter and update exact text.
# ---------------------------------------------------------------------------

metadata = json.loads(
    subprocess.check_output(
        [
            sys.executable,
            "-c",
            dedent(
                '''
                import json
                from newsroom.authority.canonical import digest_bytes
                from newsroom.increment5 import (
                    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
                    PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
                    expected_increment5a_owner_approval_body,
                )
                body = expected_increment5a_owner_approval_body()
                print(json.dumps({
                    "fixture": FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
                    "proposal_fixture": PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
                    "body": body,
                    "body_digest": digest_bytes(body.encode("utf-8")),
                }))
                '''
            ),
        ],
        cwd=ROOT,
        text=True,
    )
)
new_body = metadata["body"]
new_body_digest = metadata["body_digest"]
new_fixture_digest = metadata["fixture"]
proposal_fixture_digest = metadata["proposal_fixture"]
if new_fixture_digest == OLD_PUBLIC_FIXTURE_DIGEST:
    raise RuntimeError("effective fixture schema digest did not change")
if proposal_fixture_digest != OLD_PUBLIC_FIXTURE_DIGEST:
    raise RuntimeError("historical proposal fixture schema changed")

for path in tuple((ROOT / "docs").rglob("*.md")) + (
    ROOT / "newsroom" / "tests" / "test_increment5a_approval.py",
):
    value = path.read_text(encoding="utf-8")
    value = value.replace(OLD_OWNER_BODY, new_body)
    value = value.replace(OLD_OWNER_BODY_DIGEST, new_body_digest)
    write_text(path, value)

# Add visible effective/historical fixture identities to the two core decision docs.
for path in (owner_doc_path, attempt_doc_path):
    value = path.read_text(encoding="utf-8")
    marker = "**Owner-body digest:**"
    if marker in value and "**Effective fixture schema:**" not in value:
        line_end = value.find("\n", value.find(marker))
        insertion = (
            f"\n**Proposal fixture schema:** `{proposal_fixture_digest}`"
            f"\n**Effective fixture schema:** `{new_fixture_digest}`"
        )
        value = value[:line_end] + insertion + value[line_end:]
    write_text(path, value)

# The approval test must pin the newly generated exact statement digest.
approval_test = approval_test_path.read_text(encoding="utf-8")
if new_body_digest not in approval_test:
    raise RuntimeError("approval test did not receive new owner-body digest")

# Canonical schema and source guards.
if fixture_v2_path.read_bytes() != canonical_json_bytes(fixture_v2):
    raise RuntimeError("effective fixture schema artifact is not canonical")
if (ROOT / "newsroom" / "increment5" / "data" / "increment5a_owner_approval_record_v1.json").exists():
    raise RuntimeError("owner record appeared before clean review")
if (ROOT / "newsroom" / "increment5" / "data" / "increment5a_main_qualification_record_v2.json").exists():
    raise RuntimeError("main admission record appeared before merge")

print(
    json.dumps(
        {
            "fixture_schema_digest": new_fixture_digest,
            "proposal_fixture_schema_digest": proposal_fixture_digest,
            "owner_body_digest": new_body_digest,
        },
        sort_keys=True,
    )
)
