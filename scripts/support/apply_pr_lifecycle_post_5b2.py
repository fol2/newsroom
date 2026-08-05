from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"PR lifecycle correction anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    workflow = ".github/workflows/pr-lifecycle.yml"
    replace_once(
        workflow,
        "run: python scripts/sdlc/pr_lifecycle.py validate-event",
        "run: python -m scripts.sdlc.pr_lifecycle validate-event",
    )
    replace_once(
        workflow,
        "python scripts/sdlc/pr_lifecycle.py inventory --apply",
        "python -m scripts.sdlc.pr_lifecycle inventory --apply",
    )
    replace_once(
        workflow,
        "python scripts/sdlc/pr_lifecycle.py inventory\n",
        "python -m scripts.sdlc.pr_lifecycle inventory\n",
    )

    tests = "newsroom/tests/test_pr_lifecycle.py"
    replace_once(
        tests,
        "from datetime import datetime, timedelta, timezone\n\nimport pytest\n",
        "from datetime import datetime, timedelta, timezone\nimport json\nimport os\nfrom pathlib import Path\nimport subprocess\nimport sys\n\nimport pytest\n",
    )
    replace_once(
        tests,
        """def test_plan_never_closes_canonical_and_closes_checkpointed_support() -> None:\n""",
        """def test_workflow_module_entrypoint_runs_without_installed_package(\n    tmp_path: Path,\n) -> None:\n    repository_root = Path(__file__).resolve().parents[2]\n    event_path = tmp_path / \"pull-request-event.json\"\n    event_path.write_text(\n        json.dumps(\n            {\n                \"pull_request\": {\n                    \"number\": 10,\n                    \"draft\": False,\n                    \"body\": body(),\n                    \"head\": {\"ref\": \"agent/increment-5b2\"},\n                }\n            },\n            sort_keys=True,\n        ),\n        encoding=\"utf-8\",\n    )\n    environment = os.environ.copy()\n    environment.pop(\"PYTHONPATH\", None)\n    result = subprocess.run(\n        [\n            sys.executable,\n            \"-S\",\n            \"-m\",\n            \"scripts.sdlc.pr_lifecycle\",\n            \"validate-event\",\n            \"--event\",\n            str(event_path),\n        ],\n        cwd=repository_root,\n        env=environment,\n        check=False,\n        capture_output=True,\n        text=True,\n        timeout=10,\n    )\n\n    assert result.returncode == 0, result.stderr\n    assert \"validated PR lifecycle: canonical / increment-5b2\" in result.stdout\n    workflow_text = (\n        repository_root / \".github/workflows/pr-lifecycle.yml\"\n    ).read_text(encoding=\"utf-8\")\n    assert \"python -m scripts.sdlc.pr_lifecycle\" in workflow_text\n    assert \"python scripts/sdlc/pr_lifecycle.py\" not in workflow_text\n\n\ndef test_plan_never_closes_canonical_and_closes_checkpointed_support() -> None:\n""",
    )


if __name__ == "__main__":
    main()
