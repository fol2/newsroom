import json
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment8.observability import AccessContract, SecurityAdmission
from newsroom.increment9.deployment import (
    EXPECTED_EGRESS_DESTINATIONS,
    READINESS_ONLY_DESTINATIONS,
)
from newsroom.increment9.provider_terms import (
    FIXTURE_NOW,
    GATE_ID,
    LIVE_PATH,
    LIVE_ROUTE_ID,
    NO_PROVIDER_PATH,
    NO_PROVIDER_ROUTE_ID,
    NON_PROVIDER_EGRESS,
    PROVIDER_CLASSES,
    ProviderTermsError,
    admit,
    bind_campaign_provider_terms,
    bind_inventory,
    bind_provider_classes,
    fixture_declaration,
    fixture_inventory,
    fixture_terms_record,
    live_route_destinations,
    no_provider_destinations,
    refuse_increment8_terms_current,
    refuse_namesake_satisfaction,
    refuse_openrouter_unused,
)
from newsroom.increment9.provider_terms_current import (
    INVENTORY_NAME,
    PACKAGE_FIXTURES,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    QualificationError,
    assess,
    default_probe,
    evidence_json,
)
from newsroom.increment9.proving import PROVING_GATES

_SPEC = spec_from_file_location(
    "increment9q8_provider_terms_current",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "increment9q8_provider_terms_current.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CLI = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)

from scripts.increment9_shadow_campaign import (
    RUNTIME_GATES,
    GateRecord,
    GateStatus,
    _gate_findings,
    main as campaign_main,
)


def _inventory_bytes() -> bytes:
    return PACKAGE_FIXTURES.joinpath(INVENTORY_NAME).read_bytes()


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    root.joinpath(INVENTORY_NAME).write_bytes(_inventory_bytes())
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
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(PACKAGE_FIXTURES.joinpath(rc).read_bytes())
    with pytest.raises(QualificationError, match="inventory"):
        assess(root)
    with pytest.raises(QualificationError, match="inventory"):
        assess(root, terms_inventory={})
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
    evidence = assess(_authorised_inventory(tmp_path))
    assert evidence.gate_id == GATE_ID
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES) == 10
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.count == 1 and item.engaged for item in evidence.refusals)
    live = admit(LIVE_ROUTE_ID, inventory=fixture_inventory())
    named = admit(NO_PROVIDER_ROUTE_ID, inventory=fixture_inventory())
    assert evidence.live_route_digest == live.digest
    assert evidence.no_provider_route_digest == named.digest
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"refusals_engaged":10' in payload
    assert b'"gate_id":"PROVIDER_TERMS_CURRENT"' in payload
    assert b'"LIVE_ROUTE"' in payload
    assert b'"NO_PROVIDER_ROUTE"' in payload
    assert evidence.live_route_digest.encode() in payload
    assert evidence.no_provider_route_digest.encode() in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload


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
        return rc in REFUSAL_CLASSES[:4]

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
    assert b'"gate_id":"PROVIDER_TERMS_CURRENT"' in raw
    assert b'"LIVE_ROUTE"' in raw
    assert b'"NO_PROVIDER_ROUTE"' in raw


def test_six_class_universe_is_od012_commercial_api_subset() -> None:
    assert PROVIDER_CLASSES == bind_provider_classes()
    assert PROVIDER_CLASSES == (
        "ANTHROPIC_AGENT_SDK",
        "APPROVED_REVIEW_RESEARCH",
        "GOOGLE_GEMINI_API",
        "OPENAI_CODEX",
        "OPENAI_EMBEDDINGS",
        "XAI_GROK_BUILD",
    )
    assert NON_PROVIDER_EGRESS == {
        "INTEGRATED_NEWSROOM_TARGET",
        "TEN_APPROVED_SOURCE_ENDPOINTS",
    }
    assert set(PROVIDER_CLASSES).isdisjoint(NON_PROVIDER_EGRESS)
    assert set(PROVIDER_CLASSES) | NON_PROVIDER_EGRESS == set(
        EXPECTED_EGRESS_DESTINATIONS
    )
    for cls in PROVIDER_CLASSES:
        assert cls in EXPECTED_EGRESS_DESTINATIONS
    assert "LOCAL_FILESYSTEM" in READINESS_ONLY_DESTINATIONS
    assert "INTEGRATED_NEWSROOM_TARGET" in live_route_destinations()
    assert "TEN_APPROVED_SOURCE_ENDPOINTS" in no_provider_destinations()


