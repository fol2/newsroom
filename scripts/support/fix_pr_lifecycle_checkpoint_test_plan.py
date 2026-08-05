from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[2] / "newsroom/tests/test_pr_lifecycle.py"
text = path.read_text(encoding="utf-8")
old = '''        module._apply_plan(
            client,
            plan,
            lifecycles={},
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_workflow_separates_dry_run_and_two_key_apply() -> None:
'''
new = '''        module._apply_plan(
            client,
            plan,
            lifecycles={
                11: module.parse_pr_lifecycle(
                    body(
                        lifecycle="support",
                        canonical="#10",
                        close_when="canonical-merged",
                        retention="delete-after-checkpoint",
                    )
                )
            },
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_workflow_separates_dry_run_and_two_key_apply() -> None:
'''
if text.count(old) != 1:
    raise SystemExit("checkpoint regression planned-lifecycle anchor differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
