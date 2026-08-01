from __future__ import annotations

import sys

from . import _workflow_lane_impl as _implementation


# Importers receive the reviewed implementation module itself, so normal
# imports, direct implementation execution, reloads, monkeypatches and the
# stable public CLI all use the same permanent scheduler defaults.
if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation