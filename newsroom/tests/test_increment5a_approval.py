from __future__ import annotations

from newsroom.tests import _increment5a_approval_tests_v1 as _legacy


_REPLACED_TESTS = {"test_owner_statement_and_non_effects_are_exact"}
for _name in dir(_legacy):
    if _name.startswith("test_") and _name not in _REPLACED_TESTS:
        globals()[_name] = getattr(_legacy, _name)


def test_owner_statement_and_non_effects_are_exact() -> None:
    assert _legacy._OWNER_BODY_DIGEST == (
        "sha256:8e00ded4cec0a95a59b3507b5fb28eba8033f96c2dccb531d4075bdcbe976f87"
    )
    assert (
        _legacy.approval_module.ADMISSION_SOURCE_MANIFEST_DIGEST
        in _legacy._OWNER_BODY
    )
    assert (
        _legacy.approval_module.ADMISSION_SOURCE_BUNDLE_IDENTITY
        in _legacy._OWNER_BODY
    )
    assert tuple(_legacy.APPROVAL_NON_EFFECTS) == (
        "CANARY",
        "DOWNSTREAM_IMPLEMENTATION",
        "EXTERNAL_EMBEDDING_API_CALLS",
        "LIVE_SOURCE_EXECUTION",
        "PROTECTED_CONTENT_VECTORS",
        "PROVIDER_SPENDING",
        "PUBLICATION",
        "PUBLIC_EFFECT",
        "PRODUCTION_ACTIVATION",
        "SHADOW",
    )
