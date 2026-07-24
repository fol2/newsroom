from __future__ import annotations

from pathlib import Path


def replace_exact(path: Path, old: str, new: str, *, identity: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1 or (new and new in text):
        raise SystemExit(f"{identity} source mismatch")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    replace_exact(
        Path("newsroom/tests/test_integrated_c1_proof_integrity.py"),
        '''def test_context_digest_binds_authoritative_serving_time() -> None:
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
''',
        '''def test_context_digest_binds_authoritative_serving_time() -> None:
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
''',
        identity="proof-integrity serving-time test",
    )
    replace_exact(
        Path("newsroom/integrated/models.py"),
        '''        if any(
            relation.recorded_at.value
            > self.metadata.query_valid_time.value
            for relation in self.relations
        ):
            raise IntegratedStateError(
                "integrated graph relation postdates query-valid time"
            )
''',
        "",
        identity="business-valid relation semantics",
    )


if __name__ == "__main__":
    main()
