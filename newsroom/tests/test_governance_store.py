from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import sqlite3
from threading import Barrier

import pytest

from newsroom.editorial.decisions import evaluate_candidate
from newsroom.editorial.governance_store import GovernanceStore, GovernanceStoreError
from newsroom.editorial.governance_store import (
    GovernanceIntegrityError,
    GovernancePausedError,
    GovernanceResourceLimitError,
    StaleFenceError,
)
from newsroom.editorial.packages import build_candidate_package, build_evidence_package
from newsroom.editorial.policy import load_shadow_policy


def _evaluation(*, run_id: str = "run-1", rights: str = "PASS"):
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


def test_bootstrap_is_fail_closed_and_verifies_runtime_configuration(tmp_path) -> None:
    database = tmp_path / "governance.sqlite3"

    with GovernanceStore(database, limits=load_shadow_policy().limits) as store:
        pause = store.pause_state()
        runtime = store.runtime_configuration()
        audit = store.verify_audit_chain()

    assert pause.paused is True
    assert pause.epoch == 1
    assert pause.actor == "SYSTEM"
    assert pause.reason == "BOOTSTRAP_FAIL_CLOSED"
    assert runtime.schema_version == 1
    assert runtime.journal_mode == "wal"
    assert runtime.synchronous == 2
    assert runtime.foreign_keys is True
    assert runtime.busy_timeout_ms == load_shadow_policy().limits.busy_timeout_ms
    assert runtime.max_page_count > 0
    assert audit.event_count == 1
    assert audit.head_sequence == 1
    assert database.exists()


def test_newer_and_partial_schemas_are_rejected(tmp_path) -> None:
    policy = load_shadow_policy()
    newer = tmp_path / "newer.sqlite3"
    with sqlite3.connect(newer) as connection:
        connection.execute("PRAGMA user_version=2")
    with pytest.raises(GovernanceStoreError, match="unsupported governance schema"):
        GovernanceStore(newer, limits=policy.limits)

    partial = tmp_path / "partial.sqlite3"
    with sqlite3.connect(partial) as connection:
        connection.execute("CREATE TABLE partial_state(id INTEGER PRIMARY KEY)")
    with pytest.raises(GovernanceStoreError, match="unversioned"):
        GovernanceStore(partial, limits=policy.limits)


def test_evaluation_commit_is_atomic_idempotent_and_exactly_inspectable(tmp_path) -> None:
    evidence, candidate, result = _evaluation()

    with GovernanceStore(
        tmp_path / "governance.sqlite3", limits=load_shadow_policy().limits
    ) as store:
        first = store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
        replay = store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
        before_inspect = store.verify_audit_chain()
        inspected = store.inspect_evaluation(result.decision.digest)
        after_inspect = store.verify_audit_chain()

    assert first == replay
    assert first.revision == 1
    assert first.stable_story_id == "event:42"
    assert first.story_version == "v1"
    assert first.target == "shadow-recording"
    assert first.decision_digest == result.decision.digest
    assert first.publication_digest == result.publication_package.digest
    assert inspected.authority == first
    assert inspected.candidate_id == "run-1:story_01"
    assert inspected.run_id == "run-1"
    assert inspected.story_id == "story_01"
    assert inspected.outcome == "AUTO_PUBLISH"
    assert before_inspect.event_count == 2
    assert after_inspect.event_count == 3


def test_authority_supersession_is_monotonic_and_audit_failure_rolls_back_every_blob(
    tmp_path,
) -> None:
    database = tmp_path / "governance.sqlite3"
    first_evidence, first_candidate, first_result = _evaluation(run_id="run-1")
    second_evidence, second_candidate, second_result = _evaluation(
        run_id="run-2", rights="MISSING"
    )
    failed_evidence, failed_candidate, failed_result = _evaluation(
        run_id="run-3", rights="UNKNOWN"
    )

    with GovernanceStore(database, limits=load_shadow_policy().limits) as store:
        first = store.record_evaluation(
            evidence=first_evidence,
            candidate=first_candidate,
            decision=first_result.decision,
            publication=first_result.publication_package,
        )
        second = store.record_evaluation(
            evidence=second_evidence,
            candidate=second_candidate,
            decision=second_result.decision,
            publication=second_result.publication_package,
        )
        before_failure = store.verify_audit_chain()

        with sqlite3.connect(database) as fault:
            fault.execute(
                """CREATE TRIGGER reject_evaluation_audit
                   BEFORE INSERT ON audit_events
                   WHEN NEW.event_type = 'EVALUATION_RECORDED'
                   BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END"""
            )
        with pytest.raises(GovernanceStoreError, match="injected audit failure"):
            store.record_evaluation(
                evidence=failed_evidence,
                candidate=failed_candidate,
                decision=failed_result.decision,
                publication=failed_result.publication_package,
            )
        after_failure = store.verify_audit_chain()
        with sqlite3.connect(database) as repair:
            repair.execute("DROP TRIGGER reject_evaluation_audit")
        rollback = store.record_evaluation(
            evidence=first_evidence,
            candidate=first_candidate,
            decision=first_result.decision,
            publication=first_result.publication_package,
        )
        inspected_rollback = store.inspect_authority(rollback.authority_id)

    assert first.revision == 1
    assert second.revision == 2
    assert second.publication_digest is None
    assert second.decision_digest == second_result.decision.digest
    assert rollback.revision == 3
    assert rollback.authority_id != first.authority_id
    assert rollback.decision_digest == first.decision_digest
    assert inspected_rollback.authority == rollback
    assert after_failure == before_failure
    with sqlite3.connect(database) as check:
        for digest in (
            failed_evidence.digest,
            failed_candidate.digest,
            failed_result.decision.digest,
        ):
            assert check.execute(
                "SELECT COUNT(*) FROM packages WHERE digest=?", (digest,)
            ).fetchone()[0] == 0
        assert check.execute(
            "SELECT revision FROM authority_heads WHERE stable_story_id='event:42' AND story_version='v1' AND target='shadow-recording'"
        ).fetchone()[0] == 3


