"""Latch-drop (d-hat) triage. Reads Depth10 ONLY for climate days 2026-08-30..2026-10-06, 12:00-13:00Z."""
import sys, json, datetime as dt, random, statistics as st
from pathlib import Path
from decimal import Decimal
import pyarrow.dataset as ds, pyarrow.parquet as pq
sys.path.insert(0, "/home/jon/breezy")
from scripts.analysis import market_calibration_scan as m1
from breezy.analysis import capture_audit_tape as cat
NS = 10**9
FIRST, LAST = dt.date(2026, 8, 30), dt.date(2026, 10, 6)
ROOT = m1.DEFAULT_CATALOG / "data" / cat.DEPTH_DIR
MAIN = {"LAX", "MDW", "MIA", "SFO"}
OUT = Path(__file__).parent

def first_row(inst, day):
    lo = int(dt.datetime(day.year, day.month, day.day, 12, tzinfo=dt.UTC).timestamp()) * NS
    hi = lo + 3600 * NS
    files = []
    for p in sorted((ROOT / inst).iterdir()):
        sp = cat._span(p)
        if sp and sp[1] >= lo and sp[0] < hi:
            files.append(p)
    if not files:
        return None, 0
    prec = cat._precisions(files[0])
    f = ds.field("ts_event")
    best = None
    for p in files:  # files oldest first; take min ts in window across them
        t = ds.dataset([str(p)], format="parquet").to_table(columns=list(cat._DEPTH_COLUMNS), filter=(f >= lo) & (f < hi))
        if t.num_rows == 0: continue
        rows = t.to_pylist()
        r = min(rows, key=lambda r: r["ts_event"])
        if best is None or r["ts_event"] < best["ts_event"]: best = r
    return (cat._depth_body(best, prec) if best else None), len(files)

def collect():
    by_day = {}
    for e in sorted(ROOT.iterdir()):
        spec, kind = m1.classify_directory(e.name)
        if spec is None or not (FIRST <= spec.climate_day <= LAST): continue
        by_day.setdefault(spec.climate_day, []).append((e.name, spec))
    cands = {}; stats = {"norow": 0, "nobid": 0, "rungs": 0}
    for day in sorted(by_day):
        lst = []
        for name, spec in by_day[day]:
            if spec.station not in MAIN | {"NYC"}: continue
            stats["rungs"] += 1
            row, _ = first_row(name, day)
            if row is None: stats["norow"] += 1; continue
            na = m1.no_ask(row)
            if na is None: stats["nobid"] += 1; continue
            if na >= Decimal("0.90"): lst.append((row["ts_event"], spec.station, name))
        cands[day] = lst
    return cands, stats, sorted(by_day)

def sim_day(c, p, hold_draw, rng):
    c = sorted(c, key=lambda x: (x[0], rng.random()))
    free = -1; drop = 0; att = 0
    for ts, _, _ in c:
        t = ts / NS
        if t < free: drop += 1; continue
        att += 1; free = t + hold_draw(p, rng)
    return drop, att

def hold(p, rng):
    if rng.random() < p:
        return 5.0 if rng.random() < 0.2 else 150.0
    return 0.3

def pct(xs, q):
    xs = sorted(xs); k = (len(xs) - 1) * q; i = int(k); j = min(i + 1, len(xs) - 1)
    return xs[i] + (xs[j] - xs[i]) * (k - i)

def main():
    cands, stats, days = collect()
    res = {"stats": stats, "days_with_rungs": len(days)}
    for label, sset in (("main4", MAIN), ("main4+NYC", MAIN | {"NYC"}), ("NYC_only", {"NYC"})):
        per = {d: [x for x in v if x[1] in sset] for d, v in cands.items()}
        nd = [len(v) for v in per.values()]
        pos = {d: v for d, v in per.items() if v}
        first5 = sum(1 for v in per.values() for x in v if x[0] % (86400 * NS) < (12 * 3600 + 5) * NS)
        tot = sum(nd)
        gaps = []; ties = 0; tdays = 0
        for v in pos.values():
            ts = sorted(x[0] for x in v)
            gaps += [(b - a) / NS for a, b in zip(ts, ts[1:])]
            if len(set(ts)) < len(ts): tdays += 1; ties += len(ts) - len(set(ts))
        r = {"days": len(per), "days_with_cands": len(pos), "cand_mean": st.mean(nd), "cand_median": st.median(nd), "total": tot,
             "share_first5s": first5 / tot if tot else None,
             "gap_q": {q: pct(gaps, q) for q in (0, .1, .25, .5, .75, .9, 1)} if gaps else None,
             "gap_share_le_1s": sum(g <= 1 for g in gaps) / len(gaps) if gaps else None,
             "gap_share_lt_150s": sum(g < 150 for g in gaps) / len(gaps) if gaps else None,
             "days_with_shared_ts": tdays, "tied_extra_rungs": ties, "p": {}}
        for p in (0.10, 0.18, 0.33):
            dh = []; att = []
            for d, v in sorted(pos.items()):
                rng = random.Random(f"20261120-{p}-{d}")
                ds_, as_ = zip(*[sim_day(v, p, hold, rng) for _ in range(1000)])
                dh.append(st.mean(ds_) / len(v)); att.append(st.mean(as_))
            n = len(dh)
            r["p"][p] = {"p50": pct(dh, .5), "p90": pct(dh, .9), "mean": st.mean(dh), "se_day": st.stdev(dh) / n ** .5,
                         "attempted_per_day_over_candidate_days": st.mean(att),
                         "attempted_per_day_all_days": sum(att) / len(per),
                         "verdict": "STOP" if pct(dh, .9) > 0.30 else "PASS"}
        res[label] = r
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "cands.json").write_text(json.dumps({str(d): [(a, b) for a, b, _ in v] for d, v in cands.items()}))
    print(json.dumps(res, indent=1, default=str))
main()
