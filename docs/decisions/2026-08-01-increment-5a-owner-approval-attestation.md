# Increment 5A owner-approval attestation and effective qualification authority

**Status:** Implemented verification contract; no approval claim or verified approval recorded
**Issue:** #250
**Pull request:** #255
**Proposal base:** `main@c9e31879421083e82e2538d57087d04e9b454d34`
**Proposal payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Proposal record:** `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`
**Proposal bundle:** `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`
**Proposal production-profile schema:** `sha256:2cdaa92a487ff48dd6095e1cc82af6f67362c168c557d9e6c3ecfe83e83cb647`
**Effective qualification-profile schema:** `sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef`
**Approval-claim schema:** `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`
**Fixture-replay schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`
**GitHub verifier contract:** `github-issue-comment-approval-verifier-v1`

## Immutable proposal

The proposal packet is immutable proposal evidence. It remains
`PENDING_OWNER_REVIEW` after an owner later approves that exact proposal.
Approval is never represented by changing proposal bytes, status, component
dispositions, profile lists, runtime authority or digests.

The historical proposal production-profile schema remains available only under
explicit `PROPOSAL_PRODUCTION_PROFILE_SCHEMA*` names because its digest is part
of the immutable proposal. Every unqualified `PRODUCTION_PROFILE_SCHEMA*`
package export resolves to the hardened effective qualification schema instead.
The proposal schema cannot validate an effective production profile.

## Three distinct authority states

The implementation deliberately separates:

1. **Proposal** — the immutable pending decision packet. It authorizes only
   non-qualifying fixture replay.
2. **Approval claim** — canonical JSON that states which proposal, schemas,
   components, owner, issue, PR, comment and UTC time are claimed. Parsing this
   file proves structure and digest consistency only. It is untrusted and cannot
   create production authority.
3. **Verified approval** — a private capability created only after the
   repository verifier performs a fresh authenticated GitHub REST read and
   matches the exact external owner comment. Only this state can construct an
   effective production-qualification authority.

No approval claim or verified approval is checked into the repository.
`INCREMENT_5A_DECISION_AUTHORITY.production_authorized` therefore remains
false and issue #251 remains blocked.

## Approval claim binding

The canonical claim binds:

- proposal decision, payload, record and contract-bundle identities;
- the historical proposal production-profile schema;
- the hardened effective production-qualification schema;
- the fixture-replay schema;
- every exact component identity digest;
- owner display name and GitHub login;
- issue #250 and PR #255;
- the exact GitHub issue-comment ID and HTML URL;
- the SHA-256 digest of the exact owner statement; and
- canonical microsecond UTC approval time.

A changed proposal, schema, component, owner, issue, PR, comment, statement or
time creates a different or invalid claim.

## Authenticated GitHub verification

`GitHubIssueCommentApprovalVerifier` accepts an explicit bounded bearer token
and performs one fixed request:

```text
GET https://api.github.com/repos/fol2/newsroom/issues/comments/{comment_id}
```

The verifier:

- sends the fixed GitHub JSON media type and API version;
- permits no redirects;
- accepts only HTTP 200 JSON within a 128 KiB response bound;
- rejects duplicate JSON object names and malformed UTF-8;
- requires the exact API URL, issue URL and issue #250 HTML comment URL;
- requires GitHub login `fol2`, immutable GitHub user ID `105634418`, and
  `author_association=OWNER`;
- requires the exact owner statement byte for byte;
- recomputes and compares the statement digest;
- requires claim approval time to equal the GitHub comment creation time;
- rejects edited comments by requiring `updated_at == created_at`; and
- records a verification digest over the claim and canonical GitHub response.

The token is not placed in the claim, profile, logs or effective contract. A
caller-supplied JSON object, subclass, fake verifier, claimed author name or
claimed timestamp cannot create the private verified-approval capability.

## Effective production-qualification profile

The effective profile uses
`increment5-production-qualification-profile-v2`. It binds the immutable
proposal record and bundle, the GitHub verification digest and the resulting
effective-contract digest. Every component remains exact and is marked
`APPROVED_BY_ATTESTATION` only after verification.

`protected_content_allowed` is a schema constant of `false`. A manifest
operator cannot enable protected-content processing, including under an
otherwise valid verified approval. Rights-restricted source text, personal
data, secrets and credentials remain prohibited from the Increment 5 v1 vector
lane. Expanding that boundary requires a new data-class-specific owner decision,
schema and qualification epoch.

## Approval effect and non-effects

A verified approval authorizes only:

- implementation of issues #251–#254 under the exact bound contracts; and
- production-equivalent qualification of those exact components under the
  pre-registered Evaluation Plan.

The immutable non-effect set is:

- shadow;
- canary;
- production activation;
- publication or public effect;
- live-source execution;
- external embedding API calls;
- provider spending; and
- protected-content vectors.

A claim that drops any non-effect fails schema validation.

## Exact owner statement

After this PR reaches an exact reviewed head with all permanent gates passing
and zero unresolved P1/P2 findings, the owner must post the following exact
single-line body as a comment on issue #250:

```text
I approve Increment 5A proposal payload `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`, proposal record `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`, proposal contract bundle `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`, effective production-qualification schema `sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef`, approval-attestation schema `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`, and fixture-replay schema `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e` as the exact implementation and production-equivalent qualification contract for issues #251–#254. This approval authorizes no shadow, canary, production activation, publication, public effect, live-source execution, external embedding API call, provider spending, or protected-content vector.
```

Line wrapping by a client changes the body and is rejected. The approval claim
must use the exact comment ID, body digest and canonical microsecond form of the
comment creation time returned by GitHub. Editing the comment invalidates it;
a corrected decision requires a fresh exact comment and fresh verification.

## Fail-closed behavior

- Bare proposal packets authorize fixture replay only.
- A canonical approval claim remains untrusted.
- Missing, malformed or noncanonical claims fail closed.
- GitHub lookup failure, unauthorized access, redirect, non-JSON response,
  oversized response or malformed response fails closed.
- A comment from another login, user ID or repository role fails closed.
- A different, edited or moved comment fails closed.
- A claimed time different from GitHub `created_at` fails closed.
- A production manifest without the GitHub verification and effective-contract
  digests fails closed.
- `protected_content_allowed=true` always fails schema validation.
- Fixture replay cannot substitute for real-vector qualification.
- `DEVAL-073`, `DOPS-064` and `DOPS-072` remain deferred to 5E/#254, where
  completed-run decisions, accountable runbooks and tested rollback actually
  exist.

## Runtime boundary

No model has been loaded, no vector created, no protected material processed,
no external approval lookup executed by the checked-in pending authority, no
provider credential used and no spend incurred by this contract. Issue #251
must not begin until a verified approval is retained through the reviewed 5A
merge boundary on `main`.
