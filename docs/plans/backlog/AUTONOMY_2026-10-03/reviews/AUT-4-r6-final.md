# AUT-4 r6: post-READY build items
- **E-7/E-8 (adopted 2026-10-03):** add the AST read-only test and rename sandbox-parse tests to `*_config_*`, per ARCH-ERRATA-rev9_2.md.
- **E-9 (adopted 2026-10-03):** any multi-command oneshot bounds each command and sums the bounds (ARCH-ERRATA E-9). Binding build item.
- **E-7a (adopted 2026-10-03):** universal bwrap through the shared wrapper and table; WAL reads via the snapshot helper; AST check is a lint. See ARCH-ERRATA E-7a. Binding build item.
- **From AUT-6 r13 (2026-10-03):** register the `eval_replay_path` tape-day and parity-result metric names in `metric_registry` before go-live. AUT-6 #16 consumes them.
- **E-7c (2026-10-03):** the shared bwrap wrapper provides a private `--tmpfs /tmp` with TMPDIR; see ARCH-ERRATA E-7c. Binding build item.
