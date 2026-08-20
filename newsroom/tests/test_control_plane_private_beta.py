from pathlib import Path
import json

import pytest

from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.intake import run_intake
from newsroom.control_plane.items import parse_observation
from newsroom.control_plane.reports import news_report
from newsroom.control_plane.store import connect, list_payloads, mark_public_dispatch
from newsroom.control_plane.surface import UnpublishedSurfacePayload
from newsroom.control_plane.veto import VetoError, refuse_public_effect
from newsroom.control_plane.writer import FixtureWriter, OpenRouterWriter
from newsroom.graphiti_adapter.evaluation_packet import (
    EVALUATION_GRAPHITI_PACKET,
    EVALUATION_WORKSPACE_POLICY,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_EMBEDDING_MODEL,
    OPENROUTER_API,
    WRITER_MODEL,
)
from newsroom.graphiti_adapter.models import REAL_GRAPHITI_RUNTIME_ENABLED
from newsroom.graphiti_adapter.types import (
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiRuntimeNotAuthorized,
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
        """
    )
    connection.execute(
        "INSERT INTO proving_runs VALUES('run-1','2026-08-16T21:41:34.000000Z',0,0,0,0)"
    )
    rows = (
        (
            "UK-01",
            "https://www.gov.uk/search/all.atom",
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
            (source_id, "https://example.invalid/feed", f"sha256:{source_id}", body)
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


def test_evaluation_packet_is_real_but_flag_stays_false() -> None:
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

    assert REAL_GRAPHITI_RUNTIME_ENABLED is False
    assert GRAPHITI_CORE_RELEASE == "graphiti-core-0.29.3"
    assert OPENROUTER_API == "OPENROUTER_API"
    assert GRAPHITI_CHAT_MODEL == "openrouter:openai.gpt-5-mini"
    assert GRAPHITI_EMBEDDING_MODEL == "openrouter:openai.text-embedding-3-large"
    assert WRITER_MODEL == "openrouter:x-ai.grok-4.6"
    assert EVALUATION_GRAPHITI_PACKET.model_release == GRAPHITI_CHAT_MODEL
    assert "placeholder" not in EVALUATION_GRAPHITI_PACKET.framework_release
    assert EVALUATION_WORKSPACE_POLICY.egress_policy is GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY
    assert (
        EVALUATION_WORKSPACE_POLICY.credential_class
        is GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY
    )
    assert EVALUATION_GRAPHITI_PACKET.framework_release == GRAPHITI_CORE_RELEASE
    assert "placeholder" not in EVALUATION_GRAPHITI_PACKET.framework_release
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
        idempotency_key="evaluation-packet-refuses-until-flag",
    )
    with pytest.raises(GraphitiRuntimeNotAuthorized, match="disabled and unqualified"):
        configuration.require_execution_authorized()


def test_intake_fetches_when_gates_pass(tmp_path: Path) -> None:
    proving = tmp_path / "proving_store.sqlite3"

    def fetch(url: str) -> tuple[int, bytes]:
        if "atom" in url:
            return 200, ATOM
        if url.endswith(".xml") or "rss" in url.lower() or "WarningsRSS" in url:
            return 200, RSS
        return 200, JSON_DOC

    report = run_intake(proving_store=str(proving), fetch=fetch)
    assert report.authorised
    assert report.sources == 10
    assert report.ok == 10


def test_openrouter_writer_does_not_call_graphiti() -> None:
    from newsroom.control_plane.editorial import (
        DiscoverySignalRecord,
        NewsLeadRecord,
        StoryCandidateRecord,
    )
    from newsroom.control_plane.evidence import EvidencePackage

    seen: dict[str, str] = {}

    def post(*, prompt: str, api_key: str) -> str:
        seen["prompt"] = prompt
        seen["api_key"] = api_key
        return json.dumps(
                {"title": "【未出版】測試稿", "body": "【未出版原創】根據證據包改寫，唔係來源標題複本。"}
        )

    writer = OpenRouterWriter(post=post, api_key=lambda: "test-openrouter-token")
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
    copy = writer.write(candidate, package)
    assert copy.writer_id.startswith("openrouter-")
    assert copy.title.startswith("【未出版】")
    assert "來源標題複本" in copy.body
    assert seen["api_key"] == "test-openrouter-token"
    assert "Graphiti" in seen["prompt"]


def test_broker_error_does_not_include_secret(monkeypatch) -> None:
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

