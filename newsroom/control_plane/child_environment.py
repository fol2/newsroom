"""Environment boundary for non-controller child processes."""

from __future__ import annotations

import os

_CONTROLLER_ONLY_ENVIRONMENT = frozenset({"NEWSROOM_EVIDENCE_APPROVAL_KEY"})


def unprivileged_child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in _CONTROLLER_ONLY_ENVIRONMENT:
        environment.pop(name, None)
    return environment
