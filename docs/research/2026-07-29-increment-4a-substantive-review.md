# Increment 4A substantive review

**Issue:** #225
**Parent:** #144
**Pull request:** #232
**Authorised base:** `main@d03441ef2fa26b5dc83f65d1797abf2b381d8f1a`
**Reviewed scope:** immutable Extraction Run, retained output and generic proposal authority only

## Review method

The review traced the proposed source from the public authenticated facade through command authorisation, current source/object preflight, deterministic producer execution, independent structured-output validation, transactional SQLite commitment, typed reads, checked migration and startup integrity.

It also reviewed the negative boundary: no entity resolution, relation admission, Candidate, Evidence Intake, Graphiti/model runtime, proposal workspace, graph writer, publication or production activation may be reachable from 4A.

Focused evidence covers typed contracts, all outcomes, exact replay, idempotency conflicts, semantic collisions, identifier reuse, current source/rights/deletion changes, invalid output rollback, persist-before-admission ordering, raw-SQL tamper/reopen, authentication, scope separation, representation redaction, import guards, checked v12-to-v13 migration and exact traceability.

## P1 review

No unresolved P1 finding was identified in the reviewed local product tree.

## Corrected P2 findings

### P2-01 — broad authority-package export created an import cycle

An early attempt exported the extraction opener from `newsroom.authority.__init__`. Source policy imports projection types, and the broad projection package imports source-facing modules, so the new export made ordinary source imports cycle through the extraction system.

**Correction:** the public entry point remains the dedicated `newsroom.authority.extraction_system` submodule. A security test fixes the exact bounded facade and prevents accidental exposure of private store, producer or database surfaces.

### P2-02 — producer validation was not independent enough

The first kernel trusted the deterministic producer's `VALID` or `INVALID` marker and canonical value shape. A later private adapter could therefore have mislabeled malformed output or emitted proposals that differed from the retained structured value.

**Correction:** `newsroom.extraction.output_schema` owns a closed Draft 2020-12 schema and canonical digest. Authority validates output independently before committing any extraction authority. Malformed or proposal-inconsistent bytes claimed as valid are retained honestly as `INVALID_OUTPUT` with no Proposal Set; a falsely invalid exact result or incompatible deterministic contract is retained as a proposal-free blocking failure. Store-level identity, chronology and lineage violations still roll back the whole transaction.

### P2-03 — Proposal Set canonical identity omitted its producer contract

The Proposal Set table retained `producer_contract_digest`, but the first canonical Set value did not include it. A raw-SQL attacker who bypassed immutability triggers could change and rehash the producer lineage without changing the Set's canonical meaning.

**Correction:** the producer contract digest is part of the Proposal Set canonical value, typed reconstruction and proposal cross-record checks. A rehashed tamper now fails reopen.

### P2-04 — output and proposal chronology was incompletely rederived

The initial reader relied on SQL insertion order and foreign keys but did not require Output, Proposal Set and Proposal retained times to equal the authoritative Run Version recording time.

**Correction:** typed models and startup reconstruction require exact retained-time equality and exact Run/Run Version/Output/Set/producer lineage. Timestamp or contract drift fails reopen.

### P2-05 — evidence bounds could be rehashed beyond the retained passage

Insertion guards enforced evidence end offsets, but the first startup path reconstructed `EvidenceRange` without comparing the range to the retained Passage byte length. Trigger-bypassing SQL could enlarge and rehash the evidence record.

**Correction:** startup joins every evidence row to its exact retained Passage, checks byte bounds and rederives the evidence digest and ordinal sequence. A rehashed out-of-range record fails reopen.

### P2-06 — normalized input and stable-Run columns were not fully rederived

The original reader did not compare every retained Passage normalized column, stable budget bytes/digest and stable Run creation event/time against the first Run Version.

**Correction:** startup reconstructs the exact input binding and budget, compares every normalized source/object/hydration field and requires the stable Run creation lineage to match version 1. Rehashed normalized-column, budget or creation-lineage tampering fails reopen.

### P2-07 — replay and lifecycle evidence was too implicit

The original success test showed replay equality but did not prove that the producer could not be called again. It covered rights revocation, but not the accepted pending-deletion/tombstone distinction or later Source Definition Version change.

