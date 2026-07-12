from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from newsroom.editorial.decisions import evaluate_candidate
from newsroom.editorial.governance_store import (
    GovernanceConflictError,
    GovernanceIntegrityError,
    GovernancePausedError,
    GovernanceStore,
)
from newsroom.editorial.packages import build_candidate_package, build_evidence_package
from newsroom.editorial.policy import load_shadow_policy
from newsroom.editorial.publication_control import ShadowPublicationController
from newsroom.editorial.publishers import RecordingAdapterResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def evaluation(*, run_id: str = "run-1", rights: str = "PASS"):
    evidence = build_evidence_package(
        {
            "schema_version": "evidence_package_v1",
            "encoding_version": "rfc8785-restricted-v1",
            "digest_algorithm": "sha256",
            "provenance": {
                "run_id": run_id,
                "story_id": "story_01",
                "source_refs": [
                    {
                        "source_id": "official",
                        "source_digest": "sha256:" + "1" * 64,
                        "rights_status": "PERMITTED",
                    }
                ],
            },
            "claims": [{"claim_id": "claim-1", "evidence_refs": ["official"]}],
            "component_versions": {"extractor": "shadow-fixture-v1"},
        }
    )
    candidate = build_candidate_package(
        {
            "schema_version": "editorial_candidate_v1",
            "encoding_version": "rfc8785-restricted-v1",
            "digest_algorithm": "sha256",
            "candidate_id": f"{run_id}:story_01",
            "stable_story_id": "event:42",
            "story_version": "v1",
            "evidence_digest": evidence.digest,
            "content_digest": "sha256:" + "2" * 64,
            "asset_digests": [],
            "gate_results": {
                "claim_evidence": "PASS",
                "rights": rights,
                "sensitive_risk": "PASS",
                "jurisdiction": "PASS",
            },
            "policy_version": "editorial-shadow-v1",
            "controller_version": "shadow-controller-v1",
            "validator_results": {"article_contract": "PASS"},
            "target": "shadow-recording",
            "provenance": {"run_id": run_id, "story_id": "story_01"},
        }
    )
    result = evaluate_candidate(
        candidate=candidate,
        evidence=evidence,
        policy=load_shadow_policy(),
        publication_content={
            "headline": "英國公共服務安排更新",
            "body": "呢份係純合成測試內容，唔包含第三方新聞原文。",
            "geographies": ["UK"],
            "categories": ["UK News"],
            "source_refs": ["official"],
            "publisher_id": "newsroom-shadow",
            "content_language": "zh-HK",
            "status": "READY",
        },
    )
    return evidence, candidate, result


def store_with_authority(tmp_path, *, resumed: bool = True):  # type: ignore[no-untyped-def]
    store = GovernanceStore(
        tmp_path / "governance.sqlite3", limits=load_shadow_policy().limits
    )
    evidence, candidate, result = evaluation()
    authority = store.record_evaluation(
        evidence=evidence,
        candidate=candidate,
        decision=result.decision,
        publication=result.publication_package,
    )
    if resumed:
        store.resume(actor="operator:test", reason="controller proof")
    return store, authority


