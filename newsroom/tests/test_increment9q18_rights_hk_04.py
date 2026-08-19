import inspect
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.proving import PORTFOLIO, SOURCE_URLS
from newsroom.increment9.rights import (
    BINDINGS,
    FIXTURE_ACCESS_METHOD,
    FIXTURE_FAMILIES,
    FIXTURE_HMAC_KEY,
    FIXTURE_NOW,
    GATE_ID,
    HK_01_ACCESS_METHOD,
    HK_01_GATE_ID,
    HK_02_ACCESS_METHOD,
    HK_02_GATE_ID,
    HK_04_ACCESS_METHOD,
    HK_04_ENDPOINT,
    HK_04_GATE_ID,
    HK_04_SOURCE_ROLE,
    HMAC_KEY_NAME,
    INVENTORY_NAME,
    PACKAGE_FIXTURES_HK_04,
    PROBE_COUNTS_BY_GATE,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    UK_02_ACCESS_METHOD,
    UK_02_GATE_ID,
    UK_03_GATE_ID,
    UK_05_GATE_ID,
    UK_10_ACCESS_METHOD,
    UK_10_GATE_ID,
    QualificationError,
    RightsError,
    assess,
    assess_rights,
    bind_inventory,
    evidence_json,
    fixture_inventory,
    fixture_review,
    probe_for,
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

_COUNTS = PROBE_COUNTS_BY_GATE[HK_04_GATE_ID]
_UNEMITTED = (
    "RIGHTS_RAD-01",
    "RIGHTS_RAD-02",
)


def _inventory_bytes() -> bytes:
    return PACKAGE_FIXTURES_HK_04.joinpath(INVENTORY_NAME).read_bytes()


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
    for path in PACKAGE_FIXTURES_HK_04.iterdir():
        (root / path.name).write_bytes(path.read_bytes())
    return root


def test_assess_fails_closed_without_inventory(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="inventory"):
        assess(tmp_path / "missing", gate=HK_04_GATE_ID)


def test_assess_fails_closed_without_a_valid_inventory(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    root.joinpath(HMAC_KEY_NAME).write_bytes(FIXTURE_HMAC_KEY)
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(PACKAGE_FIXTURES_HK_04.joinpath(rc).read_bytes())
    with pytest.raises(QualificationError, match="inventory"):
        assess(root, gate=HK_04_GATE_ID)
    with pytest.raises(QualificationError, match="inventory"):
        assess(root, gate=HK_04_GATE_ID, rights_inventory={})
    (root / INVENTORY_NAME).write_bytes(b"{")
    with pytest.raises(QualificationError, match="inventory"):
        assess(root, gate=HK_04_GATE_ID)


def test_assess_fails_closed_when_a_refusal_class_is_missing(tmp_path: Path) -> None:
    root = _inventory(tmp_path)
    (root / REFUSAL_CLASSES[0]).unlink()
    with pytest.raises(QualificationError, match="refusal"):
        assess(root, gate=HK_04_GATE_ID)


def test_assess_fails_closed_when_an_extra_refusal_class_is_present(
    tmp_path: Path,
) -> None:
    root = _inventory(tmp_path)
    (root / "EXTRA").write_bytes(b"extra")
    with pytest.raises(QualificationError, match="refusal"):
        assess(root, gate=HK_04_GATE_ID)


def test_news_pool_paths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="news_pool"):
        assess(tmp_path / "news_pool.sqlite3", gate=HK_04_GATE_ID)


def test_assess_emits_qualification_evidence_not_a_gate_record(tmp_path: Path) -> None:
    root = _authorised_inventory(tmp_path)
    evidence = assess(root, gate=HK_04_GATE_ID)
    again = assess(root, gate=HK_04_GATE_ID)
    assert evidence.evidence_digest == again.evidence_digest
    first = assess_rights(
        HK_04_GATE_ID, inventory=fixture_inventory(gate=HK_04_GATE_ID), now=FIXTURE_NOW
    )
    second = assess_rights(
        HK_04_GATE_ID, inventory=fixture_inventory(gate=HK_04_GATE_ID), now=FIXTURE_NOW
    )
    assert first == second
    assert first.status == "PASS"
    assert first.endpoint == evidence.endpoint == HK_04_ENDPOINT
    assert first.source_role == evidence.source_role == HK_04_SOURCE_ROLE
    assert first.families == evidence.families == tuple(sorted(FIXTURE_FAMILIES))
    assert len(set(first.families)) == 3
    assert evidence.gate_id == HK_04_GATE_ID == "RIGHTS_HK-04"
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES) == 10
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.engaged for item in evidence.refusals)
    counts = {item.refusal_class: item.count for item in evidence.refusals}
    assert counts == _COUNTS
    assert counts["BINDING_MISMATCH"] == 4
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"deterministic_pass":true' in payload
    assert b'"gate_id":"RIGHTS_HK-04"' in payload
    assert b'"unanimous":true' in payload
    assert HK_04_ENDPOINT.encode() in payload
    assert b"&amp;" not in payload
    assert b"/en/" not in payload
    assert b"HKEAA" not in payload
    assert b"HTTPS_GET_PUBLIC_ATOM" not in payload
    assert b"HTTPS_GET_PUBLIC_CONTENT_API_JSON" not in payload
    assert b"HTTPS_GET_PUBLIC_WARNINGS_RSS" not in payload
    assert b"HTTPS_GET_PUBLIC_HKO_WARNSUM_JSON" not in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload
    assert b'"status":"PASS"' in payload
    assert evidence.evidence_digest.encode() in payload
    assert b"RIGHTS_HK-03" not in payload
    assert b"RIGHTS_RAD-01" not in payload
    assert b"RIGHTS_RAD-02" not in payload


