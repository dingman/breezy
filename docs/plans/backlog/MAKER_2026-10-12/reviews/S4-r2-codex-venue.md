# S4 r2 verification — Codex (venue API / order lifecycle) — 2026-10-12
Verdict: READY-WITH-NOTES — the five r1 findings are resolved in r2 as planning requirements; venue facts remain gated by WP6 positive controls and STOP constants, which is appropriate; no new blocker.

| r1 finding | Resolved? |
|---|---|
| STOP must require slug-scoped cancel-all | YES — S-2 "slug-scoped cancel-all is unavailable or not honoured" is a programme STOP (plan :41) |
| No-id AMBIGUOUS POST can orphan after restart | YES — boot sweep "cancels every order on every slug in the durable slug ledger and confirms by read" (:28); WP4e slugs = all `resting:` rows + resolver contexts, re-read confirmation (:172) |
| Private WS order stream underweighted | YES — explicitly rejected with reasons (documented, never wire-verified, unsnapshotted, 10-subs cap) (:73); open latency question, not a blocker |
| Non-post-only resting GTD unproven | YES — S-1 STOP "a non-post-only GTD limit BUY NO does not rest on tc-temp-*" (:40); WP6 positive control tests GTD/cancel/expiry (:249) |
| Maker fee sign | YES — WP0 pins "maker commission field name and sign" (:101); WP5 uses venue commission with its venue sign (:200) |

Venue assumptions align with the skill: GTD via GOOD_TILL_DATE/goodTillTime, cancel params marketSlug and cancel-all slugs, participateDontInitiate as post-only (SKILL.md:144,147). Spec v0.3 "never post_only unless the venue requires it" matches.
New blocker: none.
