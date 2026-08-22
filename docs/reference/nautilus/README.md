# NautilusTrader documentation — vendored reference

Fetched 2026-08-22. This directory is **third-party documentation stored verbatim for offline,
version-locked reference**. Nothing here is Breezy's own documentation, and nothing here is edited.

## Read this first: two different traps

Breezy pins **nautilus-trader 1.231.0** and uses its **Cython Python** API. Two separate things will
mislead you, and they are easy to confuse with each other.

### Trap 1 — the website serves a different major version

    https://nautilustrader.io/docs/...            →  `latest` = 2.x / develop
    https://nautilustrader.io/docs/md/nightly/...  →  the unreleased develop branch
    https://nautilustrader.io/docs/md/1.231.0/...  →  404 — no version-pinned URL exists

Searching the web for "NautilusTrader docs" lands on a **later major version** than the one we build
against. That has already produced at least one wrong architectural conclusion on this project.

The reliable version tell is an **absence**, not a presence: `customdataclass` occurs **0 times** in
the fetched 2.x corpus. If a page discusses custom data and never says `customdataclass`, it is not
describing our library.

### Trap 2 — 1.231.0 ships three API surfaces, and the docs cover the wrong two

Within the single pinned version there are three parallel surfaces. The tag's own docs are
**Rust-first and PyO3-forward**; the Cython Python API Breezy actually uses is the least documented
of the three. `register_arrow` appears in exactly **one** file of the 206-page tag tree.

| Surface | Custom data | Actor | DataType first arg | Breezy uses it? |
|---|---|---|---|---|
| **Cython Python** | `@customdataclass`, `register_arrow` | `Actor` | **class object** — `DataType(WeatherObs, meta)` | **Yes — this is us** |
| PyO3 Python | `@customdataclass_pyo3`, `nautilus_pyo3.register_custom_data_class` | — | **string** — `DataType("Name", meta)` | No |
| Rust | — | `DataActor`, `DataActorCore` | — | No |

Verified against the installed 1.231.0 (`.venv`), not inferred:

```
from nautilus_trader.model.custom import register_custom_data_class  → ImportError
from nautilus_trader.common.actor  import DataActor                  → ImportError
DataType("GreeksData", {})   → TypeError: expected type, got str
DataType(GreeksData,   {})   → OK
nautilus_pyo3.register_custom_data_class                             → exists
```

