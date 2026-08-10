# Authority-store conformance harness

`newsroom/tests/authority_store_conformance.py` is a repository-owned,
test-only kernel for the remaining Increment 6 persistence atoms.  It has no
production imports and no store schema knowledge.  A persistence PR supplies a
small adapter implementing `AuthorityStoreAdapter`, returns an
`AuthorityStoreFixture`, and declares only the invariant families that its
store can exercise:

```python
class MyStoreAdapter:
    name = "my-store"
    supported_cases = CASE_INVENTORY

    def build_fixture(self) -> AuthorityStoreFixture: ...
    def exercise_case(self, case, fixture) -> ConformanceEvidence: ...

report = assert_conformant(MyStoreAdapter())
```

`run_conformance` executes the fixed `CASE_INVENTORY` order.  Unsupported
families are recorded as `skipped`; declared families must provide typed
observations and receive a stable `FailureCode` on failure.  `report.render()`
is value-independent and deterministic for CI artefacts.

The inventory covers:

| Case | Required observation |
| --- | --- |
| `fresh_replay` | fresh and exact replay results |
| `fresh_reopen` | fresh and reopened results |
| `representation_binding` | canonical bytes, scalar/identity columns and linked rows |
| `request_binding` | actor, request, idempotency and CAS predecessor |
| `lost_response_replay` | retained-result replay, retained-integrity validation and no unrelated currentness |
| `historical_read` | retained value identity, digest and provenance |
| `current_use_revalidation` | every required upstream head and changed-head rejection |
| `tamper_rejection` | adapter-named direct SQL, linked-row and self-consistent mutations |
| `competing_writers` | deterministic competing-writer outcome |
| `transaction_rollback` | clean rollback boundary |
| `restart_migration` | restart and migration/reopen parity |

The focused test module contains deliberately broken in-memory adapters for
replay, reopen, canonical/scalar and linked-row representations, and historical
reads.  They are fixtures for the harness itself, not examples of any product
store and are intentionally not coupled to PR #380.  A store adapter belongs in
its persistence PR's test tree; this kernel does not change authority runtime
behaviour, migrations, tables or public APIs.
