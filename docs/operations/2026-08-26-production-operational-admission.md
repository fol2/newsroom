# Production Operational Admission

**Role:** #760 production-readiness inspection and admission mechanism

**Status:** implemented mechanism; no production admission minted

**Owner:** issue #760 under #151 and #557

**Canonical language:** UK English

**Date:** 2026-08-26

## Authority boundary

This mechanism implements the production-scope decision shape fixed by #586 and
#599. It does not issue the dedicated Human Accountable Owner instruction that
#599 requires. Issue #599 is the decision-shape record and issue #760 is the
implementation issue; neither is accepted as the dedicated production-admission
instruction.

A passing readiness report authorises no effect. A minted
`PRODUCTION_OPERATIONAL_ADMITTED` record completes one evidence prerequisite
for a later, separate Increment 11R decision. It is not Increment 11R authority,
activation authority, publication authority, public-dispatch authority or
production-mutation authority.

`FIXTURE_OPERATIONAL_ADMITTED` is retained only as an evidence digest. It is
never inherited into the seven production identity classes.

## Deterministic seams

`newsroom.production_admission.inspect_readiness()` is the public inspection
seam. It consumes retained canonical evidence and injected verification keys.
It performs no network request, provider call, publication effect or production
mutation. It always reports the complete gate inventory as `PASS` or with named
blockers. An absent manifest therefore produces a useful, content-addressed
blocked report rather than an exception or an empty result.
Malformed manifest, attestation or trust configuration input also retains the
same complete gate inventory with one precise fail-closed blocker on every
gate; it does not collapse into an unstructured command error.

The command wrapper resolves Git through `/usr/bin/git`, clears redirecting Git
environment, and accepts only a clean checkout whose `HEAD`, local `main` and
retained `origin/main` all identify the same commit and tree. A local branch
without `origin/main` authority is not exact main.

`newsroom.production_admission.mint_production_operational_admission()` is the
public minting seam. It independently reconstructs the readiness report,
authenticates the owner instruction, checks the instruction-named production
key and emits one deterministic record. Replaying the same instruction and
evidence produces the same bytes and digest. Changing any identity requires new
evaluation evidence, a new manifest, a new readiness report and a new owner
instruction.

## Change decomposition

This R4 change exceeds the advisory executable-line review trigger, so the
domain is deliberately split by responsibility rather than retained as one
admission module:

- `_shared.py` owns canonical primitives and trust-root key identities;
- `identities.py` owns the seven exact identity classes and bound artefacts;
- `gate_evidence.py` owns typed gate-fact reconstruction;
- `evidence.py` owns manifests and signed gate attestations;
- `readiness.py` owns provider-free blocker reporting;
- `owner.py` owns the live issue snapshot and owner instruction; and
- `admission.py` owns the final evidence binding, seal, mint and verifier.

The command wrapper is the only Git/GitHub adapter. Tests retain the production
contract and classifier routing separately from these domain responsibilities.

## Exact production identities

The production identity set contains exactly the seven classes fixed by #586:

1. relational schema, including exact version, migration history and schema
   fingerprint evidence;
2. the exact production Operational Profile;
3. the exact mandatory GraphRAG deployment;
4. the exact production retrieval contract;
5. the qualifying live Evidence Intake canary identity;
6. the exact publication adapters; and
7. the Handoff anchor, including `max_attempts`, and non-effect identities.

Every identity records its digest, its evaluation-evidence digest, the exact
main SHA and tree on which it was evaluated, the operational-manifest digest
and an explicit production-scope flag. Missing, fixture-scoped or drifted
identity evidence blocks only with a visible gate result; it cannot be rebound
as current.

## Readiness gates

The canonical report always contains these gates in fixed order:

- `RELATIONAL_SCHEMA_CURRENT`;
- `OPERATIONAL_PROFILE_CURRENT`;
- `GRAPHRAG_DEPLOYMENT_CURRENT`;
- `RETRIEVAL_CONTRACT_CURRENT`;
- `LIVE_EVIDENCE_INTAKE_CURRENT`;
- `PUBLICATION_ADAPTERS_CURRENT`;
- `HANDOFF_NON_EFFECT_IDENTITIES_CURRENT`;
- `EFFECTIVE_REVISION_COVERAGE_CURRENT`;
- `SPEND_ACCOUNTING_RECONCILED`;
- `RIGHTS_TERMS_CREDENTIALS_EGRESS_CURRENT`;
- `HERMES_RUNTIME_CONTROLS_CURRENT`;
- `STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT`;
- `PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED`;
- `CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND`;
- `SDLC_CORE_SERVICE_CURRENT`; and
- `READINESS_INSPECTION_NON_EFFECT`.

Each gate first retains a typed canonical evidence record. Its gate-specific
facts are parsed and recomputed — including coverage arithmetic, spend
reconciliation, source/CI authority, publication-spec inventory, runtime
controls and recovery bindings — so an arbitrary digest cannot be signed as a
passing fact. A canonical HMAC-SHA-256 `EVIDENCE_AUTHORITY` attestation then
binds that record, the exact evidence manifest, main SHA/tree and seven-class
identity-set digest. The retained manifest also binds the qualifying shadow
closeout, qualifying live canary closeout, backup, restore and rollback
artefacts. Canary, restore and rollback must name the same identity set,
deployment bytes and store identity.

