# Design: Sub0LlmEngine as a whole system

2026-11-16. The target shape of the engine, the contracts between its parts, and the order to build it in. The backlog
([BACKLOG.md](BACKLOG.md)) holds the work items; this document says where each one fits. Evidence and selection rules are in
[TUNING_MAP.md](TUNING_MAP.md); measured results in [RESULTS.md](RESULTS.md).

Who owns what across the Sub0 projects (RASCI): [RESPONSIBILITIES.md](RESPONSIBILITIES.md).

## 1. Purpose

Run local inference engines on the machine you have, at the configuration the evidence supports, for clients that
should not need to know engine flags. One machine, one owner, nothing leaves it (servers bind 127.0.0.1). The first
client is Sub0Squad: many agents, each a long multi-turn conversation, sharing one GPU.

What "good" means, in order: a client gets a working endpoint whose behaviour (concurrency, context, speed) was
measured; the engine never silently serves something other than what was asked; the GPU is used for one job at a time;
results always name their exact weights, build and settings; changes that cost the owner (downloads, installs,
services, frontier models) are asked first.

## 1a. Product shape (owner, 2026-11-23)

The engine is a **built service that runs on this machine**, not a Python script. It owns the GPU and the backend
processes. Clients (Sub0Squad, tools, a person) ask it for an inference configuration through the levers (concurrency,
context per request, decode and prefill floors, images, model and format) and get an endpoint, or a refusal with the
nearest measured alternatives. The service also adapts the configuration itself as the active users and their requests
change (the M4 workload-adaptive work: hysteresis, drain or hand over before a switch, never drop a request's KV).

The Python package is the prototype and the reference: its contracts (`engine.v1`, `axes.v1`, `measured-selection.v1`,
bench records, the registry `request`) and its tests are the specification the service must pass. The tuning page stays
a view over the service. The service is **C++23 with CMake and CPM, versioned by Version.cmake, built from the Sub0 series** (decided 2026-11-23);
the plan and layers are in [SERVICE.md](SERVICE.md). Until the port passes the Python tests, new engine logic keeps its
decisions in data and contracts (JSON fixtures both sides read), not in script glue.

## 2. Components

```
                 clients (Sub0Squad, tools, a person)
                    |  OpenAI-compatible HTTP            |  CLI / JSON contracts
                    v                                    v
   +--------------------------------+     +----------------------------------------+
   | Gateway (M3, optional)         |     | Control (CLI `python -m sub0llmengine`) |
   |  admission, pool watermark,    |<--->|  instances: start / stop / status       |
   |  routing to instances, request |     |  profiles, start from requirements      |
   |  level switch (M4)             |     |  config layers                          |
   +--------------------------------+     +----------------------------------------+
                    |                         |                |              |
                    v                         v                v              v
   +--------------------------------+   +-----------+   +-------------+  +-----------------+
   | Instances: one server process  |   | Selector  |   | Evidence    |  | Registry client |
   | per name (llama.cpp, Strata,   |   | measured  |   | bench, auto |  | (Sub0LlmModel-  |
   | Basalt adapters), supervised  |   | points -> |   | fill, spike,|  |  Registry)      |
   +--------------------------------+   | a config  |   | history     |  +-----------------+
                    |                   +-----------+   +-------------+
                    v                         ^                |
   +--------------------------------+         +----------------+
   | Backend adapters               |   Resource arbiter: one GPU job at a time (bench lock today;
   | llamacpp, strata, Basalt;      |   instances and benches both take it in M2), plus the owner's
   | Sub0Llm later: knobs, commands|   allowances (VRAM, RAM, threads kept free)
   +--------------------------------+
```

* **Backend adapters** (`sub0llmengine/backends/`): turn a configuration into a server command, describe their knobs
  (`axes.v1`), and provide backend-specific profiling where supported. The shared sweep currently parses llama.cpp
  output only; Strata and Basalt are explicitly rejected by that sweep. Adapters never decide what to run.
* **Instances** (`process.py`): one supervised server process per instance name, with its record (`engine.v1`).
  Today there is one unnamed instance.
* **Evidence** (`bench.py`, `exploration.py`, `spike.py`): measured points per machine (`bench/<machine>.jsonl`),
  auto-fill, reconfiguration spikes. Benchmarks are synthetic: they establish throughput at a workload, not quality.
* **Selector** (`web/tune.html` `TuningEvidence`, `selection.py`): from requirements and priorities to one measured
  configuration, with its evidence. Measured points only, requirements as filters, log-scale Chebyshev ranking.
  Today the ranking lives in the page (JavaScript); `start --min-ctx` (M1) needs it on the command line too.
* **Control**: the CLI and its JSON contracts; the tuning page (`serve`) is a view and a queue over the same parts.
* **Registry client** (`registry.py`): aliases and ids to files and GGUF facts; downloads belong to the registry.
* **Gateway** (M3): an optional OpenAI-compatible front on 127.0.0.1 that clients use instead of the instance
  directly, so the engine can see and steer requests: admission, the pool watermark in responses, routing between
  instances, and later the request-level configuration switch. Without it clients talk to llama-server directly.
* **Resource arbiter**: today the bench lock (`out/bench.lock`) plus "benches refuse while an instance answers" and
  "start refuses while a bench runs". M2 makes it one lock both sides take, with the owner's allowances as limits.

## 3. Contracts (versioned, JSON)

| Contract | Producer | What it carries | State |
|---|---|---|---|
| Config layers | owner, page, `selection --out` | defaults < `engine.local.json` < `$SUB0LLMENGINE_CONFIG` < `--config` | built |
| `sub0llmengine.axes.v1` | `axes`, `/api/axes` | axes, workload, knobs (flag, range, change at load/request, KV transfer) | built |
| Bench record | `bench.py` | machine, backend, model id, build, params, depth, ntg, B, throughput, outcome, VRAM | built |
| `sub0llmengine.measured-selection.v1` | the page's export | identity, engineConfig, consumerBudget, evidence, activation | built |
| `sub0llmengine.engine.v1` | `start/status --json` | endpoint, slots, context, model id and path, build, config, matchesConfig, bench lock, pool, loading | built |
| Profile | `config/profiles/*.json` | a config layer plus `_evidence` (records, build, model) | built |
| Pool watermark | `status --json` `pool`; gateway header (M3) | size, used, reclaimable, free, busy slots, level | built; header M3 |
| Registry id | Sub0LlmModelRegistry | `hf/<org>/<repo>@<revision>#<file>` and facts | built |

Rules: a contract gains fields without breaking readers; a breaking change bumps its version; every contract a client
reads is tested without a GPU (`tests/`).

## 4. Key decisions

1. **Measured, not predicted, configurations are served.** Prediction (registry facts) only orders what to measure.
2. **The engine owns load-time settings; clients own requests.** A client never passes engine flags; it asks for
   requirements (concurrency, context, speed floors) or a profile.
3. **One GPU job at a time.** Benches and instances exclude each other; no automatic preemption of a running instance.
4. **Context per request is dynamic.** With unified KV the pool is shared; `squadCtx` is a planning target. The engine
   reports headroom (watermark) and the two exhaustion signals; clients react (Sub0Squad backlog).
5. **No silent substitution.** If what answers differs from what is configured, `matchesConfig` says so and `start`
   does not replace it without an explicit stop.
6. **Upstream first.** Fixes go to llama.cpp where they belong (hybrid reuse came from upstream; the 27B kernel fault
   and the all-requests-fail-on-full-pool behaviour are candidates); local patches only as a bridge, on a named branch.
7. **The owner approves costs**: downloads, installs, builds, services, frontier tiers, the final project name.

## 5. Milestones

**M0: measured single instance (done).** Bench history and auto-fill; runtime explorer and export; axes; spike;
`engine.v1` with `start/status --json`, the started-engine record, bench-lock refusal, waiting stop.

**M1: serving basics.** What a client needs to run real work on one instance.
* Done 2026-11-16: pool watermark in `status --json` from `/slots` (used, reclaimable, free, level; checked on the
  real server); a loading instance counts as present (`/health` 503), so `start` never launches a second server; named
  profiles (`profiles`, `--profile NAME`) with evidence, flagged stale when build, model or records change;
  `kvUnifiedPerSlot` knob (refused with a clear message on builds without `--kv-unified-per-slot`).
* Start from requirements: `start --slots N --min-ctx T [--min-decode X]` picks the best measured point (needs the
  selector's filters and ranking in Python, shared with the page's tests as fixtures).
* Move the default build to upstream after re-measuring the serving points on it (owner's go-ahead).
* Pool-exhaustion spike: four growing requests; record the signals and recovery cost.
* Migrate the current 131,072-token llama.cpp serving profile and image/projector setup from `D:\tools\llamacpp`;
  verify the measured prompt depths, actual server context and client input/output budget before adopting it here.
* Add and test llama.cpp image requests through the configured projector/native multimodal path; keep vision optional
  and report it only when the model, runtime and required assets support it.

**M2: supervision and arbitration.** Named instances (`--instance NAME`, own port, pid and record), restart on
crash with back-off, log rotation, one lock shared by instances and benches, the owner's allowances (VRAM/RAM/threads
kept free) as hard limits. Service install (systemd user unit on Linux/WSL, scheduled task on Windows) on request.

**M3: gateway.** OpenAI-compatible proxy on 127.0.0.1: forwards to an instance, adds the watermark to responses
(`x-sub0-pool` header and a `pool` field), admission control by headroom with a queue and fair order, per-client usage
records that reconcile with the engine's counters (Sub0Squad's accounting gap), routing by model alias to instances.

