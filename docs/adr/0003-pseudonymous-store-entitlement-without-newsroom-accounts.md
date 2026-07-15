---
status: accepted
date: 2026-07-15
---

# Pseudonymous store entitlement without Newsroom accounts

The initial Newsroom product will use a dedicated server-side entitlement verifier for Apple App Store and Google Play purchase proof without creating first-party Newsroom customer accounts. The verifier will retain only the minimum pseudonymous, ecosystem-scoped entitlement record needed to establish product, effective period, expiry, refund, revocation and verification evidence, and will issue a signed short-lived Access Grant. Names, email addresses, reader profiles and reading history do not belong in this entitlement domain, and a client-side paid flag is not authority.

Apple and Google entitlements remain separate in the initial product. Purchase and restore work within the originating store ecosystem; automatic iOS-to-Android portability is not promised. Adding cross-ecosystem account linking later requires a separate accepted decision because it would expand identity, privacy, support and security scope.

The introductory free trial is a store-managed, time-bounded Store Entitlement rather than an article-ageing rule. Independently designated Free Samples remain visibly labelled and readable without starting a trial or buying a subscription, including after a reader's trial expires. A Free Sample Designation requires an explicit authenticated human action in Web Admin; automation may suggest a candidate but cannot activate or revoke free access. Trial duration and the human operating policy for selecting and retiring Free Samples remain separately configurable product decisions.

Every paid article will automatically carry an exact validated Preview Excerpt of no more than one quarter of the canonical article body's readable narrative text, measured in Unicode grapheme clusters. Headline, byline, metadata, sources, related links, images and captions do not contribute to that denominator. Preview serving is enabled by default but can be disabled or re-enabled globally through an authenticated, audited owner control. This Global Preview Control changes the access projection only; it is not a hidden backdoor and does not rewrite the story, payload or Publication Bundle. Missing or indeterminate control state disables previews.

Device-only restriction was rejected because it cannot reliably protect server-served paid content or handle refund and revocation. A first-party account was rejected for the initial product because cross-platform convenience does not yet justify the additional personal-data and account-recovery boundary. Pseudonymisation and data minimisation reduce exposure but do not by themselves remove privacy or GDPR obligations.
