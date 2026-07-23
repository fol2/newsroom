from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence.yml")
TEST = Path("newsroom/tests/test_sdlc_evidence_workflow.py")

workflow = WORKFLOW.read_text(encoding="utf-8")
setup_marker = '''          version: '0.8.0'
          enable-cache: true
'''
setup_replacement = '''          version: '0.8.0'
          github-token: ''
          enable-cache: true
'''
if workflow.count(setup_marker) != 2 or "github-token: ''" in workflow:
    raise SystemExit("setup-uv token insertion mismatch")
workflow = workflow.replace(setup_marker, setup_replacement)

old_persist = '''          {
            echo "NEO4J_ADMIN_PASSWORD=${NEO4J_ADMIN_PASSWORD}"
            echo "NEWSROOM_NEO4J_PROJECTOR_PASSWORD=${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"
          } >> "${GITHUB_ENV}"
'''
new_persist = '''          credential_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          umask 077
          {
            printf 'NEO4J_ADMIN_PASSWORD=%s\\n' "${NEO4J_ADMIN_PASSWORD}"
            printf 'NEWSROOM_NEO4J_PROJECTOR_PASSWORD=%s\\n' "${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"
          } > "${credential_file}"
          chmod 600 "${credential_file}"
'''
if workflow.count(old_persist) != 1 or "newsroom-sdlc-neo4j.env" in workflow:
    raise SystemExit("credential file insertion mismatch")
workflow = workflow.replace(old_persist, new_persist)

wait_marker = '''      - name: Wait for authenticated Neo4j
        shell: bash
        run: |
          set -euo pipefail
          uv run --no-sync python - <<'PY'
'''
wait_replacement = '''      - name: Wait for authenticated Neo4j
        shell: bash
        run: |
          set -euo pipefail
          credential_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          test -f "${credential_file}"
          set -a
          source "${credential_file}"
          set +a
          uv run --no-sync python - <<'PY'
'''
if workflow.count(wait_marker) != 1:
    raise SystemExit("wait credential scope mismatch")
workflow = workflow.replace(wait_marker, wait_replacement)

execute_marker = '''      - name: Execute evidence lane
        shell: bash
        env:
          NEWSROOM_SDLC_CACHE_KEY: ${{ steps.setup_uv.outputs.cache-key }}
          NEWSROOM_SDLC_CACHE_HIT: ${{ steps.setup_uv.outputs.cache-hit }}
        run: |
          set -euo pipefail
          uv run --no-sync python -m scripts.sdlc.workflow_lane execute \\
            --route .sdlc-run/route/route.json \\
            --lane service \\
'''
execute_replacement = '''      - name: Execute evidence lane
        shell: bash
        env:
          NEWSROOM_SDLC_CACHE_KEY: ${{ steps.setup_uv.outputs.cache-key }}
          NEWSROOM_SDLC_CACHE_HIT: ${{ steps.setup_uv.outputs.cache-hit }}
        run: |
          set -euo pipefail
          credential_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          test -f "${credential_file}"
          set -a
          source "${credential_file}"
          set +a
          uv run --no-sync python -m scripts.sdlc.workflow_lane execute \\
            --route .sdlc-run/route/route.json \\
            --lane service \\
'''
if workflow.count(execute_marker) != 1:
    raise SystemExit("execute credential scope mismatch")
workflow = workflow.replace(execute_marker, execute_replacement)

old_cleanup = '''      - name: Remove disposable Neo4j state
        if: always()
        shell: bash
        run: timeout --signal=TERM --kill-after=2s 10s docker rm --force newsroom-sdlc-neo4j || true
'''
cleanup = '''      - name: Remove disposable Neo4j state
        if: always()
        shell: bash
        run: |
          rm -f "${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          timeout --signal=TERM --kill-after=2s 10s docker rm --force newsroom-sdlc-neo4j || true

'''
if workflow.count(old_cleanup) != 1:
    raise SystemExit("credential cleanup mismatch")
workflow = workflow.replace(old_cleanup, "")

service_finalize = '''      - name: Finalize evidence
        if: always()
        shell: bash
        env:
          NEWSROOM_SDLC_CACHE_KEY: ${{ steps.setup_uv.outputs.cache-key }}
          NEWSROOM_SDLC_CACHE_HIT: ${{ steps.setup_uv.outputs.cache-hit }}
        run: |
          set -euo pipefail
          uv run --no-sync python -m scripts.sdlc.workflow_budget finalize-lane \\
            --route .sdlc-run/route/route.json \\
            --lane service \\
            --artifact-root .sdlc-run/service \\
            --output .sdlc-run/service-lane.json \\
            > "${RUNNER_TEMP}/service-finalize-gate.json"
          cat "${RUNNER_TEMP}/service-finalize-gate.json"
'''
if workflow.count(service_finalize) != 1:
    raise SystemExit("service finalization position mismatch")
