# Database architecture expertise review

**Status:** Reviewed reference
**Type:** External expertise commentary
**Owner:** Product owner
**Canonical language:** Hong Kong Traditional Chinese (`zh-HK`)
**Translation status:** None
**As of:** 2026-07-15
**Related research:** [`2026-07-15-local-agentic-graph-rag-database-options.md`](2026-07-15-local-agentic-graph-rag-database-options.md)
**Related decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) (`Proposed`), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md) (`Proposed`)

> This article is retained as non-normative expert commentary. Adopted constraints are restated in UK-English specifications or ADRs; the article does not authorise implementation on its own. References to Discord illustrate the legacy system or a generic secondary public target only. Discord and OpenClaw are not target-platform dependencies.
>
> **Adopted interpretation:** references below to a first phase or to doing one item before another describe authority priority and engineering dependency, not two target architectures. The adopted plan defines publication, serving and governed knowledge projections against one canonical contract from inception and has one production-activation gate.

## 整體判斷

我贊成你第一階段嘅核心決定，而且會正式寫成 ADR：

> **Long-lived SQLite editorial ledger 同 content-addressed source object store 係權威來源；Graph、vector 同 full-text index 全部係可以重建嘅 projection。**

呢個唔只係保守做法，而係同 publication requirements 天然一致。你份 GraphRAG research 已經正確分開 database、knowledge graph、retrieval 同 agent orchestration；publication spec 又要求 immutable versions、完整 lineage、append-only／tamper-evident audit，以及 audit 寫入失敗時必須阻止 publication。將 probabilistic graph extraction 放喺呢啲權威要求之上，風險會太高。

我會作一個重要修正：

```text
唔應該係：

Graphiti → Graph → Publication truth

而應該係：

Graphiti extraction
        ↓
Relation / Claim Proposals
        ↓
Deterministic validation or authorised admission
        ↓
SQLite editorial ledger
        ↓
Approved graph projection
```

呢個箭嘴方向非常重要。

---

## Graph database decision：我同意 Neo4j + Graphiti 做 POC，但唔好當成 production commitment

Neo4j Community + Graphiti 係合理嘅 compatibility-first baseline。你會最快知道 temporal graph、hybrid retrieval、GraphRAG tooling 同 Hermes tool orchestration實際上有冇價值。Neo4j Community 嘅單機、backup、安全控制限制亦已經喺 research 裏面列清楚；對本地 Mac mini POC 可以接受，但係唔應該因為 POC 順利就自動升格成 production 決定。

我反而唔建議第一輪同時 implementation 四個 database。現階段最大風險唔係 graph engine throughput，而係：

* ontology 是否正確；
* entity identity resolution 是否可靠；
* temporal semantics 是否足夠；
* relationship admission 是否安全；
* graph retrieval 對新聞判斷有冇真實 precision／recall 增益。

先用 Neo4j + Graphiti驗證呢啲。只有當 server footprint、licence、backup 或 deployment 成為實際問題，先用同一 corpus 跑 LadybugDB challenger。否則會將時間花喺 adapter，而唔係驗證 architecture。

### 1. 唔好將有爭議嘅事實直接表示成 ordinary edge

例如：

```text
(:Story)-[:DEVELOPMENT_OF]->(:Story)
(:Person)-[:RESPONSIBLE_FOR]->(:Event)
```

如果 relationship 需要來源、時間、驗證、反駁或者多個 source 支持，單一 edge properties 好快會變得難以管理。

我會將有 editorial meaning 嘅 relationship reify 成 assertion：

```text
(:RelationAssertion {
  assertion_id,
  predicate,
  trust_state,
  confidence,
  valid_from,
  valid_to,
  recorded_at,
  invalidated_at
})
  -[:SUBJECT]->(:Entity)
  -[:OBJECT]->(:Entity)
  -[:SUPPORTED_BY]->(:SourcePassage)
  -[:PROPOSED_BY]->(:ExtractionRun)
  -[:ADMITTED_BY]->(:Decision)
```

