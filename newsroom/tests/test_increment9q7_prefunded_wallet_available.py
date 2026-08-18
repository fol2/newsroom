import json
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.increment9.comparator import (
    AdmissionDisposition,
    ApprovedPhaseAdmissionController,
    BudgetCaps,
    ComparatorContractError,
    ResourceReservation,
    StopReason,
)
from newsroom.increment9.controller import ControllerError, LedgerKind
from newsroom.increment9.epoch import EpochAuthorityError
from newsroom.increment9.prefunded_wallet import (
    CAPACITY_GBP_MINOR_UNITS,
    CURRENCY,
    FIXTURE_WALLET,
    SPEND_METERED,
    SPEND_SUBSCRIPTION,
    PrefundedWalletError,
    bind_campaign_prefunded_wallet,
    bind_wallet,
    bound_wallet,
    budget_caps_digest,
    fixture_wallet,
    ledger_budget_reservation,
    refuse_namesake_satisfaction,
)
from newsroom.increment9.prefunded_wallet_available import (
    GATE_ID,
    PACKAGE_FIXTURES,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    WALLET_NAME,
    QualificationError,
    assess,
    default_probe,
    evidence_json,
)

_SPEC = spec_from_file_location(
    "increment9q7_prefunded_wallet_available",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "increment9q7_prefunded_wallet_available.py",
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


def _wallet_bytes() -> bytes:
    return PACKAGE_FIXTURES.joinpath(WALLET_NAME).read_bytes()


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    root.joinpath(WALLET_NAME).write_bytes(_wallet_bytes())
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


def test_assess_fails_closed_without_a_valid_wallet(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(PACKAGE_FIXTURES.joinpath(rc).read_bytes())
    with pytest.raises(QualificationError, match="wallet"):
        assess(root)
    with pytest.raises(QualificationError, match="wallet"):
        assess(root, wallet={})
    (root / WALLET_NAME).write_bytes(b"{")
    with pytest.raises(QualificationError, match="wallet"):
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
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES)
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.count == 1 and item.engaged for item in evidence.refusals)
    assert evidence.budget_caps_digest == budget_caps_digest()
    assert evidence.reservation_digest.startswith("sha256:")
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"refusals_engaged":11' in payload
    assert b'"gate_id":"PREFUNDED_WALLET_AVAILABLE"' in payload
    assert evidence.budget_caps_digest.encode() in payload
    assert b'"capacity_gbp_minor_units":25000' in payload
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
        if rc == "CAPACITY_MISMATCH":
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
    assert b'"gate_id":"PREFUNDED_WALLET_AVAILABLE"' in raw
    assert budget_caps_digest().encode() in raw


def test_wallet_binds_od011_capacity_and_refuses_mismatch() -> None:
    wallet = bind_wallet(FIXTURE_WALLET)
    assert wallet.capacity == CAPACITY_GBP_MINOR_UNITS == 25_000
    assert wallet.available == CAPACITY_GBP_MINOR_UNITS
    assert wallet.budget_caps_digest == BudgetCaps().canonical_digest
    assert FIXTURE_WALLET["currency"] == CURRENCY
    with pytest.raises(ComparatorContractError):
        BudgetCaps(gross_monetary_gbp_minor_units=24_999)
    with pytest.raises(PrefundedWalletError, match="capacity"):
        bind_wallet(fixture_wallet(capacity_gbp_minor_units=24_999))


