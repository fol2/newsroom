# Control Plane rights renewal

The private-beta proving intake evaluates one hard Rights Gate for each of the
ten OD-001 sources. A gate such as `RIGHTS_HK-01` passes only when its packet
contains exactly three independently identified, validly sealed review records
whose source, endpoint, terms identity and destination set agree.
The renewed destination set covers the ten approved source endpoints plus the
three reviewed evaluation routes: Cursor Agent CLI, Grok Build CLI and
OpenRouter embeddings.

The Control Plane checks the retained packet against the real dispatch time on
every cycle. It does not sign on every cycle. An unchanged, valid packet is
reused for up to 30 days and the complete ten-source packet set is renewed when
seven days or less remain. One renewal therefore creates 30 seals: three for
each of ten source gates.

Automatic renewal is deliberately narrower than automatic approval. It may
renew only the accepted, unchanged fixture review contract. A malformed packet,
digest mismatch, invalid seal, incomplete latest packet set or terms-identity
change fails closed instead of falling back to older authority. Autonomous
rights-risk acceptance is an auditable operating decision; it is not permission
from a source owner.

Current operational endpoints for `UK-10` and `RAD-01` are the final HTTPS
hosts `www.metoffice.gov.uk` and `rthk9.rthk.hk`. The older redirecting
aliases `weather.metoffice.gov.uk` and `rthk.hk` are retired from current
authority; a structurally valid sealed packet that still binds exactly those
aliases is renewed to the current `BINDINGS` endpoints and is never reused,
while arbitrary endpoint drift still fails closed. Historical signed-plan
files keep the earlier URLs as versioned evidence. This document records the
current endpoint correction, not a rewrite of those plans. `BINDINGS` is the
single source of current endpoint authority; proving transport derives the
same URLs.

The renewal changes no publication authority. Proving intake retains
`publication=false`, `public_dispatch=false` and zero OpenRouter spend.
