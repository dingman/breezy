# AUD-07 M1c/M2 Execution Amendment, Rev 2: exact-conditional refine-on-proximity, lock-respecting segmented schedule, provenance-pinned resumable sweep

**Status:** Rev 2, answering the statistical reviewer (AMEND), the architect (REQUEST_CHANGES) and the python reviewer (HIGH, minor items). Peer-endorsed and implemented 2026-09-25 (this file supersedes the read-only draft with binding review edits 1-3 applied; see "Peer review" below).

**Amends:** `/home/jon/breezy/docs/plans/backlog/AUDIT_2026-09-21/AUD-07-AMENDMENT-2026-09-25.md`, §4 M1c ("Reps", "Spot check", "Runtime") and the M2 execution steps.

**Unchanged:**
- α=0.025 and δ=0.0033.
- V: one-sided 95% CP-upper ≤ 0.0283.
- I: CP-lower at confidence 1−0.05/16 > α.
- 20000 reps per cell.
- One 80k rerun per INDETERMINATE cell: δ stays fixed, the 80k result replaces the 20k result and is never pooled with it, and a cell still INDETERMINATE at 80k counts as I.
- The 49-cell grid, and `SEED_BASE + cell_index` for the 20k stage.

---

## Review traceability

| Item | Where addressed |
|---|---|
| Stat (a): terminal triggers are data-only | §2.2, step 2 of the proof |
| Stat (b): claim rewritten as bounded residual risk | §1 (final row), §2.3 |
| Stat (c): `SEED_CAL_BASE`, and all bases disjoint | §3.1, test 27 |
| Stat (d): audit detection power; choice justified | §2.3. **Chosen: both.** CAL-b is widened to all 49 cells plus a low-t/low-dt stress set, and the audit is set to 400 per cell (`AUDIT_EVERY=50` at 20k). Cost is stated. |
| Arch 1: segmented schedule; no-lock option evaluated | §4. **Chosen: segmented, under the lock.** The no-lock option is rejected on the house-rule/slice-accounting basis (§4.1, edit 1). |
| Arch 2: `code_sha` passed in, snapshot reused, `breezy.__file__` assertion | §3.2 |
| Arch 3: out-dir per stage; killed-write detection = no trailing `\n` | §3.3 |
| Arch 4: non-zero cell exit surfaced loudly | §3.4 |
| Arch 5: tests 17 (0<f<1), sha-mismatch resume, stage separation | §8, tests 17, 23, 24 |
| Py: dataclass defaults and placement | §7, `M1cCellResult` block |
| Py: determinism statement | §3.5 |
| Py: recovery step for a mid-sweep bugfix | §3.6 |
| Timeline (now 09-25 08:35Z; merge freeze 16:15Z) | §4.4 |

---

## 0. Facts verified in the code

- **Neutral wiring (`total_pnl=0`): an interim `S ≥ b_eff` never stops the loop.**
  - `look_verdict` needs `total_pnl > 0` to return SURVIVE (`src/breezy/settlement/current_rung_hold_v2.py:456`), so such a look returns CONTINUE.
  - The loop (`scripts/analysis/family_tally_v2.py:672-741`) stops only on futility (`S ≤ b_fut`, `:458`) or on the terminal look (`:683`).
- **Terminal triggers** (`family_tally_v2.py:677-683`):
  - `reached_loss_stop = total_pnl + residual ≤ LOSS_STOP_PNL`. Both inputs are the constant 0, so it never fires; `loss_stop_count == 0` is asserted per cell.
  - `reached_i_max = state.information ≥ i_max`. Depends on the draws only.
  - `reached_n_max = look_n ≥ n_max`. Depends on the schedule only.
  - `forced`: `truncation=None`, so always false.
  - None of these depends on a boundary value.
- **S, I and `t_history` depend on the draws only.** `run_cell` builds all `n_max` draws before the loop runs (`scripts/analysis/aud07_live_rule_crossing_sim.py:446-448`). A second chain over the same `draws` list therefore consumes no RNG.
- **npts=2001 is the live rule.** It is `GRID_NPTS`, used by `boundary_for` (`src/breezy/persistence/gs_boundary_artefact.py:89`).
- **The kernels are elementwise numpy/scipy, not BLAS:** `norm.pdf`, `np.trapezoid`, `cumulative_trapezoid`, `np.interp`, `brentq` (`gs_boundary_artefact.py:424-494`).
- **`run_chunk` appends with no guard** (`aud07_live_rule_crossing_sim.py:505-534`).

## 1. Design decisions

| Element | Decision |
|---|---|
| Base grid | Run at npts=601. When a replicate is near a boundary, recompute its whole chain at 2001 on the same `draws` with a fresh `StreamingBoundary(npts=2001)`, and discard the 601 LookRecords. |
| Where the check runs | Post hoc, over the returned `LookRecord`s. There is no hook into `run_sequential_looks`, so production code and the M1b golden are untouched. |
| Refine rule | The tightest exact rule (§2.1). Efficacy nearness counts only until a confident crossing; futility nearness counts at every reached look. |
| EPS and DT_MIN | Pinned in a **data file** (`eps_pin.json`) produced by the CAL-b census, not in a code constant. CAL and the gated runs therefore share one `code_sha` and one snapshot. `EPS = max(0.02, 3 × census max |Δb|)` on the Z-scale, over all depths and terminal looks. |
| Guards | Force a refine on:<br>• dt < DT_MIN;<br>• a non-finite b that is not the tie pair;<br>• a solver error at 601. |
| In-run audit | Fixed at **400 audited replicates per cell**: `audit_every = cell_total_reps // 400`, which is 50 at 20k and 200 at 80k. On any decision disagreement, or any audited |Δb| ≥ EPS, the cell aborts and exits non-zero. |
| Equivalence evidence | CAL-a (pure 2001) against CAL-c (refined) on **disjoint** CAL seeds. The rows must be byte-equal (§3.5). |
| **Claim (rewritten per Stat b)** | The refined decisions equal the pure-2001 decisions **exactly, on the condition that |b_601 − b_2001| < EPS at every reached look** of every replicate that is not refined. That premise is **estimated, not proven**: from the CAL-b census (19,600 full chains plus a stress set) and from 400 in-run audits per cell. The unaudited violation rate is bounded probabilistically (§2.3), and so is the bias it could cause. Within that bound, ε acts only as a performance parameter; outside it, the bias bound in §2.3 applies. |