def test_pause_and_resume_advance_epoch_and_are_hash_chain_audited(tmp_path) -> None:
    database = tmp_path / "governance.sqlite3"

    with GovernanceStore(database, limits=load_shadow_policy().limits) as store:
        resumed = store.resume(actor="operator:test", reason="begin shadow evaluation")
        paused = store.pause(actor="operator:test", reason="finish shadow evaluation")
        audit = store.verify_audit_chain()

    assert resumed.paused is False
    assert resumed.epoch == 2
    assert resumed.actor == "operator:test"
    assert paused.paused is True
    assert paused.epoch == 3
    assert paused.reason == "finish shadow evaluation"
    assert audit.event_count == 3

    with GovernanceStore(database, limits=load_shadow_policy().limits) as reopened:
        assert reopened.pause_state() == paused
        assert reopened.verify_audit_chain() == audit


def test_claim_fence_intent_and_receipt_are_atomic_idempotent_store_primitives(
    tmp_path,
) -> None:
    evidence, candidate, result = _evaluation()

    with GovernanceStore(
        tmp_path / "governance.sqlite3", limits=load_shadow_policy().limits
    ) as store:
        authority = store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
        with pytest.raises(GovernancePausedError):
            store.claim_authority(authority.authority_id, owner="worker-a", expected_fence=0)

        store.resume(actor="operator:test", reason="claim fixture")
        first_claim = store.claim_authority(
            authority.authority_id, owner="worker-a", expected_fence=0
        )
        replacement_claim = store.claim_authority(
            authority.authority_id, owner="worker-b", expected_fence=first_claim.fence
        )
        with pytest.raises(StaleFenceError):
            store.record_intent(first_claim, action_version="recording-v1")

        intent = store.record_intent(replacement_claim, action_version="recording-v1")
        replayed_intent = store.record_intent(
            replacement_claim, action_version="recording-v1"
        )
        receipt = store.record_receipt(
            intent.intent_id,
            owner=replacement_claim.owner,
            fence=replacement_claim.fence,
            status="RECORDED_NOT_PUBLISHED",
            payload={"adapter": "recording-only", "recorded": True},
        )
        replayed_receipt = store.record_receipt(
            intent.intent_id,
            owner=replacement_claim.owner,
            fence=replacement_claim.fence,
            status="RECORDED_NOT_PUBLISHED",
            payload={"adapter": "recording-only", "recorded": True},
        )

    assert first_claim.fence == 1
    assert replacement_claim.fence == 2
    assert intent == replayed_intent
    assert intent.state == "INTENT_RECORDED"
    assert receipt == replayed_receipt
    assert receipt.status == "RECORDED_NOT_PUBLISHED"


def test_concurrent_claimers_leave_one_current_fence(tmp_path) -> None:
    database = tmp_path / "governance.sqlite3"
    evidence, candidate, result = _evaluation()
    with GovernanceStore(database, limits=load_shadow_policy().limits) as store:
        authority = store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
        store.resume(actor="operator:test", reason="concurrency proof")

    barrier = Barrier(2)

    def attempt(owner: str):
        try:
            with GovernanceStore(database, limits=load_shadow_policy().limits) as store:
                barrier.wait()
                return store.claim_authority(
                    authority.authority_id, owner=owner, expected_fence=0
                )
        except Exception as exc:  # surfaced for assertions below
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("worker-a", "worker-b")))

    claims = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(claims) == 1
    assert claims[0].fence == 1
    assert len(failures) == 1
    assert isinstance(failures[0], StaleFenceError)


def test_audit_tamper_blocks_reopen_and_package_quota_leaves_only_genesis(tmp_path) -> None:
    policy = load_shadow_policy()
    tampered_database = tmp_path / "tampered.sqlite3"
    evidence, candidate, result = _evaluation()
    with GovernanceStore(tampered_database, limits=policy.limits) as store:
        store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
    with sqlite3.connect(tampered_database) as tamper:
        tamper.execute("UPDATE audit_events SET entity_id='changed' WHERE sequence=2")
    with pytest.raises(GovernanceIntegrityError, match="hash"):
        GovernanceStore(tampered_database, limits=policy.limits)

    quota_database = tmp_path / "quota.sqlite3"
    limits = replace(policy.limits, max_package_bytes=64)
    with GovernanceStore(quota_database, limits=limits) as store:
        with pytest.raises(GovernanceResourceLimitError, match="max_package_bytes"):
            store.record_evaluation(
                evidence=evidence,
                candidate=candidate,
                decision=result.decision,
                publication=result.publication_package,
            )
        assert store.verify_audit_chain().event_count == 1
    with sqlite3.connect(quota_database) as check:
        assert check.execute("SELECT COUNT(*) FROM packages").fetchone()[0] == 0