**M4: workload-adaptive configuration.** Using the spike's result (KV survives a restart into another configuration):
prefill-tuned start for long prompts, then the serving configuration with the context restored; switches driven by the
queue, with hysteresis and drain/hand-over; never drop a request's KV. Measure against fixed configurations first.

**M5: more backends and machines.** Initial Strata and Basalt serving adapters and Windows runtime acquisitions are in
place; Sub0Llm adapters, machine profiles beyond the reference laptop, automated compatibility/acquisition/build/install,
and native per-backend profiling remain. Verify process ownership/lifecycle, readiness and health, API credentials,
model/pack identity, capability discovery (including vision), and backend-specific measurements. Keep each backend's
knobs truthful (no fake CPU-MoE flags), and do not compare measurements across engines unless their workloads and
metrics are equivalent.

Strata and Basalt use explicit native profile/config files. Strata exposes a foreground `strata serve` path; Basalt
documents `basalt serve --config` and `.basalt` packs for Blackwell/CUDA 13. Current adapters do not download or prepare
models, and Basalt wrapper/child shutdown remains to be verified before relying on managed stop. Keep compatibility
checks and owner approval for installs, downloads, model preparation and disruptive restarts. Add image-request support
to llama.cpp through its projector/native multimodal configuration in M1. M5 exposes vision capability through the
backend contract only when the chosen model, runtime and required assets are available.

