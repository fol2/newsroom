# Installed Hermes Agent versus the Newsroom Hermes Control Plane

**Date:** 17 August 2026  
**Host:** `macm4` (`Jamess-Mac-mini.local`, user `jamesto`)  
**Ticket:** [Compare installed Hermes with the Newsroom Control Plane](https://github.com/fol2/newsroom/issues/558)  
**Map:** [Wayfinder map — Autonomous production Newsroom](https://github.com/fol2/newsroom/issues/557)  
**Question:** What gaps remain between the installed Hermes Agent on `macm4` and the Newsroom Hermes Control Plane required by ADR 0007 and Increment 9R OD-007?

This note is a gap inventory. It does not implement the Control Plane, change `main`, or open Increment 11 work. Secret files were not read: `~/.hermes/.env`, `~/.hermes/auth.json`, and other credential stores were excluded. `config.yaml` was inspected for **key names only**.

## Method

Primary sources only:

- Live install: `hermes version`, `hermes` on `PATH`, `~/.hermes/hermes-agent`, `hermes gateway status` / `list`, `hermes cron list` / `status`, LaunchAgents, `com.jamesto.newsroom-hub.plist`.
- Official Hermes Agent documentation (and the matching files in the local clone at `~/.hermes/hermes-agent`): service/launchd, cron, skills, credentials, stop/kill, update.
- [ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md).
- [Increment 9R shadow plan](../plans/2026-08-15-021-increment-9r-shadow-plan.md) OD-007 (and the OD-012 / OD-014 credential and stop clauses that OD-007 depends on).
- `newsroom/increment9/plan.py` and `newsroom/increment9/agent_profiles_v1.json` (Hermes input/result transport).
- `AGENTS.md` (OpenClaw runner).
- `CONTEXT.md` glossary terms for the Hermes Control Plane.
- Increment 9B2 controller module and operations note, only to show they are **not** the live Control Plane.

## Answer in one line

Hermes Agent v0.18.2 is installed as a CLI substrate. The Newsroom Hermes Control Plane required by ADR 0007 and OD-007 is not installed: there is no Hermes `launchd` service, no Newsroom cron or skill, no Keychain credential broker, no Autonomous Control Ledger bound to Hermes, and no live admission/publication daemon. `com.jamesto.newsroom-hub` is a separate read-only operator shell.

## Charting observations — confirmed or corrected

| Charting claim | Finding |
|---|---|
| Hermes Agent v0.18.2 at `~/.hermes/hermes-agent` | **Confirmed.** `hermes version` reports `Hermes Agent v0.18.2 (2026.7.7.2)`, install directory `/Users/jamesto/.hermes/hermes-agent`, method `git`. `which hermes` is `/Users/jamesto/.local/bin/hermes`. `HERMES_HOME` remains `~/.hermes`. |
| `hermes` on `PATH` | **Confirmed.** |
| Empty Hermes cron | **Confirmed.** `hermes cron list` prints `No scheduled jobs.` Neither `~/.hermes/cron/jobs.json` nor the `mini-hub-operator` profile copy exists. Cron directories hold only lock files, ticker stamps, and an empty `output/` folder. |
| No Hermes LaunchAgent | **Confirmed.** `~/Library/LaunchAgents/` has no `ai.hermes*` plist. `launchctl print gui/$(id -u)/ai.hermes.gateway` returns that the service does not exist. `hermes gateway status` reports the gateway is not running. |
| `com.jamesto.newsroom-hub` is a separate operator shell | **Confirmed.** See Gap 3. |

**Correction to OD-007's recorded upstream SHA.** OD-007 recorded the observed install as Hermes Agent v0.18.2 with upstream commit `17c7b0be` and carried local commit `8e734810`. Live `hermes version` still reports local `8e734810` and v0.18.2, but names upstream as `12b1f0f8` (the short hash of `origin/main` in the banner). `hermes update --check` reports the checkout is behind `origin/main`. The banner formats that pair via `get_git_banner_state()` / `format_banner_version_label()` in `~/.hermes/hermes-agent/hermes_cli/banner.py`. This is version drift of the Agent checkout, not evidence that a Control Plane exists.

Sources: live `hermes version`; live `hermes cron list`; live `hermes gateway status`; `~/Library/LaunchAgents/`; [OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md); local `hermes_cli/banner.py`.

## What the Control Plane is required to be

`CONTEXT.md` defines the **Hermes Control Plane** as the complete local autonomous authority comprising an AI controller and an inseparable deterministic policy-and-effect boundary. The AI controller may decide and orchestrate; only the deterministic boundary holds authority-store, projection or target credentials and rejects any command that fails a frozen veto. A model subprocess is not the Hermes Control Plane.

ADR 0007 and OD-007 bind that definition to `macm4` operations:

1. Hermes on `macm4` is the local orchestration, admission and delivery hub ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).
2. Only the deterministic boundary possesses canonical SQLite, Neo4j projection and target-adapter credentials. Codex, Claude, Grok and Gemini subprocesses never receive those credentials; they return schema-valid commands to Hermes ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md)).
3. Hermes runs as a `launchd` user service under `jamesto`, with one active instance, health checks, restart, staged update, replay verification, atomic promotion and rollback ([OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).
4. Credentials come from a local broker backed by macOS Keychain or an equivalent local secret store, injected minimally and transiently; the ledger stores class, scope and digest only ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-012](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).
5. The Autonomous Control Ledger is append-only, hash-chained and checkpoint-signed; a gap blocks further external action ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-014](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).
6. P0: kill within 60 seconds, revoke affected credentials within five minutes, notify the human within five minutes, contain within 15 minutes. An authenticated Human Accountable Owner may issue a signed global or scoped emergency stop, including `HUMAN_RELEASE_REQUIRED` ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-014](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).
7. A **Hermes Publication Admission** is a terminal `AUTO_PUBLISH` for one exact Publication Bundle; the credential-bearing target adapter then dispatches. Discord and OpenClaw are not target dependencies ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); `CONTEXT.md`).
8. Hermes updates through a staging checkout. Adapter, ledger, redaction and admission replays must pass before atomic promotion; failure restores the last healthy build ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md)).

