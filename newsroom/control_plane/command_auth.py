"""In-process command-service authentication for Control Plane mutation.

ADR 0002: only the dedicated command-service identity may be a direct writer.
Proofs are checked by the configured authority authenticator before the
private reconciliation writer is entered.
"""

from __future__ import annotations

COMMAND_SERVICE_PRINCIPAL = "newsroom.control-plane.command-service"
RECONCILE_COMMAND_TYPE = "control_plane.effective_revision_backlog.reconcile"
