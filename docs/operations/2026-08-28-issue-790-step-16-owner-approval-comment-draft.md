# Owner approval comment draft — Step 16 canary (NOT POSTED)

**Status:** draft only · `executable: false` · no approval assumed

Copy only after independent owner verification. Do not treat this file as approval.

## Required named identities

- merged `main`: `7b6c3423bf4b46b80a930826c00383097105a14d`
- tree: `d77ba3b4a73161b9b1b3171e1d8b7aab31f60d47`
- reviewed tip before squash: `88c61c8d551bbfc2503c9bcd31bdf55ad5e448e6`
- PR: https://github.com/fol2/newsroom/pull/840
- Focus Gates exact tip: https://github.com/fol2/newsroom/actions/runs/33204489662
- Focus Gate manifest: `sha256:e69bda0fb23814321c49683f73a1f159b8dad9ddd00d08226958b86168d95564`
- projection policy: `NewsroomGovernedProposalProjectionV1` / `sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c`
- temporal policy: `graphiti-source-reference-time-v2`
- validator: `NewsroomCombinedTemporalNormaliseV2`
- call-shape digest: `sha256:ba1cb4267ff78419174b50a0e233545a4bf745168d4f7fdbffa2fb6007ab5abc`
- pending plan digest: `sha256:f0a05a07fe3d65cbaed792987ce6885fd1f5d6f70f201a67cdaece408a8b264c`
- draft digest: `sha256:188d83f22183e13e083193eca0f8d71ad541df8a1ca2f32c081af17c5829df79`
- qualification digest: `sha256:cc69d2b2d9a0050be38bf681326b5d4a953fdb33858772fa3fd2acf8f4e7104b`
- review receipt digest: `sha256:94c335c5e9762b2d20b6c4a273de0f58712f88f086b9b9feb3fafa85b2b802f6`
- reviewed-fix record digest: `sha256:821dfaeaf6e502f8a06c1ae2276e902b90c152e1a3f56c8168f3a4bc28e39dba`
- causal report digest: `sha256:d020e4418ba4fe5b684d04857fa39ff459b1a287b5d03ae2a7b0c390c3f30f66`

## Suggested approval scope (owner to edit)

Authorise at most:

- exact main deployment of `7b6c3423bf4b46b80a930826c00383097105a14d` if not already the live tip;
- at most one model-catalogue query if required by the executable plan;
- one untouched fresh event;
- one provider dispatch;
- zero retries;
- zero fallback;
- no publication / backlog drain / route widening / worker activation beyond the single canary.

## Explicit non-authority until posted by owner

This draft authorises nothing. `OWNER_AUTHENTICATED_STEP_16_CANARY_APPROVAL` remains unsatisfied.