OD-007 also records that the install carries **repository-owned adapter contracts**. Those contracts live in this repository as Increment 9 qualification code. They are not wired to the installed Agent as a running Control Plane (see Gaps 8 and 10).

## Installed substrate (not the Control Plane)

| Item | Observed |
|---|---|
| Product | Hermes Agent v0.18.2 CLI and git checkout at `~/.hermes/hermes-agent`. |
| Sticky profile | `~/.hermes/active_profile` contains `mini-hub-operator`. |
| Gateways | `hermes gateway list`: default **not running**; `mini-hub-operator` (current) **not running**. |
| Official service shape | The documented macOS background service is the **messaging gateway**, installed by `hermes gateway install` as `~/Library/LaunchAgents/ai.hermes.gateway.plist` (or `ai.hermes.gateway-<profile>.plist`). It runs platform adapters and ticks cron every 60 seconds. It is not an admission or publication controller. |
| Skills | Bundled/hub skills under `~/.hermes/skills/`. No `newsroom` skill directory. `hermes skills list` has no Newsroom / Control Plane / Increment 9 name. |
| Secrets CLI | `hermes secrets` supports Bitwarden and 1Password only. `config.yaml` has no `secrets`, `bitwarden` or `onepassword` keys. |

Sources: live CLI; [Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/); [Secrets](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/); [Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills).

---

## Gap inventory

Each gap is **required Control Plane behaviour** minus **what is installed**. Citations follow the claim.

### Gap 1 — The installed Agent is not the Hermes Control Plane

**Required:** the Control Plane is the AI controller **plus** the inseparable deterministic policy-and-effect boundary. A model subprocess is not the Control Plane (`CONTEXT.md`; [ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md)).

**Installed:** a general Hermes Agent CLI, profiles, skills, and an optional messaging gateway. Official docs describe Hermes as an AI assistant with tool-calling, a messaging gateway, and cron ([CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands); [Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/)).

**Gap:** installing Hermes Agent does not install the Newsroom Control Plane. No Newsroom process binds an AI controller to a credential-bearing deterministic veto daemon.

### Gap 2 — No Hermes `launchd` user service

