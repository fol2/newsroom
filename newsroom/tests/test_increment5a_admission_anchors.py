from __future__ import annotations

import inspect

import pytest

import newsroom.increment5.approval as approval_module
import newsroom.increment5.main_qualification as main_module
from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment5 import Increment5ContractError
from newsroom.increment5 import _main_qualification_v2 as immutable_main
from newsroom.increment5.admission_anchors import (
    ADMISSION_SOURCE_BUNDLE_IDENTITY,
    ADMISSION_SOURCE_MANIFEST_DIGEST,
    APPROVAL_RECORD_DIGEST,
    INCREMENT5_ADMISSION_ANCHORS,
    MAIN_QUALIFICATION_RECORD_DIGEST,
    parse_increment5a_admission_anchors,
)


def test_current_admission_anchors_are_fail_closed() -> None:
    assert APPROVAL_RECORD_DIGEST is None
    assert MAIN_QUALIFICATION_RECORD_DIGEST is None
    assert INCREMENT5_ADMISSION_ANCHORS.approval_record_digest is None
    assert INCREMENT5_ADMISSION_ANCHORS.main_qualification_record_digest is None
    assert main_module.MAIN_QUALIFICATION_RECORD_DIGEST is None
    assert immutable_main.MAIN_QUALIFICATION_RECORD_DIGEST is None


def test_future_record_digests_live_only_in_canonical_data_anchor() -> None:
    owner_digest = "sha256:" + "a" * 64
    main_digest = "sha256:" + "b" * 64
    value = {
        "schema_version": "increment5a-admission-anchors-v1",
        "source_manifest_digest": ADMISSION_SOURCE_MANIFEST_DIGEST,
        "source_bundle_identity": ADMISSION_SOURCE_BUNDLE_IDENTITY,
        "approval_record_digest": owner_digest,
        "main_qualification_record_digest": main_digest,
    }
    parsed = parse_increment5a_admission_anchors(
        canonical_json_bytes(value)
    )
    assert parsed.approval_record_digest == owner_digest
    assert parsed.main_qualification_record_digest == main_digest
    assert "MAIN_QUALIFICATION_RECORD_DIGEST: str | None = None" in (
        inspect.getsource(immutable_main)
    )
    assert "from .admission_anchors import" in inspect.getsource(main_module)


def test_main_anchor_cannot_exist_before_owner_anchor() -> None:
    value = {
        "schema_version": "increment5a-admission-anchors-v1",
        "source_manifest_digest": ADMISSION_SOURCE_MANIFEST_DIGEST,
        "source_bundle_identity": ADMISSION_SOURCE_BUNDLE_IDENTITY,
        "approval_record_digest": None,
        "main_qualification_record_digest": "sha256:" + "b" * 64,
    }
    with pytest.raises(
        Increment5ContractError,
        match="requires owner approval anchor",
    ):
        parse_increment5a_admission_anchors(canonical_json_bytes(value))


def test_owner_statement_externally_binds_reviewed_source_root() -> None:
    body = approval_module.expected_increment5a_owner_approval_body()
    assert ADMISSION_SOURCE_MANIFEST_DIGEST in body
    assert ADMISSION_SOURCE_BUNDLE_IDENTITY in body
    assert "admission-source manifest" in body
    assert "admission-source bundle" in body
