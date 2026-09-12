"""Native revisions through the existing accounted Graphiti/admission path.

EVALUATION here is the isolated untrusted proposal workspace. Serving authority
still comes only from the existing entity/relation decisions and Increment 4
projection. This worker neither resumes a historical campaign nor mints READY.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ContextManager

from newsroom.authority import AuthenticationProof
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical, validate_sha256_digest
from newsroom.authority.hermes_native_system import HermesNativeAuthoritySystem
from newsroom.extraction.types import ExtractionRunId
from newsroom.graphiti_adapter.identity import typed_id
from newsroom.graphiti_adapter.types import GraphitiAdapterOutcome, GraphitiAdapterRightsDenied
from newsroom.increment4.neo4j import Increment4Neo4jCurrentBuildRequest
from newsroom.projection.models import ProjectionGenerationId, ProjectionGenerationState

from .corpus import CorpusIngestUnit
from .cycle import _DispatchAuthority, _ingest
from .graphiti import EvaluationGraphitiRunner, graphiti_required_route_holds
from .graphiti_admission import GraphitiAdmissionConsumerError
from .graphiti_admission_integration import compose_existing_graphiti_admission_consumer
from .model_usage import ModelUsageService
from .native_cycle import _uuid4_for
from .store import append_ledger, graphiti_failure_state
from .veto import OperatorDrainRequested, VetoError


@dataclass(frozen=True, slots=True)
class NativeGraphitiOutcome:
    ingest_id: str
    state: str
    receipt_digest: str | None
    reason: str | None


class NativeGraphitiProcessor:
    """One bounded native cohort; durable retries/accounting use existing stores."""

    def __init__(
        self, *, system: HermesNativeAuthoritySystem,
        connection: sqlite3.Connection, usage: ModelUsageService,
        proof: AuthenticationProof,
        rights_for: Callable[[CorpusIngestUnit], Mapping[str, object] | None],
        stop_check: Callable[[], None],
        dispatch_fence: Callable[[], ContextManager[None]],
        operator_drain_requested: Callable[[], bool] = lambda: False,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._system, self._connection, self._usage = system, connection, usage
        self._proof, self._rights_for = proof, rights_for
        self._stop_check, self._dispatch_fence, self._clock = stop_check, dispatch_fence, clock
        self._operator_drain_requested = operator_drain_requested
        self._cohorts: dict[str, tuple[str, ...]] = {}
        self._completed: set[str] = set()
        for raw, digest in connection.execute(
            "SELECT payload_json,payload_digest FROM ledger WHERE kind='NATIVE_GRAPHITI_COHORT' ORDER BY seq"
        ):
            if digest_bytes(raw.encode()) != digest:
                raise ValueError("native Graphiti cohort ledger differs")
            value = json.loads(raw)
            exact = tuple(value["ingest_ids"])
            if tuple(sorted(set(exact))) != exact or value["cohort_id"] != digest_canonical(exact):
                raise ValueError("native Graphiti cohort identity differs")
            self._cohorts[value["cohort_id"]] = exact
            if value["state"] == "COMPLETE":
                self._completed.add(value["cohort_id"])
            elif value["state"] != "STARTED":
                raise ValueError("native Graphiti cohort state differs")
        self._runner = EvaluationGraphitiRunner(
            clock=clock, fallback_permitted=False,
            proposal_adapter=system.graphiti, extraction_records=system.extraction,
            proof=proof,
        )
        self._admission = compose_existing_graphiti_admission_consumer(
            connection, adapter=system.graphiti, extraction=system.extraction,
            objects=system.objects, entities=system.entities, relations=system.relations,
            increment4=system.increment4, proof=proof,
        )

    def _rights(self, unit: CorpusIngestUnit) -> dict[str, object] | None:
        self._stop_check()
        value = self._rights_for(unit)
        return None if value is None else dict(value)

    @contextmanager
    def _fence(self, unit: CorpusIngestUnit):
        with self._dispatch_fence():
            rights = self._rights(unit)
            active = threading.Event()
            fence_pid = os.getpid()
            active.set()

            def require_active_fence() -> None:
                if os.getpid() != fence_pid:
                    raise VetoError("owner emergency stop fence belongs to another process")
                if not active.is_set():
                    raise VetoError("owner emergency stop fence has expired")

            try:
                yield None if rights is None else _DispatchAuthority(
                    rights, self._clock().astimezone(UTC) + timedelta(minutes=15),
                    require_active_fence,
                )
            finally:
                active.clear()

    def advance(
        self, units: tuple[CorpusIngestUnit, ...], *, cycle_id: str,
        defer_before_unit: Callable[[CorpusIngestUnit], bool] = lambda _: False,
    ) -> tuple[NativeGraphitiOutcome, ...]:
        if not units:
            return ()
        if len({unit.ingest_id for unit in units}) != len(units):
            raise ValueError("native Graphiti cohort repeats an ingest")
        for unit in units:
            if type(unit) is not CorpusIngestUnit or unit.authority is None:
                raise ValueError("native Graphiti requires retained source authority")
            if not unit.proving_run_id.startswith("native-source:"):
                raise ValueError("historical campaign input is outside native dispatch")
            validate_sha256_digest(unit.proving_run_id.removeprefix("native-source:"))
            if unit.proving_run_id != "native-source:" + unit.observation_digest:
                raise ValueError("native Graphiti observation provenance differs")
        revisions: dict[str, list[CorpusIngestUnit]] = {}
        for unit in units:
            revisions.setdefault(unit.revision_id, []).append(unit)
        for members in revisions.values():
            members.sort(key=lambda unit: unit.chunk_ordinal)
            if (tuple(unit.chunk_ordinal for unit in members) != tuple(range(1, members[0].chunk_count + 1))
                    or any(unit.chunk_count != members[0].chunk_count for unit in members)):
                raise ValueError("native Graphiti revision chunk coverage differs")
        self._stop_check()
        # Resolve retained accounting before considering another provider call.
        self._settle_missing_subscription_usage(units)
        terminal_holds = {}
        for unit in units:
            # The authority commits before the private receipt/failure journal.
            # Inspect it even if a crash left no local failure row.
            if self._connection.execute(
                "SELECT 1 FROM unpublished_graphiti_ingest WHERE ingest_id=? AND outcome='COMPLETE'",
                (unit.ingest_id,),
            ).fetchone() is not None:
                continue
            try:
                history = self._system.graphiti.attempt_history(
                    typed_id(ExtractionRunId, "run", unit.ingest_id),
                    limit=1, proof=self._proof,
                )
            except GraphitiAdapterRightsDenied:
                terminal_holds[unit.ingest_id] = "CURRENT_SOURCE_RIGHTS_HOLD"
                continue
            if history and history[0].outcome.terminal:
                head = history[0]
                # A settled terminal adapter result is not a new retryable
                # provider failure. Keep the original cause and its accounting.
                terminal_holds[unit.ingest_id] = (
                    "RETAINED_COMPLETE_RECONCILIATION_REQUIRED"
                    if head.outcome is GraphitiAdapterOutcome.COMPLETE else
                    f"{head.outcome.value}:{head.failure_code}"
                )
        deferred = set()

        def defer(unit: CorpusIngestUnit) -> bool:
            self._stop_check()
            if defer_before_unit(unit):
                deferred.add(unit.ingest_id)
                return True
            return False

        _ingest(
            self._connection, graphiti=self._runner,
            units=tuple(unit for unit in units if unit.ingest_id not in terminal_holds),
            max_graphiti=len(units), rights_check=self._rights,
            rights_fence=self._fence, clock=self._clock,
            model_usage=self._usage, cycle_id=cycle_id,
            operator_drain_requested=self._operator_drain_requested,
            defer_before_unit=defer,
        )
        self._settle_missing_subscription_usage(units)
        if self._operator_drain_requested():
            raise OperatorDrainRequested
        route_held = bool(graphiti_required_route_holds(self._usage))
        outcomes = []
        complete = []
        for unit in units:
            row = self._connection.execute(
                "SELECT outcome,receipt_digest FROM unpublished_graphiti_ingest "
                "WHERE ingest_id=?", (unit.ingest_id,),
            ).fetchone()
            if row is not None and row[0] == "COMPLETE":
                complete.append(unit.ingest_id)
                outcomes.append(NativeGraphitiOutcome(unit.ingest_id, "EXTRACTION_COMPLETE", str(row[1]), None))
            elif unit.ingest_id in deferred:
                outcomes.append(NativeGraphitiOutcome(
                    unit.ingest_id, "GRAPHITI_DEFERRED", None,
                    "WORK_QUANTUM_EXHAUSTED",
                ))
            else:
                failures, dead = graphiti_failure_state(self._connection, unit.ingest_id)
                reason = (
                    terminal_holds[unit.ingest_id] if unit.ingest_id in terminal_holds else
                    "REQUIRED_MODEL_ROUTE_CIRCUIT_OPEN" if route_held else
                    "PARTIAL_EXTRACTION" if row is not None else
                    "DEAD_LETTER" if dead else "RETRY_PENDING" if failures else
                    "RIGHTS_OR_PREDECESSOR_HOLD"
                )
                outcomes.append(NativeGraphitiOutcome(unit.ingest_id, "GRAPHITI_HOLD", None, reason))
        # Never project a prefix of a multi-chunk revision. An independently
        # complete revision may still advance while another revision is held.
        complete_set = set(complete)
        eligible = set()
        for members in revisions.values():
            if all(unit.ingest_id in complete_set for unit in members):
                eligible.update(unit.ingest_id for unit in members)
        statuses = {item.ingest_id: item for item in outcomes}
        assigned = {ingest for exact in self._cohorts.values() for ingest in exact}
        for members in revisions.values():
            exact = tuple(sorted(unit.ingest_id for unit in members))
            if set(exact) <= eligible and set(exact).isdisjoint(assigned):
                # Durable admission units follow revision atomicity. Projection
                # still batches every ready unit once below.
                self._cohort_state(exact, "STARTED")
                assigned.update(exact)
        pending = []
        for cohort_id, exact in tuple(self._cohorts.items()):
            selected = set(exact) & eligible
            if not selected:
                continue
            if cohort_id in self._completed:
                for ingest in selected:
                    statuses[ingest] = NativeGraphitiOutcome(ingest, "GRAPHITI_COMPLETE", statuses[ingest].receipt_digest, None)
                continue
            if set(exact) != selected:
                for ingest in selected:
                    statuses[ingest] = NativeGraphitiOutcome(ingest, "ADMISSION_HOLD", statuses[ingest].receipt_digest, "COHORT_CONTINUATION_PENDING")
                continue
            pending.append((cohort_id, exact))
        if pending:
            if self._operator_drain_requested():
                raise OperatorDrainRequested
            self._stop_check()
            admission_ready = []
            queued = {}
            for cohort_id, exact in pending:
                try:
                    self._admission.enqueue_complete_receipts(
                        ingest_ids=exact
                    )
                except GraphitiAdmissionConsumerError as exc:
                    for ingest in exact:
                        statuses[ingest] = NativeGraphitiOutcome(
                            ingest,
                            "ADMISSION_HOLD",
                            statuses[ingest].receipt_digest,
                            str(exc),
                        )
                else:
                    admission_ready.append((cohort_id, exact))
                    queued[cohort_id] = self._connection.execute(
                        "SELECT count(*) FROM unpublished_graphiti_admission_queue "
                        "WHERE ingest_id IN ("
                        + ",".join("?" for _ in exact)
                        + ")",
                        exact,
                    ).fetchone()[0]
            combined = tuple(
                sorted(
                    ingest
                    for _, exact in admission_ready
                    for ingest in exact
                )
            )
            if not combined:
                return tuple(statuses[unit.ingest_id] for unit in units)
            self._admission.drain(
                worker_id=cycle_id,
                limit=max(1, sum(queued.values())),
                ingest_ids=combined,
            )
            if self._operator_drain_requested():
                raise OperatorDrainRequested
            ready = []
            units_by_ingest = {unit.ingest_id: unit for unit in units}
            with self._dispatch_fence():
                for cohort_id, exact in admission_ready:
                    if all(
                        self._rights(units_by_ingest[ingest]) is not None
                        for ingest in exact
                    ):
                        ready.append((cohort_id, exact))
                    else:
                        for ingest in exact:
                            statuses[ingest] = NativeGraphitiOutcome(
                                ingest,
                                "ADMISSION_HOLD",
                                statuses[ingest].receipt_digest,
                                "CURRENT_RIGHTS_HOLD",
                            )
                verified = []
                for cohort_id, exact in ready:
                    try:
                        self._admission.preflight_decided_cohort(
                            ingest_ids=exact
                        )
                    except GraphitiAdmissionConsumerError as exc:
                        for ingest in exact:
                            statuses[ingest] = NativeGraphitiOutcome(
                                ingest,
                                "ADMISSION_HOLD",
                                statuses[ingest].receipt_digest,
                                str(exc),
                            )
                    else:
                        verified.append((cohort_id, exact))
                ready = verified
                if ready:
                    final_ids = tuple(
                        sorted(ingest for _, exact in ready for ingest in exact)
                    )
                    try:
                        self._admission.finalise_decided_cohort(
                            ingest_ids=final_ids
                        )
                        if not sum(queued[cohort_id] for cohort_id, _ in ready):
                            # One real full-history generation covers every
                            # zero-proposal revision ready in this iteration.
                            frontier = digest_canonical(final_ids)
                            generation_id = ProjectionGenerationId.parse(
                                _uuid4_for({"native_zero_proposal_cohort": frontier})
                            )
                            built = self._system.increment4.build_current_and_promote(
                                Increment4Neo4jCurrentBuildRequest(
                                    generation_id,
                                    "NATIVE_ZERO_PROPOSAL_COHORT",
                                    f"native-empty-cohort:{frontier}",
                                ),
                                proof=self._proof,
                            )
                            if (
                                built.generation.state
                                is not ProjectionGenerationState.ACTIVE
                            ):
                                raise GraphitiAdmissionConsumerError(
                                    "native empty-cohort graph is not active"
                                )
                    except GraphitiAdmissionConsumerError as exc:
                        for _, exact in ready:
                            for ingest in exact:
                                statuses[ingest] = NativeGraphitiOutcome(
                                    ingest,
                                    "ADMISSION_HOLD",
                                    statuses[ingest].receipt_digest,
                                    str(exc),
                                )
                        ready = []
            for _, exact in ready:
                self._cohort_state(exact, "COMPLETE")
                for ingest in exact:
                    statuses[ingest] = NativeGraphitiOutcome(
                        ingest,
                        "GRAPHITI_COMPLETE",
                        statuses[ingest].receipt_digest,
                        None,
                    )
            if self._operator_drain_requested():
                raise OperatorDrainRequested
        return tuple(statuses[unit.ingest_id] for unit in units)

    def _settle_missing_subscription_usage(
        self, units: tuple[CorpusIngestUnit, ...],
    ) -> None:
        if self._usage is None:
            return
        ingest_ids = {unit.ingest_id for unit in units}
        rows = self._connection.execute(
            "SELECT a.invocation_id,a.canonical_digest,t.terminal_digest,e.record_json "
            "FROM model_invocation_allocations a "
            "JOIN model_invocation_terminals t ON t.invocation_id=a.invocation_id "
            "JOIN model_work_envelopes e ON e.envelope_id=a.envelope_id "
            "WHERE a.workload_class='GRAPHITI_CHAT_PRIMARY' "
            "AND a.provider='cursor-agent-cli' AND t.usage_status='UNREPORTED' "
            "AND t.failure_class='MISSING_PROVIDER_TELEMETRY' "
            "AND NOT EXISTS (SELECT 1 FROM model_usage_conservative_dispositions d "
            "WHERE d.invocation_id=a.invocation_id)"
        ).fetchall()
        for invocation_id, allocation_digest, terminal_digest, envelope_raw in rows:
            if json.loads(envelope_raw).get("ingest_id") not in ingest_ids:
                continue
            # The usage service independently validates the exact native source,
            # qualified policy and dispatch. This retains ESTIMATED accounting,
            # never fabricated telemetry, and does not release a route circuit.
            self._usage.disposition_native_unreported_subscription_usage(
                invocation_id=invocation_id,
                expected_terminal_digest=terminal_digest,
                expected_allocation_digest=allocation_digest,
                observed_at=self._clock(),
            )

    def _cohort_state(self, exact: tuple[str, ...], state: str) -> None:
        cohort_id = digest_canonical(exact)
        append_ledger(self._connection, "NATIVE_GRAPHITI_COHORT", {
            "cohort_id": cohort_id, "ingest_ids": list(exact), "state": state,
        })
        self._connection.commit()
        self._cohorts[cohort_id] = exact
        if state == "COMPLETE":
            self._completed.add(cohort_id)
