# Qwen3.8-27B produces garbage once its layers are offloaded to CUDA

Status: **open; narrowed to the UD-IQ3_XXS file's tensor types (Q4_0 is correct)** (2026-11-16). Found during the reconfiguration spike (`python -m sub0llmengine spike`).
Not yet reported upstream: confirm the cause in isolation first (brief for that session: [../sessions/qwen38-27b-cuda-isolation.md](../sessions/qwen38-27b-cuda-isolation.md)).

## Symptom

Greedy completions (temperature 0, top-k 1) from `llama-server` with the model partly offloaded:

| GPU layers (`-ngl`, of 65) | "The capital of France is" | chat: "What is 2+2? Answer in one word." |
|---|---|---|
| 0 (CPU only) | ` Paris.` (repeats) | `<think> The user asks "What is 2+2?" ...` |
| 4 | ` Paris.` (repeats) | `<think></think> Four` |
| 12 | ` a city of 22.2 million inhabitants, making it the 12th largest city in the world.` | `None` |
| 22 | `ATUS\nThe\nThe\nThe...` | ` vit.` |

Quality falls as more layers run on the GPU: correct on CPU, plausible-but-wrong at 12, garbage at 22. A 16k-token
synthetic prompt gives multilingual token soup at 22 layers on both builds. The same machine runs Qwen3.6-35B-A3B
(`qwen35moe`, APEX Q4_K_M mix) fully on the GPU path with correct output, and Qwen3.8-Flash-Next (`qwen4exp`, UD-IQ1_S)
answers correctly with all non-expert layers on the GPU.

## Environment

* GPU: NVIDIA GeForce RTX 5070 Laptop, 8 GB, compute capability 12.0 (Blackwell, sm_120); driver 617.14; CUDA 13.2.
* CPU: Intel Core Ultra 9 275HX; 63 GB RAM; Windows 11.
* llama.cpp: b9413 (`112065977`, 2026-05-29, the reference build) and upstream master `c7518dbec` (b12427+26,
  2026-11-17). Both: CUDA, Release, `GGML_NATIVE=ON`, `GGML_CUDA_FA=ON`, `GGML_CUDA_GRAPHS=ON`, Visual Studio 2026.
* Model: `unsloth/Qwen3.8-27B-GGUF@4af51b3`, `Qwen3.8-27B-UD-IQ3_XXS.gguf` (10.18 GiB, Unsloth Dynamic v3.1), architecture
  `qwen35` (dense; 16 x (3 Gated DeltaNet + 1 gated attention), 65 blocks, 17 KV layers).
* Server flags (engine defaults): `-fa on -ctk q8_0 -ctv q8_0 -ub 512 -b 2048 -t 16 -kvu -lm none` (upstream) /
  `--no-mmap` (b9413), `-c 4096 -np 1` for the sanity check.

## Q4_0 of the same model is correct (2026-11-16)

`Qwen3.8-27B-Q4_0.gguf` (same repo and revision, 14.95 GiB), upstream build, same flags: at `-ngl` 0, 4, 12 and 22 both
prompts give the same output as CPU-only (` Paris.\nThe capital of Germany is Berlin...`; `<think>\nThe user asks
"What is 2+2?"...`). The graph, the Gated DeltaNet ops, the attention split and the build are therefore not enough to
cause it: the fault follows the IQ3_XXS file's tensor types.

| | UD-IQ3_XXS (wrong on CUDA) | Q4_0 (correct) |
|---|---|---|
| Weight types | IQ3_XXS 120, IQ3_S 106, IQ4_XS 45, IQ2_S 35, IQ2_XXS 24, IQ2_XS 12, IQ1_S 8, IQ1_M 3, Q2_K 10, Q3_K 6, Q4_K 26, Q5_K 7, Q6_K 6, Q8_0 98 | Q4_0 352, Q4_1 8, Q5_K 48, Q6_K 1, Q8_0 1 |
| `ssm_alpha`, `ssm_beta` (48 each) | Q8_0 | F32 |
| `ssm_out` | IQ3_S, IQ4_XS, IQ3_XXS, Q3_K, Q4_K, IQ2_S | Q5_K |

Prime suspects: an i-quant matmul kernel on sm_120 (IQ1_S, IQ1_M, IQ2_XXS/XS/S, IQ3_XXS/S), or Q8_0 for the small
`ssm_alpha`/`ssm_beta` projections (a shape the Q4_0 file never sends to CUDA).

## Ruled out so far

* Not the model, the graph or the build alone: Q4_0 of the same model is correct at every offload tried.
* Not the context transfer: the from-scratch runs are garbage too.
* Not the old build alone: upstream master behaves the same.
* Not CUDA graphs: `GGML_CUDA_DISABLE_GRAPHS=1` gives the same output.
* KV type: `-ctk f16 -ctv f16` still wrong at 22 layers.
* Flash attention off: the server fails to create the context at 22 layers (not yet investigated; may be VRAM).

The server logs `resolve_fused_ops: layer 3 is assigned to device CPU but Flash Attention over K/V rows is assigned to
device CUDA0 (usually due to missing support)`: a split of attention across devices worth checking first.

## Hypotheses, in order

1. A CUDA kernel for one of the IQ3_XXS file's types is wrong on sm_120 (Q4_0 being correct points here). Test:
   `test-backend-ops -o MUL_MAT` and `MUL_MAT_VEC` (and `GET_ROWS`) for IQ1_S, IQ1_M, IQ2_XXS, IQ2_XS, IQ2_S, IQ3_XXS,
   IQ3_S, IQ4_XS and Q8_0 on this GPU, at the model's shapes (5120-wide rows) and batch sizes 1 and 512; then
   bisect by layer (which `-ngl` first goes wrong) and by type (`llama-quantize --tensor-type` a Q4_0 copy with one
   role switched to the suspect type).
2. Q8_0 for `ssm_alpha`/`ssm_beta` (tiny output dimension) on CUDA. Test: the same `test-backend-ops` at that shape;
   requantize those two roles to F32 in the IQ3_XXS file.
3. The CPU/CUDA split of attention (the `resolve_fused_ops` warning) combined with a type above: the Q4_0 file logs the
   same split and is correct, so not alone.

## Reproduce

```sh
# the sanity check: completions at several offloads with the upstream build
python tools/sanity.py qwen38-27b-iq3 D:/tools/llamacpp/vendor/llama.cpp-next/build/bin/Release 0,4,12,22
# the control: the same model in Q4_0, correct at every offload
python tools/sanity.py qwen38-27b-q4_0 D:/tools/llamacpp/vendor/llama.cpp-next/build/bin/Release 0,4,12,22
```

(`tools/sanity.py` starts `llama-server` with the engine config and each `-ngl`, then sends two prompts at temperature 0.)

## Results so far

Recorded in `out/spike/invalid-old-build.jsonl` (the spike's 27B records, set aside: output garbage, so identical/not
identical says nothing; the reuse measurement itself, 64 tokens recomputed after restore, stands).