def test_dual_path_pass_and_crossing_is_refused() -> None:
    inventory = fixture_inventory()
    live = admit(LIVE_ROUTE_ID, inventory=inventory)
    named = admit(NO_PROVIDER_ROUTE_ID, inventory=inventory)
    assert live.path == LIVE_PATH
    assert named.path == NO_PROVIDER_PATH
    assert live.admitted_provider_classes == PROVIDER_CLASSES
    assert named.admitted_provider_classes == ()
    crossed = fixture_inventory()
    crossed["routes"][LIVE_ROUTE_ID]["declaration"] = fixture_declaration(
        LIVE_ROUTE_ID, live_route_destinations()
    )
    with pytest.raises(ProviderTermsError, match="path crossing"):
        admit(LIVE_ROUTE_ID, inventory=crossed)


def test_subset_live_route_needs_only_admitted_classes() -> None:
    inventory = fixture_inventory()
    live = inventory["routes"][LIVE_ROUTE_ID]
    live["admitted_destinations"] = ["OPENAI_EMBEDDINGS"]
    live["terms_records"] = [fixture_terms_record("OPENAI_EMBEDDINGS")]
    admission = admit(LIVE_ROUTE_ID, inventory=inventory)
    assert admission.path == LIVE_PATH
    assert admission.admitted_provider_classes == ("OPENAI_EMBEDDINGS",)


def test_no_records_path_crossing_and_contradiction_are_refused() -> None:
    with pytest.raises(ProviderTermsError, match="inventory"):
        admit(LIVE_ROUTE_ID, inventory=None)
    with pytest.raises(ProviderTermsError, match="inventory"):
        bind_inventory({})
    empty = fixture_inventory()
    empty["routes"][LIVE_ROUTE_ID]["terms_records"] = []
    with pytest.raises(ProviderTermsError, match="records"):
        admit(LIVE_ROUTE_ID, inventory=empty)
    contradicted = fixture_inventory()
    route = contradicted["routes"][NO_PROVIDER_ROUTE_ID]
    route["admitted_destinations"] = sorted(
        {*route["admitted_destinations"], "ANTHROPIC_AGENT_SDK"}
    )
    with pytest.raises(ProviderTermsError, match="contradicted"):
        admit(NO_PROVIDER_ROUTE_ID, inventory=contradicted)
    counted = fixture_inventory()
    counted["provider_call_count"] = 1
    with pytest.raises(ProviderTermsError, match="contradicted"):
        admit(NO_PROVIDER_ROUTE_ID, inventory=counted)


def test_incomplete_unexpected_and_digest_drift_are_refused() -> None:
    incomplete = fixture_inventory()
    incomplete["routes"][LIVE_ROUTE_ID]["terms_records"].pop()
    with pytest.raises(ProviderTermsError, match="incomplete"):
        admit(LIVE_ROUTE_ID, inventory=incomplete)
    unexpected = fixture_inventory()
    unexpected["routes"][LIVE_ROUTE_ID]["terms_records"].append(
        fixture_terms_record("INTEGRATED_NEWSROOM_TARGET")
    )
    with pytest.raises(ProviderTermsError, match="unexpected"):
        admit(LIVE_ROUTE_ID, inventory=unexpected)
    drifted = fixture_inventory()
    cls = drifted["routes"][LIVE_ROUTE_ID]["terms_records"][0]["provider_class"]
    drifted["routes"][LIVE_ROUTE_ID]["terms_records"][0] = fixture_terms_record(
        cls, terms_digest="sha256:" + "0" * 64
    )
    with pytest.raises(ProviderTermsError, match="digest"):
        admit(LIVE_ROUTE_ID, inventory=drifted)


