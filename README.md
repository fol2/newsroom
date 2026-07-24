# Newsroom

Newsroom contains both the accepted authority/GraphRAG foundation and the older
OpenClaw Discord newsroom runtime. They are not the same product boundary.

## Current Repository Status

Increment 1 is complete. The merged foundation proves one synthetic,
deterministic path through authenticated command authority, the SQLite ledger,
governed-object hydration, an authority-selected Neo4j structural projection,
and SQLite-authoritative Candidate admission.

The foundation establishes these rules:

- SQLite ledger records, retained contracts, governed objects, Retrieval Context
  records, and Candidate tables are authoritative.
- Neo4j is a disposable, rebuildable projection. It never creates or repairs
  ledger, governed-object, or Candidate authority.
- GraphRAG is mandatory for qualifying production, evaluation, and complete
  live-shadow profiles; a missing, fake, disabled, stale, or graph-free variant
  fails closed.
- Models, extractors, Graphiti, similarity, and ranking may propose. Only
  deterministic or authorised controllers may commit authority.
- Graph loss is recovered from SQLite and governed-object authority, and
  deletion or tombstone state cannot be resurrected by rebuild.

This is a foundation proof, not production admission. It authorises no live
source access, Graphiti/model/embedding execution, publication, product shadow,
canary, production activation, spending, or public effect.

Start with these records:

- [Increment 1C operating and rollback guide](docs/operations/increment-1c-integrated-foundation.md)
- [Neo4j B2 qualification guide](docs/operations/neo4j-b2-qualification.md)
- [Neo4j B3 rebuild and promotion guide](docs/operations/neo4j-b3-rebuild-promotion.md)
- [SDLC v2 specification](docs/specs/sdlc/high-performance-evidence-sdlc.md)
- [SDLC v2 owner acceptance record](docs/specs/sdlc/2026-07-22-sdlc-v2-owner-acceptance.md)
- [Machine gate contract](.sdlc/gates.toml)

## Legacy OpenClaw Runtime

The older runtime remains in the repository as implementation and migration
material. It ingests links, clusters them with an LLM, writes stories, and can
publish to Discord through the OpenClaw Gateway. Its existence does not make it
the accepted new authority architecture or a production-admitted path.

The remainder of this README documents that legacy runtime and its local
development commands.

## Legacy Architecture Overview

The legacy OpenClaw runtime transforms raw news links into clustered stories and
Discord posts. It has four stages:

1. **News pool ingestion** -- Multiple source adapters (Brave News API, GDELT
   DOC 2.0, curated RSS/Atom feeds) fetch links and upsert them into a local
   SQLite news pool database with deduplication and TTL expiry.
2. **Clustering and deduplication** -- An LLM-powered event manager groups links
   into events. Token-based and cross-lingual entity matching provides a fast
   pre-filter before LLM classification, followed by a merge pass.
3. **LLM story writing** -- Selected events are sent to Gemini with
   category-aware prompt routing. Structured output is validated and repaired.
4. **Discord publishing** -- Finished stories can be sent to Discord through
   the OpenClaw Gateway with images, charts, and source attribution.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) -- Detailed legacy runtime architecture and
  component internals
- [AGENTS.md](AGENTS.md) -- Legacy cron agent system, planner/runner architecture,
  and job formats
- [PROMPTS.md](PROMPTS.md) -- Prompt templates, category routing, and validators
- [CONTRIBUTING.md](CONTRIBUTING.md) -- Development guidance
- [docs/evaluation/clustering_eval_dataset_v1.md](docs/evaluation/clustering_eval_dataset_v1.md)
  -- Labelled clustering evaluation dataset and replay workflow

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management
- **OpenClaw Gateway**, only for the legacy Discord publishing path. The Gateway
  is a separate service and is not included in this repository. Local dry-run
  development does not require it.

## Installation

```bash
git clone https://github.com/fol2/newsroom.git
cd newsroom
uv sync --dev --locked
```

This creates a virtual environment and installs the locked development
dependencies. To include optional chart dependencies, run
`uv sync --extra charts --locked`.

## Legacy Runtime Configuration

Copy `.env.example` to `.env` and provide only the credentials needed for the
legacy command being exercised:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Legacy LLM path | Google Gemini API key for clustering and story writing. |
| `BRAVE_SEARCH_API_KEYS` | Legacy Brave ingestion | Multiple Brave Search API keys, comma/newline separated; supports `label:key`. |
| `BRAVE_SEARCH_API_KEY` | Legacy fallback | Single Brave Search API key when the multi-key variable is unset. |
| `OPENCLAW_GATEWAY_TOKEN` | Legacy publishing only | Bearer token for the OpenClaw Gateway. |
| `OPENCLAW_HOME` | No | Override the OpenClaw home directory. |
| `OPENCLAW_GATEWAY_HTTP_URL` | No | Gateway endpoint; defaults to `http://127.0.0.1:3000`. |
| `GEMINI_PROFILE_ORDER` | No | Gemini CLI OAuth profile order. |
| `GEMINI_AUTH_PROFILES` | No | Path to `auth-profiles.json`. |
| `GEMINI_API_KEY_ONLY_UNTIL` | No | Timestamp controlling API-key/OAuth preference. |
| `NANO_BANANA_SCRIPT` | No | Optional image-generation script invoked through `uv run`. |

