import inspect
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.deployment import EXPECTED_EGRESS_DESTINATIONS
from newsroom.increment9.epoch import (
    EpochAuthorityError,
    EvaluationEpoch,
    ManifestCohort,
    RunKind,
    ShadowRun,
    initialise_shadow_epoch_authority,
)
from newsroom.increment9.prospective_run_authority import (
    GATE_ID,
    INVENTORY_NAME,
    PACKAGE_FIXTURES,
    PROBE_COUNTS,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    QualificationError,
    RunAuthorityPresentation,
    assess,
    assess_run_authority,
    bind_inventory,
    default_probe,
    evidence_json,
    fixture_inventory,
    fixture_run,
    persist_authorised_chain,
    refuse_namesake_satisfaction,
    resolver_from_store,
)

_SPEC = spec_from_file_location(
    "increment9q10_prospective_run_authority",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "increment9q10_prospective_run_authority.py",
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

from scripts.increment9_shadow_campaign import RUNTIME_GATES, _gate_findings


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
        assess(root, chain_inventory={})
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
    isolated = persist_authorised_chain()
    first = assess_run_authority(isolated.run.run_id, resolver=isolated.resolver)
    second = assess_run_authority(isolated.run.run_id, resolver=isolated.resolver)
    assert first == second
    assert first.status == "PASS"
    assert first.epoch_digest == evidence.epoch_digest == isolated.epoch.canonical_digest
    assert first.cohort_digest == evidence.cohort_digest
    assert first.manifest_digest == evidence.manifest_digest
    assert first.exposure_contract_digest == evidence.exposure_contract_digest
    assert first.budget_rules_digest == evidence.budget_rules_digest
    assert evidence.gate_id == GATE_ID == "PROSPECTIVE_RUN_AUTHORITY"
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES) == 9
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.engaged for item in evidence.refusals)
    counts = {item.refusal_class: item.count for item in evidence.refusals}
    assert counts == PROBE_COUNTS
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"deterministic_pass":true' in payload
    assert b'"gate_id":"PROSPECTIVE_RUN_AUTHORITY"' in payload
    assert evidence.epoch_digest.encode() in payload
    assert evidence.cohort_digest.encode() in payload
    assert evidence.manifest_digest.encode() in payload
    assert evidence.exposure_contract_digest.encode() in payload
    assert evidence.budget_rules_digest.encode() in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload
    assert b"expires_at" not in payload
    assert b'"destination"' not in payload
    assert b"stop_rules" not in payload


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
        if rc == "NO_AUTHORITY":
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
    assert _CLI.main(["assess", "--inventory", str(tmp_path / "missing")]) == 2
    output = tmp_path / "evidence.json"
    assert _CLI.main(["assess", "--output", str(output)]) == 0
    raw = output.read_bytes()
    assert b'"status":"PASS"' in raw
    assert b'"deterministic_pass":true' in raw
    assert b"exact_main_sha" not in raw
    assert b'"gate_id":"PROSPECTIVE_RUN_AUTHORITY"' in raw
    assert _CLI.main(["assess", "--output", str(output)]) == 0
    assert output.read_bytes() == raw


def test_proving_store_cli_is_fail_closed_without_a_resolver() -> None:
    assert (
        _PROVING_CLI.main(["assess", "--run-id", "r1", "--attest-no-emergency-stop"])
        == 2
    )


def test_destination_is_bound_through_exposure_and_od012() -> None:
    isolated = persist_authorised_chain()
    assert isolated.cohort.exposure_contract_digest.startswith("sha256:")
    assert EXPECTED_EGRESS_DESTINATIONS == (
        "ANTHROPIC_AGENT_SDK",
        "APPROVED_REVIEW_RESEARCH",
        "GOOGLE_GEMINI_API",
        "INTEGRATED_NEWSROOM_TARGET",
        "OPENAI_CODEX",
        "OPENAI_EMBEDDINGS",
        "TEN_APPROVED_SOURCE_ENDPOINTS",
        "XAI_GROK_BUILD",
    )
    assert "destination" not in isolated.epoch.primitive()
    assert "stop_rules" not in isolated.epoch.primitive()
    assert "destination" not in isolated.cohort.primitive()
    assert "destination" not in isolated.run.primitive()


def test_nine_b1_helpers_persist_on_the_real_shadow_authority() -> None:
    import sqlite3

    from newsroom.tests.test_increment9b1_shadow_epoch import (
        _cohort,
        _epoch,
        _manifest,
        _run,
    )

    connection = sqlite3.connect(":memory:", isolation_level=None)
    authority = initialise_shadow_epoch_authority(connection)
    epoch = _epoch()
    manifest = _manifest()
    cohort = _cohort(epoch, manifest)
    run = _run(epoch, cohort, manifest)
    for record in (epoch, manifest, cohort, run):
        authority.append(record, epoch_id=epoch.epoch_id)
    resolver = resolver_from_store(authority, connection)
    first = assess_run_authority(run.run_id, resolver=resolver)
    second = assess_run_authority(run.run_id, resolver=resolver)
    assert first == second
    assert first.status == "PASS"
    assert first.epoch_digest == epoch.canonical_digest
    assert first.budget_rules_digest == epoch.budget_rules_digest
    assert first.exposure_contract_digest == cohort.exposure_contract_digest


