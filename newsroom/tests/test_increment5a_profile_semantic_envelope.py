from __future__ import annotations

from copy import deepcopy
import inspect
from typing import Any, Callable

import pytest
from jsonschema import Draft202012Validator

from newsroom.increment5 import (
    Increment5ProfileError,
    build_fixture_replay_manifest,
    build_qualification_manifest,
    validate_profile_manifest,
)


_DIGEST_A = "sha256:" + "a" * 64


def _reachable_closure_values(function: Callable[..., object]) -> tuple[object, ...]:
    """Return values reachable through nested Python function closures."""

    values: list[object] = []
    stack: list[object] = [function]
    seen: set[int] = set()
    while stack:
        value = stack.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        if inspect.isfunction(value):
            for cell in value.__closure__ or ():
                try:
                    captured = cell.cell_contents
                except ValueError:
                    continue
                values.append(captured)
                if inspect.isfunction(captured):
                    stack.append(captured)
    return tuple(values)


def _fixture_manifest() -> dict[str, Any]:
    return build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )


def _qualification_manifest() -> dict[str, Any]:
    return build_qualification_manifest(
        dataset_id="increment5-rights-cleared-v1",
        dataset_manifest_digest=_DIGEST_A,
    )


def test_public_profile_closures_retain_no_mutable_validator_instance() -> None:
    reachable = _reachable_closure_values(validate_profile_manifest)

    assert not any(
        isinstance(value, Draft202012Validator)
        for value in reachable
    )
    assert any(
        isinstance(value, bytes) and b"qualification_eligible" in value
        for value in reachable
    )


@pytest.mark.parametrize(
    ("builder", "mutate", "message"),
    (
        (
            _fixture_manifest,
            lambda manifest: manifest.__setitem__(
                "qualification_eligible",
                True,
            ),
            "profile qualification eligibility differs",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest.__setitem__(
                "qualification_eligible",
                False,
            ),
            "profile qualification eligibility differs",
        ),
        (
            _fixture_manifest,
            lambda manifest: manifest["fixture"].__setitem__(
                "production_substitution_allowed",
                True,
            ),
            "fixture replay cannot substitute",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest.__setitem__(
                "actual_neo4j_required",
                False,
            ),
            "qualification requires an actual Neo4j service",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest["dataset"].__setitem__(
                "rights_cleared",
                False,
            ),
            "qualification dataset must be rights cleared",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest["runtime_effects"].__setitem__(
                "external_calls",
                1,
            ),
            "profile runtime effects differs",
        ),
        (
            _fixture_manifest,
            lambda manifest: manifest.__setitem__(
                "implicit_authority",
                True,
            ),
            "profile fields differ",
        ),
    ),
)
def test_immutable_semantic_envelope_survives_validator_bypass(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[], dict[str, Any]],
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    manifest = deepcopy(builder())
    mutate(manifest)

    # Simulate a fully bypassed or caller-modified JSON-Schema validator. The
    # authority-bearing semantic envelope must still reject the document.
    monkeypatch.setattr(
        Draft202012Validator,
        "iter_errors",
        lambda self, instance: iter(()),
    )

    with pytest.raises(Increment5ProfileError, match=message):
        validate_profile_manifest(manifest)