def test_window_seal_and_malformed_records_are_refused() -> None:
    expired = fixture_inventory()
    cls = expired["routes"][LIVE_ROUTE_ID]["terms_records"][0]["provider_class"]
    expired["routes"][LIVE_ROUTE_ID]["terms_records"][0] = fixture_terms_record(
        cls, expires_at=FIXTURE_NOW
    )
    with pytest.raises(ProviderTermsError, match="expired"):
        admit(LIVE_ROUTE_ID, inventory=expired)
    future = fixture_inventory()
    future_cls = future["routes"][LIVE_ROUTE_ID]["terms_records"][0]["provider_class"]
    future["routes"][LIVE_ROUTE_ID]["terms_records"][0] = fixture_terms_record(
        future_cls, issued_at="2026-08-18T12:00:00.000001Z"
    )
    with pytest.raises(ProviderTermsError, match="future"):
        admit(LIVE_ROUTE_ID, inventory=future)
    sealed = fixture_inventory()
    sealed_cls = sealed["routes"][LIVE_ROUTE_ID]["terms_records"][0]["provider_class"]
    sealed["routes"][LIVE_ROUTE_ID]["terms_records"][0] = fixture_terms_record(
        sealed_cls, seal="hmac-sha256:" + "0" * 64
    )
    with pytest.raises(ProviderTermsError, match="seal"):
        admit(LIVE_ROUTE_ID, inventory=sealed)
    missing = fixture_inventory()
    del missing["routes"][LIVE_ROUTE_ID]["terms_records"][0]["terms_url"]
    with pytest.raises(ProviderTermsError, match="malformed"):
        admit(LIVE_ROUTE_ID, inventory=missing)
    extra = fixture_inventory()
    extra["routes"][LIVE_ROUTE_ID]["terms_records"][0]["extra"] = "field"
    with pytest.raises(ProviderTermsError, match="malformed"):
        admit(LIVE_ROUTE_ID, inventory=extra)
    with pytest.raises(ProviderTermsError, match="malformed"):
        admit("H" * 257, inventory=fixture_inventory())


def test_campaign_namesake_list_membership_cannot_pass() -> None:
    with pytest.raises(ProviderTermsError, match="RUNTIME_GATES"):
        refuse_namesake_satisfaction(RUNTIME_GATES)
    with pytest.raises(ProviderTermsError, match="terms_current"):
        refuse_increment8_terms_current(True)
    with pytest.raises(ProviderTermsError, match="OPENROUTER_UNUSED"):
        refuse_openrouter_unused()
    bind_campaign_provider_terms()
    import scripts.increment9_shadow_campaign as campaign_mod

    assert hasattr(campaign_mod, "bind_campaign_provider_terms")
    assert GATE_ID in RUNTIME_GATES
    assert "OPENROUTER_UNUSED" in PROVING_GATES


def test_increment8_terms_current_boolean_cannot_satisfy_this_gate() -> None:
    contract = AccessContract.build(
        contract_id="fixture-access:v1",
        approved_hosts=["fixture.invalid"],
        maximum_redirects=0,
        request_timeout_seconds=30,
        maximum_body_bytes=1_000_000,
        content_types=["application/json"],
    )
    admission = SecurityAdmission.build(
        access_contract=contract,
        exact_version_approved=True,
        rights_current=True,
        terms_current=True,
        pricing_current=True,
        credential_scope_current=True,
        rollback_tested=True,
        scoped_disable_tested=True,
        graph_capability_admitted=True,
        runbook_version_digest="sha256:" + "1" * 64,
    )
    payload = json.loads(admission.canonical_bytes)["payload"]
    assert payload["terms_current"] is True
    assert admission.eligible is True
    with pytest.raises(ProviderTermsError, match="terms_current"):
        refuse_increment8_terms_current(payload["terms_current"])


