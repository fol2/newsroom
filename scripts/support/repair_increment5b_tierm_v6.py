"""Run the v5 Tier-M builder with canonical service identity ordering."""
from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.support import repair_increment5b_tierm_v5 as v5


def main() -> None:
    v5.base.FIRST, v5.base.SECOND = tuple(sorted((v5.base.FIRST, v5.base.SECOND)))
    v5.main()


if __name__ == "__main__":
    main()
