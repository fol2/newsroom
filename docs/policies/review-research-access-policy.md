# Review Research Access Policy

- **Role:** Owner-approved production policy
- **Status:** Owner-approved
- **Owner:** Human Accountable Owner (`fol2`)
- **Version:** 1
- **Canonical language:** UK English
- **Date:** 2026-08-17
- **Authorised by:** [#628](https://github.com/fol2/newsroom/issues/628) (OD-012 provider terms retrieval and sealing)
- **Issue:** [#636](https://github.com/fol2/newsroom/issues/636)

## Purpose

This policy governs the `APPROVED_REVIEW_RESEARCH` credential class: the dynamic,
logged, non-decision-bearing reviewer-research egress class used during Increment 9
sealed AI review (OD-009). It has no single commercial counterparty. Its Provider
Terms Record binds this document at the raw repository URL pinned to the freeze SHA,
with a terms digest of SHA-256 over its exact bytes (#567 record contract).

## Scope

This policy applies to every external research fetch performed under the
`APPROVED_REVIEW_RESEARCH` class during reviewer work. It does not govern the ten
OD-001 source-rights classes, commercial API classes, Evidence Intake or publication
egress.

## Access rules

1. **Public pages only.** Review research MAY retrieve only publicly accessible web
   pages that require no authentication, subscription login, cookie session or other
   access credential.
2. **No paywall or access-control circumvention.** Review research MUST NOT bypass,
   disable or evade paywalls, registration walls, geographic blocks, bot challenges
   or any other access control.
3. **No credentialed fetch.** Review research MUST NOT attach credentials, tokens,
   API keys, session cookies or owner-provisioned secrets to a research request.

## Site compliance at use time

Review research MUST respect the robots directives and applicable per-site terms of
each target at the time of retrieval. A target whose robots rules or site terms
forbid automated retrieval MUST NOT be fetched under this class.

## Evidence recording

Every research action MUST be recorded in the reviewer evidence appendix (OD-009).
Each entry MUST include:

- the query submitted;
- the URL retrieved;
- the SHA-256 digest of the retrieved bytes;
- the observation time; and
- the stated purpose of the retrieval.

## Retention

Retrieved bytes MUST be retained as `REVIEW_RESEARCH_BYTES` protected artefacts under
OD-012 retention rules: lineage, encryption at rest, the positive retention ceiling
and rights-revocation purge deadline bound by the active Effective Manifest.

## Decision-bearing status

Review research remains logged and non-decision-bearing until a new Effective
Manifest. Under the shadow-plan egress allowlist rule
`LOGGED_NON_DECISION_BEARING_UNTIL_NEW_MANIFEST`, retrieved research bytes and
their evidence appendix entries MUST NOT alone satisfy, override or substitute for
a sealed review decision, editorial gate or publication authority.

## Authority boundary

Merging this document grants no live fetch, credential, spend, mint, campaign-launch,
publication or activation authority.

If this document is absent or not owner-approved on the freeze checkout, the
`PROVIDER_TERMS_CURRENT` First I/O Gate MUST NOT PASS on the shadow route — fail
closed (#567 refusal class 4).
