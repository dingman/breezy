# P1 plan r2 — latency pre-flight for P4 (2026-10-22; supersedes r1 per reviews/P1_r1_pmr.md + reviews/P1_r1_grok.md)


**Goal.** Before P4, find out whether sharp's 17 in-sample fills survive placement latency or were sub-second feed-skew artefacts. This is not an edge test.

## Inputs
- **Code.** Worktree `/home/jon/breezy-maker-design` at HEAD 0d6b4c59, run with `PYTHONPATH=/home/jon/breezy-maker-design`. The sharp outputs came from a dirty tree: `code_sha` 206d89ae has no `Arm("sharp")`. So the committed code must reproduce them first (G0).
- **Baseline.** Sharp in `~/.local/share/breezy/derived/replay/design/maker_nobid_sharp/`:
  - 17 fills that pass the stress rule, all wins, `sum_x` 1.96 in the base cell;
  - 20 fills under the base rule. The other 3 fill only under base, and all 3 win (MIA 09-27 `gte91f`, MDW 10-06 `gte76lt77f`, LAX 10-11 `gte78f`).
  - The 17-vs-20 gap is base vs stress counting (`maker_design_score.py:191`, `maker_stage0_runio.py:219-246`). It is not a bug, and it needs no new script.
- **Run config.** As recorded in `sharp/summary.json`: days 09-18 to 10-13, cached plan, θ (0.0695, 0.08), slip (0.01, 0.02). Arms: `sharp`, `sharp_l1`, `sharp_l5` only.

## Latency model (exact wording)
For one replay, the driver wraps `fill_pass.Pass._on_print`. A print on a live episode with `ts <= t0 + L` does not change `r` or `g`; it only updates `self.instance`. The simulator file is not edited.

The model is **conservative on queue consumption**: prints during L do not eat the queue ahead of us. It does **not model queue growth or book drift during L**. The refusal check (marketable or stale) runs only at t0. It is not a realistic model. L = 1 s is the gate. L = 5 s is report-only.

## Steps
1. **Edit `scripts/analysis/maker_design_config.py`.**
   - Add `Arm.latency_ns: int = 0`.
   - Add the arms `sharp_l1` (1 s) and `sharp_l5` (5 s). They are identical to `sharp` except for latency.
2. **Edit `scripts/analysis/maker_design_nobid.py`.**
   - Add a `latency_override(latency_ns)` context manager, built the same way as `rule_override` and always restored.
   - In `_replay_arm`, apply it only when `latency_ns > 0`.
3. **Edit `tests/unit/test_maker_design_nobid.py`.**
   - Use a synthetic `Pass` with one live episode with `r=5`.
   - A print of size 10 inside L leaves `r` and `g` unchanged.
   - A later print of size 3 leaves `r=2` and no fill. A further print of size 2 fills.
   - With L=0 the behaviour is unchanged.
   - The override is restored after an exception.
   - The arm-table pins cover `latency_ns` and the NO<0.90 ceiling.
   - Run that test file, then `lint-imports` (from the worktree directory), then ruff on the changed files only.
   - Commit by explicit path, and confirm `git status --porcelain scripts/analysis` is empty before launching.
4. **Run** `maker_design_nobid` with the 3 arms into a fresh `.../design/p1_latency/`.
   - Launch under `systemd-run --user -p MemoryMax=8G -p RuntimeMaxSec=14400 -p LimitNOFILE=524288` with `workers=2`.
   - Stall watch: flag `progress.jsonl` if it is unchanged for more than 30 min.
   - Run only when no other heavy job is running. Expect about 1.5–2 h.
5. **Read the results** with an inline pandas check on `positions.csv` and `episodes.jsonl`. Nothing is committed.
   - Survivors at L=1 s and L=5 s, out of the 17, and out of the 4 base fills that landed under 10 s.
   - Any fill at L=1 s that is not in the L=0 set.
   - A descriptive same-station markout:
     - **Change:** mean YES-mid change in cents from just before each L=1 s stress fill to 10 min after it, on the filled rung's own Depth10.
     - **Comparison:** shown next to the mean X of about 11.5 ¢.
     - **Limits:** no p-value. A fill with a one-sided book is dropped and counted.
6. **Record** the outcome in one short note, `docs/evidence/P1_latency_preflight_<date>.md`, and update the P1 row in `docs/core/PROGRESS.md`.

## PASS / FAIL / STOP
- **G0 (reproduction).** At L=0, committed HEAD gives sharp 17 stress-pass fills and `sum_x` 1.96. If not, **STOP** and fix provenance before reading any latency arm.
- **G1 (the only gate).** Both must hold:
  - `sharp_l1` has 10 or more stress-pass fills;
  - **no** fill at L=1 s, base or stress, is a settlement loser.
- **Outcome.** PASS = G0 and G1, and P4 may start. If G1 fails, the maker programme ends. L=5 s and the markout are report-only.

## Effort
$0. About 2 h of code and tests, 1.5–2 h of run, and about 30 min to read and record. About half a day.

## Risks
1. The model ignores size that joins ahead of us during L. That could overstate survivors at L=1 s; the L=5 s count and the markout give context.
2. G0 may fail because of the dirty-tree provenance. That is a STOP, not a FAIL.
3. A PASS only says the fills are not a feed-skew artefact. The edge is tested only in P4, live.

## Not doing
- No change to the simulator or to `src/`. The full gate is not required.
- No control arms.
- No adverse-selection gate, p-value, matched controls or sign-flip.
- No audit script.
- No holdout replay. The 10-14 to 11-15 tape stays unread for later.
- No threshold changes after the results are read.
---

## r2.1 coordinator amendments (adopting `reviews/P1_r2_pmr.md` + `reviews/P1_r2_grok.md`, both APPROVE-WITH-CHANGES) — STATUS: READY

1. **Provenance cite.** The sharp artefact's `code_sha` is `eac99bd6`, not 206d89ae. Neither commit contains `Arm("sharp")`; HEAD `0d6b4c59` does (`maker_design_config.py:83`).
2. **G0, pinned exactly.** The base cell is `x_t0.0695_s0.01`. Slip-0.02 cells read 1.79 and must not be compared to 1.96. At L = 0, the committed-HEAD `sharp` arm must reproduce:
   - the **same set** of stress-pass fills at the (station, day, rung) level as the old `positions.csv`;
   - 17 fills;
   - `sum_x` 1.96 in that cell.
   Record `code_sha` in the new `summary.json`.
3. **G1 row filter, written into the gate.**
   - "≥ 10" counts rows with `stress_pass and win is not None`, the same filter as the 17 (`maker_design_score.py:191`).
   - A loser is `win is False` on any filled L = 1 s row, base or stress.
   - Rows with `win is None` are counted and reported, never treated as non-losers silently.
   - Survivors among the 4 sub-10 s fills are named. If all 4 die, 13 remain, which still passes.
4. **The markout is biased adverse by construction.** A fill is a BUYER sweep print, so the mid is pushed up at the fill. Report it as descriptive only, never as a selection measure against X.
