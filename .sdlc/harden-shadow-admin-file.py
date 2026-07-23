from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence.yml")
TEST = Path("newsroom/tests/test_sdlc_evidence_workflow.py")

workflow = WORKFLOW.read_text(encoding="utf-8")
old_generate = '''          credential_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          umask 077
          {
            printf 'NEO4J_ADMIN_PASSWORD=%s\\n' "${NEO4J_ADMIN_PASSWORD}"
            printf 'NEWSROOM_NEO4J_PROJECTOR_PASSWORD=%s\\n' "${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"
          } > "${credential_file}"
          chmod 600 "${credential_file}"
'''
new_generate = '''          admin_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"
          projector_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env"
          umask 077
          printf 'NEO4J_ADMIN_PASSWORD=%s\\n' "${NEO4J_ADMIN_PASSWORD}" > "${admin_file}"
          printf 'NEWSROOM_NEO4J_PROJECTOR_PASSWORD=%s\\n' "${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}" > "${projector_file}"
          chmod 600 "${admin_file}" "${projector_file}"
'''
if workflow.count(old_generate) != 1:
    raise SystemExit("credential split generation mismatch")
workflow = workflow.replace(old_generate, new_generate)

old_wait = '''          credential_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          test -f "${credential_file}"
          set -a
          source "${credential_file}"
          set +a
          uv run --no-sync python - <<'PY'
'''
new_wait = '''          admin_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"
          projector_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env"
          test -f "${admin_file}"
          test -f "${projector_file}"
          set -a
          source "${admin_file}"
          source "${projector_file}"
          set +a
          uv run --no-sync python - <<'PY'
'''
if workflow.count(old_wait) != 1:
    raise SystemExit("credential split wait mismatch")
workflow = workflow.replace(old_wait, new_wait)

wait_end = '''          finally:
              projector.close()
          PY

      - name: Execute evidence lane
'''
wait_end_new = '''          finally:
              projector.close()
          PY
          rm -f "${admin_file}"

      - name: Execute evidence lane
'''
if workflow.count(wait_end) != 1:
    raise SystemExit("admin removal position mismatch")
workflow = workflow.replace(wait_end, wait_end_new)

old_execute = '''          credential_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          test -f "${credential_file}"
          set -a
          source "${credential_file}"
          set +a
          uv run --no-sync python -m scripts.sdlc.workflow_lane execute \\
'''
new_execute = '''          projector_file="${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env"
          test -f "${projector_file}"
          test ! -e "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"
          set -a
          source "${projector_file}"
          set +a
          uv run --no-sync python -m scripts.sdlc.workflow_lane execute \\
'''
if workflow.count(old_execute) != 1:
    raise SystemExit("projector-only execute mismatch")
workflow = workflow.replace(old_execute, new_execute)

old_cleanup = '''          rm -f "${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
          timeout --signal=TERM --kill-after=2s 10s docker rm --force newsroom-sdlc-neo4j || true
'''
new_cleanup = '''          rm -f \\
            "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env" \\
            "${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env"
          timeout --signal=TERM --kill-after=2s 10s docker rm --force newsroom-sdlc-neo4j || true
'''
if workflow.count(old_cleanup) != 1:
    raise SystemExit("split credential cleanup mismatch")
workflow = workflow.replace(old_cleanup, new_cleanup)
WORKFLOW.write_text(workflow, encoding="utf-8")

tests = TEST.read_text(encoding="utf-8")
old = "        '${RUNNER_TEMP}/newsroom-sdlc-neo4j.env',\n        'chmod 600 \"${credential_file}\"',\n"
new = "        '${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env',\n        '${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env',\n        'chmod 600 \"${admin_file}\" \"${projector_file}\"',\n"
if tests.count(old) != 1:
    raise SystemExit("credential generation test mismatch")
tests = tests.replace(old, new)
old = "    assert 'source \"${credential_file}\"' in wait\n    execute = _step(\"service\", \"Execute evidence lane\")[\"run\"]\n    assert 'source \"${credential_file}\"' in execute\n"
new = "    assert 'source \"${admin_file}\"' in wait\n    assert 'source \"${projector_file}\"' in wait\n    assert 'rm -f \"${admin_file}\"' in wait\n    execute = _step(\"service\", \"Execute evidence lane\")[\"run\"]\n    assert 'source \"${projector_file}\"' in execute\n    assert 'source \"${admin_file}\"' not in execute\n    assert 'test ! -e \"${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env\"' in execute\n"
if tests.count(old) != 1:
    raise SystemExit("credential execution test mismatch")
tests = tests.replace(old, new)
old = "    assert 'rm -f \"${RUNNER_TEMP}/newsroom-sdlc-neo4j.env\"' in cleanup[\"run\"]\n"
new = "    assert '${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env' in cleanup[\"run\"]\n    assert '${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env' in cleanup[\"run\"]\n"
if tests.count(old) != 1:
    raise SystemExit("credential cleanup test mismatch")
tests = tests.replace(old, new)
old_final_test = '''    credential_file = "${RUNNER_TEMP}/newsroom-sdlc-neo4j.env"
    assert rendered.count(credential_file) == 4
'''
new_final_test = '''    admin_file = "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"
    projector_file = "${RUNNER_TEMP}/newsroom-sdlc-neo4j-projector.env"
    assert rendered.count(admin_file) == 4
    assert rendered.count(projector_file) == 4
'''
if tests.count(old_final_test) != 1:
    raise SystemExit("split credential test mismatch")
tests = tests.replace(old_final_test, new_final_test)
if "test_service_test_child_has_no_admin_credential_file" in tests:
    raise SystemExit("admin file test already present")
tests += '''


def test_service_test_child_has_no_admin_credential_file() -> None:
    execute = _step("service", "Execute evidence lane")["run"]
    assert 'source "${projector_file}"' in execute
    assert 'source "${admin_file}"' not in execute
    assert 'test ! -e "${RUNNER_TEMP}/newsroom-sdlc-neo4j-admin.env"' in execute
'''
TEST.write_text(tests, encoding="utf-8")
