from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys

import pytest

import scripts.sdlc.command_spec as command_spec_module
from scripts.sdlc.command_spec import (
    CommandSpecError,
    build_environment,
    execute_command_spec,
    load_command_spec,
    main as command_main,
    parse_command_spec,
)
from scripts.sdlc.contracts import SdlcContract, load_contract


REPO_ROOT = Path(__file__).parents[2]
FIXED_DIGEST = "sha256:a06f3cb359bd3b59d89b388130577ca4b54c30139cc3ef8dc902ac8272456063"


def _contract(root: Path = REPO_ROOT) -> SdlcContract:
    source = load_contract(REPO_ROOT)
    if root == REPO_ROOT:
        return source
    return SdlcContract(root, source.source_path, source.data)


def _value(
    *,
    argv: list[str] | None = None,
    cwd: str = ".",
    static_env: dict[str, str] | None = None,
    pass_env: list[str] | None = None,
    redact_env: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "newsroom.sdlc.command-spec.v1",
        "gate_id": "route",
        "phase": "unit",
        "argv": argv or [sys.executable, "-c", "print('ok')"],
        "cwd": cwd,
        "static_env": static_env or {},
        "pass_env": pass_env or [],
        "redact_env": redact_env or [],
        "output_limit_bytes": 65_536,
        "termination_grace_ms": 500,
    }


def _write_spec(root: Path, name: str, value: dict[str, object]) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_command_spec_has_fixed_canonical_digest() -> None:
    value = _value(
        argv=["python", "-c", "print('ok')"],
        static_env={"PYTHONHASHSEED": "0"},
        pass_env=["PATH"],
    )

    spec = parse_command_spec(value, contract=_contract())

    assert spec.digest == FIXED_DIGEST
    assert spec.as_dict() == value


def test_order_is_normalized_but_each_execution_input_changes_digest(
    tmp_path: Path,
) -> None:
    (tmp_path / "sub").mkdir()
    contract = _contract(tmp_path)
    baseline_value = _value(
        static_env={"B": "2", "A": "1"},
        pass_env=["VISIBLE", "CUSTOM_VALUE"],
        redact_env=["CUSTOM_VALUE"],
    )
    baseline = parse_command_spec(baseline_value, contract=contract)
    reordered = deepcopy(baseline_value)
    reordered["static_env"] = {"A": "1", "B": "2"}
    reordered["pass_env"] = ["CUSTOM_VALUE", "VISIBLE"]
    assert parse_command_spec(reordered, contract=contract).digest == baseline.digest

    variants: list[dict[str, object]] = []
    for field, value in (
        ("argv", [sys.executable, "-c", "print('changed')"]),
        ("cwd", "sub"),
        ("static_env", {"A": "1", "B": "3"}),
        ("pass_env", ["VISIBLE", "CUSTOM_VALUE", "PATH"]),
        ("redact_env", []),
        ("output_limit_bytes", 4096),
        ("termination_grace_ms", 250),
    ):
        changed = deepcopy(baseline_value)
        changed[field] = value
        variants.append(changed)

    assert all(
        parse_command_spec(value, contract=contract).digest != baseline.digest
        for value in variants
    )


def test_same_spec_drives_execution_digest_and_minimal_redacted_environment(
    tmp_path: Path,
) -> None:
    source = (
        "import os; "
        "print('|'.join([os.environ.get('STATIC_VALUE','missing'),"
        "os.environ.get('VISIBLE','missing'),"
        "os.environ.get('CUSTOM_VALUE','missing'),"
        "os.environ.get('UNLISTED','missing')]))"
    )
    contract = _contract(tmp_path)
    spec = parse_command_spec(
        _value(
            argv=[sys.executable, "-c", source],
            static_env={"STATIC_VALUE": "fixed"},
            pass_env=["VISIBLE", "CUSTOM_VALUE"],
            redact_env=["CUSTOM_VALUE"],
        ),
        contract=contract,
    )

    command_run = execute_command_spec(
        contract=contract,
        spec=spec,
        ambient_env={
            "VISIBLE": "allowed",
            "CUSTOM_VALUE": "sensitive-value",
            "UNLISTED": "must-not-leak",
        },
    )

    assert command_run.command_spec_digest == spec.digest
    assert command_run.gate_run.result == "PASS"
    assert command_run.gate_run.stdout == "fixed|allowed|***|missing\n"
    assert "sensitive-value" not in command_run.gate_run.stdout
    assert "must-not-leak" not in command_run.gate_run.stdout


