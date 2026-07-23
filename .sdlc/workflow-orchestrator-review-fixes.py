from __future__ import annotations

from pathlib import Path

SOURCE = Path("scripts/sdlc/workflow_orchestrator.py")
TEST = Path("newsroom/tests/test_sdlc_workflow_orchestrator.py")

source = SOURCE.read_text(encoding="utf-8")
old_constant = '''_MAX_JSON_BYTES = 64 * 1024 * 1024
'''
new_constant = '''_MAX_JSON_BYTES = 64 * 1024 * 1024
_GITHUB_REQUEST_TIMEOUT_SECONDS = 5.0
'''
if source.count(old_constant) != 1:
    raise SystemExit("request timeout constant mismatch")
source = source.replace(old_constant, new_constant)

old_client = '''            client = GitHubActionsClient.from_environment()
'''
new_client = '''            client = GitHubActionsClient.from_environment(
                timeout_seconds=_GITHUB_REQUEST_TIMEOUT_SECONDS
            )
'''
if source.count(old_client) != 1:
    raise SystemExit("client timeout replacement mismatch")
source = source.replace(old_client, new_client)

old_validation = '''        normalized = validate_collection(collection, contract=contract)
        _private_write(target / "collection.json", normalized)
        return normalized
'''
new_validation = '''        try:
            normalized = validate_collection(collection, contract=contract)
        except (
            WorkflowOrchestratorError,
            WorkflowEvidenceError,
            ShadowLaneError,
            ArtifactProvenanceError,
        ):
            normalized = validate_collection(
                _collection_value(
                    context=context,
                    event=None,
                    core=None,
                    service=None,
                    status="ERROR",
                    failure_result="EVIDENCE_MISMATCH",
                    failure_code="collection-validation",
                ),
                contract=None,
            )
        _private_write(target / "collection.json", normalized)
        return normalized
'''
if source.count(old_validation) != 1:
    raise SystemExit("collection validation replacement mismatch")
source = source.replace(old_validation, new_validation)

old_contract = '''    except ContractError:
        decision = failure_shadow_decision(
'''
new_contract = '''    except (ContractError, OSError, UnicodeError):
        decision = failure_shadow_decision(
'''
if source.count(old_contract) != 1:
    raise SystemExit("contract failure replacement mismatch")
source = source.replace(old_contract, new_contract)

old_child = '''    output = Path(output_path)
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or not output.parent.is_dir()
        or not output.parent.resolve().is_relative_to(root)
    ):
        raise WorkflowOrchestratorError("child_output")
'''
new_child = '''    output = Path(output_path)
    if not output.is_absolute():
        raise WorkflowOrchestratorError("child_output")
    try:
        relative_output = output.relative_to(root)
        output = _safe_target(root, relative_output, suffix=".json")
    except (ValueError, WorkflowOrchestratorError) as exc:
        raise WorkflowOrchestratorError("child_output") from exc
'''
if source.count(old_child) != 1:
    raise SystemExit("child output replacement mismatch")
source = source.replace(old_child, new_child)
SOURCE.write_text(source, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
replacements = (
    (
        '''        classmethod(lambda cls: client),
''',
        '''        classmethod(lambda cls, **kwargs: client),
''',
        "client fixture replacement mismatch",
    ),
    (
        '''        classmethod(lambda cls: _FakeClient()),
''',
        '''        classmethod(lambda cls, **kwargs: _FakeClient()),
''',
        "transport fixture replacement mismatch",
    ),
)
for old, new, failure in replacements:
    if tests.count(old) != 1:
        raise SystemExit(failure)
    tests = tests.replace(old, new)
marker = "def test_collection_uses_bounded_github_request_timeout("
if marker in tests:
    raise SystemExit("review-fix tests already present")
tests += '''


def test_collection_uses_bounded_github_request_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = {}
    client = _FakeClient()
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator.GitHubActionsClient,
        "from_environment",
        classmethod(
            lambda cls, **kwargs: observed.update(kwargs) or client
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_artifact_bundle",
        lambda **_kwargs: (_ for _ in ()).throw(GitHubTransportError("missing")),
    )

    orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert observed == {"timeout_seconds": 5.0}


def test_collection_validation_failure_becomes_typed_error_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _FakeLane("core", False)
    client = _FakeClient()
    monkeypatch.setattr(orchestrator, "context_from_environment", lambda _root: _context())
    monkeypatch.setattr(orchestrator, "derive_workflow_event", lambda _root: _event())
    monkeypatch.setattr(orchestrator, "load_contract", lambda _root: object())
    monkeypatch.setattr(
        orchestrator.GitHubActionsClient,
        "from_environment",
        classmethod(lambda cls, **kwargs: client),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_artifact_bundle",
        lambda **kwargs: Path(kwargs["output_parent"], kwargs["output_name"]).mkdir(),
    )
    monkeypatch.setattr(orchestrator, "verify_shadow_lane", lambda **_kwargs: core)
    real_validate = orchestrator.validate_collection
    calls = 0

    def validate(value, *, contract):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise orchestrator.WorkflowOrchestratorError("collection_evidence")
        return real_validate(value, contract=contract)

    monkeypatch.setattr(orchestrator, "validate_collection", validate)

    value = orchestrator.collect_decision_inputs(
        repo_root=tmp_path, output_directory="decision-input"
    )

    assert value["status"] == "ERROR"
    assert value["failure_code"] == "collection-validation"
    assert (tmp_path / "decision-input/context.json").is_file()
    assert (tmp_path / "decision-input/collection.json").is_file()


def test_contract_filesystem_failure_after_context_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "context.json", _context().as_dict())
    _write(tmp_path / "collection.json", {"ignored": True})
    monkeypatch.setattr(
        orchestrator,
        "load_contract",
        lambda _root: (_ for _ in ()).throw(OSError("unavailable")),
    )

    decision = orchestrator.run_bounded_decision(
        repo_root=tmp_path,
        context_path="context.json",
        collection_path="collection.json",
        output_path="decision.json",
    )

    assert decision.result == "EVIDENCE_MISMATCH"
    assert decision.result_reason == "EVIDENCE_MISMATCH:decision:contract-load"


def test_decision_child_rejects_symlinked_output_parent(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(orchestrator.WorkflowOrchestratorError, match="child_output"):
        orchestrator._decision_child(
            repo_root=tmp_path,
            context_path="context.json",
            collection_path="collection.json",
            output_path=linked / "decision.json",
        )
'''
TEST.write_text(tests, encoding="utf-8")
