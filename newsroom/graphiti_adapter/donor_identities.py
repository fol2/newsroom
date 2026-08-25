"""Non-authoritative Graphiti donor identity contracts (#772)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from struct import pack
from typing import Any, Final, Literal

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.graphiti_adapter.combined_temporal_contract import (
    CONTRACT_NAME,
    SCHEMA_DIGEST,
    CompactPrompt,
    SourceRevisionInput,
)
from newsroom.graphiti_adapter.combined_temporal_evidence import (
    MAX_SEGMENT_BYTES,
    SEGMENTATION_ALGORITHM_VERSION,
)
from newsroom.graphiti_adapter.combined_temporal_validation import (
    GOVERNED_ENTITY_TYPE_IDS,
    RELATION_TYPE_RULE_VERSION,
    VALIDATOR_CONTRACT_VERSION,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CHAT_FALLBACK,
    GRAPHITI_CHAT_MODEL,
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_GENERATION_ID,
)
from newsroom.graphiti_adapter.identity import configuration_digest
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

TrackADecision = Literal[
    "CONTROLLER_ONLY_PROVED", "SEMANTIC_INPUT_REQUIRED", "UNRESOLVED_HOLD"
]
TRACK_A_DECISION: Final[TrackADecision] = "CONTROLLER_ONLY_PROVED"


@dataclass(frozen=True, slots=True)
class SemanticExtractionRequestIdentityV1:
    identity_digest: str
    manifest_json: bytes


@dataclass(frozen=True, slots=True)
class ValidatedSemanticExtractionArtifactV1:
    artifact_digest: str
    identity_digest: str
    manifest_json: bytes


@dataclass(frozen=True, slots=True)
class EmbeddingRequestIdentityV1:
    identity_digest: str
    manifest_json: bytes


@dataclass(frozen=True, slots=True)
class EmbeddingVectorIntegrityV1:
    integrity_digest: str
    identity_digest: str
    manifest_json: bytes


def build_embedding_request_identity(
    *,
    provider: str,
    model: str,
    dimensions: int | None,
    input_data: object,
    provider_options: Mapping[str, object],
) -> EmbeddingRequestIdentityV1:
    if isinstance(input_data, str):
        values = (input_data,)
        input_kind = "STRING"
    elif isinstance(input_data, list) and all(
        isinstance(item, str) for item in input_data
    ):
        values = tuple(input_data)
        input_kind = "STRING_LIST"
    else:
        raise TypeError("embedding input must be a string or list of strings")
    encoded = tuple(item.encode("utf-8") for item in values)
    exact_bytes = (
        encoded[0]
        if input_kind == "STRING"
        else b"".join(len(item).to_bytes(8, "little") + item for item in encoded)
    )
    manifest = {
        "contract": "EmbeddingRequestIdentityV1",
        "dimensions": dimensions,
        "encoding": "UTF-8",
        "input": {
            "byte_digest": digest_bytes(exact_bytes),
            "byte_length": len(exact_bytes),
            "item_count": len(encoded),
            "items": [
                {
                    "byte_digest": digest_bytes(item),
                    "byte_length": len(item),
                }
                for item in encoded
            ],
            "kind": input_kind,
        },
        "input_construction": "ExactUtf8StringOrLengthPrefixedStringListV1",
        "model": model,
        "provider": provider,
        "provider_options": dict(provider_options),
    }
    return EmbeddingRequestIdentityV1(
        identity_digest=digest_canonical(manifest),
        manifest_json=canonical_json_bytes(manifest),
    )


def build_embedding_vector_integrity(
    *,
    request_identity: EmbeddingRequestIdentityV1,
    provider: str,
    model: str,
    vectors: list[list[float]],
    provider_request_id: str,
    receipt_linkage: Mapping[str, str],
) -> EmbeddingVectorIntegrityV1:
    vector_manifest = []
    for index, vector in enumerate(vectors):
        values = tuple(float(value) for value in vector)
        vector_bytes = b"".join(pack("<d", value) for value in values)
        vector_manifest.append(
            {
                "finite": all(isfinite(value) for value in values),
                "index": index,
                "length": len(values),
                "vector_digest": digest_bytes(vector_bytes),
            }
        )
    manifest = {
        "configuration_digest": configuration_digest(),
        "contract": "EmbeddingVectorIntegrityV1",
        "model": model,
        "provider": provider,
        "provider_request_id": provider_request_id,
        "receipt_linkage": dict(receipt_linkage),
        "request_identity_digest": request_identity.identity_digest,
        "vector_encoding": "IEEE-754-little-endian-float64",
        "vectors": vector_manifest,
    }
    return EmbeddingVectorIntegrityV1(
        integrity_digest=digest_canonical(manifest),
        identity_digest=request_identity.identity_digest,
        manifest_json=canonical_json_bytes(manifest),
    )


def build_semantic_request_identity(
    revision: SourceRevisionInput,
    prompt: CompactPrompt,
) -> SemanticExtractionRequestIdentityV1:
    body_bytes = revision.body.encode("utf-8")
    prompt_bytes = prompt.text.encode("utf-8")
    manifest = {
        "contract": "SemanticExtractionRequestIdentityV1",
        "chunk": {
            "byte_digest": digest_bytes(body_bytes),
            "byte_length": len(body_bytes),
            "encoding": "UTF-8",
        },
        "evidence_segments": {
            "algorithm": SEGMENTATION_ALGORITHM_VERSION,
            "manifest": [
                {
                    "end_byte": segment.end_byte,
                    "segment_id": segment.segment_id,
                    "start_byte": segment.start_byte,
                    "text_byte_digest": digest_bytes(segment.text.encode("utf-8")),
                    "text_byte_length": len(segment.text.encode("utf-8")),
                }
                for segment in prompt.segments
            ],
            "maximum_segment_bytes": MAX_SEGMENT_BYTES,
        },
        "output": {
            "contract_name": CONTRACT_NAME,
            "encoding": "UTF-8",
            "language_contract": "source-grounded-language-v1",
        },
        "prompt": {
            "model_visible_byte_digest": digest_bytes(prompt_bytes),
            "model_visible_byte_length": len(prompt_bytes),
        },
        "runtime": {
            "chat_fallback": GRAPHITI_CHAT_FALLBACK,
            "chat_model": GRAPHITI_CHAT_MODEL,
            "configuration_digest": configuration_digest(),
            "framework": GRAPHITI_CORE_RELEASE,
            "generation_id": GRAPHITI_GENERATION_ID,
        },
        "schema": {"digest": SCHEMA_DIGEST},
        "temporal": {
            "basis": revision.temporal_basis,
            "policy": TEMPORAL_POLICY_VERSION,
            "reference_time": revision.reference_time,
        },
        "validator": {
            "contract": VALIDATOR_CONTRACT_VERSION,
            "entity_type_ids": sorted(GOVERNED_ENTITY_TYPE_IDS),
            "relation_type_rule": RELATION_TYPE_RULE_VERSION,
        },
    }
    return SemanticExtractionRequestIdentityV1(
        identity_digest=digest_canonical(manifest),
        manifest_json=canonical_json_bytes(manifest),
    )


def build_validated_artifact(
    *,
    request_identity: SemanticExtractionRequestIdentityV1,
    payload: Mapping[str, Any],
    payload_digest: str,
    raw_output_digest: str,
    prompt: CompactPrompt,
    framework_version: str,
    model_version: str | None,
    outcome: str,
) -> ValidatedSemanticExtractionArtifactV1:
    if outcome not in {
        "TERMINAL_SUCCESS_WITH_PROPOSALS",
        "TERMINAL_SUCCESS_ZERO_PROPOSALS",
    }:
        raise ValueError("validated donor artefact requires a terminal success")
    manifest = {
        "contract": "ValidatedSemanticExtractionArtifactV1",
        "model_identities": {
            "configuration_digest": configuration_digest(),
            "framework_version": framework_version,
            "generation_id": GRAPHITI_GENERATION_ID,
            "model_version": model_version,
        },
        "payload": {
            "entities": [dict(item) for item in payload["entities"]],
            "facts": [dict(item) for item in payload["facts"]],
        },
        "payload_digest": payload_digest,
        "prompt_identity": {
            "contract_name": CONTRACT_NAME,
            "model_visible_byte_digest": digest_bytes(prompt.text.encode("utf-8")),
            "schema_digest": SCHEMA_DIGEST,
        },
        "raw_output_digest": raw_output_digest,
        "request_identity_digest": request_identity.identity_digest,
        "terminal_validity_class": outcome,
        "validator_receipt": {
            "failure_code": "NONE",
            "outcome_class": outcome,
            "validator_contract": VALIDATOR_CONTRACT_VERSION,
        },
    }
    return ValidatedSemanticExtractionArtifactV1(
        artifact_digest=digest_canonical(manifest),
        identity_digest=request_identity.identity_digest,
        manifest_json=canonical_json_bytes(manifest),
    )


def validated_artifact_is_eligible(
    artifact: ValidatedSemanticExtractionArtifactV1,
) -> bool:
    try:
        manifest = json.loads(artifact.manifest_json)
        if (
            not isinstance(manifest, dict)
            or canonical_json_bytes(manifest) != artifact.manifest_json
            or digest_canonical(manifest) != artifact.artifact_digest
            or manifest.get("contract")
            != "ValidatedSemanticExtractionArtifactV1"
            or manifest.get("request_identity_digest")
            != artifact.identity_digest
            or manifest.get("terminal_validity_class")
            not in {
                "TERMINAL_SUCCESS_WITH_PROPOSALS",
                "TERMINAL_SUCCESS_ZERO_PROPOSALS",
            }
        ):
            return False
        validator = manifest.get("validator_receipt")
        payload = manifest.get("payload")
        return (
            isinstance(validator, dict)
            and validator.get("failure_code") == "NONE"
            and validator.get("outcome_class")
            == manifest["terminal_validity_class"]
            and isinstance(payload, dict)
            and manifest.get("payload_digest") == digest_canonical(payload)
        )
    except (KeyError, TypeError, ValueError):
        return False


__all__ = [
    "TRACK_A_DECISION",
    "EmbeddingRequestIdentityV1",
    "EmbeddingVectorIntegrityV1",
    "SemanticExtractionRequestIdentityV1",
    "TrackADecision",
    "ValidatedSemanticExtractionArtifactV1",
    "build_embedding_request_identity",
    "build_embedding_vector_integrity",
    "build_semantic_request_identity",
    "build_validated_artifact",
    "validated_artifact_is_eligible",
]
