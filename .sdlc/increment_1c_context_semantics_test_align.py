from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("newsroom/tests/test_integrated_c1_proof_integrity.py")
    text = path.read_text(encoding="utf-8")
    old = '''def test_context_digest_binds_authoritative_serving_time() -> None:
    current = context()
    changed = replace(
        current,
        metadata=replace(
            current.metadata,
            serving_time=UtcTimestamp.parse(
                "2026-07-24T08:01:00.000000Z"
            ),
        ),
    )
    assert changed.context_digest != current.context_digest
'''
    new = '''def test_context_digest_binds_authoritative_serving_time() -> None:
    current = context()
    serving_time = UtcTimestamp.parse(
        "2026-07-24T08:01:00.000000Z"
    )
    changed = replace(
        current,
        metadata=replace(
            current.metadata,
            serving_time=serving_time,
        ),
        recorded_at=serving_time,
    )
    assert changed.context_digest != current.context_digest
'''
    if text.count(old) != 1 or new in text:
        raise SystemExit("proof-integrity serving-time test source mismatch")
    path.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
