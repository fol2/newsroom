from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping

from .decisions import DecisionEvaluationError, evaluate_candidate
from .packages import (
    PackageValidationError,
    build_candidate_package,
    build_evidence_package,
    canonicalise_json,
    parse_json_bytes,
)
from .policy import EditorialPolicy


class IntakeError(ValueError):
    """Raised before semantic decision when compatibility input is unsafe."""


_fstat = os.fstat
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _require_posix_capabilities() -> None:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if os.name != "posix" or any(not hasattr(os, name) for name in required):
        raise IntakeError("required POSIX descriptor capabilities are unavailable")
    if os.open not in os.supports_dir_fd:
        raise IntakeError("descriptor-relative open is unavailable")


def _contained_parts(relative_path: str) -> tuple[str, ...]:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or relative_path in {"", "."} or ".." in path.parts:
        raise IntakeError("input path traversal is not permitted")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise IntakeError("input path is empty")
    return parts


def _check_owned_mode(info: os.stat_result, *, label: str, regular: bool) -> None:
    if info.st_uid != os.getuid():
        raise IntakeError(f"{label} is not owned by the current OS account")
    if info.st_mode & 0o022:
        raise IntakeError(f"{label} is group/world writable")
    expected = stat.S_ISREG if regular else stat.S_ISDIR
    if not expected(info.st_mode):
        raise IntakeError(f"{label} has an unsupported file type")
    if regular and info.st_nlink != 1:
        raise IntakeError(f"{label} has multiple hard links")


def stable_read(root: Path, relative_path: str, *, max_bytes: int) -> bytes:
    """Read one file through pinned descriptors without reopening its pathname."""

    _require_posix_capabilities()
    if max_bytes <= 0:
        raise IntakeError("input byte limit must be positive")
    parts = _contained_parts(relative_path)
    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    root_fd: int | None = None
    current_fd: int | None = None
    file_fd: int | None = None
    try:
        root_fd = os.open(root, root_flags)
        current_fd = root_fd
        root_info = _fstat(root_fd)
        _check_owned_mode(root_info, label="trusted input root", regular=False)

        for component in parts[:-1]:
            next_fd = os.open(
                component,
                root_flags,
                dir_fd=current_fd,
            )
            info = _fstat(next_fd)
            _check_owned_mode(info, label="input parent directory", regular=False)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd

        file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
        before = _fstat(file_fd)
        _check_owned_mode(before, label="input file", regular=True)
        if before.st_size > max_bytes:
            raise IntakeError("input exceeds the configured byte limit")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(65_536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise IntakeError("input exceeds the configured byte limit")
        after = _fstat(file_fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_mode,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_mode,
        )
        if identity_before != identity_after or total != before.st_size:
            raise IntakeError("input changed during the stable read")
        return b"".join(chunks)
    except OSError as exc:
        raise IntakeError(f"unsafe or unavailable input path: {exc.strerror or exc}") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if current_fd is not None and current_fd != root_fd:
            os.close(current_fd)
        if root_fd is not None:
            os.close(root_fd)


def _resolve_root(
    *,
    root_id: str,
    policy: EditorialPolicy,
    root_overrides: Mapping[str, Path] | None,
) -> Path:
    configured = next(
        (root for root in policy.trusted_input_roots if root.root_id == root_id),
        None,
    )
    if configured is None:
        raise IntakeError("unknown trusted input root identifier")
    if root_overrides is not None and root_id in root_overrides:
        return Path(root_overrides[root_id])
    if configured.base != "repository":
        raise IntakeError("unsupported trusted input root base")
    return _REPOSITORY_ROOT / configured.relative_path


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"legacy occurrence is missing {field}")
    return value.strip()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_story_id(story: Mapping[str, Any], *, run_id: str, story_id: str) -> tuple[str, bool]:
    event_id = story.get("event_id")
    if isinstance(event_id, int) and not isinstance(event_id, bool) and event_id > 0:
        return f"event:{event_id}", False
    dedupe_key = story.get("dedupe_key")
    if isinstance(dedupe_key, str):
        key = " ".join(dedupe_key.strip().split())
        if key.startswith("event:") and key[6:].isdigit() and int(key[6:]) > 0:
            return f"event:{int(key[6:])}", False
        if key and "://" not in key and len(key) <= 512:
            return "legacy-dedupe:" + hashlib.sha256(key.encode()).hexdigest(), False
    occurrence = canonicalise_json({"run_id": run_id, "story_id": story_id})
    return "compat-occurrence:" + hashlib.sha256(occurrence).hexdigest(), True


