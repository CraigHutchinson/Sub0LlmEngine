# Backlog

Work for Sub0LlmEngine, in rough priority order. Moved here from Sub0Squad's backlog where it concerned the engine.

## Tuning map

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

## Workload-adaptive engine configuration (spike)

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

## Engine supervision (from Sub0Squad's "wizard")

- Build and update llama.cpp (`D:\tools\llamacpp` scripts today) from the engine: a pinned commit, CUDA arch for the
  machine, the build label recorded with every bench. A build or install needs the owner's go-ahead.
- Supervise `llama-server`: health checks, restart on crash, a log rotation, and a service option (systemd under WSL or
  Linux, a scheduled task on Windows). Each service install needs the owner's go-ahead.
- Offer models for the machine: query the registry (`sub0llmregistry` `query(moe=..., maxBytes=..., minContext=...)`)
  and its providers, rank by predicted fit and speed, and fetch only with the owner's go-ahead
  (`python -m sub0llmregistry fetch`, which asks before downloading).
- Backends beyond llama.cpp (strata, the Sub0Llm engine) behind the same backend interface.
