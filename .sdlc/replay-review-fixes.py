from pathlib import Path

source = Path("scripts/sdlc/transport_replay.py")
text = source.read_text(encoding="utf-8")
replacements = (
    (
        "import os\nfrom pathlib import Path\nimport stat\n",
        "import os\nfrom pathlib import Path\nimport re\nimport stat\n",
    ),
    (
        "from .emit_evidence import sha256_identity\n",
        "from .emit_evidence import canonical_json_bytes, sha256_identity\n",
    ),
    (
        "_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024\n",
        "_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024\n"
        "_SAFE_NAME = re.compile(r\"[A-Za-z0-9_.-]{1,255}\")\n",
    ),
    (
        '_text(self.artifact_name, "artifact_name", maximum=255)\n'
        '        _positive(self.artifact_size_bytes, "artifact_size")\n',
        '_safe_name(self.artifact_name, "artifact_name")\n'
        '        if _positive(self.artifact_size_bytes, "artifact_size") > _MAX_ARCHIVE_BYTES:\n'
        '            raise TransportReplayError("artifact_size")\n',
    ),
    (
        "def _sha(value: object, code: str) -> str:\n",
        "def _safe_name(value: object, code: str) -> str:\n"
        "    text = _text(value, code, maximum=255)\n"
        "    if _SAFE_NAME.fullmatch(text) is None:\n"
        "        raise TransportReplayError(code)\n"
        "    return text\n\n\n"
        "def _sha(value: object, code: str) -> str:\n",
    ),
    (
        'artifact_name=_text(item.get("artifact_name"), "artifact_name", maximum=255),\n'
        '        artifact_size_bytes=_positive(\n'
        '            item.get("artifact_size_bytes"), "artifact_size"\n'
        '        ),\n',
        'artifact_name=_safe_name(item.get("artifact_name"), "artifact_name"),\n'
        '        artifact_size_bytes=_positive(\n'
        '            item.get("artifact_size_bytes"), "artifact_size"\n'
        '        ),\n',
    ),
    (
        "def _digest(payload: bytes) -> str:\n",
        "def _canonical_json(payload: bytes, code: str) -> Mapping[str, object]:\n"
        "    value = _load_json(payload, code)\n"
        "    if payload != canonical_json_bytes(value) + b\"\\n\":\n"
        "        raise TransportReplayError(f\"{code}_canonical\")\n"
        "    return value\n\n\n"
        "def _digest(payload: bytes) -> str:\n",
    ),
    (
        '    for raw in jobs:\n'
        '        job = _mapping(raw, "job")\n'
        '        job_run_id = job.get("run_id")\n'
        '        job_attempt = job.get("run_attempt")\n'
        '        if job_run_id is not None and _positive(job_run_id, "job_run_id") != run_id:\n'
        '            raise TransportReplayError("job_run_id")\n'
        '        if job_attempt is not None and _positive(job_attempt, "job_run_attempt") != attempt:\n'
        '            raise TransportReplayError("job_run_attempt")\n',
        '    for raw in jobs:\n'
        '        job = _mapping(raw, "job")\n'
        '        if _positive(job.get("run_id"), "job_run_id") != run_id:\n'
        '            raise TransportReplayError("job_run_id")\n'
        '        if _positive(job.get("run_attempt"), "job_run_attempt") != attempt:\n'
        '            raise TransportReplayError("job_run_attempt")\n',
    ),
    (
        '    try:\n'
        '        bundle = validate_transport_bundle(_load_json(transport_payload, "transport_json"))\n'
        '    except GitHubTransportError as exc:\n'
        '        raise TransportReplayError("transport_invalid") from exc\n'
        '    run_value = _load_json(run_payload, "run_json")\n'
        '    jobs_value = _load_json(jobs_payload, "jobs_json")\n'
        '    metadata_value = _load_json(metadata_payload, "metadata_json")\n',
        '    try:\n'
        '        bundle = validate_transport_bundle(\n'
        '            _canonical_json(transport_payload, "transport_json")\n'
        '        )\n'
        '    except GitHubTransportError as exc:\n'
        '        raise TransportReplayError("transport_invalid") from exc\n'
        '    run_value = _canonical_json(run_payload, "run_json")\n'
        '    jobs_value = _canonical_json(jobs_payload, "jobs_json")\n'
        '    metadata_value = _canonical_json(metadata_payload, "metadata_json")\n',
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"source replacement mismatch: {old[:80]!r}")
    text = text.replace(old, new)
source.write_text(text, encoding="utf-8")

tests = Path("newsroom/tests/test_sdlc_transport_replay.py")
text = tests.read_text(encoding="utf-8")
replacements = (
    (
        "\ndef _archive(root: Path) -> tuple[bytes, str]:\n",
        "\n\ndef _replay_identity(value: dict[str, object]) -> str:\n"
        "    return sha256_identity(\n"
        "        {key: item for key, item in value.items() if key != \"replay_identity\"}\n"
        "    )\n\n\n"
        "def _archive(root: Path) -> tuple[bytes, str]:\n",
    ),
    (
        'def test_jobs_must_belong_to_exact_run_and_attempt(tmp_path: Path) -> None:\n'
        '    root = _fixture(tmp_path)\n'
        '    jobs = json.loads((root / "jobs.json").read_text(encoding="utf-8"))\n'
        '    jobs["jobs"][0]["run_attempt"] = RUN_ATTEMPT + 1\n'
        '    _rewrite_snapshot(root, "jobs.json", jobs)\n\n'
        '    with pytest.raises(TransportReplayError, match="job_run_attempt"):\n'
        '        load_verified_transport(root)\n',
        '@pytest.mark.parametrize(\n'
        '    ("field", "value", "reason"),\n'
        '    [\n'
        '        ("run_id", None, "job_run_id"),\n'
        '        ("run_attempt", None, "job_run_attempt"),\n'
        '        ("run_id", RUN_ID + 1, "job_run_id"),\n'
        '        ("run_attempt", RUN_ATTEMPT + 1, "job_run_attempt"),\n'
        '    ],\n'
        ')\n'
        'def test_jobs_must_belong_to_exact_run_and_attempt(\n'
        '    tmp_path: Path,\n'
        '    field: str,\n'
        '    value: object,\n'
        '    reason: str,\n'
        ') -> None:\n'
        '    root = _fixture(tmp_path)\n'
        '    jobs = json.loads((root / "jobs.json").read_text(encoding="utf-8"))\n'
        '    if value is None:\n'
        '        del jobs["jobs"][0][field]\n'
        '    else:\n'
        '        jobs["jobs"][0][field] = value\n'
        '    _rewrite_snapshot(root, "jobs.json", jobs)\n\n'
        '    with pytest.raises(TransportReplayError, match=reason):\n'
        '        load_verified_transport(root)\n',
    ),
    (
        "\ndef test_replay_record_rejects_shape_and_identity_tampering",
        "\n\ndef test_snapshots_must_retain_canonical_json_bytes(tmp_path: Path) -> None:\n"
        "    root = _fixture(tmp_path)\n"
        "    run = json.loads((root / \"run.json\").read_text(encoding=\"utf-8\"))\n"
        "    payload = json.dumps(run, indent=2).encode(\"utf-8\") + b\"\\n\"\n"
        "    _write_private(root / \"run.json\", payload)\n"
        "    transport_path = root / \"transport.json\"\n"
        "    transport = json.loads(transport_path.read_text(encoding=\"utf-8\"))\n"
        "    transport[\"run_digest\"] = \"sha256:\" + hashlib.sha256(payload).hexdigest()\n"
        "    transport[\"transport_identity\"] = _transport_identity(transport)\n"
        "    _write_private(transport_path, _json_bytes(transport))\n\n"
        "    with pytest.raises(TransportReplayError, match=\"run_json_canonical\"):\n"
        "        load_verified_transport(root)\n\n\n"
        "def test_standalone_replay_revalidates_artifact_name_and_size(tmp_path: Path) -> None:\n"
        "    replay = load_verified_transport(_fixture(tmp_path)).replay.as_dict()\n\n"
        "    changed = deepcopy(replay)\n"
        "    changed[\"artifact_name\"] = \"unsafe/name\"\n"
        "    changed[\"replay_identity\"] = _replay_identity(changed)\n"
        "    with pytest.raises(TransportReplayError, match=\"artifact_name\"):\n"
        "        validate_transport_replay(changed)\n\n"
        "    changed = deepcopy(replay)\n"
        "    changed[\"artifact_size_bytes\"] = 512 * 1024 * 1024 + 1\n"
        "    changed[\"replay_identity\"] = _replay_identity(changed)\n"
        "    with pytest.raises(TransportReplayError, match=\"artifact_size\"):\n"
        "        validate_transport_replay(changed)\n\n\n"
        "def test_replay_record_rejects_shape_and_identity_tampering",
    ),
)
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"test replacement mismatch: {old[:80]!r}")
    text = text.replace(old, new)
tests.write_text(text, encoding="utf-8")
