import json
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.increment9.deployment import (
    EXPECTED_EGRESS_DESTINATIONS,
    EXPECTED_PROBES,
    READINESS_ONLY_DESTINATIONS,
    DeploymentError,
    admit_readiness_egress,
)
from newsroom.increment9.egress_allowlist import (
    CONTEXT_READINESS,
    CONTEXT_SHADOW,
    DESTINATION_INVENTORY,
    FIXTURE_HOST_MAP,
    NAMESAKE_A2_PROBES,
    EgressAllowlistError,
    admit,
    bind_campaign_egress_allowlist,
    bind_host_map,
    bind_inventory,
    bound_admitter,
    fixture_request,
    inventory_digest,
    policy_digest,
    receipt_from_primitive,
)
from newsroom.increment9.egress_allowlist_enforced import (
    GATE_ID,
    HOST_MAP_NAME,
    PACKAGE_FIXTURES,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    QualificationError,
    assess,
    default_probe,
    evidence_json,
)

_SPEC = spec_from_file_location(
    "increment9q6_egress_allowlist_enforced",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "increment9q6_egress_allowlist_enforced.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CLI = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)

from scripts.increment9_shadow_campaign import (
    GateRecord,
    GateStatus,
    _gate_findings,
    main as campaign_main,
)


def _host_map_bytes() -> bytes:
    return PACKAGE_FIXTURES.joinpath(HOST_MAP_NAME).read_bytes()


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    root.joinpath(HOST_MAP_NAME).write_bytes(_host_map_bytes())
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


def test_assess_fails_closed_without_a_valid_host_map(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(PACKAGE_FIXTURES.joinpath(rc).read_bytes())
    with pytest.raises(QualificationError, match="host map"):
        assess(root)
    with pytest.raises(QualificationError, match="host map"):
        assess(root, host_map={})


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
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES)
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.count == 1 and item.engaged for item in evidence.refusals)
    assert evidence.egress_policy_digest == policy_digest()
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"refusals_engaged":10' in payload
    assert b'"gate_id":"EGRESS_ALLOWLIST_ENFORCED"' in payload
    assert evidence.egress_policy_digest.encode() in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload
    assert b"sk-fixture-not-a-real-secret" not in payload


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
        if rc == "DEFAULT_DENY":
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
    assert b'"gate_id":"EGRESS_ALLOWLIST_ENFORCED"' in raw
    assert policy_digest().encode() in raw


def test_shadow_https_host_is_admitted_with_metadata_only_receipt() -> None:
    receipt = admit(fixture_request())
    assert receipt.destination_class == "ANTHROPIC_AGENT_SDK"
    assert receipt.host == "anthropic.fixture.invalid"
    assert receipt.policy_digest == policy_digest()
    assert set(receipt.primitive()) == {
        "bounds",
        "destination_class",
        "host",
        "policy_digest",
    }
    assert receipt.bounds.tls_minimum == "TLS_1_3"
    assert receipt.bounds.redirects_max == 0
    assert receipt.bounds.response_body_bytes_max == 8_388_608
    assert receipt.bounds.timeout_seconds == 30
    assert receipt.bounds.source_requests_per_day_max == 36


def test_readiness_loopback_agrees_with_admit_readiness_egress() -> None:
    url = "bolt://127.0.0.1:7687"
    receipt = admit(fixture_request(context=CONTEXT_READINESS, url=url))
    assert receipt.destination_class == admit_readiness_egress(url) == "LOCAL_NEO4J"
    with pytest.raises(DeploymentError):
        admit_readiness_egress("https://localhost:7687")
    with pytest.raises(EgressAllowlistError):
        admit(fixture_request(context=CONTEXT_READINESS, url="https://localhost:7687"))


def test_default_deny_unknown_class_and_context_crossing_are_refused() -> None:
    with pytest.raises(EgressAllowlistError, match="default-denied"):
        admit(fixture_request(url="https://absent.fixture.invalid/v1"))
    with pytest.raises(EgressAllowlistError, match="unknown"):
        admit(fixture_request(destination_class="NOT_A_DESTINATION_CLASS"))
    with pytest.raises(EgressAllowlistError, match="context"):
        admit(
            fixture_request(
                context=CONTEXT_SHADOW, url="https://filesystem.fixture.invalid/v1"
            )
        )
    with pytest.raises(EgressAllowlistError, match="context"):
        admit(
            fixture_request(
                context=CONTEXT_READINESS,
                url="https://anthropic.fixture.invalid/v1",
            )
        )


def test_policy_digest_mismatch_and_malformed_requests_are_refused() -> None:
    with pytest.raises(EgressAllowlistError, match="digest"):
        admit(fixture_request(policy_digest="sha256:" + "0" * 64))
    with pytest.raises(EgressAllowlistError, match="malformed"):
        admit(fixture_request(url="https:///missing-host"))
    with pytest.raises(EgressAllowlistError, match="malformed"):
        admit(
            fixture_request(
                url="https://user:secret@anthropic.fixture.invalid/v1"
            )
        )
    with pytest.raises(EgressAllowlistError, match="malformed"):
        admit(fixture_request(source_id="H" * 257))


