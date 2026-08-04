#!/usr/bin/env python3
"""Finalize generated stdlib validator diagnostics, tests, and prose.

Disposable support helper; never merge into PR #255 or main.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
EVALUATION = ROOT / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = VALIDATOR.read_text(encoding="utf-8")
    marker = "\n\nclass _TrustedGitBinary:\n"
    parser = '''

def _parse_input_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileInputError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ProfileInputError("profile manifest must be an object")
    if raw != _canonical_json_bytes(value):
        raise ProfileInputError("input is not canonical JSON")
    return value
'''
    if "def _parse_input_manifest(raw: bytes)" not in text:
        text = replace_once(text, marker, parser + marker, "input parser insertion")
    old_main = (
        '        manifest = _parse_canonical_object(raw, "profile manifest")\n'
        '        if raw != _canonical_json_bytes(manifest):\n'
        '            raise ProfileInputError("input is not canonical JSON")\n'
    )
    if old_main in text:
        text = text.replace(old_main, '        manifest = _parse_input_manifest(raw)\n', 1)
    elif '        manifest = _parse_input_manifest(raw)\n' not in text:
        raise RuntimeError("main input parser is absent")
    VALIDATOR.write_text(text, encoding="utf-8")

    tests = TESTS.read_text(encoding="utf-8")
    old_assertion = '            assert b"qualification_eligible" in completed.stderr\n'
    new_assertion = (
        '            assert b"profile qualification eligibility differs" '
        'in completed.stderr\n'
    )
    if old_assertion in tests:
        tests = tests.replace(old_assertion, new_assertion, 1)
    elif new_assertion not in tests:
        raise RuntimeError("eligibility diagnostic assertion is absent")
    definition = (
        '_CONTRACT_RELATIVE_PATH = "newsroom/increment5/data/'
        'increment5a_retrieval_contract_v1.json"\n'
    )
    if definition not in tests:
        tests = replace_once(
            tests,
            "_VALIDATOR_SCRIPT = _REPOSITORY_ROOT / _VALIDATOR_RELATIVE_PATH\n",
            "_VALIDATOR_SCRIPT = _REPOSITORY_ROOT / _VALIDATOR_RELATIVE_PATH\n"
            + definition,
            "contract path constant",
        )
    TESTS.write_text(tests, encoding="utf-8")

    evaluation = EVALUATION.read_text(encoding="utf-8")
    duplicate = "Superseded Epoch Runs remain retained.Superseded Epoch Runs remain retained."
    if duplicate in evaluation:
        evaluation = evaluation.replace(
            duplicate,
            "Superseded Epoch Runs remain retained.",
            1,
        )
    EVALUATION.write_text(evaluation, encoding="utf-8")


if __name__ == "__main__":
    main()
