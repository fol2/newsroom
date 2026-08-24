# Newsroom domain language

**Status:** Proposed vocabulary; Increment 9 autonomy terms accepted 2026-08-15; Active Coverage accepted 2026-08-17; Evaluation Threshold Schedule accepted 2026-08-17; Retention Schedule accepted 2026-08-17; Rights Record and Asset Record accepted 2026-08-17

This glossary proposes the canonical meanings of editorial records that connect evidence, decisions, publication and derived newsroom intelligence. The product owner has not accepted this vocabulary yet.

The product owner has accepted the Increment 9 terms in the final section. That
acceptance does not implicitly accept every earlier proposed term.

## Discovery

**Source Registry**:
An owner-approved, versioned coverage map of the sources the Newsroom intends to monitor. It defines discovery coverage and does not itself provide publication evidence.
_Avoid_: Feed list, search query list

**Source Definition**:
One approved source endpoint or channel and the editorial purpose for monitoring it. Implementation metadata is defined only when the source is activated.
_Avoid_: Website, generic source

**Planned Agenda Item**:
A known expected release, proceeding, effective date or deadline with an explicit monitoring window. It records an expectation, not evidence that the development occurred.
_Avoid_: Scheduled story, confirmed event

**Discovery Signal**:
A minimal record that a registered adapter observed a new item, material revision or bounded search result. It is not a Source Observation, News Lead, verified fact or evidence.
_Avoid_: Raw Observation, Source Observation, discovered fact

**News Lead**:
A Discovery Signal that passed the applicable deterministic integrity, newness, duplication and unambiguous scope gates. It is eligible for editorial triage, not evidence acquisition by default or publication.
_Avoid_: Source Observation, Story Candidate, verified lead

**Story Candidate**:
One or more News Leads judged sufficiently relevant, useful, material and novel to begin evidence acquisition. It carries no publication authority.
_Avoid_: Approved story, selected article

**Coverage Gap**:
A relevant in-scope development that the selected direct-watch sources did not detect and that another permitted channel found. It is evidence for reviewing source selection, not a service-level breach.
_Avoid_: Search hit, missed publication

## Evidence and relationships

**Source Observation**:
A retained record that a source presented particular content at a particular time. It proves what was observed, not that the source's claim is true.
_Avoid_: Source truth, verified fact

**Entity Mention**:
An immutable occurrence of a possible person, organisation, place, event or other entity in one exact source passage or extraction output. It is not itself a canonical entity.
_Avoid_: Entity, resolved node

**Entity Resolution Proposal**:
An immutable proposal to bind one or more entity mentions to an existing canonical entity or to create a new canonical entity, with provenance and the proposed matching basis.
_Avoid_: Model-created entity, automatic merge

**Entity Resolution Decision**:
An immutable governance decision that accepts or rejects one exact entity-resolution proposal. An accepting decision binds the mentions to an existing canonical entity or atomically creates and binds a new one.
_Avoid_: Confidence threshold, mutable entity status

**Canonical Entity**:
A stable governed identity established by an entity-resolution decision. Later aliases, merges, splits or corrections require new governed decisions rather than silent identity mutation.
_Avoid_: Graph node ID, extracted name

**Claim Assertion**:
An immutable normalised statement attributed to an exact source observation, with applicable subject, predicate, value, provenance and temporal semantics. It records what is asserted, not that the assertion is true.
_Avoid_: Fact, model truth

**Claim Proposal**:
An immutable candidate claim assertion submitted for an admission decision. It is ineligible as approved publication evidence until admitted and independently governed by the applicable evidence rules.
_Avoid_: Probable fact, extracted evidence

**Claim Admission Decision**:
An immutable governance decision that admits or rejects one exact claim-proposal identity for a stated use and trust scope.
_Avoid_: Confidence threshold, verified flag

**Governed Claim**:
A deterministic read model derived from one immutable claim proposal and its effective admission decision. Its stable view identity is derived from those authoritative identities and is not an independently mutable record. Admission does not by itself make the claim objectively true or sufficient publication evidence.
_Avoid_: Approved fact, model-approved claim

**Relation Assertion**:
A first-class immutable statement that one subject reference bears a named relationship to one object reference, together with its provenance and applicable time semantics. Proposal-time references may be Entity Mention or Canonical Entity identities; depended-on mentions must resolve before admission.
_Avoid_: Smart edge, graph fact

