# Responsibilities and relationships

One page that says which project owns what, so a new feature lands in one place. R = does the work, A = accountable
(one per row; its repository holds the contract and the tests), S = supports, C = consulted before a change, I = kept
informed. The owner (the person at the machine) is accountable for every cost: downloads, installs, builds, services
and stopping a running server.

## Projects

| Project | One responsibility | Does not |
|---|---|---|
| **Sub0LlmEngine** (this) | The service that owns the GPU: run, measure, tune and supervise inference backends, grant clients a configuration against their levers and adapt it to demand; the backend abstraction; backend install/update checks | Store weights, schedule jobs, implement inference |
| **Sub0LlmModelRegistry** | The model store: versioned folders, manifests, hashes, facts read from files, providers that fetch, eviction | Launch or update any backend; choose a model for a job |
| **Sub0Platform** | OS layer: paths, WSL, processes, atomic files, locks | Know anything about models or backends |
| **Sub0Squad** | Delegated work: jobs, workers, a collaborative scheduler; a client of the engine | Pick engine flags, start servers, hold models |
| **Sub0Llm** | Native inference engine and model transformations; a future backend and a producer of registry artifacts | Serve other backends, own the registry |
| **llama.cpp, Strata, Basalt** | The third-party engines: their own formats, profiling and native tools | Anything in this table; we adapt to them, never patch them (upstream first) |
| Sub0Pipeline, Sub0Pub, Sub0Log | Job graphs, typed events, diagnostics, used by Squad | Not used by the engine or registry |

## RASCI by capability

| Capability | Engine | Registry | Platform | Squad | Sub0Llm | Owner |
|---|---|---|---|---|---|---|
| Launch, stop, supervise a backend server | **A/R** | I | S | I | S (own adapter) | C |
| Backend adapter: knobs, command line, bench parsing | **A/R** | | S | | C | |
| Detect, install, update or build a backend (`versions.py` checks; the rest is manual) | **R** | | S | | | **A** |
| Measure and rank configurations (bench, auto-fill, selection) | **A/R** | | S | C | | I |
| Start from requirements (slots, context, speed) | **A/R** | | | C (requirements) | | |
| Resolve alias or id to a file and facts | S (`registry.py` client) | **A/R** | S | I | | |
| Store a model: manifest, hashes, layout, eviction | | **A/R** | S | | | C |
| Fetch a model (provider, progress, integrity) | C | **R** | | | | **A** (approves) |
| New artifact format area (`basalt/`, `strata/`) and its fact reader | C | **A/R** | | | | I |
| Which artifact a backend can load (format, version) | **A/R** (refuses) | S (manifest `format`) | | | | |
| Produce a derived artifact (`llama-quantize`, `.basalt` pack, transformation) | R (runs it when asked) | **A** (records `derivedFrom`, `tool`) | | | R (own formats) | **A** (approves) |
| Model identity check (server's reported model against the config) | **A/R** | S (id) | | | | |
| Run a workload through an endpoint | S (endpoint, headroom) | | | **A/R** | | C |
| Arbitrate the GPU (one job at a time, allowances) | **A/R** | | S (locks) | C | | **A** (allowances) |
| Cross-engine comparison (matched workload, per-artifact evidence) | **A/R** | S (artifact ids) | | C | S | I |
| OS portability (Windows, Linux, WSL) | C | C | **A/R** | C | | |

## Relationships

```
 owner ──approves downloads, installs, stops──▶ Engine ──resolve(alias)──▶ Registry ◀──fetch── providers (hf, url, basalt, strata)
                                                  │  ▲                       ▲
                       OpenAI HTTP, status --json │  │ endpoint, headroom    │ register derived artifacts (derivedFrom, tool)
                                                  ▼  │                       │
                                                Squad                  Engine runs converters, Sub0Llm transforms
        Engine ─launches─▶ llama.cpp | Strata | Basalt | Sub0Llm (adapters, one server each)
        Engine, Registry ─use─▶ Sub0Platform
```

Rules that keep the boundaries:
1. The registry never runs a backend and the engine never writes into the registry's folders except through
   `sub0llmregistry`; a model is referred to by alias or id, never by path.
2. A backend gets only what it can load. The manifest `format` decides; the engine refuses a mismatch rather than
   starting.
3. Native profiling stays with each backend. Results are stored per backend, artifact, build and settings, and are
   compared only on a matched workload.
4. Anything that costs the owner is asked first, whichever project's code does the work.
5. A contract (here: `engine.v1`, `axes.v1`, `measured-selection.v1`; there: the manifest schema) is changed in the
   repository that is accountable for it, with its tests, and the others are informed.

## Engine modules

| Module | Responsibility |
|---|---|
| `backends/` | One adapter per backend (command, knobs, bench parsing); never decides what to run |
| `process.py` | One supervised server process and its `engine.v1` record |
| `config.py`, `profiles.py` | Layered config; named profiles with their evidence |
| `bench.py`, `exploration.py`, `spike.py`, `activity.py` | Measurement and its history |
| `selection.py`, `axes.py` | Choosing a measured configuration; the backend-neutral knob definition |
| `registry.py` | Thin client: alias or id to path and facts; fetching is the registry's |
| `versions.py` | Installed versus latest backend versions; check only |
| `machine.py`, `platform.py` | Machine identity; Sub0Platform shim |
| `tuneserver.py` | The tuning page's JSON API |

Registry side: `store.py` (layout, manifests), `gguf.py` (fact reader), `providers/` (fetch), `cache.py` (disk use and
eviction). New formats add a fact reader and a provider there, not in the engine.
