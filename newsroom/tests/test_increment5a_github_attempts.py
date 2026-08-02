from __future__ import annotations

import scripts.sdlc.increment5_github_admission as admission_module
from newsroom.authority.canonical import digest_bytes
from newsroom.tests import _increment5a_github_attempts_tests_v1 as _legacy


for _name in dir(_legacy):
    if _name.startswith("test_") and _name != (
        "test_exact_authenticated_decision_artifact_is_accepted"
    ):
        globals()[_name] = getattr(_legacy, _name)


def test_exact_authenticated_decision_artifact_is_accepted(
    tmp_path,
    monkeypatch,
) -> None:
    def accept_test_collection(*, collection, decision, contract):
        del decision, contract
        return dict(collection)

    monkeypatch.setattr(
        admission_module._implementation,
        "validate_collection_decision_binding",
        accept_test_collection,
    )
    root, value, record = _legacy._decision_artifact(tmp_path)
    digests = admission_module.validate_authenticated_decision_artifact(
        extracted_root=root,
        record_value=value,
        record=record,
    )
    assert set(digests) == {
        "decision_file_digest",
        "context_file_digest",
        "collection_file_digest",
    }
    assert digests["decision_file_digest"] == digest_bytes(
        (root / "decision.json").read_bytes()
    )
