from __future__ import annotations

import os
import subprocess

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    SCHEMA_VERSION,
)
from newsroom.increment6.closeout import (
    INCREMENT6G_FINAL_CLOSEOUT_CASES,
    INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT6G_FINAL_NON_EFFECTS,
    INCREMENT6G_FINAL_SCHEMA_FINGERPRINT,
    INCREMENT6G_FINAL_SCHEMA_VERSION,
    increment6g_final_migration_history,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
    Neo4jProjectorConfig,
)
from newsroom.projection.neo4j._adapter import _open_neo4j_adapter
from scripts.sdlc.workflow_lane import service_compatibility_digest


def test_actual_service_increment6g_identity_and_closeout_inventory(
    record_property,
) -> None:
    if os.environ.get("NEWSROOM_NEO4J_SERVICE_REQUIRED") != "1":
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
    assert SCHEMA_VERSION >= INCREMENT6G_FINAL_SCHEMA_VERSION
    history_prefix = increment6g_final_migration_history(
        EXPECTED_MIGRATION_HISTORY
    )

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], text=True
    ).strip()
    history = canonical_json_bytes(
        [list(item) for item in history_prefix]
    ).decode("utf-8")

    record_property("increment6g_source_head_sha", head)
    record_property("increment6g_source_tree_sha", tree)
    record_property(
        "increment6g_schema_version", str(INCREMENT6G_FINAL_SCHEMA_VERSION)
    )
    record_property(
        "increment6g_schema_fingerprint", INCREMENT6G_FINAL_SCHEMA_FINGERPRINT
    )
    record_property("increment6g_migration_history_json", history)
    record_property(
        "increment6g_closeout_inventory_digest",
        INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    )
    record_property(
        "increment6g_closeout_case_count",
        str(len(INCREMENT6G_FINAL_CLOSEOUT_CASES)),
    )
    record_property(
        "increment6g_non_effects",
        ",".join(INCREMENT6G_FINAL_NON_EFFECTS),
    )
    record_property("increment6g_neo4j_image", NEO4J_B2_IMAGE)
    record_property("increment6g_neo4j_server_version", compatibility.server_version)
    record_property("increment6g_neo4j_edition", compatibility.edition)
    record_property("increment6g_neo4j_driver_version", compatibility.driver_version)
    record_property("increment6g_neo4j_database", config.database)
    record_property("increment6g_neo4j_projector_username", config.username)
    record_property(
        "increment6g_service_compatibility_digest",
        service_compatibility_digest(),
    )