Credentials are capabilities. Do not place production credentials in tests,
fixtures, documentation, artifacts, or the accepted foundation proof.

### RSS Feeds

To override the built-in legacy RSS/Atom feed list:

```bash
cp newsroom/examples/rss_feeds.example.yaml newsroom/rss_feeds.yaml
```

## Legacy Runtime Quick Start

Use a disposable database and dry-run mode. These commands exercise the legacy
runtime; they do not constitute foundation qualification or production
admission.

```bash
# 1. Populate a disposable news pool.
uv run python scripts/news_pool_update.py \
  --db data/newsroom/news_pool.sandbox.sqlite3

# 2. Cluster and select hourly inputs.
uv run python scripts/newsroom_hourly_inputs.py \
  --db data/newsroom/news_pool.sandbox.sqlite3

# 3. Run the story writer without Discord publication.
uv run python scripts/newsroom_runner.py --dry-run
```

## Scripts Reference

| Script | Description |
|---|---|
| `newsroom_runner.py` | Legacy story-job runner and optional Discord publisher; supports `--dry-run`. |
| `newsroom_hourly_inputs.py` | Legacy hourly planner and clustering path. |
| `newsroom_daily_inputs.py` | Legacy daily planner with category balancing. |
| `newsroom_write_run_job.py` | Creates a legacy story job JSON file. |
| `news_pool_update.py` | Fetches Brave News results into the legacy pool. |
| `gdelt_pool_update.py` | Fetches GDELT DOC 2.0 results into the legacy pool. |
| `rss_pool_update.py` | Fetches curated RSS/Atom results into the legacy pool. |
| `news_pool_status.py` | Displays pool and clustering diagnostics. |
| `newsroom_clustering_decisions.py` | Inspects clustering decision evidence. |
| `news_pool_dump_jsonl.py` | Dumps a consistent pool snapshot for sandbox rebuilds. |
| `news_pool_restore_jsonl.py` | Restores a JSONL dump into a fresh SQLite database. |
| `build_clustering_eval_dataset.py` | Builds the labelled clustering evaluation dataset. |
| `replay_clustering_eval_dataset.py` | Replays labelled rows through parser logic. |
| `eval_clustering_metrics.py` | Enforces clustering quality regression thresholds. |

All scripts live in `scripts/`.

## DB Sandbox Rebuild

Do not experiment against a production or operator-owned SQLite database. Export
and restore a snapshot into a disposable path:

```bash
uv run python scripts/news_pool_dump_jsonl.py \
  --db data/newsroom/news_pool.sqlite3 \
  --out-dir data/newsroom/db_dumps/$(date -u +%Y%m%dT%H%M%SZ)

uv run python scripts/news_pool_restore_jsonl.py \
  --dump-dir data/newsroom/db_dumps/<TIMESTAMP> \
  --db data/newsroom/news_pool.sandbox.sqlite3
```

The dump defaults to recent links and events, including referenced parent
events. Restore refuses to overwrite unless explicitly authorised.

## Testing and Evidence

Run the locked deterministic suite:

```bash
uv lock --check
uv sync --dev --locked
uv run --no-sync python -m pytest -q newsroom/tests
```

Run the clustering regression gate:

```bash
uv run --no-sync python scripts/eval_clustering_metrics.py \
  --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \
  --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \
  --fail-on-regression
```

Changes to authority, persistence, Neo4j integration, workflows, or SDLC
contracts are routed through the repository-owned risk classifier and may
require the authenticated actual-service lane. See `.sdlc/gates.toml` rather
than weakening or bypassing the selected evidence.

## Key Areas

| Area | Purpose |
|---|---|
| `newsroom/authority/` | Authenticated commands, SQLite event authority, governed objects, and projection authority. |
| `newsroom/projection/` | Structural ontology, mappings, projection contracts, and Neo4j adapter. |
| `newsroom/integrated/` | Synthetic authority-to-GraphRAG-to-Candidate foundation proof. |
| `scripts/sdlc/` | Exact-tree routing, watchdog, evidence, transport, telemetry, and decision tooling. |
| `.github/workflows/evidence.yml` | Permanent always-reporting SDLC evidence shadow. |
| `newsroom/event_manager.py` | Legacy event-centric LLM clustering. |
| `newsroom/news_pool_db.py` | Legacy news-pool SQLite storage. |
| `newsroom/runner.py` | Legacy story-writing and publishing runtime. |
| `newsroom/gateway_client.py` | Legacy OpenClaw Gateway client. |
| `newsroom/story_index.py` | Deterministic clustering and ranking helpers. |

## License

[MIT](LICENSE)
