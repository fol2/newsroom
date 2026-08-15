---
status: accepted
date: 2026-08-15
accepted_by_owner: 2026-08-15
---

# Hermes autonomy envelope and conditional activation

## Decision

Hermes on `macm4` is the Newsroom's local orchestration, admission and delivery
hub. The owner grants it a non-expiring Autonomy Envelope with no Epoch-count
limit and Conditional Activation Authority for the approved Increment 9 and
Increment 10 route.

The authority is prospective and conditional. Merging its planning record does
not execute an unimplemented capability or manufacture a live effect. It lets
Hermes proceed without a later human reply once every named implementation,
identity, rights, evidence, budget, ledger and emergency-stop prerequisite is
true.

## One Hermes authority, two internal trust roles

The **Hermes Control Plane** contains:

1. an AI controller that plans, coordinates and makes the final autonomous
   admission decision; and
2. an inseparable deterministic policy-and-effect boundary with an unavoidable
   veto.

Only the deterministic boundary possesses canonical SQLite, Neo4j projection
and target-adapter credentials. Codex, Claude, Grok and Gemini subprocesses
never receive those credentials. They return schema-valid commands to Hermes.
Hermes validates policy, expected versions, idempotency, ledger continuity,
rights and budget before committing a command.

This naming does not weaken the existing non-agent service-identity boundary:
the credential-bearing deterministic process is the direct writer, even though
it is deployed and operated as part of Hermes.

## Publication consequence

A **Hermes Publication Admission** is a terminal `AUTO_PUBLISH` decision for one
exact Publication Bundle. Its authoritative transaction creates the separate
Publication Decision, audit event and immutable Target Operations. The
credential-bearing deterministic target adapter dispatches those operations
immediately without a second approval.

This does not make ordinary Claim Admission or Relation Admission a publication
event. A model never sends directly to a public target.

The first approved target is the integrated Newsroom app-serving system and its
iPhone, iPad and Android reader surfaces. Discord and OpenClaw are not target
dependencies.

## Autonomous delivery and activation

After this planning atom closes, Hermes may:

- deliver each 9A–9G atom through its own issue, branch and pull request;
- arrange independent model review, repair findings and merge after the
  required checks pass;
- notify the Human Accountable Owner without waiting for a reply;
- create and execute a distinct Increment 10 canary manifest and verified
  rollback point after the Increment 9 signed closeout succeeds; and
- promote a successful canary to production automatically.

The dependency graph, exact evidence gates and single-writer rule remain
mandatory. Automation does not turn an unimplemented or failed gate into a
pass.

## Updates and reproducibility

Hermes, adapters, prompts, models and SDKs may follow their latest route. Every
dispatch records the observed Effective Manifest. Versions may change within an
Epoch, but closeout applies only to the final Effective Manifest Cohort, which
must independently meet full exposure.

Hermes updates through a staging checkout. Adapter, ledger, redaction and
admission replays must pass before atomic promotion. Failure restores the last
healthy build and records the attempt.

## Credentials and host access

Agents may inspect the complete `macm4` host, repository, filesystem and
network. Hermes uses a local credential broker backed by macOS Keychain or an
equivalent local secret store. Secrets are injected minimally and transiently;
the ledger stores only their class, scope and digest.

The broader host capability is an explicit owner choice. It increases the
importance of complete pre-I/O intent, output redaction and post-effect audit;
it is not evidence that a model owns a database or publication credential.

## Stop, recovery and human authority

The Autonomous Control Ledger is append-only, hash-chained and checkpoint-
signed. A ledger gap prevents further external action.

P0 events retain the approved deadlines: kill within 60 seconds, revoke affected
credentials within five minutes, notify the human within five minutes and
contain within 15 minutes. Recovery cannot erase the original failure. A failed
Epoch remains failed, and resumed evidence is non-decision-bearing unless a new
final manifest independently qualifies.

Any authenticated Human Accountable Owner may issue a signed global or scoped
emergency stop. Hermes executes it immediately. Hermes may recover and resume
after deterministic proof unless the stop explicitly states
`HUMAN_RELEASE_REQUIRED`.

## Budget consequence

The £250 Epoch cap applies to incremental paid APIs. Existing Codex and Grok
subscription fees do not count towards it and their CLI use has no request or
reviewer-minute quota, although every invocation and all observable usage are
ledgered. Ordinary CLI resource exhaustion relies on the operating system.
P0 controls, ledger fail-closed behaviour, credential revocation and the API
cash cap remain mandatory.

## Rejected alternatives

### Human approval before every merge or activation

Rejected because it conflicts with the accepted full-autonomy destination.

### Model subprocesses hold authority credentials

Rejected because autonomous decision authority does not require exposing the
authority store or target secret to a generative process.

### Pool all versions into one qualification score

Rejected because a passing old model or harness must not qualify a changed final
manifest.

### Immediate live effect from planning bytes

Rejected because authority can be granted conditionally, while pretending that
missing implementation already exists would destroy the audit model.

## Evidence

- [Wayfinder decision: Bind Increment 9 owner decisions and the Hermes autonomy envelope](https://github.com/fol2/newsroom/issues/503)
- [Wayfinder map: Increment 9 owner decisions and Hermes autonomy](https://github.com/fol2/newsroom/issues/502)
