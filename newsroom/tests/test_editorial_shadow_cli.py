from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

import pytest

from newsroom.editorial.legacy_adapter import (
    IntakeError,
    evaluate_legacy_file,
    stable_read,
)
from newsroom.editorial.decisions import evaluate_candidate
from newsroom.editorial.governance_store import GovernanceStore
from newsroom.editorial.packages import build_candidate_package, build_evidence_package
from newsroom.editorial.policy import load_shadow_policy
import scripts.newsroom_editorial_shadow as cli


def legacy_job(
    *,
    run_id: str = "run-1",
    story_id: str = "story_01",
    dedupe_key: str = "event:42",
) -> dict[str, object]:
    return {
        "schema_version": "story_job_v1",
        "run": {"run_id": run_id, "trigger": "manual", "run_time_uk": "2026-07-12T12:00:00+01:00"},
        "story": {
            "story_id": story_id,
            "title": "第三方新聞標題不得輸出",
            "primary_url": "https://publisher.example/protected-expression",
            "supporting_urls": ["https://other.example/report"],
            "dedupe_key": dedupe_key,
        },
        "state": {"status": "SUCCESS"},
        "result": {"final_status": "SUCCESS", "body": "第三方新聞全文不得輸出"},
    }


def write_job(root: Path, value: dict[str, object], name: str = "job.json") -> Path:
    path = root / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_pure_evaluation_holds_legacy_gaps_and_never_mutates_or_discloses_input(
    tmp_path: Path,
) -> None:
    path = write_job(tmp_path, legacy_job())
    before = path.read_bytes()

    output = evaluate_legacy_file(
        root_id="repository-jobs",
        relative_path="job.json",
        policy=load_shadow_policy(),
        root_overrides={"repository-jobs": tmp_path},
    )

    assert path.read_bytes() == before
    assert output["decision"]["outcome"] == "HOLD_FOR_REVIEW"
    assert output["delivery"]["state"] == "NOT_REQUESTED"
    assert output["publication_package_digest"] is None
    assert output["decision"]["reason_codes"] == [
        "MISSING_CLAIM_EVIDENCE",
        "MISSING_RIGHTS",
        "MISSING_SENSITIVE_RISK",
        "MISSING_JURISDICTION",
        "MISSING_ARTICLE_CONTRACT",
    ]
    rendered = json.dumps(output, ensure_ascii=False)
    assert "第三方新聞標題" not in rendered
    assert "第三方新聞全文" not in rendered
    assert "publisher.example" not in rendered
    assert "https://" not in rendered


def test_stable_story_identity_is_separate_from_run_occurrence(tmp_path: Path) -> None:
    first = write_job(tmp_path, legacy_job(run_id="run-1"), "first.json")
    second = write_job(tmp_path, legacy_job(run_id="run-2"), "second.json")
    policy = load_shadow_policy()

    one = evaluate_legacy_file(
        root_id="repository-jobs",
        relative_path=first.name,
        policy=policy,
        root_overrides={"repository-jobs": tmp_path},
    )
    two = evaluate_legacy_file(
        root_id="repository-jobs",
        relative_path=second.name,
        policy=policy,
        root_overrides={"repository-jobs": tmp_path},
    )

    assert one["candidate"]["stable_story_id"] == "event:42"
    assert two["candidate"]["stable_story_id"] == "event:42"
    assert one["candidate"]["candidate_id"] != two["candidate"]["candidate_id"]


def test_url_only_story_key_gets_compatibility_identity_and_mandatory_hold(
    tmp_path: Path,
) -> None:
    write_job(tmp_path, legacy_job(dedupe_key="https://publisher.example/story"))
    output = evaluate_legacy_file(
        root_id="repository-jobs",
        relative_path="job.json",
        policy=load_shadow_policy(),
        root_overrides={"repository-jobs": tmp_path},
    )
    assert output["candidate"]["stable_story_id"].startswith("compat-occurrence:")
    assert "MIGRATION_MISSING_STABLE_STORY_ID" in output["decision"]["reason_codes"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b'{"schema_version":"story_job_v1","run":{"run_id":"a","run_id":"b"}}', "duplicate"),
        (b"not-json", "invalid JSON"),
        (json.dumps({"schema_version": "unknown"}).encode(), "schema_version"),
        (json.dumps({"schema_version": "story_job_v1", "run": {}, "story": {}}).encode(), "occurrence"),
    ],
)
def test_malformed_or_unconstructable_input_is_an_intake_error(
    tmp_path: Path, raw: bytes, message: str
) -> None:
    path = tmp_path / "job.json"
    path.write_bytes(raw)
    with pytest.raises(IntakeError, match=message):
        evaluate_legacy_file(
            root_id="repository-jobs",
            relative_path=path.name,
            policy=load_shadow_policy(),
            root_overrides={"repository-jobs": tmp_path},
        )


