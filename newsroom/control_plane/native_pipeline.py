"""One autonomous private Hermes iteration; no per-story owner gate."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import ContextManager

from newsroom.authority import UtcTimestamp

from .native_cycle import advance_native_cycle
from .native_progress import NativeRevisionJournal
from .veto import VetoError


@dataclass(frozen=True, slots=True)
class NativePipelineReport:
    sources: tuple[dict, ...]
    revision_states: dict[str, int]
    unclassified_revisions: int


class NativePipeline:
    """Reuse retained stages; isolate a held revision while other work advances.

    The daemon supplies the concrete retrieval builder and publication
    continuation. Neither a heartbeat nor this report is an acceptance PASS.
    """

    def __init__(
        self, *, runtime, journal: NativeRevisionJournal, source_intake,
        graphiti, discovery, retrieval_for: Callable, collision, publish,
        actor_identity_digest: str, stop_check: Callable[[], None],
        stop_fence: Callable[[], ContextManager[None]],
        refresh_rights: Callable[[], None] = lambda: None,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        self._runtime, self._journal = runtime, journal
        self._intake, self._graphiti, self._discovery = source_intake, graphiti, discovery
        self._retrieval_for, self._collision, self._publish = retrieval_for, collision, publish
        self._actor, self._check, self._fence, self._clock = actor_identity_digest, stop_check, stop_fence, clock
        self._refresh_rights = refresh_rights
        self.runtime_identity_digest: str | None = None

    def tick(self, *, cycle_id: str) -> NativePipelineReport:
        self._check()
        self._refresh_rights()
        self._check()
        dispositions = self._intake.poll()
        self._journal.sources(dispositions)
        grouped = defaultdict(list)
        for disposition in dispositions:
            for unit in disposition.units:
                grouped[unit.revision_id].append(unit)
        for revision_id, units in grouped.items():
            self._journal.land(tuple(units))

        # Fixed disjoint cohorts attempt each revision at most once per tick.
        # Retained downstream work must not wait behind fresh model requests.
        ready, pending_revisions = [], []
        for revision_id, units in self._journal.units.items():
            facts = self._journal.progress.get(revision_id, {}).get("facts", {})
            cohort = ready if facts.get("graphiti_receipts") else pending_revisions
            cohort.append((revision_id, units))
        self._advance_revisions(tuple(ready))
        pending_revisions = tuple(pending_revisions)

        # Extraction stays per ingest; projection remains one complete cohort.
        pending = tuple(unit for _, units in pending_revisions for unit in units)
        if pending:
            self._check()
            try:
                results = self._graphiti.advance(pending, cycle_id=cycle_id)
                if len(results) != len(pending) or {item.ingest_id for item in results} != {unit.ingest_id for unit in pending}:
                    raise ValueError("native Graphiti continuation partition differs")
                by_ingest = {item.ingest_id: item for item in results}
                for revision_id in dict.fromkeys(unit.revision_id for unit in pending):
                    outcomes = tuple(by_ingest[unit.ingest_id] for unit in self._journal.units[revision_id])
                    facts = dict(self._journal.progress.get(revision_id, {}).get("facts", {}))
                    complete = all(item.state == "GRAPHITI_COMPLETE" for item in outcomes)
                    if complete:
                        facts.pop("graphiti_outcomes", None)
                        facts.pop("reason", None)
                        facts["graphiti_receipts"] = [asdict(item) for item in outcomes]
                    else:
                        held = tuple(
                            item for item in outcomes
                            if item.state in {"GRAPHITI_HOLD", "ADMISSION_HOLD"}
                        )
                        if not held:
                            raise ValueError("native Graphiti incomplete revision lacks a hold")
                        reasons = {
                            item.reason
                            for item in held
                        }
                        if any(type(reason) is not str or not reason for reason in reasons):
                            raise ValueError("native Graphiti hold reason differs")
                        facts.pop("graphiti_receipts", None)
                        facts["graphiti_outcomes"] = [asdict(item) for item in outcomes]
                        facts["reason"] = (
                            next(iter(reasons))
                            if len(reasons) == 1
                            else "MULTIPLE_GRAPHITI_HOLDS"
                        )
                    self._journal.advance(revision_id, stage="GRAPHITI_COMPLETE" if complete else "GRAPHITI_HOLD", facts=facts)
            except VetoError:
                raise
            except Exception as exc:
                for revision_id in dict.fromkeys(unit.revision_id for unit in pending):
                    facts = self._journal.progress.get(revision_id, {}).get("facts", {})
                    self._journal.advance(revision_id, stage="GRAPHITI_HOLD", facts={
                        **facts, "reason": type(exc).__name__,
                    })

        self._advance_revisions(pending_revisions)
        states = Counter(
            self._journal.progress.get(revision_id, {}).get("stage", "QUEUED")
            for revision_id in self._journal.units
        )
        return NativePipelineReport(
            self._journal.portfolio, dict(states), states.get("QUEUED", 0),
        )

    def _advance_revisions(self, revisions: tuple) -> None:
        # Each revision remains in the journal even when it disappears from the
        # next feed page. This is work continuation, not a fresh provider retry.
        for revision_id, units in revisions:
            self._check()
            previous = self._journal.progress.get(revision_id, {})
            if previous.get("stage") == "ASSESSMENT_INTERRUPTED":
                candidate_version_id = previous.get("facts", {}).get(
                    "candidate_version_id"
                )
                if type(candidate_version_id) is str and candidate_version_id:
                    self._publish.advance(
                        revision_id=revision_id,
                        candidate_version_id=candidate_version_id,
                    )
                continue
            if previous.get("stage") == "ACKNOWLEDGED":
                continue
            if (
                previous.get("stage") == "EVIDENCE_HOLD"
                and previous.get("facts", {}).get("acquisition_retryable") is not True
                and previous.get("facts", {}).get("reason") not in {
                    "CURRENT_RIGHTS_HOLD", "GOVUK_LICENCE_BINDING_HOLD",
                    "GOVUK_LICENCE_REVIEW_HOLD", "NATIVE_SOURCE_RIGHTS_HOLD",
                    "PUBLICATION_RIGHTS_HOLD",
                }
            ):
                continue
            facts = dict(previous.get("facts", {}))
            stage = "GRAPHITI"
            try:
                if not facts.get("graphiti_receipts"):
                    continue
                candidate_version_id = facts.get("candidate_version_id")
                if candidate_version_id is None:
                    stage = "DISCOVERY"
                    now = self._clock()
                    delivered = self._discovery.deliver(
                        units[0], now=now, proof=self._runtime.proof,
                    )
                    status = self._discovery.admit_lead(
                        delivered, now=now, proof=self._runtime.proof,
                    )
                    if status.lead is None:
                        self._journal.advance(revision_id, stage="DISCOVERY_HOLD", facts={
                            **facts, "reason": status.phase.value,
                        })
                        continue
                    stage = "RETRIEVAL"
                    retrieval = self._retrieval_for(units)
                    outcomes = advance_native_cycle(
                        system=self._runtime.authority, statuses=(status,), retrieval=retrieval,
                        collision_requests=self._collision,
                        actor_identity_digest=self._actor, proof=self._runtime.proof,
                        owner_stop_check=self._check, owner_stop_fence=self._fence,
                    )
                    facts = dict(self._journal.progress.get(revision_id, {}).get("facts", facts))
                    if len(outcomes) != 1 or outcomes[0].revision_id != revision_id:
                        raise ValueError("native Candidate continuation partition differs")
                    outcome = outcomes[0]
                    if outcome.state != "CANDIDATE_ADMITTED":
                        self._journal.advance(revision_id, stage=outcome.state, facts={
                            **facts, "reason": outcome.reason,
                        })
                        continue
                    candidate_version_id = outcome.triage.candidate.version_id
                    facts["candidate_version_id"] = candidate_version_id
                    self._journal.advance(revision_id, stage="CANDIDATE_ADMITTED", facts=facts)
                stage = "PUBLICATION"
                self._publish.advance(
                    revision_id=revision_id, candidate_version_id=candidate_version_id,
                )
            except VetoError:
                raise
            except Exception as exc:
                # Do not overwrite a more precise durable provider-dispatch or
                # publication intent marker with a generic outer-loop failure.
                retained = self._journal.progress.get(revision_id, {})
                if retained.get("stage") in {"ASSESSMENT_STARTED", "PUBLICATION_STARTED"}:
                    continue
                self._journal.advance(revision_id, stage=f"{stage}_HOLD", facts={
                    **self._journal.progress.get(revision_id, {}).get("facts", facts),
                    "reason": getattr(exc, "reason", getattr(exc, "reason_code", type(exc).__name__)),
                })
