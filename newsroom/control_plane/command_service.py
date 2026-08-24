"""Authenticated Control Plane reconciliation command service (ADR 0002)."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane import backlog_reconciliation as backlog
from newsroom.control_plane.command_auth import HERMES_COMMAND_PRINCIPAL
from newsroom.control_plane.graphiti_spend_reconciliation import (
    GRAPHITI_SPEND_RECONCILE_COMMAND_TYPE,
    GraphitiSpendReconciliationReceipt,
    _GraphitiSpendReconciliationCommand,
    _apply_graphiti_spend_reconciliation,
)


class _VerifiedAuthentication(Protocol):
    principal_id: str

    def require_current(self, now: UtcTimestamp) -> None: ...


class _Authenticator(Protocol):
    def authenticate(
        self, proof: object, *, now: UtcTimestamp
    ) -> _VerifiedAuthentication: ...


class ControlPlaneCommandService:
    """Sole direct writer for Control Plane canonical mutation."""

    principal = backlog.COMMAND_SERVICE_PRINCIPAL

    def __init__(
        self,
        *,
        authenticator: _Authenticator,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    ) -> None:
        if authenticator is None:
            raise ValueError("command service requires an authenticator")
        self._authenticator = authenticator
        self._clock = clock

    def reconcile_graphiti_spend(
        self,
        *,
        unpublished_store: str,
        dry_run_plan: Mapping[str, object],
        evaluated_at: datetime,
        idempotency_key: str,
        expected_plan_digest: str,
        proof: AuthenticationProof,
        graph_journal_evidence: Mapping[str, Mapping[str, object]] | None = None,
    ) -> GraphitiSpendReconciliationReceipt:
        """Authenticate and apply one provider-free spend reconciliation plan."""

        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        if authentication.principal_id != HERMES_COMMAND_PRINCIPAL:
            raise PermissionError(
                "Graphiti spend reconciliation requires the Hermes principal"
            )
        return _apply_graphiti_spend_reconciliation(
            unpublished_store,
            dry_run_plan=dry_run_plan,
            evaluated_at=evaluated_at,
            graph_journal_evidence=graph_journal_evidence,
            command=_GraphitiSpendReconciliationCommand(
                caller_principal=authentication.principal_id,
                writer_principal=self.principal,
                command_type=GRAPHITI_SPEND_RECONCILE_COMMAND_TYPE,
                idempotency_key=idempotency_key,
                expected_plan_digest=expected_plan_digest,
            ),
        )

    def reconcile_effective_revision_backlog(
        self,
        *,
        proving_store: str,
        unpublished_store: str,
        dry_run_receipt: Mapping[str, object],
        receipt_path: Path | None = None,
        backup_dir: Path | None = None,
        allow_canonical_mutation: bool = False,
        evaluated_at: datetime | None = None,
        idempotency_key: str,
        expected_mapping_digest: str,
        proof: AuthenticationProof,
        mode: Literal["live"] = "live",
    ) -> backlog.BacklogReconciliationReceipt:
        if mode != "live":
            raise ValueError("command-service mutation is live-only")
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        command = backlog._ReconciliationCommand(
            caller_principal=authentication.principal_id,
            writer_principal=backlog.COMMAND_SERVICE_PRINCIPAL,
            command_type=backlog.RECONCILE_COMMAND_TYPE,
            idempotency_key=idempotency_key,
            expected_mapping_digest=expected_mapping_digest,
        )
        backlog.refuse_canonical_write(
            proving_store, allow_canonical_mutation=allow_canonical_mutation
        )
        backlog.refuse_canonical_write(
            unpublished_store, allow_canonical_mutation=allow_canonical_mutation
        )
        if backup_dir is None:
            raise backlog.BacklogReconciliationError(
                "G3: live migration requires a backup directory"
            )
        backlog._assert_command_authority(command)
        proving_path = Path(proving_store)
        unpublished_path = Path(unpublished_store)
        backup_root = Path(backup_dir)
        store_binding = backlog._store_pair_identity(
            proving_store, unpublished_store
        )

        # Recovery is itself a mutation, so it stays behind authentication.
        backlog._restore_incomplete_dual_store(
            proving_path, unpublished_path, backup_root
        )
        evaluated = backlog._as_utc(evaluated_at or datetime.now(tz=UTC))
        plan, _proving_before, _unpublished_before = backlog._plan_reconciliation(
            proving_store, unpublished_store, evaluated_at=evaluated
        )
        backlog._assert_g2(plan, dry_run_receipt, store_binding=store_binding)
        backlog._assert_command(command, plan, dry_run_receipt)
        completed = backlog._load_completed_command(
            unpublished_store, command, store_binding=store_binding
        )
        if completed is not None:
            backlog._write_receipt(receipt_path, completed)
            return completed

        proving_backup = backup_root / "proving_store.sqlite3"
        unpublished_backup = backup_root / "unpublished_store.sqlite3"
        proving_backup_result = backlog._backup_store(proving_path, proving_backup)
        unpublished_backup_result = backlog._backup_store(
            unpublished_path, unpublished_backup
        )
        coordinator: dict[str, object] = {
            "mapping_digest": plan.mapping_digest,
            "idempotency_key": command.idempotency_key,
            "proving_store": backlog._store_identity(proving_path),
            "unpublished_store": backlog._store_identity(unpublished_path),
            "proving_backup": str(proving_backup.resolve()),
            "unpublished_backup": str(unpublished_backup.resolve()),
            "proving_backup_digest": proving_backup_result["digest"],
            "unpublished_backup_digest": unpublished_backup_result["digest"],
        }
        coordinator_path = backup_root / backlog.COORDINATOR_NAME
        backlog._write_coordinator(
            coordinator_path, {**coordinator, "status": "STARTED"}
        )

        def apply_mutations() -> tuple[int, backlog.BacklogReconciliationReceipt]:
            conn: sqlite3.Connection | None = sqlite3.connect(str(unpublished_path))
            try:
                backlog.apply_control_plane_sqlite_profile(conn, wal=False)
                conn.execute("ATTACH DATABASE ? AS proving", (str(proving_path),))
                backlog.apply_control_plane_sqlite_profile(
                    conn, wal=False, schema=backlog.PROVING_ATTACH_SCHEMA
                )

                def versions() -> tuple[int, int]:
                    return (
                        int(conn.execute("PRAGMA main.data_version").fetchone()[0]),
                        int(conn.execute("PRAGMA proving.data_version").fetchone()[0]),
                    )

                before_plan_versions = versions()
                live_plan = backlog._build_plan(
                    conn,
                    conn,
                    evaluated_at=evaluated,
                    proving_schema=backlog.PROVING_ATTACH_SCHEMA,
                )
                if versions() != before_plan_versions:
                    raise backlog.BacklogReconciliationError(
                        "G2: stores changed while planning"
                    )
                backlog._assert_g1(live_plan)
                backlog._assert_g2(
                    live_plan, dry_run_receipt, store_binding=store_binding
                )
                backlog._assert_g5(live_plan)
                backlog._assert_command(command, live_plan, dry_run_receipt)
                proving_before = backlog._census_proving(
                    conn, schema=backlog.PROVING_ATTACH_SCHEMA
                )
                unpublished_before = backlog._census_unpublished(conn)
                conn.execute("BEGIN IMMEDIATE")
                if versions() != before_plan_versions:
                    raise backlog.BacklogReconciliationError(
                        "G2: stores changed before mutation"
                    )
                deadline = time.monotonic() + backlog.LIVE_TRANSACTION_TIMEOUT_SECONDS
                conn.set_progress_handler(lambda: time.monotonic() >= deadline, 1_000)
                backlog._ensure_landed_schema(conn)
                remapped = backlog._apply_proving(
                    conn, live_plan, schema=backlog.PROVING_ATTACH_SCHEMA
                )
                remapped += backlog._apply_remap_rows(conn, live_plan)
                no_loss = backlog._no_loss_proof(
                    proving_before=proving_before,
                    unpublished_before=unpublished_before,
                    proving_after=backlog._census_proving(
                        conn, schema=backlog.PROVING_ATTACH_SCHEMA
                    ),
                    unpublished_after=backlog._census_unpublished(conn),
                )
                if no_loss["lost"]:
                    raise backlog.BacklogReconciliationError(
                        "G3: append-only census lost records"
                    )
                rerun_changes = backlog._apply_proving(
                    conn, live_plan, schema=backlog.PROVING_ATTACH_SCHEMA
                ) + backlog._apply_remap_rows(conn, live_plan)
                if rerun_changes:
                    raise backlog.BacklogReconciliationError(
                        "G4: rerun produced further remapping"
                    )
                receipt = backlog._receipt_from_plan(
                    live_plan,
                    mode="live",
                    mutated=True,
                    remapped_count=remapped,
                    no_loss_proof=no_loss,
                    gates={key: "pass" for key in ("G1", "G2", "G3", "G4", "G5")},
                    store_binding=store_binding,
                    command=command.as_dict(),
                )
                backlog._retain_receipt(conn, receipt.as_dict())
                backlog._record_command(conn, command, receipt)
                conn.commit()
                return remapped, receipt
            except Exception as exc:
                if conn is not None and conn.in_transaction:
                    conn.rollback()
                if conn is not None:
                    conn.close()
                    conn = None
                if isinstance(exc, sqlite3.OperationalError) and "interrupted" in str(
                    exc
                ):
                    raise backlog.BacklogReconciliationError(
                        "live reconciliation exceeded the five-second transaction limit"
                    ) from exc
                raise
            finally:
                if conn is not None:
                    conn.set_progress_handler(None, 0)
                    conn.close()

        try:
            backlog._set_journal_mode(proving_path, "DELETE")
            backlog._set_journal_mode(unpublished_path, "DELETE")
            remapped, receipt = apply_mutations()
        except Exception:
            backlog._restore_wal_profiles(proving_path, unpublished_path)
            backlog._write_coordinator(
                coordinator_path, {**coordinator, "status": "ABORTED"}
            )
            raise
        coordinator["remapped_count"] = remapped
        backlog._write_coordinator(
            coordinator_path, {**coordinator, "status": "COMMITTED"}
        )
        backlog._restore_wal_profiles(proving_path, unpublished_path)
        backlog._write_coordinator(
            coordinator_path, {**coordinator, "status": "COMPLETE"}
        )
        backlog._write_receipt(receipt_path, receipt)
        return receipt


__all__ = ["ControlPlaneCommandService"]
