"""Environment boundary for non-controller child processes."""

from __future__ import annotations

import os

_UNPRIVILEGED_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "SHELL",
        "TMPDIR",
        "USER",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)


def unprivileged_child_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if name in _UNPRIVILEGED_ENVIRONMENT_ALLOWLIST
    }
