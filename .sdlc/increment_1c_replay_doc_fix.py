from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("docs/operations/increment-1c-integrated-foundation.md")
    text = path.read_text(encoding="utf-8")
    old = "It must never be interpreted as “no prior match.”"
    new = "It must never be interpreted as “no prior match”."
    if text.count(old) != 1 or new in text:
        raise SystemExit("integrated operating evidence differs from expected")
    path.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
