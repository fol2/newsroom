from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import AggregateId, require_token
from newsroom.relations.fixture_v2 import INTEGRATED_FIXTURE_V2

from .complete import (
    CompleteProjectionContract,
    CompleteProjectionContractRegistry,
    CompleteProjectionProfile,
    FixtureVectorDocumentContract,
    FixtureVectorManifestContract,
    FullTextIndexContract,
    VectorIndexContract,
    VectorProviderKind,
    VectorQuantizationType,
    VectorSimilarityFunction,
)
from .models import (
    ProjectionContractError,
    ProjectionFamilyDefinition,
    ProjectionFamilyKind,
)
from .registry import ProjectionFamilyRegistry


_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"
_FIXTURE_PATH = _FIXTURE_ROOT / "integrated_fixture_v2_projection.json"
_SCHEMA_PATH = _FIXTURE_ROOT / "integrated_fixture_v2_projection.schema.json"


@dataclass(frozen=True, slots=True)
class FixtureProjectionDocument:
    passage_id: str
    blob_digest: str
    language: str
    revision_id: str | None
    expected_lifecycle: str
    normalized_text_digest: str
    components: tuple[int, ...]
    vector_digest: str

    def __post_init__(self) -> None:
        require_token(self.passage_id, field="projection_fixture_passage_id")
        validate_sha256_digest(self.blob_digest, field="projection_blob_digest")
        validate_sha256_digest(
            self.normalized_text_digest,
            field="normalized_text_digest",
        )
        validate_sha256_digest(self.vector_digest, field="vector_digest")
        if self.language not in {"en-GB", "zh-HK"}:
            raise ProjectionContractError("projection fixture language is invalid")
        if self.expected_lifecycle not in {"ACTIVE", "TOMBSTONED"}:
            raise ProjectionContractError(
                "projection fixture lifecycle expectation is invalid"
            )
        if not isinstance(self.components, tuple):
            raise ProjectionContractError(
                "projection fixture vector components must be immutable"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": self.passage_id,
            "blob_digest": self.blob_digest,
            "language": self.language,
            "revision_id": self.revision_id,
            "expected_lifecycle": self.expected_lifecycle,
            "normalized_text_digest": self.normalized_text_digest,
            "components": list(self.components),
            "vector_digest": self.vector_digest,
        }


@dataclass(frozen=True, slots=True)
class FullTextQualificationQuery:
    query_id: str
    language: str
    query: str
    normalized_query: str
    expected_first_passage_id: str

    def __post_init__(self) -> None:
        require_token(self.query_id, field="fulltext_query_id")
        require_token(
            self.expected_first_passage_id,
            field="fulltext_expected_passage_id",
        )
        if self.language not in {"en-GB", "zh-HK"}:
            raise ProjectionContractError("full-text query language is invalid")
        if not self.query or not self.normalized_query:
            raise ProjectionContractError("full-text qualification query is empty")


