"""In-process command-service authentication for Control Plane mutation.

ADR 0002: only the dedicated command-service identity may be a direct writer.
This token is minted solely by ControlPlaneCommandService.
"""

from __future__ import annotations

COMMAND_SERVICE_PRINCIPAL = "newsroom.control-plane.command-service"
RECONCILE_COMMAND_TYPE = "control_plane.effective_revision_backlog.reconcile"
ISSUER_TOKEN = object()
