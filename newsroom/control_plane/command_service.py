"""Authenticated Control Plane reconciliation command service (ADR 0002)."""

from newsroom.control_plane.backlog_reconciliation import (
    _ControlPlaneCommandService as ControlPlaneCommandService,
)

__all__ = ["ControlPlaneCommandService"]