@dataclass(frozen=True, slots=True)
class VectorQualificationQuery:
    query_id: str
    passage_id: str
    expected_active_prefix: tuple[str, ...]

    def __post_init__(self) -> None:
        require_token(self.query_id, field="vector_query_id")
        require_token(self.passage_id, field="vector_query_passage_id")
        if (
            not isinstance(self.expected_active_prefix, tuple)
            or len(self.expected_active_prefix) < 3
            or len(set(self.expected_active_prefix))
            != len(self.expected_active_prefix)
        ):
            raise ProjectionContractError(
                "vector qualification prefix must be unique and bounded"
            )
        for passage_id in self.expected_active_prefix:
            require_token(passage_id, field="vector_expected_passage_id")


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2Projection:
    schema_version: str
    fixture_id: str
    source_fixture_digest: str
    component_scale: int
    dimensions: int
    canonical_bytes: bytes
    documents: tuple[FixtureProjectionDocument, ...]
    fulltext_queries: tuple[FullTextQualificationQuery, ...]
    vector_queries: tuple[VectorQualificationQuery, ...]
    expected_active_passage_ids: tuple[str, ...]
    expected_tombstoned_passage_ids: tuple[str, ...]
    fulltext_contract: FullTextIndexContract
    vector_contract: VectorIndexContract
    complete_contract: CompleteProjectionContract

    def __post_init__(self) -> None:
        if self.schema_version != "integrated_fixture_v2_projection_v1":
            raise ProjectionContractError(
                "projection fixture schema identity is invalid"
            )
        if self.fixture_id != INTEGRATED_FIXTURE_V2.fixture_id:
            raise ProjectionContractError(
                "projection fixture identity differs from governed fixture"
            )
        if self.source_fixture_digest != INTEGRATED_FIXTURE_V2.manifest_digest:
            raise ProjectionContractError(
                "projection fixture digest differs from governed fixture"
            )
        if self.component_scale != self.vector_contract.component_scale:
            raise ProjectionContractError(
                "projection fixture vector scale differs from contract"
            )
        if self.dimensions != self.vector_contract.dimensions:
            raise ProjectionContractError(
                "projection fixture dimensions differ from contract"
            )
        passage_ids = tuple(item.passage_id for item in self.documents)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise ProjectionContractError(
                "projection fixture documents must be sorted and unique"
            )
        source_by_id = INTEGRATED_FIXTURE_V2.passage_by_id
        if set(passage_ids) != set(source_by_id):
            raise ProjectionContractError(
                "projection fixture must cover every governed fixture passage"
            )
        for document in self.documents:
            passage = source_by_id[document.passage_id]
            expected_normalized = self.fulltext_contract.normalize(passage.text)
            expected_vector_digest = digest_bytes(
                canonical_json_bytes(
                    {
                        "contract": "newsroom-fixture-vector-v1",
                        "passage_id": document.passage_id,
                        "dimensions": self.dimensions,
                        "component_scale": self.component_scale,
                        "components": list(document.components),
                    }
                )
            )
            if (
                document.blob_digest != passage.blob_digest
                or document.language != passage.language
                or document.revision_id != passage.revision_id
                or document.expected_lifecycle != passage.expected_lifecycle
                or document.normalized_text_digest
                != digest_bytes(expected_normalized.encode("utf-8"))
                or document.vector_digest != expected_vector_digest
            ):
                raise ProjectionContractError(
                    "projection document differs from governed fixture authority"
                )
            self.vector_contract.vector_from_components(document.components)
        expected_active = tuple(
            sorted(
                item.passage_id
                for item in INTEGRATED_FIXTURE_V2.passages
                if item.expected_lifecycle == "ACTIVE"
            )
        )
        expected_tombstoned = (
            INTEGRATED_FIXTURE_V2.tombstoned_negative_passage_id,
        )
        if self.expected_active_passage_ids != expected_active:
            raise ProjectionContractError(
                "projection fixture active set differs from governed fixture"
            )
        if self.expected_tombstoned_passage_ids != expected_tombstoned:
            raise ProjectionContractError(
                "projection fixture tombstone set differs from governed fixture"
            )
        active = set(expected_active)
        if any(
            query.expected_first_passage_id not in active
            for query in self.fulltext_queries
        ):
            raise ProjectionContractError(
                "full-text expected result must be currently active"
            )
        for query in self.vector_queries:
            if query.passage_id not in active or not set(
                query.expected_active_prefix
            ).issubset(active):
                raise ProjectionContractError(
                    "vector qualification expectations must be currently active"
                )
        if (
            self.complete_contract.source_fixture_digest
            != self.source_fixture_digest
            or self.complete_contract.fixture_vector_manifest_digest
            != self.manifest_digest
            or self.complete_contract.fulltext_contract_digest
            != self.fulltext_contract.contract_digest
            or self.complete_contract.vector_contract_digest
            != self.vector_contract.contract_digest
        ):
            raise ProjectionContractError(
                "complete projection contract differs from fixture contracts"
            )
        self.vector_contract.require_profile(
            CompleteProjectionProfile.FIXTURE_QUALIFICATION
        )

    @property
    def manifest_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def document_by_id(self) -> dict[str, FixtureProjectionDocument]:
        return {item.passage_id: item for item in self.documents}

    @property
    def fixture_manifest_contract(self) -> FixtureVectorManifestContract:
        return FixtureVectorManifestContract(
            schema_version=self.schema_version,
            fixture_id=self.fixture_id,
            source_fixture_digest=self.source_fixture_digest,
            component_scale=self.component_scale,
            dimensions=self.dimensions,
            canonical_bytes=self.canonical_bytes,
            documents=tuple(
                FixtureVectorDocumentContract(
                    passage_id=item.passage_id,
                    blob_digest=item.blob_digest,
                    language=item.language,
                    revision_id=item.revision_id,
                    expected_lifecycle=item.expected_lifecycle,
                    normalized_text_digest=item.normalized_text_digest,
                    components=item.components,
                    vector_digest=item.vector_digest,
                )
                for item in self.documents
            ),
        )

    @property
    def contracts(self) -> CompleteProjectionContractRegistry:
        return CompleteProjectionContractRegistry(
            fulltext_contracts=(self.fulltext_contract,),
            vector_contracts=(self.vector_contract,),
            fixture_manifests=(self.fixture_manifest_contract,),
            complete_contracts=(self.complete_contract,),
        )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionContractError(
            f"cannot load projection fixture contract: {path.name}"
        ) from exc