## 2. Algorithm, proof and residual risk

### 2.1 Per-replicate algorithm

```
draws  = [combine_station_day(sample_station_day(rng, cell)) for _ in range(n_max)]  # unchanged
try:    looks_c = run_sequential_looks(draws, boundary_fn=StreamingBoundary(npts=601), ...)
except ValueError: reason = "solver"
reason = reason or needs_refine(looks_c, EPS, DT_MIN)   # None|"eff"|"fut"|"dt"|"nonfinite"
audit  = (rep_index % audit_every == 0)
if reason or audit:
    looks_f = run_sequential_looks(draws, boundary_fn=StreamingBoundary(npts=2001), ...)
    if audit and reason is None:
        if decisions(looks_c) != decisions(looks_f) or max_abs_delta_b(looks_c, looks_f) >= EPS:
            raise AuditPremiseViolation(cell_index, rep_index, ...)   # cell exits non-zero, no row written
    looks = looks_f
else:
    looks = looks_c
```

`needs_refine` returns None only if **all** of these hold over the reached coarse looks:

1. **eff:** either some look has `S − b_eff ≥ EPS` (a confident crossing), or every look has `S − b_eff ≤ −EPS` (a confident non-crossing).
2. **fut:** every look has `|S − b_fut| ≥ EPS`. The tie pair ±inf gives an infinite margin and passes.
3. **dt:** every look has dt == 0 (a tie) or dt ≥ DT_MIN.
4. **nonfinite:** every b is finite, or the look is the exact `(+inf, −inf)` tie pair.

`decisions(looks)` is the tuple (crossing indicator, number of looks, futility-stop index).

### 2.2 Equivalence proof, conditional on the premise P: |Δb_k| < EPS at every reached look k of a non-refined replicate

1. The boundary at look k depends only on t_1..t_k, and those come from the draws alone (§0).
2. **The terminal look is data-only.** I_max depends on `state.information`, n_max on `look_n`; LOSS_STOP is identically false and `forced` is false (§0). So the terminal index T is the same under both grids, whatever the boundaries are.
3. **Induction on k < T.** Rule (fut) and P give `sign(S − b_fut^601) = sign(S − b_fut^2001)`. So both grids take the same futility decision at each look up to their shared stop index, and they reach the identical look set.
4. On that look set, rule (eff) and P give the same crossing indicator. One confident crossing settles it; otherwise all looks are confidently below.
5. `S_terminal`, `n_looks`, the crossing indicator and the per-cell sums are therefore identical. Refined replicates use the 2001 records directly. So every result field equals the pure-2001 run with the same seed. ∎ (conditional on P)

### 2.3 Residual risk and audit detection power (Stat b, d)

**Definition.** Let p be a cell's prevalence of **premise violation**: an unrefined replicate with some reached |Δb| ≥ EPS. The audit detects the violation itself, not only a decision flip, so the detectable event is the premise failing.

**P(undetected per cell) ≈ (1−p)^n.** The CAL-b row assumes the violation shows up in that cell's census as well.

| p | Rev 1: 100 audits | **Rev 2: 400 in-run audits** | **Rev 2 + CAL-b (400 chains per cell), 800 checks** |
|---|---|---|---|
| 0.5% | 61% | 13.5% | **1.8%** |
| 1.0% | 37% | 1.8% | **0.03%** |
| 1.5% | 22% | 0.24% | **<0.001%** |

**Choice: both levers.**
- **CAL-b widened to all 49 cells** × 400 full no-stop chains, plus a synthetic low-t/low-dt stress set. This catches structural failures (look 1 at t≈0.06, where the `1/√t` Z-scale amplification bites) **before** the run, so the fix is a larger EPS rather than aborted cells.
- **In-run audit raised to 400 per cell.** This catches in-distribution clustering that CAL-b sampled too thinly.
- A clustered failure confined to one stratum hits several cells of that stratum, so the stratum-level detection probability is higher than the per-cell figures.

**Cost of the audit increase.** Going from 0.5% to 2% at 20k adds 0.015 × 386.7 = **5.8 CPU-h, about 1.1 h of wall time** at P=8×0.65. At 80k the audit rate stays at 0.5% (still 400 per cell), so 80k costs nothing extra. CAL-b costs about 15.4 worker-h (§4).

**Bias bound if a violation escapes.** A violation flips a decision only when S lies within |Δb| of b. For |Δb| up to 2·EPS = 0.04 near the late-look boundaries (φ(b) ≈ 0.03–0.06), that probability is at most about 0.05. So |bias| ≤ p × 0.05.
- At p = 0.5%: at most 2.5e-4, which is 7.6% of δ. This scenario escapes both checks with probability ≤ 1.8% per cell.
- Pure-601 bias, for comparison: 5e-4 to 1e-3, systematic.

**Statement carried into M2:** exact conditional on P, and P estimated with the power table above.

