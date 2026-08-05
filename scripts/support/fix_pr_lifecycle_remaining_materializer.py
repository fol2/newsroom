from __future__ import annotations

from pathlib import Path


path = Path(__file__).with_name("apply_pr_lifecycle_remaining_review.py")
text = path.read_text(encoding="utf-8")
start = text.find('    docs = "docs/operations/pr-lifecycle.md"\n')
end = text.find('\n\n\nif __name__ == "__main__":', start)
if start < 0 or end < 0:
    raise SystemExit("remaining lifecycle prose block differs")
path.write_text(text[:start] + text[end:], encoding="utf-8")
