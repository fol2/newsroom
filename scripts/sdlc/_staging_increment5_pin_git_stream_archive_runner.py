#!/usr/bin/env python3
"""Run the staging transformer with one disambiguated test-source match."""

from __future__ import annotations

import importlib.util
from pathlib import Path


TRANSFORMER = Path(__file__).with_name(
    "_staging_increment5_pin_git_stream_archive.py"
)
spec = importlib.util.spec_from_file_location(
    "increment5_pinned_git_stream_transformer",
    TRANSFORMER,
)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load staging transformer")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_replace_once = module._replace_once


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if label == "isolated environment call":
        count = text.count(old)
        if count != 2:
            raise RuntimeError(f"{label} replacement count differs: {count}")
        return text.replace(old, new, 1)
    return original_replace_once(text, old, new, label)


module._replace_once = _replace_once
raise SystemExit(module.main())
