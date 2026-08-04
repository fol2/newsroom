#!/usr/bin/env python3
"""Disposable wrapper aligning private test probes with stdin execution."""
from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(
    str(Path(__file__).with_name("_staging_increment5_outer_blob_launcher_v3.py")),
    run_name="__main__",
)

path = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
text = path.read_text(encoding="utf-8")
old_probe = '''import runpy, sys
sys.argv[0] = "-"
namespace = runpy.run_path(sys.argv[1], run_name="validator-probe")
'''
new_probe = '''import sys
from pathlib import Path
sys.argv[0] = "-"
source = Path(sys.argv[1]).read_bytes()
namespace = {"__name__": "validator-probe", "__file__": sys.argv[1]}
exec(compile(source, "-", "exec"), namespace)
'''
if text.count(old_probe) != 1:
    raise RuntimeError("bounded private probe source differs")
text = text.replace(old_probe, new_probe, 1)

old_completion = '''import io, runpy, sys
from pathlib import Path
sys.argv[0] = "-"
namespace = runpy.run_path(sys.argv[1], run_name="validator-completion-probe")
'''
new_completion = '''import io, sys
from pathlib import Path
sys.argv[0] = "-"
source = Path(sys.argv[1]).read_bytes()
namespace = {"__name__": "validator-completion-probe", "__file__": sys.argv[1]}
exec(compile(source, "-", "exec"), namespace)
'''
if text.count(old_completion) != 1:
    raise RuntimeError("completion private probe source differs")
text = text.replace(old_completion, new_completion, 1)

bad = 'bootstrap = source.index("or sys.argv[0] != "-"")'
good = 'bootstrap = source.index(\'or sys.argv[0] != "-"\')'
if text.count(bad) != 1:
    raise RuntimeError("source-boundary assertion differs")
text = text.replace(bad, good, 1)
path.write_text(text, encoding="utf-8")