def test_stable_read_rejects_traversal_links_hardlinks_and_unsafe_modes(
    tmp_path: Path,
) -> None:
    safe = write_job(tmp_path, legacy_job())
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("{}", encoding="utf-8")
    symlink = tmp_path / "link.json"
    symlink.symlink_to(outside)
    hardlink = tmp_path / "hard.json"
    os.link(safe, hardlink)

    try:
        for relative in ("../outside.json", "link.json", "hard.json"):
            with pytest.raises(IntakeError):
                stable_read(tmp_path, relative, max_bytes=1024 * 1024)

        safe.chmod(0o666)
        with pytest.raises(IntakeError, match="writable"):
            stable_read(tmp_path, safe.name, max_bytes=1024 * 1024)
    finally:
        outside.unlink(missing_ok=True)


def test_stable_read_rejects_oversize_and_identity_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_job(tmp_path, legacy_job())
    with pytest.raises(IntakeError, match="limit"):
        stable_read(tmp_path, path.name, max_bytes=8)

    import newsroom.editorial.legacy_adapter as adapter

    real_fstat = adapter._fstat
    calls = 0

    def changed_fstat(fd: int):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        result = real_fstat(fd)
        if calls != 3:
            return result
        values = list(result)
        values[1] = int(result.st_ino) + 1
        return os.stat_result(values)

    monkeypatch.setattr(adapter, "_fstat", changed_fstat)
    with pytest.raises(IntakeError, match="changed"):
        stable_read(tmp_path, path.name, max_bytes=1024 * 1024)


def test_cli_has_no_arbitrary_root_flag_and_imports_no_live_modules(tmp_path: Path) -> None:
    write_job(tmp_path, legacy_job())
    live_modules = {
        name: sys.modules.get(name)
        for name in ("newsroom.runner", "newsroom.gateway_client")
    }
    output = io.StringIO()
    with redirect_stdout(output):
        rc = cli.main(
            ["evaluate", "--root-id", "repository-jobs", "--path", "job.json"],
            root_overrides={"repository-jobs": tmp_path},
        )
    assert rc == 0
    assert json.loads(output.getvalue())["decision"]["outcome"] == "HOLD_FOR_REVIEW"
    for name, existing_module in live_modules.items():
        assert sys.modules.get(name) is existing_module

    with pytest.raises(SystemExit):
        cli.main(
            [
                "evaluate",
                "--root-id",
                "repository-jobs",
                "--path",
                "job.json",
                "--root",
                str(tmp_path),
            ]
        )


def run_control_cli(args: list[str], state_root: Path) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with redirect_stdout(output):
        rc = cli.main(args, state_root_override=state_root)
    return rc, json.loads(output.getvalue())