### 2.4 Cost model

Per replicate: τ601 + (f + a) × τ2001, where a is the audit fraction.

- **Refine fraction f:** an upper-bound estimate from Σ_k 2·2ε·φ(b_k) ≈ 0.023 at ε=0.02. Planned at f=3%, budgeted at 5%, measured in CAL-c.
- **Per-cell wall time,** one worker, derate 0.65:

| Unit | f=3% | f=5% |
|---|---|---|
| 20k mixed cell (a=2%) | 1.05 h | 1.19 h |
| 20k same-side 16-look cell or control (a=2%) | 1.91 h | 2.20 h |
| 80k sub-run: mixed, 20k reps (a=0.5%) | 0.95 h | 1.09 h |
| 80k sub-run: control, 20k reps | 1.69 h | 1.98 h |
| CAL-a pure 2001 × 2000 reps (cells 0 and 15; cell 46) | 0.69 h; 1.47 h | — |
| CAL-b census × 400 reps (same-side; mixed) | 0.38 h; 0.18 h | — |
| CAL-c refined × 2000 reps | ≤ 0.22 h | — |

- **20k stage total:** 51.8 CPU-h at f=3%, 59.5 CPU-h at f=5%. That is 10.0–11.4 h ideal at P=8×0.65. Cells skipped as infeasible (e.g. all_no at k=3) cost about 0.
- **80k stage, expected:** about 2.5 cells × 4 sub-runs ≈ 11 worker-h. **Worst case:** 17 cells (16 mixed plus the control) ≈ 72 worker-h.

**80k as 4 pinned sub-streams.** Each rerun is 4 × 20k with seeds `SEED_RERUN_BASE + 100·j + cell_index`, j=0..3, all pinned before any number exists. The four are pooled into **one** 80k result by exact integer and sum arithmetic.
- This is still "rerun once at 80000 reps with fresh seeds". It pools only within the rerun and never with the 20k result (Rev 2.1 A).
- It exists because a single-stream 80k mixed cell (≈3.8–4.4 h) fits only the 02:10Z segment. At about 1 h each, sub-runs fit segments A and B.
- **Reviewers must check this explicitly.**

## 3. Seeds, provenance, resume, orchestration

### 3.1 Seed bases (Stat c)

| Stage | Seed | Range |
|---|---|---|
| 20k (gated) | `SEED_BASE + i` = 20260925_000 + i | …000–…048 |
| 80k (gated) | `SEED_RERUN_BASE + 100·j + i` = 20260925_500 + 100j + i | …500–…848 |
| CAL-a, CAL-b, CAL-c | `SEED_CAL_BASE + i` = 20260925_900 + i | …900–…948 |

The three ranges are pairwise disjoint. CAL never inspects a gated replicate. All three bases land in the pre-CAL freeze merge.

### 3.2 Code provenance (Arch 2)

- **Snapshot.** The driver takes `--code-sha <sha>` (required) and uses `~/.local/share/breezy/aud07_m1c/code-<sha>/`.
  - If the directory is absent: `git -C /home/jon/breezy archive <sha> | tar -x -C …`, then write `SNAPSHOT_SHA`.
  - If it is present: verify that `SNAPSHOT_SHA == <sha>` and **never re-archive**.
  - Day 2 onward reuses the same directory.
- **Stamping.** The CLI receives `--code-sha` (no `.git` in the export) and stamps it in every row.
- **Startup assertions.** Each of these must resolve under the snapshot root `_REPO_ROOT`; the run raises otherwise:
  - `Path(breezy.__file__).resolve()`. This catches an editable install in `.venv`, or a stray `PYTHONPATH`, pointing at `/home/jon/breezy/src`.
  - `aud06a_qty_envelope_sweep.__file__`.
  - The path the `family_tally_v2` spec was loaded from.
- **Interpreter.** Python is `/home/jon/breezy/.venv/bin/python`. Every row stamps `numpy_version` and `scipy_version`.

### 3.3 Stage separation and idempotent resume (Arch 3, Py 5)

- **Out-dirs.** `~/.local/share/breezy/aud07_m1c/runs/<sha12>/{cal_a,cal_b,cal_c,20k,80k}/cell_<ii>[_s<j>].jsonl`, one file per (cell, sub-stream).
  - The CLI takes `--stage` and refuses an `--out` whose parent directory name is not that stage.
- **Resume, in `run_chunk`:**
  1. **Killed write:** if the file is non-empty and does not end in `\n`, truncate it to the last `\n` (or to empty) and log to stderr.
  2. Any complete line that fails to parse → raise.
  3. Resume key = `(stage, cell_index, substream, seed, n_reps, boundary_mode, coarse_npts, eps_pin_sha256, code_sha, numpy_version, scipy_version)`.
     - Exact match → the cell is done; skip it.
     - Same `(stage, cell_index, substream)` with any other key difference, including `code_sha` → **raise**.
     - A row whose `stage` differs from `--stage` → **raise**.
  4. Rows are written as one `write` plus `flush` plus `os.fsync`.
- **Merge** (`aud07_m1c_merge.py --stage <s>`):
  - dedupes identical rows (ignoring `wall_s`); raises on conflicting duplicates;
  - raises on mixed stages, and on more than one `code_sha` or `eps_pin_sha256` across `{cal_c, 20k, 80k}`;
  - checks coverage: 20k = 0..48; `--mixed-only` = 0..15 plus 48, used to build the rerun list early; 80k = the INDETERMINATE set × 4 sub-streams;
  - pools the 80k sub-streams from integer counts and raw sums (`sum_s_terminal`, `sum_s2_terminal`, `sum_look_count`);
  - writes the sorted JSONL plus its sha256.

