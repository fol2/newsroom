# Increment 5A zero-call and zero-spend schema hardening

**Issue:** #250
**Pull request:** #255
**Qualification base:** `main@8f53b1ef2200442b459d5d84087df1905efec4bd`
**Hardening commit:** `b313b30b712773198844dd680d9b5dd78e690984`

The effective production-qualification v2 JSON Schema now makes both external-call and provider-spend boundaries independently enforceable by any standards-compliant schema consumer:

- `budgets.max_external_calls_per_request` is exactly `{"const":0}`;
- `budgets.max_gross_cost_microunits_per_request` is exactly `{"const":0}`.

The canonical schema artifact and source-defined schema are byte- and digest-bound. A standalone `Draft202012Validator` regression proves that an otherwise valid production manifest is accepted at zero and rejected when either field is changed to one. The existing Python profile validator continues to enforce the same proposal-bound zero values as a second boundary.

The hardened effective schema digest is:

`sha256:3e2ac38b2c17d11b8ea29afe58bd0cdf6924146969600cad2b89fc82ec8607b9`

The corresponding exact owner-statement body digest is:

`sha256:665e146d420088a1a88e4946741bae187cd950e6e0eb733e103f2fcfda1fe37b`

The immutable proposal payload, proposal record, proposal bundle, historical proposal schema and fixture-replay schema are unchanged. No owner approval record is admitted by this change, no model or vector is loaded, no external request is made, no provider credential is used, and no live-source, shadow, canary, publication or production activation occurs.