def test_nine_refusal_classes_fail_closed_on_the_real_contracts() -> None:
    isolated = persist_authorised_chain()
    epoch, manifest, cohort, run = (
        isolated.epoch,
        isolated.manifest,
        isolated.cohort,
        isolated.run,
    )
    assert (
        assess_run_authority("ghost-run", resolver=isolated.resolver).status == "FAIL"
    )
    for value in ("", "a" * 257, "run id"):
        assert assess_run_authority(value, resolver=isolated.resolver).status == "FAIL"
    from dataclasses import replace

    stale = fixture_run(
        epoch, cohort, manifest, run_id="stale-run-9q10"
    )
    superseded = assess_run_authority(
        stale.run_id,
        resolver=lambda rid: (
            RunAuthorityPresentation(
                epoch.canonical_bytes,
                cohort.canonical_bytes,
                stale.canonical_bytes,
                "sha256:" + "f" * 64,
            )
            if rid == stale.run_id
            else None
        ),
    )
    assert superseded.status == "FAIL"
    mismatched = replace(run, epoch_digest="sha256:" + "e" * 64)
    assert (
        assess_run_authority(
            mismatched.run_id,
            resolver=lambda rid: RunAuthorityPresentation(
                epoch.canonical_bytes,
                cohort.canonical_bytes,
                mismatched.canonical_bytes,
                cohort.canonical_digest,
            ),
        ).status
        == "FAIL"
    )
    assert (
        assess_run_authority(
            run.run_id,
            resolver=lambda rid: RunAuthorityPresentation(
                None,
                cohort.canonical_bytes,
                run.canonical_bytes,
                cohort.canonical_digest,
            ),
        ).status
        == "FAIL"
    )
    early = replace(run, started_at="2041-12-31T23:59:59.000000Z")
    late = replace(run, started_at="2042-01-29T00:00:00.000000Z")
    for item in (early, late):
        assert (
            assess_run_authority(
                item.run_id,
                resolver=lambda rid, item=item: RunAuthorityPresentation(
                    epoch.canonical_bytes,
                    cohort.canonical_bytes,
                    item.canonical_bytes,
                    cohort.canonical_digest,
                ),
            ).status
            == "FAIL"
        )
    payload = json.loads(run.canonical_bytes)
    payload["prospective"] = False
    with pytest.raises(EpochAuthorityError, match="prospective"):
        ShadowRun.from_bytes(canonical_json_bytes(payload))
    replay = replace(
        run, run_kind=RunKind.REPLAY_QUALIFICATION, prospective=False
    )
    assert (
        assess_run_authority(
            replay.run_id,
            resolver=lambda rid: RunAuthorityPresentation(
                epoch.canonical_bytes,
                cohort.canonical_bytes,
                replay.canonical_bytes,
                cohort.canonical_digest,
            ),
        ).status
        == "FAIL"
    )
    drifted = replace(run, manifest_digest="sha256:" + "0" * 64)
    identity = replace(run, epoch_id="other-epoch-9q10")
    for item in (drifted, identity):
        assert (
            assess_run_authority(
                item.run_id,
                resolver=lambda rid, item=item: RunAuthorityPresentation(
                    epoch.canonical_bytes,
                    cohort.canonical_bytes,
                    item.canonical_bytes,
                    cohort.canonical_digest,
                ),
            ).status
            == "FAIL"
        )
    for raw in (
        RunAuthorityPresentation(
            b"{", cohort.canonical_bytes, run.canonical_bytes, cohort.canonical_digest
        ),
        RunAuthorityPresentation(
            epoch.canonical_bytes, b"{", run.canonical_bytes, cohort.canonical_digest
        ),
        RunAuthorityPresentation(
            epoch.canonical_bytes, cohort.canonical_bytes, b"{", cohort.canonical_digest
        ),
    ):
        assert (
            assess_run_authority(
                run.run_id, resolver=lambda rid, raw=raw: raw
            ).status
            == "FAIL"
        )
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    bare = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    assert next(g for g in bare if g.gate_id == GATE_ID).status is GateStatus.FAIL
    with pytest.raises(QualificationError, match="RUNTIME_GATES"):
        refuse_namesake_satisfaction(RUNTIME_GATES)


def test_campaign_namesake_list_membership_cannot_pass() -> None:
    with pytest.raises(QualificationError, match="RUNTIME_GATES"):
        refuse_namesake_satisfaction(RUNTIME_GATES)
    persist_authorised_chain()
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    module_source = inspect.getsource(campaign_mod)
    assert GATE_ID in RUNTIME_GATES
    assert "assess_run_authority" not in source
    assert "persist_authorised_chain" not in module_source
    assert "ShadowEpochAuthority" not in module_source
    findings = _gate_findings(
        {},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "MISSING_GATE:PROSPECTIVE_RUN_AUTHORITY" in findings


def test_package_inventory_matches_fixture_inventory() -> None:
    loaded = json.loads(PACKAGE_FIXTURES.joinpath(INVENTORY_NAME).read_bytes())
    assert canonical_json_bytes(loaded) == canonical_json_bytes(fixture_inventory())
    bound = bind_inventory(loaded)
    epoch = bound["epoch"]
    cohort = bound["cohort"]
    run = bound["run"]
    assert type(epoch) is EvaluationEpoch
    assert type(cohort) is ManifestCohort
    assert type(run) is ShadowRun
    assert run.prospective is True
    assert "expires_at" not in loaded
    assert "destination" not in loaded["epoch"]
    assert "stop_rules" not in loaded["epoch"]


def test_no_parallel_run_authority_module_was_added() -> None:
    root = Path(__file__).resolve().parents[1] / "increment9"
    assert not (root / "run_authority.py").exists()
    assert not (root / "qualification_run_authority.py").exists()
    assert (root / "prospective_run_authority.py").is_file()