def test_secret_static_environment_and_unscoped_redaction_are_rejected(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    secret = _value(static_env={"API_TOKEN": "not-allowed"})
    with pytest.raises(CommandSpecError, match="static_secret_name"):
        parse_command_spec(secret, contract=contract)

    unscoped = _value(redact_env=["MISSING"])
    with pytest.raises(CommandSpecError, match="redact_env_scope"):
        parse_command_spec(unscoped, contract=contract)

    overlap = _value(static_env={"VALUE": "x"}, pass_env=["VALUE"])
    with pytest.raises(CommandSpecError, match="environment_overlap"):
        parse_command_spec(overlap, contract=contract)


def test_missing_environment_fails_without_echoing_name_or_value(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    spec = parse_command_spec(
        _value(pass_env=["PRIVATE_MISSING_VALUE"]),
        contract=contract,
    )

    with pytest.raises(CommandSpecError) as failure:
        build_environment(spec, {})

    assert str(failure.value) == "missing_environment"
    assert "PRIVATE_MISSING_VALUE" not in str(failure.value)


def test_shape_identifiers_and_numeric_limits_fail_closed(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    cases = []
    unknown = _value()
    unknown["extra"] = True
    cases.append((unknown, "shape"))
    bad_gate = _value()
    bad_gate["gate_id"] = "not-a-gate"
    cases.append((bad_gate, "gate_id"))
    bad_phase = _value()
    bad_phase["phase"] = "bad:phase"
    cases.append((bad_phase, "phase"))
    bad_output = _value()
    bad_output["output_limit_bytes"] = True
    cases.append((bad_output, "output_limit"))
    bad_grace = _value()
    bad_grace["termination_grace_ms"] = 5001
    cases.append((bad_grace, "termination_grace"))

    for value, code in cases:
        with pytest.raises(CommandSpecError, match=code):
            parse_command_spec(value, contract=contract)


@pytest.mark.skipif(os.name != "posix", reason="symlink evidence is POSIX-specific")
def test_cwd_and_spec_symlinks_or_path_escape_are_rejected(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CommandSpecError, match="cwd_symlink"):
        parse_command_spec(_value(cwd="linked"), contract=contract)
    with pytest.raises(CommandSpecError, match="cwd"):
        parse_command_spec(_value(cwd="../outside"), contract=contract)

    target = _write_spec(tmp_path, "real.json", _value())
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(CommandSpecError, match="spec_symlink"):
        load_command_spec(tmp_path, "link.json", contract=contract)


def test_cli_writes_private_atomic_result_and_never_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = _contract(tmp_path)
    monkeypatch.setattr(command_spec_module, "load_contract", lambda _root: contract)
    _write_spec(
        tmp_path,
        "command.json",
        _value(static_env={"PYTHONUTF8": "1"}),
    )

    assert command_main(
        (
            "--repo-root",
            str(tmp_path),
            "--spec",
            "command.json",
            "--output",
            "run.json",
        )
    ) == 0
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "newsroom.sdlc.command-run.v1"
    assert payload["gate_run"]["result"] == "PASS"
    assert payload["command_spec_digest"].startswith("sha256:")
    assert stat.S_IMODE((tmp_path / "run.json").stat().st_mode) == 0o600

    original = (tmp_path / "run.json").read_bytes()
    assert command_main(
        (
            "--repo-root",
            str(tmp_path),
            "--spec",
            "command.json",
            "--output",
            "run.json",
        )
    ) == 3
    assert (tmp_path / "run.json").read_bytes() == original
    assert capsys.readouterr().err.strip() == (
        "ENVIRONMENT_ERROR:command-spec:output_exists"
    )


def test_cli_preserves_gate_exit_semantics_and_hides_input_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = _contract(tmp_path)
    monkeypatch.setattr(command_spec_module, "load_contract", lambda _root: contract)
    _write_spec(
        tmp_path,
        "failure.json",
        _value(argv=[sys.executable, "-c", "raise SystemExit(7)"]),
    )

    assert command_main(
        ("--repo-root", str(tmp_path), "--spec", "failure.json")
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate_run"]["result"] == "FAIL"
    assert payload["gate_run"]["returncode"] == 7

    private_name = "PRIVATE_MISSING_VALUE_12345"
    _write_spec(
        tmp_path,
        "missing.json",
        _value(pass_env=[private_name]),
    )
    assert command_main(
        ("--repo-root", str(tmp_path), "--spec", "missing.json")
    ) == 3
    error = capsys.readouterr().err.strip()
    assert error == "ENVIRONMENT_ERROR:command-spec:missing_environment"
    assert private_name not in error
