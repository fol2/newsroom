from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_MODULE = 'from __future__ import annotations\n\nfrom dataclasses import dataclass\nimport json\nfrom pathlib import Path\nimport re\nfrom typing import Any, Mapping\n\nfrom jsonschema import Draft202012Validator\n\nfrom newsroom.authority.canonical import (\n    canonical_json_bytes,\n    digest_bytes,\n    validate_sha256_digest,\n)\nfrom newsroom.authority.types import UtcTimestamp\n\nfrom .contracts import (\n    Increment5ADecisionPacket,\n    Increment5ContractError,\n)\nfrom .decision import INCREMENT_5A_DECISION_PACKET\nfrom .decision_validation import object_without_duplicate_names\n\n\nMAIN_QUALIFICATION_RECORD_SCHEMA_ID = (\n    "urn:newsroom:increment5a:main-qualification-record:v1"\n)\nMAIN_QUALIFICATION_RECORD_SCHEMA_VERSION = (\n    "increment5a-main-qualification-record-v1"\n)\nMAIN_QUALIFICATION_RECORD_ID = "increment5a-post-merge-main-qualification"\nMAIN_QUALIFICATION_RECORD_VERSION = "increment5a-main-qualification-v1"\nMAIN_QUALIFICATION_SCOPE = "POST_MERGE_INCREMENT5_IMPLEMENTATION_ADMISSION"\nMAIN_QUALIFICATION_REPOSITORY = "fol2/newsroom"\nMAIN_QUALIFICATION_BRANCH = "main"\nMAIN_QUALIFICATION_ISSUE_NUMBER = 250\nMAIN_QUALIFICATION_PULL_REQUEST_NUMBER = 255\nMAIN_QUALIFICATION_WORKFLOW_NAMES = (\n    "CI",\n    "AUTHORITY_A2A",\n    "AUTHORITY_A2B",\n    "PROJECTION_B1",\n    "PROJECTION_B2_B3_C1_NEO4J",\n    "SDLC_EVIDENCE_SHADOW",\n)\nMAIN_QUALIFICATION_RECORD_SCHEMA_PATH = (\n    Path(__file__).resolve().parent\n    / "data"\n    / "increment5a_main_qualification_record_v1.schema.json"\n)\nMAIN_QUALIFICATION_RECORD_PATH = (\n    Path(__file__).resolve().parent\n    / "data"\n    / "increment5a_main_qualification_record_v1.json"\n)\n# A later post-merge admission commit replaces None with the exact canonical\n# record digest after the merged 5A commit has passed exact-main qualification.\nMAIN_QUALIFICATION_RECORD_DIGEST: str | None = None\n_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"\n_COMMIT_PATTERN = r"^[0-9a-f]{40}$"\n\n\nMAIN_QUALIFICATION_RECORD_SCHEMA: dict[str, object] = {\n    "$schema": "https://json-schema.org/draft/2020-12/schema",\n    "$id": MAIN_QUALIFICATION_RECORD_SCHEMA_ID,\n    "type": "object",\n    "required": [\n        "schema_version",\n        "qualification_id",\n        "qualification_version",\n        "qualification_scope",\n        "repository",\n        "branch",\n        "issue_number",\n        "pull_request_number",\n        "qualified_main_commit_sha",\n        "qualified_main_tree_sha",\n        "qualified_main_commit_url",\n        "qualified_at",\n        "approval_record_digest",\n        "proposal",\n        "evidence",\n    ],\n    "additionalProperties": False,\n    "properties": {\n        "schema_version": {"const": MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION},\n        "qualification_id": {"const": MAIN_QUALIFICATION_RECORD_ID},\n        "qualification_version": {"const": MAIN_QUALIFICATION_RECORD_VERSION},\n        "qualification_scope": {"const": MAIN_QUALIFICATION_SCOPE},\n        "repository": {"const": MAIN_QUALIFICATION_REPOSITORY},\n        "branch": {"const": MAIN_QUALIFICATION_BRANCH},\n        "issue_number": {"const": MAIN_QUALIFICATION_ISSUE_NUMBER},\n        "pull_request_number": {\n            "const": MAIN_QUALIFICATION_PULL_REQUEST_NUMBER\n        },\n        "qualified_main_commit_sha": {\n            "type": "string",\n            "pattern": _COMMIT_PATTERN,\n        },\n        "qualified_main_tree_sha": {\n            "type": "string",\n            "pattern": _COMMIT_PATTERN,\n        },\n        "qualified_main_commit_url": {\n            "type": "string",\n            "minLength": 1,\n            "maxLength": 512,\n        },\n        "qualified_at": {\n            "type": "string",\n            "minLength": 1,\n            "maxLength": 64,\n        },\n        "approval_record_digest": {\n            "type": "string",\n            "pattern": _SHA256_PATTERN,\n        },\n        "proposal": {\n            "type": "object",\n            "required": [\n                "payload_digest",\n                "record_digest",\n                "contract_bundle_digest",\n                "qualification_profile_schema_digest",\n            ],\n            "additionalProperties": False,\n            "properties": {\n                "payload_digest": {\n                    "type": "string",\n                    "pattern": _SHA256_PATTERN,\n                },\n                "record_digest": {\n                    "type": "string",\n                    "pattern": _SHA256_PATTERN,\n                },\n                "contract_bundle_digest": {\n                    "type": "string",\n                    "pattern": _SHA256_PATTERN,\n                },\n                "qualification_profile_schema_digest": {\n                    "type": "string",\n                    "pattern": _SHA256_PATTERN,\n                },\n            },\n        },\n        "evidence": {\n            "type": "object",\n            "required": ["workflow_runs", "signed_decision"],\n            "additionalProperties": False,\n            "properties": {\n                "workflow_runs": {\n                    "type": "object",\n                    "required": list(MAIN_QUALIFICATION_WORKFLOW_NAMES),\n                    "additionalProperties": False,\n                    "properties": {\n                        name: {"type": "integer", "minimum": 1}\n                        for name in MAIN_QUALIFICATION_WORKFLOW_NAMES\n                    },\n                },\n                "signed_decision": {\n                    "type": "object",\n                    "required": [\n                        "run_id",\n                        "decision_digest",\n                        "test_count",\n                        "skip_count",\n                        "required_skip_count",\n                        "failure_count",\n                        "error_count",\n                    ],\n                    "additionalProperties": False,\n                    "properties": {\n                        "run_id": {"type": "integer", "minimum": 1},\n                        "decision_digest": {\n                            "type": "string",\n                            "pattern": _SHA256_PATTERN,\n                        },\n                        "test_count": {"type": "integer", "minimum": 1},\n                        "skip_count": {"type": "integer", "minimum": 0},\n                        "required_skip_count": {"const": 0},\n                        "failure_count": {"const": 0},\n                        "error_count": {"const": 0},\n                    },\n                },\n            },\n        },\n    },\n}\nDraft202012Validator.check_schema(MAIN_QUALIFICATION_RECORD_SCHEMA)\n_MAIN_QUALIFICATION_VALIDATOR = Draft202012Validator(\n    MAIN_QUALIFICATION_RECORD_SCHEMA\n)\nMAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST = digest_bytes(\n    canonical_json_bytes(MAIN_QUALIFICATION_RECORD_SCHEMA)\n)\n\n\ndef _require_schema_artifact() -> None:\n    try:\n        data = MAIN_QUALIFICATION_RECORD_SCHEMA_PATH.read_bytes()\n        value = json.loads(\n            data.decode("utf-8", errors="strict"),\n            object_pairs_hook=object_without_duplicate_names,\n        )\n    except (OSError, UnicodeError, json.JSONDecodeError) as exc:\n        raise Increment5ContractError(\n            "cannot load Increment 5A main-qualification schema artifact"\n        ) from exc\n    if not isinstance(value, dict):\n        raise Increment5ContractError(\n            "main-qualification schema artifact must be an object"\n        )\n    if (\n        data != canonical_json_bytes(value)\n        or value != MAIN_QUALIFICATION_RECORD_SCHEMA\n        or digest_bytes(data) != MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST\n    ):\n        raise Increment5ContractError(\n            "main-qualification schema artifact differs from repository code"\n        )\n\n\n# MATERIALIZE_SCHEMA_CHECK\n\n\ndef _qualification_schema_digest() -> str:\n    from .profiles import QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST\n\n    return QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST\n\n\ndef _parse_canonical_utc(value: str, *, field: str) -> UtcTimestamp:\n    try:\n        parsed = UtcTimestamp.parse(value)\n    except (TypeError, ValueError) as exc:\n        raise Increment5ContractError(f"{field} is not valid UTC text") from exc\n    if value != parsed.to_text():\n        raise Increment5ContractError(f"{field} must be canonical UTC text")\n    return parsed\n\n\ndef _require_commit_sha(value: object, *, field: str) -> str:\n    if not isinstance(value, str) or re.fullmatch(_COMMIT_PATTERN, value) is None:\n        raise Increment5ContractError(f"{field} must be lowercase 40-hex text")\n    if value == "0" * 40:\n        raise Increment5ContractError(f"{field} cannot be the null commit")\n    return value\n\n\ndef _require_digest(value: object, *, field: str) -> str:\n    if not isinstance(value, str):\n        raise Increment5ContractError(f"{field} must be a digest")\n    try:\n        return validate_sha256_digest(value, field=field)\n    except ValueError as exc:\n        raise Increment5ContractError(f"{field} is not canonical") from exc\n\n\ndef _schema_errors(value: Mapping[str, Any]) -> tuple[str, ...]:\n    errors = sorted(\n        _MAIN_QUALIFICATION_VALIDATOR.iter_errors(value),\n        key=lambda item: [str(component) for component in item.absolute_path],\n    )\n    return tuple(\n        (\n            "/".join(str(component) for component in error.absolute_path)\n            or "<root>"\n        )\n        + ": "\n        + error.message\n        for error in errors\n    )\n\n\n@dataclass(frozen=True, slots=True)\nclass Increment5AMainQualificationRecord:\n    qualified_main_commit_sha: str\n    qualified_main_tree_sha: str\n    qualified_at: UtcTimestamp\n    approval_record_digest: str\n    proposal_payload_digest: str\n    proposal_record_digest: str\n    proposal_contract_bundle_digest: str\n    qualification_profile_schema_digest: str\n    workflow_run_ids: tuple[tuple[str, int], ...]\n    signed_sdlc_decision_digest: str\n    test_count: int\n    skip_count: int\n    record_digest: str\n\n    def __post_init__(self) -> None:\n        _require_commit_sha(\n            self.qualified_main_commit_sha,\n            field="qualified_main_commit_sha",\n        )\n        _require_commit_sha(\n            self.qualified_main_tree_sha,\n            field="qualified_main_tree_sha",\n        )\n        if not isinstance(self.qualified_at, UtcTimestamp):\n            raise Increment5ContractError(\n                "main qualification time must be typed UTC"\n            )\n        for field_name in (\n            "approval_record_digest",\n            "proposal_payload_digest",\n            "proposal_record_digest",\n            "proposal_contract_bundle_digest",\n            "qualification_profile_schema_digest",\n            "signed_sdlc_decision_digest",\n            "record_digest",\n        ):\n            _require_digest(getattr(self, field_name), field=field_name)\n        actual_names = tuple(name for name, _run_id in self.workflow_run_ids)\n        if actual_names != MAIN_QUALIFICATION_WORKFLOW_NAMES:\n            raise Increment5ContractError(\n                "main qualification workflow inventory differs"\n            )\n        run_ids: list[int] = []\n        for name, run_id in self.workflow_run_ids:\n            if (\n                name not in MAIN_QUALIFICATION_WORKFLOW_NAMES\n                or isinstance(run_id, bool)\n                or not isinstance(run_id, int)\n                or run_id <= 0\n            ):\n                raise Increment5ContractError(\n                    "main qualification workflow evidence is invalid"\n                )\n            run_ids.append(run_id)\n        if len(set(run_ids)) != len(run_ids):\n            raise Increment5ContractError(\n                "main qualification workflow run identities must be distinct"\n            )\n        if (\n            isinstance(self.test_count, bool)\n            or not isinstance(self.test_count, int)\n            or self.test_count <= 0\n            or isinstance(self.skip_count, bool)\n            or not isinstance(self.skip_count, int)\n            or self.skip_count < 0\n        ):\n            raise Increment5ContractError(\n                "main qualification signed test totals are invalid"\n            )\n\n    @property\n    def workflow_run_id_by_name(self) -> dict[str, int]:\n        return dict(self.workflow_run_ids)\n\n    @property\n    def qualified_main_commit_url(self) -> str:\n        return (\n            f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"\n            f"{self.qualified_main_commit_sha}"\n        )\n\n\ndef main_qualification_record_value(\n    *,\n    proposal: Increment5ADecisionPacket,\n    approval_record_digest: str,\n    qualified_main_commit_sha: str,\n    qualified_main_tree_sha: str,\n    qualified_at: UtcTimestamp,\n    workflow_run_ids: Mapping[str, int],\n    signed_sdlc_decision_digest: str,\n    test_count: int,\n    skip_count: int,\n) -> dict[str, object]:\n    if not isinstance(proposal, Increment5ADecisionPacket):\n        raise Increment5ContractError(\n            "main qualification builder requires a typed proposal"\n        )\n    if not isinstance(qualified_at, UtcTimestamp):\n        raise Increment5ContractError(\n            "main qualification builder requires typed UTC time"\n        )\n    commit_sha = _require_commit_sha(\n        qualified_main_commit_sha,\n        field="qualified_main_commit_sha",\n    )\n    tree_sha = _require_commit_sha(\n        qualified_main_tree_sha,\n        field="qualified_main_tree_sha",\n    )\n    approval_digest = _require_digest(\n        approval_record_digest,\n        field="approval_record_digest",\n    )\n    decision_digest = _require_digest(\n        signed_sdlc_decision_digest,\n        field="signed_sdlc_decision_digest",\n    )\n    if set(workflow_run_ids) != set(MAIN_QUALIFICATION_WORKFLOW_NAMES):\n        raise Increment5ContractError(\n            "main qualification workflow inventory differs"\n        )\n    ordered_runs: dict[str, int] = {}\n    for name in MAIN_QUALIFICATION_WORKFLOW_NAMES:\n        run_id = workflow_run_ids[name]\n        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:\n            raise Increment5ContractError(\n                "main qualification workflow run identity is invalid"\n            )\n        ordered_runs[name] = run_id\n    if len(set(ordered_runs.values())) != len(ordered_runs):\n        raise Increment5ContractError(\n            "main qualification workflow run identities must be distinct"\n        )\n    if (\n        isinstance(test_count, bool)\n        or not isinstance(test_count, int)\n        or test_count <= 0\n        or isinstance(skip_count, bool)\n        or not isinstance(skip_count, int)\n        or skip_count < 0\n    ):\n        raise Increment5ContractError(\n            "main qualification signed test totals are invalid"\n        )\n    return {\n        "schema_version": MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION,\n        "qualification_id": MAIN_QUALIFICATION_RECORD_ID,\n        "qualification_version": MAIN_QUALIFICATION_RECORD_VERSION,\n        "qualification_scope": MAIN_QUALIFICATION_SCOPE,\n        "repository": MAIN_QUALIFICATION_REPOSITORY,\n        "branch": MAIN_QUALIFICATION_BRANCH,\n        "issue_number": MAIN_QUALIFICATION_ISSUE_NUMBER,\n        "pull_request_number": MAIN_QUALIFICATION_PULL_REQUEST_NUMBER,\n        "qualified_main_commit_sha": commit_sha,\n        "qualified_main_tree_sha": tree_sha,\n        "qualified_main_commit_url": (\n            f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"\n            f"{commit_sha}"\n        ),\n        "qualified_at": qualified_at.to_text(),\n        "approval_record_digest": approval_digest,\n        "proposal": {\n            "payload_digest": proposal.payload_digest,\n            "record_digest": proposal.record_digest,\n            "contract_bundle_digest": proposal.bundle.contract_digest,\n            "qualification_profile_schema_digest": (\n                _qualification_schema_digest()\n            ),\n        },\n        "evidence": {\n            "workflow_runs": ordered_runs,\n            "signed_decision": {\n                "run_id": ordered_runs["SDLC_EVIDENCE_SHADOW"],\n                "decision_digest": decision_digest,\n                "test_count": test_count,\n                "skip_count": skip_count,\n                "required_skip_count": 0,\n                "failure_count": 0,\n                "error_count": 0,\n            },\n        },\n    }\n\n\ndef load_increment5a_main_qualification_record(\n    path: Path,\n    *,\n    approval_record_digest: str,\n    proposal: Increment5ADecisionPacket = INCREMENT_5A_DECISION_PACKET,\n) -> Increment5AMainQualificationRecord:\n    expected_approval_digest = _require_digest(\n        approval_record_digest,\n        field="approval_record_digest",\n    )\n    try:\n        data = path.read_bytes()\n        value = json.loads(\n            data.decode("utf-8", errors="strict"),\n            object_pairs_hook=object_without_duplicate_names,\n        )\n    except (OSError, UnicodeError, json.JSONDecodeError) as exc:\n        raise Increment5ContractError(\n            f"cannot read Increment 5A main qualification record: {path}"\n        ) from exc\n    if not isinstance(value, dict):\n        raise Increment5ContractError(\n            "main qualification record root must be an object"\n        )\n    if data != canonical_json_bytes(value):\n        raise Increment5ContractError(\n            "main qualification record must be exact canonical JSON"\n        )\n    errors = _schema_errors(value)\n    if errors:\n        raise Increment5ContractError(\n            "main qualification record schema validation failed: " + errors[0]\n        )\n\n    proposal_value = value["proposal"]\n    evidence = value["evidence"]\n    workflow_runs = evidence["workflow_runs"]\n    signed_decision = evidence["signed_decision"]\n    commit_sha = _require_commit_sha(\n        value["qualified_main_commit_sha"],\n        field="qualified_main_commit_sha",\n    )\n    tree_sha = _require_commit_sha(\n        value["qualified_main_tree_sha"],\n        field="qualified_main_tree_sha",\n    )\n    expected_url = (\n        f"https://github.com/{MAIN_QUALIFICATION_REPOSITORY}/commit/"\n        f"{commit_sha}"\n    )\n    if value["qualified_main_commit_url"] != expected_url:\n        raise Increment5ContractError(\n            "main qualification commit URL differs"\n        )\n    if value["approval_record_digest"] != expected_approval_digest:\n        raise Increment5ContractError(\n            "main qualification approval digest differs"\n        )\n    expected_proposal = {\n        "payload_digest": proposal.payload_digest,\n        "record_digest": proposal.record_digest,\n        "contract_bundle_digest": proposal.bundle.contract_digest,\n        "qualification_profile_schema_digest": (\n            _qualification_schema_digest()\n        ),\n    }\n    if proposal_value != expected_proposal:\n        raise Increment5ContractError(\n            "main qualification record does not bind the exact proposal"\n        )\n    ordered_runs = tuple(\n        (name, workflow_runs[name])\n        for name in MAIN_QUALIFICATION_WORKFLOW_NAMES\n    )\n    if signed_decision["run_id"] != dict(ordered_runs)[\n        "SDLC_EVIDENCE_SHADOW"\n    ]:\n        raise Increment5ContractError(\n            "signed decision run differs from workflow evidence"\n        )\n    return Increment5AMainQualificationRecord(\n        qualified_main_commit_sha=commit_sha,\n        qualified_main_tree_sha=tree_sha,\n        qualified_at=_parse_canonical_utc(\n            value["qualified_at"],\n            field="qualified_at",\n        ),\n        approval_record_digest=expected_approval_digest,\n        proposal_payload_digest=proposal_value["payload_digest"],\n        proposal_record_digest=proposal_value["record_digest"],\n        proposal_contract_bundle_digest=proposal_value[\n            "contract_bundle_digest"\n        ],\n        qualification_profile_schema_digest=proposal_value[\n            "qualification_profile_schema_digest"\n        ],\n        workflow_run_ids=ordered_runs,\n        signed_sdlc_decision_digest=signed_decision["decision_digest"],\n        test_count=signed_decision["test_count"],\n        skip_count=signed_decision["skip_count"],\n        record_digest=digest_bytes(data),\n    )\n'
TEST_MODULE = 'from __future__ import annotations\n\nfrom copy import deepcopy\nimport json\nfrom pathlib import Path\n\nimport pytest\n\nfrom newsroom.authority.canonical import canonical_json_bytes, digest_bytes\nfrom newsroom.authority.types import UtcTimestamp\nfrom newsroom.increment5 import (\n    INCREMENT_5A_DECISION_AUTHORITY,\n    INCREMENT_5A_DECISION_PACKET,\n    Increment5ContractError,\n    MAIN_QUALIFICATION_RECORD_DIGEST,\n    MAIN_QUALIFICATION_RECORD_PATH,\n    MAIN_QUALIFICATION_RECORD_SCHEMA,\n    MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST,\n    MAIN_QUALIFICATION_RECORD_SCHEMA_PATH,\n    MAIN_QUALIFICATION_WORKFLOW_NAMES,\n    load_increment5a_main_qualification_record,\n    main_qualification_record_value,\n    repository_main_qualification_record,\n)\n\n\n_APPROVAL_DIGEST = "sha256:" + "a" * 64\n_COMMIT_SHA = "1" * 40\n_TREE_SHA = "2" * 40\n_QUALIFIED_AT = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")\n_WORKFLOW_RUNS = {\n    "CI": 101,\n    "AUTHORITY_A2A": 102,\n    "AUTHORITY_A2B": 103,\n    "PROJECTION_B1": 104,\n    "PROJECTION_B2_B3_C1_NEO4J": 105,\n    "SDLC_EVIDENCE_SHADOW": 106,\n}\n_DECISION_DIGEST = "sha256:" + "b" * 64\n\n\ndef _value() -> dict[str, object]:\n    return main_qualification_record_value(\n        proposal=INCREMENT_5A_DECISION_PACKET,\n        approval_record_digest=_APPROVAL_DIGEST,\n        qualified_main_commit_sha=_COMMIT_SHA,\n        qualified_main_tree_sha=_TREE_SHA,\n        qualified_at=_QUALIFIED_AT,\n        workflow_run_ids=_WORKFLOW_RUNS,\n        signed_sdlc_decision_digest=_DECISION_DIGEST,\n        test_count=1911,\n        skip_count=38,\n    )\n\n\ndef _write(tmp_path: Path, value: dict[str, object]) -> Path:\n    path = tmp_path / "main-qualification.json"\n    path.write_bytes(canonical_json_bytes(value))\n    return path\n\n\ndef test_main_qualification_schema_artifact_is_canonical() -> None:\n    data = MAIN_QUALIFICATION_RECORD_SCHEMA_PATH.read_bytes()\n    assert data == canonical_json_bytes(json.loads(data.decode("utf-8")))\n    assert digest_bytes(data) == MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST\n    assert MAIN_QUALIFICATION_RECORD_SCHEMA["properties"]["branch"] == {\n        "const": "main"\n    }\n\n\ndef test_current_branch_has_no_post_merge_implementation_admission() -> None:\n    assert MAIN_QUALIFICATION_RECORD_DIGEST is None\n    assert not MAIN_QUALIFICATION_RECORD_PATH.exists()\n    assert repository_main_qualification_record() is None\n    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized\n    assert not (\n        INCREMENT_5A_DECISION_AUTHORITY.downstream_implementation_authorized\n    )\n    assert INCREMENT_5A_DECISION_AUTHORITY.main_qualification_record_digest is None\n    assert INCREMENT_5A_DECISION_AUTHORITY.qualified_main_commit_sha is None\n\n\ndef test_main_qualification_record_binds_exact_approval_and_main_evidence(\n    tmp_path: Path,\n) -> None:\n    record = load_increment5a_main_qualification_record(\n        _write(tmp_path, _value()),\n        approval_record_digest=_APPROVAL_DIGEST,\n    )\n    assert record.qualified_main_commit_sha == _COMMIT_SHA\n    assert record.qualified_main_tree_sha == _TREE_SHA\n    assert record.qualified_at == _QUALIFIED_AT\n    assert record.approval_record_digest == _APPROVAL_DIGEST\n    assert record.workflow_run_id_by_name == _WORKFLOW_RUNS\n    assert record.signed_sdlc_decision_digest == _DECISION_DIGEST\n    assert record.test_count == 1911\n    assert record.skip_count == 38\n\n\ndef test_main_qualification_record_rejects_wrong_approval(\n    tmp_path: Path,\n) -> None:\n    with pytest.raises(\n        Increment5ContractError,\n        match="approval digest differs",\n    ):\n        load_increment5a_main_qualification_record(\n            _write(tmp_path, _value()),\n            approval_record_digest="sha256:" + "c" * 64,\n        )\n\n\ndef test_main_qualification_record_rejects_wrong_proposal(\n    tmp_path: Path,\n) -> None:\n    value = _value()\n    proposal = value["proposal"]\n    assert isinstance(proposal, dict)\n    proposal["payload_digest"] = "sha256:" + "c" * 64\n    with pytest.raises(\n        Increment5ContractError,\n        match="does not bind the exact proposal",\n    ):\n        load_increment5a_main_qualification_record(\n            _write(tmp_path, value),\n            approval_record_digest=_APPROVAL_DIGEST,\n        )\n\n\ndef test_main_qualification_record_rejects_incomplete_or_reused_runs(\n    tmp_path: Path,\n) -> None:\n    missing = _value()\n    evidence = missing["evidence"]\n    assert isinstance(evidence, dict)\n    workflow_runs = evidence["workflow_runs"]\n    assert isinstance(workflow_runs, dict)\n    workflow_runs.pop("CI")\n    with pytest.raises(\n        Increment5ContractError,\n        match="schema validation failed",\n    ):\n        load_increment5a_main_qualification_record(\n            _write(tmp_path, missing),\n            approval_record_digest=_APPROVAL_DIGEST,\n        )\n\n    reused = deepcopy(_WORKFLOW_RUNS)\n    reused["CI"] = reused["AUTHORITY_A2A"]\n    with pytest.raises(\n        Increment5ContractError,\n        match="must be distinct",\n    ):\n        main_qualification_record_value(\n            proposal=INCREMENT_5A_DECISION_PACKET,\n            approval_record_digest=_APPROVAL_DIGEST,\n            qualified_main_commit_sha=_COMMIT_SHA,\n            qualified_main_tree_sha=_TREE_SHA,\n            qualified_at=_QUALIFIED_AT,\n            workflow_run_ids=reused,\n            signed_sdlc_decision_digest=_DECISION_DIGEST,\n            test_count=1911,\n            skip_count=38,\n        )\n\n\ndef test_main_qualification_record_requires_canonical_utc(\n    tmp_path: Path,\n) -> None:\n    value = _value()\n    value["qualified_at"] = "2042-03-12T12:00:00Z"\n    with pytest.raises(\n        Increment5ContractError,\n        match="canonical UTC text",\n    ):\n        load_increment5a_main_qualification_record(\n            _write(tmp_path, value),\n            approval_record_digest=_APPROVAL_DIGEST,\n        )\n\n\ndef test_workflow_inventory_is_exact() -> None:\n    assert MAIN_QUALIFICATION_WORKFLOW_NAMES == (\n        "CI",\n        "AUTHORITY_A2A",\n        "AUTHORITY_A2B",\n        "PROJECTION_B1",\n        "PROJECTION_B2_B3_C1_NEO4J",\n        "SDLC_EVIDENCE_SHADOW",\n    )\n'


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    module_path = REPO_ROOT / "newsroom/increment5/main_qualification.py"
    module_path.write_text(MAIN_MODULE, encoding="utf-8")

    # Load with the artifact check disabled, materialise the canonical schema,
    # then enable the import-time repository check for all later processes.
    from newsroom.increment5.main_qualification import (
        MAIN_QUALIFICATION_RECORD_SCHEMA,
        MAIN_QUALIFICATION_RECORD_SCHEMA_PATH,
    )
    from newsroom.authority.canonical import canonical_json_bytes

    MAIN_QUALIFICATION_RECORD_SCHEMA_PATH.write_bytes(
        canonical_json_bytes(MAIN_QUALIFICATION_RECORD_SCHEMA)
    )
    module_text = module_path.read_text(encoding="utf-8")
    module_text = replace_once(
        module_text,
        "# MATERIALIZE_SCHEMA_CHECK",
        "_require_schema_artifact()",
        label="schema check activation",
    )
    module_path.write_text(module_text, encoding="utf-8")

    approval_path = REPO_ROOT / "newsroom/increment5/approval.py"
    approval = approval_path.read_text(encoding="utf-8")
    import_anchor = """from .decision_validation import (
    object_without_duplicate_names,
    require_digest,
    require_exact_keys,
    require_integer,
    require_mapping,
    require_string,
)


"""
    import_replacement = import_anchor + """from .main_qualification import (
    MAIN_QUALIFICATION_RECORD_DIGEST,
    MAIN_QUALIFICATION_RECORD_PATH,
    Increment5AMainQualificationRecord,
    load_increment5a_main_qualification_record,
)


"""
    approval = replace_once(
        approval,
        import_anchor,
        import_replacement,
        label="main qualification imports",
    )

    loader_anchor = "def _effective_contract_digest_factory(\n"
    loader_block = """def _main_qualification_loader_factory(
    *,
    path: Path,
    expected_digest: str | None,
    approval_record_digest: str | None,
    parser: Callable[..., Increment5AMainQualificationRecord] = (
        load_increment5a_main_qualification_record
    ),
) -> Callable[[], Increment5AMainQualificationRecord | None]:
    captured_path = path
    captured_digest = expected_digest
    captured_approval_digest = approval_record_digest
    captured_parser = parser

    def load() -> Increment5AMainQualificationRecord | None:
        if captured_digest is None:
            if captured_path.exists():
                raise Increment5ContractError(
                    "unadmitted post-merge main qualification record is present"
                )
            return None
        if captured_approval_digest is None:
            raise Increment5ContractError(
                "post-merge qualification cannot exist without owner approval"
            )
        try:
            validate_sha256_digest(
                captured_digest,
                field="main_qualification_record_digest",
            )
        except ValueError as exc:
            raise Increment5ContractError(
                "main qualification record digest is invalid"
            ) from exc
        if not captured_path.is_file():
            raise Increment5ContractError(
                "admitted post-merge main qualification record is missing"
            )
        qualification = captured_parser(
            captured_path,
            approval_record_digest=captured_approval_digest,
        )
        if qualification.record_digest != captured_digest:
            raise Increment5ContractError(
                "post-merge main qualification record digest differs"
            )
        return qualification

    return load


_LOAD_MAIN_QUALIFICATION = _main_qualification_loader_factory(
    path=MAIN_QUALIFICATION_RECORD_PATH,
    expected_digest=MAIN_QUALIFICATION_RECORD_DIGEST,
    approval_record_digest=APPROVAL_RECORD_DIGEST,
)


def repository_main_qualification_record(
    _load: Callable[
        [], Increment5AMainQualificationRecord | None
    ] = _LOAD_MAIN_QUALIFICATION,
) -> Increment5AMainQualificationRecord | None:
    'Return only the source-pinned post-merge exact-main admission.'

    return _load()


def require_repository_main_qualification_record(
    _load: Callable[
        [], Increment5AMainQualificationRecord | None
    ] = _LOAD_MAIN_QUALIFICATION,
) -> Increment5AMainQualificationRecord:
    qualification = _load()
    if qualification is None:
        raise Increment5ProfileError(
            "Increment 5 implementation remains blocked until the admitted "
            "post-merge exact-main qualification record exists"
        )
    return qualification


"""
    approval = replace_once(
        approval,
        loader_anchor,
        loader_block + loader_anchor,
        label="main qualification loader insertion",
    )

    old_factory = """def _decision_authority_class_factory(
    *,
    proposal: Increment5ADecisionPacket,
    load_approval: Callable[[], Increment5AApprovalAttestation | None],
    effective_contract_digest_for: Callable[
        [Increment5AApprovalAttestation | None], str
    ],
) -> type:
    captured_proposal = proposal
    captured_loader = load_approval
    captured_effective_digest = effective_contract_digest_for
"""
    new_factory = """def _decision_authority_class_factory(
    *,
    proposal: Increment5ADecisionPacket,
    load_approval: Callable[[], Increment5AApprovalAttestation | None],
    load_main_qualification: Callable[
        [], Increment5AMainQualificationRecord | None
    ],
    effective_contract_digest_for: Callable[
        [Increment5AApprovalAttestation | None], str
    ],
) -> type:
    captured_proposal = proposal
    captured_loader = load_approval
    captured_main_loader = load_main_qualification
    captured_effective_digest = effective_contract_digest_for
"""
    approval = replace_once(
        approval,
        old_factory,
        new_factory,
        label="authority factory signature",
    )

    old_prod = """        @property
        def production_authorized(self) -> bool:
            return captured_loader() is not None

        @property
        def approval_attestation_digest(self) -> str | None:
"""
    new_prod = """        @property
        def production_qualification_authorized(self) -> bool:
            return captured_loader() is not None

        @property
        def production_authorized(self) -> bool:
            approval = captured_loader()
            if approval is None:
                return False
            qualification = captured_main_loader()
            return (
                qualification is not None
                and qualification.approval_record_digest
                == approval.attestation_digest
            )

        @property
        def downstream_implementation_authorized(self) -> bool:
            return self.production_authorized

        @property
        def approval_attestation_digest(self) -> str | None:
"""
    approval = replace_once(
        approval,
        old_prod,
        new_prod,
        label="authority production semantics",
    )

    approval_claim_anchor = """        @property
        def approval_claim_digest(self) -> str | None:
            return self.approval_attestation_digest

        @property
        def effective_contract_digest(self) -> str:
"""
    approval_claim_replacement = """        @property
        def approval_claim_digest(self) -> str | None:
            return self.approval_attestation_digest

        @property
        def main_qualification_record_digest(self) -> str | None:
            qualification = captured_main_loader()
            return None if qualification is None else qualification.record_digest

        @property
        def qualified_main_commit_sha(self) -> str | None:
            qualification = captured_main_loader()
            return (
                None
                if qualification is None
                else qualification.qualified_main_commit_sha
            )

        @property
        def effective_contract_digest(self) -> str:
"""
    approval = replace_once(
        approval,
        approval_claim_anchor,
        approval_claim_replacement,
        label="main qualification authority properties",
    )

    component_anchor = """        def component_authorized(
            self,
            kind: RetrievalComponentKind,
        ) -> bool:
"""
    downstream_property = """        @property
        def downstream_contract_digest(self) -> str | None:
            approval = captured_loader()
            qualification = captured_main_loader()
            if approval is None or qualification is None:
                return None
            return digest_bytes(
                canonical_json_bytes(
                    {
                        "contract": (
                            "increment5a-post-merge-implementation-authority-v1"
                        ),
                        "proposal_payload_digest": captured_proposal.payload_digest,
                        "proposal_record_digest": captured_proposal.record_digest,
                        "proposal_contract_bundle_digest": (
                            captured_proposal.bundle.contract_digest
                        ),
                        "approval_record_digest": approval.attestation_digest,
                        "main_qualification_record_digest": (
                            qualification.record_digest
                        ),
                        "qualified_main_commit_sha": (
                            qualification.qualified_main_commit_sha
                        ),
                        "qualified_main_tree_sha": (
                            qualification.qualified_main_tree_sha
                        ),
                    }
                )
            )

"""
    approval = replace_once(
        approval,
        component_anchor,
        downstream_property + component_anchor,
        label="downstream contract property",
    )

    old_component = """            approval = captured_loader()
            if approval is None:
                return False
            expected = captured_proposal.bundle.component_by_kind[
                kind
            ].identity_digest
            return approval.component_digest_by_kind.get(kind) == expected
"""
    new_component = """            if not self.production_authorized:
                return False
            approval = captured_loader()
            assert approval is not None
            expected = captured_proposal.bundle.component_by_kind[
                kind
            ].identity_digest
            return approval.component_digest_by_kind.get(kind) == expected
"""
    approval = replace_once(
        approval,
        old_component,
        new_component,
        label="component post-merge gate",
    )

    old_require = """            approval = captured_loader()
            if approval is None:
                raise Increment5ProfileError(
                    "PRODUCTION is not authorized without the admitted "
                    "repository owner approval record"
                )
            for kind in RetrievalComponentKind:
"""
    new_require = """            approval = captured_loader()
            if approval is None:
                raise Increment5ProfileError(
                    "PRODUCTION is not authorized without the admitted "
                    "repository owner approval record"
                )
            qualification = captured_main_loader()
            if qualification is None:
                raise Increment5ProfileError(
                    "Increment 5 implementation remains blocked until the "
                    "admitted post-merge exact-main qualification record exists"
                )
            if qualification.approval_record_digest != approval.attestation_digest:
                raise Increment5ProfileError(
                    "post-merge qualification does not bind owner approval"
                )
            for kind in RetrievalComponentKind:
"""
    approval = replace_once(
        approval,
        old_require,
        new_require,
        label="profile post-merge gate",
    )

    construct_old = """Increment5ADecisionAuthority = _decision_authority_class_factory(
    proposal=INCREMENT_5A_DECISION_PACKET,
    load_approval=_LOAD_REPOSITORY_APPROVAL,
    effective_contract_digest_for=_EFFECTIVE_CONTRACT_DIGEST_FOR,
)
"""
    construct_new = """Increment5ADecisionAuthority = _decision_authority_class_factory(
    proposal=INCREMENT_5A_DECISION_PACKET,
    load_approval=_LOAD_REPOSITORY_APPROVAL,
    load_main_qualification=_LOAD_MAIN_QUALIFICATION,
    effective_contract_digest_for=_EFFECTIVE_CONTRACT_DIGEST_FOR,
)
"""
    approval = replace_once(
        approval,
        construct_old,
        construct_new,
        label="authority construction",
    )
    approval_path.write_text(approval, encoding="utf-8")

    init_path = REPO_ROOT / "newsroom/increment5/__init__.py"
    init = init_path.read_text(encoding="utf-8")
    trace_anchor = "from .traceability import (\n"
    main_import = """from .main_qualification import (
    MAIN_QUALIFICATION_BRANCH,
    MAIN_QUALIFICATION_RECORD_DIGEST,
    MAIN_QUALIFICATION_RECORD_ID,
    MAIN_QUALIFICATION_RECORD_PATH,
    MAIN_QUALIFICATION_RECORD_SCHEMA,
    MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST,
    MAIN_QUALIFICATION_RECORD_SCHEMA_ID,
    MAIN_QUALIFICATION_RECORD_SCHEMA_PATH,
    MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION,
    MAIN_QUALIFICATION_RECORD_VERSION,
    MAIN_QUALIFICATION_SCOPE,
    MAIN_QUALIFICATION_WORKFLOW_NAMES,
    Increment5AMainQualificationRecord,
    load_increment5a_main_qualification_record,
    main_qualification_record_value,
)
"""
    init = replace_once(
        init,
        trace_anchor,
        main_import + trace_anchor,
        label="main qualification package import",
    )
    approval_import_anchor = """    repository_approval_record,
    require_repository_approval_record,
)
"""
    approval_import_replacement = """    repository_approval_record,
    repository_main_qualification_record,
    require_repository_approval_record,
    require_repository_main_qualification_record,
)
"""
    init = replace_once(
        init,
        approval_import_anchor,
        approval_import_replacement,
        label="approval main qualification exports",
    )

    all_anchor = '    "NormalizationContractIdentity",\n'
    all_main = """    "MAIN_QUALIFICATION_BRANCH",
    "MAIN_QUALIFICATION_RECORD_DIGEST",
    "MAIN_QUALIFICATION_RECORD_ID",
    "MAIN_QUALIFICATION_RECORD_PATH",
    "MAIN_QUALIFICATION_RECORD_SCHEMA",
    "MAIN_QUALIFICATION_RECORD_SCHEMA_DIGEST",
    "MAIN_QUALIFICATION_RECORD_SCHEMA_ID",
    "MAIN_QUALIFICATION_RECORD_SCHEMA_PATH",
    "MAIN_QUALIFICATION_RECORD_SCHEMA_VERSION",
    "MAIN_QUALIFICATION_RECORD_VERSION",
    "MAIN_QUALIFICATION_SCOPE",
    "MAIN_QUALIFICATION_WORKFLOW_NAMES",
    "Increment5AMainQualificationRecord",
"""
    init = replace_once(
        init,
        all_anchor,
        all_main + all_anchor,
        label="main qualification all constants",
    )
    all_function_anchor = '    "load_increment5a_approval_attestation",\n'
    all_function_replacement = """    "load_increment5a_approval_attestation",
    "load_increment5a_main_qualification_record",
    "main_qualification_record_value",
"""
    init = replace_once(
        init,
        all_function_anchor,
        all_function_replacement,
        label="main qualification all functions",
    )
    repo_anchor = """    "repository_approval_record",
    "require_repository_approval_record",
"""
    repo_replacement = """    "repository_approval_record",
    "repository_main_qualification_record",
    "require_repository_approval_record",
    "require_repository_main_qualification_record",
"""
    init = replace_once(
        init,
        repo_anchor,
        repo_replacement,
        label="main qualification repository all",
    )
    init_path.write_text(init, encoding="utf-8")

    test_path = REPO_ROOT / "newsroom/tests/test_increment5a_main_qualification.py"
    test_path.write_text(TEST_MODULE, encoding="utf-8")

    approval_test_path = REPO_ROOT / "newsroom/tests/test_increment5a_approval.py"
    approval_test = approval_test_path.read_text(encoding="utf-8")
    approval_test = replace_once(
        approval_test,
        "    APPROVAL_RECORD_PATH,\n",
        """    APPROVAL_RECORD_PATH,
    MAIN_QUALIFICATION_RECORD_DIGEST,
    MAIN_QUALIFICATION_RECORD_PATH,
""",
        label="approval test main constants import",
    )
    pending_anchor = """    assert repository_approval_record() is None
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized
"""
    pending_replacement = """    assert repository_approval_record() is None
    assert MAIN_QUALIFICATION_RECORD_DIGEST is None
    assert not MAIN_QUALIFICATION_RECORD_PATH.exists()
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_qualification_authorized
    assert not INCREMENT_5A_DECISION_AUTHORITY.production_authorized
    assert not INCREMENT_5A_DECISION_AUTHORITY.downstream_implementation_authorized
"""
    approval_test = replace_once(
        approval_test,
        pending_anchor,
        pending_replacement,
        label="pending main qualification assertions",
    )
    approval_test_path.write_text(approval_test, encoding="utf-8")

    decision_doc = REPO_ROOT / (
        "docs/decisions/2026-08-01-increment-5a-post-merge-qualification-gate.md"
    )
    decision_doc.write_text(
        """# Increment 5A post-merge exact-main qualification gate

**Issue:** #250
**Pull request:** #255
**Pre-approval reviewed head:** `8d70d83180906c548ab494b1359b1eefdb471174`

Owner approval and downstream implementation admission are deliberately separate.

The canonical owner approval record permits production-equivalent qualification
of the exact retrieval contract. It does not by itself permit #251 or any later
Increment 5 implementation to begin. `production_qualification_authorized`
therefore reflects the owner record, while `production_authorized`,
`component_authorized(...)`, and `require_profile(PRODUCTION)` additionally
require a second source-pinned post-merge record.

That later record can be created only after PR #255 is merged and the exact
merged `main` commit has passed all six permanent workflows. It binds:

- the exact merged main commit and tree;
- the exact owner-approval record digest;
- the immutable proposal and hardened qualification-profile schema;
- distinct CI, Authority A2a, Authority A2b, Projection B1, authenticated
  Projection B2/B3/C1 Neo4j and signed SDLC workflow run IDs;
- the signed SDLC decision digest and zero-failure, zero-error,
  zero-required-skip totals; and
- one canonical UTC qualification time.

Before that record is admitted, its digest is `None`, its path must be absent,
and every downstream implementation gate fails closed. A stray unpinned record,
missing pinned record, digest mismatch, wrong approval, wrong proposal,
incomplete workflow inventory, reused workflow run, noncanonical timestamp or
noncanonical JSON is rejected.

The owner approval comment may therefore be materialised and used to qualify the
5A contract without making an unmerged branch a source of 5B authority. Issue
#250 remains open until the post-merge record is separately reviewed, admitted,
merged and exact `main` is requalified. Only then may #251 begin.

This gate authorizes no shadow, canary, production activation, publication,
public effect, live-source execution, external embedding API call, provider
spending or protected-content vector.
""",
        encoding="utf-8",
    )

    checklist_path = REPO_ROOT / (
        "docs/decisions/2026-08-01-increment-5a-approval-materialisation-checklist.md"
    )
    checklist = checklist_path.read_text(encoding="utf-8")
    checklist += """

## Post-merge downstream admission

The owner record alone permits production-equivalent qualification but does not
open #251. After PR #255 merges, qualify the exact merged `main` commit with all
six permanent workflows, build the canonical post-merge main-qualification
record from those immutable run identities and the signed decision, pin its
digest in source in the same reviewed commit, qualify that admission change,
merge it, requalify exact `main`, close #250, and only then begin #251.
"""
    checklist_path.write_text(checklist, encoding="utf-8")


if __name__ == "__main__":
    main()
