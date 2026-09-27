#!/usr/bin/env bash
# PreToolUse(Bash) gate: block `git stash` in any form.
# The stash is repo-global and shared by every sibling worktree; agents have
# stashed live WIP four times despite written bans (LESSONS / memory
# never-git-stash-in-a-shared-tree). Fails open on parse errors.
input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception: print("")' 2>/dev/null)
# Read-only inspection (stash list / stash show) stays allowed: the coordinator
# uses `stash list` to verify no agent left a stash behind.
stripped=$(printf '%s' "$cmd" | sed -E 's/git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+stash[[:space:]]+(list|show)([[:space:]]|$)/git-stash-readonly /g')
if printf '%s' "$stripped" | grep -qE '(^|[;&|(`[:space:]])git([[:space:]]+(-C[[:space:]]+[^[:space:]]+|-c[[:space:]]+[^[:space:]]+|--[a-z-]+(=[^[:space:]]+)?))*[[:space:]]+stash([[:space:]]|$)'; then
  echo "BLOCKED: git stash is banned in this repo (shared across worktrees). For a baseline, use a detached base worktree under ~/.cache/breezy-gate/<slug>/base, or 'git show HEAD:<file>'." >&2
  exit 2
fi
exit 0