### 3.4 Driver and failure surfacing (Arch 4)

- **`aud07_m1c_sweep.sh`** takes `--code-sha --stage --queue <file> --cutoff <ISO-UTC> -P 8`.
  1. **Refuses to start** if any `FAILED` file exists under `runs/<sha12>/*/`. This is fail-closed until the coordinator resolves it.
  2. Runs `xargs -P 8 -n 1 aud07_m1c_cell.sh`.
  3. On xargs exit 123/124/125, prints every entry of `<stage>/FAILED` to stderr and exits 1. The systemd unit then shows `failed`, visible in `journalctl --user -u aud07-m1c-*`.
- **`aud07_m1c_cell.sh <i[:j]>`:**
  1. Reads `est_wall`. That is the class median of `wall_s` from completed rows of this stage, or the §2.4 f=5% figure × 1.15 when there are none.
  2. If `now + est_wall > cutoff`, appends to `DEFERRED` and exits 0.
  3. Otherwise runs the CLI. On a non-zero exit, appends `<i[:j]> rc=<rc> <utc>` to `FAILED` and exits 255. Exit 255 makes xargs stop launching new cells, so an audit abort halts the whole segment.
- **Environment:** `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1`. This controls oversubscription only (§3.5).
- **Queue order:** the control first (cell 48), then the 16 mixed cells, then the same-side cells in descending cost. Mixed-first because the 80k reruns, which are the critical path, depend only on the mixed and control results.

### 3.5 Determinism (Py)

- The kernels are elementwise numpy/scipy, not BLAS. Bitwise equality between CAL-a and CAL-c rows, and bitwise reproducibility on resume, rely on three things:
  - **the same numpy/scipy build**, stamped and made part of the resume key;
  - **the same host and CPU**: numpy's SIMD dispatch depends on CPU features, and all runs are on this host;
  - the same input order.
- The thread variables are there only to prevent 8 × N-thread oversubscription.
- If CAL equality fails at float level only, investigate the cause. Never relax the check.

### 3.6 Recovery from a mid-sweep bugfix (Py)

1. Fix the bug and merge it. The fix produces a new `sha`, so create a new snapshot `code-<newsha>`.
2. The resume guard raises for every file stamped with the old sha. Rename those files; **never delete them**. Rename `runs/<oldsha12>/` to `runs/<oldsha12>.superseded-<utc>/`. This is reversible.
3. The merge requires one `code_sha` across `{cal_c, 20k, 80k}`. A new sha therefore re-runs CAL-c and every affected stage in full.

That cost is the reason for the smoke run in §4.4. It runs before the first gated segment to catch plumbing bugs cheaply.

## 4. Schedule (Arch 1)

### 4.1 Decision: segmented runs under `breezy-studies.slice` holding `$XDG_RUNTIME_DIR/breezy-studies.lock`

**No-lock alternative, evaluated and rejected (edit 1: rests on the house rule and slice accounting, not on an OOM claim).**

It would run outside the slice with no lock, avoiding only k1 (01:30–02:10Z) and the node window (16:50–01:00Z).

- **Memory math.** The host has 30G. In-window lock-takers are capped at 1–6G each (this run's own `MemoryMax=6G`, and every OTHER slice unit observed to date has run inside that same 1–6G band). The no-lock alternative's worst-case concurrent total on THIS host is therefore about 19–20G, which fits comfortably under 30G. **The earlier OOM claim is withdrawn:** it is not supported once the actual per-unit caps are accounted for.
- **The actual basis for rejection is the house rule plus slice accounting, not a memory-safety argument:** running outside `breezy-studies.slice` with no lock would break the "one heavy job at a time" house rule this repo already runs on, and would let this study's CPU/IO contend directly with the ingest/capture pipeline and other slice members during hours the slice exists specifically to serialize. That contention risk to the capture pipeline is the real cost, independent of whether the host's total memory happens to fit.
- **Gain:** about 13 h/day of slots instead of about 10.8 h/day, roughly 20%, saving at most about half a day in the worst case.
- **Verdict:** rejected. The no-lock option buys a 20% schedule gain by breaking the one-heavy-job-at-a-time house rule and taking on unmanaged contention risk against the capture pipeline -- not because it would exhaust host memory.

### 4.2 Segments

Each segment is its own transient unit:

```
systemd-run --user --unit=aud07-m1c-<stage>-<YYYYMMDD>-<A|B|C> --slice=breezy-studies.slice \
  --on-calendar='<date> <start> UTC' \
  -p MemoryMax=6G -p MemorySwapMax=0 -p RuntimeMaxSec=<cutoff−start> \
  --setenv=OPENBLAS_NUM_THREADS=1 --setenv=OMP_NUM_THREADS=1 --setenv=MKL_NUM_THREADS=1 \
  -- flock -w <W> "$XDG_RUNTIME_DIR/breezy-studies.lock" \
     ~/.local/share/breezy/aud07_m1c/code-<sha>/scripts/analysis/aud07_m1c_sweep.sh \
     --code-sha <sha> --stage <s> --queue <q> --cutoff <date>T<cutoff>Z -P 8
```

| Seg | Start | Cutoff (= hard kill) | `flock -w` | Next lock-taker | Notes |
|---|---|---|---|---|---|
| **A** | 02:10Z | 08:40Z | 1800 s | 09:00Z rotate | Starts after k1 (01:35Z, 21–27 min, 12G). k1 peak plus ours (12 + 6 = 18G) would exceed the slice's 16G, so A must start after k1; `-w` waits out any k1 overrun. |
| **B** | 09:35Z | 13:05Z | 900 s | 13:30Z asos+MOS | Starts after 09:25Z retention. |
| **C** | 14:05Z | 14:50Z | 600 s | 15:00Z position-monitor | The refresh can run to about 14:00. The cutoff is tightened from 14:55Z to leave a 10-minute margin. Overlaps with the lock-free scorer (5G) and live-tally (2G): if both sit in the slice, 13G ≤ 16G; host total ≈ 19G. |

**Why no study ever skips:**
- We only take the lock inside a gap.
- `RuntimeMaxSec` kills the whole cgroup (flock plus python) by the cutoff, which releases the lock at least 10 minutes before the next `flock -n` taker.
- A study that already holds the lock makes us wait (`-w`); we never make it skip.
- Node window: 16:50–01:00Z. No segment runs 15:00–02:10Z.

**Edit 2 -- two additional notes, binding:**
- A reboot or `daemon-reload` mid-segment can fire a `Persistent=true` catch-up run while we hold the lock. This is an **accepted residual risk**, logged against AC6 (§9 acceptance criteria) rather than engineered away: the catch-up run would contend for the same lock, `flock -w` would make it wait rather than skip, and worst case it delays that unit's own next scheduled occurrence by up to one segment. No capture-path risk results, because the lock discipline itself is unaffected.
- The transient `systemd-run --on-calendar` units in this schedule do **not** survive a reboot (they are transient, not persistent enabled units) -- so a reboot between segments simply means that segment's unit does not exist for that occurrence. It is silently NOT re-armed for the same calendar slot; the coordinator re-arms it (or the next day's equivalent unit re-arms fresh) the following day rather than treating a missed segment as an incident.

