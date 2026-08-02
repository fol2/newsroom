from __future__ import annotations

import inspect

import newsroom.increment5.approval as approval_module
import newsroom.increment5.github_attempts as github_attempts_module


def test_repository_authenticator_has_no_mutable_delegate_global() -> None:
    authenticator = (
        github_attempts_module.authenticate_repository_main_qualification_record
    )

    assert authenticator.__name__ == (
        "authenticate_repository_main_qualification_record"
    )
    assert authenticator.__closure__
    assert not hasattr(
        github_attempts_module,
        "_AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION",
    )

    module_source = inspect.getsource(github_attempts_module)
    assert "return _AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION" not in module_source
    assert "captured_validate_certificate" in module_source
    assert "captured_canonical_bytes" in module_source
    assert "captured_run_process" in module_source

    closure = inspect.getclosurevars(authenticator)
    assert closure.globals == {}


def test_source_pinned_main_loader_retains_the_sealed_closure() -> None:
    authenticator = (
        github_attempts_module.authenticate_repository_main_qualification_record
    )
    captured = tuple(
        cell.cell_contents
        for cell in approval_module._LOAD_MAIN_QUALIFICATION.__closure__ or ()
    )

    assert any(value is authenticator for value in captured)