So `register_custom_data_class`, `DataActor` and string-first `DataType` are **not** 2.x tells —
they are present in 1.231.0, on surfaces we do not use. In the tag docs, `DataActor` appears only in
Rust pages (`concepts/rust.md`, `how_to/write_rust_actor.md`, and `concepts/actors.md:61`: *"Rust
authors implement `DataActor`"*), and `register_custom_data_class` only in the PyO3 sections of
`concepts/custom_data.md` and `concepts/data/index.md`.

**Practical consequence:** when a page in `v1.231.0/` seems to contradict the installed library,
check which surface it is describing before concluding the docs are wrong. Most apparent
contradictions are surface mismatches, not errors.

### The one-token check

Grep the page for **`nautilus_pyo3`**. Present → 1.231.0-era. Absent, with `_libnautilus` or
`DataActor` present → 2.x, wrong for us. (Counts: `nautilus_pyo3` appears 41× in the v1.231.0 tree
and **0×** in the 2.x corpus.)

The costliest single falsehood in the 2.x corpus:

> *"The public Python API does not yet define an interface for implementing an out-of-tree adapter
> entirely in Python… Custom venue integrations currently use the Rust adapter traits."*

**False for 1.231.0.** This wheel ships `LiveDataClient`/`LiveMarketDataClient`
(`live/data_client.py:82,320`), `LiveDataClientFactory` (`live/factories.py:27`), an adapter
`_template/`, and a pure-Python Polymarket adapter (38 `.py` files, 0 `.so`). Believing the 2.x
statement pushes the whole design toward Rust for no reason.

### The vendored 1.231.0 docs contain their own errors

They are authoritative for *version*, not infallible. Confirmed defects in the tag tree:

- `BacktestDataConfig(data_type=...)` — shown in `concepts/options.md:164` and
  `concepts/backtesting/apis-and-runs.md:120`. `data_type` is a read-only property; the kwarg raises
  `TypeError`. The field is `data_cls`.
- `data_cls="pkg.mod.Class"` dotted form at `concepts/data/index.md:947`. Resolution does
  `rsplit(":", 1)` — the dotted form raises `ValueError` mid-run. Use the class object or `"pkg.mod:Class"`.
- `LiveNode.builder(...)` wiring shown in `concepts/live.md`, `integrations/deribit.md`,
  `integrations/derive.md`. `nautilus_trader.live.LiveNode` does not exist; use `TradingNode` +
  `add_data_client_factory(name, FactoryClass)`.

When a doc example and the installed source disagree, **the source wins** — see precedence below.

## Digests

Breezy-authored distillations, each cross-checked against the installed library by execution:

| File | Covers |
|---|---|
| `digests/custom-data-and-persistence.md` | `Data` subclassing, `@customdataclass` limits, `register_arrow`, catalog read/write/delete, schema evolution |
| `digests/actors-msgbus-cache-clock.md` | Actor lifecycle, publish/subscribe topic routing, timers, executor determinism, state persistence |
| `digests/adapters-live-networking.md` | `LiveDataClient` contract, factories, retry, the `HttpClient` capability matrix |
| `digests/backtesting-and-replay.md` | `BacktestNode` vs `BacktestEngine`, `data_cls` forms, `ts_init` ordering, determinism levers |
| `digests/prediction-markets-native-support.md` | `BinaryOption`, `pUSD`, fee models, settlement, the two Polymarket adapters, Kalshi absence |
| `digests/version-drift-1231-vs-upstream.md` | Full 1.231.0 ↔ 2.x delta and the tell-tale token table |

## Layout

| Path | What it is | Authority |
|---|---|---|
| `v1.231.0/` | The `docs/` tree from git tag `v1.231.0` — 206 markdown pages plus the in-tree example `.py`/`.rs` files. Matches the installed library exactly. | **Authoritative** |
| `upstream-latest/site-llms.txt` | `https://nautilustrader.io/llms.txt` — site map and key facts | Version-neutral |
| `upstream-latest/docs-llms-index.txt` | `https://nautilustrader.io/docs/llms.txt` — per-page index of the `latest` docs | 2.x — forward reference only |
| `upstream-latest/docs-llms-full.txt` | `https://nautilustrader.io/docs/llms-full.txt` — the complete `latest` corpus, 2.7 MB / ~313k words | 2.x — forward reference only |
| `digests/` | Breezy-authored distillations of the above, per subject area | Derived; cites both |

## When sources disagree

Precedence, highest first:

1. **The installed source** at `.venv/lib/python3.13/site-packages/nautilus_trader/` — behavior is what ships, not what is written about it. Cite `file.py:line`.
2. **`v1.231.0/`** — the docs published with that exact tag.
3. **`upstream-latest/`** — a later version. Never a basis for a 1.231.0 decision.

Docs-vs-code drift within (1) and (2) is real and is recorded in `digests/`.

## Refreshing

    # authoritative tree, from the pinned tag
    curl -sSL https://codeload.github.com/nautechsystems/nautilus_trader/tar.gz/refs/tags/v1.231.0 \
      | tar -xz --wildcards '*/docs/*'

    # upstream corpus
    curl -sSL https://nautilustrader.io/llms.txt            -o upstream-latest/site-llms.txt
    curl -sSL https://nautilustrader.io/docs/llms.txt       -o upstream-latest/docs-llms-index.txt
    curl -sSL https://nautilustrader.io/docs/llms-full.txt  -o upstream-latest/docs-llms-full.txt

Re-fetch `v1.231.0/` only if the pin changes — and if it does, the digests and
`.claude/skills/nautilus-trader-patterns/SKILL.md` must be re-verified against the new tag, not
carried forward.