### 4.3 Stage-to-segment fit

- **80k sub-runs** (≈1 h mixed, ≈1.7–2 h control) fit A and B.
- **20k same-side cells** (1.9–2.2 h) fit A and B.
- **C** (45 min) fits only CAL-b cells (0.18–0.38 h), merges, and the gate script.

### 4.4 Day-by-day timeline

| When (UTC) | Work | Exit condition |
|---|---|---|
| **09-25, 08:35–~13:45** | TDD implementation (RED→GREEN, tests 17–33), python-reviewer and stat-reviewer on the diff, merge to the integration branch, then `scripts/ci/run_tests_no_egress.sh` and `lint-imports`. The merge freezes the gate module, the seed bases, `AUDIT_TARGET=400`, the EPS rule (floor 0.02, 3×) and the pin validator. | Merged sha S, gate green. **Hard deadline 16:15Z (merge freeze).** Missing it slips everything below by exactly one day. |
| 09-25, ~13:50 | Snapshot `code-S`. Smoke run (`--stage smoke`, cells 0 and 16, 20 reps, P=2, scratch dir; about 2 min, not heavy). Driver test: a forced failing cell must produce `FAILED` and exit 1; resume must skip. | Smoke green. |
| **09-25 C, 14:05–14:50** *(only if merged by 13:45)* | CAL-b, part 1: about 16 same-side census cells. | Resumable. |
| **09-26 A, 02:10–08:40** | CAL-b remainder together with CAL-a: about 12.3 worker-h if part 1 ran, else 18.3, so about 1.6–2.3 h. Then `aud07_m1c_census.py`, which writes `eps_pin.json`: EPS, DT_MIN, the census sha, the stress-set results. Then CAL-c (≈0.25 h). Then `aud07_m1c_cal_check.py`, automatic:<br>• CAL-c row == CAL-a row on every result field;<br>• 0 audit disagreements;<br>• f reported.<br>**Pass → the 20k stage starts in the same unit at about 04:10–04:45**, running the control, all 16 mixed cells, and about 4–8 same-side cells. **Fail → stop:** no 20k run, `FAILED` is written, investigate. | Mixed and control 20k rows complete. |
| 09-26, after A | `aud07_m1c_merge.py --stage 20k --mixed-only`, then `aud07_m2_gate.py --stage20k`, which emits the INDETERMINATE list and so the 80k queue. Commit the CAL evidence (docs only). | Rerun queue fixed. |
| **09-26 B, 09:35–13:05** | Per worker: one 20k same-side cell plus one 80k mixed sub-run. That is about 8 cells and about 8 sub-runs, which is expected to cover about 2 of the ~2.5 expected reruns. | — |
| 09-26 C | Idle, or leftover CAL-b if CAL was re-run. | — |
| **09-27 A** | The remaining ~17 same-side 20k cells: 2–3 per worker, depending on f. Remaining 80k sub-runs. | **Expected:** all 20k done and all reruns done (f≈3%). |
| 09-27 B | Overflow at f=5%: at most 1–2 same-side cells, and sub-runs. | — |
| 09-27, after B | Final 20k and 80k merges, `aud07_m2_gate.py --final`, draft the M2 artefact, peer review. | **Expected ruling 09-27. At f=5%: 09-28.** |
| Worst case | All 17 cells INDETERMINATE → 68 sub-runs, about 72 worker-h. This adds 09-27 B plus 09-28 A and B. | Ruling by 09-29. |

## 5. Calibration job (CAL), on `SEED_CAL_BASE` only

- **CAL-a (spot check):** `run_cell(npts=2001)` pure, 2000 reps, on:
  - cell 0: mixed, the fact-3 cell;
  - cell 15: the last mixed cell, the other dispersion/k extreme;
  - cell 46: 16-look all_yes matched to cell 15.
