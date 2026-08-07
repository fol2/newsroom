"""Preflight exact new-blob identities, then run the v2 publisher."""
from __future__ import annotations

import re

from scripts.support import publish_increment5c2_authority_tools_v2 as publisher

_EXPECTED_NEW_BLOBS = {
    "newsroom/increment5/named_tool_authority_adapters.py": "519d197",
    "newsroom/increment5/named_tool_authority_execution.py": "ea00822",
    "newsroom/tests/test_increment5c2_named_tool_authority_execution.py": "b2b5607",
}


def _verify_patch_blobs(patch: bytes) -> None:
    text = patch.decode("utf-8")
    blocks = re.split(r"(?=^diff --git )", text, flags=re.MULTILINE)
    actual: dict[str, str] = {}
    for block in blocks:
        if not block.startswith("diff --git "):
            continue
        header = block.splitlines()
        match = re.fullmatch(r"diff --git a/(.+) b/(.+)", header[0])
        if match is None or match.group(1) != match.group(2):
            raise SystemExit("authority-tools patch path header is malformed")
        path = match.group(1)
        if path not in _EXPECTED_NEW_BLOBS:
            raise SystemExit(f"authority-tools patch contains an unexpected path: {path}")
        if "new file mode 100644" not in header[:4]:
            raise SystemExit(f"authority-tools patch mode is not 100644: {path}")
        index_rows = [line for line in header[:5] if line.startswith("index ")]
        if len(index_rows) != 1:
            raise SystemExit(f"authority-tools patch index is not exact: {path}")
        index_match = re.fullmatch(r"index 0000000\.\.([0-9a-f]{7})(?: 100644)?", index_rows[0])
        if index_match is None:
            raise SystemExit(f"authority-tools patch is not a pure new-file atom: {path}")
        actual[path] = index_match.group(1)
    if actual != _EXPECTED_NEW_BLOBS:
        raise SystemExit(f"authority-tools patch blob identities drifted: {actual}")


def main() -> None:
    _manifest, patch = publisher.load_transfer()
    _verify_patch_blobs(patch)
    publisher.main()


if __name__ == "__main__":
    main()