def _project_legacy_job(value: Any, policy: EditorialPolicy) -> tuple[Any, Any, tuple[str, ...]]:
    if not isinstance(value, dict) or value.get("schema_version") != "story_job_v1":
        raise IntakeError("unsupported legacy schema_version")
    run = value.get("run")
    story = value.get("story")
    if not isinstance(run, dict) or not isinstance(story, dict):
        raise IntakeError("legacy occurrence is missing run or story")
    run_id = _required_text(run.get("run_id"), field="run_id")
    story_id = _required_text(story.get("story_id"), field="story_id")
    candidate_id = f"{run_id}:{story_id}"
    stable_story_id, compatibility_identity = _stable_story_id(
        story,
        run_id=run_id,
        story_id=story_id,
    )

    raw_sources = [story.get("primary_url")]
    supporting = story.get("supporting_urls")
    if isinstance(supporting, list):
        raw_sources.extend(supporting)
    sources = [item.strip() for item in raw_sources if isinstance(item, str) and item.strip()]
    if not sources:
        raise IntakeError("legacy occurrence is missing source provenance")
    source_refs = [
        {
            "source_id": f"legacy-source-{index}",
            "source_digest": _sha256_text(source),
            "rights_status": "UNKNOWN",
        }
        for index, source in enumerate(sources, start=1)
    ]
    evidence = build_evidence_package(
        {
            "schema_version": "evidence_package_v1",
            "encoding_version": "rfc8785-restricted-v1",
            "digest_algorithm": "sha256",
            "provenance": {
                "run_id": run_id,
                "story_id": story_id,
                "source_refs": source_refs,
            },
            "claims": [],
            "component_versions": {"extractor": "legacy-adapter-v1"},
        }
    )

    result = value.get("result") if isinstance(value.get("result"), dict) else {}
    content_fingerprint = canonicalise_json(
        {
            "title": story.get("title") if isinstance(story.get("title"), str) else None,
            "result_body": result.get("body") if isinstance(result.get("body"), str) else None,
            "result_status": result.get("final_status")
            if isinstance(result.get("final_status"), str)
            else None,
        }
    )
    content_digest = "sha256:" + hashlib.sha256(content_fingerprint).hexdigest()
    candidate = build_candidate_package(
        {
            "schema_version": "editorial_candidate_v1",
            "encoding_version": "rfc8785-restricted-v1",
            "digest_algorithm": "sha256",
            "candidate_id": candidate_id,
            "stable_story_id": stable_story_id,
            "story_version": "legacy:" + content_digest[7:23],
            "evidence_digest": evidence.digest,
            "content_digest": content_digest,
            "asset_digests": [],
            "gate_results": {
                "claim_evidence": "MISSING",
                "rights": "MISSING",
                "sensitive_risk": "MISSING",
                "jurisdiction": "MISSING",
            },
            "policy_version": policy.policy_id,
            "controller_version": policy.component_versions["controller"],
            "validator_results": {"article_contract": "MISSING"},
            "target": policy.target_allowlist[0],
            "provenance": {"run_id": run_id, "story_id": story_id},
        }
    )
    compatibility_reasons = (
        ("MIGRATION_MISSING_STABLE_STORY_ID",) if compatibility_identity else ()
    )
    return evidence, candidate, compatibility_reasons


def evaluate_legacy_file(
    *,
    root_id: str,
    relative_path: str,
    policy: EditorialPolicy,
    root_overrides: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    root = _resolve_root(
        root_id=root_id,
        policy=policy,
        root_overrides=root_overrides,
    )
    data = stable_read(root, relative_path, max_bytes=policy.limits.max_input_bytes)
    try:
        legacy_value = parse_json_bytes(data, max_bytes=policy.limits.max_input_bytes)
        evidence, candidate, compatibility_reasons = _project_legacy_job(
            legacy_value,
            policy,
        )
        decision = evaluate_candidate(
            candidate=candidate,
            evidence=evidence,
            policy=policy,
            publication_content=None,
            compatibility_reason_codes=compatibility_reasons,
        )
    except (PackageValidationError, DecisionEvaluationError) as exc:
        raise IntakeError(str(exc)) from exc

    return {
        "status": "ok",
        "mode": "SHADOW_NOT_PRODUCTION",
        "policy_version": policy.policy_id,
        "input": {"root_id": root_id, "byte_size": len(data)},
        "evidence": {
            "digest": evidence.digest,
            "byte_size": evidence.byte_size,
            "integrity": "VERIFIED",
        },
        "candidate": {
            "candidate_id": candidate.value["candidate_id"],
            "stable_story_id": candidate.value["stable_story_id"],
            "story_version": candidate.value["story_version"],
            "digest": candidate.digest,
            "byte_size": candidate.byte_size,
            "integrity": "VERIFIED",
        },
        "decision": {
            "digest": decision.decision.digest,
            "outcome": decision.outcome,
            "reason_codes": list(decision.reason_codes),
            "policy_version": policy.policy_id,
            "controller_version": policy.component_versions["controller"],
        },
        "publication_package_digest": (
            decision.publication_package.digest
            if decision.publication_package is not None
            else None
        ),
        "delivery": {"state": decision.delivery_state},
        "capability_boundary": "NO_LIVE_DEPENDENCY_EDGE",
    }