- **CAL-b (census):** all 49 cells × 400 reps. For each rep, run both the 601 and the 2001 chains over the full no-stop `t` sequence, which is a superset of any reached prefix, with `is_terminal` at the natural terminal look. Record:
  - per-depth max and p99.9 of |Δb_eff| and |Δb_fut| on the Z-scale;
  - the minimum dt and the minimum t_1, per cell.

  **Stress set:** synthetic histories with t_1 ∈ [½·min observed, 0.15] and dt on a log grid down to 1e-4. The stress set can only lower DT_MIN, and only where it shows Δb ≤ EPS/3.
- **Pin (`eps_pin.json`, data only; the code sha does not change):**
  - `EPS = max(0.02, 3 × census global max)`;
  - `DT_MIN = min(realised min dt, lowest stress dt with Δb ≤ EPS/3)`;
  - the census file sha and `code_sha`.

  The refined CLI requires `--eps-pin`. It validates `EPS ≥ 0.02`, `EPS ≥ 3 × census max`, and that the census sha and `code_sha` match the running code. It stamps `eps_pin_sha256` on every row.
- **If f > 10%:** switch to a per-depth `eps_k` table in the pin, using the same validation rule per depth. A new pin requires a CAL-c re-run.
- **CAL-c:** refined `run_cell` on the CAL-a cells and seeds.

## 6. M2 ruling artefact steps

1. **Pre-CAL freeze merge (09-25):** `scripts/analysis/aud07_m2_gate.py`, a set of pure functions.
   - `classify_cell(count, n)` with literals:
     - `ALPHA = 0.025`;
     - `V_THRESHOLD = 0.0283`;
     - `V_CONF = 0.95`;
     - `I_CONF = 1 − 0.05/16`;
     - each cited to amendment §4 and Rev 2.1 A.

     It uses `clopper_pearson_upper` / `clopper_pearson_lower` (`aud06a_qty_envelope_sweep.py:393-404`, both one-sided).
   - `final_class(r20k, r80k | None)`: the 80k result replaces the 20k result; INDETERMINATE at 80k becomes I.
   - `branch(mixed16)`: V only if all 16 are V; I if any is I.

   The gate code exists before any number does.
2. After the mixed and control 20k rows: `--stage20k` produces the rerun list.
3. After the 80k stage: `--final` produces the table, pasted verbatim.
4. Write `docs/evidence/RULING_aud07_mixed_side_ldobf_2026-09-__.md` with:
   - the verbatim gate text and the amendment sha;
   - the freeze sha S; the `eps_pin` and census shas; the 20k and 80k merged-JSONL shas;
   - per cell: rate, CP-upper, CP-lower, n, class;
   - the AUD-06a rates side by side, joined on `(q_max=1, dispersion, k, side_mix)`;
   - the control (test 7);
   - L-41 diagnostics (`loss_stop_count == 0`; `mean_s_terminal`/`var_s_terminal`);
   - **method disclosure:**
     - the refined mode, EPS, DT_MIN;
     - f per cell by trigger;
     - audit totals and max |Δb|;
     - the CAL byte-equality result;
     - the §2.2 conditional proof;
     - the §2.3 power table and bias bound;
     - the 80k sub-stream construction;
   - the CAL rates, disclosed as not gated;
   - citations of amended L-40 and `21213d5`.
5. Peer review by prediction-market-reviewer and architect, then the DoD (ii) branch, then the `C-AUD07-MIXED-SIDE` row.

## 7. File-by-file changes

**`/home/jon/breezy/scripts/analysis/aud07_live_rule_crossing_sim.py`**

- **Constants:** `COARSE_NPTS = REDUCED_NPTS`, `SEED_CAL_BASE = 20260925_900`, `SEED_RERUN_BASE = 20260925_500`, `N_SUBSTREAMS_80K = 4`, `AUDIT_TARGET = 400`.
- **Functions:**
  - `load_eps_pin(path, *, code_sha) -> EpsPin`
  - `_needs_refine(looks, *, eps, dt_min) -> str | None`
  - `_run_replicate(draws, *, artefact, mode, pin, audit) -> (looks, reason, audit_stats)`
  - `AuditPremiseViolation(Exception)`
  - `_assert_snapshot_imports(root)`
  - `seed_for(stage, cell_index, substream)`
- **`run_cell`** gains `boundary_mode: Literal["pure","refined"] = "pure"`, `eps_pin: EpsPin | None = None`, and `audit_every: int | None = None`. The pure default keeps existing tests unchanged.
- **`run_chunk`:** stage-aware and idempotent (§3.3).
- **CLI:** `--stage`, `--code-sha`, `--eps-pin`, `--substream`, `--boundary-mode`.
- **Docstring** cites the refined mode. The existing `REDUCED_NPTS` comment stays true: 601 is never a decision grid on its own.

**`M1cCellResult`.** New fields go **after** `skip_reason`, all defaulted, so the dataclass definition stays valid:

```python
stage: str | None = None
code_sha: str | None = None
substream: int | None = None
boundary_mode: str = "pure"
coarse_npts: int | None = None
eps: float | None = None
dt_min: float | None = None
eps_pin_sha256: str | None = None
audit_every: int | None = None
refined_count: int = 0
refine_reasons: tuple[tuple[str, int], ...] = ()   # sorted pairs: frozen/slots-safe, no mutable default
audit_reps: int = 0
audit_max_abs_delta_b: float | None = None
audit_disagreements: int = 0
sum_s_terminal: float = 0.0
sum_s2_terminal: float = 0.0
sum_look_count: int = 0
numpy_version: str | None = None
scipy_version: str | None = None
```

`to_json` is extended to match. In refined mode, `npts` is 2001, the decision grid.

**New files:**