## 6. Platform support

Windows and Linux (WSL included) from one checkout: OS differences come from Sub0Platform through `sub0llmengine/platform.py`, config layers
per platform (`engine.local.<windows|linux|wsl>.json`), Windows drive paths read as `/mnt/x` under WSL, tests on both
in CI. Supported topologies: engine and clients on Windows; engine on Windows with clients in WSL (mirrored
networking, verified); engine native on Linux (needs a Linux llama.cpp build; untested here). The engine depends on
[Sub0Platform](https://github.com/CraigHutchinson/Sub0Platform) (v0.1.0, seeded from this module), the platform library shared by the Sub0 projects (plan: Sub0Squad `docs/sessions/platform-unification.md`).

## 7. Open questions

* Gateway or not: a proxy adds a hop (small on localhost) and a component to supervise, but is the only place to see
  and steer requests. Decide after M1's watermark is used by Sub0Squad directly.
* Where ranking lives: one implementation (Python) serving both page and CLI, or keep JavaScript in the page with
  shared fixtures. Leaning: port the filters and score to Python, keep the page's copy tested against the same fixtures.
* Unified pool attention cost (decode speed versus whole-pool occupancy): measure before relying on large idle pools.
* Determinism: first-prefill effects (Flash-Next) and top-k ties; a deterministic mode for experiments.