**Relation Proposal**:
A retained, immutable candidate relation assertion submitted for an admission decision. It is ineligible as approved publication evidence.
_Avoid_: Probable fact, low-confidence relation

**Relation Admission Decision**:
An immutable governance decision that admits or rejects one exact relation-proposal identity for a stated use and trust scope.
_Avoid_: Status update, confidence threshold

**Governed Relation**:
A deterministic read model derived from one immutable relation proposal, the effective resolution decisions for its endpoints and its effective admission decision. It exposes Canonical Entity identities for both endpoints. Its stable view identity is derived from those authoritative identities and is not an independently mutable record. Admission does not by itself make the relation publication evidence.
_Avoid_: Approved relation, high-confidence relation, model-approved relation

Entity mentions MUST be resolved by an effective entity-resolution decision before a claim or relation that depends on those identities may be admitted. Re-extraction creates new proposals; it never mutates or replaces the historical proposal and decision record.

## Publication

**Evidence Package**:
An immutable set of governed source passages, claim mappings, permissions and provenance approved as input to a particular editorial decision.
_Avoid_: Search result, context dump

**Asset Record**:
The governed record for one public visual, including provenance, licence, platform and territory limits, credit, subject-risk checks and, where generated, input provenance. Incomplete rights or subject-risk status blocks automatic publication.
_Avoid_: Image metadata, model-declared safe asset

**Story Version**:
An immutable public content state for one stable story identity.
_Avoid_: Latest article, mutable story

**Surface Payload**:
The exact, immutable and validated content candidate for one controlled reader-facing surface.
_Avoid_: Rendered later, generic article

**Publication Bundle**:
An immutable collection of exact surface payloads and their evidence, policy and validation references for one story version. Its hashed content does not contain a publication decision.
_Avoid_: Generic article, delivery job

**Publication Decision**:
A separate governed record that authorises one exact authoritative publication-bundle digest, or refuses one exact staged candidate-manifest digest, under a stated policy version.
_Avoid_: Approved story, publish flag

**Retention Schedule**:
An owner-approved, versioned production-policy artefact that names each audit and content retention class, its period, deletion behaviour and fail-closed rule. Missing class or period fails closed. It is not a Rights Record and does not authorise retaining source expression beyond that Rights Record.
_Avoid_: Rights Record, backup policy, TTL flag, retention_scope

**Target Publication**:
The desired and observed delivery lifecycle of one publication-bundle payload on one controlled public target.
_Avoid_: Published flag, message status

**Target Attempt**:
A durable fenced record created before external I/O for one exact Target Operation, with its stable semantic idempotency key and current authority preconditions.
_Avoid_: Worker run, retry count

**Target Acknowledgement**:
An untrusted target response correlated to one exact Target Attempt and validated with its adapter identity, target context, native identifier, response digest, target timestamps and verification result.
_Avoid_: Publication proof, worker success

**Target Observation**:
An immutable, independently controlled observation of a target payload or public effect, recording the asserted effect time, later observation time, method, observer identity, native evidence or content digest and verification result.
_Avoid_: Acknowledgement, mutable published flag

**First Public Effect Time** (`first_public_effect_at`):
The derived earliest valid asserted-effect time at which any controlled target made an authorised payload publicly observable. Every Target Acknowledgement and Target Observation from which it is derived retains when and how that fact became known.
_Avoid_: Feed timestamp, worker-finished time

**Primary Feed Published Time** (`primary_feed_published_at`):
The time assigned under the accepted feed policy when a story becomes eligible for ordering in the primary reader feed. It is distinct from an earlier or later public effect on another target.
_Avoid_: Universal first-publication time

**Target Acknowledged Time** (`target_acknowledged_at`):
The time at which a target acknowledged an exact target-operation attempt. It does not by itself prove when the payload became publicly observable.
_Avoid_: Publication time, successful worker time

**Access Policy Key**:
A stable, non-secret serving reference that identifies the kind of free-or-paid access rule to resolve. A surface payload carries this key, not a mutable policy revision or subscriber record.
_Avoid_: Paywall flag embedded in article identity, policy version

