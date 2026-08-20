#!/bin/sh
# Install Neo4j Community 2026.06.0 from the official unix tarball.
# Do not use Homebrew (advertises 2026.07.1). Do not use Docker.
set -eu
ROOT="${NEWSROOM_NEO4J_ROOT:-$HOME/Library/Application Support/newsroom}"
TARBALL="$ROOT/neo4j-community-2026.06.0-unix.tar.gz"
HOME_DIR="$ROOT/neo4j-community-2026.06.0"
URI="https://dist.neo4j.org/neo4j-community-2026.06.0-unix.tar.gz"
PIN="1dcf62e7e8035e71732b86532b9f8e3219ce8956bd06940d5a0024696727192a"

mkdir -p "$ROOT"
if [ ! -f "$TARBALL" ]; then
  curl -fsSL -o "$TARBALL" "$URI"
fi
actual="$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
if [ "$actual" != "$PIN" ]; then
  echo "Neo4j tarball digest differs: $actual" >&2
  exit 1
fi
if [ ! -d "$HOME_DIR" ]; then
  tar -xzf "$TARBALL" -C "$ROOT"
fi
CONF="$HOME_DIR/conf/neo4j.conf"
python3 - "$CONF" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
replacements = {
    "#server.default_listen_address=0.0.0.0": "server.default_listen_address=127.0.0.1",
    "server.default_listen_address=0.0.0.0": "server.default_listen_address=127.0.0.1",
    "#server.bolt.listen_address=:7687": "server.bolt.listen_address=127.0.0.1:7687",
    "server.bolt.listen_address=:7687": "server.bolt.listen_address=127.0.0.1:7687",
    "#server.http.listen_address=:7474": "server.http.listen_address=127.0.0.1:7474",
    "server.http.listen_address=:7474": "server.http.listen_address=127.0.0.1:7474",
}
for old, new in replacements.items():
    text = text.replace(old, new)
if "server.default_listen_address=127.0.0.1" not in text:
    text += "\nserver.default_listen_address=127.0.0.1\n"
if "server.bolt.listen_address=127.0.0.1:7687" not in text:
    text += "server.bolt.listen_address=127.0.0.1:7687\n"
path.write_text(text)
print(path)
PY
echo "installed $HOME_DIR"
echo "Bolt must remain 127.0.0.1:7687. Set NEO4J_COMMUNITY_LOCAL via the credential broker before start."
