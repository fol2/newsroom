#!/usr/bin/env python3
"""Disposable wrapper making the stat-cache attack Git-version independent."""
from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(
    str(Path(__file__).with_name("_staging_increment5_content_addressed_cleanliness_v2.py")),
    run_name="__main__",
)
path = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
text = path.read_text(encoding="utf-8")
old = '''    assert source.stat().st_size == baseline.st_size
    assert _git_text(clone, "status", "--porcelain=v1", "--untracked-files=no") == ""

    completed = _run_isolated_bytes(
'''
new = '''    assert source.stat().st_size == baseline.st_size
    # Git releases differ in whether this adversarial stat configuration hides
    # the edit. The validator must reject the bytes independently either way.
    completed = _run_isolated_bytes(
'''
if text.count(old) != 1:
    raise RuntimeError("version-dependent status assertion differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