The manifest and final admission record carry the individual content digests
for the exact eight publication-facing specifications fixed by #560 and #589.
Their canonical set digest is the artefact for
`PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED`; a missing path or any digest
drift blocks that gate rather than accepting an aggregate substitute.

The accepted shadow outcome is `SCOPED_OPERATIONAL_ELIGIBILITY`; the accepted
live-canary outcome is `ELIGIBLE_FOR_ACTIVATION_PLANNING`. Backup, restore and
rollback each require `PASS`. Any other outcome remains a blocker.

## Owner instruction and seal

The owner instruction is canonical, one-admission-only and authenticated by an
injected `HUMAN_ACCOUNTABLE_OWNER` key. Before minting, the wrapper independently
reads the dedicated issue from the GitHub API and requires an open issue in
`fol2/newsroom` whose author association is `OWNER`. Its immutable node
identity, update time, author identity, URL and title/body digests must exactly
match the sealed retained issue snapshot. A caller-provided issue number or
locally invented issue digest is therefore insufficient. The instruction
binds:

- one dedicated owner issue other than #599 or #760;
- the exact SHA, tree, operational manifest and identity set;
- the exact readiness report and evidence manifest;
- the qualifying shadow and canary closeouts;
- the owner identity and issue time; and
- one named `PRODUCTION_OPERATIONAL_ADMISSION` signing key.

The issue body must contain the canonical
`newsroom.owner-production-admission-binding.v1` marker rendered by
`owner_issue_binding_marker()`. That marker names every binding above,
`maximum_admissions=1`, and explicit false values for Increment 11R and
production activation. Free-form approval prose without this exact marker is
not an instruction.

The production record is then sealed with that named key. Production trust-root
key identifiers are fixed by key class in code; command-line input names only
the environment variable containing a secret and cannot self-assert a key
identifier or provenance. Key bytes enter only through injected process memory
and never enter canonical evidence. Fixture, synthetic and Increment 9Q
signing-key identities are rejected by the minter. The operational wrapper
expects base64 key bytes in environment variables so a credential broker or
Keychain launcher can inject them transiently without putting them on the
command line.

## Provider-free command path

First create an exact-main blocker report. This is the correct command when no
complete production evidence manifest exists:

```bash
uv run python -m scripts.production_operational_admission inspect \
  --repo-root . \
  --output /ABSOLUTE_EVIDENCE_DIR/production-readiness.json
```

The command exits `2` after retaining the complete blocked report. It exits `0`
only when every gate passes. For a complete retained evidence set:

```bash
uv run python -m scripts.production_operational_admission inspect \
  --repo-root . \
  --evidence-manifest /ABSOLUTE_EVIDENCE_DIR/manifest.json \
  --attestation-directory /ABSOLUTE_EVIDENCE_DIR/gates \
  --evidence-key-env EVIDENCE_KEY_B64 \
  --output /ABSOLUTE_EVIDENCE_DIR/production-readiness.json
```

Mint only after the dedicated owner instruction exists:

```bash
uv run python -m scripts.production_operational_admission mint \
  --repo-root . \
  --evidence-manifest /ABSOLUTE_EVIDENCE_DIR/manifest.json \
  --attestation-directory /ABSOLUTE_EVIDENCE_DIR/gates \
  --evidence-key-env EVIDENCE_KEY_B64 \
  --readiness-report /ABSOLUTE_EVIDENCE_DIR/production-readiness.json \
  --owner-instruction /ABSOLUTE_EVIDENCE_DIR/owner-instruction.json \
  --owner-key-env OWNER_KEY_B64 \
  --production-key-env PRODUCTION_KEY_B64 \
  --output /ABSOLUTE_EVIDENCE_DIR/production-operational-admission.json
```

`mint` performs the live read-only GitHub issue-currentness check. `verify`
takes the same evidence, report, instruction and key arguments, plus
`--admission`; it remains reproducible from the retained signed issue snapshot.
It re-runs exact-main cleanliness and readiness inspection before checking both
the owner seal and production seal.

## Permanent evidence and rollback

Changes to the focused `newsroom.production_admission` package, wrapper or tests route as
`R4_RELEASE_OPERATIONAL`. The accepted SDLC contract therefore requires owner
authority, the complete deterministic core and the actual-service lane. Those
checks are implementation evidence only; `SDLC_CORE_SERVICE_CURRENT` still
needs an exact freeze-bound gate attestation before admission.

Admission records are immutable. Do not edit a report, instruction or record,
rewrite a store, relax a blocker or re-sign drifted bytes. Stop, retain the
blocker, reconcile ambiguous effects, restore only the exact verified target,
re-evaluate every drifted component and issue a new dedicated owner instruction.
