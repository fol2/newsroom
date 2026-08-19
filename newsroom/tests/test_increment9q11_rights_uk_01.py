import inspect
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.proving import PORTFOLIO, SOURCE_URLS
from newsroom.increment9.rights import (
    BINDINGS,
    FIXTURE_FAMILIES,
    FIXTURE_HMAC_KEY,
    FIXTURE_NOW,
    GATE_ID,
    HMAC_KEY_NAME,
    INVENTORY_NAME,
    PACKAGE_FIXTURES,
    PROBE_COUNTS,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    UK_01_ENDPOINT,
    UK_01_SOURCE_ROLE,
    QualificationError,
    RightsError,
    assess,
    assess_rights,
    bind_inventory,
    default_probe,
    evidence_json,
    fixture_inventory,
    fixture_review,
    refuse_boolean,
    refuse_gate_record_namesake,
    refuse_namesake_satisfaction,
)

_SPEC = spec_from_file_location(
    "increment9q_rights",
    Path(__file__).resolve().parents[2] / "scripts" / "increment9q_rights.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CLI = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)

_PROVING_SPEC = spec_from_file_location(
    "increment9_proving_store",
    Path(__file__).resolve().parents[2] / "scripts" / "increment9_proving_store.py",
)
assert _PROVING_SPEC is not None and _PROVING_SPEC.loader is not None
_PROVING_CLI = module_from_spec(_PROVING_SPEC)
_PROVING_SPEC.loader.exec_module(_PROVING_CLI)

from scripts.increment9_shadow_campaign import required_gate_ids, _gate_findings


def _inventory_bytes() -> bytes:
    return PACKAGE_FIXTURES.joinpath(INVENTORY_NAME).read_bytes()


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    root.joinpath(INVENTORY_NAME).write_bytes(_inventory_bytes())
    root.joinpath(HMAC_KEY_NAME).write_bytes(FIXTURE_HMAC_KEY)
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(f"refusal:{rc}\n".encode())
    return root


def _authorised_inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    for path in PACKAGE_FIXTURES.iterdir():
        (root / path.name).write_bytes(path.read_bytes())
    return root


def test_assess_fails_closed_without_inventory(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="inventory"):
        assess(tmp_path / "missing")


def test_assess_fails_closed_without_a_valid_inventory(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    root.joinpath(HMAC_KEY_NAME).write_bytes(FIXTURE_HMAC_KEY)
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(PACKAGE_FIXTURES.joinpath(rc).read_bytes())
    with pytest.raises(QualificationError, match="inventory"):
        assess(root)
    with pytest.raises(QualificationError, match="inventory"):
        assess(root, rights_inventory={})
    (root / INVENTORY_NAME).write_bytes(b"{")
    with pytest.raises(QualificationError, match="inventory"):
        assess(root)


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
    root = _authorised_inventory(tmp_path)
    evidence = assess(root)
    again = assess(root)
    assert evidence.evidence_digest == again.evidence_digest
    first = assess_rights(GATE_ID, inventory=fixture_inventory(), now=FIXTURE_NOW)
    second = assess_rights(GATE_ID, inventory=fixture_inventory(), now=FIXTURE_NOW)
    assert first == second
    assert first.status == "PASS"
    assert first.endpoint == evidence.endpoint == UK_01_ENDPOINT
    assert first.source_role == evidence.source_role == UK_01_SOURCE_ROLE
    assert first.families == evidence.families == tuple(sorted(FIXTURE_FAMILIES))
    assert len(set(first.families)) == 3
    assert evidence.gate_id == GATE_ID == "RIGHTS_UK-01"
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES) == 10
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.engaged for item in evidence.refusals)
    counts = {item.refusal_class: item.count for item in evidence.refusals}
    assert counts == PROBE_COUNTS
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"deterministic_pass":true' in payload
    assert b'"gate_id":"RIGHTS_UK-01"' in payload
    assert b'"unanimous":true' in payload
    assert UK_01_ENDPOINT.encode() in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload
    assert b'"status":"PASS"' in payload
    assert evidence.evidence_digest.encode() in payload


