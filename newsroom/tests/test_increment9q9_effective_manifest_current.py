import inspect
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.controller import ControllerError, ControllerQualificationPlan
from newsroom.increment9.effective_manifest_current import (
    GATE_ID,
    IDENTITY_KEYS,
    INVENTORY_NAME,
    PACKAGE_FIXTURES,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    QualificationError,
    assess,
    bind_controller,
    bind_inventory,
    bind_manifest,
    default_probe,
    evidence_json,
    fixture_identity_digests,
    fixture_inventory,
    refuse_namesake_satisfaction,
)
from newsroom.increment9.epoch import (
    EFFECTIVE_MANIFEST_IDENTITY_KEYS,
    EffectiveManifest,
    EpochAuthorityError,
)

_SPEC = spec_from_file_location(
    "increment9q9_effective_manifest_current",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "increment9q9_effective_manifest_current.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CLI = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)

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
        assess(root, identity_inventory={})
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
    first = bind_manifest(fixture_inventory())
    second = bind_manifest(fixture_inventory())
    assert first.canonical_digest == second.canonical_digest == evidence.manifest_digest
    assert evidence.gate_id == GATE_ID == "EFFECTIVE_MANIFEST_CURRENT"
    assert evidence.status == "PASS"
    assert evidence.drift_refusals == 16
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES) == 5
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.engaged for item in evidence.refusals)
    counts = {item.refusal_class: item.count for item in evidence.refusals}
    assert counts == {
        "DRIFT": 16,
        "UNRESOLVED": 1,
        "MALFORMED": 3,
        "SUPERSEDED": 1,
        "ANTI_NAMESAKE": 1,
    }
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"drift_refusals":16' in payload
    assert b'"unresolved_refusals":1' in payload
    assert b'"malformed_refusals":3' in payload
    assert b'"superseded_refusals":1' in payload
    assert b'"deterministic_bind":true' in payload
    assert b'"gate_id":"EFFECTIVE_MANIFEST_CURRENT"' in payload
    assert evidence.manifest_digest.encode() in payload
    assert b"exact_main_sha" not in payload
    assert b"campaign-gate" not in payload
    assert b"qualification-evidence" in payload
    assert b"expires_at" not in payload


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
        if rc == "DRIFT":
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
    assert evidence.drift_refusals == 16
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
    assert b'"drift_refusals":16' in raw
    assert b"exact_main_sha" not in raw
    assert b'"gate_id":"EFFECTIVE_MANIFEST_CURRENT"' in raw


def test_sixteen_identity_keys_match_the_epoch_contract() -> None:
    assert IDENTITY_KEYS == tuple(sorted(EFFECTIVE_MANIFEST_IDENTITY_KEYS))
    assert IDENTITY_KEYS == (
        "candidate",
        "code",
        "config",
        "embedding",
        "handoff",
        "image",
        "index",
        "model",
        "ontology",
        "operational_profile",
        "projector",
        "prompt",
        "provider",
        "retrieval",
        "source",
        "triage",
    )
    assert len(fixture_identity_digests()) == 16
    assert set(fixture_identity_digests()) == set(EFFECTIVE_MANIFEST_IDENTITY_KEYS)


def test_deterministic_bind_is_content_addressed() -> None:
    first = bind_manifest(fixture_inventory())
    second = bind_manifest(fixture_inventory())
    assert first.canonical_digest == second.canonical_digest
    plan = bind_controller(first)
    again = bind_controller(second)
    assert plan.effective_manifest_digest == first.canonical_digest
    assert again.canonical_digest == plan.canonical_digest
    assert plan.effective_manifest_digest == again.effective_manifest_digest


def test_effective_manifest_v1_has_no_expiry_field() -> None:
    manifest = bind_manifest(fixture_inventory())
    assert "expires_at" not in EffectiveManifest.__dataclass_fields__
    assert "expiry" not in EffectiveManifest.__dataclass_fields__
    assert "expires_at" not in manifest.primitive()
    assert manifest.schema_version == "newsroom.increment9.effective-manifest.v1"