**Required:** Hermes runs as a `launchd` user service under `jamesto`, one active instance, with health checks and restart ([OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).

**Installed capability (unused):** `hermes gateway install` writes `~/Library/LaunchAgents/ai.hermes.gateway.plist` with `RunAtLoad` and unconditional `KeepAlive`, plus `PATH`, `VIRTUAL_ENV` and `HERMES_HOME` ([Messaging Gateway — macOS launchd](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/); local `hermes_cli/gateway.py` `get_launchd_plist_path()` and the plist template). Profile homes would use `ai.hermes.gateway-<suffix>.plist`.

**Observed:** no such plist; `ai.hermes.gateway` is not registered; both listed gateways are stopped. `hermes cron status` therefore reports that cron jobs will not fire.

**Gap:** the OD-007 service envelope is absent. Even if the official gateway were installed, it would supervise a **messaging gateway**, not the Control Plane's admission boundary.

### Gap 3 — `com.jamesto.newsroom-hub` is not the Control Plane

**Required:** the Control Plane is Hermes as orchestration and admission hub ([OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md); `CONTEXT.md`).

**Observed:** `~/Library/LaunchAgents/com.jamesto.newsroom-hub.plist` is loaded and running (`launchctl` state `running`, PID observed). It starts `/usr/bin/python3 /Users/jamesto/Coding/newsroom-hub/shell/serve.py --bind 127.0.0.1 --port 3847 --store …/proving_store.sqlite3`, with `RunAtLoad` and `KeepAlive`. The module docstring is `Read-only operator hub origin. No writes, no model calls.` POST is rejected (`405 write path denied`). The store is the Increment 9P proving SQLite, not production `news_pool.sqlite3`.

**Gap:** this LaunchAgent is an operator shell over proving evidence. It holds no AI controller, no admission veto, no target credentials, and no Hermes identity (`ai.hermes.gateway` vs `com.jamesto.newsroom-hub`).

### Gap 4 — No Newsroom Hermes cron

**Required:** OD-007 makes Hermes the local hub for ledgered operations. Increment 9R execution uses Hermes to deliver atoms once prerequisites pass ([9R plan](../plans/2026-08-15-021-increment-9r-shadow-plan.md)). Official Hermes cron can attach skills and will not tick unless the gateway is running ([Cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron); [Cron internals](https://hermes-agent.nousresearch.com/docs/developer-guide/cron-internals) — jobs live in `~/.hermes/cron/jobs.json`; the gateway ticks every 60 seconds).

**Observed:** no jobs; no `jobs.json`; gateway not running. The live Newsroom schedules documented in `AGENTS.md` are **OpenClaw** cron (`openclaw cron add` for the daily and hourly planners), which spawn `newsroom_runner.py` — not `hermes cron`.

**Gap:** there is no Hermes-scheduled Newsroom control loop. Empty Hermes cron is not an equivalent of the OpenClaw planner/runner path, and that OpenClaw path is not the Control Plane (Gap 11).

### Gap 5 — No Newsroom Hermes skill

**Required:** a Control Plane that plans, coordinates and admits against repository-owned contracts ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); OD-007). Official skills are on-demand `SKILL.md` instruction packs under `~/.hermes/skills/`, not a policy-and-effect boundary ([Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills); [Creating skills](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills)).

**Observed:** many bundled skills; none named for Newsroom, Increment 9, or a Control Plane. A skill would still be the AI-controller side only.

**Gap:** no Newsroom skill, and a skill alone would not satisfy the deterministic veto half of the Control Plane (`CONTEXT.md`: a model subprocess is not the Control Plane).

### Gap 6 — No Keychain (or equivalent) credential broker

**Required:** Hermes uses a local credential broker backed by macOS Keychain or an equivalent local secret store. Secrets are injected minimally and transiently; the ledger stores class, scope and digest. Only the deterministic boundary holds SQLite, Neo4j and target-adapter credentials ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md); [OD-012](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).

**Installed Hermes credential model:** `hermes secrets` pulls provider API keys from **Bitwarden Secrets Manager** or **1Password** at process startup, instead of `~/.hermes/.env`. OS keystores are explicitly **not** in-tree: “Bitwarden and 1Password ship in-tree. Everything else — … OS keystores — belongs in plugin repos” ([Secrets](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/); [Secret source plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/secret-source-plugin)).

**Observed:** `config.yaml` has no `secrets` / `bitwarden` / `onepassword` keys. No Keychain plugin is present in the inspected plugin listings. This note did not open `.env` or `auth.json`.

**Gap:** there is no Newsroom Keychain broker, no class/scope/digest ledger of injections, and no enforced split that keeps authority-store credentials out of model subprocesses. Official Hermes secrets solve **provider API keys for the Agent**, not SQLite / Neo4j / target-adapter authority credentials for a deterministic boundary.

### Gap 7 — Stop and kill are session/service stops, not the signed P0 envelope

