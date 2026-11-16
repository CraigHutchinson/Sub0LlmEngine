# Qwen3.8-Flash-Next is not deterministic run-to-run on long prompts

Status: **open, cause not confirmed** (2026-11-16). Found during the reconfiguration spike. Not reported upstream.

## Symptom

One `llama-server` process, the same 2,048-token prompt three times, `cache_prompt: false`, temperature 0, top-k 1:

| run | first generated token ids |
|---|---|
| 1 (first long prefill after load) | 25, 17, 15, 17, 15, 1116 |
| 2 | 4, 314, 279, 1560, 1472, 279 |
| 3 | 4, 314, 279, 1560, 1472, 279 |

Short prompts ("The capital of France is") repeat exactly. In the spike, restored, from-scratch and split-prefill runs all
diverged at the first generated token, so for this model the spike cannot tell a faithful KV transfer from noise. The
reuse measurement holds (64 tokens recomputed after restore, about 50 s of prefill saved per switch on 8k tokens).

## Environment

* llama.cpp upstream `c7518dbec` (b12427+26), CUDA 13.2, RTX 5070 Laptop (sm_120), driver 617.14, Windows 11.
* Model: `unsloth/Qwen3.8-Flash-Next-GGUF`, UD-IQ1_S (3 shards, 67.6 GiB), architecture `qwen4exp` (Gated DeltaNet +
  Qwen Sparse Attention, 512 experts, n-gram embeddings).
* Flags: `-ngl 99 -ncmoe 48 -lm mmap -fa on -ctk q8_0 -ctv q8_0 -ub 512 -c 16384 -np 1`.

## Ruled out so far

* **Sampling and the seed.** With `n_probs: 1` the first token's own log-probability differs: run 1 gives token 25 at
  −2.7727, runs 2 to 4 give token 4 at −0.6129, identical to four decimals. The logits differ before any sampler runs,
  so greedy picking, top-k sampling order and the seed play no part.
* **CUDA graphs.** `GGML_CUDA_DISABLE_GRAPHS=1` gives the same pattern (run 1 differs, runs 2 and 3 match).
* **Random per-run noise.** Runs 2 onwards repeat exactly. Only the first long prefill after the model loads differs.

## Top-k in the model graph

Qwen Sparse Attention picks key blocks with a top-k over block scores. Upstream PRs ggml-org/llama.cpp#32297 ("top-k
rows in pick order") and #32299 (a graph-level fix of the top-k order for `qwen4exp`) fix a pick-order
nondeterminism. Both are stacked on #32247 and do not apply to master. Master's path (`c7518db`) is `ggml_top_k`
(unordered) followed by the fused `ggml_top_k_mask`, an order-independent mask over the KV, so pick order alone cannot
change the result there. Two top-k effects could still explain the first run:

* **Ties at the k-th score**: which tied block makes the cut is order-dependent, even when the mask is order-independent.
* **First-use state**: a buffer or block-score cache that is not yet set on the first long batch after load (for
  example uninitialised memory read by the scorer), which would pick a different block set once only.

A one-off first-run difference fits the second better than the first: ties broken by thread order would vary on every
run, not only the first.

## Hypotheses

1. First-use state in QSA's block selection or chunking (a buffer read before it is first written; several open
   upstream PRs touch QSA: chunking, decode independence in unified KV, top-k order).
2. Ties at the top-k cut-off, decided by kernel order on the first run.
3. An IQ1_S quant so coarse that tiny numeric differences flip greedy decoding: does not explain runs 2 and 3 matching.

Next: run `compute-sanitizer --tool initcheck` (looks for reads of uninitialised device memory) on one long prefill
after load; dump the selected block indices for runs 1 and 2; repeat with a larger quant if one is obtained, with
`-fa off` and CPU-only attention; and try the stacked PRs ggml-org/llama.cpp#30815, #32247 and #32299.

For the spike: phase A's prefill is always the first long prefill after a load, so for this model its KV differs from
any later from-scratch run. That alone explains the spike's mismatch, independent of the transfer.
