from __future__ import annotations

import ctypes
from copy import deepcopy
import inspect
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

import pytest
from jsonschema import Draft202012Validator

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    Increment5ProfileError,
    build_fixture_replay_manifest,
    build_qualification_manifest,
)
from newsroom.increment5 import profiles


_DIGEST_A = "sha256:" + "a" * 64
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR_SCRIPT = (
    _REPOSITORY_ROOT / "scripts" / "sdlc" / "increment5_profile_validator.py"
)


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


def _run_isolated(manifest: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", str(_VALIDATOR_SCRIPT)],
        input=canonical_json_bytes(manifest),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env={"PYTHONUTF8": "1"},
    )


def _closure_cell(
    function: Callable[..., object],
    captured_name: str,
) -> tuple[object, object]:
    for cell in function.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if inspect.isfunction(value) and value.__name__ == captured_name:
            return cell, value
    raise AssertionError(f"closure does not capture {captured_name}")


def _set_cell(cell: object, value: object) -> None:
    py_cell_set = ctypes.pythonapi.PyCell_Set
    py_cell_set.argtypes = (ctypes.py_object, ctypes.py_object)
    py_cell_set.restype = ctypes.c_int
    assert py_cell_set(cell, value) == 0


@pytest.mark.parametrize(
    "builder",
    (_fixture_manifest, _qualification_manifest),
)
def test_fresh_process_returns_non_authoritative_canonical_receipt(
    builder: Callable[[], dict[str, Any]],
) -> None:
    manifest = builder()
    completed = _run_isolated(manifest)

    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    raw_receipt = completed.stdout.rstrip(b"\n")
    receipt = json.loads(raw_receipt.decode("utf-8"))
    assert raw_receipt == canonical_json_bytes(receipt)
    assert receipt == {
        "authority_effect": "NONE",
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
        "production_activation_authorized": False,
        "profile_kind": manifest["profile_kind"],
        "qualification_authority_granted": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v1",
        "validation_scope": "REVIEWED_PROFILE_STRUCTURE_AND_SEMANTICS",
    }


@pytest.mark.parametrize(
    ("builder", "mutate", "message"),
    (
        (
            _fixture_manifest,
            lambda manifest: manifest.__setitem__("qualification_eligible", True),
            "profile qualification eligibility differs",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest.__setitem__("qualification_eligible", False),
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
            lambda manifest: manifest.__setitem__("implicit_authority", True),
            "profile fields differ",
        ),
    ),
)
def test_private_semantic_check_survives_json_schema_validator_bypass(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[], dict[str, Any]],
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    manifest = deepcopy(builder())
    mutate(manifest)

    monkeypatch.setattr(
        Draft202012Validator,
        "iter_errors",
        lambda self, instance: iter(()),
    )

    with pytest.raises(Increment5ProfileError, match=message):
        profiles._check_profile_manifest(manifest)


def test_same_process_closure_mutation_cannot_create_qualification_authority() -> None:
    manifest = _fixture_manifest()
    manifest["qualification_eligible"] = True

    cell, original = _closure_cell(
        profiles._check_profile_manifest,
        "check_snapshot",
    )

    def bypass(snapshot: object, *, profile: object) -> None:
        return None

    try:
        _set_cell(cell, bypass)

        # Arbitrary code in the same Python process can bypass any Python
        # helper. The private helper therefore returns no certificate, boolean,
        # or authority-bearing value even under this exact attack.
        assert profiles._check_profile_manifest(manifest) is None

        # The fresh -I process reloads exact source and rejects the same bytes;
        # the caller's mutated cell cannot cross the process boundary.
        completed = _run_isolated(manifest)
        assert completed.returncode == 2
        assert b"profile qualification eligibility differs" in completed.stderr
        assert completed.stdout == b""
    finally:
        _set_cell(cell, original)


def test_isolated_validator_rejects_noncanonical_and_duplicate_json() -> None:
    valid = _fixture_manifest()
    pretty = json.dumps(valid, indent=2, sort_keys=True).encode("utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", str(_VALIDATOR_SCRIPT)],
        input=pretty,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env={"PYTHONUTF8": "1"},
    )
    assert completed.returncode == 2
    assert b"input is not canonical JSON" in completed.stderr

    duplicate = b'{"profile_kind":"FIXTURE_REPLAY","profile_kind":"FIXTURE_REPLAY"}'
    completed = subprocess.run(
        [sys.executable, "-I", str(_VALIDATOR_SCRIPT)],
        input=duplicate,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env={"PYTHONUTF8": "1"},
    )
    assert completed.returncode == 2
    assert b"duplicate JSON object name" in completed.stderr
