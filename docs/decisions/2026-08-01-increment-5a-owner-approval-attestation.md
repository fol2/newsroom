# Increment 5A owner approval record and production-qualification authority

**Status:** Repository-record contract implemented and restacked; no owner approval record admitted
**Issue:** #250
**Pull request:** #255
**Immutable proposal base:** `main@c9e31879421083e82e2538d57087d04e9b454d34`
**Current qualification base:** `main@8f53b1ef2200442b459d5d84087df1905efec4bd` (PR #256)
**Proposal payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Proposal record:** `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`
**Proposal bundle:** `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`
**Proposal production-profile schema:** `sha256:2cdaa92a487ff48dd6095e1cc82af6f67362c168c557d9e6c3ecfe83e83cb647`
**Effective qualification-profile schema:** `sha256:3e2ac38b2c17d11b8ea29afe58bd0cdf6924146969600cad2b89fc82ec8607b9`
**Approval-record schema:** `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`
**Fixture-replay schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`

## Immutable proposal

The proposal packet remains immutable proposal evidence and continues to parse
as `PENDING_OWNER_REVIEW` after approval. Approval never changes its bytes,
status, component dispositions, profile lists, runtime authority or digests.
The qualification-base restack changes none of those proposal identities.

## Authentication boundary

Owner approval is represented by two durable GitHub facts:

1. an exact, unedited owner comment on issue #250; and
2. a canonical approval record committed in the reviewed PR, binding the exact
   comment identity, URL, canonical creation time, body digest, proposal,
   schemas, component identities, effects and non-effects.

The repository record is admitted only when its exact canonical SHA-256 digest
is pinned in source in the same reviewed commit. The Git commit, pull-request
review and branch-protection evidence are therefore the authentication and
change-control boundary. Runtime code performs no caller-configurable HTTP
request and accepts no caller-provided approval object.

Before materialisation, `APPROVAL_RECORD_DIGEST` is `None` and the record path
must be absent. A stray unpinned file is an error. After materialisation, a
missing, changed or noncanonical record fails closed.

## Production gate

Production qualification does not trust class identity, mutable slots,
subclass methods, injected sessions or supplied verifier objects. At import,
the reviewed path, expected digest and parser are captured in one repository
loader. The authority façade closes over that loader. The public production
builder and validator are created by a factory that closes over a one-time
binding to the same loader and effective-contract calculator; the internal
implementations and binding getter are then removed from the module namespace.

The builder accepts no authority argument. The validator accepts only the
canonical source-bound authority object. Later reassignment of public path,
digest, loader, parser, authority or helper-function attributes does not alter
the closed-over production gates. The direct authority gate is independently
closed over the same reviewed loader.

A separately parsed record from another path is evidence only. It cannot be
passed into a production gate. This boundary assumes the running repository
code itself is trusted; arbitrary replacement of the public API function is
code replacement, not approval evidence.

## Exact owner statement

The owner comment on issue #250 must be the following exact single-line body:

> I approve Increment 5A proposal payload `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`, proposal record `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`, proposal contract bundle `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`, effective production-qualification schema `sha256:3e2ac38b2c17d11b8ea29afe58bd0cdf6924146969600cad2b89fc82ec8607b9`, approval-attestation schema `sha256:8e69e5a66949e103ec4a960af34a509f3ba8b86a9f32b08ed77930f0898b8577`, and fixture-replay schema `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e` as the exact implementation and production-equivalent qualification contract for issues #251–#254. This approval authorizes no shadow, canary, production activation, publication, public effect, live-source execution, external embedding API call, provider spending, or protected-content vector.

The exact body digest is:

`sha256:600c6b43c645d8c26d234c7a29d325650ab164791cdde457ac96b55b1b99cacd`

Line wrapping inserted by display is harmless only when the stored body remains
the exact single line. Editing, paraphrasing, changing a digest, changing the
author or using another issue is not accepted.

## Approval effect

An admitted record authorizes only:

- implementation of issues #251–#254 under the exact bound contracts; and
- production-equivalent qualification under the pre-registered Evaluation
  Plan.

It does not authorize shadow, canary, production activation, publication,
public effect, live-source execution, external embedding API calls, provider
spending or protected-content vectors. Those non-effects are exact schema
constants and cannot be removed from a record.

## Effective production profile

The proposal-time v1 schema remains historical proposal evidence only. All
unqualified `PRODUCTION_PROFILE_SCHEMA*` package names resolve to the hardened
v2 schema. Effective manifests require the proposal record, approval-record and
effective-contract digests, and bind every component identity.

`protected_content_allowed` is a schema constant of `false`. Personal data,
secrets, credentials and rights-restricted expression remain prohibited from
the Increment 5 v1 vector lane. Expansion requires a new data-class-specific
owner decision, schema and qualification epoch.

## Fail-closed cases

- no admitted record: production qualification is unauthorized;
- unpinned record at the repository path: import/use fails;
- missing or changed pinned record: use fails;
- noncanonical JSON, duplicate names or schema mismatch: parsing fails;
- wrong proposal, schema, component, owner, issue, PR, comment or body digest:
  binding fails;
- caller-created authority, subclass or parsed external record: production
  gates reject or ignore it;
- public loader, parser, authority and helper-function reassignment after import
  cannot change the source-closed gates;
- fixture replay remains non-qualifying and cannot substitute for production;
- `DEVAL-073`, `DOPS-064` and `DOPS-072` remain deferred to 5E/#254.

No model, vector, external embedding request, protected-content operation,
provider credential, provider spend, live-source run, shadow, canary,
publication or production activation is performed by this decision unit.