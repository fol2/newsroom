# Newsroom domain language

**Status:** Proposed vocabulary

This glossary proposes the canonical meanings of editorial records that connect evidence, decisions, publication and derived newsroom intelligence. The product owner has not accepted this vocabulary yet.

## Evidence and relationships

**Source Observation**:
A retained record that a source presented particular content at a particular time. It proves what was observed, not that the source's claim is true.
_Avoid_: Source truth, verified fact

**Relation Assertion**:
A first-class statement that a subject bears a named relationship to an object, together with its provenance and applicable time semantics.
_Avoid_: Smart edge, graph fact

**Relation Proposal**:
A retained, immutable candidate relation assertion submitted for an admission decision. It is ineligible as approved publication evidence.
_Avoid_: Probable fact, low-confidence relation

**Relation Admission Decision**:
An immutable governance decision that admits or rejects one exact relation-proposal identity for a stated use and trust scope.
_Avoid_: Status update, confidence threshold

**Admitted Relation**:
A derived relation assertion projected from an immutable relation proposal and its admitting decision. Admission does not by itself make the relation publication evidence.
_Avoid_: Approved relation, high-confidence relation, model-approved relation

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
A separate governed record that authorises or refuses one exact publication-bundle digest under a stated policy version.
_Avoid_: Approved story, publish flag

**Target Publication**:
The desired and observed delivery lifecycle of one publication-bundle payload on one controlled public target.
_Avoid_: Published flag, message status

**Access Policy Reference**:
A stable reference from a serving payload to the versioned free-or-paid access rule evaluated separately from editorial content identity. Changing the rule does not create a new story version or publication bundle unless reader-visible editorial bytes also change.
_Avoid_: Paywall flag embedded in article identity, subscriber record

**Semantic UI Projection**:
A versioned, machine-readable description of the user-interface state derived from canonical content, delivery and operational records for regression testing and agent inspection.
_Avoid_: Screenshot interpretation, visual scrape
