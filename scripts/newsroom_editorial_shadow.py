#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import stat
from typing import Iterator, Mapping, Sequence

from newsroom.editorial.governance_store import (
    GovernanceStore,
    GovernanceStoreError,
)
from newsroom.editorial.legacy_adapter import (
    IntakeError,
    evaluate_legacy_file,
    evaluation_metadata,
    prepare_input_file,
)
from newsroom.editorial.policy import EditorialPolicy, load_shadow_policy
from newsroom.editorial.publication_control import ShadowPublicationController


class StateRootError(GovernanceStoreError):
    """Raised when the policy-owned governance location is not private."""


def _add_pretty(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pretty", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Credential-free newsroom editorial shadow evaluator",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser(
        "evaluate",
        help="Evaluate one explicit compatibility input without writing governance state",
        allow_abbrev=False,
    )
    evaluate.add_argument("--root-id", required=True)
    evaluate.add_argument("--path", required=True, dest="relative_path")
    _add_pretty(evaluate)

    record = subparsers.add_parser(
        "record",
        help="Persist an exact evaluation and invoke the recording-only controller if eligible",
        allow_abbrev=False,
    )
    record.add_argument("--root-id", required=True)
    record.add_argument("--path", required=True, dest="relative_path")
    record.add_argument("--expected-fence", type=int, default=0)
    record.add_argument("--lease-seconds", type=int, default=60)
    _add_pretty(record)

    inspect = subparsers.add_parser(
        "inspect", help="Inspect one exact authority revision", allow_abbrev=False
    )
    inspect.add_argument("--authority-id", type=int, required=True)
    _add_pretty(inspect)

    for command in ("pause", "resume"):
        control = subparsers.add_parser(
            command,
            help=f"{command.title()} the local shadow recording scope",
            allow_abbrev=False,
        )
        control.add_argument("--actor", required=True)
        control.add_argument("--reason", required=True)
        _add_pretty(control)

    audit = subparsers.add_parser(
        "audit-verify",
        help="Verify packages, relations, and the audit chain, then audit the inspection",
        allow_abbrev=False,
    )
    _add_pretty(audit)
    return parser


def _same_account_principal() -> str:
    account = pwd.getpwuid(os.getuid())
    return f"uid:{os.getuid()}:{account.pw_name}"


def _check_directory(info: os.stat_result, *, final: bool) -> None:
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise StateRootError("governance state root has unsafe ownership or type")
    forbidden = 0o077 if final else 0o022
    if info.st_mode & forbidden:
        raise StateRootError("governance state root has unsafe permissions")


def _walk_policy_state_root(policy: EditorialPolicy) -> Path:
    if policy.state_root.base != "account_home":
        raise StateRootError("unsupported policy state-root base")
    relative = PurePosixPath(policy.state_root.relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise StateRootError("policy state root is not contained")
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(home, flags)
    current_fd = root_fd
    try:
        _check_directory(os.fstat(root_fd), final=False)
        parts = tuple(part for part in relative.parts if part not in {"", "."})
        for index, component in enumerate(parts):
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
                next_fd = os.open(component, flags, dir_fd=current_fd)
            _check_directory(os.fstat(next_fd), final=index == len(parts) - 1)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
    except OSError as exc:
        raise StateRootError("governance state root is unsafe or unavailable") from exc
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
    return home.joinpath(*relative.parts)


def _test_state_root_override(path: Path) -> Path:
    path = Path(path)
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        pass
    try:
        info = path.lstat()
    except OSError as exc:
        raise StateRootError("governance state root is unavailable") from exc
    _check_directory(info, final=True)
    return path


def _state_database(
    policy: EditorialPolicy,
    *,
    state_root_override: Path | None,
) -> Path:
    root = (
        _test_state_root_override(state_root_override)
        if state_root_override is not None
        else _walk_policy_state_root(policy)
    )
    database = root / "governance.sqlite3"
    if database.exists() or database.is_symlink():
        info = database.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise StateRootError("governance database has unsafe ownership, type, or permissions")
    return database


def _verify_sqlite_files(database: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(database) + suffix)
        if not path.exists() and not path.is_symlink():
            continue
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise StateRootError("governance SQLite file has unsafe ownership, type, or permissions")


@contextmanager
def _open_store(
    policy: EditorialPolicy,
    *,
    state_root_override: Path | None,
) -> Iterator[GovernanceStore]:
    database = _state_database(policy, state_root_override=state_root_override)
    previous_umask = os.umask(0o077)
    try:
        with GovernanceStore(database, limits=policy.limits) as store:
            _verify_sqlite_files(database)
            yield store
            _verify_sqlite_files(database)
    finally:
        os.umask(previous_umask)
        _verify_sqlite_files(database)


def _inspection_payload(inspection) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "status": "ok",
        "mode": "SHADOW_NOT_PRODUCTION",
        "authority": asdict(inspection.authority),
        "occurrence": {
            "candidate_id": inspection.candidate_id,
            "run_id": inspection.run_id,
            "story_id": inspection.story_id,
        },
        "packages": {
            "evidence_digest": inspection.evidence_digest,
            "candidate_digest": inspection.candidate_digest,
            "decision_digest": inspection.decision_digest,
            "publication_digest": inspection.publication_digest,
        },
        "decision": {
            "outcome": inspection.outcome,
            "policy_version": inspection.policy_version,
            "controller_version": inspection.controller_version,
        },
        "integrity": "VERIFIED",
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    root_overrides: Mapping[str, Path] | None = None,
    state_root_override: Path | None = None,
) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    policy = load_shadow_policy()
    principal = _same_account_principal()
    try:
        if args.command == "evaluate":
            payload = evaluate_legacy_file(
                root_id=args.root_id,
                relative_path=args.relative_path,
                policy=policy,
                root_overrides=root_overrides,
            )
        else:
            with _open_store(
                policy,
                state_root_override=state_root_override,
            ) as store:
                if args.command == "record":
                    prepared = prepare_input_file(
                        root_id=args.root_id,
                        relative_path=args.relative_path,
                        policy=policy,
                        root_overrides=root_overrides,
                    )
                    authority = store.record_evaluation(
                        evidence=prepared.evidence,
                        candidate=prepared.candidate,
                        decision=prepared.decision.decision,
                        publication=prepared.decision.publication_package,
                        principal=principal,
                    )
                    payload = evaluation_metadata(prepared, policy)
                    payload["authority"] = asdict(authority)
                    if prepared.decision.outcome == "AUTO_PUBLISH":
                        recorded = ShadowPublicationController(store).record(
                            authority.authority_id,
                            owner=f"{principal}:pid:{os.getpid()}",
                            expected_fence=args.expected_fence,
                            lease_seconds=args.lease_seconds,
                        )
                        payload["delivery"] = asdict(recorded)
                    else:
                        payload["delivery"] = {"state": "NOT_APPLICABLE"}
                elif args.command == "inspect":
                    payload = _inspection_payload(
                        store.inspect_authority(
                            args.authority_id,
                            principal=principal,
                        )
                    )
                elif args.command in {"pause", "resume"}:
                    action = store.pause if args.command == "pause" else store.resume
                    pause = action(
                        actor=args.actor,
                        reason=args.reason,
                        principal=principal,
                    )
                    payload = {
                        "status": "ok",
                        "mode": "SHADOW_NOT_PRODUCTION",
                        "pause": asdict(pause),
                        "queued_work_dispatched": False,
                    }
                elif args.command == "audit-verify":
                    audit = store.verify_and_audit(principal=principal)
                    payload = {
                        "status": "ok",
                        "mode": "SHADOW_NOT_PRODUCTION",
                        "audit": {
                            "verified": True,
                            "event_count": audit.event_count,
                            "head_sequence": audit.head_sequence,
                            "head_hash": audit.head_hash,
                        },
                    }
                else:
                    raise IntakeError("unsupported shadow command")
        rc = 0
    except IntakeError as exc:
        payload = {
            "status": "intake_error",
            "error": {"type": "INTAKE_ERROR", "message": str(exc)},
            "delivery": {"state": "NOT_REQUESTED"},
        }
        rc = 2
    except (GovernanceStoreError, ValueError) as exc:
        payload = {
            "status": "governance_error",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "delivery": {"state": "NOT_REQUESTED"},
        }
        rc = 3
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