**Required:** P0 kill within 60 seconds; credential revocation and human notification within five minutes; containment within 15 minutes; signed global or scoped emergency stop; resume blocked when the stop states `HUMAN_RELEASE_REQUIRED` ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-014](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).

**Installed Hermes stops:**

- `hermes gateway stop` stops the messaging-gateway service ([Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/); [CLI](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)).
- `/stop` kills running background processes and interrupts the current agent session ([Slash commands](https://hermes-agent.nousresearch.com/docs/reference/slash-commands)).
- Official security is allowlists, dangerous-command approval, containers and pairing — not a signed Newsroom emergency stop ([Security](https://hermes-agent.nousresearch.com/docs/user-guide/security)).
- Increment 9P proving code attests `kill_switch` / `no_emergency_stop` as **boolean proving-gate inputs** (`newsroom/increment9/proving.py`). That is qualification attestation, not a live signed stop.

**Gap:** no signed stop object, no 60-second kill SLA wired to Hermes, no five-minute Keychain/credential revocation path, no `HUMAN_RELEASE_REQUIRED` latch on the installed Agent.

### Gap 8 — `hermes update` is not the staged Control Plane promotion

**Required:** Hermes updates through a staging checkout; adapter, ledger, redaction and admission replays must pass before atomic promotion; failure restores the last healthy build ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).

**Installed:** `hermes update` git-pulls `main`, compiles a small set of startup files, rolls the **Agent checkout** back with `git reset --hard` if those files fail to parse, reinstalls Python deps, and restarts a service-managed gateway ([Updating](https://hermes-agent.nousresearch.com/docs/getting-started/updating)). `/rollback` checkpoints are an optional filesystem shadow-git for agent file edits, default off ([Checkpoints](https://hermes-agent.nousresearch.com/docs/user-guide/checkpoints-and-rollback)).

**Gap:** there is no staging promotion that replays Newsroom adapters, the Autonomous Control Ledger, redaction or admission before swapping a Control Plane build.

### Gap 9 — No Autonomous Control Ledger bound to Hermes

**Required:** append-only, hash-chained, checkpoint-signed Autonomous Control Ledger; a gap blocks external action. Agent stderr for Increment 9 profiles must be redacted into that ledger ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-014](../plans/2026-08-15-021-increment-9r-shadow-plan.md); `agent_profiles_v1.json` `stderr_policy`: `EVENT_STREAM_REDACTED_TO_AUTONOMOUS_CONTROL_LEDGER`).

**Installed / in-repo:**

- Hermes `state.db` and session logs are Agent runtime state, not a Newsroom control ledger.
- Increment 9B2 `ControllerEvidenceJournal` is an isolated SQLite journal for **fixture/replay qualification**, not installed into production or the 9B1 Epoch schema (`docs/operations/increment-9b2-shadow-controller.md`; `newsroom/increment9/controller.py`).

**Gap:** no live hash-chained control ledger that Hermes fail-closes against.

### Gap 10 — Hermes input/result schemas exist; no live dispatcher

**Required / specified:** Increment 9 agent profiles freeze a transport contract (`newsroom/increment9/plan.py` `load_increment9_agent_profiles`; `newsroom/increment9/agent_profiles_v1.json`):

- input: `newsroom.increment9.hermes-input.v1`
- output: `newsroom.increment9.hermes-result.v1`
- stdout: one schema-valid JSON result only
- stderr: redacted to the Autonomous Control Ledger
- invalid result: `NOT_EVALUATED`
- silent repair forbidden
- result statuses: `SUCCESS`, `NOT_EVALUATED`, `FAILED`
- verdicts: `APPROVE`, `BLOCK`, `INSUFFICIENT_EVIDENCE`, `NOT_APPLICABLE`
- three profiles: system-under-test, primary reviewer, adjudicator, none of which may hold credentials

**Observed:** those names and the result vocabulary are frozen in repository JSON and enforced by `plan.py`. There is no separate JSON Schema document for `hermes-input.v1` beyond the identifier. No Newsroom module dispatches the installed `hermes` binary with that input or consumes `hermes-result.v1` from it (repository search for the schema ids resolves only to `plan.py` and its tests).

**Gap:** the subprocess contract is specified; the Control Plane runtime that would feed it, validate it, apply the deterministic veto, and ledger the result is not running on the installed Agent.

### Gap 11 — Live Newsroom orchestration is still OpenClaw, targeting Discord

**Required:** Hermes is the hub; Discord and OpenClaw are not target dependencies; first approved target is the integrated Newsroom app-serving system and reader surfaces ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); `CONTEXT.md` **Hermes Publication Admission**).

**Installed live path (`AGENTS.md`):** OpenClaw cron planners write `story_job_v1` files; `newsroom_runner.py` is a detached Python process; workers spawn via OpenClaw `sessions_spawn`; default publisher mode posts to Discord (`script_posts` / `agent_posts`). Environment is `OPENCLAW_HOME`, not `HERMES_HOME`.

**Gap:** the production-shaped loop on this host (as documented in-tree) is the legacy OpenClaw runner. It is a different orchestrator, a different spawn API, and a publication target the Autonomy Envelope excludes.

### Gap 12 — Increment 9B2 is qualification, not the live Control Plane

**Required:** an AI controller that makes the final autonomous admission decision, bound to a credential-bearing deterministic boundary ([ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md); [OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md)). Wave 2 of the 9R graph is “Isolated deployment and Hermes controller” (atoms 9A2, 9B2).

**In-repo 9B2:** `newsroom.increment9.controller` “executes canonical fixture/replay records only. It has no credential, network, provider, publication, Evidence Intake or production writer capability and cannot start the 9B3 prospective campaign.” A successful receipt is only `READY_FOR_9B3_AUTHORISATION_GATE` (`docs/operations/increment-9b2-shadow-controller.md`; `newsroom/increment9/controller.py`).

**Gap:** 9B2 proves an isolated editorial-path controller against fixtures. It is not the installed Hermes Agent, and it is not a live Control Plane with credentials or publication admission.

### Gap 13 — No Hermes Publication Admission / target adapter

**Required:** terminal `AUTO_PUBLISH` for one Publication Bundle; deterministic target adapter dispatches; models never send directly to a public target (`CONTEXT.md`; [ADR 0007](../adr/0007-hermes-autonomy-envelope-and-conditional-activation.md)).

**Installed:** Hermes gateway adapters are messaging platforms (Telegram, Discord, WhatsApp, …) ([Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/)). The OpenClaw runner publishes Discord drafts (`AGENTS.md`). Neither is the integrated Newsroom app-serving target adapter.

**Gap:** no Control Plane publication-admission transaction and no credential-bearing Newsroom target adapter driven by Hermes.

### Gap 14 — One-active-instance, health, and restart exist only as unused gateway machinery

**Required:** one active instance, health checks, restart ([OD-007](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).

**Installed machinery:** official launchd `KeepAlive` and gateway health reporting in `hermes_cli/gateway.py`; SIGUSR1 drain-then-restart so launchd respawns the **gateway** ([Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/); local `_graceful_restart_via_sigusr1`). Multi-profile installs would create **multiple** labels (`ai.hermes.gateway` and `ai.hermes.gateway-mini-hub-operator`) ([Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles); `hermes gateway list` already names both, both down).

**Gap:** OD-007's single supervised Control Plane instance is not running. Official health/restart would attach to a messaging gateway, and the current profile layout already names two gateway identities.

---

## Present, but not sufficient

These are real, cited facts. They do not close the Control Plane.

- Hermes Agent v0.18.2 is installed and `hermes` is on `PATH` (live `hermes version`).
- The Agent can be installed as a macOS LaunchAgent **if** an operator runs `hermes gateway install` ([Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/)). That step has not been taken.
- Increment 9 frozen profiles and result vocabulary exist in `agent_profiles_v1.json` / `plan.py`.
- Increment 9A2/9B2 qualification code exists in-repo and remains non-activating.
- ADR 0007 is accepted; Conditional Activation Authority remains gated on missing implementation ([9R Decision](../plans/2026-08-15-021-increment-9r-shadow-plan.md)).

## Intentionally unread

`~/.hermes/.env`, `~/.hermes/auth.json`, profile `auth.json` files, and any Keychain item bodies. Absence of a Keychain **broker** is inferred from ADR/OD requirements, official Hermes secret backends, `config.yaml` key names, and plugin listings — not from dumping secrets.

## Implications for later tickets

This inventory does not authorise installing the official Hermes gateway, writing a Newsroom skill, or implementing Increment 11. It does imply that later decision tickets still need to specify, among other things already in the map fog: the Keychain credential classes and injection contract; whether production emergency stop requires `HUMAN_RELEASE_REQUIRED`; and that `hermes gateway install` is not, by itself, the Control Plane.