只有 identity、containment、version ownership 呢類 deterministic relationship，先直接做 edge，例如：

```text
(:Story)-[:HAS_VERSION]->(:ArticleVersion)
(:SourceDocument)-[:HAS_PASSAGE]->(:SourcePassage)
(:PublicationBundle)-[:CONTAINS_VERSION]->(:ArticleVersion)
```

尤其唔建議用同一個 `DEVELOPMENT_OF` edge，再靠 `{status: "PROPOSED"}` 區分。某一條 query 遺漏 status filter，就可能將 proposal 當成批准事實。Proposal 最好係獨立 node 或獨立 relationship type。

### 2. `valid_from`／`valid_to` 唔夠，Newsroom 需要明確時間語義

新聞系統至少有四種不同時間：

```text
source_published_at     原始來源幾時發布
observed_at             Newsroom 幾時取得或觀察到
valid_from / valid_to   呢個 assertion 被指稱喺現實世界幾時有效
recorded_at             Newsroom 幾時將佢寫入權威 ledger
```

另外通常仲需要：

```text
admitted_at
invalidated_at
source_revised_at
first_publication_at
target_acknowledged_at
```

例如政府喺星期三修訂一個星期一生效嘅政策，而 Newsroom 星期四先發現。將所有時間塞入一對 `valid_from`／`valid_to`，之後做 correction、timeline 或「當時我哋知道甚麼」查詢時一定出問題。

Graphiti 嘅 temporal model可以提供好好嘅基礎，但 Newsroom 必須自己定義以上語義，唔可以直接將 framework field 名當成 editorial contract。

### 3. 建議明確分成三個 trust layers

```text
OBSERVED
原始來源確實出現過嘅文字、metadata、entity mention

PROPOSED
模型推斷嘅 entity resolution、claim、relationship 或 contradiction

APPROVED
通過 deterministic rule、validator 或 authorised decision 嘅資料
```

`confidence=0.98` 唔等於 `APPROVED`。Confidence 係模型判斷；approval 係 governance decision，兩者必須分開。

Hermes 做 research 可以查 `OBSERVED + PROPOSED + APPROVED`，但 context pack 必須標示 trust scope。Publication validator 原則上只能依賴 `OBSERVED + APPROVED`。

### 4. Graph projection 要有正式 replay contract

唔好做 relational write 加 graph write 嘅 dual-write。SQLite transaction 應該同時寫：

```text
authoritative record
projection outbox entry
monotonic ledger sequence
```

Graph projector 之後以 at-least-once、idempotent 方式消費 outbox：

```text
ledger_seq
projector_version
ontology_version
projection_generation
source_content_hash
```

每次 query 應該可以返回：

```json
{
  "projection_sequence": 184233,
  "projector_version": "3.2.0",
  "ontology_version": "newsroom-kg-5",
  "as_of": "2026-07-15T13:45:00Z"
}
```

咁 Hermes 先知道 graph 有幾新。對普通 research，少量 lag 可以接受；對 correction impact 或 source revision，projection 過期就應該 fail closed，或者改用 authoritative SQL indexes。

Rebuild 最好用 blue/green generation：

```text
graph_generation_17  ← current
graph_generation_18  ← rebuilding and validating

validate counts, hashes, invariants
             ↓
atomically switch active generation
```

「Rebuildable」亦唔等於「完全唔需要 snapshot」。Ledger 同 object store 係 recovery authority；graph snapshot 可以用來改善 recovery time，但唔係唯一 backup。

### 5. Agent 唔應該直接寫或者自由生成 Cypher

Read-only credentials 只解決 mutation，未解決 expensive traversal、data exfiltration、query explosion 同 accidental trust mixing。

我會畀 Hermes named tools，而唔係一個 generic `run_cypher`：

