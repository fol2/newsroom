# Reference material

Reference documents preserve useful context without directly controlling implementation. Humans and AI agents may use them to understand the product, identify risks, conduct research or draft a specification, but must not turn their contents into code or production behaviour unless an accepted spec or explicit owner instruction adopts the relevant requirement.

Repository-authored reference documents default to Hong Kong Traditional Chinese (`zh-HK`) as the canonical language because they are primarily intended for owner and human review. English translations are development aids unless the document explicitly declares a different canonical language. External source material may remain in its original language, but any repository-authored interpretation must state its own canonical language.

## What belongs here

Examples include:

- product and editorial principles or charters;
- legal, regulatory, copyright, privacy and compliance notes;
- source assessments and research notes;
- market, audience and competitor research;
- business model, company-formation and registration research;
- prospectus, positioning and historical product material;
- external articles, summaries and retained decision context;
- detailed options that may later inform a spec or plan.

Use subject subfolders such as [`editorial/`](editorial/), `legal/`, `business/` or `research/` when there is real content to place in them. Do not create empty structure in advance.

## Authority

Reference material is non-normative.

- It may explain why a future requirement is desirable.
- It may be cited by a spec.
- It may be incomplete, jurisdiction-specific, provisional or out of date.
- It does not authorise code changes, model behaviour, automated publication rules or release decisions on its own.
- A spec that adopts part of a reference document must state the adopted requirement explicitly.

## Language and translation metadata

A translated reference set must identify:

- the canonical language and file;
- the translation language and purpose;
- which version controls if they differ;
- the date or version last synchronised; and
- any known translation gap.

A translation must not introduce a new policy decision. If a development agent finds a mismatch, it must use the canonical version and surface the mismatch for correction.

## Recommended metadata

```markdown
# <Reference title>

**Status:** Working | Reviewed | Historical  
**Type:** Editorial | Legal | Business | Research | Other  
**Owner:** <name or role>  
**Canonical language:** zh-HK | <declared exception>  
**Translation status:** <canonical | development translation | none>  
**As of:** YYYY-MM-DD  
**Last reviewed:** YYYY-MM-DD  
**Related specs or plans:** <links or none>  
**Sources:** <links or citations where applicable>

> This is non-normative reference material. It does not create an implementation requirement unless an accepted spec explicitly adopts one.
```

For legal or regulatory material, record the jurisdiction and effective or access date. Treat it as research rather than legal advice unless it has been formally reviewed and labelled accordingly.

## Public-repository safety

This repository is public. Do not commit secrets, identity documents, personal addresses, bank or payment details, signed contracts, unpublished legal advice, confidential incorporation records, private correspondence or other sensitive company or personal data.

Keep only material that is safe to publish, or a redacted summary that points authorised maintainers to an approved secure storage location. Never place credentials or private storage links containing access tokens in a reference document.
