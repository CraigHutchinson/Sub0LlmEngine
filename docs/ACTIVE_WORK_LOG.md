# Active work

Who is working on what in this repository right now, so parallel sessions (Claude, Codex) do not collide on files or on
the GPU. Add a row when you start, mark it Done when you finish, and remove Done rows at the next commit (git keeps
them). One GPU job at a time: benches take `out/bench.lock`; `start` refuses while it is held.

| Date | Owner | Scope | Status | Hardware |
|---|---|---|---|---|
| 2026-11-16 | Codex | Coverage targets, gap experiments, benchmark progress visibility, planner evidence scope | Active | Existing queue owns CPU/GPU; lightweight tests only; refresh Python server only after verifying idle and preserving its state |
