from pathlib import Path

import pytest

from newsroom.authority import ObjectAdmissionRequest
from newsroom.authority.persistence import AuthorityWriterBusy
from newsroom.control_plane.native_runtime import open_native_runtime
from newsroom.increment5.retrieval_context import RetrievalContextJournal
from newsroom.increment6.collision import (
    CurrentCollisionEffectEnforcer, TrustedCurrentCollisionAuthorityBoundary,
)
from newsroom.increment6.work_items import RetrievalContextAuthority
from newsroom.tests.authority_helpers import FIXED_NOW
from newsroom.tests.discovery_3d_authority_helpers import seed_check_lineage
from newsroom.tests.increment5b2_helpers import config
from newsroom.tests.projection_b2_helpers import MemoryNeo4jAdapter


def _args(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "newsroom.authority._graphiti_increment4_system._open_structural_graph_adapter",
        lambda _: MemoryNeo4jAdapter(),
    )
    journal = RetrievalContextJournal(tmp_path / "retrieval.sqlite3")
    return dict(
        authority_path=tmp_path / "authority.sqlite3",
        object_root=tmp_path / "objects", workspace_root=tmp_path,
        intake_path=tmp_path / "intake.sqlite3", target_path=tmp_path / "serving.sqlite3",
        target_id="hermes-private-serving", credential="token-1",
        principal_id="principal.alpha", authority_domain="newsroom.authority",
        neo4j_config=config(), retrieval_authority=RetrievalContextAuthority(journal.path, {}),
        collision_enforcer=CurrentCollisionEffectEnforcer(
            current_authority_provider=lambda _: None,
            trusted_boundary=TrustedCurrentCollisionAuthorityBoundary(
                "fixture-scope", "fixture-profile", "sha256:" + "a" * 64,
                "sha256:" + "b" * 64, "fixture-port",
            ),
        ), clock=lambda: FIXED_NOW,
    )


def test_native_runtime_real_policy_composition_and_reopen(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    with open_native_runtime(**args) as runtime:
        seed_check_lineage(runtime.authority)
        source = runtime.authority.objects.admit(
            ObjectAdmissionRequest("evidence.source", "source-1"), b"source bytes",
            proof=runtime.proof,
        ).admission
        assert source.allowed_use == "publication_evidence"
        assert runtime.ingress.receipt_count == 0
        assert runtime.publication is not None
        with pytest.raises(AuthorityWriterBusy):
            open_native_runtime(**args)
    with open_native_runtime(**args) as reopened:
        same = reopened.authority.objects.admit(
            ObjectAdmissionRequest("evidence.source", "source-1"), b"source bytes",
            proof=reopened.proof,
        ).admission
        assert same == source
        assert reopened.ingress.receipt_count == 0
    # No target row, provider invocation or fake retrieval success was created.


def test_native_runtime_rejects_overlapping_store_identity_before_open(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    args["target_path"] = args["authority_path"]
    with pytest.raises(ValueError, match="must be distinct"):
        open_native_runtime(**args)
    assert not args["authority_path"].exists()


def test_native_runtime_builds_dependencies_from_opened_base_before_children(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    retrieval = args.pop("retrieval_authority")
    collision = args.pop("collision_enforcer")
    captured = []

    def build_dependencies(*, objects, extraction, commands, events):
        assert args["authority_path"].exists()
        captured.append((objects, extraction, commands, events))
        return retrieval, collision

    args["native_dependency_factory"] = build_dependencies
    with open_native_runtime(**args) as runtime:
        assert len(captured) == 1
        objects, extraction, commands, events = captured[0]
        assert objects is runtime.authority.objects
        assert extraction is runtime.authority.extraction
        assert commands is runtime.authority.commands
        assert events is runtime.authority.events
        seed_check_lineage(runtime.authority)

    with open_native_runtime(**args) as reopened:
        assert len(captured) == 2
        assert captured[1][2] is reopened.authority.commands
        assert captured[1][3] is reopened.authority.events


def test_native_runtime_factory_failure_closes_base_writer(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    retrieval = args.pop("retrieval_authority")
    collision = args.pop("collision_enforcer")

    def fail_factory(**_):
        raise RuntimeError("dependency construction failed")

    args["native_dependency_factory"] = fail_factory
    with pytest.raises(RuntimeError, match="dependency construction failed"):
        open_native_runtime(**args)

    args.pop("native_dependency_factory")
    args.update(retrieval_authority=retrieval, collision_enforcer=collision)
    with open_native_runtime(**args):
        pass


def test_native_runtime_rejects_ambiguous_dependency_setup_before_open(
    tmp_path, monkeypatch,
):
    args = _args(tmp_path, monkeypatch)
    args["native_dependency_factory"] = lambda **_: (
        args["retrieval_authority"], args["collision_enforcer"],
    )
    with pytest.raises(TypeError, match="conflicts with explicit"):
        open_native_runtime(**args)
    assert not args["authority_path"].exists()
