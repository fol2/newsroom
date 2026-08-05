from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST_PATH = ROOT / "newsroom/tests/test_pr_lifecycle.py"
TARGETS = (
    "test_apply_revalidates_current_disposable_surface",
    "test_checkpointed_keep_closure_requires_current_head_checkpoint",
    "test_apply_rejects_retention_change_after_planning",
    "test_apply_revalidates_current_merged_canonical_binding",
    "test_apply_rejects_checkpoint_not_bound_to_current_head",
)


def _patch_function(text: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"missing fixture function: {function_name}")
    end = text.find("\ndef ", start + len(marker))
    if end < 0:
        end = len(text)

    section = text[start:end]
    lines = section.splitlines(keepends=True)

    number_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == '"number": 11,'
        ),
        None,
    )
    if number_index is None:
        raise SystemExit(f"missing current PR fixture in {function_name}")

    number_indent = lines[number_index][
        : len(lines[number_index]) - len(lines[number_index].lstrip())
    ]
    state_line = f'{number_indent}"state": "open",\n'
    if state_line in lines:
        raise SystemExit(f"state fixture already present in {function_name}")
    lines.insert(number_index + 1, state_line)

    created_index = next(
        (
            index
            for index, line in enumerate(lines[number_index + 2 :], number_index + 2)
            if line.strip() == '"created_at": "2026-08-05T12:00:00Z",'
        ),
        None,
    )
    if created_index is None:
        raise SystemExit(f"missing created_at fixture in {function_name}")

    created_indent = lines[created_index][
        : len(lines[created_index]) - len(lines[created_index].lstrip())
    ]
    merged_line = f'{created_indent}"merged_at": None,\n'
    if merged_line in lines:
        raise SystemExit(f"merged fixture already present in {function_name}")
    lines.insert(created_index + 1, merged_line)

    return text[:start] + "".join(lines) + text[end:]


def main() -> None:
    text = TEST_PATH.read_text(encoding="utf-8")
    for function_name in TARGETS:
        text = _patch_function(text, function_name)
    TEST_PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
