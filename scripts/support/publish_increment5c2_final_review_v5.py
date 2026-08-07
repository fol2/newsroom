"""Select the unique digest-bound final 5C2 patch from canonical/repaired chunks."""
from __future__ import annotations

import base64
import hashlib
from itertools import product

from scripts.support import publish_increment5c2_final_review_v4 as publisher


def _text(path) -> str:
    return "".join(path.read_text(encoding="ascii").split())


def _fragment_alternative(name: str) -> str | None:
    fragments = sorted(
        path
        for path in publisher.PART_ROOT.glob(name + ".*")
        if path.name.rsplit(".", 1)[-1].isdigit()
    )
    if not fragments:
        return None
    return "".join(_text(path) for path in fragments)


def rebuild_patch() -> bytes:
    canonical = [_text(publisher.PART_ROOT / name) for name in publisher.PART_NAMES]
    variable_indices = (1, 2, 5)
    choices: list[tuple[str, ...]] = []
    for index in variable_indices:
        alternatives = [canonical[index]]
        fragment = _fragment_alternative(publisher.PART_NAMES[index])
        if fragment is not None and fragment != canonical[index]:
            alternatives.append(fragment)
        choices.append(tuple(alternatives))

    observed: list[str] = []
    for selected in product(*choices):
        parts = list(canonical)
        for index, value in zip(variable_indices, selected, strict=True):
            parts[index] = value
        encoded = "".join(parts)
        try:
            patch = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            observed.append("invalid-base64")
            continue
        digest = hashlib.sha256(patch).hexdigest()
        observed.append(digest)
        if digest == publisher.EXPECTED_PATCH_SHA256:
            publisher.PATCH_PATH.write_bytes(patch)
            return patch
    raise SystemExit(
        "no canonical/repaired 5C2 chunk combination matched the exact patch digest; "
        f"observed={observed}"
    )


def main() -> None:
    publisher.rebuild_patch = rebuild_patch
    publisher.main()


if __name__ == "__main__":
    main()
