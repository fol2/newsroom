"""Run the exact Tier-M sandbox repair against the current canonical head."""
from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.support import fix_increment5b_tierm_sandbox_env as repair


if __name__ == "__main__":
    repair.EXPECTED_HEAD = "ad2d2b324d148a798433ad8bec4adeaf92f3a621"
    repair.main()