def _gate_record(gate_id: str = "PROVIDER_TERMS_CURRENT") -> GateRecord:
    return GateRecord(
        gate_id=gate_id,
        observed_at="2026-08-16T00:00:00.000000Z",
        expires_at="2026-08-17T00:00:00.000000Z",
        exact_main_sha="a" * 40,
        exact_main_tree="b" * 40,
        subject_digest="sha256:" + "c" * 64,
        evidence_digest="sha256:" + "d" * 64,
        issuer_id="fixture",
        status=GateStatus.PASS,
    )


def test_campaign_gate_check_uses_admitter_not_a_bare_gate_name() -> None:
    findings_ok = _gate_findings(
        {"PROVIDER_TERMS_CURRENT": _gate_record()},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "PROVIDER_TERMS_UNBOUND" not in findings_ok
    assert "MISSING_GATE:PROVIDER_TERMS_CURRENT" not in findings_ok
    import inspect
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    assert "bind_campaign_provider_terms" in source


def test_campaign_assess_lands_at_requested_output_and_reruns(
    tmp_path: Path,
) -> None:
    from newsroom.increment9.protected_storage import (
        list_audit_entries,
        write_protected_artefact,
    )

    root = tmp_path / "storage"
    root.mkdir(mode=0o700)
    output = tmp_path / "exact" / "bundle.json"
    payload = {"gate_id": GATE_ID, "status": "PASS"}
    write_protected_artefact(
        root,
        artefact_class="CAMPAIGN_EVIDENCE",
        artefact_id="bundle.json",
        payload=payload,
        target_path=output,
    )
    assert output.is_file()
    write_protected_artefact(
        root,
        artefact_class="CAMPAIGN_EVIDENCE",
        artefact_id="bundle.json",
        payload={"gate_id": GATE_ID, "status": "PASS", "attempt": 2},
        target_path=output,
    )
    assert b'"attempt":2' in output.read_bytes()
    writes = [e for e in list_audit_entries(root) if e.operation == "WRITE"]
    assert len(writes) == 2


def test_campaign_cli_writes_requested_output_and_reruns(tmp_path: Path) -> None:
    repo = tmp_path / "repository"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
    )
    (repo / "tracked.txt").write_text("exact\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "tracked.txt"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Newsroom Tests",
            "-c",
            "user.email=newsroom-tests@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    gates = tmp_path / "gates"
    gates.mkdir(mode=0o700)
    output_dir = tmp_path / "out"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "bundle.json"
    argv = [
        "assess",
        "--repo",
        str(repo),
        "--gate-directory",
        str(gates),
        "--campaign-id",
        "FIXTURE_CAMPAIGN",
        "--observed-at",
        "2026-08-16T12:00:00.000000Z",
        "--output",
        str(output),
        "--accept-blocked",
    ]
    assert campaign_main(argv) == 0
    assert output.is_file()
    first = output.read_bytes()
    assert b"PROVIDER_TERMS_CURRENT" in first
    assert b"MISSING_GATE:PROVIDER_TERMS_CURRENT" in first
    assert b"PROVIDER_TERMS_UNBOUND" not in first
    assert json.loads(first)["launch_receipt"]["finding_ids"]
    assert campaign_main(argv) == 0
    assert output.read_bytes() == first


def test_package_inventory_matches_fixture_inventory() -> None:
    loaded = json.loads(PACKAGE_FIXTURES.joinpath(INVENTORY_NAME).read_bytes())
    assert canonical_json_bytes(loaded) == canonical_json_bytes(fixture_inventory())
    bind_inventory(loaded)
    assert admit(LIVE_ROUTE_ID, inventory=loaded).path == LIVE_PATH
    assert admit(NO_PROVIDER_ROUTE_ID, inventory=loaded).path == NO_PROVIDER_PATH
