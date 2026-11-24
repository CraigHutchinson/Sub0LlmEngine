# Consolidated review and plan: responsibilities across the Sub0 libraries (2026-11-24)

Status: review, read-only; nothing here is built. It extends the Sub0Canvas review of 2026-11-23 (`Sub0Canvas docs/reviews/2026-11-23-fabric-portal-store.md`, decisions
D1-D11, called **F-D*n*** below) from the engine's side: the HTTP seam (GitHub issue 1), the three browser views, the machine-exclusivity problem seen in practice today,
and which library owns what. It does not repeat F-D1..D11; it adds, sharpens or contradicts them where the code says so.

## Scope and inputs

| repository | commit | read |
|---|---|---|
| Sub0LlmEngine | ade9319 | `docs/SERVICE.md`, `RESPONSIBILITIES.md`, `net/http.hpp`, `src/net`, `supervision`, `evidence`, `fit`, `web/tune.html`, `tuneserver.py`, test_http_bench |
| Sub0Platform | 5feccdf | `cpp/README.md`, `net.hpp`, `process.hpp`, `file.hpp` (`FileLock`) |
| Sub0Fabric | dc1cc05 | `docs/DESIGN.md`, `BACKLOG.md`, `include` and `src` listing |
| Sub0Squad | f698909 | `docs/COMPONENTS.md`, `PORTAL_WORK_OVERVIEW.md`, `BACKLOG.md` (engine items), `engine.hpp`, file sizes of the portal and HTTP units |
| Sub0Canvas | 902827c | `docs/PLAN.md` 3.2, `VIEWS.md`, `reviews/2026-11-23-...`, `tools/serve.mjs`, `src/view.js` sizes |
| Sub0LlmModelRegistry | 0c63027 | `docs/REQUIREMENTS.md` (through the engine's RASCI) |

Method: one reviewer (inline), lenses C, D, E, F, G. Lens A and B were not applied (no numerics reviewed). Not read: Sub0Pub, Sub0Pipeline, Sub0MemPage, Sub0Llm internals.
Findings that rest on those are marked *unverified*.

## 1. Verdict

The family is sound and the 2026-11-23 decisions hold: protocol first, one HTTP seam in Fabric `transport`, Platform mechanism-only, projections as data. What is **not yet one
solution** is the layer between them. There are four socket and HTTP stacks (Beast in the engine, Squad's hand-rolled server and client on Platform sockets, Node in Canvas, Python
`http.server` in the engine's reference), three browser views that each hand-roll page delivery, auth and state, four copies of the same CMake layer check, three of the same
JSON reader idiom, and **no machine-wide exclusivity at all**: the only lock is a Python file the C++ tools never take, which is why two sessions had to coordinate by message today.
The contract that the next milestones will inherit and that is least settled is the HTTP seam itself: it has no streaming and its front serves one request at a time, and
Fabric is about to freeze it.

## 2. Canonical decisions

| # | Topic | Decision | Sources |
|---|---|---|---|
| D1 | HTTP seam shape | The seam is the engine's `IHttpFront` / `IHttpClient` (issue 1), **plus two additions before Fabric freezes it**: a streamed response (server-sent events: the handler writes chunks and may hold the connection) and a streamed client read (a callback per chunk, for time-to-first-token and SSE). Concurrency is part of the contract: the front serves connections **concurrently**; a handler never blocks another connection. | issue 1; F-D7, F-D10; E1, E2 below |
| D2 | Who owns what in HTTP | Platform: sockets with deadlines (mechanism). Fabric `transport`: the seam, the contract suite, implementation A (Platform sockets, hand-rolled, with the hardening) and the shared hardening policy (loopback bind, token, Origin and Host checks, path escape, response caps). Engine: implementation B (Beast, `src/net/beast_http.cpp`), offered to the family, kept behind the same suite. Consumers (engine, Squad, Canvas) hold no HTTP code of their own. | F-D10; issue 1 |
| D3 | The engine does not wait for Fabric | Until `transport` publishes, the engine's `net` layer is the seam's reference; its streaming addition lands **here first**, and Fabric lifts it (as F-D1 lifted Squad's journal). The engine then depends on Fabric `transport` and keeps only Beast. | issue 1 item 1; "build by lifting what runs" (F-D1) |
| D4 | Machine exclusivity | One **machine lease**: a per-user well-known file (`<state dir>/sub0/machine.lock`) held through Platform's `FileLock` (released by the OS on a crash), with an owner record beside it (tool, pid, purpose, start time) so a waiting tool can say who holds it. Every tool that needs the quiet machine takes it: engine fit, bench and serve, Squad's host guard, sub0perf runs, Canvas timing. A tool that cannot take it exits with the owner's name; it never waits silently. Python takes the same file through Platform's Python `lock`. Replaces the Python-only `out/bench.lock` (Squad backlog line 271 already asks Squad to honour it). | Platform `FileLock`; Squad BACKLOG; today's coordination |
| D5 | Views | Three bespoke pages (engine tuning page 1,582 lines, Squad portal 587 + page, Canvas viewer 635 + Node server) become **one shell and many view definitions** (F-D8, F-D11): the shell and its auth live once; each project contributes a view definition and a projection. The engine's tuning page is a **panel** of that shell, not a second app. Until the shell exists, the tuning page's data is served only through a documented projection (`/api/history`, `/api/config`) so the panel move is a re-hosting, not a rewrite. | F-D8, F-D11; E3 |
| D6 | What the engine shows and what it does not | The engine owns **measured operating points** (bench records, fit records, engine status). Squad owns task and campaign evidence; Canvas owns documents and their views. The portal joins them by projection and by the composite key (F-D6); no project reads another's files. | RESPONSIBILITIES.md; `PORTAL_WORK_OVERVIEW.md` "Evidence" |
| D7 | The OpenAI-compatible client | The wire is a **contract with golden fixtures**, not a shared library: the engine writes the fixtures (chat request, reply with usage, error replies of each backend) and Squad's `engine.cpp` and the engine's bench both parse them. Neither depends on the other. | `engine.hpp`; `chat_wire.hpp`; E4 |
| D8 | Build and test scaffolding | One home for the layer check, test tiers, the label rule and the semver script. Interim: the copy in Fabric is canonical (newest, smallest); the engine and Squad replace theirs by it when each next touches the file. Final home: the family tooling repository (`.github` docs/ci-strategy.md is the label spec) once more than three consumers exist. | four copies of the layer check across the family; issue 1 item 3 |
| D9 | JSON helpers | Typed on-demand reads and the parser pool exist three times (Canvas, Fabric `pure/json_util.hpp`, engine `contracts/json_fields.hpp`). The engine takes the Fabric dependency anyway (D3), so **Fabric `pure` owns the helper**; engine and Canvas switch when they take that dependency. Not into Platform (not an operating-system concern). | Fabric DESIGN "json_util"; engine contracts |
| D10 | Process supervision | Mechanism in Platform (`spawn`, `Child`, process groups). **Policy stays with each owner**: Squad's shim runs workers (session leader, subreaper, resume); the engine's `Instance` runs servers (ready, probe, stop tree). They do different jobs; no merge. Both already use `newSession`. | Squad `shim.cpp`; engine `instance.cpp` |
| D11 | Records the engine writes | Bench JSONL stays a plain file with one writer (the lease holder, D4); it is **not** lifted into Fabric until a second writer or a reader on another machine exists ("grow by use"). If it is, it is a third Fabric shape with order `aligned-time`. Fit records join the same file with `note` and the same identity fields. | F-D2; DESIGN.md |

## 3. Correctness defects and stale claims

| Defect | Source |
|---|---|
| **The front serves one request at a time**: `IHttpFront` calls the handler "on the front's thread". The bench test showed it: two concurrent requests to the fake server took twice as long, so a long answer blocks every other connection, and a portal or SSE client would freeze the page. Fix before the seam is frozen (D1). | `net/http.hpp`; `test_http_bench.cpp` |
| The interface has no streamed response or streamed read. The engine's own bench cannot measure time-to-first-token and uses a two-pass estimate; Squad's portal and Canvas live views need SSE. | `http_bench.cpp`; PLAN 3.2 |
| "Implementation A on Platform `net`" is not the engine's Beast: Beast brings its own Asio sockets, so the family has two socket stacks under one seam. Acceptable if the suite holds both to one behaviour; today only Beast exists behind the seam and Squad's server is not behind it. | issue 1; `beast_http.cpp`; Squad `portal.cpp` |
| Nothing enforces exclusive use of the machine. `out/bench.lock` is read by Python only; `sub0engine_fit`, `sub0engine_bench` and `Serve-Basalt.ps1` take no lock and can start while another run times. | `bench.py`; `apps/*.cpp` |
| `docs/TUNING_MAP.md` says llama.cpp is the only implemented adapter and the shared sweep supports llama.cpp only; Basalt records now exist through the HTTP bench and appear in the page. The page's llama.cpp knob contract is still global (`PARAM_KEYS`), so a Basalt cohort shows llama.cpp controls. | `TUNING_MAP.md`; portal today |
| Canvas `DECISIONS.md` section 7 premise (Node bridge until Platform `net` lands) was already marked stale by the earlier review; confirm it was edited. *Unverified here.* | earlier review section 3 |

## 4. Redundancy removed (when the plan lands)

* Four HTTP stacks (Beast, Squad hand-rolled, Node, Python `http.server`) -> one seam, two implementations, no consumer code.
* Three browser shells -> one shell and view definitions (the engine page becomes a panel).
* Four `CheckLayers.cmake`, three `TestTiers.cmake`, `CheckTests.cmake` and `git-semver.sh` -> one copy each.
* Three typed-JSON helpers -> Fabric `pure`.
* One Python-only lock and three unlocked C++ tools -> one machine lease on `FileLock`.
* Two OpenAI-client parsers -> one set of golden fixtures read by both.

## 5. Ordered plan

| Wave | Work | Repo | Owner |
|---|---|---|---|
| W1 | Machine lease (D4): Platform helper over `FileLock` with an owner record; engine fit, bench and serve take it; `Serve-Basalt.ps1` calls the engine tool; Python `out/bench.lock` becomes a thin caller. Squad's host guard and sub0perf adopt it in their own repositories. | Platform, engine; Squad and Math as consumers | engine session |
| W2 | HTTP seam contract (D1): concurrent front, streamed response, streamed client read, in the engine's `net` first with the contract suite; bench uses streaming for exact time-to-first-token. Comment the additions on issue 1 and on the Fabric issue. | engine | engine session |
| W3 | Fabric `transport`: lift the seam and implementation A; engine consumes it and keeps Beast as B. Squad's `portal.cpp` and `engine.cpp` and Canvas `serve` move onto it one at a time. | Fabric, then each consumer | Fabric session |
| W4 | Portal data contract for the engine page (D5, D6): `history`, `config`, `status` documented as projections with fixtures; per-backend knob descriptor replaces `PARAM_KEYS` (TUNING_MAP "next engine"); parallel-slot and VRAM fields in bench records. | engine | engine session |
| W5 | Scaffolding consolidation (D8) and JSON helper move (D9). | Fabric, engine, Squad | each repo when next touched |
| W6 | Shell and panel hosting (D5): after W3, with Canvas and Squad view definitions. | Fabric, Canvas, Squad | owner decision 1 |

W1 and W2 touch disjoint engine directories (`evidence`, `fit`, `apps`, tools against `net`) and can run in parallel. W3 waits for W2. W4 waits for nothing but the machine for measuring.

## 6. Owner decisions

1. **Where the shell lives** (W6). Recommendation: Canvas's viewer, because it already has live views, pin state and a Node-free path (F-D7), with Squad and the engine contributing view definitions; revisit when W3 lands.
2. **Does the machine lease also gate serving?** Recommendation: yes. The engine's server holds it in shared mode while it answers requests and any timing run takes it exclusively, so a timing run waits for the server to be stopped on purpose, never alongside it. A shared mode needs one more Platform primitive; if that is refused, serve holds nothing and timing tools refuse while the engine answers (what happens today).
3. **Family tooling repository** (D8 final home). Recommendation: do it when a fourth repository needs the scaffolding; until then Fabric's copy is the source.

## 7. Progress

| Wave | State |
|---|---|
| W1 | plan approved (owner, 2026-11-24, with the three recommendations in section 6). Engine side written, not yet built or tested: `supervision/machine_lease` on Platform's `FileLock` (exclusive only; the shared mode for serving needs a Platform primitive, not requested yet), taken by `sub0engine_fit` and `sub0engine_bench`. Waiting for the quiet machine before building. |
| W2 | not started |
| W3 | not started |
| W4 | not started |
| W5 | not started |
| W6 | not started |
