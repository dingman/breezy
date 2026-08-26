# G-11 — Commit the quote-tape recorder work

**Phase:** A support. **Depends on:** G-04, G-09, G-10 landing (they modify the
same working tree).

## Problem

Work item 1.1 — the venue quote-tape recorder — is built, three-axis reviewed,
and **uncommitted**. From `docs/core/PROGRESS.md`: "BUILT, REVIEWED, NOT YET
RUNNING (2026-08-26). **Uncommitted.**"

It is the single item on the irreversible critical path. Living only in a
working tree is an unacceptable risk for it: the tape it produces cannot be
backfilled by any vendor, and the recorder that produces the tape currently has
no durable copy.

## Approach

1. Review the full working-tree diff before committing anything. The tree
   currently holds changes from several concurrent workstreams — assume other
   agents' work may be present and commit only by explicit path.
2. **Never `git add -A` or `git add -am`.** Stage by explicit path.
3. Verify no secrets: no private keys, no `X-PM-Access-Key` values, no real
   credentials in fixtures or evidence files. The evidence directories under
   `docs/evidence/venue/` contain captured venue traffic — confirm redaction
   covers the access key, not only the signature (this is exactly SEC-4).
4. Confirm gates green immediately before commit: `uv run pytest -q`,
   `uv run ruff check .`, `uv run mypy`.
5. Group into coherent commits by concern rather than one omnibus commit.

## GREEN criterion

Recorder work committed on a branch, gates green at the commit, no secret
material in the diff, and no other agent's uncommitted work discarded or
swept in.

## Risks

- **Sweeping in concurrent work.** Mitigation: explicit paths only, diff
  reviewed first.
- **Committing captured credentials.** Mitigation: step 3 is a hard gate, not a
  checklist item. If any doubt exists, do not commit the evidence directory.
