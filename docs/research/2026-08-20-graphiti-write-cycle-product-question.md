# Should Graphiti ingest the source corpus on its own schedule?

**Status:** Research / product question

**Canonical language:** English

**Issue:** [#722](https://github.com/fol2/newsroom/issues/722) (`wayfinder:grilling`, `ready-for-human`)

**Code base discussed:** `main` @ `46d7d67` (#721)

**Closed maps:** [#690](https://github.com/fol2/newsroom/issues/690), spec [#707](https://github.com/fol2/newsroom/issues/707)

**Host freeze:** [2026-08-20-unpublished-beta-store-snapshot](2026-08-20-unpublished-beta-store-snapshot/)

**Implementation authority:** None. Do not change Control Plane logic until #722 records a PM answer.

## Why this exists

SLT and the owner challenged the implementing agent's explanation of Graphiti. The agent had framed Graphiti as if it served **this unpublished draft** (or the next one). The product correction is: Graphiti builds GraphRAG across the **entire source corpus** (source-to-source connections). Linking that graph to **our article** is a bonus.

That correction may change Control Plane logic. This note freezes the discussion against merged `main`, with a snapshot git can hold because live SQLite/Neo4j are not in the repository.

## Decision required

Record the choice on #722.

1. **Keep current.** Graphiti remains a step *after* up to five CONT writes in the same unpublished cycle; at most one extract per cycle; then sleep 300s.
2. **Decouple ingest.** Graphiti walks Evidence Packages on its own schedule to cover the corpus. Writers stay evidence-only and do not wait on Graphiti.
3. **Decouple ingest, and later add admitted retrieval as drafting context.** Same as (2), plus a *separate* later slice in which writers may see **admitted** GraphRAG context. Raw, unadmitted Graphiti proposals must not enter the CONT prompt.

## What stakeholders asked

1. Why this newsroom needs GraphRAG and Graphiti at product level (not “how the adapter works”).
2. Why Graphiti runs after the draft, if SLT expects it as drafting context that would raise quality and cut redundancy.
3. After a confused agent reply: Graphiti connects **sources**, for the **whole database**, not one topic / one article. Article connection is a bonus. Explain again at PM level.
4. How Graphiti is scheduled; what it costs; why writers can disregard the GraphRAG connection. True examples, not hypotheticals.

## What the agent explained (including errors)

**Product purpose (kept).** GraphRAG is the newsroom's governed memory of the source world: same event across outlets, entity identity, developments over time. Neo4j holds graph state; Graphiti is the proposal-only extractor. The CONT writer is a different agent and writes original Hong Kong Traditional Chinese from the Evidence Package. Graph-less production is not the Accepted target (`GRAG-050`, ADR 0005).

**Error.** The agent answered “after the draft” with a two-clock story about *this* package versus *the next article*. That still made Graphiti sound article-centric.

**Correction the owner required.** Graphiti's job is corpus GraphRAG. The write cycle is a separate product line. Running extract after mint is **scheduling**, not the product definition.

**Schedule/cost/examples (kept, aligned to `main` + host freeze).**

- LaunchAgent `com.jamesto.newsroom-control-plane` runs `hermes_control_plane.py serve --interval 300`. The 300s is idle **after a finished cycle**, not “one Graphiti extract every five minutes”.
- Each cycle: intake → up to **5** writes → at most **1** Graphiti extract (`cycle.py`).
- Graphiti spend: OpenRouter `gpt-5-mini` + `text-embedding-3-large`, OD-011 **£250** cash ceiling, not pre-spent, one `GRAPHITI_SPEND_RESERVE` row. Writer Grok/cursor-agent subscription is not debited from that ceiling. Token invoices are not in the unpublished ledger.
- Writer prompt is 題旨 + 證據 only (`writer.py`). No retrieval. `CONT-001` plus unadmitted proposals (`GRAG-020` / `GRAG-023`) are why the writer **must not** treat Graphiti output as copy context today.
- Freeze counts: **176** unpublished payloads vs **3** COMPLETE Graphiti attempts; disposable workspace **14** nodes / **18** edges / **4** episodes. Covering ~295 candidates at one extract per write-cycle is slow **by construction**.

**True examples in the freeze.**

- Graph: `HK-04` relates to Legislative Council question 7 and the Technology and Living curriculum. Hub still has many other standalone HK-04 LegCo/education titles written without that graph.
- Many Parenting Smart Net payloads exist as separate reports; the freeze does not show that cluster ingested into the workspace.
- Graph: Hong Kong Observatory / Strong Monsoon Signal, and separately RAD-02 / Simon King / United Kingdom. Writers continued to mint UK-05 exam copy from evidence, not from that weather graph.

## What `main` already merged (do not re-litigate as missing code)

|#|Change|
|---|---|
|#717|Real EVALUATION Graphiti executor|
|#718|Typed ADMIT/REJECT/HOLD before projector writes|
|#719|Reject planning-residue titles/bodies|
|#720|EVALUATION flag on; spend reserve; ≤1 extract/cycle|
|#721|OpenRouter `json_object` so extract can COMPLETE|

No unpublished write depends on Graphiti succeeding (`GRAG-045`). Destination copy on newsroom-hub is the CONT path.

## Specs that bound any later logic change

- `GRAG-020` / `021` / `023` — proposals, disposable workspace, explicit admission.
- `GRAG-040` — GraphRAG is context; it does not allocate Event Hypothesis or Candidate.
- `GRAG-045` — collection may continue during graph lag.
- `CONT-001` — writer input is the approved Evidence Package (and only later, if the PM chooses (3), other **admitted** permitted context).
- Out of scope here: Increment 11 / 11R, AUTO_PUBLISH, public TargetOperation, silent ADMIT, PRODUCTION.