def test_assess_fails_closed_when_a_probe_mutates(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def mutate(rc: str, path: Path) -> bool:
        path.write_bytes(path.read_bytes() + b"mutated")
        return True

    with pytest.raises(QualificationError, match="mutated"):
        assess(root, probe=mutate, gate=HK_04_GATE_ID)


def test_assess_fails_closed_when_not_all_refusals_engage(tmp_path: Path) -> None:
    root = _inventory(tmp_path)

    def partial_engage(rc: str, path: Path) -> bool:
        return rc in REFUSAL_CLASSES[:2]

    with pytest.raises(QualificationError, match="not all refusals"):
        assess(root, probe=partial_engage, gate=HK_04_GATE_ID)


def test_authorised_package_fixtures_assess_without_mutating() -> None:
    evidence = assess(PACKAGE_FIXTURES_HK_04, gate=HK_04_GATE_ID)
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES)
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    writer = probe_for(HK_04_GATE_ID)
    for rc in REFUSAL_CLASSES:
        assert writer(rc, PACKAGE_FIXTURES_HK_04 / rc) is True


def test_cli_assess_is_fail_closed_without_inventory_and_writes_evidence(
    tmp_path: Path,
) -> None:
    assert (
        _CLI.main(
            [
                "assess",
                "--gate",
                HK_04_GATE_ID,
                "--inventory",
                str(tmp_path / "missing"),
            ]
        )
        == 2
    )
    for gate in _UNEMITTED:
        assert _CLI.main(["assess", "--gate", gate]) == 2
    output = tmp_path / "evidence.json"
    assert _CLI.main(["assess", "--gate", HK_04_GATE_ID, "--output", str(output)]) == 0
    raw = output.read_bytes()
    assert b'"status":"PASS"' in raw
    assert b'"deterministic_pass":true' in raw
    assert b"exact_main_sha" not in raw
    assert b'"gate_id":"RIGHTS_HK-04"' in raw
    assert _CLI.main(["assess", "--gate", HK_04_GATE_ID, "--output", str(output)]) == 0
    assert output.read_bytes() == raw


def test_proving_store_cli_is_fail_closed_without_rights_inventory() -> None:
    assert (
        _PROVING_CLI.main(["assess", "--run-id", "r1", "--attest-no-emergency-stop"])
        == 2
    )


