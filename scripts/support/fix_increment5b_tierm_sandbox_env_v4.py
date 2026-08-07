"""Run the committed-tree Tier-M repair with canonical text boundaries."""
from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.support import fix_increment5b_tierm_sandbox_env as repair
from scripts.support import fix_increment5b_tierm_sandbox_env_v3 as committed

_ORIGINAL_PATCH = repair.patch


def patch(root: Path) -> None:
    _ORIGINAL_PATCH(root)
    focused = root / "newsroom/tests/test_increment5b_tierm_service_reconciliation.py"
    focused.write_text(
        focused.read_text(encoding="utf-8").rstrip() + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    repair.EXPECTED_HEAD = "ad2d2b324d148a798433ad8bec4adeaf92f3a621"
    repair.patch = patch
    repair.verify_and_publish = committed.verify_and_publish
    repair.main()
