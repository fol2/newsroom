"""EVALUATION Graphiti runner for the unpublished Control Plane cycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from newsroom.control_plane.evidence import EvidencePackage
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_WORKSPACE_GROUP


@dataclass(frozen=True, slots=True)
class GraphitiCycleResult:
    candidate_id: str
    outcome: str
    proposal_count: int
    failure_code: str
    workspace_group: str = GRAPHITI_WORKSPACE_GROUP


class GraphitiPort(Protocol):
    def extract(self, package: EvidencePackage) -> GraphitiCycleResult: ...


class EvaluationGraphitiRunner:
    """Real Graphiti under EVALUATION. Does not write the ledger or admitted labels."""

    def extract(self, package: EvidencePackage) -> GraphitiCycleResult:
        from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
        from newsroom.graphiti_adapter.real import RealGraphitiAdapter

        attempt = evaluation_attempt_for(package.passages)
        with TemporaryDirectory() as root:
            execution = RealGraphitiAdapter().execute(
                attempt=attempt,
                workspace_root=Path(root),
            )
        return GraphitiCycleResult(
            candidate_id=package.candidate_id,
            outcome=execution.outcome.value,
            proposal_count=len(execution.produced.proposals),
            failure_code=execution.failure_code,
        )


__all__ = ["EvaluationGraphitiRunner", "GraphitiCycleResult", "GraphitiPort"]
