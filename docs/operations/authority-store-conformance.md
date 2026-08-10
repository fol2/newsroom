# Authority-store conformance harness

`newsroom/tests/authority_store_conformance.py` is a repository-owned,
test-only kernel for the remaining Increment 6 persistence atoms. It imports no
production code and knows no product schema. A persistence PR supplies a small
`AuthorityStoreAdapter` which translates the generic primitive operations to
its test store:

```python
class MyStoreAdapter:
    name = "my-store"
    applicability = {case: Applicability.required() for case in CASE_INVENTORY}

    def reset(self): ...
    def put(self, command, *, lose_response=False): ...
    def replay(self, command): ...
    def observe(self, record_id): ...
    def load(self, record_id): ...
    def list_history(self): ...
    def set_upstream_head(self, authority, value): ...
    def current_use(self, record_id): ...
    def tamper(self, record_id, kind): ...
    def reopen(self, *, migrate): ...
    def rollback(self, command): ...

report = assert_conformant(MyStoreAdapter())
```

The adapter must expose real state transitions and observable persisted state.
It does not provide expected values, success booleans or per-case evidence.
The kernel owns the fixed commands, sequencing, mutations and normative
assertions. It proves that a row is absent before a write, observes retention,
changes heads, tampers stored forms, attempts same-predecessor writes, rolls a
transaction back and reopens the store. A constant, no-store adapter therefore
does not conform merely by returning self-consistent values.

## Exhaustive applicability

`applicability` is an exhaustive manifest: every member of `CASE_INVENTORY`
must be present. Normally use `Applicability.required()`. A structurally
inapplicable family needs both a stable reason and a reviewed waiver reference:

```python
applicability = {case: Applicability.required() for case in CASE_INVENTORY}
applicability[CaseId.RESTART_MIGRATION] = Applicability.waived(
    reason="store is ephemeral and has no reopen boundary",
    waiver_reference="issue:NNN#reviewed-waiver",
)
```

A missing family, blank reason or blank reference is `ADAPTER_PROTOCOL` and
fails the report. Valid skips render deterministically with both `waiver=` and
`reason=` so CI cannot hide an omitted invariant family.

## Kernel-owned scenarios

| Case | Normative sequence and assertion |
| --- | --- |
| `fresh_replay` | absent → write → retained exact replay |
| `fresh_reopen` | write → reopen → validated equal load |
| `representation_binding` | observe exact canonical bytes, scalar/identity columns and linked rows |
| `request_binding` | observe exact actor, request, idempotency and CAS predecessor |
| `lost_response_replay` | retain before lost response, replay despite changed use-time heads, reject retained tamper |
| `historical_read` | load/list retained value, then reject identity, digest and provenance mutations |
| `current_use_revalidation` | accept matching heads and reject each required head independently after change |
| `tamper_rejection` | reject direct canonical, linked-row and self-consistent offline rewrites |
| `competing_writers` | accept one same-predecessor writer and reject the other without retention |
| `transaction_rollback` | observe no row or history after rollback |
| `restart_migration` | retain validated value and representation across restart and migration/reopen |

Adapters translate product exceptions to `IntegrityViolation`, `WriteConflict`
and `LostResponse` at this test seam. The focused stateful in-memory fixture
injects defects into store behaviour rather than evidence records and proves
stable family-specific `FailureCode` classification. Store adapters remain in
their persistence PR test trees; this harness changes no production authority
behaviour, migrations, tables or public runtime APIs.
