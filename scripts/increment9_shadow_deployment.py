#!/usr/bin/env python3
"""Bounded Increment 9A2 readiness probes; no campaign or provider IO."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Mapping

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.deployment import (
    DeploymentError,
    DeploymentPlan,
    IsolatedDeploymentReceipt,
    materialise_isolated_deployment,
    probe_increment9_neo4j,
    probe_macm4_capacity,
    teardown_isolated_deployment,
    verify_materialised_deployment,
    verify_isolated_sqlite_backup_restore,
)


def _write_protected(path: Path, value: Mapping[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise DeploymentError("protected evidence parent permits group or public access")
    payload = canonical_json_bytes(dict(value))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _neo4j(output: Path) -> None:
    password = os.environ.get("NEWSROOM_INCREMENT9_NEO4J_PASSWORD")
    if not password:
        raise DeploymentError("Neo4j readiness credential is absent")
    observed = probe_increment9_neo4j(
        uri=os.environ.get("NEWSROOM_INCREMENT9_NEO4J_URI", "bolt://localhost:7687"),
        username=os.environ.get("NEWSROOM_INCREMENT9_NEO4J_USERNAME", "neo4j"),
        password=password,
    )
    _write_protected(output, observed)


def _read_plan(path: Path) -> DeploymentPlan:
    return DeploymentPlan.from_bytes(path.read_bytes())


def _read_receipt(path: Path) -> IsolatedDeploymentReceipt:
    return IsolatedDeploymentReceipt.from_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    sqlite_parser = subparsers.add_parser("sqlite-backup-restore")
    sqlite_parser.add_argument("--output", type=Path, required=True)
    capacity_parser = subparsers.add_parser("capacity")
    capacity_parser.add_argument("--output", type=Path, required=True)
    capacity_parser.add_argument("--root", default="/")
    neo4j_parser = subparsers.add_parser("neo4j")
    neo4j_parser.add_argument("--output", type=Path, required=True)
    for command in ("materialise", "verify-materialised", "teardown"):
        deployment_parser = subparsers.add_parser(command)
        deployment_parser.add_argument("--plan", type=Path, required=True)
        deployment_parser.add_argument("--root", type=Path, required=True)
        deployment_parser.add_argument("--output", type=Path, required=True)
        if command != "materialise":
            deployment_parser.add_argument("--receipt", type=Path, required=True)
        else:
            deployment_parser.add_argument(
                "--production-snapshot", type=Path, required=True
            )
            deployment_parser.add_argument("--receipt-id", required=True)
            deployment_parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    if args.command == "sqlite-backup-restore":
        _write_protected(
            args.output,
            {
                "probe": "SQLITE_ISOLATED_BACKUP_RESTORE",
                "evidence_digest": verify_isolated_sqlite_backup_restore(),
                "secret_value_count": 0,
            },
        )
    elif args.command == "capacity":
        _write_protected(args.output, probe_macm4_capacity(root=args.root))
    elif args.command == "materialise":
        receipt = materialise_isolated_deployment(
            _read_plan(args.plan),
            root=args.root,
            production_snapshot=args.production_snapshot,
            receipt_id=args.receipt_id,
            created_at=args.created_at,
        )
        _write_protected(args.output, receipt.primitive())
    elif args.command == "verify-materialised":
        digest = verify_materialised_deployment(
            _read_plan(args.plan), _read_receipt(args.receipt), root=args.root
        )
        _write_protected(
            args.output,
            {
                "probe": "ISOLATED_DEPLOYMENT_VERIFICATION",
                "evidence_digest": digest,
                "secret_value_count": 0,
            },
        )
    elif args.command == "teardown":
        digest = teardown_isolated_deployment(
            _read_plan(args.plan), _read_receipt(args.receipt), root=args.root
        )
        _write_protected(
            args.output,
            {
                "probe": "ISOLATED_DEPLOYMENT_TEARDOWN",
                "evidence_digest": digest,
                "secret_value_count": 0,
            },
        )
    else:
        _neo4j(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
