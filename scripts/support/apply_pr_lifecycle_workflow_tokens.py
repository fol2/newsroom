from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[2] / ".github/workflows/pr-lifecycle.yml"
text = path.read_text(encoding="utf-8")
old_dry = """  inventory-dry-run:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
"""
new_dry = """  inventory-dry-run:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    env:
      GITHUB_TOKEN: ${{ github.token }}
    steps:
"""
old_apply = """    env:
      PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS
"""
new_apply = """    env:
      GITHUB_TOKEN: ${{ github.token }}
      PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS
"""
if text.count(old_dry) != 1 or text.count(old_apply) != 1:
    raise SystemExit("lifecycle workflow token anchors differ")
path.write_text(
    text.replace(old_dry, new_dry, 1).replace(old_apply, new_apply, 1),
    encoding="utf-8",
)
