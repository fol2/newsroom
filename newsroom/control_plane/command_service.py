"""Authenticated Control Plane command-service (ADR 0002).

Hermes, workers and CLI scripts submit commands here. They do not choose a
caller principal or command type, and they do not open canonical stores.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal

from newsroom.control_plane.backlog_reconciliation import (
    BacklogReconciliationReceipt,
    ReconciliationCommand,
    reconcile_effective_revision_backlog,
)
from newsroom.control_plane.command_auth import (
    COMMAND_SERVICE_PRINCIPAL,
    ISSUER_TOKEN,
    RECONCILE_COMMAND_TYPE,
)


def issue_reconciliation_command(
    *,
    idempotency_key: str,
    expected_mapping_digest: str,
) -> ReconciliationCommand:
    """Stamp the allow-listed command-service identity onto a live command."""

    return ReconciliationCommand(
        caller_principal=COMMAND_SERVICE_PRINCIPAL,
        command_type=RECONCILE_COMMAND_TYPE,
        idempotency_key=idempotency_key,
        expected_mapping_digest=expected_mapping_digest,
        _issuer=ISSUER_TOKEN,
    )


def command_is_authenticated(command: ReconciliationCommand) -> bool:
    return command._issuer is ISSUER_TOKEN


class ControlPlaneCommandService:
    """Sole direct writer for Control Plane canonical mutation."""

    principal = COMMAND_SERVICE_PRINCIPAL

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
        mode: Literal["live"] = "live",
    ) -> BacklogReconciliationReceipt:
        if mode != "live":
            raise ValueError("command-service mutation is live-only")
        command = issue_reconciliation_command(
            idempotency_key=idempotency_key,
            expected_mapping_digest=expected_mapping_digest,
        )
        return reconcile_effective_revision_backlog(
            proving_store=proving_store,
            unpublished_store=unpublished_store,
            mode="live",
            dry_run_receipt=dry_run_receipt,
            receipt_path=receipt_path,
            backup_dir=backup_dir,
            allow_canonical_mutation=allow_canonical_mutation,
            evaluated_at=evaluated_at,
            command=command,
        )
