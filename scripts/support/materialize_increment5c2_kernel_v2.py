"""Normalize the hardened Increment 5C2 kernel candidate before verification."""
from __future__ import annotations

from scripts.support import materialize_increment5c2_kernel as builder

_ORIGINAL_PATCH = builder.patch


def patch(root):
    _ORIGINAL_PATCH(root)
    tests = root / builder.PRODUCT_FILES[1]
    tests.write_text(tests.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")


builder.patch = patch


if __name__ == "__main__":
    builder.main()
