from __future__ import annotations

import inspect

import pytest

import newsroom.increment5.approval as approval_module
import newsroom.increment5.github_attempts as github_attempts_module
import scripts.sdlc.increment5_github_admission as admission_module
from newsroom.authority.canonical import digest_bytes
from newsroom.increment5 import Increment5ContractError
from newsroom.tests import _increment5a_github_attempts_tests_v1 as _legacy


_REPLACED_TESTS = {
    "test_exact_authenticated_decision_artifact_is_accepted",
    "test_transport_authentication_runs_out_of_process",
    "test_synthetic_claim_cannot_authenticate_without_github_token",
}
for _name in dir(_legacy):
    if _name.startswith("test_") and _name not in _REPLACED_TESTS:
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


def test_transport_authentication_runs_out_of_process() -> None:
    parent_source = inspect.getsource(github_attempts_module)
    bootstrap_source = inspect.getsource(admission_module)
    implementation_source = inspect.getsource(admission_module._implementation)
    assert "GitHubActionsClient" not in parent_source
    assert '"-I"' in parent_source
    assert "captured_run_process" in parent_source
    assert "captured_approval_loader" in parent_source
    assert "--expected-source-manifest-digest" in parent_source
    assert "--expected-source-bundle-identity" in parent_source
    assert "validate_source_manifest(" in bootstrap_source
    assert "fetch_artifact_bundle(" in implementation_source
    assert "validate_authenticated_decision_artifact(" in implementation_source
    assert "newsroom-sdlc-decision-" in implementation_source
    assert "_EXPECTED_DECISION_ARTIFACT_FILES" in implementation_source
    assert "PYTHONPATH" not in parent_source
    assert "SSL_CERT_FILE" not in parent_source


def test_synthetic_claim_cannot_authenticate_without_owner_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(
        Increment5ContractError,
        match="requires owner approval",
    ):
        approval_module._AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION(
            _legacy._record()
        )
