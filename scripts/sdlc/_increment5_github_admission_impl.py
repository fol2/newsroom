from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if _REPOSITORY_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT.as_posix())

from newsroom.authority.canonical import (  # noqa: E402
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment5.contracts import (  # noqa: E402
    Increment5ContractError,
)
from newsroom.increment5.decision_validation import (  # noqa: E402
    object_without_duplicate_names,
)
from newsroom.increment5.github_evidence import (  # noqa: E402
    validate_github_commit_payload,
    validate_github_workflow_attempt_payload,
)
from newsroom.increment5.main_qualification import (  # noqa: E402
    MAIN_QUALIFICATION_RECORD_PATH,
    Increment5AMainQualificationRecord,
    load_increment5a_main_qualification_record,
)
from scripts.sdlc.artifact_envelope import (  # noqa: E402
    ArtifactProvenanceError,
    _validate_json_depth,
)
from scripts.sdlc.collection_binding import (  # noqa: E402
    CollectionBindingError,
    validate_collection_decision_binding,
)
from scripts.sdlc.contracts import (  # noqa: E402
    ContractError,
    load_contract,
)
from scripts.sdlc.github_transport import (  # noqa: E402
    GitHubActionsClient,
    GitHubTransportError,
    TransportBundle,
    fetch_artifact_bundle,
)


SCHEMA_VERSION = (
    "newsroom.increment5.github-main-admission-authentication.v1"
)
_MAX_JSON_BYTES = 8 * 1024 * 1024
_EXPECTED_DECISION_ARTIFACT_FILES = frozenset(
    {
        "decision-input/collection.json",
        "decision-input/context.json",
        "decision.json",
    }
)


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    return value


def _canonical_json_file(
    path: Path,
    *,
    field: str,
) -> tuple[Mapping[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise Increment5ContractError(f"{field} is not a regular file")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Increment5ContractError(f"{field} is unreadable") from exc
    if not 0 < len(data) <= _MAX_JSON_BYTES:
        raise Increment5ContractError(f"{field} size is invalid")
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
        _validate_json_depth(value)
    except (
        ArtifactProvenanceError,
        Increment5ContractError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise Increment5ContractError(f"{field} is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    if data != canonical_json_bytes(value) + b"\n":
        raise Increment5ContractError(f"{field} is not canonical JSON")
    return value, data


def _artifact_file_inventory(root: Path) -> frozenset[str]:
    if root.is_symlink() or not root.is_dir():
        raise Increment5ContractError(
            "authenticated SDLC artifact root is invalid"
        )
    files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Increment5ContractError(
                "authenticated SDLC artifact contains a symlink"
            )
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise Increment5ContractError(
                "authenticated SDLC artifact member is invalid"
            )
    return frozenset(files)


def validate_authenticated_decision_artifact(
    *,
    extracted_root: Path,
    record_value: Mapping[str, Any],
    record: Increment5AMainQualificationRecord,
) -> dict[str, str]:
    if not isinstance(record, Increment5AMainQualificationRecord):
        raise Increment5ContractError(
            "decision artifact verification requires typed main admission"
        )
    inventory = _artifact_file_inventory(extracted_root)
    if inventory != _EXPECTED_DECISION_ARTIFACT_FILES:
        raise Increment5ContractError(
            "authenticated SDLC decision artifact inventory differs"
        )

    signed = _mapping(
        record_value.get("signed_decision"),
        field="main_qualification.signed_decision",
    )
    embedded = _mapping(
        signed.get("decision_document"),
        field="main_qualification.signed_decision.decision_document",
    )
    expected_decision_bytes = canonical_json_bytes(embedded) + b"\n"
    decision, decision_bytes = _canonical_json_file(
        extracted_root / "decision.json",
        field="authenticated_sdlc.decision",
    )
    if decision_bytes != expected_decision_bytes or decision != embedded:
        raise Increment5ContractError(
            "authenticated SDLC decision bytes differ from main admission"
        )
    document_digest = digest_bytes(canonical_json_bytes(embedded))
    if (
        document_digest != record.decision_document_digest
        or signed.get("decision_document_digest") != document_digest
    ):
        raise Increment5ContractError(
            "authenticated SDLC decision digest differs from main admission"
        )

    context, context_bytes = _canonical_json_file(
        extracted_root / "decision-input" / "context.json",
        field="authenticated_sdlc.context",
    )
    collection, collection_bytes = _canonical_json_file(
        extracted_root / "decision-input" / "collection.json",
        field="authenticated_sdlc.collection",
    )
    decision_context = _mapping(
        decision.get("context"),
        field="authenticated_sdlc.decision.context",
    )
    if context != decision_context:
        raise Increment5ContractError(
            "authenticated SDLC context differs from decision"
        )
    contract = load_contract(_REPOSITORY_ROOT)
    try:
        normalized_collection = validate_collection_decision_binding(
            collection=collection,
            decision=decision,
            contract=contract,
        )
    except CollectionBindingError as exc:
        raise Increment5ContractError(
            "authenticated SDLC collection differs from decision"
        ) from exc
    if collection_bytes != canonical_json_bytes(normalized_collection) + b"\n":
        raise Increment5ContractError(
            "authenticated SDLC collection bytes are not canonical"
        )
    return {
        "decision_file_digest": digest_bytes(decision_bytes),
        "context_file_digest": digest_bytes(context_bytes),
        "collection_file_digest": digest_bytes(collection_bytes),
    }


def _read_source_pinned_record(
    path: Path,
    *,
    expected_record_digest: str,
    approval_record_digest: str,
) -> tuple[Mapping[str, Any], Increment5AMainQualificationRecord]:
    expected_path = MAIN_QUALIFICATION_RECORD_PATH.resolve()
    if path.resolve() != expected_path:
        raise Increment5ContractError(
            "main admission verifier path is not source-pinned"
        )
    if expected_path.is_symlink() or not expected_path.is_file():
        raise Increment5ContractError(
            "source-pinned main admission is not a regular file"
        )
    try:
        data = expected_path.read_bytes()
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=object_without_duplicate_names,
        )
        _validate_json_depth(value)
    except (
        ArtifactProvenanceError,
        Increment5ContractError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise Increment5ContractError(
            "source-pinned main admission is invalid"
        ) from exc
    if (
        not isinstance(value, Mapping)
        or data != canonical_json_bytes(value)
    ):
        raise Increment5ContractError(
            "source-pinned main admission is not canonical JSON"
        )
    try:
        expected_digest = validate_sha256_digest(
            expected_record_digest,
            field="main_qualification_record_digest",
        )
        approval_digest = validate_sha256_digest(
            approval_record_digest,
            field="approval_record_digest",
        )
    except ValueError as exc:
        raise Increment5ContractError(
            "main admission verifier digest is invalid"
        ) from exc
    if digest_bytes(data) != expected_digest:
        raise Increment5ContractError(
            "source-pinned main admission digest differs"
        )
    record = load_increment5a_main_qualification_record(
        expected_path,
        approval_record_digest=approval_digest,
    )
    if record.record_digest != expected_digest:
        raise Increment5ContractError(
            "source-pinned main admission record differs"
        )
    return value, record


def _certificate(
    *,
    record: Increment5AMainQualificationRecord,
    bundle: TransportBundle,
    artifact_digests: Mapping[str, str],
) -> dict[str, object]:
    attempts = [
        {
            "key": attempt.key,
            "run_id": attempt.run_id,
            "run_attempt": attempt.run_attempt,
        }
        for attempt in record.workflow_attempts
    ]
    value: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "record_digest": record.record_digest,
        "qualified_main_commit_sha": record.qualified_main_commit_sha,
        "qualified_main_tree_sha": record.qualified_main_tree_sha,
        "workflow_attempts": attempts,
        "sdlc_artifact": {
            "artifact_id": bundle.artifact.artifact_id,
            "name": bundle.artifact.name,
            "archive_digest": bundle.artifact.digest,
            "transport_identity": bundle.transport_identity,
        },
        "decision_document_digest": record.decision_document_digest,
        "decision_file_digest": artifact_digests[
            "decision_file_digest"
        ],
        "context_file_digest": artifact_digests[
            "context_file_digest"
        ],
        "collection_file_digest": artifact_digests[
            "collection_file_digest"
        ],
        "verifier_source_digest": digest_bytes(
            Path(__file__).read_bytes()
        ),
    }
    value["authentication_identity"] = digest_bytes(
        canonical_json_bytes(value)
    )
    return value


def authenticate_source_pinned_main_admission(
    *,
    record_path: Path,
    expected_record_digest: str,
    approval_record_digest: str,
) -> dict[str, object]:
    record_value, record = _read_source_pinned_record(
        record_path,
        expected_record_digest=expected_record_digest,
        approval_record_digest=approval_record_digest,
    )
    client = GitHubActionsClient.from_environment()
    commit = client.fetch_git_commit(
        record.qualified_main_commit_sha
    )
    validate_github_commit_payload(record=record, payload=commit)
    for attempt in record.workflow_attempts:
        payload = client.fetch_run_attempt(
            attempt.run_id,
            attempt.run_attempt,
        )
        validate_github_workflow_attempt_payload(
            attempt=attempt,
            payload=payload,
        )

    sdlc_attempt = record.workflow_attempt_by_name[
        "SDLC_EVIDENCE_SHADOW"
    ]
    artifact_name = (
        "newsroom-sdlc-decision-"
        f"{sdlc_attempt.run_id}-{sdlc_attempt.run_attempt}-"
        f"{record.qualified_main_commit_sha}"
    )
    with tempfile.TemporaryDirectory(
        prefix="newsroom-increment5a-github-admission-"
    ) as temporary:
        bundle = fetch_artifact_bundle(
            client=client,
            output_parent=temporary,
            output_name="authenticated-sdlc-decision",
            run_id=sdlc_attempt.run_id,
            run_attempt=sdlc_attempt.run_attempt,
            artifact_name=artifact_name,
        )
        extracted_root = (
            Path(temporary)
            / "authenticated-sdlc-decision"
            / bundle.artifact.extracted_path
        )
        artifact_digests = validate_authenticated_decision_artifact(
            extracted_root=extracted_root,
            record_value=record_value,
            record=record,
        )
    return _certificate(
        record=record,
        bundle=bundle,
        artifact_digests=artifact_digests,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Authenticate the source-pinned Increment 5A main admission"
        )
    )
    parser.add_argument("--record-path", required=True)
    parser.add_argument("--expected-record-digest", required=True)
    parser.add_argument("--approval-record-digest", required=True)
    arguments = parser.parse_args(argv)
    try:
        certificate = authenticate_source_pinned_main_admission(
            record_path=Path(arguments.record_path),
            expected_record_digest=arguments.expected_record_digest,
            approval_record_digest=arguments.approval_record_digest,
        )
        sys.stdout.buffer.write(
            canonical_json_bytes(certificate) + b"\n"
        )
    except (
        CollectionBindingError,
        ContractError,
        GitHubTransportError,
        Increment5ContractError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        reason = str(exc) if str(exc) else type(exc).__name__
        print(
            "EVIDENCE_MISMATCH:increment5-github-admission:"
            + reason,
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
