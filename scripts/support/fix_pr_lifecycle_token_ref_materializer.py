from __future__ import annotations

from pathlib import Path


path = Path(__file__).with_name("apply_pr_lifecycle_token_ref_binding.py")
text = path.read_text(encoding="utf-8")
old = '''    replace_once(
        workflow,
        """    permissions:\\n      contents: read\\n      pull-requests: read\\n    runs-on: ubuntu-latest\\n    steps:\\n""",
        """    permissions:\\n      contents: read\\n      pull-requests: read\\n    runs-on: ubuntu-latest\\n    env:\\n      GITHUB_TOKEN: ${{ github.token }}\\n    steps:\\n""",
    )
'''
new = '''    replace_once(
        workflow,
        """  inventory-dry-run:\\n    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'\\n    permissions:\\n      contents: read\\n      pull-requests: read\\n    runs-on: ubuntu-latest\\n    steps:\\n""",
        """  inventory-dry-run:\\n    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'\\n    permissions:\\n      contents: read\\n      pull-requests: read\\n    runs-on: ubuntu-latest\\n    env:\\n      GITHUB_TOKEN: ${{ github.token }}\\n    steps:\\n""",
    )
'''
if text.count(old) != 1:
    raise SystemExit("lifecycle materializer dry-run anchor differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
