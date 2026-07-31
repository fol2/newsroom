from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Iterable, Mapping

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.types import UtcTimestamp

from .models import (
    GraphitiCleanupReceipt,
    GraphitiWorkspaceDescriptor,
    GraphitiWorkspacePolicy,
)
from .types import (
    GraphitiCleanupReason,
    GraphitiCleanupReceiptId,
    GraphitiWorkspaceError,
    GraphitiWorkspaceState,
)


def _reject_workspace_secrets(value: object, *, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise GraphitiWorkspaceError(
                    f"private workspace key must be text at {path}"
                )
            lowered = key.lower()
            if any(
                fragment in lowered
                for fragment in (
                    "access_token",
                    "api_key",
                    "credential",
                    "cypher",
                    "password",
                    "secret",
                )
            ):
                raise GraphitiWorkspaceError(
                    f"secret or arbitrary-query field is prohibited at {path}.{key}"
                )
            _reject_workspace_secrets(item, path=f"{path}.{key}")
        return
    if isinstance(value, Iterable) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        for index, item in enumerate(value):
            _reject_workspace_secrets(item, path=f"{path}[{index}]")
        return
    raise GraphitiWorkspaceError(
        f"unsupported private workspace value at {path}: {type(value).__name__}"
    )


class DisposableProposalWorkspace:
    """Private, bounded, credential-free proposal workspace.

    The workspace may contain disposable private graph IDs, but its public
    descriptor and cleanup receipt never expose those IDs or the filesystem path.
    """

    __slots__ = (
        "_root",
        "_path",
        "descriptor",
        "policy",
        "_state",
        "_private_node_count",
        "_private_relation_count",
    )

    def __init__(
        self,
        *,
        root: Path,
        descriptor: GraphitiWorkspaceDescriptor,
        policy: GraphitiWorkspacePolicy,
    ) -> None:
        if not isinstance(root, Path):
            raise GraphitiWorkspaceError("workspace root must be a pathlib Path")
        if not isinstance(descriptor, GraphitiWorkspaceDescriptor):
            raise GraphitiWorkspaceError("workspace descriptor must be typed")
        if not isinstance(policy, GraphitiWorkspacePolicy):
            raise GraphitiWorkspaceError("workspace policy must be typed")
        if descriptor.policy_id != policy.policy_id:
            raise GraphitiWorkspaceError("workspace descriptor policy identity differs")
        if descriptor.policy_digest != policy.canonical_digest:
            raise GraphitiWorkspaceError("workspace descriptor policy digest differs")
        if not root.is_absolute():
            raise GraphitiWorkspaceError("workspace root must be absolute")
        self._root = root
        self._path = root / descriptor.namespace
        self.descriptor = descriptor
        self.policy = policy
        self._state = GraphitiWorkspaceState.CREATED
        self._private_node_count = 0
        self._private_relation_count = 0

    @property
    def state(self) -> GraphitiWorkspaceState:
        return self._state

    @property
    def exists(self) -> bool:
        return self._path.exists()

    def activate(self) -> None:
        if self._state is not GraphitiWorkspaceState.CREATED:
            raise GraphitiWorkspaceError("workspace can be activated only once")
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            raise GraphitiWorkspaceError("workspace root cannot be a symlink")
        os.chmod(self._root, 0o700)
        try:
            self._path.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError as exc:
            raise GraphitiWorkspaceError(
                "workspace namespace already exists and cannot be reused"
            ) from exc
        if self._path.is_symlink():
            raise GraphitiWorkspaceError("workspace namespace cannot be a symlink")
        os.chmod(self._path, 0o700)
        self._state = GraphitiWorkspaceState.ACTIVE

    def write_private_graph(
        self,
        *,
        nodes: tuple[dict[str, object], ...],
        relations: tuple[dict[str, object], ...],
    ) -> None:
        if self._state is not GraphitiWorkspaceState.ACTIVE:
            raise GraphitiWorkspaceError("workspace must be active before graph writes")
        if not isinstance(nodes, tuple) or any(not isinstance(item, dict) for item in nodes):
            raise GraphitiWorkspaceError("private graph nodes must be typed tuples")
        if not isinstance(relations, tuple) or any(
            not isinstance(item, dict) for item in relations
        ):
            raise GraphitiWorkspaceError(
                "private graph relations must be typed tuples"
            )
        if len(nodes) > self.policy.max_private_nodes:
            raise GraphitiWorkspaceError("private graph node count exceeds policy")
        if len(relations) > self.policy.max_private_relations:
            raise GraphitiWorkspaceError("private graph relation count exceeds policy")
        value = {
            "schema_version": "newsroom.graphiti.private-proposal-workspace.v1",
            "workspace_id": str(self.descriptor.workspace_id),
            "nodes": list(nodes),
            "relations": list(relations),
        }
        _reject_workspace_secrets(value)
        data = canonical_json_bytes(value)
        if len(data) > self.policy.max_workspace_bytes:
            raise GraphitiWorkspaceError("private graph bytes exceed workspace policy")
        target = self._path / "private-proposal-graph.json"
        if target.exists() or target.is_symlink():
            raise GraphitiWorkspaceError("private graph file cannot be overwritten")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(target, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        os.chmod(target, 0o600)
        self._private_node_count = len(nodes)
        self._private_relation_count = len(relations)

    def _statistics(self) -> tuple[int, int]:
        file_count = 0
        byte_count = 0
        if self._path.exists():
            for item in self._path.rglob("*"):
                if item.is_symlink():
                    raise GraphitiWorkspaceError(
                        "workspace cannot retain symbolic links"
                    )
                if item.is_file():
                    file_count += 1
                    byte_count += item.stat().st_size
        if byte_count > self.policy.max_workspace_bytes:
            raise GraphitiWorkspaceError("workspace bytes exceed policy")
        return file_count, byte_count

    def cleanup(
        self,
        *,
        receipt_id: GraphitiCleanupReceiptId,
        reason: GraphitiCleanupReason,
        recorded_at: UtcTimestamp,
    ) -> GraphitiCleanupReceipt:
        if self._state is not GraphitiWorkspaceState.ACTIVE:
            raise GraphitiWorkspaceError("only an active workspace can be cleaned")
        if not self._path.exists():
            raise GraphitiWorkspaceError(
                "workspace disappeared without an explicit loss transition"
            )
        file_count, byte_count = self._statistics()
        shutil.rmtree(self._path)
        if self._path.exists():
            raise GraphitiWorkspaceError("workspace cleanup did not remove state")
        self._state = GraphitiWorkspaceState.CLEANED
        return GraphitiCleanupReceipt(
            receipt_id=receipt_id,
            workspace_id=self.descriptor.workspace_id,
            final_state=self._state,
            reason=reason,
            private_node_count=self._private_node_count,
            private_relation_count=self._private_relation_count,
            file_count=file_count,
            byte_count=byte_count,
            workspace_absent=True,
            recorded_at=recorded_at,
        )

    def simulate_loss(
        self,
        *,
        receipt_id: GraphitiCleanupReceiptId,
        recorded_at: UtcTimestamp,
    ) -> GraphitiCleanupReceipt:
        if self._state is not GraphitiWorkspaceState.ACTIVE:
            raise GraphitiWorkspaceError("only an active workspace can be lost")
        file_count, byte_count = self._statistics()
        shutil.rmtree(self._path)
        if self._path.exists():
            raise GraphitiWorkspaceError("workspace loss simulation left state behind")
        self._state = GraphitiWorkspaceState.LOST
        return GraphitiCleanupReceipt(
            receipt_id=receipt_id,
            workspace_id=self.descriptor.workspace_id,
            final_state=self._state,
            reason=GraphitiCleanupReason.SIMULATED_LOSS,
            private_node_count=self._private_node_count,
            private_relation_count=self._private_relation_count,
            file_count=file_count,
            byte_count=byte_count,
            workspace_absent=True,
            recorded_at=recorded_at,
        )


__all__ = ["DisposableProposalWorkspace"]
