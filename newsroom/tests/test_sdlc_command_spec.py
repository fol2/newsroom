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
    CommandSpec,
    CommandSpecError,
    build_environment,
    execute_command_spec,
    executable_digest,
    load_command_spec,
    main as command_main,
    parse_command_spec,
)
from scripts.sdlc.contracts import SdlcContract, load_contract


REPO_ROOT = Path(__file__).parents[2]
FIXED_DIGEST = "sha256:4a0780dacdf4bc9f4864efd7f5ff10b123131788af556c5bd4b254f1b63e6108"


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
    executable_sha: str | None = None,
) -> dict[str, object]:
    selected_argv = argv or [sys.executable, "-c", "print('ok')"]
    _, actual_digest = executable_digest(selected_argv[0])
    return {
        "schema_version": "newsroom.sdlc.command-spec.v1",
        "gate_id": "route",
        "phase": "unit",
        "argv": selected_argv,
        "cwd": cwd,
        "static_env": static_env or {},
        "pass_env": pass_env or [],
        "redact_env": redact_env or [],
        "executable_digest": executable_sha or actual_digest,
        "output_limit_bytes": 65_536,
        "termination_grace_ms": 500,
    }


def _write_spec(root: Path, name: str, value: dict[str, object]) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_command_spec_has_fixed_canonical_digest() -> None:
    spec = CommandSpec(
        gate_id="route",
        phase="unit",
        argv=("/usr/bin/python", "-c", "print('ok')"),
        cwd=".",
        static_env=(("PYTHONHASHSEED", "0"),),
        pass_env=(),
        redact_env=(),
        executable_digest="sha256:" + "1" * 64,
        output_limit_bytes=65_536,
        termination_grace_ms=500,
    )

    assert spec.digest == FIXED_DIGEST
    assert spec.as_dict()["executable_digest"] == "sha256:" + "1" * 64


def test_order_is_normalized_but_each_execution_input_changes_digest(
    tmp_path: Path,
) -> None:
    (tmp_path / "sub").mkdir()
    contract = _contract(tmp_path)
    baseline_value = _value(
        static_env={"B": "2", "A": "1"},
        pass_env=["SECRET_TWO", "SECRET_ONE"],
        redact_env=["SECRET_ONE", "SECRET_TWO"],
    )
    baseline = parse_command_spec(baseline_value, contract=contract)
    reordered = deepcopy(baseline_value)
    reordered["static_env"] = {"A": "1", "B": "2"}
    reordered["pass_env"] = ["SECRET_ONE", "SECRET_TWO"]
    reordered["redact_env"] = ["SECRET_TWO", "SECRET_ONE"]
    assert parse_command_spec(reordered, contract=contract).digest == baseline.digest

    variants: list[dict[str, object]] = []
    for field, value in (
        ("argv", [sys.executable, "-c", "print('changed')"]),
        ("cwd", "sub"),
        ("static_env", {"A": "1", "B": "3"}),
        ("output_limit_bytes", 4096),
        ("termination_grace_ms", 250),
    ):
        changed = deepcopy(baseline_value)
        changed[field] = value
        variants.append(changed)
    changed_environment = deepcopy(baseline_value)
    changed_environment["pass_env"] = ["SECRET_ONE", "SECRET_TWO", "SECRET_THREE"]
    changed_environment["redact_env"] = ["SECRET_ONE", "SECRET_TWO", "SECRET_THREE"]
    variants.append(changed_environment)

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
            static_env={"STATIC_VALUE": "fixed", "VISIBLE": "allowed"},
            pass_env=["CUSTOM_VALUE"],
            redact_env=["CUSTOM_VALUE"],
        ),
        contract=contract,
    )

    command_run = execute_command_spec(
        contract=contract,
        spec=spec,
        ambient_env={
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
    with pytest.raises(CommandSpecError, match="unbound_environment"):
        parse_command_spec(unscoped, contract=contract)

    overlap = _value(
        static_env={"VALUE": "x"},
        pass_env=["VALUE"],
        redact_env=["VALUE"],
    )
    with pytest.raises(CommandSpecError, match="environment_overlap"):
        parse_command_spec(overlap, contract=contract)


def test_missing_environment_fails_without_echoing_name_or_value(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    spec = parse_command_spec(
        _value(
            pass_env=["PRIVATE_MISSING_VALUE"],
            redact_env=["PRIVATE_MISSING_VALUE"],
        ),
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
    bad_executable = _value(executable_sha="sha256:" + "0" * 64)
    cases.append((bad_executable, "executable_digest"))
    relative_executable = _value()
    relative_executable["argv"] = ["python", "-c", "pass"]
    cases.append((relative_executable, "executable_path"))

    for value, code in cases:
        with pytest.raises(CommandSpecError, match=code):
            parse_command_spec(value, contract=contract)


def test_direct_dataclass_cannot_bypass_parser_invariants(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    parsed = parse_command_spec(_value(), contract=contract)
    bypass = CommandSpec(
        gate_id=parsed.gate_id,
        phase=parsed.phase,
        argv=parsed.argv,
        cwd=parsed.cwd,
        static_env=parsed.static_env,
        pass_env=("UNBOUND_VALUE",),
        redact_env=(),
        executable_digest=parsed.executable_digest,
        output_limit_bytes=parsed.output_limit_bytes,
        termination_grace_ms=parsed.termination_grace_ms,
    )

    with pytest.raises(CommandSpecError, match="unbound_environment"):
        execute_command_spec(
            contract=contract,
            spec=bypass,
            ambient_env={"UNBOUND_VALUE": "secret"},
        )


def test_executable_is_resolved_and_content_bound(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    resolved, digest = executable_digest(sys.executable)
    spec = parse_command_spec(_value(), contract=contract)

    assert spec.argv[0] == resolved
    assert spec.executable_digest == digest


def test_all_ambient_values_are_redacted_and_bounded(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    unbound = _value(pass_env=["VALUE"], redact_env=[])
    with pytest.raises(CommandSpecError, match="unbound_environment"):
        parse_command_spec(unbound, contract=contract)

    spec = parse_command_spec(
        _value(pass_env=["VALUE"], redact_env=["VALUE"]),
        contract=contract,
    )
    with pytest.raises(CommandSpecError, match="environment_value"):
        build_environment(spec, {"VALUE": "x" * 65_537})
    with pytest.raises(CommandSpecError, match="environment_value"):
        build_environment(spec, {"VALUE": "bad\x00value"})


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    _, digest = executable_digest(sys.executable)
    payload = (
        '{"schema_version":"newsroom.sdlc.command-spec.v1",'
        '"gate_id":"route","gate_id":"route","phase":"unit",'
        f'"argv":[{json.dumps(sys.executable)},"-c","pass"],'
        '"cwd":".","static_env":{},"pass_env":[],"redact_env":[],'
        f'"executable_digest":"{digest}",'
        '"output_limit_bytes":65536,"termination_grace_ms":500}'
    )
    (tmp_path / "duplicate.json").write_text(payload, encoding="utf-8")

    with pytest.raises(CommandSpecError, match="spec_duplicate_key"):
        load_command_spec(tmp_path, "duplicate.json", contract=contract)


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
        _value(pass_env=[private_name], redact_env=[private_name]),
    )
    assert command_main(
        ("--repo-root", str(tmp_path), "--spec", "missing.json")
    ) == 3
    error = capsys.readouterr().err.strip()
    assert error == "ENVIRONMENT_ERROR:command-spec:missing_environment"
    assert private_name not in error
