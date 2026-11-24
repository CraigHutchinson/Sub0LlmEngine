# The engine as a C++23 service

Decided 2026-11-23 (owner): C++23, CMake with CPM, versioning from Version.cmake, built from the Sub0 series like
[Sub0Squad](https://github.com/CraigHutchinson/Sub0Squad). Why and what it must do: [DESIGN.md](DESIGN.md) 1a. The
Python package stays as the reference until the service passes the same tests.

## Conventions (taken from Sub0Squad, so the family builds the same way)

* `cmake_minimum_required(3.24)`, C++23, no extensions, `-Wall -Wextra -Werror` (GCC's two flow diagnostics demoted as in
  Squad), `CMAKE_EXPORT_COMPILE_COMMANDS`; presets, test tiers and an include/layer check as Squad does.
* `cmake/get_cpm.cmake` (shared `CPM_SOURCE_CACHE`) and `cmake/dependencies.cmake`: every dependency a pinned
  `CPMAddPackage`, Version.cmake included.
* One static library per layer, linking only the layers below it, so an upward call fails at link time.
* Owner's standing rules for style, commits and pushes: the cpp-write / cpp-review skills and each repo's `AGENTS.md`.

## Dependencies (all pinned through CPM)

| Need | From |
|---|---|
| Paths, processes, locks, sockets, WSL | Sub0Platform (C++ layer) |
| Diagnostics that survive a hard kill | Sub0Log |
| Typed events (status, pool level, lease changes) | Sub0Pub |
| Job graphs, cancellation (admission, drain and switch) | Sub0Pipeline |
| JSON for contracts and bench history | simdjson 5.1.1 (Squad DECISIONS #16): on-demand reads, `builder::string_builder` writes; types stay out of public headers |
| Local HTTP API and client calls to backends | Boost.Beast 1.92.0 (Squad DECISIONS #18), only in the `net` layer behind `IHttpFront` / `IHttpClient`; HTTP/2 for a later "v2" would add nghttp2 behind the same `net` interfaces |

## Layers (lowest first)

1. **platform**: Sub0Platform only.
1b. **net**: the one place that includes Boost (`boost/` only under `src/net`; `simdjson.h` only under `src/contracts`, checked by `cmake/CheckLayers.cmake`).
2. **contracts**: `engine.v1`, `axes.v1`, `measured-selection.v1`, bench records, lever request and lease, registry
   `request` result. Plain types and JSON in and out; no I/O.
3. **evidence**: bench history reader/writer and the selector (measured points, filters, ranking), pure and testable.
4. **backends**: adapters (llama.cpp, Strata, Basalt, later Sub0Llm): command lines, `modelFormats()`, knobs, health.
5. **supervision**: one process per instance, readiness, clean stop (child included), the GPU lock, owner allowances.
5b. **fit**: finds the largest context a backend loads on this machine (a refusal's shortfall predicts the next try; levers by cost), `apps/fit_main.cpp` is its tool (`sub0engine_fit`).
6. **registry client**: reads `registry.json` and the model definitions, asks for a model by name and format; never
   fetches (the owner runs the registry's `request --fetch`).
7. **control**: lever requests and leases, the admission and adapt policy, status and pool watermark.
8. **service**: the daemon, the local API, install as a Windows service or systemd unit (owner's go-ahead).

## Port order (each step ships with tests both implementations pass)

1. Scaffold the project with `cpp-project-init` (CMake, CPM, Version.cmake, presets, CI) and an empty layer chain.
2. Contracts plus shared JSON fixtures: the Python tests write them (`tests/fixtures/`), the C++ tests read them.
3. Selector and bench history against the real `bench/<machine>.jsonl`.
4. Backend adapters and the registry client (the same `modelFormats()` rules; the Python registry tests' fixtures).
5. Supervision: start, ready, stop for llama.cpp, Strata and Basalt on a spare port, GPU lock.
6. Lever request and lease model, then the API; Squad's client library last.
7. Auto-adapt policy on the M4 spike's findings.

Python stays the tool for the tuning page, bench sweeps and spikes until each has a C++ counterpart.

## Open

HTTP and JSON-writer choices; whether the tuning page is served by the service; the lease model's exact levers
(concurrency, context per request, decode and prefill floors, images, model and format) and what a refusal returns.

## Decisions (2026-11-23, scaffold design by the Opus review; owner confirms the open ones)

* **Notation:** JSON stays the wire contract and the only format the service parses. Agent-facing views may get a write-only
  TOON subset (`key: value`, indented objects, tabular arrays), produced from the same field tables as the JSON. Adopt only if
  `tools/notation_bench.py` shows at least 25% fewer tokens than minified JSON on the bench and status corpora with no loss in a
  field-lookup accuracy probe; otherwise keep JSONL.
* **Tests:** tiers `smoke | full | local`, `area:<name>`, `needs:<x>` ([TESTING.md](TESTING.md)); CI runs only smoke and full.
* **Benchmarks:** sub0perf (from Sub0Math, `DOWNLOAD_ONLY`) gates what the engine's code controls (parsing bench history,
  ranking, contract encode/decode, start-to-ready on a stub server); a GPU canary appends `"suite":"canary"` records to
  `bench/<machine>.jsonl` and is logged with drift warnings, never gated on throughput; the GPU runs only with `SUB0PERF_GPU=1`.
* **Boost:** the CMake-enabled release tarball with only Beast, `BOOST_*_SEPARATE_COMPILATION`, SYSTEM includes.

Status (2026-11-24), each step tested on Windows and Linux with the fixtures the Python reference writes (`tools/write_fixtures.py`):
done: scaffold and CI smoke; Sub0Platform; `net` (Beast front and client); contracts (bench records, llama.cpp / Strata / Basalt config
and registry files); llama.cpp, Strata and Basalt command builders; the registry client (resolve, artifact states, request by
format); supervision (start, readiness, crash detection, stop of the whole process tree); fit (context search for Basalt, tool `sub0engine_fit`). Next: the `sub0llmengine` command line as the
composition root (config layers, `command`, `start`, `status`, `stop`, the `engine.v1` record), then the evidence selector and the
lever request and lease model.

## Prior Sub0 decisions checked (2026-11-23, Haiku survey of the sibling repositories)

Followed: C++23, CMake + CPM with exact pins and per-machine `CPM_<Name>_SOURCE` overrides, a shared cache outside the repo, the layer
check, the family's smoke/full CI with the pinned reusable workflows, sub0perf kept out of CI, Version.cmake with the git-semver
wrapper, `sub0<name>/` include paths and lowercase namespaces (changed from `sub0/engine/` after the survey: now
`include/sub0llmengine/<layer>/`, namespace `sub0llmengine`), camelCase functions, `#pragma once`, `[[nodiscard]]`.

Aligned with Squad: HTTP is Boost.Beast + Asio behind `IHttpFront` and `IHttpClient`, Asio is not the daemon's event loop
(DECISIONS #18); Boost 1.92.0 (this engine is the first to build it, so its pin is the family's); simdjson 5.1.1 with the builder.

Still conflicting or open:

* **Beast or Sub0Platform `net`.** Sub0Canvas' review (D7) sets "native HTTP on Platform `net`" as the local default, and Squad's portal already
  serves HTTP that way. The seams keep both possible; HTTP/2 needs TLS, which Platform `net` lacks.
* **Tiers.** Squad has `smoke | full` only; the engine adds `local` and `needs:`/`area:` labels. Offered to the shared spec.
* **MSVC.** The family ci-strategy full tier includes MSVC and macOS; Squad's full tier is GCC, Clang and MinGW. The engine's `ci-full.yml`
  will include MSVC (the native Windows service target) unless the owner says otherwise.
* **Compiler references.** Squad STATUS names clang 21 as the reference and GCC 15 as buildable; DEV_SETUP says CI uses GCC 14 and Clang 19.
* **Layers** differ per project by design; the **working-title** rule applies to Squad only.

Open for the owner: whether sub0perf moves to its own repository; a PR of the label spec to CraigHutchinson/.github now or after the engine
proves it; the network-using token count for the notation benchmark; the GPU canary's fixed model and parameters.
