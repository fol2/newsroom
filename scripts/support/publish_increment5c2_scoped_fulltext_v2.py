"""Bind the scoped full-text repair to the exact support-branch patch blob."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from scripts.support import publish_increment5c2_scoped_fulltext as builder

EXPECTED_PATCH_BLOB_SHA = "a1d6c534b468232456c2ca9bfebb5b2bc271785d"
PATCH_REPOSITORY_PATH = "scripts/support/patches/increment5c2_scoped_fulltext.patch"


def main() -> None:
    actual_blob = subprocess.run(
        ("git", "rev-parse", f"HEAD:{PATCH_REPOSITORY_PATH}"),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if actual_blob != EXPECTED_PATCH_BLOB_SHA:
        raise SystemExit(f"scoped full-text patch blob drifted: {actual_blob}")
    raw = Path(PATCH_REPOSITORY_PATH).read_bytes()
    builder.PATCH_SHA256 = hashlib.sha256(raw).hexdigest()
    builder.main()


if __name__ == "__main__":
    main()