def load_integrated_fixture_v2_projection() -> IntegratedFixtureV2Projection:
    schema = _read_json(_SCHEMA_PATH)
    value = _read_json(_FIXTURE_PATH)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = "/".join(str(item) for item in first.path) or "<root>"
        raise ProjectionContractError(
            "integrated_fixture_v2_projection schema failure at "
            f"{location}: {first.message}"
        )
    if not isinstance(value, dict):
        raise ProjectionContractError("projection fixture root must be an object")

    fulltext = FullTextIndexContract(
        contract_id="fixture_fulltext_v1",
        contract_version="fixture-fulltext-contract-v1",
        implementation_version="fixture-fulltext-normalizer-v1",
        index_name="newsroom_fixture_fulltext_v1",
        node_label="NewsroomRetrievalDocument",
        source_field="text",
        retrieval_property="retrieval_text",
        analyzer="standard-no-stop-words",
        provider="fulltext-2.0",
    )
    vector = VectorIndexContract(
        contract_id="fixture_vector_v1",
        contract_version="fixture-vector-contract-v1",
        implementation_version="fixture-fixed-point-vector-v1",
        index_name="newsroom_fixture_vector_v1",
        node_label="NewsroomRetrievalDocument",
        vector_property="fixture_vector",
        dimensions=int(value["dimensions"]),
        component_scale=int(value["component_scale"]),
        provider="vector-2026.06",
        similarity_function=VectorSimilarityFunction.COSINE,
        quantization=VectorQuantizationType.NONE,
        provider_kind=VectorProviderKind.REPOSITORY_FIXTURE,
    )

    source_by_id = INTEGRATED_FIXTURE_V2.passage_by_id
    documents: list[FixtureProjectionDocument] = []
    for item in value["documents"]:
        passage_id = str(item["passage_id"])
        passage = source_by_id.get(passage_id)
        if passage is None:
            raise ProjectionContractError(
                "projection fixture references unknown governed passage"
            )
        components = tuple(int(component) for component in item["components"])
        normalized = fulltext.normalize(passage.text)
        vector_digest = digest_bytes(
            canonical_json_bytes(
                {
                    "contract": "newsroom-fixture-vector-v1",
                    "passage_id": passage_id,
                    "dimensions": vector.dimensions,
                    "component_scale": vector.component_scale,
                    "components": list(components),
                }
            )
        )
        documents.append(
            FixtureProjectionDocument(
                passage_id=passage_id,
                blob_digest=str(item["blob_digest"]),
                language=str(item["language"]),
                revision_id=(
                    None
                    if item["revision_id"] is None
                    else str(item["revision_id"])
                ),
                expected_lifecycle=str(item["expected_lifecycle"]),
                normalized_text_digest=digest_bytes(normalized.encode("utf-8")),
                components=components,
                vector_digest=vector_digest,
            )
        )

    canonical = canonical_json_bytes(value)
    manifest_digest = digest_bytes(canonical)
    complete = CompleteProjectionContract(
        contract_id="integrated_fixture_v2_complete_projection",
        contract_version="complete-projection-contract-v1",
        implementation_version="increment-2b-complete-projector-v1",
        admitted_relation_projector_version="relation-projector-v1",
        source_fixture_digest=str(value["source_fixture_digest"]),
        fixture_vector_manifest_digest=manifest_digest,
        fulltext_contract_digest=fulltext.contract_digest,
        vector_contract_digest=vector.contract_digest,
    )
    queries = value["qualification_queries"]
    fulltext_queries = tuple(
        FullTextQualificationQuery(
            query_id=str(item["query_id"]),
            language=str(item["language"]),
            query=str(item["query"]),
            normalized_query=fulltext.normalize(str(item["query"])),
            expected_first_passage_id=str(item["expected_first_passage_id"]),
        )
        for item in queries["fulltext"]
    )
    vector_queries = tuple(
        VectorQualificationQuery(
            query_id=str(item["query_id"]),
            passage_id=str(item["passage_id"]),
            expected_active_prefix=tuple(
                str(passage_id) for passage_id in item["expected_active_prefix"]
            ),
        )
        for item in queries["vector"]
    )
    return IntegratedFixtureV2Projection(
        schema_version=str(value["schema_version"]),
        fixture_id=str(value["fixture_id"]),
        source_fixture_digest=str(value["source_fixture_digest"]),
        component_scale=int(value["component_scale"]),
        dimensions=int(value["dimensions"]),
        canonical_bytes=canonical,
        documents=tuple(sorted(documents, key=lambda item: item.passage_id)),
        fulltext_queries=fulltext_queries,
        vector_queries=vector_queries,
        expected_active_passage_ids=tuple(
            str(item) for item in value["expected_active_passage_ids"]
        ),
        expected_tombstoned_passage_ids=tuple(
            str(item) for item in value["expected_tombstoned_passage_ids"]
        ),
        fulltext_contract=fulltext,
        vector_contract=vector,
        complete_contract=complete,
    )


