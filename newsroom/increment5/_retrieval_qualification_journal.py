"""First-writer-wins retention for Increment 5E1 qualification reports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sqlite3
import threading

from newsroom.authority.canonical import digest_bytes

from ._retrieval_qualification_common import (
    RetrievalQualificationError,
    require_digest,
)
from ._retrieval_qualification_evidence import QualificationReport


class QualificationReportJournal:
    """Retain PASS, FAIL, and NOT_EVALUATED reports without history rewrite."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("qualification journal path must be pathlib.Path")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS increment5e1_qualification_reports(
                    run_id TEXT PRIMARY KEY,
                    epoch_digest TEXT NOT NULL,
                    report_digest TEXT NOT NULL,
                    report_bytes BLOB NOT NULL
                ) STRICT
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _decode(expected_digest: str, raw: bytes) -> QualificationReport:
        if digest_bytes(raw) != expected_digest:
            raise RetrievalQualificationError(
                "retained qualification report is corrupt"
            )
        return QualificationReport.from_canonical_bytes(raw)

    def execute(
        self,
        *,
        run_id: str,
        epoch_digest: str,
        producer: Callable[[], QualificationReport],
    ) -> QualificationReport:
        require_digest(epoch_digest, field="journal epoch")
        if not callable(producer):
            raise TypeError("qualification report producer must be callable")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT epoch_digest, report_digest, report_bytes
                FROM increment5e1_qualification_reports
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is not None:
                if row[0] != epoch_digest:
                    raise RetrievalQualificationError(
                        "qualification run id is bound to another Epoch"
                    )
                raw = bytes(row[2])
                retained = self._decode(row[1], raw)
                replay = producer()
                if replay.canonical_bytes != raw:
                    raise RetrievalQualificationError(
                        "retained report differs from deterministic replay"
                    )
                return retained
            report = producer()
            if report.run_id != run_id or report.epoch_digest != epoch_digest:
                raise RetrievalQualificationError(
                    "produced report binding differs"
                )
            connection.execute(
                """
                INSERT INTO increment5e1_qualification_reports(
                    run_id,
                    epoch_digest,
                    report_digest,
                    report_bytes
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    epoch_digest,
                    report.report_digest,
                    report.canonical_bytes,
                ),
            )
            connection.commit()
            return report

    def history(self) -> tuple[QualificationReport, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT report_digest, report_bytes
                FROM increment5e1_qualification_reports
                ORDER BY run_id
                """
            ).fetchall()
        return tuple(
            self._decode(expected_digest, bytes(raw))
            for expected_digest, raw in rows
        )
