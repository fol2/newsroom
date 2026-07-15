# Newsroom domain language

**Status:** Proposed vocabulary

This glossary proposes the canonical meanings of editorial records that connect evidence, decisions, publication and derived newsroom intelligence. The product owner has not accepted this vocabulary yet.

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