def test_assess_fails_closed_when_a_probe_mutates(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def mutate(rc: str, path: Path) -> bool:
        path.write_bytes(path.read_bytes() + b"mutated")
        return True

    with pytest.raises(QualificationError, match="mutated"):
        assess(root, probe=mutate)


def test_assess_fails_closed_when_digest_changes_without_engagement(
    tmp_path: Path,
) -> None:
    root = _inventory(tmp_path)

    def silent_mutate(rc: str, path: Path) -> bool:
        if rc == "NO_RECORDS":
            path.write_bytes(b"changed")
        return False

    with pytest.raises(QualificationError, match="mutated"):
        assess(root, probe=silent_mutate)


def test_assess_fails_closed_when_not_all_refusals_engage(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def partial_engage(rc: str, path: Path) -> bool:
        return rc in REFUSAL_CLASSES[:2]

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
    assert (
        _CLI.main(
            ["assess", "--gate", GATE_ID, "--inventory", str(tmp_path / "missing")]
        )
        == 2
    )
    assert _CLI.main(["assess", "--gate", "RIGHTS_RAD-02"]) == 2
    output = tmp_path / "evidence.json"
    assert _CLI.main(["assess", "--gate", GATE_ID, "--output", str(output)]) == 0
    raw = output.read_bytes()
    assert b'"status":"PASS"' in raw
    assert b'"deterministic_pass":true' in raw
    assert b"exact_main_sha" not in raw
    assert b'"gate_id":"RIGHTS_UK-01"' in raw
    assert _CLI.main(["assess", "--gate", GATE_ID, "--output", str(output)]) == 0
    assert output.read_bytes() == raw


def test_proving_store_cli_is_fail_closed_without_rights_inventory() -> None:
    assert (
        _PROVING_CLI.main(["assess", "--run-id", "r1", "--attest-no-emergency-stop"])
        == 2
    )


def test_ten_refusal_classes_fail_closed_on_the_real_contracts() -> None:
    authorised = fixture_inventory()
    assert assess_rights(GATE_ID, inventory=None, now=FIXTURE_NOW).status == "FAIL"
    empty = dict(authorised)
    empty["reviews"] = []
    assert assess_rights(GATE_ID, inventory=empty, now=FIXTURE_NOW).status == "FAIL"
    one = dict(authorised)
    one["reviews"] = [fixture_review(FIXTURE_FAMILIES[0])]
    two = dict(authorised)
    two["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0]),
        fixture_review(FIXTURE_FAMILIES[1]),
    ]
    for inventory in (one, two):
        assert assess_rights(GATE_ID, inventory=inventory, now=FIXTURE_NOW).status == "FAIL"
    duplicate = dict(authorised)
    duplicate["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0]),
        fixture_review(FIXTURE_FAMILIES[1]),
        fixture_review(FIXTURE_FAMILIES[0], reviewer_id="reviewer-duplicate-9q11"),
    ]
    assert assess_rights(GATE_ID, inventory=duplicate, now=FIXTURE_NOW).status == "FAIL"
    missing = fixture_review(FIXTURE_FAMILIES[0])
    del missing["retention"]
    extra = fixture_review(FIXTURE_FAMILIES[0])
    extra["extra"] = "field"
    vacant = fixture_review(FIXTURE_FAMILIES[0], destinations=[])
    rest = authorised["reviews"][1:]
    for bad in (missing, extra, vacant):
        broken = dict(authorised)
        broken["reviews"] = [bad, *rest]
        assert assess_rights(GATE_ID, inventory=broken, now=FIXTURE_NOW).status == "FAIL"
    sealed = dict(authorised)
    sealed["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], seal="hmac-sha256:" + "0" * 64),
        *rest,
    ]
    assert assess_rights(GATE_ID, inventory=sealed, now=FIXTURE_NOW).status == "FAIL"
    for verdict in ("FAIL", "WAIVE"):
        other = dict(authorised)
        other["reviews"] = [fixture_review(FIXTURE_FAMILIES[0], verdict=verdict), *rest]
        assert assess_rights(GATE_ID, inventory=other, now=FIXTURE_NOW).status == "FAIL"
    for changes in (
        {"gate_id": "RIGHTS_UK-02"},
        {"source_role": "BN(O) authority anchor"},
        {
            "endpoint": "https://www.gov.uk/api/content/british-national-overseas-bno-visa"
        },
    ):
        mismatched = dict(authorised)
        mismatched["reviews"] = [fixture_review(FIXTURE_FAMILIES[0], **changes), *rest]
        assert (
            assess_rights(GATE_ID, inventory=mismatched, now=FIXTURE_NOW).status
            == "FAIL"
        )
    drifted = dict(authorised)
    drifted["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], terms_digest="sha256:" + "0" * 64),
        *rest,
    ]
    assert assess_rights(GATE_ID, inventory=drifted, now=FIXTURE_NOW).status == "FAIL"
    expired = dict(authorised)
    expired["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], expires_at=FIXTURE_NOW),
        *rest,
    ]
    future = dict(authorised)
    future["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], issued_at="2026-08-18T12:00:00.000001Z"),
        *rest,
    ]
    assert assess_rights(GATE_ID, inventory=expired, now=FIXTURE_NOW).status == "FAIL"
    assert assess_rights(GATE_ID, inventory=future, now=FIXTURE_NOW).status == "FAIL"
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    bare = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    rights_gate = next(g for g in bare if g.gate_id == GATE_ID)
    assert rights_gate.status is GateStatus.FAIL
    assert rights_gate.reason == "inventory is required"
    assert assess_rights(GATE_ID, inventory=True, now=FIXTURE_NOW).status == "FAIL"
    with pytest.raises(RightsError, match="required_gate_ids"):
        refuse_namesake_satisfaction(required_gate_ids())
    with pytest.raises(RightsError, match="boolean"):
        refuse_boolean(True)
    with pytest.raises(RightsError, match="Gate Record"):
        refuse_gate_record_namesake(
            {"reviewer_families": list(FIXTURE_FAMILIES), "subject_digest": "x"}
        )


def test_campaign_namesake_list_membership_cannot_pass() -> None:
    with pytest.raises(RightsError, match="required_gate_ids"):
        refuse_namesake_satisfaction(required_gate_ids())
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    module_source = inspect.getsource(campaign_mod)
    assert GATE_ID in required_gate_ids()
    assert "assess_rights" not in source
    assert "assess_rights" not in module_source
    assert "increment9.rights" not in module_source
    findings = _gate_findings(
        {},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "MISSING_GATE:RIGHTS_UK-01" in findings


def test_package_inventory_matches_fixture_inventory() -> None:
    loaded = json.loads(PACKAGE_FIXTURES.joinpath(INVENTORY_NAME).read_bytes())
    assert canonical_json_bytes(loaded) == canonical_json_bytes(fixture_inventory())
    bound = bind_inventory(loaded)
    families = [item["reviewer_family"] for item in bound["reviews"]]
    assert families == list(FIXTURE_FAMILIES)
    assert len(set(families)) == 3
    assert PACKAGE_FIXTURES.joinpath(HMAC_KEY_NAME).read_bytes() == FIXTURE_HMAC_KEY
    assert bound["now"] == FIXTURE_NOW
    for item in bound["reviews"]:
        assert item["endpoint"] == UK_01_ENDPOINT
        assert item["source_role"] == UK_01_SOURCE_ROLE
        assert item["gate_id"] == GATE_ID
        assert item["verdict"] == "PASS"
        assert "&amp;" not in item["endpoint"]


def test_bindings_match_portfolio_and_proving_assess_wires_uk_01_uk_02_and_uk_03() -> None:
    assert len(BINDINGS) == 10
    assert set(BINDINGS) == {f"RIGHTS_{source_id}" for source_id, _ in PORTFOLIO}
    for gate_id, (source_id, _role, endpoint) in BINDINGS.items():
        assert "&amp;" not in endpoint
        assert gate_id == f"RIGHTS_{source_id}"
        if source_id == "UK-10":
            assert endpoint != SOURCE_URLS[source_id]
            continue
        if source_id == "RAD-01":
            assert endpoint != SOURCE_URLS[source_id]
            continue
        assert endpoint == SOURCE_URLS[source_id]
    assert BINDINGS[GATE_ID][2] == UK_01_ENDPOINT
    from newsroom.increment9.proving import assess as proving_assess

    gates = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    ids = tuple(g.gate_id for g in gates)
    assert GATE_ID in ids
    assert "RIGHTS_UK-02" in ids
    assert "RIGHTS_UK-03" in ids
    assert "RIGHTS_RAD-02" not in ids


def test_no_parallel_rights_modules_were_added() -> None:
    root = Path(__file__).resolve().parents[1] / "increment9"
    assert not (root / "rights_review.py").exists()
    assert not (root / "rights_uk_01.py").exists()
    assert not (root / "rights_uk_02.py").exists()
    assert not (root / "rights_uk_03.py").exists()
    assert not (root / "qualification_rights.py").exists()
    assert (root / "rights.py").is_file()


def test_hmac_and_injected_now_are_required_for_pass() -> None:
    inventory = fixture_inventory()
    first = assess_rights(GATE_ID, inventory=inventory, now=FIXTURE_NOW)
    second = assess_rights(GATE_ID, inventory=inventory, now=FIXTURE_NOW)
    assert first == second
    assert first.status == "PASS"
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    wired = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        rights=inventory,
        now=FIXTURE_NOW,
    )
    assert next(g for g in wired if g.gate_id == GATE_ID).status is GateStatus.PASS
    late = assess_rights(
        GATE_ID, inventory=inventory, now="2026-08-19T00:00:00.000000Z"
    )
    assert late.status == "FAIL"
    early = assess_rights(
        GATE_ID, inventory=inventory, now="2026-08-17T23:59:59.000000Z"
    )
    assert early.status == "FAIL"
