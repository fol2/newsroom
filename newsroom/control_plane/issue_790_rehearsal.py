"""Provider-free issue #790 canary rehearsal. Refuses Mini live store paths."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti import EvaluationGraphitiRunner
from newsroom.control_plane.issue_790_prepared_canary import (
    PreparedCanary,
    PreparedCanaryError,
    consume_prepared_canary,
    prepare_issue_790_canary,
)
from newsroom.control_plane.paths import (
    CANONICAL_PROVING_STORE,
    CANONICAL_UNPUBLISHED_STORE,
)
from newsroom.extraction.models import ProducedExtraction
from newsroom.extraction.types import (
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
)
from newsroom.graphiti_adapter.evaluation_packet import CURSOR_AGENT_MODEL_ID
from newsroom.graphiti_adapter.real import RealGraphitiAdapter, _no_embedding_usage
from newsroom.graphiti_adapter.result_mapping import produced_extraction

_MINI_UNPUBLISHED = Path(
    "/Users/jamesto/Coding/newsroom/data/newsroom/unpublished_store.sqlite3"
)
_MINI_PROVING = Path(
    "/Users/jamesto/Coding/newsroom/data/newsroom/proving_store.sqlite3"
)


def live_issue_790_store_paths() -> frozenset[Path]:
    return frozenset(
        {
            CANONICAL_PROVING_STORE.expanduser().resolve(strict=False),
            CANONICAL_UNPUBLISHED_STORE.expanduser().resolve(strict=False),
            _MINI_PROVING,
            _MINI_UNPUBLISHED,
        }
    )


def refuse_live_issue_790_store_paths(*paths: Path) -> None:
    """Fail closed before any rehearsal write can touch Mini live stores."""

    forbidden = live_issue_790_store_paths()
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        if resolved in forbidden:
            raise PreparedCanaryError(
                "rehearsal refuses Mini live store paths",
                failure_code="LIVE_STORE_WRITE_REFUSED",
            )
        try:
            if any(resolved.samefile(item) for item in forbidden if item.exists()):
                raise PreparedCanaryError(
                    "rehearsal refuses Mini live store path aliases",
                    failure_code="LIVE_STORE_WRITE_REFUSED",
                )
        except OSError:
            continue


def sqlite_backup_copy(source: Path, destination: Path) -> Path:
    """Full sqlite backup, not a one-row export."""

    refuse_live_issue_790_store_paths(source, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise PreparedCanaryError(
            "rehearsal backup destination already exists",
            failure_code="LIVE_STORE_WRITE_REFUSED",
        )
    source_connection = sqlite3.connect(f"{source.absolute().as_uri()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
        check = destination_connection.execute("PRAGMA quick_check").fetchone()
        if check is None or str(check[0]) != "ok":
            raise PreparedCanaryError(
                "rehearsal sqlite backup is not healthy",
                failure_code="STORE_ABSENT",
            )
    finally:
        destination_connection.close()
        source_connection.close()
    return destination


class RehearsalRealGraphitiAdapter(RealGraphitiAdapter):
    """Inherits ``execute``; fakes only the network/transport seam."""

    provider_calls = 0
    dispatch_started = False

    def _produce(self, attempt, started_at, **_kwargs) -> ProducedExtraction:
        observer = self._invocation_observer
        if observer is not None:
            from newsroom.graphiti_adapter.cli_client import (
                _before_observed_cli_invocation,
                _mark_observed_transport_dispatch,
            )

            token = _before_observed_cli_invocation(
                observer,
                provider="cursor-agent-cli",
                model=CURSOR_AGENT_MODEL_ID,
                prompt="issue-790-rehearsal",
                schema=None,
                semantic_request_class="UNSTRUCTURED",
                max_tokens=16_384,
            )
            _mark_observed_transport_dispatch(observer, token)
            type(self).dispatch_started = True
        embedding = _no_embedding_usage()
        raw: dict[str, object] = {
            "chat_invocations": [],
            "embedding_usage": embedding,
            "entities": [],
            "passages": [],
            "proposals": [],
            "provider_attempt_number": int(attempt.attempt_number),
            "relations": [],
            "token_usage": {
                "cost_usd_microunits": 0,
                "request_tokens": 0,
                "response_tokens": 0,
                "total_tokens": 0,
                "usage_basis": "NO_PROVIDER_CALL",
            },
            "usage_basis": "NO_PROVIDER_CALL",
        }
        raw["raw_output_digest"] = digest_canonical(raw)
        return produced_extraction(
            attempt,
            outcome=ExtractionOutcome.SUCCESS,
            failure_code=ExtractionFailureCode.NONE,
            validation=ExtractionOutputValidation.VALID,
            raw=raw,
            proposals=(),
            embedding_usage=embedding,
            attempt_receipt=raw,
        )


class RehearsalEvaluationGraphitiRunner(EvaluationGraphitiRunner):
    """Real runner with canonical-store requirement lifted for fixture copies."""

    requires_canonical_control_plane_stores = False
    _adapter_cls = RehearsalRealGraphitiAdapter


def run_prepared_canary_rehearsal(
    *,
    store: Path,
    proving_store: Path,
    plan: Mapping[str, object],
    observed_at: datetime,
    exact_head: str,
    prepared: PreparedCanary | None = None,
    crash_before_dispatch: bool = False,
    event_id: str | None = None,
    ledger_seq: int | None = None,
) -> dict[str, object]:
    """READY digest then production consume path down to the transport seam."""

    refuse_live_issue_790_store_paths(store, proving_store)
    RehearsalRealGraphitiAdapter.provider_calls = 0
    RehearsalRealGraphitiAdapter.dispatch_started = False
    latest = prepare_issue_790_canary(
        store=store,
        proving_store=proving_store,
        plan=plan,
        observed_at=observed_at,
        exact_head=exact_head,
        event_id=event_id,
        ledger_seq=ledger_seq,
        role="canary",
    )
    retained = consume_prepared_canary(prepared, expected=latest)
    consume_event_id = str(retained.candidate_identity["event_id"])
    consume_ledger_seq = int(retained.candidate_identity["ledger_seq"])
    if crash_before_dispatch:
        raise PreparedCanaryError(
            "rehearsal crashed before dispatch",
            failure_code="REHEARSAL_CRASH_BEFORE_DISPATCH",
        )
    from newsroom.control_plane.issue_790_disposition import _consume_issue_790_event
    from newsroom.control_plane.model_usage import ModelUsageService

    service = ModelUsageService(str(store))
    try:
        result = _consume_issue_790_event(
            proving_store=proving_store,
            unpublished_store=store,
            owner_id=f"issue-790-rehearsal:{observed_at.astimezone(UTC).isoformat()}",
            event_id=consume_event_id,
            canary_consumption_digest=None,
            model_usage=service,
            graphiti=RehearsalEvaluationGraphitiRunner(
                fallback_permitted=False,
                clock=lambda: observed_at,
            ),
            clock=lambda: observed_at,
        )
        post_dispatch_error = None
    except Exception as exc:
        if not RehearsalRealGraphitiAdapter.dispatch_started:
            raise
        result = None
        post_dispatch_error = f"{type(exc).__name__}: {exc}"
    return {
        "decision_digest": retained.decision_digest,
        "dispatch_started": RehearsalRealGraphitiAdapter.dispatch_started,
        "post_dispatch_error": post_dispatch_error,
        "process_result": None if result is None else {
            "attempt_count": result.attempt_count,
            "event_id": result.event_id,
            "ledger_seq": result.ledger_seq,
            "state": result.state,
        },
        "provider_calls": RehearsalRealGraphitiAdapter.provider_calls,
    }


__all__ = [
    "RehearsalEvaluationGraphitiRunner",
    "RehearsalRealGraphitiAdapter",
    "live_issue_790_store_paths",
    "refuse_live_issue_790_store_paths",
    "run_prepared_canary_rehearsal",
    "sqlite_backup_copy",
]