def test_drift_unresolved_malformed_and_superseded_are_refused() -> None:
    from newsroom.increment9.effective_manifest_current import _controller_kwargs

    bound = bind_manifest(fixture_inventory())
    kwargs = _controller_kwargs(bound)
    for key in IDENTITY_KEYS:
        drifted = dict(bound.identity_digests)
        drifted[key] = "sha256:" + "f" * 64
        presented = EffectiveManifest(
            manifest_id="effective-manifest-9q9-drift-test",
            identity_digests=drifted,
            observed_at=bound.observed_at,
            identity_resolved=True,
        )
        with pytest.raises(ControllerError, match="Manifest Cohort"):
            ControllerQualificationPlan.build(
                **{**kwargs, "effective_manifest": presented}
            )
    unresolved = EffectiveManifest(
        manifest_id=bound.manifest_id,
        identity_digests=dict(bound.identity_digests),
        observed_at=bound.observed_at,
        identity_resolved=False,
    )
    assert unresolved.decision_bearing is False
    with pytest.raises(ControllerError, match="resolved"):
        ControllerQualificationPlan.build(**_controller_kwargs(bound, unresolved))
    missing = dict(bound.identity_digests)
    del missing["candidate"]
    with pytest.raises(EpochAuthorityError, match="identity"):
        EffectiveManifest(
            manifest_id=bound.manifest_id,
            identity_digests=missing,
            observed_at=bound.observed_at,
            identity_resolved=True,
        )
    extra = dict(bound.identity_digests)
    extra["extra"] = "sha256:" + "0" * 64
    with pytest.raises(EpochAuthorityError, match="identity"):
        EffectiveManifest(
            manifest_id=bound.manifest_id,
            identity_digests=extra,
            observed_at=bound.observed_at,
            identity_resolved=True,
        )
    malformed = dict(bound.identity_digests)
    malformed["candidate"] = "not-a-digest"
    with pytest.raises(EpochAuthorityError):
        EffectiveManifest(
            manifest_id=bound.manifest_id,
            identity_digests=malformed,
            observed_at=bound.observed_at,
            identity_resolved=True,
        )
    superseded = EffectiveManifest(
        manifest_id="effective-manifest-9q9-superseded-test",
        identity_digests={key: "sha256:" + "e" * 64 for key in IDENTITY_KEYS},
        observed_at=bound.observed_at,
        identity_resolved=True,
    )
    assert superseded.canonical_digest != bound.canonical_digest
    with pytest.raises(ControllerError, match="Manifest Cohort"):
        ControllerQualificationPlan.build(**_controller_kwargs(bound, superseded))


def test_campaign_namesake_list_membership_cannot_pass() -> None:
    with pytest.raises(QualificationError, match="RUNTIME_GATES"):
        refuse_namesake_satisfaction(RUNTIME_GATES)
    bind_controller(bind_manifest(fixture_inventory()))
    import scripts.increment9_shadow_campaign as campaign_mod

    source = inspect.getsource(campaign_mod._gate_findings)
    assert GATE_ID in RUNTIME_GATES
    assert "bind_campaign_effective" not in source
    assert "EffectiveManifest" not in source
    findings = _gate_findings(
        {},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "MISSING_GATE:EFFECTIVE_MANIFEST_CURRENT" in findings


def test_package_inventory_matches_fixture_inventory() -> None:
    loaded = json.loads(PACKAGE_FIXTURES.joinpath(INVENTORY_NAME).read_bytes())
    assert canonical_json_bytes(loaded) == canonical_json_bytes(fixture_inventory())
    bind_inventory(loaded)
    first = bind_manifest(loaded)
    second = bind_manifest(loaded)
    assert first.canonical_digest == second.canonical_digest
    assert len(first.identity_digests) == 16
    assert "expires_at" not in loaded
