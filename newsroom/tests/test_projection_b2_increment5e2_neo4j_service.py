from __future__ import annotations

import json
import os
import subprocess
import uuid

import pytest

from newsroom.increment5.final_closeout import (
    INCREMENT5E2_FINAL_CLOSEOUT_CASES,
    INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT5E2_FINAL_NON_EFFECTS,
)
from newsroom.increment5.retrieval_qualification import (
    QUALIFICATION_CORPUS,
    QUALIFICATION_TARGET,
    QualificationDecision,
    RetrievalQualificationEvaluator,
    build_qualification_epoch,
    run_fixture_qualification,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
    Neo4jProjectorConfig,
)
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter
from scripts.sdlc.workflow_lane import service_compatibility_digest


_REQUIRED_FLAG = "NEWSROOM_NEO4J_SERVICE_REQUIRED"


def test_actual_service_increment5e2_target_and_report(
    record_property,
) -> None:
    assert QUALIFICATION_TARGET.graph_engine_image == NEO4J_B2_IMAGE
    assert QUALIFICATION_TARGET.graph_driver_version == NEO4J_B2_DRIVER_VERSION
    if os.environ.get(_REQUIRED_FLAG) != "1":
        pytest.skip("authenticated Neo4j service is not required")

    config = Neo4jProjectorConfig.from_environment()
    adapter = _open_neo4j_adapter(config)
    try:
        compatibility = adapter.verify_compatibility()
    finally:
        adapter.close()

    assert compatibility.server_version == NEO4J_B2_SERVER_VERSION
    assert compatibility.edition == "community"
    assert compatibility.driver_version == NEO4J_B2_DRIVER_VERSION
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"],
        text=True,
    ).strip()
    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=tree,
    )
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, epoch.epoch_digest))
    report = RetrievalQualificationEvaluator().evaluate(
        run_id=run_id,
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        epoch=epoch,
        code_tree_sha=tree,
        observations=run_fixture_qualification(
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
        ),
        started_at="2026-08-08T20:00:00Z",
        completed_at="2026-08-08T20:01:00Z",
    )
    assert report.decision is QualificationDecision.PASS
    assert report.observation_count == 500
    assert report.code_tree_sha == tree
    assert report.external_call_count == 0
    assert report.provider_spend_micros == 0
    assert report.authority_effect == "NONE"
    assert report.production_activation_authorized is False

    record_property("increment5e2_source_head_sha", head)
    record_property("increment5e2_source_tree_sha", tree)
    record_property("increment5e2_neo4j_image", NEO4J_B2_IMAGE)
    record_property("increment5e2_neo4j_server_version", compatibility.server_version)
    record_property("increment5e2_neo4j_edition", compatibility.edition)
    record_property("increment5e2_neo4j_driver_version", compatibility.driver_version)
    record_property("increment5e2_neo4j_database", config.database)
    record_property("increment5e2_neo4j_projector_username", config.username)
    record_property(
        "increment5e2_service_compatibility_digest",
        service_compatibility_digest(),
    )
    record_property("increment5e2_epoch_digest", epoch.epoch_digest)
    record_property(
        "increment5e2_epoch_json",
        json.dumps(
            epoch.canonical_value(),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    record_property("increment5e2_report_digest", report.report_digest)
    record_property(
        "increment5e2_report_json",
        report.canonical_bytes.decode("utf-8"),
    )
    record_property(
        "increment5e2_closeout_inventory_digest",
        INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    )
    record_property(
        "increment5e2_closeout_case_count",
        str(len(INCREMENT5E2_FINAL_CLOSEOUT_CASES)),
    )
    record_property(
        "increment5e2_non_effects",
        ",".join(INCREMENT5E2_FINAL_NON_EFFECTS),
    )
