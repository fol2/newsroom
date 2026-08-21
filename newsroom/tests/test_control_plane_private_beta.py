from pathlib import Path
import json
import os
from datetime import UTC, datetime

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import EvidencePackage
from newsroom.control_plane.intake import run_intake
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.reports import news_report
from newsroom.control_plane.store import connect, list_payloads, mark_public_dispatch
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, refuse_public_effect
from newsroom.control_plane.writer import (
    CliChainWriter,
    FixtureWriter,
    WriterCopy,
    run_grok_cli,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    EVALUATION_GRAPHITI_PACKET,
    EVALUATION_WORKSPACE_POLICY,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    OPENROUTER_API,
    WRITER_FALLBACK,
    WRITER_MODEL,
)
from newsroom.graphiti_adapter.models import REAL_GRAPHITI_RUNTIME_ENABLED
from newsroom.graphiti_adapter.temporal import OBSERVED_FALLBACK
from newsroom.graphiti_adapter.types import (
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiRuntimeNotAuthorized,
)
from newsroom.increment9.proving import PROVING_GATES, SOURCE_URLS
from newsroom.increment9.rights import (
    BINDINGS,
    FIXTURE_FAMILIES,
    FIXTURE_NOW,
    bound_terms_identity,
    evaluation_rights_destinations,
    fixture_review,
)

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:example:1</id>
    <title>Home Office update</title>
    <link href="https://www.gov.uk/example-1"/>
    <summary>A retained proving item.</summary>
  </entry>
</feed>
"""
RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <guid>hk-1</guid>
    <title>香港政府新聞</title>
    <link>https://www.news.gov.hk/a</link>
    <description>保留來源正文。</description>
  </item>
</channel></rss>
""".encode("utf-8")
JSON_DOC = b'{"title":"BNO visa","base_path":"/british-national-overseas-bno-visa","content_id":"abc","description":"Apply for a visa."}'
SAME_URL_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <guid>rad-1</guid>
    <title>Same event from radio</title>
    <link>https://www.gov.uk/example-1</link>
    <description>Corroborating retained item.</description>
  </item>
</channel></rss>
""".encode("utf-8")


def _proving(tmp_path: Path, extra: tuple[tuple[str, bytes], ...] = ()) -> Path:
    path = tmp_path / "proving_store.sqlite3"
    connection = __import__("sqlite3").connect(path)
    connection.executescript(
        """
        CREATE TABLE proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL DEFAULT 0,
            public_dispatch INTEGER NOT NULL DEFAULT 0,
            openrouter_invoked INTEGER NOT NULL DEFAULT 0,
            spend_gbp_minor INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE proving_observations(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            body_digest TEXT NOT NULL,
            body BLOB NOT NULL,
            item_count INTEGER NOT NULL,
            error TEXT
        );
        CREATE TABLE proving_gates(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
        );
        CREATE TABLE proving_rights_packets(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            packet_digest TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO proving_runs VALUES('run-1','2026-08-16T21:41:34.000000Z',0,0,0,0)"
    )
    rows = (
        (
            "UK-01",
            SOURCE_URLS["UK-01"],
            "sha256:feed",
            ATOM,
        ),
        (
            "HK-01",
            "https://www.news.gov.hk/tc/common/html/topstories.rss.xml",
            "sha256:rss",
            RSS,
        ),
        (
            "UK-02",
            "https://www.gov.uk/api/content/british-national-overseas-bno-visa",
            "sha256:json",
            JSON_DOC,
        ),
        *tuple(
            (
                source_id,
                BINDINGS[f"RIGHTS_{source_id}"][2],
                f"sha256:{source_id}",
                body,
            )
            for source_id, body in extra
        ),
    )
    for source_id, url, digest, body in rows:
        connection.execute(
            "INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                "run-1",
                "2026-08-16T21:41:34.000000Z",
                url,
                200,
                digest,
                body,
                1,
                None,
            ),
        )
    for gate_id in PROVING_GATES:
        if gate_id.startswith("RIGHTS_"):
            continue
        connection.execute(
            "INSERT INTO proving_gates VALUES(?,?,?,?)",
            ("run-1", gate_id, "PASS", "fixture"),
        )
    for source_id, _url, _digest, _body in rows:
        gate_id = f"RIGHTS_{source_id}"
        connection.execute(
            "INSERT INTO proving_gates VALUES(?,?,?,?)",
            ("run-1", gate_id, "PASS", "fixture"),
        )
        packet = {
            "bound_terms": bound_terms_identity(gate=gate_id),
            "now": "2026-08-20T00:00:00.000000Z",
            "reviews": [
                fixture_review(
                    family,
                    gate=gate_id,
                    issued_at="2026-01-01T00:00:00.000000Z",
                    expires_at="2099-01-01T00:00:00.000000Z",
                    destinations=list(evaluation_rights_destinations()),
                )
                for family in FIXTURE_FAMILIES
            ],
        }
        packet_bytes = canonical_json_bytes(packet)
        connection.execute(
            "INSERT INTO proving_rights_packets VALUES(?,?,?,?,?)",
            (
                "run-1",
                gate_id,
                digest_bytes(packet_bytes),
                packet_bytes.decode("utf-8"),
                "2026-08-20T00:00:00.000000Z",
            ),
        )
    connection.commit()
    connection.close()
    return path