**Correction:** focused tests replace the producer with a fail-on-call method after first execution and prove exact replay succeeds without invocation. Separate lifecycle tests prove a pending deletion remains usable while active, tombstone blocks use, and a later current Source Definition Version blocks replay and all downstream reads.

### P2-08 — collision evidence did not cover every authority axis

The first suite covered equivalent Contract semantics but not same-key/different-request conflicts for both Contracts and Runs, equivalent stable Runs under new IDs, or Run Version identifier reuse.

**Correction:** focused tests prove exact idempotency conflict, semantic collision, identifier reuse, no duplicate rows and stable retained authority after every rejected attempt.

### P2-09 — requirement traceability could be read as later-unit completion

The initial matrix attached applicable GraphRAG and discovery requirements to 4A symbols without sufficiently distinguishing implemented 4A authority, inherited contracts, proposal-only seams and work deferred to 4B–4E.

**Correction:** every row now records an explicit status such as `IMPLEMENTED`, `INHERITED_EXACT_INPUT_CONTRACT`, `PROPOSAL_ONLY_DEFERRED_4C`, `DEFERRED_4B`, `INTERFACE_ONLY_DEFERRED_4D` or `ACTUAL_SERVICE_PROOF_DEFERRED_4E`. Tests verify that every identifier exists in an accepted specification and every implementation symbol/test path resolves.

### P2-10 — a dead commitment argument obscured canonical semantics

The proposal-record helper accepted `retained_at` even though retained time is deliberately not part of the Proposal Envelope's canonical bytes and is checked separately against the Run Version.

**Correction:** the unused argument was removed. Canonical semantic fields and cross-record chronology remain explicit and independently checked.

### P2-11 — deterministic outcome selection remained caller-controlled Run input

The initial fake lane stored `fixture_case` directly on `ExtractionRunRequest`. That made success, partial and failure behaviour look like a property a caller could vary while retaining the same extractor contract, rather than part of the approved producer/policy version.

**Correction:** every deterministic fixture scenario is now bound into a distinct immutable policy-contract version and semantic digest. The Run binds only the exact extractor contract, input and budget. The producer derives its closed scenario from the approved contract and rejects any unknown or incompatible contract, so changing fixture behaviour necessarily changes authority contract identity.

### P2-12 — producer failures could escape without an immutable attempt

The first boundary allowed an incompatible deterministic contract, malformed producer output or unexpected producer exception to escape before the Run Version was committed. That contradicted the requirement that failed attempts remain traceable and could also expose arbitrary exception text to callers.

**Correction:** deterministic contract and policy failures now commit a terminal `BLOCKING_FAILURE`; unexpected producer exceptions commit a proposal-free `RETRYABLE_FAILURE` with `PRODUCER_INTERNAL_ERROR`; and malformed or proposal-inconsistent structured output commits `INVALID_OUTPUT` with retained canonical bytes and no proposals. Exception text is discarded, elapsed time is derived from authority timestamps, exact replay returns the retained failure without invoking the producer, and startup revalidates every outcome/failure-code pairing.

### P2-13 — complete-suite prose counted skipped outcomes as passes

The first evidence summary copied the file-isolated JUnit `tests` total into the passing-case field. That total includes skipped outcomes, so the prose overstated the complete local result by the exact 34 authenticated-service skips even though it separately disclosed those skips.

**Correction:** the evidence record now distinguishes 1,593 passing cases from 34 intentional local actual-service skips, records 1,627 only as the total outcome/identity count, and continues to require the permanent authenticated-Neo4j workflow to execute its mandatory service inventory without required skip, failure or error.

### P2-14 — focused SQLite inspection helpers leaked connections

Several focused tests used `sqlite3.Connection` as a transaction context manager and implicitly assumed that leaving the context closed the connection. Python 3.13 correctly reported those connections as unclosed resources, adding noise to the evidence lane and making a real store leak harder to detect.

**Correction:** every Increment 4A direct-SQL inspection now wraps the connection with `contextlib.closing`, and the focused inventory passes with `ResourceWarning` promoted to an error. Product open/reopen failure paths remain covered separately.

### P2-15 — read authorization provenance guard lacked direct evidence

The extraction read boundary already compared the authorizer's returned authentication context and request digest with the exact server-derived request, but the first focused suite proved only allowed and missing-scope outcomes. A defective or compromised authorizer returning an allowed decision for another semantic request therefore lacked direct Increment 4A regression evidence.