**Access Policy Revision**:
An immutable version of one access rule, including its content digest and activation authority. It does not contain an individual subscriber entitlement.
_Avoid_: Mutable policy row, customer record

**Access Policy Assignment**:
An immutable, authenticated and audited bitemporal decision that binds one Access Policy Key to one Access Policy Revision for a non-overlapping effective interval and retains its ledger recording sequence and supersession lineage. Changing an assignment does not create a new story version, surface payload or publication bundle unless reader-visible editorial bytes also change.
_Avoid_: Client-side entitlement, mutable pointer

**Entitlement Subject**:
A pseudonymous, store-ecosystem-scoped identity established from verified purchase proof. It is not a Newsroom customer account and does not imply that Apple and Google identities refer to the same person.
_Avoid_: User account, subscriber profile, customer

**Store Entitlement**:
The governed, provider-verified record that one Entitlement Subject may access a named paid product for an effective interval, including expiry, refund and revocation state.
_Avoid_: Client paywall flag, permanent subscription

**Subscription Trial**:
A store-managed introductory Store Entitlement that grants paid access for a defined trial interval. It is not a rule that makes each article free for its first few days.
_Avoid_: Article free window, anonymous app timer

**Free Sample**:
A reader-labelled item whose resolved Access Policy permits access without a Store Entitlement. It exists only after an authorised human Free Sample Designation and remains independent of whether that reader has started, completed or never used a Subscription Trial.
_Avoid_: Trial content, automatically free article, temporarily unlocked article

**Free Sample Designation**:
An authenticated human access-policy decision that makes or ceases to make one item a Free Sample. Automation may propose a candidate but cannot activate or revoke the designation.
_Avoid_: Free score, automatic rotation, editorial model decision

**Preview Excerpt**:
An exact, immutable and validated leading excerpt of a paid article, measured against its canonical narrative body, generated automatically under a versioned preview rule and included in its Publication Bundle. It is visibly incomplete and does not make the article a Free Sample.
_Avoid_: Free Sample, client-side truncation, teaser generated at request time

**Preview Media Permission**:
An explicit rights-validated permission that allows one governed non-text asset or approved derivative to appear in an unpaid Preview Excerpt. Its absence means the preview stops before that asset; it does not make the underlying article or asset free.
_Avoid_: Preview-eligible by default, public asset flag, client fallback

**Inline Paywall Gate**:
The reader-facing restricted-continuation surface placed directly after the authorised Preview Excerpt boundary, or after the article header and permitted hero media when the preview is hidden or empty. It never initiates a Store purchase flow without an explicit reader action.
_Avoid_: Automatic purchase popup, opening interstitial, detached paywall screen

**Store Commerce Metadata**:
The current platform-Store-authoritative product response used to present localised price, billing period and eligibility-specific trial or offer terms in an Inline Paywall Gate. It is ephemeral native-client display state, not a replayable Newsroom projection or Store Entitlement; the server selects product identity and access class but does not author, infer or substitute the commerce terms.
_Avoid_: Server price table, hard-coded trial, stale price cache

**Primary Commerce Action**:
The sole pre-purchase action given primary prominence in an Inline Paywall Gate: Start Trial when current Store Commerce Metadata confirms trial eligibility, Subscribe otherwise, or Retry when that metadata cannot be obtained. Restore Purchase remains a separate secondary action; exact copy and visual styling do not change the semantic action.
_Avoid_: Competing primary actions, assumed trial eligibility, primary restore action

**Entitlement Verification Barrier**:
The access boundary after the native Store reports purchase success and before verified proof produces an effective Store Entitlement and Access Grant. Paid content remains restricted throughout; a Store callback or local receipt alone is not paid access.
_Avoid_: Optimistic unlock, purchase-success flag, receipt-as-access

**Purchase Cancellation**:
A reader-originated ending of the native Store flow before purchase success. It is a transient non-error outcome that creates no entitlement-verification work and returns the restricted Inline Paywall Gate to its current pre-purchase state.
_Avoid_: Purchase failure, refund, Entitlement revocation

**Verification Delay**:
The non-terminal condition in which the native Store has reported purchase success but server verification has not completed within the reader wait limit. Access remains pending and restricted; recovery continues against the same Store transaction without initiating another purchase.
_Avoid_: Purchase failure, repurchase prompt, optimistic access

