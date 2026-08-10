# Authority-store conformance harness

`newsroom/tests/authority_store_conformance.py` is a repository-owned,
test-only kernel for the remaining Increment 6 persistence atoms. It imports no
production code and knows no product schema. A persistence PR supplies a small
adapter which creates a persisted location and opens primitive handles over it:

```python
class MyStoreAdapter:
    name = "my-store"
    applicability = {case: Applicability.required() for case in CASE_INVENTORY}

    def create_location(self): ...
    def open_handle(self, location, *, migrate=False): ...


class MyStoreHandle:
    def submit(self, command, *, lose_response=False): ...
    def observe(self, record_id): ...       # raw full persisted state
    def history(self): ...                  # raw append-only history
    def read(self, record_id): ...          # integrity-validating read
    def list_history(self): ...              # integrity-validating list
    def set_upstream_head(self, authority, value): ...
    def current_use(self, record_id): ...
    def tamper(self, record_id, kind): ...
    def begin(self): ...
    def close(self): ...


class MyTransaction:
    def submit(self, command): ...
    def observe(self, record_id): ...
    def history(self): ...
    def rollback(self): ...


report = assert_conformant(MyStoreAdapter())
```

The adapter does not implement replay, reopen, competing-writer or rollback
scenarios and does not provide expected values or success booleans. The kernel
owns those sequences and their fixed commands. Adapters translate product
exceptions to `IntegrityViolation`, `BindingConflict` and `LostResponse` at
the test seam.

## Kernel-owned scenarios

The kernel performs these observations in fixed inventory order:

| Case | Normative sequence and assertion |
| --- | --- |
| `fresh_replay` | submit the identical command twice through the same primitive; full state and append-only history must be byte-for-byte unchanged by replay |
| `fresh_reopen` | validate a fresh read, close the handle, open a distinct handle on the same location, then require the same validated value, state and history |
| `representation_binding` | observe exact canonical bytes, scalar/identity columns and linked rows; independently mutate each form and require both fresh and newly reopened handles to reject it |
| `request_binding` | independently change actor, request, idempotency and CAS predecessor; each resubmission must conflict without changing state or history |
| `lost_response_replay` | lose the response after retention, change use-time heads, resubmit the identical command without a new history entry, then prove retained corruption is rejected |
| `historical_read` | create two versions, independently mutate the first version's identity, digest and provenance, then require both point read and full history list to reject each mutation through fresh and newly reopened handles |
| `current_use_revalidation` | accept matching heads and independently reject every changed required head |
| `tamper_rejection` | reject direct canonical, linked-row and self-consistent offline rewrites through fresh and reopened reads |
| `competing_writers` | coordinate two independent handles with a kernel barrier and threads; require one winner, one binding conflict, one row and one history append |
| `transaction_rollback` | begin, submit, observe transaction-visible state/history, roll back, open a new handle, then require absence and unchanged history |
| `restart_migration` | close and create distinct restart and migration handles over the same location; require validated value, full state and history parity |

The focused persisted in-memory fake uses shared state, locks, independent
handles and copy-on-write transactions. Its sensitivity tests inject defects
into primitive submission, validation, handle creation, concurrency and
transaction behaviour, including a point-read-validating implementation whose
history list skips validation, then require the exact family-specific
`FailureCode`.

## Exhaustive applicability

`applicability` is exhaustive: every member of `CASE_INVENTORY` must be
present. Normally use `Applicability.required()`. A structurally inapplicable
family needs both a stable reason and reviewed waiver reference:

```python
applicability = {case: Applicability.required() for case in CASE_INVENTORY}
applicability[CaseId.RESTART_MIGRATION] = Applicability.waived(
    reason="store is ephemeral and has no reopen boundary",
    waiver_reference="issue:NNN#reviewed-waiver",
)
```

Protocol validation is total and deterministic. `supported` must have exact
type `bool`; reason and waiver reference must each be exactly `None` or `str`.
Malformed types, missing families, blank waiver metadata and unknown entries
produce inventory-ordered `ADAPTER_PROTOCOL` failures rather than exceptions.
Valid skips render with both `waiver=` and `reason=` so CI cannot hide omitted
coverage.

Store adapters remain in their persistence PR test trees. This harness changes
no production authority behaviour, migrations, tables or public runtime APIs.
