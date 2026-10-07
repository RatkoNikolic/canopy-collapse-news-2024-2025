#!/usr/bin/env bash
# Timestamp the committed state (PROTOCOL.md §6.1): timestamps/<name>.txt lists the commit and
# the sha256 of every tracked file; `ots stamp` sends only that file's hash to the public
# OpenTimestamps calendars. Commit the .txt and .ots; later `ots upgrade timestamps/<name>.txt.ots`
# (once the Bitcoin anchor confirms, a few hours) and commit the upgraded proof.
# Check: `ots verify timestamps/<name>.txt.ots` (needs the .txt next to it).
set -euo pipefail
name=${1:?usage: scripts/stamp.sh <name>}
cd "$(dirname "$0")/.."
git diff --quiet && git diff --cached --quiet || { echo "commit first: the stamp covers HEAD"; exit 1; }
mkdir -p timestamps
out=timestamps/$name.txt
[ -e "$out" ] && { echo "$out exists"; exit 1; }
{ echo "commit $(git rev-parse HEAD)"; echo "stamped $(date -u +%Y-%m-%dT%H:%M:%SZ)";
  git ls-files -z | xargs -0 sha256sum; } > "$out"
uv run ots stamp "$out"
echo "stamped $out; commit $out and $out.ots"