def eligible_evaluation():  # type: ignore[no-untyped-def]
    evidence = build_evidence_package(
        {
            "schema_version": "evidence_package_v1",
            "encoding_version": "rfc8785-restricted-v1",
            "digest_algorithm": "sha256",
            "provenance": {
                "run_id": "run-control",
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
            "candidate_id": "run-control:story_01",
            "stable_story_id": "event:control-1",
            "story_version": "v1",
            "evidence_digest": evidence.digest,
            "content_digest": "sha256:" + "2" * 64,
            "asset_digests": [],
            "gate_results": {
                "claim_evidence": "PASS",
                "rights": "PASS",
                "sensitive_risk": "PASS",
                "jurisdiction": "PASS",
            },
            "policy_version": "editorial-shadow-v1",
            "controller_version": "shadow-controller-v1",
            "validator_results": {"article_contract": "PASS"},
            "target": "shadow-recording",
            "provenance": {"run_id": "run-control", "story_id": "story_01"},
        }
    )
    decision = evaluate_candidate(
        candidate=candidate,
        evidence=evidence,
        policy=load_shadow_policy(),
        publication_content={
            "headline": "純合成控制測試",
            "body": "純合成內容。",
            "geographies": ["UK"],
            "categories": ["UK News"],
            "source_refs": ["official"],
            "publisher_id": "newsroom-shadow",
            "content_language": "zh-HK",
            "status": "READY",
        },
    )
    return evidence, candidate, decision


def test_control_cli_records_principal_pause_resume_and_exact_inspection(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    resume_rc, resumed = run_control_cli(
        ["resume", "--actor", "operations", "--reason", "begin proof"],
        state_root,
    )
    assert resume_rc == 0
    assert resumed["pause"]["paused"] is False
    assert resumed["pause"]["actor"] == "operations"
    assert str(resumed["pause"]["principal"]).startswith("uid:")

    evidence, candidate, decision = eligible_evaluation()
    with GovernanceStore(
        state_root / "governance.sqlite3", limits=load_shadow_policy().limits
    ) as store:
        authority = store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=decision.decision,
            publication=decision.publication_package,
        )
        before = store.verify_audit_chain().event_count

    inspect_rc, inspected = run_control_cli(
        ["inspect", "--authority-id", str(authority.authority_id)], state_root
    )
    assert inspect_rc == 0
    assert inspected["authority"]["authority_id"] == authority.authority_id
    assert inspected["authority"]["decision_digest"] == decision.decision.digest
    assert "body" not in json.dumps(inspected)
    with GovernanceStore(
        state_root / "governance.sqlite3", limits=load_shadow_policy().limits
    ) as store:
        assert store.verify_audit_chain().event_count == before + 1

    pause_rc, paused = run_control_cli(
        ["pause", "--actor", "operations", "--reason", "finish proof"],
        state_root,
    )
    assert pause_rc == 0
    assert paused["pause"]["paused"] is True
    assert paused["pause"]["epoch"] == 3
    assert paused["pause"]["reason"] == "finish proof"


def test_record_command_persists_hold_without_intent_or_public_capability(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir(mode=0o700)
    write_job(input_root, legacy_job())
    state_root = tmp_path / "state"
    output = io.StringIO()
    with redirect_stdout(output):
        rc = cli.main(
            ["record", "--root-id", "repository-jobs", "--path", "job.json"],
            root_overrides={"repository-jobs": input_root},
            state_root_override=state_root,
        )
    payload = json.loads(output.getvalue())
    assert rc == 0
    assert payload["decision"]["outcome"] == "HOLD_FOR_REVIEW"
    assert payload["delivery"]["state"] == "NOT_APPLICABLE"
    assert payload["authority"]["revision"] == 1
    with sqlite3.connect(state_root / "governance.sqlite3") as check:
        assert check.execute("SELECT COUNT(*) FROM delivery_intents").fetchone()[0] == 0


def test_resume_never_dispatches_previously_eligible_authority(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    evidence, candidate, decision = eligible_evaluation()
    with GovernanceStore(
        state_root / "governance.sqlite3", limits=load_shadow_policy().limits
    ) as store:
        store.record_evaluation(
            evidence=evidence,
            candidate=candidate,
            decision=decision.decision,
            publication=decision.publication_package,
        )
        assert store.pause_state().paused is True
    (state_root / "governance.sqlite3").chmod(0o600)
    rc, resumed = run_control_cli(
        ["resume", "--actor", "operations", "--reason", "explicit resume"],
        state_root,
    )
    assert rc == 0
    assert resumed["queued_work_dispatched"] is False
    with sqlite3.connect(state_root / "governance.sqlite3") as check:
        assert check.execute("SELECT COUNT(*) FROM delivery_intents").fetchone()[0] == 0


def test_audit_verify_is_audited_and_tamper_returns_nonzero(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    rc, payload = run_control_cli(["audit-verify"], state_root)
    assert rc == 0
    assert payload["audit"]["verified"] is True
    assert payload["audit"]["event_count"] == 2

    database = state_root / "governance.sqlite3"
    with sqlite3.connect(database) as tamper:
        tamper.execute("UPDATE audit_events SET entity_id='changed' WHERE sequence=1")
    failed_rc, failed = run_control_cli(["audit-verify"], state_root)
    assert failed_rc != 0
    assert failed["status"] == "governance_error"


def test_state_root_is_private_and_has_no_cli_or_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setenv("NEWSROOM_EDITORIAL_STATE_ROOT", str(tmp_path / "attacker"))
    rc, _ = run_control_cli(["audit-verify"], state_root)
    assert rc == 0
    assert stat.S_IMODE(state_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((state_root / "governance.sqlite3").stat().st_mode) == 0o600
    assert not (tmp_path / "attacker").exists()

    with pytest.raises(SystemExit):
        cli.main(["audit-verify", "--state-root", str(tmp_path / "other")])

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)
    failed_rc, failed = run_control_cli(["audit-verify"], unsafe)
    assert failed_rc != 0
    assert failed["status"] == "governance_error"
