"""Native revisions through the existing accounted Graphiti/admission path.

EVALUATION here is the isolated untrusted proposal workspace. Serving authority
still comes only from the existing entity/relation decisions and Increment 4
projection. This worker neither resumes a historical campaign nor mints READY.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ContextManager

from newsroom.authority import AuthenticationProof
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical, validate_sha256_digest
from newsroom.authority.hermes_native_system import HermesNativeAuthoritySystem
from newsroom.increment4.neo4j import Increment4Neo4jCurrentBuildRequest
from newsroom.projection.models import ProjectionGenerationId, ProjectionGenerationState

from .corpus import CorpusIngestUnit
from .cycle import _DispatchAuthority, _ingest
from .graphiti import EvaluationGraphitiRunner
from .graphiti_admission import GraphitiAdmissionConsumerError
from .graphiti_admission_integration import compose_existing_graphiti_admission_consumer
from .model_usage import ModelUsageService
from .native_cycle import _uuid4_for
from .store import append_ledger, graphiti_failure_state


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
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._system, self._connection, self._usage = system, connection, usage
        self._proof, self._rights_for = proof, rights_for
        self._stop_check, self._dispatch_fence, self._clock = stop_check, dispatch_fence, clock
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
            yield None if rights is None else _DispatchAuthority(
                rights, self._clock().astimezone(UTC) + timedelta(minutes=15),
                self._stop_check,
            )

    def advance(
        self, units: tuple[CorpusIngestUnit, ...], *, cycle_id: str,
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
        _ingest(
            self._connection, graphiti=self._runner, units=units,
            max_graphiti=len(units), rights_check=self._rights,
            rights_fence=self._fence, clock=self._clock,
            model_usage=self._usage, cycle_id=cycle_id,
        )
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
            else:
                failures, dead = graphiti_failure_state(self._connection, unit.ingest_id)
                reason = "PARTIAL_EXTRACTION" if row is not None else "DEAD_LETTER" if dead else "RETRY_PENDING" if failures else "RIGHTS_OR_PREDECESSOR_HOLD"
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
        return tuple(statuses[unit.ingest_id] for unit in units)

    def _cohort_state(self, exact: tuple[str, ...], state: str) -> None:
        cohort_id = digest_canonical(exact)
        append_ledger(self._connection, "NATIVE_GRAPHITI_COHORT", {
            "cohort_id": cohort_id, "ingest_ids": list(exact), "state": state,
        })
        self._connection.commit()
        self._cohorts[cohort_id] = exact
        if state == "COMPLETE":
            self._completed.add(cohort_id)