def test_veto_refuses_public_intents() -> None:
    with pytest.raises(VetoError, match="AUTO_PUBLISH"):
        refuse_public_effect("AUTO_PUBLISH")
    with pytest.raises(VetoError, match="IAP"):
        refuse_public_effect("IAP")
    refuse_public_effect("PRIVATE_CYCLE_START")


def test_parsers_extract_atom_rss_and_json() -> None:
    atom = parse_observation(
        source_id="UK-01", url="https://www.gov.uk/search/all.atom", body=ATOM
    )
    assert atom[0].headline == "Home Office update"
    assert atom[0].canonical_url == "https://www.gov.uk/example-1"
    rss = parse_observation(
        source_id="HK-01",
        url="https://www.news.gov.hk/tc/common/html/topstories.rss.xml",
        body=RSS,
    )
    assert rss[0].headline == "香港政府新聞"
    json_item = parse_observation(
        source_id="UK-02",
        url="https://www.gov.uk/api/content/british-national-overseas-bno-visa",
        body=JSON_DOC,
    )
    assert json_item[0].headline == "BNO visa"
    assert json_item[0].canonical_url.endswith("/british-national-overseas-bno-visa")


def test_cycle_mints_unpublished_payloads_with_evidence(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    writer = FixtureWriter()
    first = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=writer,
        max_writes=10,
    )
    assert first.proving_run_id == "run-1"
    assert first.minted == 3
    assert first.duplicate == 0
    assert first.candidates == 3
    assert first.writer_id == writer.writer_id
    payloads = list_payloads(str(unpublished))
    assert len(payloads) == 3
    assert {item.status for item in payloads} == {"UNPUBLISHED"}
    assert {item.language for item in payloads} == {"ZH_HANT_HK"}
    assert all(item.evidence_package_digest.startswith("sha256:") for item in payloads)
    assert all(item.publication_bundle is False for item in payloads)
    assert all(item.auto_publish is False for item in payloads)
    assert all(not item.body.startswith("London —") for item in payloads)
    second = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=writer,
        max_writes=10,
    )
    assert second.minted == 0
    assert second.duplicate == 3
    assert len(list_payloads(str(unpublished))) == 3


def test_cycle_continues_after_one_writer_failure(tmp_path: Path) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"

    class FlakyWriter:
        writer_id = "test-flaky-writer"

        def __init__(self) -> None:
            self.calls = 0

        def write(
            self, candidate: StoryCandidateRecord, package: EvidencePackage
        ) -> WriterCopy:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("grok writer timed out")
            return FixtureWriter().write(candidate, package)

    writer = FlakyWriter()
    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=writer,
        max_writes=10,
    )
    assert writer.calls >= 2
    assert report.minted == 2
    assert report.candidates == 3
    payloads = list_payloads(str(unpublished))
    assert len(payloads) == 2
    assert all(item.auto_publish is False for item in payloads)
    assert all(item.status == "UNPUBLISHED" for item in payloads)


def test_same_event_url_consolidates_to_one_candidate(tmp_path: Path) -> None:
    proving = _proving(tmp_path, extra=(("RAD-01", SAME_URL_RSS),))
    unpublished = tmp_path / "unpublished_store.sqlite3"
    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=10,
    )
    assert report.candidates == 3
    payloads = list_payloads(str(unpublished))
    home = [item for item in payloads if "UK-01" in item.source_lineage]
    assert len(home) == 1
    assert "RAD-01" in home[0].source_lineage


