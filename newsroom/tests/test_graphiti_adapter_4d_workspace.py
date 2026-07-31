from __future__ import annotations

import os
from dataclasses import replace

import pytest

from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter import (
    DisposableProposalWorkspace,
    GraphitiCleanupReason,
    GraphitiCleanupReceiptId,
    GraphitiWorkspaceDescriptor,
    GraphitiWorkspaceError,
    GraphitiWorkspaceId,
    GraphitiWorkspaceState,
    QUALIFICATION_WORKSPACE_POLICY,
)

from .graphiti_adapter_4d_helpers import FAKE_CONFIGURATION_ID, ADAPTER_NOW


def _workspace(tmp_path, *, suffix: str = "1") -> DisposableProposalWorkspace:
    workspace_id = GraphitiWorkspaceId.parse(
        f"00000000-0000-4000-8000-0000000048{int(suffix):02d}"
    )
    descriptor = GraphitiWorkspaceDescriptor(
        workspace_id=workspace_id,
        configuration_id=FAKE_CONFIGURATION_ID,
        policy_id=QUALIFICATION_WORKSPACE_POLICY.policy_id,
        policy_digest=QUALIFICATION_WORKSPACE_POLICY.canonical_digest,
        namespace=f"graphiti-qualification-{workspace_id}",
        created_at=ADAPTER_NOW,
    )
    return DisposableProposalWorkspace(
        root=tmp_path.resolve(),
        descriptor=descriptor,
        policy=QUALIFICATION_WORKSPACE_POLICY,
    )


def test_workspace_is_private_bounded_and_removed(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    workspace.activate()
    path = tmp_path / workspace.descriptor.namespace
    assert workspace.state is GraphitiWorkspaceState.ACTIVE
    assert path.exists()
    assert os.stat(tmp_path).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o700

    workspace.write_private_graph(
        nodes=(
            {
                "private_node_id": "node-1",
                "proposal_local_id": "entity.one",
            },
        ),
        relations=(
            {
                "private_relation_id": "relation-1",
                "proposal_local_id": "relation.one",
            },
        ),
    )
    graph = path / "private-proposal-graph.json"
    assert os.stat(graph).st_mode & 0o777 == 0o600
    receipt = workspace.cleanup(
        receipt_id=GraphitiCleanupReceiptId.parse(
            "00000000-0000-4000-8000-000000004831"
        ),
        reason=GraphitiCleanupReason.NORMAL,
        recorded_at=ADAPTER_NOW,
    )
    assert receipt.final_state is GraphitiWorkspaceState.CLEANED
    assert receipt.private_node_count == 1
    assert receipt.private_relation_count == 1
    assert receipt.file_count == 1
    assert receipt.workspace_absent is True
    assert not path.exists()
    assert str(tmp_path) not in repr(receipt)
    assert "private_node_id" not in str(receipt.canonical_value())


def test_workspace_loss_is_explicit_and_non_authoritative(tmp_path) -> None:
    workspace = _workspace(tmp_path, suffix="2")
    workspace.activate()
    workspace.write_private_graph(nodes=(), relations=())
    receipt = workspace.simulate_loss(
        receipt_id=GraphitiCleanupReceiptId.parse(
            "00000000-0000-4000-8000-000000004832"
        ),
        recorded_at=ADAPTER_NOW,
    )
    assert receipt.final_state is GraphitiWorkspaceState.LOST
    assert receipt.reason is GraphitiCleanupReason.SIMULATED_LOSS
    assert receipt.workspace_absent is True


def test_workspace_rejects_namespace_reuse_symlinks_and_overwrite(tmp_path) -> None:
    workspace = _workspace(tmp_path, suffix="3")
    workspace.activate()
    workspace.write_private_graph(nodes=(), relations=())
    with pytest.raises(GraphitiWorkspaceError, match="overwritten"):
        workspace.write_private_graph(nodes=(), relations=())

    reused = _workspace(tmp_path, suffix="3")
    with pytest.raises(GraphitiWorkspaceError, match="already exists"):
        reused.activate()

    symlink_root = tmp_path / "symlink-root"
    target = tmp_path / "target"
    target.mkdir()
    symlink_root.symlink_to(target, target_is_directory=True)
    descriptor = replace(
        workspace.descriptor,
        workspace_id=GraphitiWorkspaceId.parse(
            "00000000-0000-4000-8000-000000004834"
        ),
        namespace="graphiti-qualification-symlink",
    )
    invalid = DisposableProposalWorkspace(
        root=symlink_root,
        descriptor=descriptor,
        policy=QUALIFICATION_WORKSPACE_POLICY,
    )
    with pytest.raises(GraphitiWorkspaceError, match="symlink"):
        invalid.activate()


def test_workspace_rejects_secrets_arbitrary_queries_and_bounds(tmp_path) -> None:
    workspace = _workspace(tmp_path, suffix="5")
    workspace.activate()
    with pytest.raises(GraphitiWorkspaceError, match="secret or arbitrary-query"):
        workspace.write_private_graph(
            nodes=({"private_node_id": "node-1", "api_key": "secret"},),
            relations=(),
        )
    with pytest.raises(GraphitiWorkspaceError, match="secret or arbitrary-query"):
        workspace.write_private_graph(
            nodes=(),
            relations=({"private_relation_id": "r1", "cypher": "MATCH (n)"},),
        )
    too_many = tuple(
        {"private_node_id": f"node-{index}"}
        for index in range(QUALIFICATION_WORKSPACE_POLICY.max_private_nodes + 1)
    )
    with pytest.raises(GraphitiWorkspaceError, match="node count"):
        workspace.write_private_graph(nodes=too_many, relations=())