def test_eligible_recording_is_idempotent_and_never_public(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store, authority = store_with_authority(tmp_path)
    with store:
        controller = ShadowPublicationController(store)
        calls: list[bytes] = []
        original = controller._publisher.record

        def counted(*, publication_bytes: bytes, intent_id: str):  # type: ignore[no-untyped-def]
            calls.append(publication_bytes)
            return original(publication_bytes=publication_bytes, intent_id=intent_id)

        monkeypatch.setattr(controller._publisher, "record", counted)
        first = controller.record(authority.authority_id, owner="worker-a", expected_fence=0)
        replay = controller.record(authority.authority_id, owner="worker-b", expected_fence=1)

    assert first.status == "RECORDED_NOT_PUBLISHED"
    assert replay.status == "RECORDED_NOT_PUBLISHED"
    assert first.intent_id == replay.intent_id
    assert len(calls) == 1
    assert first.public_effect is False


def test_pause_before_claim_or_inside_intent_prevents_adapter_call(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store, authority = store_with_authority(tmp_path, resumed=False)
    with store:
        controller = ShadowPublicationController(store)
        monkeypatch.setattr(
            controller._publisher,
            "record",
            lambda **_: pytest.fail("recording adapter must not run while paused"),
        )
        with pytest.raises(GovernancePausedError):
            controller.record(authority.authority_id, owner="worker-a", expected_fence=0)

        store.resume(actor="operator:test", reason="between-boundary proof")
        original = store.record_intent

        def pause_then_intent(*args, **kwargs):  # type: ignore[no-untyped-def]
            store.pause(actor="operator:test", reason="pause before intent")
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "record_intent", pause_then_intent)
        with pytest.raises(GovernancePausedError):
            controller.record(authority.authority_id, owner="worker-a", expected_fence=0)


def test_pause_after_intent_does_not_retroactively_cancel_entered_recording(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store, authority = store_with_authority(tmp_path)
    with store:
        controller = ShadowPublicationController(store)

        def pause_during_adapter(*, publication_bytes: bytes, intent_id: str):  # type: ignore[no-untyped-def]
            store.pause(actor="operator:test", reason="ordered after intent")
            return RecordingAdapterResult(
                status="RECORDED_NOT_PUBLISHED",
                metadata={"adapter": "recording-only-v1", "intent_id": intent_id},
            )

        monkeypatch.setattr(controller._publisher, "record", pause_during_adapter)
        result = controller.record(authority.authority_id, owner="worker-a", expected_fence=0)
        assert store.pause_state().paused is True

    assert result.status == "RECORDED_NOT_PUBLISHED"


def test_adapter_exception_and_prior_unfinished_intent_become_terminal_unknown(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store, authority = store_with_authority(tmp_path)
    with store:
        controller = ShadowPublicationController(store)
        monkeypatch.setattr(
            controller._publisher,
            "record",
            lambda **_: (_ for _ in ()).throw(RuntimeError("ambiguous adapter return")),
        )
        unknown = controller.record(
            authority.authority_id, owner="worker-a", expected_fence=0
        )
        assert unknown.status == "UNKNOWN"
        replay = controller.record(
            authority.authority_id, owner="worker-b", expected_fence=1
        )
        assert replay.status == "UNKNOWN"

    second_store, second_authority = store_with_authority(tmp_path / "prior")
    with second_store:
        first_claim = second_store.claim_authority(
            second_authority.authority_id, owner="crashed", expected_fence=0
        )
        prior = second_store.record_intent(first_claim, action_version="recording-v1")
        controller = ShadowPublicationController(second_store)
        monkeypatch.setattr(
            controller._publisher,
            "record",
            lambda **_: pytest.fail("an unfinished prior intent must not be retried"),
        )
        reconciled = controller.record(
            second_authority.authority_id, owner="replacement", expected_fence=1
        )
    assert reconciled.intent_id == prior.intent_id
    assert reconciled.status == "UNKNOWN"


def test_superseded_authority_audit_failure_and_integrity_failure_call_nothing(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store, authority = store_with_authority(tmp_path)
    with store:
        hold_evidence, hold_candidate, hold_result = evaluation(
            run_id="run-2", rights="MISSING"
        )
        store.record_evaluation(
            evidence=hold_evidence,
            candidate=hold_candidate,
            decision=hold_result.decision,
            publication=hold_result.publication_package,
        )
        controller = ShadowPublicationController(store)
        monkeypatch.setattr(
            controller._publisher,
            "record",
            lambda **_: pytest.fail("superseded authority must not call adapter"),
        )
        with pytest.raises(GovernanceConflictError):
            controller.record(authority.authority_id, owner="worker-a", expected_fence=0)

    audit_store, audit_authority = store_with_authority(tmp_path / "audit")
    with audit_store:
        with sqlite3.connect(audit_store.path) as fault:
            fault.execute(
                """CREATE TRIGGER reject_intent_audit BEFORE INSERT ON audit_events
                   WHEN NEW.event_type='DELIVERY_INTENT_RECORDED'
                   BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"""
            )
        controller = ShadowPublicationController(audit_store)
        monkeypatch.setattr(
            controller._publisher,
            "record",
            lambda **_: pytest.fail("audit failure must prevent adapter entry"),
        )
        with pytest.raises(Exception, match="audit unavailable"):
            controller.record(
                audit_authority.authority_id, owner="worker-a", expected_fence=0
            )

    integrity_store, integrity_authority = store_with_authority(tmp_path / "integrity")
    with integrity_store:
        controller = ShadowPublicationController(integrity_store)
        monkeypatch.setattr(
            integrity_store,
            "publication_bytes",
            lambda _: (_ for _ in ()).throw(GovernanceIntegrityError("tamper")),
        )
        monkeypatch.setattr(
            controller._publisher,
            "record",
            lambda **_: pytest.fail("integrity failure must prevent adapter entry"),
        )
        outcome = controller.record(
            integrity_authority.authority_id, owner="worker-a", expected_fence=0
        )
    assert outcome.status == "UNKNOWN"


def test_receipt_audit_failure_after_adapter_becomes_unknown_without_retry(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store, authority = store_with_authority(tmp_path)
    with store:
        with sqlite3.connect(store.path) as fault:
            fault.execute(
                """CREATE TRIGGER reject_receipt_audit BEFORE INSERT ON audit_events
                   WHEN NEW.event_type='DELIVERY_RECEIPT_RECORDED'
                   BEGIN SELECT RAISE(ABORT, 'receipt audit unavailable'); END"""
            )
        controller = ShadowPublicationController(store)
        calls = 0
        original = controller._publisher.record

        def counted(**kwargs):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return original(**kwargs)

        monkeypatch.setattr(controller._publisher, "record", counted)
        outcome = controller.record(
            authority.authority_id, owner="worker-a", expected_fence=0
        )
        replay = controller.record(
            authority.authority_id, owner="worker-b", expected_fence=1
        )

    assert outcome.status == "UNKNOWN"
    assert replay.status == "UNKNOWN"
    assert calls == 1


def test_controller_import_graph_has_no_live_or_network_modules() -> None:
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import newsroom.editorial.publication_control; "
                "forbidden={'newsroom.runner','newsroom.gateway_client','requests'}; "
                "assert not (forbidden & set(sys.modules)), forbidden & set(sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


def test_cli_evaluate_and_eligible_record_have_no_network_egress(
    tmp_path: Path,
) -> None:
    environment = {
        name: value
        for name, value in os.environ.items()
        if "GATEWAY" not in name.upper() and "DISCORD" not in name.upper()
    }
    environment["OPENCLAW_HOME"] = str(tmp_path / "empty-openclaw-home")
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory

attempts = []
real_socket = socket.socket


def deny(operation):
    def denied(*args, **kwargs):
        attempts.append(operation)
        raise AssertionError(f"network egress attempted: {operation}")

    return denied


class DeniedSocket(real_socket):
    connect = deny("socket.connect")
    connect_ex = deny("socket.connect_ex")
    sendto = deny("socket.sendto")
    sendmsg = deny("socket.sendmsg")


socket.socket = DeniedSocket
socket.SocketType = DeniedSocket
socket.create_connection = deny("socket.create_connection")
socket.getaddrinfo = deny("socket.getaddrinfo")

from scripts import newsroom_editorial_shadow as cli

fixture_root = Path("newsroom/evals/editorial_shadow").resolve()


def run(arguments, *, state_root=None):
    output = io.StringIO()
    with redirect_stdout(output):
        return_code = cli.main(
            arguments,
            root_overrides={"repository-fixtures": fixture_root},
            state_root_override=state_root,
        )
    return return_code, json.loads(output.getvalue())


evaluate_code, evaluated = run(
    [
        "evaluate",
        "--root-id",
        "repository-fixtures",
        "--path",
        "eligible.json",
    ]
)
assert evaluate_code == 0
assert evaluated["decision"]["outcome"] == "AUTO_PUBLISH"

with TemporaryDirectory() as temporary_directory:
    state_root = Path(temporary_directory) / "state"
    resume_code, _ = run(
        ["resume", "--actor", "zero-egress-proof", "--reason", "record fixture"],
        state_root=state_root,
    )
    assert resume_code == 0
    record_code, recorded = run(
        [
            "record",
            "--root-id",
            "repository-fixtures",
            "--path",
            "eligible.json",
        ],
        state_root=state_root,
    )

assert record_code == 0
assert recorded["decision"]["outcome"] == "AUTO_PUBLISH"
assert "RECORDED_NOT_PUBLISHED" in {
    recorded["delivery"].get("state"),
    recorded["delivery"].get("status"),
}
assert attempts == [], attempts
""",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr or check.stdout
