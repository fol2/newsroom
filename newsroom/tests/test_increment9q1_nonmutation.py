from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.increment9.qualification import (
    GATE_ID,
    SCHEMA_VERSION,
    WRITER_ROUTES,
    QualificationError,
    assess,
    evidence_json,
)

_SPEC = spec_from_file_location(
    "increment9q_nonmutation",
    Path(__file__).resolve().parents[2] / "scripts" / "increment9q_nonmutation.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CLI = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    for route in WRITER_ROUTES:
        (root / route).write_bytes(f"fixture:{route}\n".encode())
    return root


def test_assess_fails_closed_without_inventory(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="inventory"):
        assess(tmp_path / "missing")


def test_assess_fails_closed_when_a_surface_is_missing(tmp_path: Path) -> None:
    root = _inventory(tmp_path)
    (root / WRITER_ROUTES[0]).unlink()
    with pytest.raises(QualificationError, match="surface"):
        assess(root)


def test_production_and_news_pool_paths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="news_pool"):
        assess(tmp_path / "news_pool.sqlite3")
    with pytest.raises(QualificationError, match="production"):
        assess(tmp_path / "production")


def test_assess_emits_qualification_evidence_not_a_gate_record(tmp_path: Path) -> None:
    evidence = assess(_inventory(tmp_path))
    assert evidence.gate_id == GATE_ID
    assert evidence.status == "PASS"
    assert evidence.publication is False
    assert evidence.public_dispatch is False
    assert evidence.production_writer_successes == 0
    assert tuple(item.route for item in evidence.surfaces) == WRITER_ROUTES
    assert all(item.before_digest == item.after_digest for item in evidence.surfaces)
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"publication":false' in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload


def test_assess_fails_closed_when_a_writer_probe_mutates(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def mutate(route: str, path: Path) -> bool:
        path.write_bytes(path.read_bytes() + b"mutated")
        return True

    with pytest.raises(QualificationError, match="writer"):
        assess(root, probe=mutate)


def test_assess_fails_closed_when_digest_changes_without_claimed_write(
    tmp_path: Path,
) -> None:
    root = _inventory(tmp_path)

    def silent(route: str, path: Path) -> bool:
        if route == "PUBLICATION":
            path.write_bytes(b"changed")
        return False

    with pytest.raises(QualificationError, match="digest"):
        assess(root, probe=silent)


def test_cli_assess_is_fail_closed_without_inventory_and_writes_evidence(
    tmp_path: Path,
) -> None:
    assert _CLI.main(["assess"]) == 2
    output = tmp_path / "evidence.json"
    assert _CLI.main(["assess", "--inventory", str(_inventory(tmp_path)), "--output", str(output)]) == 0
    raw = output.read_bytes()
    assert b'"status":"PASS"' in raw
    assert b"exact_main_sha" not in raw