**Verification Recovery**:
The single-flight, idempotent re-evaluation of the same Store transaction during a Verification Delay, triggered by reader retry or a safe client or provider signal. It cannot initiate a new purchase or create parallel verification authority.
_Avoid_: Repurchase retry, parallel verification, automatic purchase

**Verification Failure**:
A terminal outcome for one Store transaction after an authenticated provider verdict proves it invalid or incapable of granting the selected product and access class. Transport errors, throttling, provider unavailability and absent or delayed responses are Verification Delay, not Verification Failure.
_Avoid_: Timeout failure, retry-exhaustion failure, Purchase Cancellation

**Verification Failure Reason**:
A stable reader-safe classification of a submitted transaction's provider-definitive Verification Failure: Transaction Invalid, Product Mismatch, Store Context Mismatch, Entitlement Inactive at verification time or Purchase Not Verified. It never exposes raw provider detail and does not classify later expiry, refund or revocation of an already verified Store Entitlement.
_Avoid_: Raw provider code, free-form error, stack trace

**Verification Failure Recovery**:
The Restore-first route from a Verification Failure: Restore Purchase is primary and Get Help is secondary while transaction retry and new purchase remain unavailable. Get Help may carry only an opaque diagnostic reference, and fresh purchase returns only after provider-backed restore confirms there is no active or pending entitlement.
_Avoid_: Repurchase first, raw provider error, identity-bearing support bundle

**Support Case**:
A privacy-minimised request created when a reader submits the Newsroom-hosted Get Help form, containing one opaque diagnostic reference and only the reply address or description the reader voluntarily supplies after consent. It is handled in a restricted Web Admin queue and is not a Newsroom account, entitlement evidence or reading history.
_Avoid_: Customer account, automatic email, receipt bundle

**Global Preview Control**:
An authenticated and audited owner control that enables or disables Preview Excerpt serving across paid content without changing article or Publication Bundle identity. Missing or indeterminate control state means previews are disabled.
_Avoid_: Backdoor, hidden flag, editorial rewrite

**Access Grant**:
A signed, short-lived credential issued after an effective Store Entitlement has been verified, scoped to one Entitlement Subject and permitted access class.
_Avoid_: Login session, stored receipt, permanent token

**Access Decision**:
A time-specific result produced by resolving an Access Policy Assignment and, where paid access is required, a valid Store Entitlement or Access Grant. It does not change editorial content identity.
_Avoid_: Paywall flag, publication decision

## Autonomous evaluation and control

**Hermes Control Plane**:
The complete local autonomous authority comprising an AI controller and an
inseparable deterministic policy-and-effect boundary. The AI controller may
decide and orchestrate; only the deterministic boundary holds authority-store,
projection or target credentials and it rejects any command that fails a frozen
veto. A model subprocess is not the Hermes Control Plane. An operator console
is not the Hermes Control Plane.
_Avoid_: Individual model, unrestricted agent, model-held database credential, Hermes Agent CLI, newsroom-hub, official messaging gateway

**First I/O Gate**:
One named Increment 9 precondition that must PASS before the shadow campaign may perform decision-bearing live I/O. The current inventory is ten runtime gates plus ten OD-001 source-rights gates. A namesake PASS in another packet does not satisfy it.
_Avoid_: Proving Gate, Increment 10 fixture residual gate, HTTP 200, curl success

**Qualification Evidence**:
Retained proof that one First I/O Gate can later be sealed. It is not a First I/O Gate Record and does not authorise campaign launch.
_Avoid_: GateRecord, campaign PASS, Proving Gate PASS, GitHub comment as proof

**First I/O Gate Record**:
An immutable sealed PASS or non-PASS for one First I/O Gate on one exact main SHA and tree. Records are minted only at a freeze of one checkout, after the Qualification Evidence exists.
_Avoid_: Proving Gate, Qualification Evidence, issue comment, HTTP 200

**Active Coverage**:
Retained proof that decision-bearing live I/O ran under sealed First I/O Gate Records and closed with a qualifying evaluation disposition. Qualification Evidence, a First I/O Gate Record, a Proving Gate PASS and a fixture canary are not Active Coverage.
_Avoid_: Qualification Evidence, GateRecord mint, Proving Gate PASS, fixture canary, HTTP 200

