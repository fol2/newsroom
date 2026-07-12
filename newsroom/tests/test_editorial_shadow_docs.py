from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tomllib

from scripts import newsroom_editorial_shadow as cli


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "newsroom" / "evals" / "editorial_shadow"


def run_fixture(name: str) -> dict[str, object]:
    output = io.StringIO()
    with redirect_stdout(output):
        rc = cli.main(
            [
                "evaluate",
                "--root-id",
                "repository-fixtures",
                "--path",
                name,
            ],
            root_overrides={"repository-fixtures": FIXTURE_ROOT},
        )
    assert rc == 0, output.getvalue()
    return json.loads(output.getvalue())


def test_public_safe_fixtures_have_deterministic_outcomes() -> None:
    expected = {
        "eligible.json": "AUTO_PUBLISH",
        "hold.json": "HOLD_FOR_REVIEW",
        "reject.json": "REJECT",
        "prompt_injection_hold.json": "HOLD_FOR_REVIEW",
    }
    for name, outcome in expected.items():
        payload = run_fixture(name)
        assert payload["decision"]["outcome"] == outcome
        raw = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
        assert "http://" not in raw
        assert "https://" not in raw
        assert "@" not in raw

    injection = run_fixture("prompt_injection_hold.json")
    assert injection["publication_package_digest"] is None
    assert "ignore-policy" not in json.dumps(injection)


def test_checked_in_evaluate_example_executes_without_gateway_configuration() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/newsroom_editorial_shadow.py",
            "evaluate",
            "--root-id",
            "repository-fixtures",
            "--path",
            "eligible.json",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"]["outcome"] == "AUTO_PUBLISH"


def test_checked_in_eligible_fixture_records_once_after_explicit_resume(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"

    def run(arguments: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            rc = cli.main(
                arguments,
                root_overrides={"repository-fixtures": FIXTURE_ROOT},
                state_root_override=state_root,
            )
        return rc, json.loads(output.getvalue())

    resume_rc, resumed = run(
        ["resume", "--actor", "fixture-proof", "--reason", "explicit fixture proof"]
    )
    assert resume_rc == 0
    assert resumed["pause"]["paused"] is False  # type: ignore[index]

    record_args = [
        "record",
        "--root-id",
        "repository-fixtures",
        "--path",
        "eligible.json",
    ]
    first_rc, first = run(record_args)
    replay_rc, replay = run([*record_args, "--expected-fence", "1"])

    assert first_rc == replay_rc == 0
    assert first["decision"]["outcome"] == "AUTO_PUBLISH"  # type: ignore[index]
    assert first["delivery"]["status"] == "RECORDED_NOT_PUBLISHED"  # type: ignore[index]
    assert first["delivery"]["public_effect"] is False  # type: ignore[index]
    assert replay["delivery"]["reused"] is True  # type: ignore[index]
    assert replay["delivery"]["intent_id"] == first["delivery"]["intent_id"]  # type: ignore[index]


def test_docs_and_metadata_state_the_shadow_boundary_and_new_repository_identity() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (REPOSITORY_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    engine = (REPOSITORY_ROOT / "newsroom" / "README.md").read_text(encoding="utf-8")
    combined = "\n".join((readme, architecture, engine))
    for required in (
        "Hong Kongers in the UK",
        "shadow governance",
        "RECORDED_NOT_PUBLISHED",
        "not production conformance",
        "same OS account",
        "QA-051",
        "newsroom-editorial-shadow evaluate",
        "legacy Discord",
    ):
        assert required in combined
    for forbidden in (
        "fully conformant",
        "production compliant",
        "agent-proof pause",
        "publishes publicly from the shadow",
    ):
        assert forbidden not in combined.casefold()

    metadata = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["urls"]["Repository"] == "https://github.com/fol2/newsroom"
    assert metadata["project"]["urls"]["Issues"] == "https://github.com/fol2/newsroom/issues"
    assert "UK" in metadata["project"]["description"]


def test_fixture_scenarios_cover_the_declared_shadow_evaluation_matrix() -> None:
    scenarios: set[str] = set()
    for path in FIXTURE_ROOT.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["schema_version"] == "editorial_shadow_fixture_v1"
        scenarios.update(value["scenarios"])
    assert {
        "eligible",
        "hold",
        "reject",
        "tamper",
        "pause",
        "concurrency",
        "stable-story-identity",
        "prompt-injection-shaped-data",
    }.issubset(scenarios)