INTEGRATED_FIXTURE_V2_PROJECTION = load_integrated_fixture_v2_projection()
INTEGRATED_FIXTURE_V2_PROJECTION_DIGEST = (
    INTEGRATED_FIXTURE_V2_PROJECTION.manifest_digest
)
INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID = "graph.complete_fixture_v2"
INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_AGGREGATE_ID = AggregateId.parse(
    "22222222-2222-4222-8222-222222222222"
)


def integrated_fixture_v2_complete_family(
    *,
    ontology_contract_digest: str,
    mapping_contract_digest: str,
) -> ProjectionFamilyDefinition:
    return ProjectionFamilyDefinition(
        family_id=INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
        authority_aggregate_id=(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_AGGREGATE_ID
        ),
        family_kind=ProjectionFamilyKind.GRAPH,
        definition_version="complete-family-v1",
        projector_version="complete-projector-v1",
        ontology_contract_digest=ontology_contract_digest,
        mapping_contract_digest=mapping_contract_digest,
        complete_projection_contract_digest=(
            INTEGRATED_FIXTURE_V2_PROJECTION.complete_contract.contract_digest
        ),
        max_delivery_attempts=3,
        max_gap_span=1000,
    )


def with_integrated_fixture_v2_complete_projection(
    registry: "ProjectionContractRegistry",
) -> "ProjectionContractRegistry":
    from .policy import ProjectionContractRegistry

    if not isinstance(registry, ProjectionContractRegistry):
        raise ProjectionContractError(
            "complete fixture projection requires a typed contract registry"
        )
    structural_candidates = [
        item
        for item in registry.families.definitions()
        if item.family_kind is ProjectionFamilyKind.GRAPH
        and item.complete_projection_contract_digest is None
        and item.projector_version == "structural-projector-v1"
    ]
    if len(structural_candidates) != 1:
        raise ProjectionContractError(
            "complete fixture projection requires one accepted structural family"
        )
    structural = structural_candidates[0]
    # The complete fixture family deliberately reuses the accepted structural
    # ontology and mapping. New derivative contracts are bound separately and
    # cannot change the retained Increment 1 family digests.
    family = integrated_fixture_v2_complete_family(
        ontology_contract_digest=structural.ontology_contract_digest,
        mapping_contract_digest=structural.mapping_contract_digest,
    )
    definitions = list(registry.families.definitions())
    matching = [item for item in definitions if item.family_id == family.family_id]
    if matching:
        if len(matching) != 1 or matching[0].digest != family.digest:
            raise ProjectionContractError(
                "complete fixture projection family identity conflict"
            )
    else:
        definitions.append(family)
    current_versions = {
        item.family_id: registry.family(item.family_id).definition_version
        for item in registry.families.definitions()
    }
    current_versions[family.family_id] = family.definition_version
    families = ProjectionFamilyRegistry(
        definitions,
        ontologies=registry.ontologies,
        mappings=registry.mappings,
        current_versions=current_versions,
    )

    fixture_contracts = INTEGRATED_FIXTURE_V2_PROJECTION.contracts
    if registry.complete_projections is None:
        complete = fixture_contracts
    else:
        fulltext = {
            item.contract_digest: item
            for item in registry.complete_projections.fulltext_contracts()
        }
        vector = {
            item.contract_digest: item
            for item in registry.complete_projections.vector_contracts()
        }
        manifests = {
            item.manifest_digest: item
            for item in registry.complete_projections.fixture_manifests()
        }
        complete_contracts = {
            item.contract_digest: item
            for item in registry.complete_projections.complete_contracts()
        }
        for item in fixture_contracts.fulltext_contracts():
            fulltext.setdefault(item.contract_digest, item)
        for item in fixture_contracts.vector_contracts():
            vector.setdefault(item.contract_digest, item)
        for item in fixture_contracts.fixture_manifests():
            manifests.setdefault(item.manifest_digest, item)
        for item in fixture_contracts.complete_contracts():
            complete_contracts.setdefault(item.contract_digest, item)
        complete = CompleteProjectionContractRegistry(
            fulltext_contracts=fulltext.values(),
            vector_contracts=vector.values(),
            fixture_manifests=manifests.values(),
            complete_contracts=complete_contracts.values(),
        )
    return ProjectionContractRegistry(
        ontologies=registry.ontologies,
        mappings=registry.mappings,
        families=families,
        graphiti_workspaces=registry.graphiti_workspaces,
        complete_projections=complete,
    )


__all__ = [
    "INTEGRATED_FIXTURE_V2_PROJECTION",
    "INTEGRATED_FIXTURE_V2_PROJECTION_DIGEST",
    "INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_AGGREGATE_ID",
    "INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID",
    "FixtureProjectionDocument",
    "FullTextQualificationQuery",
    "IntegratedFixtureV2Projection",
    "VectorQualificationQuery",
    "integrated_fixture_v2_complete_family",
    "load_integrated_fixture_v2_projection",
    "with_integrated_fixture_v2_complete_projection",
]