def test_cycle_reserves_graphiti_spend_before_stub_extract(tmp_path: Path) -> None:
    from newsroom.control_plane.graphiti import GraphitiCycleResult

    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[str] = []

    class StubGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(unit.ingest_id)
            return GraphitiCycleResult(
                ingest_id=unit.ingest_id,
                source_id=unit.source_id,
                item_key=unit.item_key,
                outcome="COMPLETE",
                proposal_count=2,
                entity_count=2,
                relation_count=0,
                failure_code="NONE",
                temporal_basis=OBSERVED_FALLBACK,
                reference_time=unit.observed_at,
                attempt_number=unit.attempt_number,
                provider_attempt_number=unit.attempt_number,
            )

    first = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=10,
        graphiti=StubGraphiti(),
        max_graphiti=1,
    )
    assert first.graphiti == 1
    assert first.minted == 3
    assert len(calls) == 1
    connection = __import__("sqlite3").connect(unpublished)
    kinds = [row[0] for row in connection.execute("SELECT kind FROM ledger ORDER BY seq")]
    connection.close()
    assert kinds.count("GRAPHITI_SPEND_RESERVE") == 1
    assert kinds.count("GRAPHITI_SPEND_RECONCILE") == 1
    assert kinds.count("GRAPHITI_EVALUATION_ATTEMPT") == 1
    assert kinds.index("GRAPHITI_SPEND_RESERVE") < kinds.index("GRAPHITI_EVALUATION_ATTEMPT")
    second = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=10,
        graphiti=StubGraphiti(),
        max_graphiti=1,
    )
    assert second.graphiti == 1
    assert len(calls) == 2
    connection = __import__("sqlite3").connect(unpublished)
    kinds = [row[0] for row in connection.execute("SELECT kind FROM ledger ORDER BY seq")]
    connection.close()
    assert kinds.count("GRAPHITI_SPEND_RESERVE") == 2
    assert kinds.count("GRAPHITI_SPEND_RECONCILE") == 2
    assert kinds.count("GRAPHITI_EVALUATION_ATTEMPT") == 2


def test_cycle_retries_failed_graphiti_extract(tmp_path: Path) -> None:
    from newsroom.control_plane.graphiti import GraphitiCycleResult
    from newsroom.tests.test_graphiti_corpus_ingest import _complete

    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    calls: list[str] = []

    class FlakyGraphiti:
        def ingest(self, unit: CorpusIngestUnit) -> GraphitiCycleResult:
            calls.append(unit.ingest_id)
            if len(calls) == 1:
                raise RuntimeError("provider failed before returning a result")
            return _complete(unit)

    first = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=10,
        graphiti=FlakyGraphiti(),
        max_graphiti=1,
    )
    assert first.graphiti == 1
    connection = __import__("sqlite3").connect(unpublished)
    stored = connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_ingest"
    ).fetchone()[0]
    connection.close()
    assert stored == 0
    second = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        max_writes=10,
        graphiti=FlakyGraphiti(),
        max_graphiti=1,
    )
    assert second.graphiti == 1
    assert calls[0] == calls[1]
    connection = __import__("sqlite3").connect(unpublished)
    stored = connection.execute(
        "SELECT outcome, proposal_count FROM unpublished_graphiti_ingest"
    ).fetchone()
    connection.close()
    assert stored == ("COMPLETE", 1)


def test_surface_payload_refuses_dateline_dump_and_publication_bundle() -> None:
    with pytest.raises(ValueError, match="dateline dump"):
        UnpublishedSurfacePayload(
            payload_kind="unpublished_surface_payload",
            publication_bundle=False,
            auto_publish=False,
            language="ZH_HANT_HK",
            title="x",
            body="London — Home Office and UKVI, 2026-08-19 — copied",
            evidence_package_digest="sha256:" + ("a" * 64),
            story_candidate_id="c",
            event_hypothesis_id="h",
            source_lineage=("UK-01",),
            generated_at="2026-08-20T00:00:00.000000Z",
            status="UNPUBLISHED",
            writer_id="w",
        )
    with pytest.raises(VetoError, match="PUBLICATION_BUNDLE"):
        UnpublishedSurfacePayload(
            payload_kind="unpublished_surface_payload",
            publication_bundle=True,
            auto_publish=False,
            language="ZH_HANT_HK",
            title="x",
            body="【未出版原創評核稿】正文",
            evidence_package_digest="sha256:" + ("a" * 64),
            story_candidate_id="c",
            event_hypothesis_id="h",
            source_lineage=("UK-01",),
            generated_at="2026-08-20T00:00:00.000000Z",
            status="UNPUBLISHED",
            writer_id="w",
        )