```text
find_related_story_candidates(...)
get_event_timeline(...)
find_claims_supported_by_source(...)
find_versions_using_claim(...)
find_source_revision_impact(...)
find_conflicting_assertions(...)
get_story_provenance(...)
```

每個 tool 固定：

* allow-listed node／relationship types；
* maximum depth；
* maximum fan-out；
* date window；
* result count；
* timeout；
* trust scope；
* required provenance fields。

Graph 只返回 candidate IDs、paths 同 provenance references；完整 passage、audit decision 同 immutable content應該再由 ledger/object store hydrate。咁 graph query result唔會悄悄變成 publication evidence。

另外，agentic planning 適合 research 同 drafting；final validation 應該執行一套 versioned、固定嘅 evidence checklist，而唔係由 Hermes 自由決定今次查唔查某個 critical source。

### 6. Identity resolution 應該成為一級 domain，而唔係 ingestion side effect

Newsroom Graph 最大嘅錯誤來源，好可能唔係 traversal，而係錯誤 merge：

* 同名人物；
* 公司改名；
* 香港／英國中英文異名；
* 法案、政策、諮詢文件名稱接近；
* 同一案件有唔同新聞寫法；
* wire copy 重複但唔係獨立 corroboration。

建議加入：

```text
EntityMention
CanonicalEntity
Alias
EntityResolutionProposal
EntityResolutionDecision
MergeDecision
SplitDecision
```

任何 entity merge 都需要保留 prior IDs、reason、evidence 同 reversal path。Embedding similarity只可以產生 candidate，唔可以直接 canonicalise。

---

## Graph 同 publication lifecycle 之間嘅正確邊界

Graph 最有價值嘅地方係：

* 建議 `same_event`／`development_of`／`same_process_as`；
* 發現同一 source revision 可能影響邊啲 claims；
* 找出長期 policy、case 或 bill 嘅 timeline；
* 找出 archive reassessment candidates；
* 發現 indirect contradiction 或 shared original source。

但 Graph 唔應該成為以下事情嘅唯一依據：

* 某個 public version實際包含咗邊個 claim；
* 某個錯誤出現喺邊個 feed card、notification 或 Discord message；
* 哪些 target 必須 correction；
* 哪個 bundle獲准發布；
* public target目前應該顯示甚麼。

呢啲 critical mappings 應該喺 SQLite有 deterministic tables：

```text
story_version_claim
claim_evidence
surface_payload_claim
story_relation
publication_bundle_surface
target_publication
```

Graph 可以擴大 investigation blast radius，但 correction workflow最基本嘅影響範圍，應該靠 publication-time manifest準確計到。

---

# Publication lifecycle：editorial requirements 已經好強，但工程上仲欠一個 executable model

你份 lifecycle spec 對 immutable version、target mapping、correction propagation、withdrawal、archive reassessment、append-only audit、partial failure 同 reconciliation定義得好完整。最大缺口係：目前主要係 normative product requirements，仲未變成 database invariants、state transitions 同 worker semantics。

## 1. 唔好用一個 `status` column 表達所有狀態

一篇文章可以同時：

* 仍然公開可見；
* 已經 corrected；
* 已被另一篇 policy update supersede；
* app target成功；
* Discord target retry中；
* notification無法修改，只能發 correction。

所以 `PUBLISHED | CORRECTED | WITHDRAWN | REMOVED | SUPERSEDED` 唔應該係單一 mutually exclusive enum。

我會拆成幾條 state axes：

```text
Editorial decision
DRAFT / VALIDATING / APPROVED / HELD / REJECTED

Version disposition
CURRENT / REPLACED_BY_CORRECTION / SUPERSEDED / WITHDRAWN

Public visibility
VISIBLE / TOMBSTONE_ONLY / DEINDEXED / REMOVED

Target delivery
PENDING / IN_FLIGHT / ACKNOWLEDGED /
FAILED_RETRYABLE / FAILED_FINAL / DRIFTED

Correction state
NONE / NON_SUBSTANTIVE / MATERIAL / SOURCE_REVISION
```

