from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.increment9.no_active_human_emergency_stop import (
    GATE_ID,
    PACKAGE_FIXTURES,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    QualificationError,
    assess,
    default_probe,
    evidence_json,
)

_SPEC = spec_from_file_location(
    "increment9q3_no_active_human_emergency_stop",
    Path(__file__).resolve().parents[2] / "scripts" / "increment9q3_no_active_human_emergency_stop.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CLI = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(f"refusal:{rc}\n".encode())
    return root


def test_assess_fails_closed_without_inventory(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="inventory"):
        assess(tmp_path / "missing")


def test_assess_fails_closed_when_a_refusal_class_is_missing(tmp_path: Path) -> None:
    root = _inventory(tmp_path)
    (root / REFUSAL_CLASSES[0]).unlink()
    with pytest.raises(QualificationError, match="refusal"):
        assess(root)


def test_assess_fails_closed_when_an_extra_refusal_class_is_present(
    tmp_path: Path,
) -> None:
    root = _inventory(tmp_path)
    (root / "EXTRA").write_bytes(b"extra")
    with pytest.raises(QualificationError, match="refusal"):
        assess(root)


def test_news_pool_paths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="news_pool"):
        assess(tmp_path / "news_pool.sqlite3")


def test_assess_emits_qualification_evidence_not_a_gate_record(tmp_path: Path) -> None:
    # Create proper fixtures that will pass the probes
    root = tmp_path / "fixtures"
    root.mkdir()
    for rc in REFUSAL_CLASSES:
        if rc == "ASSERTION_MISSING":
            (root / rc).write_bytes(b"assertion_missing")
        elif rc == "ASSERTION_MALFORMED":
            (root / rc).write_bytes(b"assertion_malformed")
        elif rc == "HMAC_VERIFICATION_FAILED":
            (root / rc).write_bytes(b"hmac_verification_failed")
        elif rc == "RUN_ID_MISMATCH":
            (root / rc).write_bytes(b"run_id_mismatch")
        elif rc == "ASSERTION_NOT_YET_ISSUED":
            (root / rc).write_bytes(b"assertion_not_yet_issued")
        elif rc == "ASSERTION_EXPIRED":
            (root / rc).write_bytes(b"assertion_expired")
        elif rc == "NO_STOP_ASSERTION_SIGNATURE_INVALID":
            (root / rc).write_bytes(b"signature_invalid")
        elif rc == "STOP_SUPERSEDES_ASSERTION":
            (root / rc).write_bytes(b"stop_supersedes_assertion")
        elif rc == "ASSERTION_BINDING_ABSENT":
            (root / rc).write_bytes(b"assertion_binding_absent")

    evidence = assess(root)
    assert evidence.gate_id == GATE_ID
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES)
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"refusals_engaged":9' in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload


def test_assess_fails_closed_when_a_probe_mutates(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def mutate(rc: str, path: Path, assertion, now) -> bool:
        path.write_bytes(path.read_bytes() + b"mutated")
        return True

    with pytest.raises(QualificationError, match="mutated"):
        assess(root, probe=mutate)


def test_assess_fails_closed_when_digest_changes_without_engagement(
    tmp_path: Path,
) -> None:
    root = _inventory(tmp_path)

    def silent_mutate(rc: str, path: Path, assertion, now) -> bool:
        if rc == "ASSERTION_MISSING":
            path.write_bytes(b"changed")
        return False

    with pytest.raises(QualificationError, match="mutated"):
        assess(root, probe=silent_mutate)


def test_assess_fails_closed_when_not_all_refusals_engage(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def partial_engage(rc: str, path: Path, assertion, now) -> bool:
        # Only engage first few refusal classes
        return rc in REFUSAL_CLASSES[:3]

    with pytest.raises(QualificationError, match="not all refusals"):
        assess(root, probe=partial_engage)


def test_authorised_package_fixtures_assess_without_mutating() -> None:
    evidence = assess(PACKAGE_FIXTURES)
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES)
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    for rc in REFUSAL_CLASSES:
        assert default_probe(rc, PACKAGE_FIXTURES / rc) is True


def test_cli_assess_is_fail_closed_without_inventory_and_writes_evidence(
    tmp_path: Path,
) -> None:
    assert _CLI.main(["assess", "--inventory", str(tmp_path / "missing")]) == 2
    output = tmp_path / "evidence.json"
    assert _CLI.main(["assess", "--output", str(output)]) == 0
    raw = output.read_bytes()
    assert b'"status":"PASS"' in raw
    assert b"exact_main_sha" not in raw
