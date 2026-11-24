# Backlog

Work for Sub0LlmEngine. The target system and the milestones are in [DESIGN.md](DESIGN.md); each item below names its
milestone. Done items are kept short here and leave in the next tidy-up (git keeps them).

## Service shape (owner, 2026-11-23; see DESIGN 1a)

Turn the engine from a CLI into a service: a daemon with a local API (lever requests, status, pool watermark, lease and
release), supervising backends (llama.cpp, Strata, Basalt, later Sub0Llm), arbitrating the GPU between requests, and
adapting the running configuration to the active users. Language decided (C++23, CPM, CMake, Version.cmake, Sub0 series:
[SERVICE.md](SERVICE.md)). Steps: scaffold the project; port the contracts and their tests
first; define the lever-request and lease model (what Squad asks, what it gets back, what happens when the machine
cannot meet it); a client library for Squad; service install (owner's go-ahead); the auto-adapt policy on top of the
M4 spike. The Python tools stay as the reference until the service passes the same tests.

## By milestone

* **M1 serving basics** (in progress; done: pool watermark in `status --json`, loading instance counts as present,
  named profiles with evidence, `kvUnifiedPerSlot` knob). Next: start from requirements (*Start from requirements*); default build
  moved to upstream after re-measuring; pool-exhaustion spike (*KV memory model*); B = 3..16 at depth >= 16k
  (*Tuning map*); choose and record the final serving configuration in RESULTS.md; migrate and verify the current
  131,072-token llama.cpp serving profile (*Migration from `D:\tools\llamacpp`*); add image-capable llama.cpp serving
  (*Image input*).
* **M2 supervision and arbitration**: named instances, restart on crash, log rotation, one lock for instances and
  benches, resource allowances (*Tuning map*), service install (*Engine supervision*).
* **M3 gateway**: OpenAI-compatible proxy with admission, the watermark in responses, usage records, routing.
* **M4 workload-adaptive configuration** (*Workload-adaptive engine configuration*): the spike is done; next the
  bounded fixture against fixed configurations.
* **M5 backends and machines**: detect, acquire/build and install backends compatible with the machine; profile each
  backend independently. Done: Strata and Basalt adapters, releases acquired, Inkling 2 Mini run on all three engines
  (docs/backends/README.md), registry model definitions with per-format artifacts and declared converters. Remaining:
  lifecycle verification through the service, native profiling, automated compatibility/install, Sub0Llm, model identity
  checks (*Strata and Basalt backends*, *Model registry iteration*).
* **Evidence quality** (any time): placement prediction from registry facts, recency for repeats, warm-up prefill in the
  spike, the open model issues (`docs/issues/`).

## Tuning map (evidence quality; M1 for the B = 3..16 measurements, M2 for allowances)

- **Runtime explorer audit: done 2026-11-16.** Every concurrency reached the pool; the cause was the "minimum context
  per slot" default of 16384, which also requires the *measured* prompt to be that deep: 513 of 525 accepted points
  were measured at 2k to 8k and dropped, leaving only B = 1, 2, 4 (the only ones measured at 32k). Now:
  - The slot minimum defaults to **Auto**: the largest standard window (256..32k) at which every measured concurrency
    keeps a qualifying point (2k on today's data). Off and Custom remain.
  - Requirements are a filter registry (`TuningEvidence.FILTERS`, `addFilter`) read by `rank()`, `misses()` and the
    page; the summary names how many points each requirement removes and which concurrencies have none left.
  - Failures heal (two later passes of the exact point, or the server's `superseded` mark), in the page and in
    `python -m sub0llmengine selection`; the summary splits failed-every-run, mixed and healed.
  - The ranked list shows the best setting per concurrency (or per concurrency and depth) instead of near-duplicates,
    with total tok/s and the settings.
  - Coverage gaps that limit the ranking are named (today: B = 3, 5, 6, 7, 16 measured at 2k only).
  Next: measure B = 3..16 at depth >= 16k with context sized per B (the "Explore beyond the measured region" panel),
  so a 16k slot window can rank them on evidence; a VRAM-ceiling filter once per-B peak VRAM is recorded.
- Auto-fill edge probes and failure healing are done (2026-11-16): `OOM?` cells beside measured successes are run to
  prove the edge; two later successes needing at least as much memory supersede an old failure. Next: extend the same
  recency rule to `repeats` outliers (weight recent runs) and show superseded failures differently in the run history.
- Predict placement from registry facts before measuring: VRAM at `--n-cpu-moe N` is
  `nonExpertBytes + sum(expertBytesByLayer[N:])` + KV (`kvBytesPerTokenQ8` x context) + compute buffers (ubatch). Fit
  the buffer term from the bench history per machine, then seed auto-fill's `?` cells with `fits?` / `OOM?` priors.

- **Resource allowances set by the user.** Let the owner reserve headroom the engine must leave free: VRAM (e.g.
  "keep 2 GB free for the desktop or another model") and system RAM (for CPU-MoE layers, mmap, and other work on the
  machine), plus an optional CPU-thread cap. The runtime explorer, auto-fill and any future adaptive controller treat
  them as hard filters (a `TuningEvidence.FILTERS` entry once peak VRAM and RAM are recorded per point, and a plan-time
  skip for runs predicted to exceed them from the registry's `expertBytesByLayer` and KV size). Store them per machine in
  the engine config; the export carries them so a receiving server can refuse a config that breaks them.

## Start from requirements (M1; owner, 2026-11-16)

- `start --slots 4 --min-ctx 8192` (and `--model`, `--min-decode`, `--min-prefill`): the engine picks the best measured
  configuration meeting the requirements from this machine's bench history (the runtime explorer's selection rules:
  measured points only, requirements as filters), prints why, and starts it; it refuses with the nearest measured
  alternatives when nothing measured qualifies, and can queue the missing bench instead. `--dry-run` shows the choice.
  Today this is done by hand with a profile layer: `config/profiles/qwen36-35b-b4-ctx8k.json`.
- Named profiles in `config/profiles/` listed by `python -m sub0llmengine profiles`, each with its evidence (record
  ids, build, date) so a stale profile (new build or model) is flagged.

## KV memory model: no paged attention; unified KV and the per-slot cap (M1; checked 2026-11-16)

- llama.cpp has no vLLM-style paged attention (no block tables): nothing named "paged" in the source or commit history
  of upstream `c7518db`. Its equivalent is the unified KV (`-kvu`): one pool of token cells shared by all slots, each
  cell tagged with its sequences, allocated per token, with prefixes shareable between sequences. A short request does
  not reserve `ctx / slots`, so idle capacity flows to busy slots, which is most of paged attention's benefit.
- The cost: a decode step's attention spans the pool's used range (`get_n_kv`: up to the highest used cell, padded) with
  other sequences' cells masked out, so per-sequence speed can fall as the whole pool fills, not only with that
  sequence's own length (newer KV slicing, `get_n_kv_slices`, may narrow this). Measure: decode at B=4 and depth 8k with
  the rest of the pool empty against full.
- **Dynamic context for clients** (Sub0Squad, 2026-11-16: requests keep going past their planned context while the pool
  has room). Needed from the engine: pool headroom in `status --json` (used and free cells, from `/slots` token counts:
  llama-server's `/metrics` has no KV usage), so a client can admit or grow a request; an exhaustion signal it can tell
  apart (`finish_reason: "length"` for one request, "Context size has been exceeded." for all of them); and a spike that
  fills the pool with 4 growing requests to see the failure and its recovery cost. Pool watermark: llama-server has none
  (upstream `c7518db`), so the engine computes it from `/slots` (`n_prompt_tokens` of busy slots = used; idle slots'
  tokens = reclaimable, the server clears them on demand; pool minus busy = free; shared prefixes counted twice, so it
  errs safe) and publishes `pool: {size, used, reclaimable, free, busySlots, level}` in `status --json` and a small
  `/pool` endpoint, with levels `ok` / `notice` (70 % used) / `warning` (85 %) / `critical` (95 %). On a full pool with every slot busy
  llama-server fails all active requests (`server-context.cpp`, TODO: end only the largest sequence): a candidate
  upstream patch.
- Upstream added `--kv-unified-per-slot N` (ggml-org/llama.cpp#24124, 2026-08-27; not in b9413): a context cap per slot
  inside the shared pool (`-c` defaults to slots x N). It turns the equal-share assumption (`ctx / B` in TUNING_MAP's
  evidence boundaries) into an enforced limit that matches `squadCtx`. Add it as a knob (`kvUnifiedPerSlot`, only when
  the build has the flag) and use it in profiles once the engine moves to the upstream build.

## Workload-adaptive engine configuration (M4; spike done)

Context (2026-11-16): the four-priority runtime explorer (speed, context, concurrency, prefill) works well, but no single
configuration wins every phase of a job, and there may be axes not yet identified that matter as much (check first:
KV quantization, speculative decoding, flash attention, thread and CPU-MoE placement under host load).

- **Spike: change the engine configuration during a job without losing its context.** Example: run the initial
  prefill with a large ubatch and fewer slots (prefill throughput is +42% at ubatch 1024 and +88% at 2048), then move to
  more context per sequence or more concurrent sequences for decode, keeping the KV cache already computed. Questions:
  - Which settings can change without a reload? `llama-server` fixes ctx, slots, ubatch and placement at load; check
    what the slot save/restore API (`/slots/{id}?action=save|restore`, `--slot-save-path`) preserves and its cost, and
    whether a KV cache saved under one ctx/parallel/ubatch can be restored under another.
  - Cost of a switch: model reload time (mmap and page cache warm), KV save/restore bandwidth, and the requests that
    stall meanwhile. Compare with simply choosing a compromise configuration.
  - Two engine instances (a prefill-tuned one handing KV to a decode-tuned one, as in disaggregated serving) against
    one engine reconfigured in place, within this machine's VRAM.
- **Spike findings, llama.cpp b9413 (2026-11-16)** (`python -m sub0llmengine spike`, `out/spike/reconfigure.jsonl`,
  16k-token prompt, 64-token follow-up, temperature 0, output compared token for token with a from-scratch run):
  - Slot save/restore survives changes of ubatch, ctx, slots and CPU-MoE/GPU-layer placement: the KV restores in full and
    the output is identical. Changing the KV cache type (q8_0 to q4_0) is refused, as expected.
  - Attention-only model (Qwen2 0.5B): the restored prefix is reused, only the 64 new tokens are computed.
  - Hybrid model (Qwen3.6 35B-A3B, Gated DeltaNet + attention): restored and identical, but llama-server then re-processes
    the whole prompt. Its prefix-reuse guard (`pos_min >= pos_next - n_swa - 1`) asks for a context checkpoint even when
    the new prompt only extends the cache, and slot files carry none. Upstream fixed this in ggml-org/llama.cpp#24110
    (`get_reuse`: the threshold is `pos_next` when there are new tokens). Being re-measured on an upstream build.
  - Costs on Qwen3.6 (8 GB laptop GPU): restart about 7.7 s, slot file 245 MB per 16k tokens (save 0.25 s, restore
    under 0.1 s). Prefill of 16k tokens: 10.0 s at ubatch 2048 / 1 slot / 32k ctx against 19.6 s at the serving config
    (ubatch 512, 8 slots, 104k ctx); ubatch 2048 does not fit beside the serving ctx. Switching pays from about 14k
    prompt tokens once reuse works (gain = prefill saving minus about 8.2 s), more for longer prompts.
  - Qwen3.8-27B (UD-IQ3_XXS) generates garbage on b9413 (predates Qwen3.8); Qwen3.8-Flash-Next (qwen4exp) needs
    ggml-org/llama.cpp#27742. Both re-run on the upstream build.
- **Spike findings, llama.cpp upstream `c7518db` (2026-11-16)** (worktree `D:/tools/llamacpp/vendor/llama.cpp-next`,
  branch `sub0/next-hybrid-reuse`; no patch needed):
  - Hybrid reuse works: Qwen3.6 restores, reuses the prefix (64 tokens recomputed) and gives identical output for ubatch,
    ctx, slots and CPU-MoE changes. Switch about 7.3 s; prefill avoided about 15.5 s per 16k tokens. KV type still refused.
  - Qwen3.8-Flash-Next (UD-IQ1_S, `-ncmoe 48`, mmap): reuse works (about 50 s saved per 8k tokens), but identity cannot be
    judged: the model's first long prefill after a load differs from every later one, and phase A is always that first
    prefill (`docs/issues/qwen38-flash-next-nondeterminism.md`). Recorded as inconclusive.
  - Qwen3.8-27B UD-IQ3_XXS: reuse works, but output is wrong with CUDA offload on both builds; the Q4_0 file is correct
    (`docs/issues/qwen38-27b-cuda-offload.md`); records set aside in `out/spike/invalid-old-build.jsonl`.
  - Follow-up for the spike: run phase A's prefill twice (or warm up with one long prefill after each load) so a
    first-run effect cannot be mistaken for a transfer fault.
- **If viable:** the engine picks its configuration from the incoming workload (prompt length, expected output,
  queue depth) using the measured operating points, with hysteresis, drains or hands over active contexts before a
  switch, and never drops a request's KV. This goes beyond "Adaptive admission" in `docs/TUNING_MAP.md`, which
  assumes load-time settings stay fixed. The goal is the best throughput for the current demand rather than one
  compromise setting.
- Measure first: a bounded fixture (long-prompt job, then many short decodes) comparing fixed configurations against a
  scripted switch, reporting total time, TTFT and peak VRAM.

## Engine supervision (M2 and M5; from Sub0Squad's "wizard")

- Build and update llama.cpp (`D:\tools\llamacpp` scripts today) from the engine: a pinned commit, CUDA arch for the
  machine, the build label recorded with every bench. A build or install needs the owner's go-ahead.
- Supervise `llama-server`: health checks, restart on crash, a log rotation, and a service option (systemd under WSL or
  Linux, a scheduled task on Windows). Each service install needs the owner's go-ahead.
- Offer models for the machine: query the registry (`sub0llmregistry` `query(moe=..., maxBytes=..., minContext=...)`)
  and its providers, rank by predicted fit and speed, and fetch only with the owner's go-ahead
  (`python -m sub0llmregistry fetch`, which asks before downloading).
- Backends beyond llama.cpp (Strata, Basalt and the Sub0Llm engine) behind the backend contract; see
  *Strata and Basalt backends*.
- Detect compatible engines for the current OS, GPU/compute capability, driver/toolkit, RAM/VRAM and storage; present
  the available prebuilt, install or source-build path per backend. Pin and record backend versions/build options and
  compatibility results. Build/install/download actions require explicit owner approval.
- Include every compatible backend in profiling as its own backend/model/build/config evidence series. Use matched
  workloads and record model artifact/quantization, context, concurrency, images, warm state and raw metrics; normalize
  only metrics that are genuinely comparable. Keep backend-specific metrics and limitations visible rather than
  treating configurations or scores as interchangeable.
- On this computer, test the hypothesis that Basalt may perform best; its compatible Windows runtime is acquired, but
  the performance hypothesis remains unverified until a compatible model pack and matched workload are profiled against
  llama.cpp on this machine.

## Migration from `D:\tools\llamacpp` (M1, then M2)

The separate `D:\tools\llamacpp` checkout is the current serving/development source of truth until migration is
verified. Its README documents a 131,072-token profile with four slots, unified KV and a multimodal projector; its
`Serve.ps1` also handles image-token limits and synchronizes the actual `/props` context to the VS Code input budget.
This repo's local engine config currently records `ctx: 106496`, eight slots and no projector, so do not treat those
settings as already migrated or equivalent.

- Inventory and record the active model, resolved server/build paths, effective launch arguments, context, slots,
  KV/cache settings, multimodal projector and client limits from the serving checkout. Do not copy its working tree
  wholesale: preserve its independent changes and keep machine-local files/credentials out of this repo.
- Recreate the serving profile as a Sub0LlmEngine config/profile with evidence; verify the model, build, actual
  `/props` context, pool size and client input/output budget agree. Benchmark the 131,072-token target on this machine
  and record the tested prompt depths separately from allocated context before making it the default.
- Port only the still-needed runtime behavior (startup/readiness, projector and image settings, long-request timeout,
  and client context-budget synchronization) behind existing config/backend contracts. Keep build/setup and tuning
  automation migration separate from serving parity; remove or retire old scripts only after parity is verified.

## Image input (llama.cpp; M1)

- Support an optional `mmproj` (or the model/build's native multimodal path) in the llama.cpp config and server
  command, including projector placement and image token limits where the selected build supports them. Validate
  paths/flags clearly; do not silently start a text-only server when a configured projector is unavailable.
- Confirm that the selected model and projector are compatible, start the server, and send an OpenAI-compatible
  image-bearing request end to end. Preserve text-only behavior when vision is not configured.
- Report vision capability/configuration in the engine status/config contract, and record the image-serving profile
  and its evidence. Keep image token usage within the same shared context/pool accounting; avoid claiming vision
  support from a text-only health check.

## Strata and Basalt backends (M5)

Both adapters launch the native CLI and read `/health` and `/v1/models`; neither downloads or prepares models, and the shared
sweep refuses both (their native profilers stay separate). Run and compared on Inkling 2 Mini: docs/backends/README.md.
Keep installs, downloads, model preparation and disruptive restarts owner-approved.

- Strata: verify foreground lifecycle (clean stop, child included) and the model it reports; it supports only its own model
  families (it refused every Qwen3.5/3.8 file), so check support before offering a model.
- Basalt: detect supported OS, GPU and CUDA and a pack that fits before starting (the Qwen3.8-27B pack needs 16 GB of VRAM
  and refused to load here); verify launcher/child shutdown; exercise image requests and its native benchmark path.
- Evidence stays partitioned by backend, artifact, build, hardware and settings; raw scores are compared across engines
  only on a matched workload. Sub0Llm remains a separate planned adapter.

## Model registry iteration (M5)

Done (Sub0LlmModelRegistry): model definitions with artifacts per format, vendor and variant; `request` by format with fetch
only on the owner's go-ahead; declared converters with the derivation recorded; Basalt and Strata formats; the engine asks
for a model by name in the backend's format (docs/backends/registry-integration.md). Open items are listed there.

## Fit search: first-class engine feature (owner, 2026-11-24)

Finding the largest context (and the levers that buy it) that a backend can hold on this card is an engine feature, not a one-off
session: `sub0llmengine fit --model NAME --backend basalt --target-context N` probes, records and reuses the answer.

- **Probe:** start the backend with a candidate set, read its refusal (Basalt prints `spill plan: ... N MiB short (--max-context C)`),
  and use the shortfall to step the context: the slope is about 14 KiB per position (Inkling 2 Mini, fp8 KV), so one refusal
  predicts the next try; bisect only near the edge. A start is a load of ~19 GiB, so predict first, probe sparingly.
- **Levers, in order:** `--vram-reserve-mib` down to 256, `--spec 1` (drafter off), `--kv` format, then context. Flags are per model
  (Inkling takes none of `--kv-resident`, `--prefill`, `--mtp-window`): the backend adapter reports which it accepts.
- **Output:** a fit record per (model file sha, backend version, GPU, free VRAM/RAM) in the evidence store: max context,
  levers used, shortfall at the next step. The lever/lease model (M4) reads it instead of guessing.
- **Measured 2026-11-24, RTX 5070 Laptop 8 GB, Inkling 2 Mini DQ8 pack, fp8 KV, Basalt 0.5.6:** 131072 is 1713 MiB short at default
  reserve, 516 short with reserve 300 and drafter off; 106496 is 132 short at reserve 256; 98304 is 4 MiB short. About 96K tokens
  fits with every expert in RAM: **>100K does not fit this card with Inkling**; Qwen3.8-27B needs 16 GB. Next: confirm 96K loads,
  then run a needle check and decode speed with experts on the CPU.
- A launcher must not trust Basalt's `ready` line: the server prints it before the engine plans weights; wait for `/health` 200
  *and* a live engine process (the supervision layer's Basalt probe needs this).

## Parked decisions (resolve at a follow-up; the engine works without them)

- **HTTP/2** (new requirement, add where viable): Beast is HTTP/1.1 only. Cheapest path: nghttp2 behind the `net` seam, h2c
  prior knowledge for service clients on loopback; browsers need TLS, which Sub0Platform `net` also lacks.
- **Beast or Sub0Platform `net`** for the local default (Sub0Canvas review D7, Squad's portal); the seams keep both open.
- Whether sub0perf moves to its own repository; when to offer the label spec to CraigHutchinson/.github.
- Compact agent-facing notation: measure TOON against JSON before adopting (docs/SERVICE.md).
- GPU canary: its fixed model and parameters. MSVC in the full CI tier (default: include it).

## Sub0Platform gaps (flag to that project as incomplete migration; Sub0Canvas' platform code is moving there)

None found yet. When a Sub0Platform module lacks something this engine needs (or Sub0Canvas still carries OS code the engine
would want), record it here with the file and what is missing, and raise it in Sub0Platform's backlog rather than working
around it.
