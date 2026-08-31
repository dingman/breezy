#!/usr/bin/env bash
# Enforces the size budget declared in docs/core/PROGRESS.md "Maintenance contract".
# PostToolUse hook: exit 2 returns stderr to Claude as a blocking error.
set -uo pipefail

MAX_LINES=250
MAX_BYTES=12288

payload=$(cat)
f=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)

case "$f" in
  */docs/core/PROGRESS.md) ;;
  *) exit 0 ;;
esac

[ -f "$f" ] || exit 0

lines=$(wc -l < "$f" | tr -d ' ')
bytes=$(wc -c < "$f" | tr -d ' ')

if [ "$lines" -gt "$MAX_LINES" ] || [ "$bytes" -gt "$MAX_BYTES" ]; then
  cat >&2 <<EOF
BLOCKED: docs/core/PROGRESS.md is over its size budget.
  now: ${lines} lines / ${bytes} bytes
  max: ${MAX_LINES} lines / ${MAX_BYTES} bytes

This file tracks OPEN state only. To get back under budget:
  - DELETE items that have closed. Do not rewrite them as [CLOSED] narratives; the commit is the record.
  - Move evidence summaries to docs/evidence/ and link them instead.
  - Move durable rules to docs/core/LESSONS.md.
  - Move superseded history to docs/core/archive/.
  - Severity tags ([HIGH]/[MEDIUM]/...) mark OPEN items only.

See the "Maintenance contract" section at the top of the file.
EOF
  exit 2
fi
exit 0