**Correction:** a focused security test now returns a syntactically valid allowed decision with a forged authorization-request digest. The boundary rejects it before any store read, fixing the fail-closed provenance check as permanent evidence.

### P2-16 — complete core evidence exhausted the shared signed lane budget

The first exact clean-head SDLC run completed every deterministic test without failure or required skip, but the six-worker file-scoped pool consumed 53.013 seconds after source-integrity work had already used part of the immutable 55-second core-lane deadline. The signed decision correctly returned `BUDGET_EXCEEDED` rather than treating successful tests as timely evidence.

**Correction:** source-integrity and the complete deterministic suite now start concurrently against the same immutable lane deadline because they are independent reads over the exact checked-out tree and produce separate command/evidence records. The complete `newsroom/tests` execution remains one pinned six-worker pytest session with `--dist=loadfile`; controlled four-CPU measurements rejected worker-count inflation and alternative schedulers because they reduced or failed to create dependable headroom. No test is removed, selected away, reclassified, skipped or moved to a non-blocking lane, and the 55-second command and lane deadlines remain unchanged. The workflow contract has direct evidence that both gates receive the same deadline and rendezvous concurrently, waits for peer cleanup before propagating an infrastructure defect, and returns their evidence in canonical source-then-core order.

## Authority and runtime boundary review

The reviewed implementation has no import or callable surface for:

```text
Graphiti or a model-provider SDK
network access, source credentials or schedules
arbitrary Cypher or governed Neo4j writes
Canonical Entity allocation, merge, split or resolution decisions
relation admission, assertions, revocation or supersession decisions
Candidate or Evidence Intake writes
publication, spending, shadow, canary or production activation
legacy link/event/cluster identity import or dual write
```

The deterministic fixture producer is exact-type constrained, uses approved repository-owned English and Hong Kong Traditional Chinese bytes, returns zero token and monetary usage, and cannot interpret source text as policy or tool instructions.

## Local evidence at this review point

```text
Dedicated `test_extraction_4a_*` inventory:             62 passed
Authority A2a/A2b extraction bridge evidence:          2 passed
Predecessor discovery/projection migration regression: 11 passed
Current focused total:                                75 passed
Required focused skips:                                0
Focused failures/errors:                               0
Reviewed product/test tree:                            `c56886d3a8cbc5e7fa8830028ae2be891087589e`
Current complete repository inventory:              1,594 passed
Intentional local actual-service skips:                 34
Complete-inventory failures/errors:                      0
Clustering regression evaluation:                      pass
Clustering evaluation rows:                             240
Clustering baseline regressions:                          0
Raw-SQL tamper/reopen cases:                           pass
Fresh and v12-to-v13 checked migration:                pass
Compile and diff checks:                               pass
```

The current 75-case count is the exact local focused inventory at this review point: all dedicated Increment 4A tests, the two permanent Authority-lane bridge tests, and both inherited migration regression files. The PR completion record must still use final JUnit and workflow artifacts rather than treating this prose count as self-updating.

The complete repository inventory for the reviewed product/test tree executed all 194 repository test files and produced 1,594 passing cases plus 34 intentional local actual-service skips (1,628 total outcomes), zero failures and zero errors. The independent file-isolated run produced the same 1,628 unique test identities with zero failed files and zero JUnit parse errors. The 240-row clustering dataset matched its pinned digest and baseline with no regression. The evidence-record update that contains these results is documentation-only; final merge qualification still belongs to the exact pushed PR head and its workflow artifacts. Local service skips are never accepted as final service qualification: the permanent authenticated-Neo4j workflow must execute its required inventory without required skip/failure/error on that exact reviewed PR head.

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  16
Unresolved P1/P2:        0 on the reviewed local product tree
Review threads:          0 at the time of local review
```

This is not final merge evidence. Before PR #232 may merge, the same clean source tree must be durably present on the PR branch, receive normal pull-request-triggered exact-head qualification, pass every applicable permanent workflow, complete the repository test inventory without required skip/failure/error, and retain zero actionable comments, submitted-review blockers and unresolved review threads.

Issue #226 remains blocked. Neither this review nor successful deterministic fixture extraction authorises Increment 4B, real Graphiti/model execution or any production effect.