`SUPERSEDED` 多數係 relationship，而唔係完全取代 `PUBLISHED`。一篇舊 policy article可以仍然公開，同時有 reader-visible superseded banner。

`CORRECTED` 亦唔應該修改舊 version狀態之後消失。應該係：

```text
Version 4: REPLACED_BY_CORRECTION
                 |
                 └── corrected_by → Version 5

Version 5: CURRENT
```

## 2. Publication 應該係 saga，而唔係 distributed transaction

你唔可能將 SQLite、app server、Discord、push provider 同 CDN放入同一個 ACID transaction。

正確流程係：

```text
BEGIN SQLite TRANSACTION

1. persist immutable story version
2. persist evidence package reference
3. persist validation results
4. persist publication decision
5. persist immutable publication bundle
6. persist one outbox command per target

COMMIT
```

只有 commit 成功後，target workers先可以執行 public action。咁先真正實作 `AUDIT-005`：「audit record失敗必須阻止 publication」。

之後：

```text
outbox worker
   ↓
target adapter
   ↓
target acknowledgement / failure
   ↓
publication_attempt
   ↓
desired-vs-observed reconciliation
```

外部 publish成功但本地未寫到 acknowledgement係必然會發生嘅 failure mode。因此 target adapter必須支援 idempotency或者 external correlation lookup，不能假設「retry 同一個 request」唔會 duplicate。

建議 idempotency key：

```text
sha256(
  story_id +
  version_id +
  bundle_id +
  target_id +
  operation_type
)
```

Acceptance criterion中「一個 target成功、一個失敗，retry不可 duplicate成功嗰個」實際上就需要呢個設計。

## 3. Target-specific rendering 必須喺 approval 前完成

唔好批准一篇 generic article，之後由 Discord adapter臨場截短、改 headline、生成摘要或重排 sources。

Publication bundle應該已經包含所有經驗證、content-addressed payload：

```text
web_article_payload
feed_card_payload
discord_payload
notification_payload
public_source_list
asset_derivatives
correction_banner
related_story_summary
```

每個 payload有獨立 hash。Adapter只負責 transport、target-native metadata 同 acknowledgement；唔應該做 editorial generation，更唔應該喺 adapter內叫 LLM。

若 target payload改咗一個字，就應該產生新 payload version／bundle reference，而唔係 audit record仍然指向原本批准嘅內容。

## 4. Publication time 要指定 canonical clock

Multi-target publication有 race condition：

```text
12:00:01 Discord成功
12:00:03 app成功
12:00:05 notification成功
```

`first_publication_at` 究竟係邊個？

需要指定一個 canonical public target，例如 app/article service。建議分開記錄：

```text
decision_at
bundle_committed_at
dispatch_started_at
canonical_first_publication_at
target_acknowledged_at
canonical_latest_update_at
```

Feed ordering使用 canonical first-publication time，再用 stable story ID做 tie-breaker。唔好用 worker dispatch time，亦唔好因 correction將文章推返上 feed；呢個先符合 lifecycle spec所要求按 first publication排序。

## 5. Correction propagation 要靠 claim-to-surface manifest

每次生成 publication bundle時，應該記錄：

```text
claim_id
story_version_id
surface_payload_id
text span / structured field
target_id
materiality
```

例如同一個錯誤數字可能出現於：

* article paragraph 3；
* headline；
* feed card；
* Discord embed；
* push notification；
* related-story summary。

當 source revision或者 claim invalidation出現時，可以先用 SQL準確列出直接影響：

```text
claim → payload → target publication
```

再用 graph搜尋可能嘅 indirect dependencies。

呢個比事後用 semantic search估計「邊啲地方可能引用過」可靠得多，亦係實現 cross-surface consistency嘅必要條件。

