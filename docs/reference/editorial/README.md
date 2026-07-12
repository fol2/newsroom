# Editorial reference documents

This directory contains human-oriented product and editorial reference material for the autonomous newsroom.

## Language authority

The canonical charter is:

- [`product-editorial-charter.zh-HK.md`](product-editorial-charter.zh-HK.md) — canonical Hong Kong Traditional Chinese (`zh-HK`) reference.

The development translation is:

- [`product-editorial-charter.en.md`](product-editorial-charter.en.md) — English translation for development agents and technical contributors.

If the two charter versions diverge, the `zh-HK` version controls. A translation update must identify the canonical file and must not silently introduce a policy decision that is absent from the canonical version.

## Relationship to specifications

The charter defines product intent and the boundary within which autonomous editorial operation may be designed. It remains non-normative reference material.

The normative development requirements derived from the charter are maintained in the [`editorial-automation` specification suite](../../specs/editorial-automation/). The specification suite is canonical in English because it is intended for implementation, testing and agentic SDLC work.

A change to the charter does not automatically change production behaviour. A corresponding specification change must be reviewed and accepted before implementation. Likewise, a specification must identify any intentional departure from the charter rather than silently redefining the reference policy.
