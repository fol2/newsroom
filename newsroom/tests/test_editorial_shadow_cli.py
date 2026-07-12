from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys

import pytest

from newsroom.editorial.legacy_adapter import (
    IntakeError,
    evaluate_legacy_file,
    stable_read,
)
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
    output = io.StringIO()
    with redirect_stdout(output):
        rc = cli.main(
            ["evaluate", "--root-id", "repository-jobs", "--path", "job.json"],
            root_overrides={"repository-jobs": tmp_path},
        )
    assert rc == 0
    assert json.loads(output.getvalue())["decision"]["outcome"] == "HOLD_FOR_REVIEW"
    assert "newsroom.runner" not in sys.modules
    assert "newsroom.gateway_client" not in sys.modules

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