Notification尤其要分開處理：已發出嘅 push通常唔可以修改，所以 correction action係新 notification，而唔係「更新原 notification」。

## 6. Reconciliation 應該比較 desired state 同 observed state

唔應該只問「target item存在嗎」。應該比較：

```text
Desired:
  version_id
  payload_hash
  visibility
  correction marker
  relationship links

Observed:
  target-native ID
  observed payload digest
  observed visibility
  target timestamp
```

Drift可以分類做：

```text
MISSING
DUPLICATED
STALE_VERSION
WRONG_PAYLOAD
UNAPPLIED_CORRECTION
ORPHANED
UNEXPECTEDLY_REMOVED
UNAUTHORISED_MUTATION
```

每個 target adapter亦要聲明 capability：

```text
can_edit
can_delete
can_tombstone
can_query_by_idempotency_key
can_list_items
can_observe_payload
can_issue_follow_up
```

只有咁，withdrawal、removal、correction同 reconciliation先可以有一致但 target-aware 嘅行為。

另外需要正式定義「correction workflow completes」：

> 所有 required targets已達到符合其 capability嘅 corrected desired state；未能處理嘅 target已有 recorded exception、retry state或 authorised limitation。

否則 LIFE-055 嘅「workflow completes」會變成模糊條件。

## 7. Audit 要保存當時輸入輸出，唔只係版本號

記錄 model、prompt、policy同 software version係必要，但唔足以重現 stochastic model output。

應該保存或者 content-address：

* exact input context pack；
* exact source passage IDs；
* prompt/template snapshot；
* model output；
* structured extraction output；
* validator results；
* repair attempts；
* final accepted payload；
* controller decision。

「Reconstruct why」唔應該理解為重新跑模型，希望得到相同結果；而係可以重播當時保存嘅證據、輸出同 decision chain。

SQLite本身亦唔係自動 tamper-evident。初期可以為 audit events建立 hash chain：

```text
event_hash = SHA256(
  previous_event_hash +
  canonical_event_payload
)
```

每日再產生 signed audit root。Hash chain唔可以阻止一個有完整 admin access嘅人重寫整個 database，但可以提高 accidental alteration同普通 tampering嘅可檢測性。

## 8. SQLite 可以做第一階段 authority，但需要清楚操作約束

對單機、有限 writer嘅 Newsroom，SQLite係合理選擇。工程上應明確：

```text
one logical command writer
WAL mode
foreign_keys = ON
busy timeout
durability policy
online backup procedure
integrity checks
schema migration history
restore drills
```

Object store則需要：

```text
write temp file
fsync
verify content hash
atomic rename
commit ledger reference
```

避免 ledger指向一個未完整寫入嘅 source object。

亦應該預先定義 SQLite-to-PostgreSQL migration trigger，而唔係等出事先討論，例如：

* 需要多 host writers；
* newsroom operator同 workers分散部署；
* single-node RPO/RTO已不可接受；
* write contention持續超出目標；
* backup／restore窗口不合要求。

---

# 我建議嘅整體工程架構

```text
                    UNTRUSTED INPUTS
 Sources / feeds / reader leads / external updates
                         |
                         v
          Content-addressed source object store
                         |
                         v
           SQLite authoritative editorial ledger
       source versions / passages / claims / decisions
                         |
          +--------------+----------------+
          |                               |
          | transactional graph outbox    | validation and approval
          v                               v
   Idempotent graph projector      Immutable story version
          |                               |
          v                               v
 Temporal KG + FTS + vector       Immutable publication bundle
          |                               |
          v                     atomic audit + publication outbox
 Bounded read-only tools                    |
          |                                 v
          +-----------> Hermes      Target-specific workers
                                             |
                              +--------------+-------------+
                              |              |             |
                             App          Discord       Notifications
                              |              |             |
                              +--------------+-------------+
                                             |
                                  acknowledgement records
                                             |
                                  reconciliation workers
                                             |
                                  lifecycle/correction actions
```

