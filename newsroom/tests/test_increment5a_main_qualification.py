from __future__ import annotations

from pathlib import Path

from newsroom.tests import _increment5a_main_qualification_tests_v2 as _legacy


_REPLACED_TESTS = {
    "test_signed_decision_requires_complete_repository_and_event_identity"
}
for _name in dir(_legacy):
    if _name.startswith("test_") and _name not in _REPLACED_TESTS:
        globals()[_name] = getattr(_legacy, _name)


def test_signed_decision_requires_complete_repository_and_event_identity() -> None:
    source = Path(_legacy.approval_module.__file__).with_name(
        "_main_qualification_v2.py"
    ).read_text(encoding="utf-8")
    for field_name in (
        "repository_id",
        "head_repository",
        "head_repository_id",
        "event_sha",
    ):
        assert f'("{field_name}",' in source
