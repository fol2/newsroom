from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 lock-budget anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/projection/neo4j/_adapter.py",
        """        with self._lock:
            started_ns = self._monotonic_ns()
            if isinstance(started_ns, bool) or not isinstance(started_ns, int):
                raise Neo4jReadError(
                    \"Neo4j Increment 5 monotonic clock is invalid\"
                )
            current_ns = self._monotonic_ns()
""",
        """        started_ns = self._monotonic_ns()
        if isinstance(started_ns, bool) or not isinstance(started_ns, int):
            raise Neo4jReadError(
                \"Neo4j Increment 5 monotonic clock is invalid\"
            )
        with self._lock:
            current_ns = self._monotonic_ns()
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
        """def test_authority_port_maps_server_timeout_to_typed_failure() -> None:
""",
        """class _ClockConsumingLock:
    def __init__(self, clock: SequenceClock) -> None:
        self._clock = clock

    def __enter__(self):
        self._clock()
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_authority_port_charges_lock_wait_to_phase_timeout() -> None:
    clock = SequenceClock((0, 5_000_000_001, 5_000_000_001))
    factory = RecordingUnitOfWorkFactory()
    driver = FakeDriver(default_scenario())
    adapter = _Neo4jAdapter(
        driver=driver,
        config=config(),
        driver_version=\"6.2.0\",
        monotonic_ns=clock,
        unit_of_work_factory=factory,
    )
    adapter._lock = _ClockConsumingLock(clock)
    reader = _open_neo4j_fulltext_reader_with_adapter(adapter)

    with pytest.raises(Neo4jFullTextReadTimeout, match=\"timed out\"):
        reader.read(
            Neo4jFullTextReadRequest.component(
                timeout_ns=5_000_000_000,
            )
        )

    assert factory.options == []
    assert driver.calls == []
    assert driver.execute_read_count == 0


def test_authority_port_maps_server_timeout_to_typed_failure() -> None:
""",
    )


if __name__ == "__main__":
    main()