| File | Purpose |
|---|---|
| `scripts/analysis/aud07_m1c_census.py` | CAL-b census and stress set; writes the census JSON and `eps_pin.json`. |
| `scripts/analysis/aud07_m1c_cal_check.py` | Automatic CAL acceptance. |
| `scripts/analysis/aud07_m1c_merge.py` | §3.3 merge. |
| `scripts/analysis/aud07_m2_gate.py` | §6.1 gate. |
| `scripts/analysis/aud07_m1c_sweep.sh`, `aud07_m1c_cell.sh` | §3.4 driver. `AUD07_CELL_CMD` override exists for tests only. |
| `tests/unit/test_aud07_m1c_orchestration.py` | Tests 22–26, 29. |
| `tests/unit/test_aud07_m2_gate.py` | Tests 30–33. |

**Untouched:** `gs_boundary_artefact.py`, `family_tally_v2.py`, the M1b golden, tests 4a and 4b, `inputs_sha256`. `lint-imports` is unaffected (scripts only).

## 8. Tests (RED first)

The gate-fast tests use a cheap grid pair: coarse=151, fine=401.

| # | Test |
|---|---|
| 17 | `test_refined_run_equals_the_fine_grid_run_field_for_field_and_exercises_both_paths`: one mixed and one 16-look cell, about 200 reps. `to_json` must be equal excluding the metadata keys, **and** `0 < refined_count < n_reps`. |
| 18 | `test_refinement_has_teeth`: a stub adds offset d to the coarse b. EPS > d → equal. EPS < d with refinement disabled → a disagreement is detected. |
| 19 | `test_refine_rules_eff_until_confident_crossing_fut_every_look`, on hand-built LookRecords. |
| 20 | `test_small_dt_nonfinite_and_solver_error_force_the_fine_grid`. |
| 21 | `test_refined_mode_consumes_the_rng_identically_to_pure_mode`: the same post-cell `rng.getstate()`. |
| 22 | `test_audit_premise_violation_aborts_the_cell_writes_no_row_and_the_driver_exits_nonzero`: `AUD07_CELL_CMD` stub returning rc=1 → `FAILED` lists the cell, the driver exits 1, and a second driver start refuses. |
| 23 | `test_resume_skips_done_cells_never_duplicates_and_raises_on_code_sha_mismatch`: also covers `eps_pin_sha256`/version mismatch, and a file without a trailing `\n` being truncated to the last `\n`. A complete bad line raises. |
| 24 | `test_stage_separation`: `--out` outside `<stage>/` raises; a foreign-stage row in the file raises; the merge refuses mixed stages or mixed shas. |
| 25 | `test_merge_rejects_conflicting_duplicates_and_incomplete_coverage`, including `--mixed-only`. |
| 26 | `test_snapshot_import_assertion_raises_when_breezy_resolves_outside_the_snapshot`. |
| 27 | `test_seed_bases_are_pairwise_disjoint_across_20k_80k_substreams_and_cal`. |
| 28 | `test_eps_pin_validation_rejects_eps_below_floor_or_below_3x_census_max_or_foreign_sha`. |
| 29 | `test_80k_substream_pooling_equals_direct_accumulation`: **exact `==` only on the integer fields (`crossing_count`, `n_reps`, `sum_look_count`); a relative tolerance of about 1e-12 on the float sums** (`sum_s_terminal`, `sum_s2_terminal`) (edit 3). |
| 30 | `test_gate_literals_are_the_amendment_values`. |
| 31 | `test_classify_cell_at_v_and_i_boundaries_at_20k_and_80k`. |
| 32 | `test_80k_replaces_never_pools_with_20k_and_indeterminate_after_rerun_is_i`. |
| 33 | `test_branch_v_needs_all_16_any_i_fires_i`. |

**Evidence, outside the gate:** CAL-a/b/c and the smoke run. After every merge, run `run_tests_no_egress.sh` and `lint-imports`, with `PYTHONPATH` set in any worktree.

## 9. Acceptance criteria

1. Tests 17–33 are green; the full gate and `lint-imports` are green; tests 4a/4b and the M1b golden are byte-unchanged.
2. The gate module, all three seed bases and `AUDIT_TARGET` are merged in sha S **before** CAL starts. Every CAL, 20k and 80k row carries `code_sha == S` and a single `eps_pin_sha256`.
3. CAL passes: CAL-c equals CAL-a on every result field; 0 audit disagreements; the census covers 49 cells plus the stress set; EPS ≥ max(0.02, 3 × census max); f is reported.
4. The 20k merge covers cells 0..48 exactly once with no conflicts. Every row has `audit_reps ≥ 400` (non-skipped cells), `audit_disagreements == 0` and `loss_stop_count == 0`.
5. The 80k merge covers exactly the INDETERMINATE set × 4 sub-streams on `SEED_RERUN_BASE`.
6. Journal timestamps show every unit held the lock only inside A, B or C. No study logged a skip for a held lock on those days. Nothing ran between 15:00Z and 02:10Z. No node unit was touched. **(edit 2 residual: a reboot/daemon-reload catch-up run firing while we hold the lock is an accepted exception to "no study ever skips a lock wait", never a violation of this criterion, provided `flock -w` recorded a wait rather than a skip.)**
7. The M2 artefact applies the gate through `aud07_m2_gate.py`, carries the §2.2/§2.3 disclosure, and has peer sign-off.
8. Amendment §6 AC8 holds: no order, no registration, no halt cleared, no operator-reserved value touched.

## 10. Risks and mitigations

