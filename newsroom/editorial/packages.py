from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import rfc8785


ENCODING_VERSION = "rfc8785-restricted-v1"
DIGEST_ALGORITHM = "sha256"
MIN_SAFE_INTEGER = -9_007_199_254_740_991
MAX_SAFE_INTEGER = 9_007_199_254_740_991
_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


class PackageValidationError(ValueError):
    """Raised when input cannot enter the immutable package domain."""


class PackageIntegrityError(ValueError):
    """Raised when stored bytes are not canonical or do not match identity."""


@dataclass(frozen=True, slots=True)
class PackageArtifact:
    kind: str
    schema_version: str
    digest_algorithm: str
    digest: str
    byte_size: int
    canonical_bytes: bytes
    value: dict[str, Any]


class _DuplicateName(ValueError):
    pass


def _reject_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateName(f"duplicate JSON object name: {key}")
        value[key] = item
    return value


def parse_json_bytes(data: bytes, *, max_bytes: int | None = None) -> Any:
    if max_bytes is not None and (max_bytes <= 0 or len(data) > max_bytes):
        raise PackageValidationError("JSON input exceeds the configured byte limit")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PackageValidationError("JSON input must be valid UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_names,
            parse_float=lambda value: (_ for _ in ()).throw(
                PackageValidationError(f"floating-point JSON value is unsupported: {value}")
            ),
            parse_constant=lambda value: (_ for _ in ()).throw(
                PackageValidationError(f"non-finite JSON value is unsupported: {value}")
            ),
        )
    except _DuplicateName as exc:
        raise PackageValidationError(str(exc)) from exc
    except PackageValidationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PackageValidationError(f"invalid JSON input: {exc}") from exc


def _validate_string(value: str, path: str) -> None:
    for char in value:
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise PackageValidationError(f"lone surrogate is unsupported at {path}")


def _validate_restricted_domain(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not MIN_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise PackageValidationError(f"integer outside the I-JSON safe range at {path}")
        return
    if isinstance(value, float):
        raise PackageValidationError(f"floating-point values are unsupported at {path}")
    if isinstance(value, str):
        _validate_string(value, path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_restricted_domain(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PackageValidationError(f"object names must be strings at {path}")
            _validate_string(key, f"{path}.<key>")
            _validate_restricted_domain(item, f"{path}.{key}")
        return
    raise PackageValidationError(f"unsupported value type at {path}: {type(value).__name__}")


def canonicalise_json(value: Any) -> bytes:
    _validate_restricted_domain(value)
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, UnicodeError, ValueError) as exc:
        raise PackageValidationError(f"RFC 8785 canonicalisation failed: {exc}") from exc


def digest_bytes(data: bytes) -> str:
    return f"{DIGEST_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


def _load_schemas() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    schema_paths = (
        _SCHEMA_DIR / "evidence_package_v1.schema.json",
        _SCHEMA_DIR / "editorial_candidate_v1.schema.json",
        _SCHEMA_DIR / "publication_package_v1.schema.json",
    )
    for path in schema_paths:
        value = parse_json_bytes(path.read_bytes())
        if not isinstance(value, dict) or not isinstance(value.get("$id"), str):
            raise RuntimeError(f"Schema is missing a local $id: {path}")
        Draft202012Validator.check_schema(value)
        schemas[str(value["$id"])] = value
        resources.append((str(value["$id"]), Resource.from_contents(value)))
    return Registry().with_resources(resources), schemas


_REGISTRY, _SCHEMAS = _load_schemas()


def _validate_schema(value: Mapping[str, Any], schema_name: str) -> dict[str, Any]:
    schema_id = f"https://newsroom.local/schemas/{schema_name}.schema.json"
    schema = _SCHEMAS.get(schema_id)
    if schema is None:
        raise RuntimeError(f"Unregistered editorial schema: {schema_name}")
    validator = Draft202012Validator(
        schema,
        registry=_REGISTRY,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            for error in errors
        )
        raise PackageValidationError(details)
    return dict(value)


def _artifact(kind: str, value: Mapping[str, Any]) -> PackageArtifact:
    canonical_bytes = canonicalise_json(dict(value))
    return PackageArtifact(
        kind=kind,
        schema_version=str(value["schema_version"]),
        digest_algorithm=DIGEST_ALGORITHM,
        digest=digest_bytes(canonical_bytes),
        byte_size=len(canonical_bytes),
        canonical_bytes=canonical_bytes,
        value=dict(value),
    )


def build_evidence_package(value: Mapping[str, Any]) -> PackageArtifact:
    return _artifact("evidence", _validate_schema(value, "evidence_package_v1"))


def build_candidate_package(value: Mapping[str, Any]) -> PackageArtifact:
    return _artifact("candidate", _validate_schema(value, "editorial_candidate_v1"))


def build_decision_digest(
    *,
    candidate_digest: str,
    evidence_digest: str,
    policy_version: str,
    controller_version: str,
    outcome: str,
    reason_codes: list[str],
) -> PackageArtifact:
    if outcome not in {"AUTO_PUBLISH", "HOLD_FOR_REVIEW", "REJECT"}:
        raise PackageValidationError(f"unsupported editorial outcome: {outcome}")
    if not all(isinstance(reason, str) and reason for reason in reason_codes):
        raise PackageValidationError("decision reason codes must be non-empty strings")
    value = {
        "schema_version": "editorial_decision_v1",
        "encoding_version": ENCODING_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "candidate_digest": candidate_digest,
        "evidence_digest": evidence_digest,
        "policy_version": policy_version,
        "controller_version": controller_version,
        "outcome": outcome,
        "reason_codes": list(reason_codes),
    }
    _validate_restricted_domain(value)
    for field in ("candidate_digest", "evidence_digest"):
        digest = str(value[field])
        if len(digest) != 71 or not digest.startswith("sha256:"):
            raise PackageValidationError(f"invalid {field}")
        try:
            int(digest[7:], 16)
        except ValueError as exc:
            raise PackageValidationError(f"invalid {field}") from exc
    if not policy_version or not controller_version:
        raise PackageValidationError("decision versions must be non-empty")
    return _artifact("decision", value)


def build_publication_package(
    value: Mapping[str, Any], *, outcome: str
) -> PackageArtifact:
    if outcome != "AUTO_PUBLISH":
        raise PackageValidationError("publication packages require AUTO_PUBLISH")
    if value.get("outcome") != outcome:
        raise PackageValidationError("publication outcome does not match the decision")
    return _artifact("publication", _validate_schema(value, "publication_package_v1"))


def verify_package_bytes(
    data: bytes, expected_digest: str, *, check_digest: bool = True
) -> dict[str, Any]:
    if check_digest and digest_bytes(data) != expected_digest:
        raise PackageIntegrityError("package digest mismatch")
    try:
        value = parse_json_bytes(data)
        canonical = canonicalise_json(value)
    except PackageValidationError as exc:
        raise PackageIntegrityError(f"invalid package bytes: {exc}") from exc
    if canonical != data:
        raise PackageIntegrityError("package bytes are not canonical")
    if not isinstance(value, dict):
        raise PackageIntegrityError("package root must be an object")
    return value
