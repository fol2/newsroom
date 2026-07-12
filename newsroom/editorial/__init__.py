"""Credential-free editorial governance primitives.

This package intentionally has no dependency on the live runner, Gateway, or
network clients.  Public-side-effect capability remains outside this module.
"""

from .packages import (
    PackageArtifact,
    PackageIntegrityError,
    PackageValidationError,
    build_candidate_package,
    build_decision_digest,
    build_evidence_package,
    build_publication_package,
    canonicalise_json,
    parse_json_bytes,
    verify_package_bytes,
)

__all__ = [
    "PackageArtifact",
    "PackageIntegrityError",
    "PackageValidationError",
    "build_candidate_package",
    "build_decision_digest",
    "build_evidence_package",
    "build_publication_package",
    "canonicalise_json",
    "parse_json_bytes",
    "verify_package_bytes",
]
