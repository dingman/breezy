# AUT-n plan template (binding structure for every area plan)

File name: `AUT-<n>-<slug>_plan_r<round>.md` in this directory. Revise in place and bump the round in the header.

0. **Header**: ID, title, round, the ARCH revision and sha consumed, current score, target 3, the upstream and downstream AUT ids.
1. **Goal state**: the area's score-3 criterion and live proof, quoted verbatim from `README.md`, plus the matching §10 "Area plan obligations" from ARCH.
2. **L-1 null hypothesis and reuse**: for every new component, the Nautilus or existing-Breezy capability checked (file:line) and the verdict.
3. **Design**: how the area implements and consumes contracts C1–C6. Exact modules, file paths, classes, functions, units and timers, schemas and states. Nothing generic.
4. **Work packages** `AUT-n.WPk`: each with its scope, the files touched, the **RED tests named first** (path::test_name), the GREEN criterion, gate commands (`scripts/ci/run_tests_no_egress.sh`, `lint-imports` from the tree root, mypy ratchet) and the activation step (activate immediately on merge unless there is a stated technical reason).
5. **Association**: the exact interfaces consumed from and provided to the other AUT plans, by contract id. Execution order and what can run in parallel.
6. **Live-proof protocol**: what artefact proves score 3, where it lands, the accrual ETA given about 5 fills a day, and the canary or drill used where natural events are too rare. State the evidence class honestly.
7. **Score-3 verification checklist**: for criteria (a)–(f) and the live proof, the exact command, path or log line an independent scorer checks.
8. **Risks and failure modes**: including memory, the 31 GB host, the shared venv, concurrent agents, statistical capacity and the KILL date 2027-01-25.
9. **Binding-constraint compliance**: one line each covering Nautilus immutability, the caps, allow_short, NO-SEND, master enablement and permit, PREREG via ruling, and safety tests never weakened.
10. **Self-score** /100 on: fidelity 20 / correctness 20 / specificity 15 / acceptance 20 / autonomy-safety 15 / reuse 10.

## Programme-wide binding rules (added 2026-10-03 from cross-plan review findings)
- **systemd**: `RuntimeMaxSec` is a no-op on `Type=oneshot` (host systemd 259). Bound every oneshot with `TimeoutStartSec` and add a deploy test that fails if any autonomy oneshot sets `RuntimeMaxSec`. No unit may overlap [16:30Z, 17:10Z) after accounting for `TimeoutStartSec` plus the flock wait.
- **ARCH basis**: Consume the FROZEN ARCH revision named in `README.md` (Items table) and cite its sha. Never cite an older snapshot.
- **Coordinator decisions** in `reviews/*-decision.md` are binding (HOLDOUT, ALPHA, ROLLBACK-FAILURE).
- **Paths**: Every path in a plan or brief is absolute or repo-root-relative.