def test_bounds_and_rate_limits_are_enforced() -> None:
    with pytest.raises(EgressAllowlistError, match="bounds"):
        admit(fixture_request(url="http://anthropic.fixture.invalid/v1"))
    with pytest.raises(EgressAllowlistError, match="bounds"):
        admit(fixture_request(tls_minimum="TLS_1_2"))
    with pytest.raises(EgressAllowlistError, match="bounds"):
        admit(fixture_request(redirects=1))
    with pytest.raises(EgressAllowlistError, match="bounds"):
        admit(fixture_request(body_bytes=8_388_609))
    with pytest.raises(EgressAllowlistError, match="bounds"):
        admit(fixture_request(timeout_seconds=31))
    admitter = bound_admitter()
    for _ in range(36):
        admit(fixture_request(source_id="RATE_SOURCE"), admitter=admitter)
    with pytest.raises(EgressAllowlistError, match="rate"):
        admit(fixture_request(source_id="RATE_SOURCE"), admitter=admitter)


def test_secret_bytes_cannot_enter_an_egress_receipt() -> None:
    receipt = admit(fixture_request())
    with pytest.raises(EgressAllowlistError, match="secret"):
        receipt_from_primitive({**receipt.primitive(), "secret": "sk-fixture"})
    with pytest.raises(EgressAllowlistError, match="fields"):
        receipt_from_primitive(
            {
                "destination_class": receipt.destination_class,
                "host": receipt.host,
                "policy_digest": receipt.policy_digest,
            }
        )
    assert "secret" not in receipt.primitive()


def test_inventory_bind_matches_od012_eight_plus_two() -> None:
    bind_inventory(DESTINATION_INVENTORY)
    assert DESTINATION_INVENTORY == tuple(
        sorted((*EXPECTED_EGRESS_DESTINATIONS, *READINESS_ONLY_DESTINATIONS))
    )
    bind_host_map(FIXTURE_HOST_MAP)
    with pytest.raises(EgressAllowlistError):
        bind_inventory(DESTINATION_INVENTORY[:-1])
    with pytest.raises(EgressAllowlistError):
        bind_inventory(tuple(sorted((*DESTINATION_INVENTORY, "EXTRA_DESTINATION"))))
    with pytest.raises(EgressAllowlistError):
        bind_inventory(
            (
                DESTINATION_INVENTORY[1],
                DESTINATION_INVENTORY[0],
                *DESTINATION_INVENTORY[2:],
            )
        )
    with pytest.raises(EgressAllowlistError):
        bind_inventory((DESTINATION_INVENTORY[0], *DESTINATION_INVENTORY))


def test_campaign_namesake_probes_cannot_pass() -> None:
    with pytest.raises(EgressAllowlistError):
        bind_campaign_egress_allowlist(NAMESAKE_A2_PROBES)
    bind_campaign_egress_allowlist()
    import scripts.increment9_shadow_campaign as campaign_mod

    assert hasattr(campaign_mod, "bind_campaign_egress_allowlist")
    assert "EGRESS_ALLOWLIST_BOUNDED" in EXPECTED_PROBES
    assert "EGRESS_DEFAULT_DENY" in EXPECTED_PROBES
    assert "EGRESS_ALLOWLIST_BOUNDED" not in REFUSAL_CLASSES
    assert "EGRESS_DEFAULT_DENY" not in REFUSAL_CLASSES


def _gate_record(gate_id: str = "EGRESS_ALLOWLIST_ENFORCED") -> GateRecord:
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
        {"EGRESS_ALLOWLIST_ENFORCED": _gate_record()},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "EGRESS_ALLOWLIST_UNBOUND" not in findings_ok
    assert "MISSING_GATE:EGRESS_ALLOWLIST_ENFORCED" not in findings_ok
    import inspect
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    assert "bind_campaign_egress_allowlist" in source


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
    assert b"EGRESS_ALLOWLIST_ENFORCED" in first
    assert b"MISSING_GATE:EGRESS_ALLOWLIST_ENFORCED" in first
    assert b"EGRESS_ALLOWLIST_UNBOUND" not in first
    assert json.loads(first)["launch_receipt"]["finding_ids"]
    assert campaign_main(argv) == 0
    assert output.read_bytes() == first


def test_package_host_map_carries_od012_inventory() -> None:
    loaded = json.loads(PACKAGE_FIXTURES.joinpath(HOST_MAP_NAME).read_bytes())
    assert loaded == FIXTURE_HOST_MAP
    assert inventory_digest().startswith("sha256:")
    assert set(loaded.values()) == set(DESTINATION_INVENTORY)