**Increment 9Q Packet**:
One authorised issue and pull request that produces Qualification Evidence for one First I/O Gate, or for one named cluster that shares a single evidence object. It does not mint a First I/O Gate Record and does not launch the shadow campaign.
_Avoid_: Increment 9P, Increment 11, campaign launch, GateRecord mint

**Kill Switch**:
The automated stop signal inside the Increment 9 runtime. Its propagation must early-stop the run with the original failure retained and zero public effect, zero production mutation and zero orphan resources, and an engaged Kill Switch fails the launch assessment closed. It is not the human emergency stop and not the Hermes Control Plane signed stop.
_Avoid_: Human Emergency Stop, Hermes signed stop, OWNER_STOP, feature flag

**Human Emergency Stop**:
A signed global or scoped stop issued by an authenticated Human Accountable Owner and executed by Hermes immediately. While one is active, no decision-bearing run may launch: the `NO_ACTIVE_HUMAN_EMERGENCY_STOP` gate fails closed. In production every Human Emergency Stop carries `HUMAN_RELEASE_REQUIRED`: resumption needs an explicit authenticated human release, and deterministic repair proof is a precondition of release, never a substitute for it. It is not the Kill Switch and not the Hermes Control Plane signed stop.
_Avoid_: Kill Switch, Hermes signed stop, auto-resume, pause flag, operator preference

**No-Stop Assertion**:
An owner-signed, time-bounded statement that no Human Emergency Stop is active for one exact execution-authority record. It must be current and bound to that record, and a later signed stop supersedes it. It is not a First I/O Gate Record and grants no run authority by itself.
_Avoid_: Bare boolean attestation, permanent waiver, run authority, GateRecord

**Rights Gate**:
One of the ten OD-001 source-rights First I/O Gates. It PASSes only through three sealed Rights Review Records for its exact Source Definition and endpoint, from three distinct provider families, unanimously. It is not the `PROVIDER_TERMS_CURRENT` gate and not a Proving Gate rights check.
_Avoid_: Terms checkbox, licence assumption, Proving Gate PASS

**Rights Review Record**:
One sealed AI rights review for one Rights Gate, bound to the exact endpoint and terms-document digest and current within its validity window, recording terms, access method, data class, destinations and retention with a verdict. It is not ADR 0006 editorial consensus, not a First I/O Gate Record, and authorises no fetch.
_Avoid_: Editorial review, bare boolean attestation, GateRecord, terms screenshot

**Rights Record**:
An owner-approved, versioned production-policy artefact stating permitted access method, use classes, destinations and retention for one Source Definition, dataset or asset provider. It is not a Rights Review Record, First I/O Gate Record or Qualification Evidence; a 9Q PASS does not mint one.
_Avoid_: Rights Review Record, terms checkbox, GateRecord

**Protected Storage**:
The isolated shadow store for protected artefacts, enforcing no group or public access, append-only access audit on every read and write, deterministic purge against retention and rights-revocation bounds, and no-resurrection after purge with a retained tombstone. All `ProtectedArtifactClass` entries must carry a matching `ProtectedArtifactRule` bound to the OD-012 inventory. It is not the production authority store, not the Keychain credential store and not general backups.
_Avoid_: Production authority store, Keychain, backup volume, unencrypted cache

**Credential Class**:
The governed category identity of one secret. Ledger and evidence carry class, scope and digest only, never secret bytes. Resolution returns a metadata `CredentialRef`, not the secret itself. It is not a credential value, not a model subprocess handle and not a production store name.
_Avoid_: Secret bytes, API key, password, production SQLite

**Isolated Principal**:
The shadow campaign's sole access identity, bound by its principal digest to `ShadowAccessBoundary.principal_identity_digest`. Authority-store, projection and target credentials resolve only through this principal under least-privilege rules. It is not a production service identity and not a `purpose_identity`.
_Avoid_: Production service account, purpose identity, human owner account

**Egress Allow-list**:
The OD-012-frozen inventory of permitted egress destination classes together with request bounds. Every outbound request must pass per-request admission; any destination not on the allow-list is default-denied. Config validation alone does not satisfy enforcement. It is not a firewall rule list and not a readiness-only destination set in isolation.
_Avoid_: Default-allow, config flag, DNS blocklist, HTTP 200

