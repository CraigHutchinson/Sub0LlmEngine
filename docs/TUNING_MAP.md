# Tuning map: measured operating points and runtime direction

2026-11-16. Sub0LlmEngine is standalone; Sub0Squad is its first consumer, not its owner.
Reviewed Squad `docs/RESUME.md`, `DEV_SETUP.md`, `METRICS.md`, and the engine's current code/history.
Squad consumes an inference endpoint and workload budgets. Its quality/agentic evaluation remains in Squad.

## Received slice

Top down: choose the relative importance of interactive decode speed, prompt depth and simultaneous work;
see an exact setting and why it qualifies. The preference triangle is an input, not a physical performance plot.
A 2D frontier uses real context/speed axes and colour/size for concurrency. This keeps values readable without
3D occlusion. Sliders, presets and a ranked table provide alternatives to dragging and selecting small dots.
With prefill as a fourth priority the weights form a tetrahedron; the triangle is the slice at the held priority's share,
drawn inside it through an orthographic camera (the projection stays affine, so dragging on the slice maps exactly to
weights at any angle). Dragging off the slice, or the corner widget, turns it; clicking a widget face selects that slice.

Bottom up: existing `llama-batched-bench` records carry machine, backend, model, build, settings, prompt depth,
generated tokens, B, throughput and outcome. The runtime view partitions by identity and output length. It groups
only exact settings/depth/B repeats, uses median throughput, and rejects excluded, incomplete, impossible or conflicting
points. One pass is labelled as one pass. Requiring two or three passes can legitimately produce no results.
Each axis is normalized on a log scale over the cohort's eligible points (doubling concurrency or depth is one step),
and points are scored by an augmented Chebyshev rule: the weighted shortfall of the worst axis plus a small weighted
sum. A plain weighted sum only reaches the corners of a curved frontier (per-sequence decode falls like 1/B, so it
jumped from B=1 to B=16); this rule makes every frontier point the best for some weights. "Speed" is selectable:
decode per sequence, prefill, or whole requests per minute (B·depth/prefill + B·ntg/decode seconds per request).
Requirements are simultaneous filters from a registry (`TuningEvidence.FILTERS`, `addFilter`): prompt, concurrency,
decode and prefill floors, and the slot minimum (Auto by default: the largest window that keeps every measured
concurrency). Zero total weights mean balanced weights. No interpolation is performed.

The exported `sub0llmengine.measured-selection.v1` proposal carries:

| Field | Consumer contract |
|---|---|
| `identity` | Machine, engine backend, model registry id, engine build label |
| `engineConfig` | Exact backend settings, server slots, model, and client planning window |
| `consumerBudget` | Concurrent requests, prompt tokens, generated tokens, and their total for the measured workload |
| `evidence` | Synthetic benchmark provenance, timestamps, notes, medians and observed range |
| `activation` | No automatic activation; server validation and restart still required |

`python -m sub0llmengine selection FILE --out NEW_FILE` receives the proposal against current local history, machine
and build label. It checks for contradictory outcomes and changed settings, resolves the real model, prints the server
command, and writes a separate config layer without overwriting. It never stops, starts, or adjusts a running engine.
Use the existing `--config` entry point to inspect that layer. Start it only when hardware is free and the real-server
receiving check is ready. The consumer budgets are advisory; today's server does not enforce them for callers.

