import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from newsroom.increment9.baseline_credential_scopes import (
    GATE_ID,
    PACKAGE_FIXTURES,
    REFUSAL_CLASSES,
    SCHEMA_VERSION,
    QualificationError,
    assess,
    default_probe,
    evidence_json,
)
from newsroom.increment9.credential_scopes import (
    BOUNDARY_ONLY_CLASSES,
    CREDENTIAL_SCOPE,
    DETERMINISTIC_BOUNDARY,
    FIXTURE_PRINCIPAL_DIGEST,
    FIXTURE_PRODUCTION_NAMES,
    MODEL_FAMILY_LOGIN,
    NAMESAKE_CAMPAIGN_CLASSES,
    CredentialRef,
    CredentialScopeError,
    bind_campaign_credential_classes,
    bind_inventory,
    bound_resolver,
    credential_ref_from_primitive,
    fixture_credential_refs,
    inventory_digest,
    resolve,
)
from newsroom.increment9.deployment import (
    EXPECTED_CREDENTIAL_CLASSES,
    EXPECTED_PROBES,
    PROHIBITED_CREDENTIAL_CLASSES,
)

_SPEC = spec_from_file_location(
    "increment9q5_baseline_credential_scopes",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "increment9q5_baseline_credential_scopes.py",
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


def _inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(f"refusal:{rc}\n".encode())
    return root


def _authorised_inventory(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    for rc in REFUSAL_CLASSES:
        (root / rc).write_bytes(PACKAGE_FIXTURES.joinpath(rc).read_bytes())
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
    evidence = assess(_authorised_inventory(tmp_path))
    assert evidence.gate_id == GATE_ID
    assert evidence.status == "PASS"
    assert evidence.refusals_engaged == len(REFUSAL_CLASSES)
    assert tuple(item.refusal_class for item in evidence.refusals) == REFUSAL_CLASSES
    assert all(item.before_digest == item.after_digest for item in evidence.refusals)
    assert all(item.count == 1 and item.engaged for item in evidence.refusals)
    assert evidence.principal_digest == FIXTURE_PRINCIPAL_DIGEST
    assert evidence.inventory_digest == inventory_digest()
    payload = evidence_json(evidence)
    assert SCHEMA_VERSION.encode() in payload
    assert b'"refusals_engaged":10' in payload
    assert b'"gate_id":"BASELINE_CREDENTIAL_SCOPES"' in payload
    assert evidence.principal_digest.encode() in payload
    assert evidence.inventory_digest.encode() in payload
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
        if rc == "UNKNOWN_CREDENTIAL_CLASS":
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
    assert b'"gate_id":"BASELINE_CREDENTIAL_SCOPES"' in raw


def test_deterministic_boundary_resolves_seven_permitted_classes() -> None:
    for cls in EXPECTED_CREDENTIAL_CLASSES:
        ref = resolve(FIXTURE_PRINCIPAL_DIGEST, DETERMINISTIC_BOUNDARY, cls)
        assert isinstance(ref, CredentialRef)
        assert ref.credential_class == cls
        assert ref.scope == CREDENTIAL_SCOPE
        assert set(ref.primitive()) == {"credential_class", "digest", "scope"}


def test_model_family_handles_resolve_only_own_login_class() -> None:
    for handle, own in MODEL_FAMILY_LOGIN.items():
        ref = resolve(FIXTURE_PRINCIPAL_DIGEST, handle, own)
        assert ref.credential_class == own
        for other in MODEL_FAMILY_LOGIN.values():
            if other == own:
                continue
            with pytest.raises(CredentialScopeError):
                resolve(FIXTURE_PRINCIPAL_DIGEST, handle, other)
        for cls in BOUNDARY_ONLY_CLASSES:
            with pytest.raises(CredentialScopeError):
                resolve(FIXTURE_PRINCIPAL_DIGEST, handle, cls)


def test_publication_and_production_names_are_refused_for_every_handle() -> None:
    handles = (DETERMINISTIC_BOUNDARY, *MODEL_FAMILY_LOGIN)
    for handle in handles:
        with pytest.raises(CredentialScopeError, match="publication"):
            resolve(FIXTURE_PRINCIPAL_DIGEST, handle, "PUBLICATION_TARGET_ADAPTER")
        for name in FIXTURE_PRODUCTION_NAMES:
            with pytest.raises(CredentialScopeError, match="production"):
                resolve(FIXTURE_PRINCIPAL_DIGEST, handle, name)


def test_unknown_class_and_malformed_requests_are_refused() -> None:
    with pytest.raises(CredentialScopeError, match="unknown"):
        resolve(FIXTURE_PRINCIPAL_DIGEST, DETERMINISTIC_BOUNDARY, "NOT_A_CREDENTIAL_CLASS")
    with pytest.raises(CredentialScopeError, match="malformed"):
        resolve(FIXTURE_PRINCIPAL_DIGEST, "", "OPENAI_CODEX_LOGIN")
    with pytest.raises(CredentialScopeError, match="malformed"):
        resolve(FIXTURE_PRINCIPAL_DIGEST, "H" * 257, "OPENAI_CODEX_LOGIN")
    with pytest.raises(CredentialScopeError, match="malformed"):
        resolve(FIXTURE_PRINCIPAL_DIGEST, "not a token", "OPENAI_CODEX_LOGIN")


def test_principal_mismatch_is_refused() -> None:
    with pytest.raises(CredentialScopeError, match="principal"):
        resolve("sha256:" + "0" * 64, DETERMINISTIC_BOUNDARY, "OPENAI_CODEX_LOGIN")


def test_secret_bytes_cannot_enter_a_credential_ref() -> None:
    digest = fixture_credential_refs()[0].digest
    with pytest.raises(CredentialScopeError, match="secret"):
        credential_ref_from_primitive(
            {
                "credential_class": "OPENAI_CODEX_LOGIN",
                "digest": digest,
                "scope": CREDENTIAL_SCOPE,
                "secret": "sk-fixture-not-a-real-secret",
            }
        )
    ref = resolve(
        FIXTURE_PRINCIPAL_DIGEST, DETERMINISTIC_BOUNDARY, "OPENAI_CODEX_LOGIN"
    )
    assert "secret" not in ref.primitive()


def test_inventory_bind_matches_od012_and_deployment_contracts() -> None:
    bind_inventory(EXPECTED_CREDENTIAL_CLASSES, PROHIBITED_CREDENTIAL_CLASSES)
    with pytest.raises(CredentialScopeError):
        bind_inventory(EXPECTED_CREDENTIAL_CLASSES[:-1], PROHIBITED_CREDENTIAL_CLASSES)
    with pytest.raises(CredentialScopeError):
        bind_inventory(
            tuple(sorted((*EXPECTED_CREDENTIAL_CLASSES, "EXTRA_CREDENTIAL_CLASS"))),
            PROHIBITED_CREDENTIAL_CLASSES,
        )
    with pytest.raises(CredentialScopeError):
        bind_inventory(
            (
                EXPECTED_CREDENTIAL_CLASSES[1],
                EXPECTED_CREDENTIAL_CLASSES[0],
                *EXPECTED_CREDENTIAL_CLASSES[2:],
            ),
            PROHIBITED_CREDENTIAL_CLASSES,
        )
    with pytest.raises(CredentialScopeError):
        bind_inventory(
            (EXPECTED_CREDENTIAL_CLASSES[0], *EXPECTED_CREDENTIAL_CLASSES),
            PROHIBITED_CREDENTIAL_CLASSES,
        )
    with pytest.raises(CredentialScopeError):
        bind_inventory(EXPECTED_CREDENTIAL_CLASSES, ("NEO4J_SHADOW_WRITER",))
    with pytest.raises(CredentialScopeError):
        bind_inventory(("ANTHROPIC_AGENT_SDK",), ("ANTHROPIC_AGENT_SDK",))


def test_campaign_namesake_three_class_list_cannot_pass() -> None:
    with pytest.raises(CredentialScopeError):
        bind_campaign_credential_classes(NAMESAKE_CAMPAIGN_CLASSES)
    bind_campaign_credential_classes(EXPECTED_CREDENTIAL_CLASSES)
    import scripts.increment9_shadow_campaign as campaign_mod

    assert not hasattr(campaign_mod, "BASELINE_CREDENTIAL_CLASSES")
    assert "PRODUCTION_CREDENTIAL_DENIED" in EXPECTED_PROBES
    assert "CREDENTIAL_VALUES_ABSENT" in EXPECTED_PROBES
    assert "PRODUCTION_CREDENTIAL_DENIED" not in REFUSAL_CLASSES
    assert "CREDENTIAL_VALUES_ABSENT" not in REFUSAL_CLASSES


def _gate_record(classes: tuple[str, ...]) -> GateRecord:
    return GateRecord(
        gate_id="BASELINE_CREDENTIAL_SCOPES",
        observed_at="2026-08-16T00:00:00.000000Z",
        expires_at="2026-08-17T00:00:00.000000Z",
        exact_main_sha="a" * 40,
        exact_main_tree="b" * 40,
        subject_digest="sha256:" + "c" * 64,
        evidence_digest="sha256:" + "d" * 64,
        issuer_id="fixture",
        status=GateStatus.PASS,
        credential_classes=classes,
    )


def test_campaign_gate_check_uses_od012_inventory_not_three_class_list() -> None:
    findings_ok = _gate_findings(
        {"BASELINE_CREDENTIAL_SCOPES": _gate_record(EXPECTED_CREDENTIAL_CLASSES)},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "BASELINE_CREDENTIAL_CLASSES_DIFFER" not in findings_ok
    findings_namesake = _gate_findings(
        {"BASELINE_CREDENTIAL_SCOPES": _gate_record(NAMESAKE_CAMPAIGN_CLASSES)},
        head="a" * 40,
        tree="b" * 40,
        observed_at="2026-08-16T12:00:00.000000Z",
    )
    assert "BASELINE_CREDENTIAL_CLASSES_DIFFER" in findings_namesake


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
    assert b"BASELINE_CREDENTIAL_SCOPES" in first
    assert campaign_main(argv) == 0
    assert output.read_bytes() == first


def test_bound_resolver_store_is_metadata_only() -> None:
    resolver = bound_resolver()
    assert resolver.bound_principal_digest == FIXTURE_PRINCIPAL_DIGEST
    assert tuple(item.credential_class for item in resolver.store) == EXPECTED_CREDENTIAL_CLASSES
    for item in resolver.store:
        assert set(item.primitive()) == {"credential_class", "digest", "scope"}
