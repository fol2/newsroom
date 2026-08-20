#!/bin/sh
# Front loopback newsroom-hub with Tailscale Serve. No Funnel. No 0.0.0.0.
set -eu
if ! command -v tailscale >/dev/null; then
  echo "tailscale not on PATH" >&2
  exit 1
fi
tailscale serve --bg --yes 127.0.0.1:3847
tailscale serve status
echo "Hub remains bound on 127.0.0.1:3847. Auth is tailnet identity. Funnel is forbidden."