def test_ten_refusal_classes_fail_closed_on_the_real_contracts() -> None:
    authorised = fixture_inventory(gate=HK_04_GATE_ID)
    assert assess_rights(HK_04_GATE_ID, inventory=None, now=FIXTURE_NOW).status == "FAIL"
    empty = dict(authorised)
    empty["reviews"] = []
    assert assess_rights(HK_04_GATE_ID, inventory=empty, now=FIXTURE_NOW).status == "FAIL"
    one = dict(authorised)
    one["reviews"] = [fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID)]
    two = dict(authorised)
    two["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID),
        fixture_review(FIXTURE_FAMILIES[1], gate=HK_04_GATE_ID),
    ]
    for inventory in (one, two):
        assert (
            assess_rights(HK_04_GATE_ID, inventory=inventory, now=FIXTURE_NOW).status
            == "FAIL"
        )
    duplicate = dict(authorised)
    duplicate["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID),
        fixture_review(FIXTURE_FAMILIES[1], gate=HK_04_GATE_ID),
        fixture_review(
            FIXTURE_FAMILIES[0],
            gate=HK_04_GATE_ID,
            reviewer_id="reviewer-duplicate-9q18",
        ),
    ]
    assert (
        assess_rights(HK_04_GATE_ID, inventory=duplicate, now=FIXTURE_NOW).status
        == "FAIL"
    )
    missing = fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID)
    del missing["retention"]
    extra = fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID)
    extra["extra"] = "field"
    vacant = fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID, destinations=[])
    rest = authorised["reviews"][1:]
    for bad in (missing, extra, vacant):
        broken = dict(authorised)
        broken["reviews"] = [bad, *rest]
        assert (
            assess_rights(HK_04_GATE_ID, inventory=broken, now=FIXTURE_NOW).status
            == "FAIL"
        )
    sealed = dict(authorised)
    sealed["reviews"] = [
        fixture_review(
            FIXTURE_FAMILIES[0],
            gate=HK_04_GATE_ID,
            seal="hmac-sha256:" + "0" * 64,
        ),
        *rest,
    ]
    assert (
        assess_rights(HK_04_GATE_ID, inventory=sealed, now=FIXTURE_NOW).status == "FAIL"
    )
    for verdict in ("FAIL", "WAIVE"):
        other = dict(authorised)
        other["reviews"] = [
            fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID, verdict=verdict),
            *rest,
        ]
        assert (
            assess_rights(HK_04_GATE_ID, inventory=other, now=FIXTURE_NOW).status
            == "FAIL"
        )
    for changes in (
        {"gate_id": HK_01_GATE_ID},
        {"source_role": BINDINGS[HK_01_GATE_ID][1]},
        {"endpoint": BINDINGS[HK_01_GATE_ID][2]},
    ):
        mismatched = dict(authorised)
        mismatched["reviews"] = [
            fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID, **changes),
            *rest,
        ]
        assert (
            assess_rights(HK_04_GATE_ID, inventory=mismatched, now=FIXTURE_NOW).status
            == "FAIL"
        )
    hk01 = fixture_inventory(gate=HK_01_GATE_ID)
    assert assess_rights(HK_04_GATE_ID, inventory=hk01, now=FIXTURE_NOW).status == "FAIL"
    drifted = dict(authorised)
    drifted["reviews"] = [
        fixture_review(
            FIXTURE_FAMILIES[0],
            gate=HK_04_GATE_ID,
            terms_digest="sha256:" + "0" * 64,
        ),
        *rest,
    ]
    assert (
        assess_rights(HK_04_GATE_ID, inventory=drifted, now=FIXTURE_NOW).status == "FAIL"
    )
    expired = dict(authorised)
    expired["reviews"] = [
        fixture_review(FIXTURE_FAMILIES[0], gate=HK_04_GATE_ID, expires_at=FIXTURE_NOW),
        *rest,
    ]
    future = dict(authorised)
    future["reviews"] = [
        fixture_review(
            FIXTURE_FAMILIES[0],
            gate=HK_04_GATE_ID,
            issued_at="2026-08-18T12:00:00.000001Z",
        ),
        *rest,
    ]
    assert (
        assess_rights(HK_04_GATE_ID, inventory=expired, now=FIXTURE_NOW).status == "FAIL"
    )
    assert (
        assess_rights(HK_04_GATE_ID, inventory=future, now=FIXTURE_NOW).status == "FAIL"
    )
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    bare = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    rights_gate = next(g for g in bare if g.gate_id == HK_04_GATE_ID)
    assert rights_gate.status is GateStatus.FAIL
    assert rights_gate.reason == "inventory is required"
    assert assess_rights(HK_04_GATE_ID, inventory=True, now=FIXTURE_NOW).status == "FAIL"
    with pytest.raises(RightsError, match="required_gate_ids"):
        refuse_namesake_satisfaction(required_gate_ids(), gate=HK_04_GATE_ID)
    with pytest.raises(RightsError, match="boolean"):
        refuse_boolean(True)
    with pytest.raises(RightsError, match="Gate Record"):
        refuse_gate_record_namesake(
            {"reviewer_families": list(FIXTURE_FAMILIES), "subject_digest": "x"}
        )
    uk01 = fixture_inventory(gate=GATE_ID)
    uk02 = fixture_inventory(gate=UK_02_GATE_ID)
    uk03 = fixture_inventory(gate=UK_03_GATE_ID)
    uk05 = fixture_inventory(gate=UK_05_GATE_ID)
    uk10 = fixture_inventory(gate=UK_10_GATE_ID)
    hk02 = fixture_inventory(gate=HK_02_GATE_ID)
    siblings = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        rights=uk01,
        rights_uk_02=uk02,
        rights_uk_03=uk03,
        rights_uk_05=uk05,
        rights_uk_10=uk10,
        rights_hk_01=hk01,
        rights_hk_02=hk02,
        now=FIXTURE_NOW,
    )
    assert next(g for g in siblings if g.gate_id == GATE_ID).status is GateStatus.PASS
    assert (
        next(g for g in siblings if g.gate_id == UK_02_GATE_ID).status is GateStatus.PASS
    )
    assert (
        next(g for g in siblings if g.gate_id == UK_03_GATE_ID).status is GateStatus.PASS
    )
    assert (
        next(g for g in siblings if g.gate_id == UK_05_GATE_ID).status is GateStatus.PASS
    )
    assert (
        next(g for g in siblings if g.gate_id == UK_10_GATE_ID).status is GateStatus.PASS
    )
    assert (
        next(g for g in siblings if g.gate_id == HK_01_GATE_ID).status is GateStatus.PASS
    )
    assert (
        next(g for g in siblings if g.gate_id == HK_02_GATE_ID).status is GateStatus.PASS
    )
    assert (
        next(g for g in siblings if g.gate_id == HK_04_GATE_ID).status is GateStatus.FAIL
    )
    cross = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        rights_hk_04=hk01,
        now=FIXTURE_NOW,
    )
    assert next(g for g in cross if g.gate_id == HK_04_GATE_ID).status is GateStatus.FAIL


