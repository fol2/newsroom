#!/usr/bin/env python3
"""Disposable wrapper that closes the derived-count invariant."""
from __future__ import annotations

import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(
    str(Path(__file__).with_name("_staging_increment5_no_site_composer_v2.py")),
    run_name="__main__",
)

path = ROOT / "newsroom/increment5/traceability.py"
text = path.read_text(encoding="utf-8")
old = '''        Increment5DeliveryTrace.DEFERRED_TO_5C: 4,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 11,
'''
new = '''        Increment5DeliveryTrace.DEFERRED_TO_5C: 2,
        Increment5DeliveryTrace.DEFERRED_TO_5D: 13,
'''
if text.count(old) != 1:
    raise RuntimeError("traceability count invariant source differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

manifest_path = ROOT / "increment5a-no-site-composer-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
product_paths = list(manifest["product_paths"])
traceability_path = "newsroom/increment5/traceability.py"
if traceability_path in product_paths:
    raise RuntimeError("traceability runtime path already present")
product_paths.insert(product_paths.index("newsroom/increment5/_traceability_model.py") + 1, traceability_path)
manifest["product_paths"] = product_paths
manifest_path.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