def test_currency_replenishment_and_transfer_are_refused() -> None:
    with pytest.raises(PrefundedWalletError, match="currency"):
        bind_wallet(fixture_wallet(currency="USD"))
    with pytest.raises(PrefundedWalletError, match="currency"):
        bound_wallet().reserve(
            reservation_id="fx",
            amount_gbp_minor_units=1.5,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    with pytest.raises(PrefundedWalletError, match="replenishment"):
        bound_wallet().replenish(1)
    with pytest.raises(ComparatorContractError):
        BudgetCaps(budget_transfer_allowed=True)
    with pytest.raises(PrefundedWalletError, match="transfer"):
        bind_wallet(fixture_wallet(budget_transfer_allowed=True))
    with pytest.raises(PrefundedWalletError, match="transfer"):
        bound_wallet().transfer(1, "other-wallet")


def test_reservation_before_spend_and_debit_rules() -> None:
    wallet = bound_wallet()
    reservation = wallet.reserve(
        reservation_id="r1",
        amount_gbp_minor_units=10,
        spend_class=SPEND_METERED,
        budget_rules_digest=budget_caps_digest(),
    )
    entry = ledger_budget_reservation(reservation.digest)
    assert entry.kind is LedgerKind.BUDGET_RESERVATION
    assert entry.payload_digest == reservation.digest
    assert wallet.available == CAPACITY_GBP_MINOR_UNITS - 10
    debit = wallet.debit(
        reservation_id="r1",
        amount_gbp_minor_units=4,
        spend_class=SPEND_METERED,
        budget_rules_digest=budget_caps_digest(),
    )
    assert debit.reservation_digest == reservation.digest
    with pytest.raises(PrefundedWalletError, match="remaining"):
        wallet.reserve(
            reservation_id="over",
            amount_gbp_minor_units=CAPACITY_GBP_MINOR_UNITS,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    with pytest.raises(PrefundedWalletError, match="Budget Reservation"):
        wallet.debit(
            reservation_id="absent",
            amount_gbp_minor_units=1,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    with pytest.raises(PrefundedWalletError, match="exceeds"):
        wallet.debit(
            reservation_id="r1",
            amount_gbp_minor_units=7,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )


def test_subscription_class_is_ledgered_never_debited() -> None:
    wallet = bound_wallet()
    with pytest.raises(PrefundedWalletError, match="subscription"):
        wallet.debit(
            reservation_id="r1",
            amount_gbp_minor_units=1,
            spend_class=SPEND_SUBSCRIPTION,
            budget_rules_digest=budget_caps_digest(),
        )
    assert wallet.available == CAPACITY_GBP_MINOR_UNITS
    assert any(item.kind == "SUBSCRIPTION" for item in wallet.ledger)


def test_budget_rules_digest_drift_and_malformed_requests_are_refused() -> None:
    wallet = bound_wallet()
    with pytest.raises(PrefundedWalletError, match="digest"):
        wallet.reserve(
            reservation_id="drift",
            amount_gbp_minor_units=1,
            spend_class=SPEND_METERED,
            budget_rules_digest="sha256:" + "0" * 64,
        )
    with pytest.raises(PrefundedWalletError, match="malformed"):
        wallet.reserve(
            reservation_id="neg",
            amount_gbp_minor_units=-1,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    with pytest.raises(PrefundedWalletError, match="malformed"):
        wallet.reserve(
            reservation_id="zero",
            amount_gbp_minor_units=0,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    with pytest.raises(PrefundedWalletError, match="malformed"):
        wallet.reserve(
            reservation_id="cls",
            amount_gbp_minor_units=1,
            spend_class="NOT_A_SPEND_CLASS",
            budget_rules_digest=budget_caps_digest(),
        )
    with pytest.raises(PrefundedWalletError, match="malformed"):
        wallet.reserve(
            reservation_id="H" * 257,
            amount_gbp_minor_units=1,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )


def test_over_budget_reservation_is_api_budget_on_comparator() -> None:
    from .test_increment9c1_comparator_contracts import _campaign, _request

    plan, epoch, manifest, cohort, campaign = _campaign()
    assert epoch.budget_rules_digest == plan.budgets.canonical_digest
    controller = ApprovedPhaseAdmissionController(plan, campaign)
    receipt = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            reservation=ResourceReservation(gross_monetary_gbp_minor_units=25_001),
        ),
    )
    assert receipt.disposition is AdmissionDisposition.EARLY_STOP
    assert receipt.stop_reason is StopReason.API_BUDGET


def test_campaign_namesake_list_membership_cannot_pass() -> None:
    with pytest.raises(PrefundedWalletError, match="RUNTIME_GATES"):
        refuse_namesake_satisfaction(RUNTIME_GATES)
    bind_campaign_prefunded_wallet()
    import scripts.increment9_shadow_campaign as campaign_mod

    assert hasattr(campaign_mod, "bind_campaign_prefunded_wallet")
    assert "PREFUNDED_WALLET_AVAILABLE" in RUNTIME_GATES


def _gate_record(gate_id: str = "PREFUNDED_WALLET_AVAILABLE") -> GateRecord:
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


def test_campaign_gate_check_uses_wallet_not_a_bare_gate_name() -> None:
    findings_ok = _gate_findings(
        {"PREFUNDED_WALLET_AVAILABLE": _gate_record()},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "PREFUNDED_WALLET_UNBOUND" not in findings_ok
    assert "MISSING_GATE:PREFUNDED_WALLET_AVAILABLE" not in findings_ok
    import inspect
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    assert "bind_campaign_prefunded_wallet" in source


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
    assert b"PREFUNDED_WALLET_AVAILABLE" in first
    assert b"MISSING_GATE:PREFUNDED_WALLET_AVAILABLE" in first
    assert b"PREFUNDED_WALLET_UNBOUND" not in first
    assert json.loads(first)["launch_receipt"]["finding_ids"]
    assert campaign_main(argv) == 0
    assert output.read_bytes() == first


def test_package_wallet_carries_od011_capacity() -> None:
    loaded = json.loads(PACKAGE_FIXTURES.joinpath(WALLET_NAME).read_bytes())
    assert loaded == FIXTURE_WALLET
    assert loaded["capacity_gbp_minor_units"] == CAPACITY_GBP_MINOR_UNITS
    assert loaded["budget_transfer_allowed"] is False


def test_epoch_budget_rules_digest_binds_budget_caps() -> None:
    from newsroom.increment9.epoch import EvaluationEpoch
    from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

    digest = budget_caps_digest()
    epoch = EvaluationEpoch(
        epoch_id="epoch-9q7-test",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        shadow_scope_digest="sha256:" + "6" * 64,
        source_portfolio_digest="sha256:" + "2" * 64,
        prospective_universe_digest="sha256:" + "1" * 64,
        slice_rules_digest="sha256:" + "7" * 64,
        thresholds_digest="sha256:" + "8" * 64,
        comparator_rules_digest="sha256:" + "a" * 64,
        reviewer_rules_digest="sha256:" + "9" * 64,
        budget_rules_digest=digest,
        rights_rules_digest="sha256:" + "3" * 64,
        opened_at="2026-08-16T00:00:00.000000Z",
        cutoff_at="2026-08-16T00:00:00.000000Z",
        closes_at="2026-09-13T00:00:00.000000Z",
    )
    assert epoch.budget_rules_digest == digest == BudgetCaps().canonical_digest
    with pytest.raises(EpochAuthorityError):
        EvaluationEpoch(
            epoch_id="epoch-9q7-bad",
            plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
            shadow_scope_digest="sha256:" + "6" * 64,
            source_portfolio_digest="sha256:" + "2" * 64,
            prospective_universe_digest="sha256:" + "1" * 64,
            slice_rules_digest="sha256:" + "7" * 64,
            thresholds_digest="sha256:" + "8" * 64,
            comparator_rules_digest="sha256:" + "a" * 64,
            reviewer_rules_digest="sha256:" + "9" * 64,
            budget_rules_digest="not-a-digest",
            rights_rules_digest="sha256:" + "3" * 64,
            opened_at="2026-08-16T00:00:00.000000Z",
            cutoff_at="2026-08-16T00:00:00.000000Z",
            closes_at="2026-09-13T00:00:00.000000Z",
        )
    with pytest.raises(ControllerError):
        ledger_budget_reservation("not-a-digest")