def test_campaign_namesake_list_membership_cannot_pass() -> None:
    with pytest.raises(RightsError, match="required_gate_ids"):
        refuse_namesake_satisfaction(required_gate_ids(), gate=HK_04_GATE_ID)
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    module_source = inspect.getsource(campaign_mod)
    assert HK_04_GATE_ID in required_gate_ids()
    assert "assess_rights" not in source
    assert "assess_rights" not in module_source
    assert "increment9.rights" not in module_source
    findings = _gate_findings(
        {},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "MISSING_GATE:RIGHTS_HK-04" in findings


def test_package_inventory_matches_fixture_inventory() -> None:
    loaded = json.loads(PACKAGE_FIXTURES_HK_04.joinpath(INVENTORY_NAME).read_bytes())
    assert canonical_json_bytes(loaded) == canonical_json_bytes(
        fixture_inventory(gate=HK_04_GATE_ID)
    )
    bound = bind_inventory(loaded)
    families = [item["reviewer_family"] for item in bound["reviews"]]
    assert families == list(FIXTURE_FAMILIES)
    assert len(set(families)) == 3
    assert PACKAGE_FIXTURES_HK_04.joinpath(HMAC_KEY_NAME).read_bytes() == FIXTURE_HMAC_KEY
    assert bound["now"] == FIXTURE_NOW
    for item in bound["reviews"]:
        assert item["endpoint"] == HK_04_ENDPOINT
        assert "&amp;" not in item["endpoint"]
        assert "/en/" not in item["endpoint"]
        assert item["source_role"] == HK_04_SOURCE_ROLE
        assert item["gate_id"] == HK_04_GATE_ID
        assert item["access_method"] == HK_04_ACCESS_METHOD == HK_01_ACCESS_METHOD
        assert item["access_method"] != FIXTURE_ACCESS_METHOD
        assert item["access_method"] != UK_02_ACCESS_METHOD
        assert item["access_method"] != UK_10_ACCESS_METHOD
        assert item["access_method"] != HK_02_ACCESS_METHOD
        assert item["verdict"] == "PASS"


def test_bindings_match_od001_and_proving_assess_wires_hk_04_independently() -> None:
    assert BINDINGS[HK_04_GATE_ID][1] == HK_04_SOURCE_ROLE
    assert BINDINGS[HK_04_GATE_ID][2] == HK_04_ENDPOINT == SOURCE_URLS["HK-04"]
    assert HK_04_ENDPOINT == next(
        url for source_id, url in PORTFOLIO if source_id == "HK-04"
    )
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    gates = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    ids = tuple(g.gate_id for g in gates)
    assert GATE_ID in ids
    assert UK_02_GATE_ID in ids
    assert UK_03_GATE_ID in ids
    assert UK_05_GATE_ID in ids
    assert UK_10_GATE_ID in ids
    assert HK_01_GATE_ID in ids
    assert HK_02_GATE_ID in ids
    assert HK_04_GATE_ID in ids
    assert "RIGHTS_RAD-01" not in ids
    assert "RIGHTS_RAD-02" not in ids
    hk04 = fixture_inventory(gate=HK_04_GATE_ID)
    hk04_only = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        rights_hk_04=hk04,
        now=FIXTURE_NOW,
    )
    assert next(g for g in hk04_only if g.gate_id == GATE_ID).status is GateStatus.FAIL
    assert (
        next(g for g in hk04_only if g.gate_id == UK_02_GATE_ID).status is GateStatus.FAIL
    )
    assert (
        next(g for g in hk04_only if g.gate_id == UK_03_GATE_ID).status is GateStatus.FAIL
    )
    assert (
        next(g for g in hk04_only if g.gate_id == UK_05_GATE_ID).status is GateStatus.FAIL
    )
    assert (
        next(g for g in hk04_only if g.gate_id == UK_10_GATE_ID).status is GateStatus.FAIL
    )
    assert (
        next(g for g in hk04_only if g.gate_id == HK_01_GATE_ID).status is GateStatus.FAIL
    )
    assert (
        next(g for g in hk04_only if g.gate_id == HK_02_GATE_ID).status is GateStatus.FAIL
    )
    assert (
        next(g for g in hk04_only if g.gate_id == HK_04_GATE_ID).status is GateStatus.PASS
    )


