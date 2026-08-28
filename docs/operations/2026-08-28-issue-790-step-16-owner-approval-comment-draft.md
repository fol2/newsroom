# Step 16 owner-approval comment draft (non-executable)

**No live effect is authorised by this draft.**

## Exact merged identity
- PR: https://github.com/fol2/newsroom/pull/844
- commit: `f44121cfaeef3dbf09c16dd26e2636e7e63b2c78`
- tree: `9b4533603636ccaa8c5ad210a0ed6d3f73a11193`
- HOLD: `5458287374`

## Authority split
- checked candidate digest: `sha256:601d0cfe63775d5205de6c672b344ab8b0055521fe6f191eb526e25c72a48d9e`
- revoked former live digest: `sha256:72723b72b71f12fee2a9ec31c2b4145e5cbac4ac55f8ddbc51319248e94c21f9` (not in the approved-plan set)
- checked approval is rejected by `_require_approved_plan` / `load_issue_790_plan` / `apply_issue_790_plan` / `run_issue_790_canary`
- `finalise_issue_790_step16_plan` requires `github:fol2`, an issue-#790 comment URL, approval time, and named commit/tree
- owner-finalised output remains unregistered (not live authority)
- no apply-able `docs/operations/2026-08-28-issue-790-success-sequence-step-16.json`

## Packet digests (executable:false)
- causal report: `sha256:c10f71ef35bbbd7e4bcc3eac005d3f4959d03dcca699fb447d4f8eeaddaa4ca5`
- provider-free qualification: `sha256:a3beda40768154c125c85c4d1f84039fd46b1bdc37c6a48ad4ba53efb2570072`
- code-fix review receipt: `sha256:47d0dc9548dd65d1fbe6952087e72b06147896607822a2f59024898bf90237c9`
- reviewed-fix record: `sha256:bfb44a10ec9441c9a2c05761650bad0bd6e289910bbb58885241420ede0aaa5c`
- pre-dispatch requirements: `sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b`
- pending owner-review plan: `sha256:8651368768f8ead04d2d96c0d0bbcf387b3baefedaaa5b5a07fb2e4d169fe271`
- draft: `sha256:6c912ebd853b09a969f1f920988258711bbc9c260dfc73f763b9e4f22f96ed81`

## Carry-forward target identities (from Step 15)
- invocation_id: `sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c`
- allocation_digest: `sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120`
- terminal_digest: `sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe`
- policy_digest: `sha256:0d1b6d2f7b7163f26df1a5e382ba8341798726dad9e38e7d38a00ba2abf3a3eb`

## Pre-dispatch / live binding
- Frozen pending-family pre-dispatch still names `9cc0f5f` / `6ae1114` as sealer **input**, not live authority
- Owner finalise overlays `reviewed_correction_revision` / `reviewed_correction_tree`; apply compares them with operational evidence (`revision` / `tree` / GitHub main) before authority consumption
- Current merged tip to name if owner later authenticates: `f44121cfaeef3dbf09c16dd26e2636e7e63b2c78` / `9b4533603636ccaa8c5ad210a0ed6d3f73a11193`
- worker before provider I/O: `UNLOADED`
- fallback: `DISABLED_BEFORE_PROVIDER_DISPATCH`
- one untouched attempt-0 event only
- `NOT_OBSERVED` is not a satisfied canary precondition

## Decision placeholders for owner
```text
Checked candidate off live approved-plan gate: <ACCEPT|HOLD>
Owner-authenticated finalise path: <ACCEPT|HOLD>
Owner-review packet: <SEALABLE|HOLD>
Step 16 live canary authority: NOT APPROVED unless owner authenticates an approval tuple and registers the resulting plan
```