| Risk | Sev | Mitigation |
|---|---|---|
| Premise P fails out of sample | MED | Stress set plus the DT_MIN guard; 400 audits per cell (§2.3 power table); bias bound ≤ p·0.05; fail-closed abort. |
| Look-1 small-t Z-scale amplification inflates EPS and f | MED | Per-depth census; per-depth `eps_k` fallback; performance-only within P. |
| f above budget | MED | Measured in CAL-c. At f=5% the ruling slips to 09-28 (timeline). |
| The code merge misses the 16:15Z freeze | MED | The whole timeline shifts by one day; there is no partial path. |
| A segment overruns its cutoff | LOW | Measured `est_wall` × 1.15; `RuntimeMaxSec` hard kill; lost work ≤ 1 cell per worker, resumed idempotently. |
| A mid-sweep bugfix forces a full-stage rerun | MED | Smoke run plus reviews before A. Rename, never delete (§3.6). |
| k1 overruns into A | LOW | `flock -w 1800`; the queue cutoff check absorbs the lost time. |
| Byte equality broken by a build or CPU difference | LOW | Versions in the resume key; same host and `.venv`; investigate, never relax. |
| Reviewers reject the 80k sub-streams | LOW-MED | Fallback: single-stream 80k, A segment only, one cell per worker (≈4.4 h). Worst case extends by about 2 days. |
| A reboot/daemon-reload fires a `Persistent=true` catch-up while the lock is held (edit 2) | LOW | Accepted residual, logged against AC6; `flock -w` serializes it rather than skipping either job; no capture-path exposure. |

## 11. Confidence

| Claim | Confidence |
|---|---|
| Exact equivalence conditional on P (§2.2, loop semantics verified at `family_tally_v2.py:672-741` and `current_rung_hold_v2.py:456-459`) | **HIGH** |
| P holds on the run distribution (census plus 400 audits per cell; power in §2.3) | **MEDIUM-HIGH** |
| Residual bias ≤ 7.6% of δ, even in the p=0.5% escape scenario | **MEDIUM**: the 0.05 near-boundary factor is analytic |
| The segmented schedule never makes a study skip | **HIGH**: architect-verified `-n` takers, gaps, and hard kills; house-rule/slice-accounting basis for the no-lock rejection (edit 1), not a memory-safety claim |
| Ruling by 09-27 (expected), 09-28 (f=5%), 09-29 (worst case) | **MEDIUM**: depends on the merge before 13:45Z/16:15Z, on f, and on the INDETERMINATE count |
| Gate, reps and two-stage design unchanged; 80k sub-streams consistent with Rev 2.1 A | **HIGH / MEDIUM-HIGH**: the sub-streams need explicit reviewer confirmation |

**Key files:**
- `/home/jon/breezy/scripts/analysis/aud07_live_rule_crossing_sim.py`
- `/home/jon/breezy/scripts/analysis/family_tally_v2.py`
- `/home/jon/breezy/src/breezy/persistence/gs_boundary_artefact.py`
- `/home/jon/breezy/src/breezy/settlement/current_rung_hold_v2.py`
- `/home/jon/breezy/scripts/analysis/aud06a_qty_envelope_sweep.py`
- `/home/jon/breezy/docs/plans/backlog/AUDIT_2026-09-21/AUD-07-AMENDMENT-2026-09-25.md`

---

## Peer review

Peer review of this Rev 2 (with edits 1-3 applied) plus the resulting implementation (commit(s) on `backlog/aud-07-m1c-exec-2026-09-25`, tests 17-33 green, full suite green, `lint-imports` 7/7 kept):

- **Statistical reviewer: ENDORSE.** The §2.2 equivalence proof conditional on premise P is sound given the verified data-only terminal-trigger facts (§0); the §2.3 audit-detection power table correctly motivates the combined CAL-b-widening plus 400-in-run-audit choice. Confirmed explicitly per §2.4's own instruction: **the 80k stage's 4 pinned sub-streams of 20000 reps each are exactly `Binomial(20000, p)` per sub-stream, and their pooled sum is exactly `Binomial(80000, p)` under H0** (integer crossing counts and reps are additive across independent sub-streams with a common p), so the pooling is statistically equivalent to a single un-split 80000-rep stream and is **equivalent to Rev 2.1 A's "rerun once at 80000 reps with fresh seeds"** -- never a relaxation of that requirement. Test 29's exact-integer/1e-12-relative-tolerance split (edit 3) is the correct way to encode that equivalence in a fast unit test.
- **Architect: APPROVE**, with the following S0 facts recorded as the basis for approval: (i) `run_sequential_looks`'s terminal triggers (`reached_loss_stop`, `reached_i_max`, `reached_n_max`, `forced`) are verified data-only, independent of the boundary function, which is the structural fact the whole refine-on-proximity design rests on (§0, §2.2 step 2); (ii) the no-lock schedule alternative is correctly rejected on the "one heavy job at a time" house rule and slice/contention accounting (§4.1, edit 1) rather than on the withdrawn OOM claim -- the revised rationale is the accurate one and is now the one of record; (iii) the reboot/daemon-reload catch-up residual and the non-persistence of transient `--on-calendar` units (§4.2, edit 2) are correctly scoped as accepted residuals against AC6, not defects requiring further engineering.
- **Python reviewer: HIGH.** `M1cCellResult`'s new fields are appended after `skip_reason`, all defaulted (dataclass validity preserved); `run_cell`'s pure-mode default path is byte-unchanged (tests 1-16 and the M1b golden stay green); the resume-key/stage-separation/merge machinery raises rather than silently resolving every ambiguous case (conflicting duplicate, foreign-stage row, cross-sha merge, incomplete coverage); `AuditPremiseViolation` propagates uncaught so an audited cell aborts with no row written, matching test 22's contract.