def test_no_parallel_rights_modules_were_added() -> None:
    root = Path(__file__).resolve().parents[1] / "increment9"
    assert not (root / "rights_review.py").exists()
    assert not (root / "rights_hk_01.py").exists()
    assert not (root / "rights_hk_02.py").exists()
    assert not (root / "rights_hk_04.py").exists()
    assert not (root / "rights_uk_01.py").exists()
    assert not (root / "rights_uk_02.py").exists()
    assert not (root / "rights_uk_03.py").exists()
    assert not (root / "rights_uk_05.py").exists()
    assert not (root / "rights_uk_10.py").exists()
    assert not (root / "qualification_rights.py").exists()
    assert (root / "rights.py").is_file()


def test_hmac_and_injected_now_are_required_for_pass() -> None:
    inventory = fixture_inventory(gate=HK_04_GATE_ID)
    first = assess_rights(HK_04_GATE_ID, inventory=inventory, now=FIXTURE_NOW)
    second = assess_rights(HK_04_GATE_ID, inventory=inventory, now=FIXTURE_NOW)
    assert first == second
    assert first.status == "PASS"
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    wired = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        rights_hk_04=inventory,
        now=FIXTURE_NOW,
    )
    assert next(g for g in wired if g.gate_id == HK_04_GATE_ID).status is GateStatus.PASS
    late = assess_rights(
        HK_04_GATE_ID, inventory=inventory, now="2026-08-19T00:00:00.000000Z"
    )
    assert late.status == "FAIL"
    early = assess_rights(
        HK_04_GATE_ID, inventory=inventory, now="2026-08-17T23:59:59.000000Z"
    )
    assert early.status == "FAIL"
