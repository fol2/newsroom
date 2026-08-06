#!/usr/bin/env python3
"""Apply the exact stale-checkpoint planning correction for PR lifecycle v1."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected exactly one replacement in {path}, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def update_contract() -> None:
    path = ROOT / "newsroom/checks/pr_lifecycle.py"
    replace_once(
        path,
        "    existing_checkpoint_refs: frozenset[str] = frozenset(),\n",
        "    checkpoint_head_shas: Mapping[str, str] | None = None,\n",
    )
    replace_once(
        path,
        """    if not isinstance(existing_checkpoint_refs, frozenset):
        raise PrLifecycleError("checkpoint ref inventory must be immutable")
    for ref in existing_checkpoint_refs:
        _validate_ref(ref, field="checkpoint ref")
""",
        """    if checkpoint_head_shas is None:
        checkpoint_shas: dict[str, str] = {}
    elif not isinstance(checkpoint_head_shas, Mapping):
        raise PrLifecycleError("checkpoint head inventory must be a mapping")
    else:
        checkpoint_shas = {}
        for ref, sha in checkpoint_head_shas.items():
            _validate_ref(ref, field="checkpoint ref")
            if (
                not isinstance(sha, str)
                or _COMMIT_SHA.fullmatch(sha) is None
            ):
                raise PrLifecycleError(
                    "checkpoint head SHA must be lowercase full commit text"
                )
            checkpoint_shas[ref] = sha
""",
    )
    replace_once(
        path,
        """        if lifecycle.close_when is CloseWhen.CHECKPOINTED:
            if (
                lifecycle.checkpoint_ref is not None
                and lifecycle.checkpoint_ref in existing_checkpoint_refs
            ):
                close_reason = (
                    "declared checkpoint exists: "
                    f"{lifecycle.checkpoint_ref}"
                )
""",
        """        if lifecycle.close_when is CloseWhen.CHECKPOINTED:
            assert lifecycle.checkpoint_ref is not None
            checkpoint_sha = checkpoint_shas.get(
                lifecycle.checkpoint_ref
            )
            if checkpoint_sha is not None:
                if pr.head_sha is None:
                    warnings.append(
                        f"#{pr.number} current head SHA is unavailable for "
                        "checkpoint verification: "
                        f"{lifecycle.checkpoint_ref}"
                    )
                elif checkpoint_sha != pr.head_sha:
                    warnings.append(
                        f"#{pr.number} declared checkpoint is stale: "
                        f"{lifecycle.checkpoint_ref}"
                    )
                else:
                    close_reason = (
                        "declared checkpoint matches current head: "
                        f"{lifecycle.checkpoint_ref}"
                    )
""",
    )


def update_cli() -> None:
    path = ROOT / "scripts/sdlc/pr_lifecycle.py"
    replace_once(
        path,
        """    existing_checkpoints = frozenset(
        ref
        for ref in sorted(checkpoint_refs)
        if client.branch_exists(ref)
    )
""",
        """    checkpoint_head_shas = {
        ref: sha
        for ref in sorted(checkpoint_refs)
        if (sha := client.branch_sha(ref)) is not None
    }
""",
    )
    replace_once(
        path,
        "        existing_checkpoint_refs=existing_checkpoints,\n",
        "        checkpoint_head_shas=checkpoint_head_shas,\n",
    )


def update_tests() -> None:
    path = ROOT / "newsroom/tests/test_pr_lifecycle.py"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"existing_checkpoint_refs=frozenset\(\n"
        r"\s+\{\"checkpoint/increment-5b2\"\}\n"
        r"\s+\),"
    )
    text, count = pattern.subn(
        'checkpoint_head_shas={"checkpoint/increment-5b2": "a" * 40},',
        text,
    )
    if count != 3:
        raise RuntimeError(
            "expected exactly three checkpoint test-call replacements, "
            f"found {count}"
        )
    marker = "\n\ndef test_automatic_branch_deletion_metadata_is_rejected() -> None:\n"
    if text.count(marker) != 1:
        raise RuntimeError("cannot locate lifecycle test insertion marker")
    regression = '''

def test_plan_excludes_stale_checkpoint_without_blocking_later_closure() -> None:
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=False,
        head_ref="agent/increment-5b2",
        head_sha="d" * 40,
    )
    stale = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            checkpoint="checkpoint/stale-support",
            close_when="checkpointed",
        ),
        draft=True,
        head_ref="support/stale-checkpoint",
        head_sha="a" * 40,
    )
    current = open_pr(
        12,
        pr_body=body(
            lifecycle="preflight",
            canonical="#10",
            checkpoint="checkpoint/current-preflight",
            close_when="checkpointed",
        ),
        draft=True,
        head_ref="preflight/current-checkpoint",
        head_sha="c" * 40,
    )

    plan = plan_housekeeping(
        (canonical, stale, current),
        checkpoint_head_shas={
            "checkpoint/stale-support": "b" * 40,
            "checkpoint/current-preflight": "c" * 40,
        },
        now=NOW,
    )

    assert [action.pr_number for action in plan.close_actions] == [12]
    assert plan.warnings == (
        "#11 declared checkpoint is stale: checkpoint/stale-support",
    )


def test_plan_rejects_malformed_checkpoint_head_sha() -> None:
    with pytest.raises(PrLifecycleError, match="checkpoint head SHA"):
        plan_housekeeping(
            (),
            checkpoint_head_shas={"checkpoint/example": "ABC"},
            now=NOW,
        )
'''
    path.write_text(text.replace(marker, regression + marker), encoding="utf-8")


def update_docs() -> None:
    path = ROOT / "docs/operations/pr-lifecycle.md"
    replace_once(
        path,
        """inventory. The dry-run job has read-only permissions. A separate apply job has
only the issue and pull-request write permissions needed to comment and close an
eligible disposable PR; repository contents remain read-only.
""",
        """inventory. Inventory resolves every declared checkpoint to its full commit SHA;
the planner emits a checkpointed close action only when that SHA equals the
inventoried PR head. A stale checkpoint is reported as a warning and cannot block
later eligible actions. The dry-run job has read-only permissions. A separate
apply job has only the issue and pull-request write permissions needed to comment
and close an eligible disposable PR; repository contents remain read-only.
""",
    )


def main() -> int:
    update_contract()
    update_cli()
    update_tests()
    update_docs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