def test_store_refuses_production_alias_and_public_dispatch(tmp_path: Path) -> None:
    with pytest.raises(VetoError, match="production"):
        connect(str(tmp_path / "production" / "unpublished.sqlite3"))
    unpublished = tmp_path / "unpublished_store.sqlite3"
    connection = connect(str(unpublished))
    with pytest.raises(VetoError, match="PUBLIC_DISPATCH"):
        mark_public_dispatch(connection, "missing")


def test_news_report_dateline_is_not_the_cycle_writer() -> None:
    items = parse_observation(
        source_id="UK-01", url="https://www.gov.uk/search/all.atom", body=ATOM
    )
    report = news_report(items[0], observed_at="2026-08-19T22:00:00.000000Z")
    assert report.startswith("London — Home Office and UKVI, 2026-08-19 — ")


def test_evaluation_packet_authorises_evaluation_and_refuses_production() -> None:
    from newsroom.authority.canonical import digest_canonical
    from newsroom.extraction.types import VersionedExtractionComponent
    from newsroom.graphiti_adapter.contracts import (
        GRAPHITI_ADAPTER_CODE_COMPONENT,
        GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        GRAPHITI_ADAPTER_POLICY_COMPONENT,
        GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        GRAPHITI_PROMPT_COMPONENT,
    )
    from newsroom.graphiti_adapter.models import GraphitiAdapterConfiguration
    from newsroom.graphiti_adapter.types import GraphitiExecutionProfile, GraphitiRuntimeMode
    from newsroom.tests.extraction_4a_helpers import contract_request
    from newsroom.tests.graphiti_adapter_4d_helpers import FAKE_CONFIGURATION_ID

    assert REAL_GRAPHITI_RUNTIME_ENABLED is True
    assert GRAPHITI_CORE_RELEASE == "graphiti-core-0.29.3"
    assert OPENROUTER_API == "OPENROUTER_API"
    assert GRAPHITI_CHAT_MODEL == "cursor-agent-cli:composer-2.5"
    assert GRAPHITI_EMBEDDING_MODEL == "openrouter:openai.text-embedding-3-large"
    assert WRITER_MODEL == "grok-build-cli:grok-4.6"
    assert WRITER_FALLBACK == "cursor-agent-cli"
    assert EVALUATION_GRAPHITI_PACKET.model_release == GRAPHITI_CHAT_MODEL
    assert "placeholder" not in EVALUATION_GRAPHITI_PACKET.framework_release
    assert EVALUATION_WORKSPACE_POLICY.egress_policy is GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY
    assert (
        EVALUATION_WORKSPACE_POLICY.credential_class
        is GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY
    )
    assert EVALUATION_GRAPHITI_PACKET.framework_release == GRAPHITI_CORE_RELEASE
    contract = contract_request()
    digest = digest_canonical({"contract": "evaluation-component"})
    configuration = GraphitiAdapterConfiguration(
        configuration_id=FAKE_CONFIGURATION_ID,
        runtime_mode=GraphitiRuntimeMode.REAL_GRAPHITI,
        execution_profile=GraphitiExecutionProfile.EVALUATION,
        framework=VersionedExtractionComponent("graphiti.framework", GRAPHITI_CORE_RELEASE, digest),
        model=VersionedExtractionComponent("graphiti.model", GRAPHITI_CHAT_MODEL, digest),
        embedding=VersionedExtractionComponent(
            "graphiti.embedding", GRAPHITI_EMBEDDING_MODEL, digest
        ),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=EVALUATION_WORKSPACE_POLICY,
        fixture_case=None,
        real_runtime_authority=EVALUATION_GRAPHITI_PACKET,
        idempotency_key="evaluation-packet-authorises-evaluation",
    )
    configuration.require_execution_authorized()
    production = GraphitiAdapterConfiguration(
        configuration_id=FAKE_CONFIGURATION_ID,
        runtime_mode=GraphitiRuntimeMode.REAL_GRAPHITI,
        execution_profile=GraphitiExecutionProfile.PRODUCTION,
        framework=VersionedExtractionComponent("graphiti.framework", GRAPHITI_CORE_RELEASE, digest),
        model=VersionedExtractionComponent("graphiti.model", GRAPHITI_CHAT_MODEL, digest),
        embedding=VersionedExtractionComponent(
            "graphiti.embedding", GRAPHITI_EMBEDDING_MODEL, digest
        ),
        prompt=GRAPHITI_PROMPT_COMPONENT,
        output_schema=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
        code=GRAPHITI_ADAPTER_CODE_COMPONENT,
        normalisation=GRAPHITI_ADAPTER_NORMALISATION_COMPONENT,
        temporal_policy=GRAPHITI_ADAPTER_TEMPORAL_COMPONENT,
        adapter_policy=GRAPHITI_ADAPTER_POLICY_COMPONENT,
        extractor_contract_id=contract.contract_id,
        extractor_contract_digest=contract.digest,
        workspace_policy=EVALUATION_WORKSPACE_POLICY,
        fixture_case=None,
        real_runtime_authority=EVALUATION_GRAPHITI_PACKET,
        idempotency_key="evaluation-packet-refuses-production",
    )
    with pytest.raises(GraphitiRuntimeNotAuthorized, match="EVALUATION"):
        production.require_execution_authorized()


