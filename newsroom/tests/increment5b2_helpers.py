from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.neo4j_fulltext_reader import (
    Neo4jFullTextReadError,
    Neo4jFullTextReadPhase,
    Neo4jFullTextReadRequest,
    Neo4jFullTextReadResult,
    Neo4jFullTextReadTimeout,
    Neo4jFullTextReader,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.increment5.branch_contracts import BranchReceiptId, BranchRequestId
from newsroom.increment5.fulltext_contracts import (
    FULLTEXT_ACTOR_ID,
    FULLTEXT_ANALYZER,
    FULLTEXT_COMPONENT_DIGEST,
    FULLTEXT_INDEXED_FIELDS,
    FULLTEXT_POLICY_ID,
    FULLTEXT_PROVIDER,
    FULLTEXT_PURPOSE,
    INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
    NORMALIZATION_COMPONENT_DIGEST,
    AuthorityAliasTerm,
    FullTextAuthorityView,
    FullTextBranchRequest,
    FullTextDocumentBinding,
    FullTextIndexState,
    FullTextLanguageMode,
    FullTextProfile,
    FullTextProjectionSnapshot,
)
from newsroom.increment5.fulltext_journal import FullTextReceiptJournal
from newsroom.increment5.fulltext_retriever import FullTextRetriever
from newsroom.projection.models import ProjectionGenerationId, ProjectionGenerationState
from newsroom.projection.neo4j._adapter import (
    _COMPONENT_QUERY,
    _FULLTEXT_INDEX_INVENTORY_QUERY,
    _FULLTEXT_READ_QUERY,
)
from newsroom.projection.neo4j.models import Neo4jProjectorConfig


NOW = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
EARLIER = UtcTimestamp.parse("2042-03-12T11:30:00.000000Z")
LATER = UtcTimestamp.parse("2042-03-12T12:30:00.000000Z")
GENERATION_ID = ProjectionGenerationId.parse(
    "00000000-0000-4000-8000-000000005220"
)


def digest(label: str) -> str:
    return digest_canonical({"label": label})


def snapshot(**changes: object) -> FullTextProjectionSnapshot:
    value = FullTextProjectionSnapshot(
        generation_id=GENERATION_ID,
        generation_state=ProjectionGenerationState.ACTIVE,
        generation_identity_digest=digest("fulltext-generation"),
        document_label="NewsroomIncrement5FullText_g5220",
        index_name="newsroom_increment5_fulltext_g5220",
        index_state=FullTextIndexState.ONLINE,
        fulltext_component_digest=FULLTEXT_COMPONENT_DIGEST,
        normalization_component_digest=NORMALIZATION_COMPONENT_DIGEST,
        rights_manifest_digest=digest("rights-manifest"),
        profile=FullTextProfile.PRODUCTION_SHAPED_QUALIFICATION,
        contiguous_ledger_seq=42,
        open_gap_count=0,
        dead_letter_count=0,
        validation_recorded_at=EARLIER,
        freshness_deadline=LATER,
        index_document_count=4,
    )
    return replace(value, **changes)


def aliases() -> tuple[AuthorityAliasTerm, ...]:
    return (
        AuthorityAliasTerm(
            alias_id="alias-expired",
            surface_text="Expired Authority",
            normalized_text="expired authority",
            valid_from=EARLIER,
            valid_until=NOW,
            rights_current=True,
            lifecycle="ACTIVE",
        ),
        AuthorityAliasTerm(
            alias_id="alias-synthetic-authority",
            surface_text="Synthetic Authority",
            normalized_text="synthetic authority",
            valid_from=EARLIER,
            valid_until=LATER,
            rights_current=True,
            lifecycle="ACTIVE",
        ),
    )


def bindings() -> tuple[FullTextDocumentBinding, ...]:
    return (
        FullTextDocumentBinding(
            passage_id="p-blocked",
            dependency_root_id="root-blocked",
            source_identity="source-blocked:revision-1",
            provenance_digest=digest("document-blocked"),
            language="en-GB",
            rights_current=False,
            lifecycle="ACTIVE",
        ),
        FullTextDocumentBinding(
            passage_id="p-en",
            dependency_root_id="root-en",
            source_identity="source-en:revision-1",
            provenance_digest=digest("document-en"),
            language="en-GB",
            rights_current=True,
            lifecycle="ACTIVE",
            valid_from=EARLIER,
            valid_until=LATER,
        ),
        FullTextDocumentBinding(
            passage_id="p-tomb",
            dependency_root_id="root-tomb",
            source_identity="source-tomb:revision-1",
            provenance_digest=digest("document-tomb"),
            language="en-GB",
            rights_current=True,
            lifecycle="TOMBSTONED",
        ),
        FullTextDocumentBinding(
            passage_id="p-zh",
            dependency_root_id="root-zh",
            source_identity="source-zh:revision-1",
            provenance_digest=digest("document-zh"),
            language="zh-HK",
            rights_current=True,
            lifecycle="ACTIVE",
            valid_from=EARLIER,
            valid_until=LATER,
        ),
    )


def authority_view(
    *,
    projection_snapshot: FullTextProjectionSnapshot | None = None,
    authority_aliases: tuple[AuthorityAliasTerm, ...] | None = None,
    document_bindings: tuple[FullTextDocumentBinding, ...] | None = None,
) -> FullTextAuthorityView:
    return FullTextAuthorityView(
        snapshot=projection_snapshot or snapshot(),
        authority_aliases=aliases() if authority_aliases is None else authority_aliases,
        document_bindings=bindings() if document_bindings is None else document_bindings,
    )


def request(**changes: object) -> FullTextBranchRequest:
    value = FullTextBranchRequest(
        request_id=BranchRequestId.parse(
            "00000000-0000-4000-8000-000000005221"
        ),
        idempotency_key="fulltext-request-a",
        actor_id=FULLTEXT_ACTOR_ID,
        purpose=FULLTEXT_PURPOSE,
        policy_id=FULLTEXT_POLICY_ID,
        contract_digest=INCREMENT5_RETRIEVAL_CONTRACT_DIGEST,
        fulltext_component_digest=FULLTEXT_COMPONENT_DIGEST,
        normalization_component_digest=NORMALIZATION_COMPONENT_DIGEST,
        expected_generation_id=GENERATION_ID,
        expected_generation_identity_digest=digest("fulltext-generation"),
        expected_rights_manifest_digest=digest("rights-manifest"),
        query_text="Synthetic Authority deadline 27 March 2042 合成網上平台",
        language_mode=FullTextLanguageMode.MIXED_EN_GB_ZH_HANT_HK,
        query_valid_time=NOW,
        serving_time=NOW,
        minimum_watermark=42,
    )
    return replace(value, **changes)


def component_row(
    *,
    version: str = "2026.06.0",
    edition: str = "community",
) -> dict[str, object]:
    return {"version": version, "edition": edition}


def index_row(
    projection_snapshot: FullTextProjectionSnapshot | None = None,
    *,
    state: str = "ONLINE",
    provider: str = FULLTEXT_PROVIDER,
    analyzer: str = FULLTEXT_ANALYZER,
    eventually_consistent: bool = False,
    properties: tuple[str, ...] = FULLTEXT_INDEXED_FIELDS,
) -> dict[str, object]:
    current = projection_snapshot or snapshot()
    return {
        "name": current.index_name,
        "type": "FULLTEXT",
        "state": state,
        "entityType": "NODE",
        "labelsOrTypes": [current.document_label],
        "properties": list(properties),
        "indexProvider": provider,
        "options": {
            "indexConfig": {
                "fulltext.analyzer": analyzer,
                "fulltext.eventually_consistent": eventually_consistent,
            }
        },
    }


def result_row(
    passage_id: str,
    score: float,
    *,
    projection_snapshot: FullTextProjectionSnapshot | None = None,
    document_digest: str | None = None,
    language: str | None = None,
) -> dict[str, object]:
    current = projection_snapshot or snapshot()
    binding = {item.passage_id: item for item in bindings()}[passage_id]
    return {
        "generation_id": str(current.generation_id),
        "passage_id": passage_id,
        "document_digest": document_digest or binding.provenance_digest,
        "language": language or binding.language,
        "score": score,
    }


class FakeResult(list[dict[str, object]]):
    def single(self) -> dict[str, object] | None:
        if not self:
            return None
        return self[0]


@dataclass
class FakeScenario:
    component: dict[str, object] | None
    indexes: list[dict[str, object]]
    rows: list[dict[str, object]]
    failure_on: str | None = None


class FakeTransaction:
    def __init__(
        self,
        scenario: FakeScenario,
        calls: list[tuple[str, dict[str, object]]],
    ) -> None:
        self._scenario = scenario
        self._calls = calls

    def run(
        self,
        statement: str,
        parameters: dict[str, object] | None = None,
    ) -> FakeResult:
        values = parameters or {}
        self._calls.append((statement, dict(values)))
        if statement == _COMPONENT_QUERY:
            if self._scenario.failure_on == "component":
                raise RuntimeError("component read failed")
            return FakeResult(
                [] if self._scenario.component is None else [self._scenario.component]
            )
        if statement == _FULLTEXT_INDEX_INVENTORY_QUERY:
            if self._scenario.failure_on == "index":
                raise RuntimeError("index read failed")
            return FakeResult(self._scenario.indexes)
        if statement == _FULLTEXT_READ_QUERY:
            if self._scenario.failure_on == "query":
                raise RuntimeError("query timed out")
            return FakeResult(self._scenario.rows)
        raise AssertionError(f"unexpected Neo4j statement: {statement}")


class FakeSession:
    def __init__(self, driver: "FakeDriver") -> None:
        self._driver = driver

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute_read(self, work: Any) -> Any:
        self._driver.execute_read_count += 1
        transaction = FakeTransaction(
            self._driver.scenario,
            self._driver.calls,
        )
        return work(transaction)


class FakeDriver:
    def __init__(self, scenario: FakeScenario) -> None:
        self.scenario = scenario
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.session_count = 0
        self.execute_read_count = 0
        self.read_requests: list[Neo4jFullTextReadRequest] = []
        self.closed = False

    def session(self, *, database: str) -> FakeSession:
        assert database == "neo4j"
        self.session_count += 1
        return FakeSession(self)

    def reader(self, *, driver_version: str = "6.2.0") -> Neo4jFullTextReader:
        return Neo4jFullTextReader(
            driver_version=driver_version,
            read=lambda request: self._read_port(
                request,
                driver_version=driver_version,
            ),
            close=self.close,
        )

    def _read_port(
        self,
        request: Neo4jFullTextReadRequest,
        *,
        driver_version: str,
    ) -> Neo4jFullTextReadResult:
        if not isinstance(request, Neo4jFullTextReadRequest):
            raise TypeError("fake full-text read request must be typed")
        self.session_count += 1
        self.read_requests.append(request)
        transaction = FakeTransaction(self.scenario, self.calls)
        try:
            self.execute_read_count += 1
            if request.phase is Neo4jFullTextReadPhase.COMPONENT:
                return Neo4jFullTextReadResult(
                    phase=request.phase,
                    component=transaction.run(_COMPONENT_QUERY).single(),
                    driver_version=driver_version,
                )
            if request.phase is Neo4jFullTextReadPhase.INDEX:
                return Neo4jFullTextReadResult(
                    phase=request.phase,
                    indexes=tuple(
                        transaction.run(
                            _FULLTEXT_INDEX_INVENTORY_QUERY,
                            {"index_name": request.index_name},
                        )
                    ),
                    driver_version=driver_version,
                )
            return Neo4jFullTextReadResult(
                phase=request.phase,
                rows=tuple(
                    transaction.run(
                        _FULLTEXT_READ_QUERY,
                        {
                            "index_name": request.index_name,
                            "query": request.lucene_expression,
                            "generation_id": str(request.generation_id),
                            "limit": request.limit,
                        },
                    )
                ),
                driver_version=driver_version,
            )
        except Exception as exc:
            if "timeout" in str(exc).lower() or "terminated" in str(exc).lower():
                raise Neo4jFullTextReadTimeout(
                    "fake full-text read timed out"
                ) from None
            raise Neo4jFullTextReadError(
                "fake full-text read is unavailable"
            ) from None

    def close(self) -> None:
        self.closed = True


class RecordingUnitOfWorkFactory:
    def __init__(self) -> None:
        self.options: list[dict[str, object]] = []

    def __call__(self, **options: object):
        self.options.append(dict(options))

        def decorate(callback: Any) -> Any:
            return callback

        return decorate


class SequenceClock:
    def __init__(self, values: tuple[int, ...]) -> None:
        self._values = iter(values)
        self._last = values[-1]

    def __call__(self) -> int:
        try:
            self._last = next(self._values)
        except StopIteration:
            pass
        return self._last


def config() -> Neo4jProjectorConfig:
    return Neo4jProjectorConfig(
        uri="bolt://neo4j.invalid:7687",
        database="neo4j",
        username="newsroom_reader",
        password="not-a-real-secret",
    )


def default_scenario(
    *,
    projection_snapshot: FullTextProjectionSnapshot | None = None,
    rows: list[dict[str, object]] | None = None,
) -> FakeScenario:
    current = projection_snapshot or snapshot()
    return FakeScenario(
        component=component_row(version=current.server_version),
        indexes=[index_row(current)],
        rows=(
            [
                result_row("p-en", 2.0, projection_snapshot=current),
                result_row("p-zh", 1.5, projection_snapshot=current),
            ]
            if rows is None
            else rows
        ),
    )


def system(
    tmp_path: Path,
    *,
    view: FullTextAuthorityView | None = None,
    scenario: FakeScenario | None = None,
    clock: Any | None = None,
    provider: Any | None = None,
    receipt_ids: tuple[str, ...] = (
        "00000000-0000-4000-8000-000000005231",
        "00000000-0000-4000-8000-000000005232",
        "00000000-0000-4000-8000-000000005233",
    ),
) -> tuple[FakeDriver, RecordingUnitOfWorkFactory, FullTextRetriever]:
    current_view = view or authority_view()
    driver = FakeDriver(scenario or default_scenario(
        projection_snapshot=current_view.snapshot
    ))
    factory = RecordingUnitOfWorkFactory()
    ids = iter(BranchReceiptId.parse(item) for item in receipt_ids)
    retriever = FullTextRetriever(
        graph_reader=driver.reader(),
        journal=FullTextReceiptJournal(tmp_path / "fulltext-receipts.sqlite3"),
        authority_view_provider=provider or (lambda _request: current_view),
        receipt_id_factory=lambda: next(ids),
        monotonic_ns=clock or (lambda: 0),
    )
    return driver, factory, retriever


__all__ = [
    "EARLIER",
    "GENERATION_ID",
    "LATER",
    "NOW",
    "FakeDriver",
    "FakeScenario",
    "RecordingUnitOfWorkFactory",
    "SequenceClock",
    "aliases",
    "authority_view",
    "bindings",
    "component_row",
    "config",
    "default_scenario",
    "digest",
    "index_row",
    "request",
    "result_row",
    "snapshot",
    "system",
]
