"""Actual private Hermes pipeline composition over the existing native ports."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from neo4j import GraphDatabase

from newsroom.authority import AuthenticationProof, UtcTimestamp
from newsroom.authority.canonical import digest_canonical
from newsroom.authority._neo4j_projection_system import _open_neo4j_fulltext_reader_with_adapter
from newsroom.increment5.exact_retriever import SQLiteExactRetriever
from newsroom.increment5.fulltext_journal import FullTextReceiptJournal
from newsroom.increment5.fulltext_retriever import FullTextRetriever
from newsroom.increment5.native_retrieval import NativeRetrievalHold, NativeRetrievalPort
from newsroom.increment5.neo4j_native_retrieval import Neo4jNativeRetrievalProjection
from newsroom.increment5.receipt_journal import BranchReceiptJournal
from newsroom.increment5.retrieval_context import RetrievalContextJournal
from newsroom.increment6.work_items import RetrievalContextAuthority
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter
from newsroom.projection.neo4j.models import Neo4jProjectorConfig
from newsroom.sources import SourceDefinitionId, SourceDefinitionVersionId

from .govuk_evidence import GovUkEvidenceAcquisition, POLICY_DIGEST as GOVUK_TRANSPORT_POLICY
from .govuk_rights import GovUkLicenceEvidence, retain_current_govuk_licence
from .graphiti_operational_readiness import OPERATOR_AUTHORITY_DOMAIN, OPERATOR_PRINCIPAL_ID
from .model_usage import InvocationEfficiencyPolicy, ModelUsageService
from .native_assessor import AutonomousNativeEvidenceAssessor, NativeAssessmentUsage
from .native_collision import NativeCollisionAuthority, NativeCollisionIdentity
from .native_cycle import _uuid4_for
from .native_discovery import NativeDiscovery
from .native_embeddings import NativePassageEmbedder
from .native_evidence import EvidenceAssessor, EvidenceTransport, NativeEvidenceController
from .native_graphiti import NativeGraphitiProcessor
from .native_pipeline import NativePipeline
from .native_policies import VERSION, native_policy_components
from .native_progress import NativeRevisionJournal
from .native_publication import NativePublicationContinuation
from .native_retrieval import NativeRetrievalContinuation, compose_native_documents
from .native_runtime import open_native_runtime
from .native_source_intake import NativeSourceIntake, native_evidence_sources
from .native_source_rights import NativePortfolioRights, observe_portfolio_terms
from .native_source_definitions import MISSING_SOURCE_IDS, register_missing_native_source_definitions
from .native_weather_sources import poll_other_source
from .native_weather_evidence import NativeWeatherEvidenceAcquisition, POLICY_DIGEST as WEATHER_TRANSPORT_POLICY
from .store import connect

TRANSPORT_POLICY = digest_canonical({
    "version": "hermes-native-independent-evidence-v1",
    "govuk": GOVUK_TRANSPORT_POLICY, "weather": WEATHER_TRANSPORT_POLICY,
})


def deployed_native_service(args):
    """Compose the installed canonical private route, after the singleton lock."""
    from . import broker, native_assessor, native_embeddings
    from .cycle import assert_no_owner_emergency_stop, owner_emergency_stop_fence
    from .model_usage import WorkloadClass
    from .native_service import NativeService
    from .paths import (
        CANONICAL_PROVING_STORE, CANONICAL_UNPUBLISHED_STORE,
        CANONICAL_INCREMENT4_AUTHORITY_STORE, CANONICAL_OBJECT_CAS_ROOT,
        CANONICAL_GRAPHITI_WORKSPACE_ROOT, HOST_CONTROL_PLANE_STATE_ROOT,
    )
    from .writer import cont_writer_implementation_identity
    from newsroom.increment9.proving import SOURCE_URLS

    if Path(args.ledger).resolve() != CANONICAL_UNPUBLISHED_STORE.resolve():
        raise ValueError("native service must use the canonical private ledger")
    private_root = HOST_CONTROL_PLANE_STATE_ROOT / "native"
    if Path(args.lock).resolve() != (private_root / "hermes.lock").resolve():
        raise ValueError("native service must use its canonical singleton lock")
    check = lambda: assert_no_owner_emergency_stop(str(CANONICAL_PROVING_STORE))
    fence = lambda: owner_emergency_stop_fence(str(CANONICAL_PROVING_STORE))

    @contextmanager
    def pipeline():
        check()
        revision, clean = cont_writer_implementation_identity()
        if not clean:
            raise ValueError("native deployment implementation is not exact and clean")
        usage = ModelUsageService(str(CANONICAL_UNPUBLISHED_STORE))
        embedding = usage.qualified_policy(
            workload_class=WorkloadClass.NATIVE_RETRIEVAL_EMBEDDING,
            provider="openrouter", route=native_embeddings.ROUTE,
            model=native_embeddings.OPENROUTER_EMBEDDING_SLUG, reasoning="none",
            implementation_revision=native_embeddings.implementation_digest(),
            output_schema_digest=native_embeddings.SCHEMA_DIGEST,
        )
        assessment = usage.qualified_policy(
            workload_class=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
            provider=native_assessor.CONT_PRIMARY_PROVIDER, route=native_assessor.ROUTE,
            model=native_assessor.CONT_PRIMARY_MODEL, reasoning=native_assessor.CONT_PRIMARY_REASONING,
            implementation_revision=revision, config_identity=native_assessor.CONFIG_IDENTITY,
            output_schema_digest=native_assessor.SCHEMA_DIGEST,
        )
        # Discovery only: each selected identity is authenticated again by the
        # Source facade before an observation. No Source Definition is invented.
        connection = sqlite3.connect(CANONICAL_INCREMENT4_AUTHORITY_STORE.as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT h.definition_id,v.locator FROM source_definition_version_heads h "
                "JOIN source_definition_versions v ON v.version_id=h.current_version_id"
            ).fetchall()
        finally:
            connection.close()
        bindings = {}
        for source_id, url in SOURCE_URLS.items():
            matching = [definition for definition, locator in rows if locator == url]
            if len(matching) > 1:
                raise ValueError("current native source definition identity is ambiguous")
            if matching:
                bindings[source_id] = SourceDefinitionId.parse(matching[0])
        with open_native_pipeline(
            authority_path=CANONICAL_INCREMENT4_AUTHORITY_STORE,
            object_root=CANONICAL_OBJECT_CAS_ROOT, workspace_root=CANONICAL_GRAPHITI_WORKSPACE_ROOT,
            private_path=CANONICAL_UNPUBLISHED_STORE, proving_path=CANONICAL_PROVING_STORE,
            intake_path=private_root / "evidence-intake.sqlite3",
            serving_path=private_root / "private-serving.sqlite3",
            retrieval_path=private_root / "retrieval.sqlite3",
            neo4j_config=broker.neo4j_projector_config(), embedding_key=broker.openrouter_api_key(),
            embedding_policy=embedding, assessment_policy=assessment, source_definition_ids=bindings,
            licence=None, stop_check=check, stop_fence=fence, implementation_worktree_clean=clean,
        ) as composed:
            yield composed

    return NativeService(
        pipeline_factory=pipeline, ledger_path=str(CANONICAL_UNPUBLISHED_STORE),
        lock_path=Path(args.lock), stop_check=check, interval_seconds=args.interval,
        failure_backoff_seconds=args.failure_backoff,
    )


@contextmanager
def open_native_pipeline(
    *, authority_path: Path, object_root: Path, workspace_root: Path,
    private_path: Path, proving_path: Path, intake_path: Path, serving_path: Path,
    retrieval_path: Path, neo4j_config: Neo4jProjectorConfig,
    embedding_key: str, embedding_policy: InvocationEfficiencyPolicy,
    assessment_policy: InvocationEfficiencyPolicy,
    source_definition_ids: Mapping[str, SourceDefinitionId],
    licence: GovUkLicenceEvidence | None,
    stop_check: Callable[[], None], stop_fence: Callable,
    implementation_worktree_clean: bool,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
):
    """Open one real runtime; qualification policies must already be retained.

    Credentials remain process-local. No route fallback, legacy intake writer,
    fixture rights renewal, historical campaign or public target is composed.
    """
    stop_check()
    if not implementation_worktree_clean:
        raise ValueError("native provider composition requires its reviewed clean implementation")
    principal, domain = OPERATOR_PRINCIPAL_ID, OPERATOR_AUTHORITY_DOMAIN
    target_id = "hermes-private-serving"
    credential = secrets.token_urlsafe(32)
    proof = AuthenticationProof(method="STATIC_TOKEN", credential=credential)
    now = lambda: UtcTimestamp(clock().astimezone(UTC))
    policies = native_policy_components(
        principal_id=principal, authority_domain=domain,
        target_path=serving_path, target_id=target_id,
    )
    # The native passage index and admitted Increment 4 graph are different
    # projections; their identities are bound separately in the context.
    generation_basis = {
        "version": VERSION, "authority": str(authority_path.resolve()),
        "document_policy": policies.retrieval_document_definition,
        "neo4j_destination": {"uri": neo4j_config.uri, "database": neo4j_config.database,
                              "projector_principal": neo4j_config.username},
    }
    generation_digest = digest_canonical(generation_basis)
    generation_id = _uuid4_for(generation_basis)
    suffix = generation_id.replace("-", "")[:16]
    scope = f"hermes-native:{generation_digest}"
    with ExitStack() as resources:
        private = connect(str(private_path))
        resources.callback(private.close)
        proving = sqlite3.connect(proving_path.as_uri() + "?mode=ro", uri=True)
        proving.execute("PRAGMA query_only=ON")
        resources.callback(proving.close)
        journal = NativeRevisionJournal(private)
        usage = ModelUsageService(str(private_path))
        RetrievalContextJournal(retrieval_path)
        exact = SQLiteExactRetriever(
            authority_database=authority_path, journal=BranchReceiptJournal(retrieval_path),
        )
        fulltext_journal = FullTextReceiptJournal(retrieval_path)
        driver = GraphDatabase.driver(neo4j_config.uri, auth=(neo4j_config.username, neo4j_config.password))
        resources.callback(driver.close)
        projector = Neo4jNativeRetrievalProjection(
            driver, database=neo4j_config.database, generation_id=generation_id,
            fulltext_index=f"native_fulltext_{suffix}", vector_index=f"native_vector_{suffix}",
        )
        reader = _open_neo4j_fulltext_reader_with_adapter(_open_neo4j_adapter(neo4j_config))
        resources.callback(reader.close)
        components = {}

        def dependencies(*, objects, extraction, commands, events):
            documents = compose_native_documents(
                objects=objects, extraction=extraction, commands=commands,
                events=events, projector=projector, policies=policies,
                principal_id=principal, authority_domain=domain,
            )
            collision = NativeCollisionAuthority(
                # Retrieval is ATTACHed to the authority writer. Its BEGIN
                # IMMEDIATE also locks that database, so collision observations
                # use the existing private ledger, never a second attached writer.
                authority_path=authority_path, journal_path=private_path,
                identity=NativeCollisionIdentity(scope, principal, domain),
                context_reader=documents.read_context, events=events,
            )
            components.update(documents=documents, collision=collision)
            return RetrievalContextAuthority(
                retrieval_path, {}, native_context_read_port=documents.context_read_port(proof=proof),
            ), collision.enforcer

        runtime = resources.enter_context(open_native_runtime(
            authority_path=authority_path, object_root=object_root, workspace_root=workspace_root,
            intake_path=intake_path, target_path=serving_path, target_id=target_id,
            credential=credential, principal_id=principal, authority_domain=domain,
            neo4j_config=neo4j_config, native_dependency_factory=dependencies, clock=now,
        ))
        documents = components["documents"]
        if licence is None:
            govuk = retain_current_govuk_licence(
                objects=runtime.authority.objects, proof=proof,
                dispatch_fence=stop_check, clock=clock,
            )
            licence = NativePortfolioRights(govuk, observe_portfolio_terms(
                objects=runtime.authority.objects, proof=proof,
                stop_check=stop_check, clock=clock,
            ))
        elif type(licence) is GovUkLicenceEvidence:
            licence = NativePortfolioRights(licence, {})
        licence.require_retained(objects=runtime.authority.objects, proof=proof)
        embedder = NativePassageEmbedder(
            api_key=embedding_key, objects=runtime.authority.objects, usage=usage,
            policy=embedding_policy, dispatch_fence=stop_fence,
            implementation_worktree_clean=implementation_worktree_clean, clock=clock,
        )
        assessor = AutonomousNativeEvidenceAssessor(
            usage=NativeAssessmentUsage(usage, assessment_policy, clock=clock),
            dispatch_fence=stop_fence,
        )
        from newsroom.increment9.proving import SOURCE_URLS
        definitions = dict(source_definition_ids)
        missing_rights = {
            source_id: rights
            for source_id in MISSING_SOURCE_IDS if source_id not in definitions
            if (rights := licence.for_source(
                source_id=source_id, definition_url=SOURCE_URLS[source_id],
            )).decision == "PERMITTED"
        }
        with stop_fence():
            definitions.update(register_missing_native_source_definitions(
                sources=runtime.authority.sources, proof=proof,
                rights_by_source=missing_rights,
            ))
            projector.bootstrap()

        def source_rights(source_id, url, _at=None):
            stop_check()
            rights = licence.for_source(source_id=source_id, definition_url=url)
            if rights.decision != "PERMITTED":
                return None
            return {"source_id": source_id, "source_url": url,
                    "packet_digest": rights.evidence_digest,
                    "rights_decision_id": rights.record_id,
                    "policy_digest": rights.policy_digest,
                    "scope": "NATIVE_RETAINED_SOURCE_TEXT"}

        def rights_for_unit(unit):
            current = runtime.authority.sources.current_summary(
                SourceDefinitionId.parse(unit.authority.definition_id), proof=proof,
            )
            if str(current.version_id) != unit.authority.definition_version_id:
                return None
            version = runtime.authority.sources.version_details(current.version_id, proof=proof)
            if version.request.locator != unit.source_definition_url:
                return None
            return source_rights(unit.source_id, version.request.locator)

        def require_rights(unit):
            if rights_for_unit(unit) is None:
                raise NativeRetrievalHold("NATIVE_CURRENT_SOURCE_RIGHTS_HOLD")

        def source_fence(source_id, url):
            with stop_fence():
                stop_check()

        def port_for(subjects):
            receipts = tuple(item.document_receipt for item in subjects)
            retained = tuple(documents.require_document(item, proof=proof) for item in receipts)
            watermark = max(runtime.authority.events.provenance(item.event_id, proof=proof).event.ledger_seq for item in receipts)
            snapshot = projector.snapshot(
                generation_identity_digest=generation_digest,
                rights_manifest_digest=digest_canonical(tuple(sorted(
                    (item.passage_id, item.rights_digest) for item in retained
                ))), contiguous_ledger_seq=watermark,
                expected_document_count=len(receipts), clock=now,
            )
            view = documents.fulltext_authority_view(receipts, snapshot, proof=proof)
            return NativeRetrievalPort(
                documents=documents, exact=exact,
                fulltext=FullTextRetriever(graph_reader=reader, journal=fulltext_journal,
                                          authority_view_provider=lambda _: view),
                increment4=runtime.authority.increment4, fulltext_view=view,
                subjects=subjects, authority_scope_id=scope,
                minimum_authority_watermark=watermark,
            )

        retrieval = NativeRetrievalContinuation(
            system=runtime.authority, documents=documents, journal=journal,
            connection=private, embedder=embedder, generation_id=generation_id,
            port_for=port_for, rights_check=require_rights,
        )
        govuk_acquisition = GovUkEvidenceAcquisition(
            sources=runtime.authority.sources, proof=proof,
            dispatch_fence=lambda request: source_fence(request.source_id, request.canonical_url),
            clock=clock, licence_evidence=licence,
            transport_policy_digest=TRANSPORT_POLICY,
        )
        weather_acquisition = NativeWeatherEvidenceAcquisition(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=proof, rights=licence, transport_policy_digest=TRANSPORT_POLICY,
            dispatch_fence=lambda request: source_fence(request.source_id, request.canonical_url),
            clock=clock,
        )

        def acquire(request):
            transport = weather_acquisition if request.source_id in {"HK-02", "UK-10"} else govuk_acquisition
            return transport(request)

        evidence = NativeEvidenceController(
            objects=runtime.authority.objects, candidate_port=runtime.authority.candidate_read_port,
            evidence_packages=runtime.evidence,
            transport=EvidenceTransport(acquire), assessor=EvidenceAssessor(assessor),
            policy_bundle_digest=policies.publication.editorial_policy_bundle_digest,
            transport_policy_digest=TRANSPORT_POLICY, clock=now,
        )

        class Publication:
            def advance(self, *, revision_id, candidate_version_id):
                sources = native_evidence_sources(
                    units=journal.units[revision_id], sources=runtime.authority.sources,
                    objects=runtime.authority.objects, licence=licence, proof=proof,
                    observations=journal.observations,
                )
                return NativePublicationContinuation(
                    journal=journal, runtime=runtime, evidence_controller=evidence,
                    sources={revision_id: sources}, clock=now,
                ).advance(revision_id=revision_id, candidate_version_id=candidate_version_id)

        intake = NativeSourceIntake(
            sources=runtime.authority.sources, objects=runtime.authority.objects,
            proof=proof, definition_ids=definitions, licence=licence,
            dispatch_fence=source_fence, clock=clock,
            other_source_poll=lambda **request: poll_other_source(intake, **request),
        )
        yield NativePipeline(
            runtime=runtime, journal=journal, source_intake=intake,
            graphiti=NativeGraphitiProcessor(
                system=runtime.authority, connection=private, usage=usage, proof=proof,
                rights_for=rights_for_unit, stop_check=stop_check, dispatch_fence=stop_fence,
                clock=clock,
            ), discovery=NativeDiscovery(
                sources=runtime.authority.sources, checks=runtime.authority.checks,
                discovery=runtime.authority.discovery, proving=proving,
                rights_for=source_rights,
            ), retrieval_for=lambda _: retrieval, collision=components["collision"],
            publish=Publication(), actor_identity_digest=runtime.actor_identity_digest,
            stop_check=stop_check, stop_fence=stop_fence, clock=now,
        )
