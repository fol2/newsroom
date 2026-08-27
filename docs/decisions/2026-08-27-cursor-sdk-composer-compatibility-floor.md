# Cursor SDK and Composer compatibility-floor amendment

**Status:** Accepted
**Owner:** Product owner
**Accepted:** 2026-08-27
**Canonical language:** English
**Issue:** [#816](https://github.com/fol2/newsroom/issues/816)
**Parent execution:** [#790](https://github.com/fol2/newsroom/issues/790)
**Owner authority amendment:** [#790 comment 5439864947](https://github.com/fol2/newsroom/issues/790#issuecomment-5439864947)
**Amends:** [`2026-08-20-graphiti.md`](2026-08-20-graphiti.md) and [`../specs/editorial-automation/graphiti-corpus-ingestion-amendment.md`](../specs/editorial-automation/graphiti-corpus-ingestion-amendment.md)

## Decision

Active and future Graphiti Cursor execution MUST use compatibility floors rather than exact product-version ceilings:

```text
Cursor SDK: official stable cursor-sdk >= 1.0.29
Composer:   canonical composer model >= 2.5
```

This amendment supersedes every earlier **active normative or executable** clause that requires exactly `cursor-sdk==1.0.29` or exactly `composer-2.5` for future execution. It does not rewrite historical receipts, research measurements, incident evidence, prior PR descriptions or other records that truthfully identify the concrete SDK/model observed at that time.

Until #816 is implemented, reviewed, merged, deployed and provider-free qualified, the existing exact-pin runtime MUST remain fail-closed and MUST NOT perform a provider call under the withdrawn Step 7 approval.

## SDK floor and resolved lock

1. The dependency requirement and runtime admission floor MUST be `cursor-sdk>=1.0.29`.
2. A reproducible dependency lock MAY record one exact resolved SDK artifact. That resolved artifact is an observed build/deployment identity, not an upper compatibility ceiling.
3. Runtime qualification MUST parse the actual installed SDK version and reject versions below `1.0.29`, malformed versions and prerelease versions before provider dispatch.
4. The actual installed SDK version and requirement identity MUST be retained on the qualification receipt.
5. A numerically newer SDK is not automatically trusted. Its supported API, construction, isolation, cancellation, usage and receipt surfaces MUST pass the same provider-free compatibility qualification. Incompatible capability or API drift fails closed before dispatch.

## Composer floor and deterministic selection

One model-catalogue query MUST be used to select a model for one governed execution.

1. A candidate model ID is admissible only when it exactly matches:

   ```text
   composer-<major>.<minor>
   composer-<major>.<minor>.<patch>
   ```

   where every version segment is decimal numeric text.
2. The semantic version MUST be at least `2.5`.
3. From all admissible candidates, the controller MUST deterministically select the numerically highest semantic version. A two-segment ID is compared as patch `0`.
4. `Auto`, `Fast`, aliases, prerelease/non-numeric identities, differently named Composer variants and non-Composer models MUST NOT qualify.
5. The selected catalogue model ID MUST be passed explicitly to the SDK request.
6. The selected catalogue model and the actual resolved run model MUST both be retained. An absent, non-canonical or incompatible resolved model fails truthfully; it MUST NOT be silently rewritten to the selected value.
7. A higher Composer version does not authorise another provider family, a weaker prompt/output contract, more tools/context, wider token limits, retries or fallback.

## Preserved execution contract

The following controls remain unchanged:

- purpose-provisioned `CURSOR_API_KEY` only;
- `tools=[]` and explicit denial of shell, MCP and task capabilities;
- no MCP servers, custom tools, subagents, setting sources or prior conversation context;
- empty non-git working directory and isolated ephemeral store;
- governed `request_digest` idempotency;
- durable pre-send dispatch fence;
- typed stream, status, error, cancellation and usage handling;
- `max_retries=0`;
- controller, extraction and cleanup bounds of `160000 / 180000 / 20000 ms`;
- truthful partial or `UNREPORTED` usage;
- no Cursor CLI, browser/IDE login, Keychain bridge or CLI fallback; and
- no same-event retry, replacement event or implicit successor authority.

## Receipt and policy migration

1. Existing v1 exact-pin qualification receipts remain valid immutable historical evidence.
2. New execution MUST use a versioned compatibility-floor qualification receipt that retains the SDK floor, actual SDK version, Composer floor, selected catalogue model, actual resolved model and transport-policy digest.
3. The Graphiti call-shape policy and its digest MUST be versioned for the compatibility-floor semantics.
4. #790 Step 7 exact-pin authority MUST be recorded as withdrawn before consumption. A new successor packet MUST remain `DRAFT` / `executable: false` until exact-main provider-free qualification, a zero-finding final review receipt and a new owner-authenticated single-use approval exist.

## Operational boundary

#816 grants no model-catalogue query, fresh event, provider dispatch, worker/circuit activation, route reset/reopen, backlog drain, retry, publication, public dispatch or Production Operational Admission.

After #816 merges, the operational checkout MUST be deployed and provider-free qualified on the exact resulting `main`. Only a later owner comment naming that deployment and the reviewed compatibility-floor packet may authorise one catalogue query, one fresh event, at most one provider dispatch and zero retries.