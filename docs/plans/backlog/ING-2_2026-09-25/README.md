# ING-2: bounded quote-tape ingest (2026-09-25)

- **S1, definitions-first.** DELIVERED (merge c5d1e24, T3b fix c7d2b85). See `ING-2_S1_plan_r4_DELIVERED.md`.
- **S2, per-run deadline.** Owed. Source: AC5/AC7, T6/T7/T9 and the deadline items in `ING-2_full_plan_r1_S2_S3_source.md`.
- **S3, bounded memory.** Owed, and Stage 0 measurement comes first. Source: F3/F4, AC1/AC2/AC6 and T4/T5/T8 in `ING-2_full_plan_r1_S2_S3_source.md`.

That r1 plan was reviewed REQUEST_CHANGES. The architect's slicing is binding:
- S2 keeps the unit at 4G/6G, adds `OOMScoreAdjust`, and sets the deadline at 600–720s rather than 1500s.
- S3 lands only after Stage 0 shows which of F3 and F4 dominates.
- The deadline is checked only between (instance, type) units, and one native unit can overrun it. Name that as a residual risk.
- The timers need no flock, because systemd runs one instance of a unit at a time.

Each slice needs a fresh plan and peer review before it is implemented.
