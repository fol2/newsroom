from __future__ import annotations

import sys

from . import _workflow_lane_impl as _implementation


# Keep one reviewed implementation module while selecting the permanent hosted-
# runner scheduler at the stable public entrypoint.  Importers receive the
# implementation module itself, so existing monkeypatching and identity checks
# continue to exercise the real lane code rather than a proxy surface.
_implementation._CORE_WORKER_COUNT = 6
_implementation._CORE_DISTRIBUTION = "worksteal"

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
