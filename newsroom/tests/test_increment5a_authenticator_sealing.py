from __future__ import annotations

import inspect

import pytest

import newsroom.increment5.approval as approval_module
import newsroom.increment5.github_attempts as github_attempts_module
from newsroom.increment5 import Increment5ContractError


def test_repository_authenticator_is_owner_bound_sealed_closure() -> None:
    authenticator = (
        approval_module._AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION
    )
    assert authenticator.__name__ == (
        "authenticate_repository_main_qualification_record"
    )
    assert authenticator.__closure__
    with pytest.raises(
        Increment5ContractError,
        match="not bound to owner approval",
    ):
        github_attempts_module.authenticate_repository_main_qualification_record(
            object()  # type: ignore[arg-type]
        )


def test_source_pinned_main_loader_retains_exact_owner_bound_closure() -> None:
    authenticator = (
        approval_module._AUTHENTICATE_REPOSITORY_MAIN_QUALIFICATION
    )
    captured = tuple(
        cell.cell_contents
        for cell in approval_module._LOAD_MAIN_QUALIFICATION.__closure__ or ()
    )
    assert any(value is authenticator for value in captured)

    closure = inspect.getclosurevars(authenticator)
    assert closure.globals == {}
    module_source = inspect.getsource(github_attempts_module)
    assert "captured_approval_loader" in module_source
    assert "captured_verify_source_bundle" in module_source
    assert "--expected-source-bundle-identity" in module_source