**Egress Receipt**:
The metadata-only admission record of one outbound request: destination class, host, policy digest and applicable bounds. It never carries secret bytes. It is not a network packet capture, not a Target Acknowledgement and not a First I/O Gate Record.
_Avoid_: HTTP log, secret bytes, GateRecord, worker success

**Model Work Envelope**:
The controller-owned, immutable identity of one admitted unit of model work. It binds the exact cycle and editorial or Graphiti work references before any provider leaf is allocated, and joins every later invocation and productive or no-result outcome without aggregating child usage into a second parent total. A held or rejected zero-call decision creates no Model Work Envelope.
_Avoid_: Provider session, token bucket, mutable job, parent token total

**Model Invocation Receipt**:
The append-only lifecycle for one exact provider leaf under a Model Work Envelope: qualified policy, pre-dispatch allocation, transport observation, terminal usage evidence and any later reconciliation. Missing usage is explicitly `UNREPORTED` or `AMBIGUOUS`, never zero; exact zero requires proof that provider dispatch did not occur. Route-local uncertainty may open that route's circuit, while usage totals remain telemetry and do not impose a normal daily hard cut.
_Avoid_: Approximate aggregate log, missing-is-zero, parent-child double count, daily token quota

**Invocation Efficiency Policy**:
The exact qualified policy a controller must resolve before allocating one model invocation. It binds workload, provider, route, pinned model and reasoning, one-turn shape, prompt and context identities, and output and total bounds. A missing or ambiguous policy holds dispatch rather than guessing a nearby route policy.
_Avoid_: Provider default, rolling token budget, best-effort model choice, post-dispatch limit

**Prefunded Wallet**:
The sole funding pool for incremental paid-API spend within an Epoch: fixed capacity at the OD-011 £250 cap, prefunded at opening, non-replenishing and non-transferable. Subscription-class usage is ledgered but never debited from it. It is not a live provider prepaid balance and not an unlimited or replenishable budget.
_Avoid_: Provider prepaid balance, subscription wallet, top-up account, credit line

**Budget Reservation**:
A ledgered reservation that must exist and show sufficient remaining balance before any metered spend; spend debits only against it. It is not spend authority by itself and not a subscription-class ledger entry.
_Avoid_: Spend authority, wallet top-up, subscription usage, implicit debit

**Provider Terms Record**:
One sealed record of current provider terms for one admitted commercial/API provider class: class, terms URL, terms digest and a validity window. It covers terms of use, acceptable use and data-handling terms only, not pricing. It is not a Rights Review Record, not a Rights Gate verdict and not a boolean `terms_current` flag.
_Avoid_: Rights Review Record, terms checkbox, pricing table, boolean flag

**No-Provider Declaration**:
One sealed statement that one named route admits zero of the six OD-012 commercial/API provider classes; official-source HTTP and local readiness destinations may remain. Silent absence of terms is not this declaration, and it cannot be presented together with Provider Terms Records. It is not a Provider Terms Record and not an implicit no-provider assumption.
_Avoid_: Missing terms, Provider Terms Record, implicit no-provider, terms checkbox

**Prospective Run Authority**:
An exact `run_id` bound to a persisted execution-authority chain — a prospective `ShadowRun` under a valid `EvaluationEpoch` and the current `ManifestCohort`, with budgets and stop rules bound through the Epoch's `budget_rules_digest` and `thresholds_digest` and destination through the cohort's `exposure_contract_digest` — before any execution. It is not a First I/O Gate Record and grants no spend or publication by itself.
_Avoid_: First I/O Gate Record, bare non-empty run_id, campaign launch authority, GateRecord

**Proving Gate**:
A named fail-closed check for one isolated proving packet. It authorises only that packet's fetch or store. It is not a First I/O Gate and does not pass Increment 9 campaign launch.
_Avoid_: First I/O Gate, campaign PASS, live-coverage closeout

**Effective Manifest**:
The exact observed combination of Hermes, adapter, prompt, model, memory,
policy, source, index and runtime identities that produced one result. An Epoch
may contain more than one Effective Manifest, but qualification applies only to
a manifest cohort that independently satisfies its complete exposure contract.
_Avoid_: Latest configuration, approximate version, Epoch-wide average

