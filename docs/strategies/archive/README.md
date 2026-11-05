# Archived strategy designs

Strategy handoff specs that are either **implemented** (the code, not the doc, is
authoritative) or **design input only** (never built, do not implement directly).
Each file carries a banner stating which.

Live designs remain in `docs/strategies/`.

**The permanent constraint every design here predates or restates:**
`allow_short=False` is permanent, and the empirical top-of-book bid on these
markets is a small fraction of one contract. Any edge that requires selling,
shorting, or fading YES upward is dead on arrival — see
`docs/prompts/GROK_STRATEGY_DESIGN_BRIEF.md` PART 1 for the current plug-in
contract.

Archived 2026-09-01.
