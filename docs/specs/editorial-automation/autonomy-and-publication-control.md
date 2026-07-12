# Autonomy and publication control specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-11  
**Canonical language:** English  
**Related plan:** None  
**Related reference:** [`product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 2, 13 and 14  
**Supersedes:** None

## Purpose

Define the target autonomy boundary: which parts of news production may run without per-story human approval, which decisions must be held or rejected, and which component is allowed to perform a public action.

## Scope

This specification covers candidate decision states, publication authority, separation of agent duties, fail-closed behaviour, exception review, human override and emergency control.

Evidence detail, content rules, rights, sensitive-topic tests and lifecycle behaviour are defined in the other suite modules and feed into the decision described here.

## Requirements

### Target autonomy

**AUTO-001 — End-to-end autonomous path.** The system MUST support an end-to-end path in which an eligible candidate is discovered, evidenced, drafted, validated and published without routine per-story human approval.

**AUTO-002 — Policy-bounded operation.** Autonomous behaviour MUST be constrained by an identifiable accepted specification set and a versioned production policy derived from it.

**AUTO-003 — No model-created exceptions.** A model or agent MUST NOT create, widen or infer an exception to an evidence, rights, risk, validation or publication rule.

**AUTO-004 — No quota override.** Publication volume, freshness targets, engagement objectives, queue size, cost or timeout pressure MUST NOT lower or bypass a gate.

### Semantic decision outcomes

**AUTO-010 — Explicit outcomes.** Before any public action, every candidate MUST have exactly one current semantic outcome:

- `AUTO_PUBLISH` — every applicable gate passed and no hold condition applies;
- `HOLD_FOR_REVIEW` — the candidate may be publishable but requires a defined authorised decision; or
- `REJECT` — the candidate is not publishable under the current evidence, policy or rights position.

Equivalent internal names MAY be used if their semantics and transitions remain unambiguous.

**AUTO-011 — Outcome reason.** `HOLD_FOR_REVIEW` and `REJECT` MUST carry at least one stable, machine-readable reason code and a human-readable explanation.

**AUTO-012 — Terminal public decision.** Only `AUTO_PUBLISH` or an authorised reviewer approval of a held candidate MAY create a publishable package.

**AUTO-013 — No passive approval.** Absence of an error, expiry of a timeout, empty reviewer queue, missing response or service recovery MUST NOT be interpreted as approval.

**AUTO-014 — Re-entry.** A rejected or held candidate MAY re-enter validation only when new evidence, an authorised policy change or a recorded reviewer action addresses the stated reason. Re-entry MUST preserve the earlier decision history.

### Publication controller

**AUTO-020 — Separate authority.** Public publication credentials MUST be available only to a dedicated publication controller or equivalent deterministic boundary component.

**AUTO-021 — No direct generative publication.** A generative planner, researcher, extractor, writer, critic, translator, image generator or repair agent MUST NOT possess or invoke a public publishing credential directly.

**AUTO-022 — Validated package only.** The publication controller MUST accept only a versioned, immutable publication package that includes:

- candidate and story identifiers;
- content and asset hashes;
- evidence-package reference;
- applicable policy version;
- required validator results;
- decision outcome and reason data;
- publication targets; and
- decision actor or automated controller identity.

**AUTO-023 — Package integrity.** Any change to content, headline, metadata, source links, asset, target or notification after validation MUST invalidate the previous publish authorisation and trigger the applicable validation again.

**AUTO-024 — Idempotency.** Publication MUST be idempotent by story, version and target so a retry cannot silently create duplicate public items.

**AUTO-025 — Target allowlist.** The controller MUST publish only to owner-approved targets using owner-approved message or article types.

### Agent and tool boundaries

**AUTO-030 — Least privilege.** Every agent or service MUST receive only the tools and data required for its defined role.

**AUTO-031 — Source content is data.** Retrieved pages, feeds, documents, metadata, messages and reader leads MUST be treated as untrusted data. Instructions embedded in them MUST NOT modify policy, system prompts, tool permissions, validation or publication decisions.

**AUTO-032 — Evidence-package boundary.** A writing agent MUST operate from the approved evidence package. It MUST NOT add a source, quote, fact or asset outside that package to the publication draft.

**AUTO-033 — Immutable governance.** Runtime agents MUST NOT edit accepted specifications, production policy, source permissions, validator code, risk thresholds, release configuration or their own role definition.

**AUTO-034 — Repair limits.** Automated repair MAY correct schema, formatting or other explicitly permitted defects. It MUST NOT repair a failed evidence or risk decision by inventing support, deleting an inconvenient qualifier or changing the governing policy.

**AUTO-035 — Cross-agent provenance.** Every agent transition MUST preserve the candidate identifier, evidence-package identifier and run identifier.

### Fail-closed behaviour

**AUTO-040 — Required dependency failure.** Publication MUST be blocked when any required policy, validator, rights record, evidence record, audit writer, credential boundary or integrity check is unavailable or returns an indeterminate result.

**AUTO-041 — Partial outage.** The system MAY continue non-public work during a partial outage, but MUST NOT emit a public story, notification, correction or withdrawal unless all dependencies required for that action are healthy.

**AUTO-042 — Degraded source state.** Failure to retrieve or parse a central source MUST invalidate any claim that depends on it. Previously cached evidence MAY be used only when its provenance, permitted retention, version and freshness satisfy the applicable specification.

**AUTO-043 — Unknown policy input.** An unrecognised jurisdiction, source class, category, asset type, decision reason or content risk MUST result in `HOLD_FOR_REVIEW` or `REJECT`, never automatic publication.

### Human exception review

**AUTO-050 — Defined reviewer authority.** Reviewer roles and the decisions each role may make MUST be configured and auditable. A reviewer MUST NOT receive broader authority merely because a queue item is urgent.

**AUTO-051 — Review actions.** An authorised reviewer MAY approve, reject, redact or request regeneration of a held candidate only within the authority granted to that role.

**AUTO-052 — Review record.** A human action MUST record reviewer identity, timestamp, reason, changed fields, supporting note or source where applicable, and the resulting decision.

**AUTO-053 — Revalidation after change.** Any human or automated change to a held draft MUST pass the applicable evidence, content, rights, risk and package-integrity checks before publication.

**AUTO-054 — No reviewer available.** A held candidate MUST remain unpublished or expire under a documented retention policy when no authorised reviewer is available. It MUST NOT age into `AUTO_PUBLISH`.

**AUTO-055 — Policy override visibility.** If a reviewer uses an explicitly permitted override, the audit record MUST identify the overridden requirement and the authority permitting that override. A generic “approved” note is insufficient.

### Emergency control

**AUTO-060 — Global pause.** The operator MUST have a control that immediately prevents new autonomous publications and notifications across all targets.

**AUTO-061 — Scoped pause.** The system SHOULD support pausing by publication target, source adapter, content category, jurisdiction, model or policy version.

**AUTO-062 — Preserve evidence.** Pausing MUST NOT delete candidates, source evidence, generated drafts, decision records or publication history.

**AUTO-063 — Resume action.** Resuming a paused scope MUST require an explicit, authenticated and logged action. Queued packages MUST be rechecked against current policy before release.

**AUTO-064 — Credential revocation.** The operator MUST be able to revoke or rotate publication credentials independently of model or agent deployment.

## Acceptance criteria

1. A low-risk official service-change candidate with complete evidence and rights records reaches `AUTO_PUBLISH` and is published without a human review action.
2. A candidate containing an unresolved serious allegation reaches `HOLD_FOR_REVIEW` with a stable reason code and creates no public item.
3. A lead-only rumour reaches `REJECT` and cannot be released by timeout or queue expiry.
4. A writing agent attempting to invoke the public publisher is denied by tool permissions.
5. A content change after validation invalidates the old package and the controller refuses it.
6. An unavailable required validator blocks publication and creates an observable failure record.
7. A reviewer amendment is revalidated and the audit identifies both the original and amended packages.
8. Activating the global pause prevents new stories and notifications while retaining the evidence and audit trail.
9. Resuming after a policy update re-evaluates queued packages rather than publishing them under stale approval.
10. Retrying the same valid package does not duplicate the public story.

## Non-goals

This specification does not select an agent framework, workflow engine, queue, database, credential store or deployment topology.

It does not require a human to review every story and does not authorise full autonomy outside the accepted policy boundary.

## Open questions

- Which reviewer roles are required at launch, and which hold reasons can each resolve?
- Which scopes must the emergency control support beyond a global pause?
- How long may held and rejected candidates remain before expiry or deletion?
- Should any formal procedural facts receive narrowly defined automatic-publication exceptions after legal review?
