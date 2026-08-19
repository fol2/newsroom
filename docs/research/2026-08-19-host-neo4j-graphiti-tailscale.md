# Host Neo4j, Graphiti and private-network facts versus the CI qualification pin

**Date:** 2026-08-19  
**Observed:** 2026-08-19T22:45:04Z (UTC) on this host, then re-checked in the same session  
**Ticket:** [fol2/newsroom#692](https://github.com/fol2/newsroom/issues/692)  
**Parent:** [fol2/newsroom#690](https://github.com/fol2/newsroom/issues/690)  
**Host:** Darwin `Jamess-Mac-mini.local` (arm64), user `jamesto` (uid 501)  
**Method:** live host commands, LaunchAgent plists, repository docs, `pyproject.toml` / `uv.lock` pins. No LaunchAgent changes, Neo4j start, Graphiti install, commit, or secret/Keychain dump.

## Question

What Neo4j, Graphiti, and private-network facts are true on this host versus the CI qualification pin?

## Live host table

| Surface | Live observation | Source |
| --- | --- | --- |
| TCP 7687 (Neo4j Bolt) | No `LISTEN` socket | `lsof -nP -iTCP:7687 -sTCP:LISTEN` → `NO_LISTENER_7687`; `netstat` showed no `.7687` `LISTEN` |
| TCP 7474 / 7473 / 7688 (Neo4j HTTP/TLS/alt Bolt) | No `LISTEN` socket | `lsof -nP -iTCP:{7474,7473,7688} -sTCP:LISTEN` |
| TCP 3847 | `Python` PID **62060** listening on **`127.0.0.1:3847` only** | `lsof -nP -iTCP:3847 -sTCP:LISTEN`; `netstat` `tcp4 127.0.0.1.3847 *.* LISTEN` |
| `com.jamesto.newsroom-hub` | LaunchAgent **running**, `pid = 62060`, `KeepAlive` + `RunAtLoad`. Bind args: `--bind 127.0.0.1 --port 3847`. Program: `/usr/bin/python3` → `newsroom-hub/shell/serve.py`. Store/drafts: proving and unpublished SQLite paths under `newsroom/data/newsroom/` | `launchctl print gui/501/com.jamesto.newsroom-hub`; `~/Library/LaunchAgents/com.jamesto.newsroom-hub.plist` `ProgramArguments` |
| `com.jamesto.newsroom-control-plane` | LaunchAgent **running**, `pid = 70728`. **No TCP bind args.** Program: newsroom `.venv` Python → `scripts/hermes_control_plane.py serve --proving … --unpublished … --interval 300`. **No TCP `LISTEN` on that PID** | `launchctl print gui/501/com.jamesto.newsroom-control-plane`; plist `ProgramArguments`; `lsof -nP -a -p 70728 -iTCP -sTCP:LISTEN` empty |
| `graphiti` import (newsroom venv) | **Missing:** `ModuleNotFoundError: No module named 'graphiti'` | `.venv/bin/python -c 'import graphiti'` |
| `graphiti` / `graphiti-core` packages (newsroom venv) | **Not installed** | `importlib.metadata`: all three names `NOT_INSTALLED` |
| Official Neo4j Python driver (newsroom venv) | **`neo4j==6.2.0`**, file under `.venv/lib/python3.13/site-packages/neo4j/` | `.venv/bin/python -c 'import neo4j; print(neo4j.__version__)'` |
| Newsroom venv interpreter | CPython **3.13.14** (uv-managed), not CI’s 3.12 | `.venv/bin/python` symlink; `sys.version` |
| `REAL_GRAPHITI_RUNTIME_ENABLED` (live import) | **`False`** | `.venv/bin/python -c 'from newsroom.graphiti_adapter.models import REAL_GRAPHITI_RUNTIME_ENABLED'` |
| Neo4j server process | **None** (`pgrep -x neo4j` exit 1; `ps` had no neo4j command) | live process table |
| Homebrew `neo4j` | Formula exists (stable **2026.07.1**), **not installed**; prefix path absent; `brew services info neo4j` → Running **false**, Loaded **false**, Schedulable **false**. Not in `brew services list` | `brew info neo4j`; `brew list --versions neo4j` empty; `ls /opt/homebrew/opt/neo4j` missing |
| Docker / Colima / Podman | **CLI and Docker.app binary absent** (`command not found: docker`; no `/Applications/Docker.app/.../docker`) | live `command -v` / `ls` |
| Tailscale CLI | **Present:** `/opt/homebrew/bin/tailscale` version **1.102.2**; daemon **Running**. Client/server version mismatch warning only (client 1.102.2 vs tailscaled 1.98.10). This host addresses below; no auth keys dumped | `command -v tailscale`; `tailscale version`; `tailscale status --self`; `tailscale ip -4` |
| This host Tailscale IPv4 | **`100.108.95.87`** (also on `utun0`) | `tailscale ip -4`; `ifconfig` |
| This host Tailscale IPv6 | **`fd7a:115c:a1e0::373a:d007`** | `tailscale status --self --json` `Self.TailscaleIPs` |
| This host Tailscale node name | **`macm4`**, `Online True` | `tailscale status --self --json` `Self.HostName` |
| This host LAN IPv4 | **`en0 192.168.1.121`**, **`en1 192.168.1.122`**; `bridge100 192.168.234.1`; loopback `127.0.0.1` | `ifconfig` `inet` |

Hub bind is loopback-only. Control Plane is a keepalive daemon with a 300-second interval and no TCP listener. Neither agent publishes Bolt.

## CI pin versus host

| Item | CI / repository qualification pin | This host |
| --- | --- | --- |
| Neo4j container image | `neo4j:2026.06.0-community-trixie` | **No container runtime.** Image is not running and cannot be observed locally |
| Neo4j server version | `2026.06.0` (Community), authenticated Bolt on runner **loopback** `127.0.0.1:7687` | **No server.** Bolt **7687** closed. Homebrew formula (if later installed) is a **different** advertised stable **2026.07.1**, and is **not** installed |
| Official Python driver | `neo4j==6.2.0` in `pyproject.toml` and `uv.lock`; CI `assert neo4j.__version__ == "6.2.0"` | **Matches:** venv reports `6.2.0` |
| Python runtime for that pin | GitHub Actions `python-version: "3.12"` with `uv sync --dev --locked` | Venv is **3.13.14**. `requires-python = ">=3.12"` still holds. This is a host/CI interpreter difference, not a driver-pin break |
| Graphiti package | **Not a CI pin.** `uv.lock` has **no** `graphiti` / `graphiti-core`. Increment 4D states the repository contains no Graphiti package in this boundary | **Matches absence:** import fails; metadata `NOT_INSTALLED` |
| Real Graphiti runtime | Increment 4E: repository-owned fake/replay plus authenticated actual Neo4j Community projection; **real Graphiti, model and embedding remain disabled** | **`REAL_GRAPHITI_RUNTIME_ENABLED = False`** in source and live import |
| Bolt exposure | CI publishes `--publish 127.0.0.1:7687:7687` (runner loopback only) | Host has **no** Bolt listener on loopback, LAN, or Tailscale addresses |

Driver pin **matches**. Neo4j **server/image do not exist on this host**, so the host is **not** an actual-Neo4j qualification runtime. Graphiti **package and REAL flag match the disabled/unqualified boundary**. Private-network identity exists (Tailscale + LAN addresses) but **does not currently front a Neo4j or Graphiti service**.

## What is not running

- Neo4j Community (no Bolt, no HTTP, no process, no Homebrew keg, no Docker container).
- Docker Engine / Docker Desktop / Colima / Podman (no CLI).
- Homebrew `neo4j` service (not installed, not loaded).
- The `graphiti` / `graphiti-core` Python packages.
- Real Graphiti / model / embedding execution (`REAL_GRAPHITI_RUNTIME_ENABLED` is `False`).
- Any Control Plane TCP socket (the LaunchAgent **is** running; it simply does not bind a port).
- Hub on any non-loopback address (it binds `127.0.0.1:3847` only).

This session did not start Neo4j, install Graphiti, or change LaunchAgents.

## Citations

1. Issue: <https://github.com/fol2/newsroom/issues/692> (question restated from the ticket body).
2. Qualification pin — image, server, driver, Python 3.12 + `uv.lock`: `docs/operations/neo4j-b2-qualification.md` lines 5–12, 54–55, 68–82.
3. CI image, loopback Bolt publish, driver assert, Python 3.12: `.github/workflows/projection-b2-neo4j.yml` lines 14–15, 23–38, 63–67.
4. Runtime boundary (fake/replay + actual Neo4j; real Graphiti disabled): `docs/operations/increment-4e-bilingual-actual-neo4j-proof.md` lines 6–10, 284–291.
5. No Graphiti package in the 4D boundary: `docs/operations/increment-4d-graphiti-proposal-adapter.md` line 10.
6. Driver pin: `pyproject.toml` line 16 `neo4j==6.2.0`; `uv.lock` `name = "neo4j"` / `version = "6.2.0"` and specifier `neo4j==6.2.0`. `uv.lock` has no `graphiti` string.
7. Flag: `newsroom/graphiti_adapter/models.py` line 68 `REAL_GRAPHITI_RUNTIME_ENABLED = False`; reject path at lines 334–338.
8. Live listeners: `lsof`/`netstat` on 7687 (none) and 3847 (`127.0.0.1`, PID 62060), 2026-08-19T22:45Z UTC.
9. Live LaunchAgents: `launchctl print gui/501/com.jamesto.newsroom-hub` and `…/com.jamesto.newsroom-control-plane`; plists `~/Library/LaunchAgents/com.jamesto.newsroom-hub.plist` and `~/Library/LaunchAgents/com.jamesto.newsroom-control-plane.plist` (`ProgramArguments` as tabulated). Control Plane `lsof -nP -a -p 70728 -iTCP -sTCP:LISTEN` empty.
10. Live packages: newsroom `.venv` CPython 3.13.14; `import graphiti` `ModuleNotFoundError`; `neo4j.__version__ == '6.2.0'`; live `REAL_GRAPHITI_RUNTIME_ENABLED is False`.
11. Live Homebrew/Docker: `brew info neo4j` “Not installed”, stable 2026.07.1; `brew services info neo4j` not running/loaded; `docker` command not found; Docker.app binary missing; `pgrep -x neo4j` exit 1.
12. Live Tailscale/LAN (this host addresses only): CLI `/opt/homebrew/bin/tailscale`; `tailscale ip -4` → `100.108.95.87`; `--self` node `macm4` online; `ifconfig` `en0 192.168.1.121`, `en1 192.168.1.122`.