**Effective Manifest Cohort**:
All decision-bearing cases produced under one exact Effective Manifest. The
final cohort is the cohort for the Effective Manifest active at closeout; older
cohorts remain comparative evidence and cannot qualify the final manifest.
_Avoid_: Mixed-version sample, pooled latest results

**AI Review Consensus**:
The sealed agreement of both authorised, provider-independent primary AI
reviewers, or a valid authorised AI adjudication of their disagreement. For the
accepted Increment 9 evaluation it is the editorial-quality ground truth; it is
not a human label and must never be described as human review.
_Avoid_: Human approval, majority vote with a missing primary, model confidence

**Evaluation Threshold Schedule**:
An owner-approved, versioned production-policy artefact that names each non-zero-tolerance evaluation metric, its threshold, and the evaluated version and product scope it binds. Missing metric or schedule fails closed. It is not ADR 0006 AI Review Consensus, not a QA-041 zero-tolerance defect, and not the CONT-084 originality overlap threshold.
_Avoid_: Confidence interval, Increment 9 Evaluation Plan, calibration result, aggregate score, originality threshold

**Hermes Publication Admission**:
The Hermes Control Plane's terminal decision that one exact Publication Bundle
meets `AUTO_PUBLISH`. It atomically commits the Publication Decision and Target
Operations, after which the deterministic target adapter dispatches without a
second approval. Claim Admission Decisions and Relation Admission Decisions are
not Hermes Publication Admissions and do not themselves cause publication.
_Avoid_: Claim admission, publish suggestion, model sending directly

**Production Operational Admission**:
The separate owner decision that admits the exact deployment identities
production activation will use, on evidence including the live Evidence Intake
canary closeout and re-evaluated component qualifications. Identities are
current only on the exact plan-freeze checkout and again at activation
admission; drift forces re-evaluation. `FIXTURE_OPERATIONAL_ADMITTED` never
inherits to it.
_Avoid_: Fixture admission inheritance, re-binding without re-evaluation, wall-clock expiry, activation authority

**Autonomy Envelope**:
An owner-signed, ledgered grant defining the scope in which Hermes may create
and close Epochs, deliver reviewed changes, recover, create canaries and promote
qualified production behaviour without waiting for a further human reply. It
never removes deterministic vetoes or an authenticated emergency stop.
_Avoid_: Unlimited permission, one-off run approval, silent production access

**Conditional Activation Authority**:
The part of an Autonomy Envelope that becomes effective automatically when all
named implementation, identity, rights, evidence, budget, ledger and emergency-
stop prerequisites hold. Possessing the planning record before those conditions
hold is not a live effect or a claim that the target exists.
_Avoid_: Immediate activation, manual approval queue, aspirational readiness

## Ledger, dispatch and projections

**Ledger Event**:
A consumer-neutral immutable event recording one authoritative domain change in ledger sequence. Its shared envelope contains non-sensitive routing metadata; protected payloads or object references remain within their authorised security domains.
_Avoid_: Queue row per consumer, delivery command

**Target Operation**:
An immutable, idempotent command authorising one exact operation for one exact publication-bundle payload on one controlled target. It is side-effect work for the publication controller, not a general projection event.
_Avoid_: Ledger event, generic job

**Projection Checkpoint**:
A consumer-specific record of the highest contiguous ledger sequence successfully applied with one projector and schema version. It cannot advance past a gap or failed dependency.
_Avoid_: Latest event seen, global cursor

**Projection Failure**:
A durable consumer-specific record that a ledger event or dependency could not be applied, including retry and dead-letter state. It does not alter the authoritative event or permit a checkpoint to skip the gap.
_Avoid_: Authoritative event status, ignored error

**Authoritative Projection Baseline**:
An immutable governed object, attested by a ledger record, from which a later consumer may initialise when earlier events are no longer retained. It declares its scope, ending ledger sequence, schema and projector contract, included aggregate and tombstone classes, retention limitations, source-event range, object manifest and digest; later events and tombstones still apply.
_Avoid_: Fabricated history, unversioned graph snapshot

**Semantic UI Projection**:
A versioned, machine-readable description of the user-interface state derived from canonical content, delivery and operational records for regression testing and agent inspection.
_Avoid_: Screenshot interpretation, visual scrape
