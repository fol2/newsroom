#!/usr/bin/env python3
"""Disposable wrapper repairing a generated test-source escape."""
from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(
    str(Path(__file__).with_name("_staging_increment5_content_addressed_cleanliness.py")),
    run_name="__main__",
)
path = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
text = path.read_text(encoding="utf-8")
old = '''    assert '"ls-files",
            "-s"' in source
'''
new = '''    assert '"ls-files",\\n            "-s"' in source
'''
if text.count(old) != 1:
    raise RuntimeError("generated ls-files assertion differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
