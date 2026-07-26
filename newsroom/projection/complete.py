from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
import math
import re
import unicodedata
from uuid import UUID

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.types import require_token

from .models import ProjectionContractError


_INDEX_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_PROPERTY_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


class CompleteProjectionProfile(StrEnum):
    FIXTURE_QUALIFICATION = "FIXTURE_QUALIFICATION"
    EVALUATION = "EVALUATION"
    PRODUCTION = "PRODUCTION"


class VectorSimilarityFunction(StrEnum):
    COSINE = "COSINE"


class VectorQuantizationType(StrEnum):
    NONE = "NONE"


class VectorProviderKind(StrEnum):
    REPOSITORY_FIXTURE = "REPOSITORY_FIXTURE"


@dataclass(frozen=True, slots=True)
class FullTextIndexContract:
    contract_id: str
    contract_version: str
    implementation_version: str
    index_name: str
    node_label: str
    source_field: str
    retrieval_property: str
    analyzer: str
    provider: str
    unicode_normalization: str = "NFKC"
    casefold: bool = True
    collapse_whitespace: bool = True
    eventually_consistent: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "contract_id",
            "contract_version",
            "implementation_version",
            "node_label",
            "source_field",
            "retrieval_property",
            "analyzer",
            "provider",
        ):
            require_token(getattr(self, field_name), field=field_name)
        if _INDEX_NAME.fullmatch(self.index_name) is None:
            raise ProjectionContractError("full-text index name is invalid")
        if _PROPERTY_NAME.fullmatch(self.retrieval_property) is None:
            raise ProjectionContractError("full-text property name is invalid")
        if self.unicode_normalization != "NFKC":
            raise ProjectionContractError(
                "fixture full-text contract must use NFKC normalization"
            )
        for field_name in (
            "casefold",
            "collapse_whitespace",
            "eventually_consistent",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ProjectionContractError(f"{field_name} must be boolean")
        if self.eventually_consistent:
            raise ProjectionContractError(
                "fixture qualification requires synchronous full-text updates"
            )

    def normalize(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ProjectionContractError("full-text source value must be non-empty")
        normalized = unicodedata.normalize(self.unicode_normalization, value)
        if self.casefold:
            normalized = normalized.casefold()
        if self.collapse_whitespace:
            normalized = " ".join(normalized.split())
        if not normalized:
            raise ProjectionContractError("normalized full-text value is empty")
        return normalized

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "index_name": self.index_name,
            "node_label": self.node_label,
            "source_field": self.source_field,
            "retrieval_property": self.retrieval_property,
            "analyzer": self.analyzer,
            "provider": self.provider,
            "unicode_normalization": self.unicode_normalization,
            "casefold": self.casefold,
            "collapse_whitespace": self.collapse_whitespace,
            "eventually_consistent": self.eventually_consistent,
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class VectorIndexContract:
    contract_id: str
    contract_version: str
    implementation_version: str
    index_name: str
    node_label: str
    vector_property: str
    dimensions: int
    component_scale: int
    provider: str
    similarity_function: VectorSimilarityFunction
    quantization: VectorQuantizationType
    provider_kind: VectorProviderKind
    fixture_only: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "contract_id",
            "contract_version",
            "implementation_version",
            "node_label",
            "vector_property",
            "provider",
        ):
            require_token(getattr(self, field_name), field=field_name)
        if _INDEX_NAME.fullmatch(self.index_name) is None:
            raise ProjectionContractError("vector index name is invalid")
        if _PROPERTY_NAME.fullmatch(self.vector_property) is None:
            raise ProjectionContractError("vector property name is invalid")
        for field_name in ("dimensions", "component_scale"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ProjectionContractError(f"{field_name} must be positive")
        if self.dimensions > 4096:
            raise ProjectionContractError("vector dimensions exceed hard limit")
        if self.component_scale > 1_000_000_000:
            raise ProjectionContractError("vector component scale exceeds hard limit")
        if not isinstance(self.similarity_function, VectorSimilarityFunction):
            raise ProjectionContractError("vector similarity function must be typed")
        if not isinstance(self.quantization, VectorQuantizationType):
            raise ProjectionContractError("vector quantization must be typed")
        if not isinstance(self.provider_kind, VectorProviderKind):
            raise ProjectionContractError("vector provider kind must be typed")
        if not isinstance(self.fixture_only, bool) or not self.fixture_only:
            raise ProjectionContractError(
                "Increment 2B vector contract must remain fixture-only"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "index_name": self.index_name,
            "node_label": self.node_label,
            "vector_property": self.vector_property,
            "dimensions": self.dimensions,
            "component_scale": self.component_scale,
            "provider": self.provider,
            "similarity_function": self.similarity_function.value,
            "quantization": self.quantization.value,
            "provider_kind": self.provider_kind.value,
            "fixture_only": self.fixture_only,
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))

    def require_profile(self, profile: CompleteProjectionProfile) -> None:
        if not isinstance(profile, CompleteProjectionProfile):
            raise ProjectionContractError("projection profile must be typed")
        if profile is not CompleteProjectionProfile.FIXTURE_QUALIFICATION:
            raise ProjectionContractError(
                "fixture-only vector contracts are rejected outside qualification"
            )

    def vector_from_components(self, components: tuple[int, ...]) -> tuple[float, ...]:
        if not isinstance(components, tuple) or len(components) != self.dimensions:
            raise ProjectionContractError("vector components have wrong dimension")
        values: list[float] = []
        non_zero = False
        for component in components:
            if isinstance(component, bool) or not isinstance(component, int):
                raise ProjectionContractError(
                    "fixture vector components must be fixed-point integers"
                )
            if abs(component) > self.component_scale:
                raise ProjectionContractError(
                    "fixture vector component exceeds fixed-point range"
                )
            non_zero = non_zero or component != 0
            value = component / self.component_scale
            if not math.isfinite(value):
                raise ProjectionContractError("fixture vector component is not finite")
            values.append(value)
        if not non_zero:
            raise ProjectionContractError("cosine fixture vector cannot be all zero")
        return tuple(values)


@dataclass(frozen=True, slots=True)
class FixtureVectorDocumentContract:
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
        for field_name in (
            "blob_digest",
            "normalized_text_digest",
            "vector_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
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

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


@dataclass(frozen=True, slots=True)
class FixtureVectorManifestContract:
    schema_version: str
    fixture_id: str
    source_fixture_digest: str
    component_scale: int
    dimensions: int
    canonical_bytes: bytes
    documents: tuple[FixtureVectorDocumentContract, ...]

    def __post_init__(self) -> None:
        require_token(self.schema_version, field="fixture_vector_schema_version")
        try:
            parsed_fixture_id = UUID(self.fixture_id)
        except (ValueError, AttributeError) as exc:
            raise ProjectionContractError(
                "fixture vector fixture identity must be canonical UUID text"
            ) from exc
        if str(parsed_fixture_id) != self.fixture_id:
            raise ProjectionContractError(
                "fixture vector fixture identity must be canonical UUID text"
            )
        validate_sha256_digest(
            self.source_fixture_digest, field="fixture_vector_source_digest"
        )
        for field_name in ("component_scale", "dimensions"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ProjectionContractError(f"{field_name} must be positive")
        if not isinstance(self.canonical_bytes, bytes) or not self.canonical_bytes:
            raise ProjectionContractError(
                "fixture vector manifest canonical bytes are required"
            )
        if not isinstance(self.documents, tuple) or not self.documents:
            raise ProjectionContractError(
                "fixture vector manifest documents must be an immutable tuple"
            )
        passage_ids = tuple(item.passage_id for item in self.documents)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise ProjectionContractError(
                "fixture vector documents must be sorted and unique"
            )
        if any(len(item.components) != self.dimensions for item in self.documents):
            raise ProjectionContractError(
                "fixture vector document dimensions differ from manifest"
            )

    @property
    def manifest_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class CompleteProjectionContract:
    contract_id: str
    contract_version: str
    implementation_version: str
    admitted_relation_projector_version: str
    source_fixture_digest: str
    fixture_vector_manifest_digest: str
    fulltext_contract_digest: str
    vector_contract_digest: str
    required_derivatives: tuple[str, ...] = (
        "ADMITTED_RELATION",
        "FULL_TEXT",
        "STRUCTURAL",
        "VECTOR",
    )

    def __post_init__(self) -> None:
        for field_name in (
            "contract_id",
            "contract_version",
            "implementation_version",
            "admitted_relation_projector_version",
        ):
            require_token(getattr(self, field_name), field=field_name)
        for field_name in (
            "source_fixture_digest",
            "fixture_vector_manifest_digest",
            "fulltext_contract_digest",
            "vector_contract_digest",
        ):
            value = getattr(self, field_name)
            if validate_sha256_digest(value, field=field_name) != value:
                raise ProjectionContractError(f"{field_name} is not canonical")
        required = (
            "ADMITTED_RELATION",
            "FULL_TEXT",
            "STRUCTURAL",
            "VECTOR",
        )
        if self.required_derivatives != required:
            raise ProjectionContractError(
                "complete projection requires the exact four derivative classes"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "admitted_relation_projector_version": (
                self.admitted_relation_projector_version
            ),
            "source_fixture_digest": self.source_fixture_digest,
            "fixture_vector_manifest_digest": self.fixture_vector_manifest_digest,
            "fulltext_contract_digest": self.fulltext_contract_digest,
            "vector_contract_digest": self.vector_contract_digest,
            "required_derivatives": list(self.required_derivatives),
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


class CompleteProjectionContractRegistry:
    def __init__(
        self,
        *,
        fulltext_contracts: Iterable[FullTextIndexContract],
        vector_contracts: Iterable[VectorIndexContract],
        fixture_manifests: Iterable[FixtureVectorManifestContract],
        complete_contracts: Iterable[CompleteProjectionContract],
    ) -> None:
        self._fulltext = self._index_contracts(
            fulltext_contracts,
            identity="full-text",
        )
        self._vector = self._index_contracts(
            vector_contracts,
            identity="vector",
        )
        manifests: dict[str, FixtureVectorManifestContract] = {}
        fixture_keys: set[tuple[str, str]] = set()
        for manifest in fixture_manifests:
            key = (manifest.fixture_id, manifest.source_fixture_digest)
            if key in fixture_keys or manifest.manifest_digest in manifests:
                raise ProjectionContractError(
                    "duplicate fixture vector manifest contract"
                )
            fixture_keys.add(key)
            manifests[manifest.manifest_digest] = manifest
        if not manifests:
            raise ProjectionContractError(
                "fixture vector manifest registry cannot be empty"
            )
        self._manifests = manifests
        complete: dict[str, CompleteProjectionContract] = {}
        complete_keys: set[tuple[str, str]] = set()
        for contract in complete_contracts:
            key = (contract.contract_id, contract.contract_version)
            if key in complete_keys or contract.contract_digest in complete:
                raise ProjectionContractError(
                    "duplicate complete projection contract"
                )
            if contract.fulltext_contract_digest not in self._fulltext:
                raise ProjectionContractError(
                    "complete projection references unknown full-text contract"
                )
            if contract.vector_contract_digest not in self._vector:
                raise ProjectionContractError(
                    "complete projection references unknown vector contract"
                )
            if contract.fixture_vector_manifest_digest not in self._manifests:
                raise ProjectionContractError(
                    "complete projection references unknown fixture vector manifest"
                )
            complete_keys.add(key)
            complete[contract.contract_digest] = contract
        if not complete:
            raise ProjectionContractError(
                "complete projection contract registry cannot be empty"
            )
        self._complete = complete

    @staticmethod
    def _index_contracts(
        contracts: Iterable[FullTextIndexContract] | Iterable[VectorIndexContract],
        *,
        identity: str,
    ) -> dict[str, FullTextIndexContract | VectorIndexContract]:
        by_digest: dict[str, FullTextIndexContract | VectorIndexContract] = {}
        keys: set[tuple[str, str]] = set()
        for contract in contracts:
            key = (contract.contract_id, contract.contract_version)
            if key in keys or contract.contract_digest in by_digest:
                raise ProjectionContractError(
                    f"duplicate {identity} projection contract"
                )
            keys.add(key)
            by_digest[contract.contract_digest] = contract
        if not by_digest:
            raise ProjectionContractError(
                f"{identity} projection contract registry cannot be empty"
            )
        return by_digest

    def fulltext(self, digest: str) -> FullTextIndexContract:
        try:
            contract = self._fulltext[digest]
        except KeyError as exc:
            raise ProjectionContractError(
                "unknown full-text projection contract digest"
            ) from exc
        if not isinstance(contract, FullTextIndexContract):
            raise ProjectionContractError("full-text projection registry is corrupt")
        return contract

    def vector(self, digest: str) -> VectorIndexContract:
        try:
            contract = self._vector[digest]
        except KeyError as exc:
            raise ProjectionContractError(
                "unknown vector projection contract digest"
            ) from exc
        if not isinstance(contract, VectorIndexContract):
            raise ProjectionContractError("vector projection registry is corrupt")
        return contract

    def fixture_manifest(self, digest: str) -> FixtureVectorManifestContract:
        try:
            return self._manifests[digest]
        except KeyError as exc:
            raise ProjectionContractError(
                "unknown fixture vector manifest digest"
            ) from exc

    def complete(self, digest: str) -> CompleteProjectionContract:
        try:
            return self._complete[digest]
        except KeyError as exc:
            raise ProjectionContractError(
                "unknown complete projection contract digest"
            ) from exc

    def fulltext_contracts(self) -> tuple[FullTextIndexContract, ...]:
        return tuple(
            contract
            for _, contract in sorted(self._fulltext.items())
            if isinstance(contract, FullTextIndexContract)
        )

    def vector_contracts(self) -> tuple[VectorIndexContract, ...]:
        return tuple(
            contract
            for _, contract in sorted(self._vector.items())
            if isinstance(contract, VectorIndexContract)
        )

    def fixture_manifests(self) -> tuple[FixtureVectorManifestContract, ...]:
        return tuple(self._manifests[key] for key in sorted(self._manifests))

    def complete_contracts(self) -> tuple[CompleteProjectionContract, ...]:
        return tuple(self._complete[key] for key in sorted(self._complete))


__all__ = [
    "CompleteProjectionContract",
    "CompleteProjectionContractRegistry",
    "CompleteProjectionProfile",
    "FixtureVectorDocumentContract",
    "FixtureVectorManifestContract",
    "FullTextIndexContract",
    "VectorIndexContract",
    "VectorProviderKind",
    "VectorQuantizationType",
    "VectorSimilarityFunction",
]
