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

`newsroom.production_admission.mint_production_operational_admission()` is the
public minting seam. It independently reconstructs the readiness report,
authenticates the owner instruction, checks the instruction-named production
key and emits one deterministic record. Replaying the same instruction and
evidence produces the same bytes and digest. Changing any identity requires new
evaluation evidence, a new manifest, a new readiness report and a new owner
instruction.

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

Gate evidence is a canonical HMAC-SHA-256 attestation from an injected
`EVIDENCE_AUTHORITY` key. The attestation binds the exact evidence manifest,
gate artefact, main SHA/tree and seven-class identity-set digest. The retained
manifest also binds the qualifying shadow closeout, qualifying live canary
closeout, backup, restore and rollback artefacts. Canary, restore and rollback
must name the same identity set, deployment bytes and store identity.

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
injected `HUMAN_ACCOUNTABLE_OWNER` key. It binds:

- one dedicated owner issue other than #599 or #760;
- the exact SHA, tree, operational manifest and identity set;
- the exact readiness report and evidence manifest;
- the qualifying shadow and canary closeouts;
- the owner identity and issue time; and
- one named `PRODUCTION_OPERATIONAL_ADMISSION` signing key.

The production record is then sealed with that named key. Key bytes enter only
through injected process memory and never enter canonical evidence. Fixture,
synthetic and Increment 9Q signing-key identities are rejected by the minter.
The operational wrapper expects base64 key bytes in environment variables so a
credential broker or Keychain launcher can inject them transiently without
putting them on the command line.

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
  --evidence-key-env 'keychain:newsroom-evidence-v1=EVIDENCE_KEY_B64' \
  --output /ABSOLUTE_EVIDENCE_DIR/production-readiness.json
```

Mint only after the dedicated owner instruction exists:

```bash
uv run python -m scripts.production_operational_admission mint \
  --repo-root . \
  --evidence-manifest /ABSOLUTE_EVIDENCE_DIR/manifest.json \
  --attestation-directory /ABSOLUTE_EVIDENCE_DIR/gates \
  --evidence-key-env 'keychain:newsroom-evidence-v1=EVIDENCE_KEY_B64' \
  --readiness-report /ABSOLUTE_EVIDENCE_DIR/production-readiness.json \
  --owner-instruction /ABSOLUTE_EVIDENCE_DIR/owner-instruction.json \
  --owner-key-env 'keychain:human-accountable-owner-v1=OWNER_KEY_B64' \
  --production-key-env 'keychain:production-operational-admission-v1=PRODUCTION_KEY_B64' \
  --output /ABSOLUTE_EVIDENCE_DIR/production-operational-admission.json
```

`verify` takes the same evidence, report, instruction and key arguments, plus
`--admission`. It re-runs exact-main cleanliness and readiness inspection before
checking both the owner seal and production seal.

## Permanent evidence and rollback

Changes to the domain module, wrapper or focused tests route as
`R4_RELEASE_OPERATIONAL`. The accepted SDLC contract therefore requires owner
authority, the complete deterministic core and the actual-service lane. Those
checks are implementation evidence only; `SDLC_CORE_SERVICE_CURRENT` still
needs an exact freeze-bound gate attestation before admission.

Admission records are immutable. Do not edit a report, instruction or record,
rewrite a store, relax a blocker or re-sign drifted bytes. Stop, retain the
blocker, reconcile ambiguous effects, restore only the exact verified target,
re-evaluate every drifted component and issue a new dedicated owner instruction.
