# Increment 5A owner-approval attestation and effective qualification authority

**Status:** Implemented contract; no approval attestation recorded
**Issue:** #250
**Pull request:** #255
**Proposal base:** `main@c9e31879421083e82e2538d57087d04e9b454d34`
**Proposal payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Proposal record:** `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`
**Proposal bundle:** `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`
**Proposal production-profile schema:** `sha256:2cdaa92a487ff48dd6095e1cc82af6f67362c168c557d9e6c3ecfe83e83cb647`
**Effective qualification-profile schema:** `sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef`
**Approval-attestation schema:** `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`
**Fixture-replay schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`

## Correction

The proposal packet is immutable proposal evidence. It remains
`PENDING_OWNER_REVIEW` even after an owner later approves that exact proposal.
Approval must not be represented by changing proposal bytes, status, component
dispositions, profile lists, runtime authority or digests.

A separate canonical owner-approval attestation binds:

- proposal decision, payload, record and contract-bundle identities;
- the historical proposal production-profile schema;
- the hardened effective production-qualification schema;
- the fixture-replay schema;
- every exact component identity digest;
- owner display name and GitHub login;
- issue #250 and PR #255;
- UTC approval time; and
- an immutable GitHub issue-comment ID, URL and body digest.

The repository currently contains the attestation schema and validator only. It
contains no owner-approval attestation. Consequently,
`INCREMENT_5A_DECISION_AUTHORITY.production_authorized` remains false and the
production-qualification profile cannot validate.

## Effective production-qualification schema

The proposal-time v1 schema is retained only because its digest is inside the
immutable proposal. It is private proposal evidence and cannot authorize a
runtime profile.

Any effective production-qualification manifest must instead use
`increment5-production-qualification-profile-v2`. That schema requires the
proposal record digest, approval-attestation digest and effective-contract
digest in addition to the proposal payload and bundle. Every component remains
bound to the exact proposal identity and is marked
`APPROVED_BY_ATTESTATION`.

`protected_content_allowed` is a schema constant of `false`. A manifest
operator cannot enable protected-content processing. Rights-restricted source
text, personal data, secrets and credentials remain prohibited from the
Increment 5 v1 vector lane. A future expansion requires a new explicit
data-class-specific rights decision, schema and qualification epoch; it cannot
be inferred from this approval.

## Approval effect

A valid attestation authorizes only:

- implementation of issues #251–#254 under the exact bound contracts; and
- production-equivalent qualification of those exact components under the
  pre-registered Evaluation Plan.

It does not authorize:

- shadow;
- canary;
- production activation;
- publication or public effect;
- live-source execution;
- external embedding API calls;
- provider spending; or
- protected-content vectors.

Those non-effects are an exact constant in the approval schema and cannot be
dropped by an approval document.

## Exact owner statement

After this PR reaches an exact reviewed head with all permanent gates passing
and zero unresolved P1/P2 findings, owner approval must be recorded as a
comment on issue #250. The comment should state:

> I approve Increment 5A proposal payload
> `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`,
> proposal record
> `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`,
> proposal contract bundle
> `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`,
> effective production-qualification schema
> `sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef`,
> approval-attestation schema
> `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`,
> and fixture-replay schema
> `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`
> as the exact implementation and production-equivalent qualification contract
> for issues #251–#254. This approval authorizes no shadow, canary, production
> activation, publication, public effect, live-source execution, external
> embedding API call, provider spending or protected-content vector.

The attestation record then binds the exact comment ID, URL, author and body
digest. A paraphrase, changed digest, different author or different issue is
not accepted.

## Fail-closed behavior

- Bare proposal packets authorize fixture replay only.
- Missing or malformed attestations fail closed.
- An attestation for another payload, record, bundle, schema, component set,
  owner, issue, PR or comment fails closed.
- A production manifest without the exact attestation and effective-contract
  digests fails closed.
- `protected_content_allowed=true` fails schema validation even under a valid
  synthetic attestation.
- Proposal schema v1 cannot substitute for effective qualification schema v2.
- Fixture replay remains non-qualifying and cannot substitute for the real
  vector lane.
- `DOPS-072` remains deferred to 5E/#254, where rollback is actually tested.

## Runtime boundary

No model has been loaded, no vector created, no protected material processed,
no external request made, no credential used and no spend incurred by this
contract correction. Issue #251 remains blocked until the exact approval
attestation is committed through the reviewed 5A boundary on `main`.