workflow = workflow.replace(service_finalize, cleanup + service_finalize)
WORKFLOW.write_text(workflow, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
common_marker = '''        "version": "0.8.0",
        "enable-cache": "true",
'''
common_replacement = '''        "version": "0.8.0",
        "github-token": "",
        "enable-cache": "true",
'''
if tests.count(common_marker) != 1:
    raise SystemExit("setup-uv test mismatch")
tests = tests.replace(common_marker, common_replacement)

start_assertion = '''    for required in (
        "::add-mask::${NEO4J_ADMIN_PASSWORD}",
        "::add-mask::${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}",
'''
start_replacement = '''    assert "GITHUB_ENV" not in start
    for required in (
        "::add-mask::${NEO4J_ADMIN_PASSWORD}",
        "::add-mask::${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}",
        '${RUNNER_TEMP}/newsroom-sdlc-neo4j.env',
        'chmod 600 "${credential_file}"',
'''
if tests.count(start_assertion) != 1:
    raise SystemExit("credential start test mismatch")
tests = tests.replace(start_assertion, start_replacement)

wait_assertion = '''    wait = _step("service", "Wait for authenticated Neo4j")["run"]
    for required in (
'''
wait_replacement = '''    wait = _step("service", "Wait for authenticated Neo4j")["run"]
    assert 'source "${credential_file}"' in wait
    execute = _step("service", "Execute evidence lane")["run"]
    assert 'source "${credential_file}"' in execute
    assert "NEO4J_ADMIN_PASSWORD" not in _step("service", "Upload service lane evidence").get("env", {})
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in _step("service", "Upload service lane evidence").get("env", {})
    for required in (
'''
if tests.count(wait_assertion) != 1:
    raise SystemExit("credential wait test mismatch")
tests = tests.replace(wait_assertion, wait_replacement)

cleanup_assertion = '''    assert "docker rm --force newsroom-sdlc-neo4j" in cleanup["run"]
    assert "kill-after=2s 10s" in cleanup["run"]
'''
cleanup_replacement = '''    assert 'rm -f "${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"' in cleanup["run"]
    assert "docker rm --force newsroom-sdlc-neo4j" in cleanup["run"]
    assert "kill-after=2s 10s" in cleanup["run"]
    service_names = [step["name"] for step in _steps("service")]
    assert service_names.index("Execute evidence lane") < service_names.index("Remove disposable Neo4j state")
    assert service_names.index("Remove disposable Neo4j state") < service_names.index("Finalize evidence")
    assert service_names.index("Finalize evidence") < service_names.index("Upload service lane evidence")
'''
if tests.count(cleanup_assertion) != 1:
    raise SystemExit("credential cleanup test mismatch")
tests = tests.replace(cleanup_assertion, cleanup_replacement)

if "test_setup_uv_never_receives_the_github_token" in tests:
    raise SystemExit("token scope test already present")
tests += '''


def test_setup_uv_never_receives_the_github_token() -> None:
    for job_id in ("core", "service"):
        setup = _uses_steps(job_id, SETUP_UV)
        assert len(setup) == 1
        assert setup[0]["with"]["github-token"] == ""


def test_service_credentials_are_removed_before_untrusted_finalization_or_actions() -> None:
    rendered = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "GITHUB_ENV" not in rendered
    credential_file = "${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
    assert rendered.count(credential_file) == 4
    service_steps = _steps("service")
    cleanup_index = next(
        index for index, step in enumerate(service_steps)
        if step["name"] == "Remove disposable Neo4j state"
    )
    assert cleanup_index < next(
        index for index, step in enumerate(service_steps)
        if step["name"] == "Finalize evidence"
    )
    assert cleanup_index < next(
        index for index, step in enumerate(service_steps)
        if step["name"] == "Upload service lane evidence"
    )
    assert all(
        "PASSWORD" not in str(name) and "TOKEN" not in str(name)
        for step in service_steps
        if step.get("uses")
        for name in step.get("env", {})
    )
'''
TEST.write_text(tests, encoding="utf-8")