def test_intake_fetches_when_gates_pass(tmp_path: Path) -> None:
    proving = tmp_path / "proving_store.sqlite3"

    def fetch(url: str) -> tuple[int, bytes]:
        if "atom" in url:
            return 200, ATOM
        if url.endswith(".xml") or "rss" in url.lower() or "WarningsRSS" in url:
            return 200, RSS
        return 200, JSON_DOC

    report = run_intake(
        proving_store=str(proving),
        fetch=fetch,
        clock=lambda: datetime.fromisoformat(FIXTURE_NOW.replace("Z", "+00:00")),
    )
    assert report.authorised
    assert report.sources == 10
    assert report.ok == 10
    assert report.proving_run_id.startswith("proving-9p-private-beta-")
    second = run_intake(
        proving_store=str(proving),
        fetch=fetch,
        clock=lambda: datetime.fromisoformat(FIXTURE_NOW.replace("Z", "+00:00")),
    )
    assert second.proving_run_id != report.proving_run_id


def _sample_candidate_package() -> tuple[StoryCandidateRecord, EvidencePackage]:
    from newsroom.control_plane.editorial import (
        DiscoverySignalRecord,
        NewsLeadRecord,
        StoryCandidateRecord,
    )
    from newsroom.control_plane.evidence import EvidencePackage

    candidate = StoryCandidateRecord(
        candidate_id="c1",
        hypothesis_id="h1",
        headline="Home Office update",
        items=parse_observation(
            source_id="UK-01", url="https://www.gov.uk/search/all.atom", body=ATOM
        ),
        signals=(
            DiscoverySignalRecord(
                signal_id="s1",
                source_id="UK-01",
                item_key="k",
                observation_digest="sha256:" + ("b" * 64),
            ),
        ),
        leads=(NewsLeadRecord(lead_id="l1", signal_id="s1", headline="Home Office update"),),
    )
    package = EvidencePackage(
        candidate_id="c1",
        hypothesis_id="h1",
        signal_ids=("s1",),
        lead_ids=("l1",),
        source_ids=("UK-01",),
        observation_digests=("sha256:" + ("b" * 64),),
        passages=("UK-01: retained",),
    )
    return candidate, package


def test_cli_writer_uses_grok_then_falls_back_to_cursor_agent() -> None:
    def grok(_prompt: str) -> str:
        raise RuntimeError("grok writer failed")

    def cursor(_prompt: str) -> str:
        return json.dumps(
            {"title": "【未出版】測試稿", "body": "【未出版原創】根據證據包改寫，唔係來源標題複本。"}
        )

    copy = CliChainWriter(primary=grok, fallback=cursor).write(*_sample_candidate_package())
    assert copy.writer_id == "cursor-agent-cli-cont-writer"
    assert copy.title.startswith("【未出版】")


def test_cli_writer_prefers_grok_build_cli() -> None:
    def grok(_prompt: str) -> str:
        return json.dumps(
            {
                "text": "",
                "structured_output": {
                    "title": "【未出版】Grok稿",
                    "body": "【未出版原創】Grok Build CLI 正文。",
                },
            }
        )

    def cursor(_prompt: str) -> str:
        raise AssertionError("fallback must not run")

    copy = CliChainWriter(primary=grok, fallback=cursor).write(*_sample_candidate_package())
    assert copy.writer_id == "grok-build-cli-cont-writer"
    assert "Grok" in copy.title