Running engine: `start --json` / `status --json` (format `sub0llmengine.engine.v1`, README "Using the engine from another
project") report the answering engine's registry id, build label, effective settings and whether they match the
consumer's configuration (`matchesConfig`), from the record `start` writes to `out/engine.json`. `start` refuses while a
bench holds `out/bench.lock`; benches refuse while the engine answers.

The original heatmap, autofill and history remain available in separate views. Its aggregation is exploratory and can
mix workloads; it is not the runtime recommender. Median aggregation now handles even sample counts, “best VRAM” means
lowest VRAM, and the old scatter respects the visible filters. Save controls are disabled while the queue/engine is busy.
This is a UI guard, not an atomic cross-process resource arbiter; legacy direct `/api/apply` callers retain their behavior.

## Evidence boundaries

* `ctx` is allocated total context. `depth` is the tested starting prompt depth **per sequence**. `B` is benchmark
  concurrency. `B * (depth + ntg) <= ctx` is the current adapter's capacity check. With unified KV, `ctx/B` is an equal
  share calculation, not a measured hard per-slot limit. The export's client window is `depth + ntg`, not `ctx/B`.
* A speed measured at 32k does not prove that speed at 2k or 64k. Admission below a measured bound is a capacity policy
  proposal, not a latency guarantee. Synthetic tokens do not validate generated output quality or Squad task success.
* Conflicting failures exclude that exact point until contamination is investigated or evidence is explicitly excluded.
  Inferred fits/OOM from autofill remain inference and are never promoted into measured recommendations.
* Whole-run VRAM peaks can cover several B rows. They cannot be used as exact per-point headroom or an adaptive controller
  threshold. Missing/zero legacy VRAM is not a free-memory observation.
* Build labels currently describe the source tree or binary mtime, not a binary digest. Machine ids describe hardware,
  not unique physical hosts. Model registry ids are not cryptographic model hashes. Those limits remain visible in the export.
* Server-only options (prompt cache, context checkpoints and extra arguments) are inherited from local config and appear
  in the CLI's proposed command. Their overhead is not covered by the batched benchmark. Binary hashes, driver versions,
  power state, benchmark duration and uncontended repeat provenance should be recorded before automatic promotion.

## Engine ownership and extension

The existing `Backend` owns command generation, benchmark parsing, failure classification, build label and capacity checks.
The received selection path now consumes `Backend.selectionParams()` so backend knob validation has a named owner.
llama.cpp is the only implemented adapter. The browser has a matching small llama.cpp knob contract, tested without the GPU.
Its inline selection core lets the running server serve this upgrade without reloading Python or losing its in-memory queue.

For the **next implemented engine**, introduce an adapter-provided descriptor consumed by the API and controls (labels,
types, ranges, units and restart requirements) and replace the browser's llama.cpp contract and global `PARAM_KEYS` use.
Do not make Sub0Llm/strata pretend to expose CPU MoE or llama.cpp KV flags. Keep common workload/result fields in the
selection contract; placement/kernel flags belong to the adapter. No placeholder engines or unconsumed controls were added.

## Next balanced slices

1. **Real server receiving.** User sees benchmark-vs-serving evidence next to the chosen point. Bottom up, after the current
   queue drains, run a bounded request fixture against the selected configuration at its stated concurrency, prompt and output
   budgets; capture output correctness, peak memory, TTFT and per-sequence/aggregate throughput. Receive the resulting endpoint
   and budgets in Sub0Squad, then its scientific-calculator workflow. Neither server parity nor Squad quality is claimed today.
2. **Read-only live telemetry.** User sees active requests, admitted budgets, observed rate and host pressure, distinguished from
   benchmark samples and saved next-start settings. Adapters supply capability/units and observation timestamps, counter reset
   handling and missing-data states. Existing `/props` and `/slots` status is refreshed every 30 seconds; normalized rate/memory
   collection is not built. Keep online observations separate from controlled benchmark evidence.
3. **Adaptive admission before adaptive engine settings.** User selects priorities plus minimum service levels and a headroom
   reserve. A controller can choose among verified operating points and change admission concurrency/budgets for **new** requests.
   It must preserve active request contexts, queue fairly, use hysteresis/cooldowns, distinguish desired from applied state,
   and back off on pressure or missing telemetry. Engine-owned load-time settings require draining and an explicit restart;
   no assumption that slots, KV allocation or model placement can be resized live. The reconfiguration spike shows a
   sequence's KV can survive that restart (slot save/restore across ubatch, ctx, slots and CPU-MoE changes; see
   BACKLOG.md, "Workload-adaptive engine configuration"). A single resource arbiter must exclude
   tuning benchmarks from inference and protect config writes across CLI/UI processes. Prove this under bounded changing load
   and multiple independent consumers before enabling it by default.

These stages trade immediate responsiveness against context/parallel throughput while preserving caller contracts. Automatic
host tuning, OS changes, engine restarts, and live resizing remain stretch work, not effects of moving the current triangle.