Public server只接收已批准、最好有 signature嘅 publication bundle；唔需要 raw source corpus、proposed relationships、private complaints、reviewer notes或者完整 knowledge graph。

Graph outage原則上唔應阻止普通 publication，前提係 required evidence、claim mapping同 validation全部已經喺 authoritative ledger完成。涉及 source-revision blast radius或者 archive reassessment嘅工作，如果 graph過期，可以 hold investigation，但唔應以 stale graph自動作結論。

---

# 建議直接加落規格嘅工程條文

以下可以變成獨立 architecture／publication engineering spec：

```text
ARCH-001 — Authoritative boundary.
The editorial ledger and governed source object store MUST be the
authoritative record. Graph, vector and full-text stores MUST be treated
as rebuildable projections unless a later accepted ADR explicitly changes
that boundary.

ARCH-002 — Proposal admission.
A model-extracted claim, relationship or entity resolution MUST enter as
a proposal and MUST NOT become an approved domain relationship until an
admission decision has been persisted.

ARCH-003 — Temporal semantics.
The system MUST distinguish source publication time, observation time,
asserted validity time and ledger transaction time.

ARCH-004 — Replayable projection.
Every graph mutation MUST be reproducible from an ordered authoritative
ledger record using a versioned, idempotent projector.

ARCH-005 — Projection watermark.
Every graph retrieval result MUST identify the projection sequence,
projector version and effective as-of time used to produce it.

RETR-001 — Bounded retrieval.
Agent retrieval MUST use allow-listed read-only operations with limits on
relationship types, depth, fan-out, time range, result count and execution
time.

PUBENG-001 — Atomic decision and enqueue.
The publication decision, required audit record, immutable bundle and
target outbox commands MUST commit in one authoritative transaction.

PUBENG-002 — Immutable target payload.
All editorially meaningful target-specific payloads MUST be generated,
validated and hashed before dispatch. Target adapters MUST NOT generate or
rewrite editorial content.

PUBENG-003 — Idempotent public action.
Every target operation MUST carry a stable idempotency key and MUST be
retryable without duplicating an already successful public action.

PUBENG-004 — Canonical publication clock.
The product MUST define the canonical target whose acknowledgement sets
first-publication and latest-update times, while retaining separate
timestamps for every target.

CORR-001 — Claim-to-surface manifest.
Every publication bundle MUST record which approved claims occur in each
controlled public payload so that correction impact can be determined
without semantic inference.

OPS-001 — Desired-state reconciliation.
The system MUST compare intended target state with observed target state
and classify missing, duplicate, stale, uncorrected and orphaned items.

OPS-002 — Degraded operation.
The system MUST define which editorial and publication actions may proceed
when graph, embedding, target or reconciliation services are unavailable
or stale.
```

---

## 最終建議次序

第一，正式批准「SQLite ledger + object store係 authority，graph係 projection」嘅 ADR。

第二，先完成 publication state model、immutable bundle、transactional outbox、idempotent target adapter同 reconciliation。呢啲係 reader-facing correctness基礎，而且完全唔依賴 Graph database。

第三，用 Neo4j + Graphiti建立細 corpus POC，但 Graphiti只產生 proposals；批准資料由 ledger projector寫返入 approved graph。

第四，優先驗證三個具體 graph use cases，而唔係 generic chat：

1. `same_event`／`development_of` related-story precision；
2. source revision對 claims同 stories嘅影響發現；
3. long-running case／policy timeline retrieval。

我最強烈嘅意見係：**Graph 應該增強 Newsroom 對關係同歷史嘅理解，但 publication correctness必須喺冇 Graph 都可以重建、解釋、retry同 reconcile。** 呢條界線守得住，之後無論最後係 Neo4j、LadybugDB或者另一個 engine，都唔會綁死整個 newsroom。