def test_cli_writer_rejects_planning_residue_and_falls_back() -> None:
    def grok(_prompt: str) -> str:
        return json.dumps(
            {"title": "正在核實幼稚園收生與家長智Net來源", "body": "先查 CONT 記者稿例。"}
        )

    def cursor(_prompt: str) -> str:
        return json.dumps(
            {
                "title": "【未出版】立法會教育議案",
                "body": "【未出版原創】立法會通過教育議案，本報根據證據包改寫。",
            },
            ensure_ascii=False,
        )

    copy = CliChainWriter(primary=grok, fallback=cursor).write(*_sample_candidate_package())
    assert copy.writer_id == "cursor-agent-cli-cont-writer"
    assert copy.title == "【未出版】立法會教育議案"
    assert not copy.title.startswith("正在")
    assert not copy.body.startswith("先查")


def test_cli_writer_accepts_finished_copy_that_mentions_verification() -> None:
    def grok(_prompt: str) -> str:
        return json.dumps(
            {
                "title": "英國入境規則公開更新",
                "body": "申請人須按現行版本核實資格，本報根據證據包改寫。",
            },
            ensure_ascii=False,
        )

    def cursor(_prompt: str) -> str:
        raise AssertionError("fallback must not run")

    copy = CliChainWriter(primary=grok, fallback=cursor).write(*_sample_candidate_package())
    assert copy.writer_id == "grok-build-cli-cont-writer"
    assert "核實資格" in copy.body


def test_grok_cli_uses_empty_cwd_and_three_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = json.dumps({"title": "t", "body": "b"})
        stderr = ""

    def fake_run(command: tuple[str, ...], **kwargs: object) -> Result:
        captured["command"] = command
        captured["timeout"] = kwargs.get("timeout")
        captured["cwd"] = kwargs.get("cwd")
        cwd = kwargs.get("cwd")
        captured["entries"] = os.listdir(cwd) if isinstance(cwd, str) else []
        return Result()

    monkeypatch.setattr("newsroom.control_plane.writer.subprocess.run", fake_run)
    run_grok_cli("prompt")
    command = captured["command"]
    assert isinstance(command, tuple)
    assert captured["timeout"] == 300
    assert command[command.index("--max-turns") + 1] == "3"
    assert command[command.index("--reasoning-effort") + 1] == "low"
    assert "--json-schema" in command
    assert "--no-plan" in command
    assert "--disable-web-search" in command
    assert "--no-subagents" in command
    assert "--always-approve" not in command
    assert "--force" not in command
    assert "--yolo" not in command
    assert captured["entries"] == ["prompt.txt"]
    cwd = captured["cwd"]
    assert isinstance(cwd, str)
    assert cwd != os.getcwd()


def test_cli_writer_reads_title_from_grok_text_envelope() -> None:
    def grok(_prompt: str) -> str:
        return json.dumps(
            {
                "text": json.dumps(
                    {"title": "【未出版】信封稿", "body": "【未出版原創】text 欄。"},
                    ensure_ascii=False,
                )
            }
        )

    def cursor(_prompt: str) -> str:
        raise AssertionError("fallback must not run")

    copy = CliChainWriter(primary=grok, fallback=cursor).write(*_sample_candidate_package())
    assert copy.title == "【未出版】信封稿"


def test_broker_error_does_not_include_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.control_plane import broker

    class Result:
        returncode = 1
        stdout = "super-secret-openrouter-key\n"
        stderr = "not found"

    monkeypatch.setattr(
        broker.subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )
    with pytest.raises(broker.BrokerError, match="OPENROUTER_API is absent") as caught:
        broker.openrouter_api_key()
    assert "super-secret-openrouter-key" not in str(caught.value)


def test_keychain_timeout_is_a_broker_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from newsroom.control_plane import broker

    def timeout(*_args: object, **_values: object) -> object:
        raise broker.subprocess.TimeoutExpired("security", 10)

    monkeypatch.setattr(broker.subprocess, "run", timeout)
    with pytest.raises(broker.BrokerError, match="OPENROUTER_API lookup timed out"):
        broker.openrouter_api_key()