def test_package_tamper_and_missing_pause_state_fail_on_reopen(tmp_path) -> None:
    policy = load_shadow_policy()
    evidence, candidate, result = _evaluation()

    package_database = tmp_path / "package-tamper.sqlite3"
    with GovernanceStore(package_database, limits=policy.limits) as store:
        store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
    with sqlite3.connect(package_database) as tamper:
        row = tamper.execute(
            "SELECT canonical_bytes FROM packages WHERE digest=?", (candidate.digest,)
        ).fetchone()
        changed = bytes(row[0]).replace(b"event:42", b"event:43")
        assert len(changed) == len(row[0])
        tamper.execute(
            "UPDATE packages SET canonical_bytes=? WHERE digest=?",
            (sqlite3.Binary(changed), candidate.digest),
        )
    with pytest.raises(GovernanceIntegrityError, match="digest"):
        GovernanceStore(package_database, limits=policy.limits)

    pause_database = tmp_path / "pause-missing.sqlite3"
    with GovernanceStore(pause_database, limits=policy.limits):
        pass
    with sqlite3.connect(pause_database) as tamper:
        tamper.execute("DELETE FROM pause_state")
    with pytest.raises(GovernanceIntegrityError, match="pause state"):
        GovernanceStore(pause_database, limits=policy.limits)

    relation_database = tmp_path / "relation-tamper.sqlite3"
    with GovernanceStore(relation_database, limits=policy.limits) as store:
        store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
    with sqlite3.connect(relation_database) as tamper:
        tamper.execute("UPDATE decisions SET outcome='HOLD_FOR_REVIEW'")
    with pytest.raises(GovernanceIntegrityError, match="decision row"):
        GovernanceStore(relation_database, limits=policy.limits)


def test_claim_lease_expires_before_intent(tmp_path) -> None:
    policy = load_shadow_policy()
    evidence, candidate, result = _evaluation()
    clock = ["2026-07-12T12:00:00.000000Z"]
    with GovernanceStore(
        tmp_path / "lease.sqlite3", limits=policy.limits, now=lambda: clock[0]
    ) as store:
        authority = store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=result.decision,
            publication=result.publication_package,
        )
        store.resume(actor="operator:test", reason="lease proof")
        claim = store.claim_authority(
            authority.authority_id,
            owner="worker-a",
            expected_fence=0,
            lease_seconds=1,
        )
        assert datetime.fromisoformat(claim.lease_expires_at.replace("Z", "+00:00")) > datetime.fromisoformat(
            clock[0].replace("Z", "+00:00")
        ).astimezone(UTC)
        clock[0] = "2026-07-12T12:00:02.000000Z"
        with pytest.raises(StaleFenceError, match="lease"):
            store.record_intent(claim, action_version="recording-v1")


def test_reactivated_decision_reuses_semantic_delivery_intent(tmp_path) -> None:
    policy = load_shadow_policy()
    first_evidence, first_candidate, first_result = _evaluation(run_id="run-1")
    hold_evidence, hold_candidate, hold_result = _evaluation(
        run_id="run-2", rights="MISSING"
    )
    with GovernanceStore(tmp_path / "semantic-intent.sqlite3", limits=policy.limits) as store:
        first = store.record_evaluation(
            evidence=first_evidence,
            candidate=first_candidate,
            decision=first_result.decision,
            publication=first_result.publication_package,
        )
        store.resume(actor="operator:test", reason="semantic intent proof")
        first_claim = store.claim_authority(first.authority_id, owner="worker-a", expected_fence=0)
        first_intent = store.record_intent(first_claim, action_version="recording-v1")
        store.record_receipt(
            first_intent.intent_id,
            owner=first_claim.owner,
            fence=first_claim.fence,
            status="RECORDED_NOT_PUBLISHED",
            payload={"adapter": "recording-only", "recorded": True},
        )
        store.record_evaluation(
            evidence=hold_evidence,
            candidate=hold_candidate,
            decision=hold_result.decision,
            publication=hold_result.publication_package,
        )
        reactivated = store.record_evaluation(
            evidence=first_evidence,
            candidate=first_candidate,
            decision=first_result.decision,
            publication=first_result.publication_package,
        )
        new_claim = store.claim_authority(
            reactivated.authority_id, owner="worker-b", expected_fence=0
        )
        replay = store.record_intent(new_claim, action_version="recording-v1")

    assert reactivated.revision == 3
    assert replay.intent_id == first_intent.intent_id
    assert replay.state == "RECORDED_NOT_PUBLISHED"
