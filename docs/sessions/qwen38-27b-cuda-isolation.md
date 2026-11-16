# Follow-up session: isolate the Qwen3.8-27B UD-IQ3_XXS CUDA fault

Status: open (written 2026-11-16). Start a session with: "Read `docs/sessions/qwen38-27b-cuda-isolation.md` and do it."
The evidence so far is in [../issues/qwen38-27b-cuda-offload.md](../issues/qwen38-27b-cuda-offload.md).

## Goal

Confirm, in isolation, why `Qwen3.8-27B-UD-IQ3_XXS.gguf` gives wrong output once layers are offloaded to CUDA, and
write it up ready to report to llama.cpp. Do not report upstream: the owner decides that.

## What is known

* UD-IQ3_XXS: correct at `-ngl` 0 and 4, plausible but wrong at 12, garbage at 22, on both b9413 and upstream `c7518db`.
  Not CUDA graphs, not the KV type, not the context transfer.
* Q4_0 of the same model (same repo and revision, same build and flags): correct at 0, 4, 12 and 22, identical to CPU.
  So the graph, the Gated DeltaNet ops and the build are not enough alone; the fault follows the tensor types.
* UD-IQ3_XXS uses IQ1_S, IQ1_M, IQ2_XXS, IQ2_XS, IQ2_S, IQ3_XXS, IQ3_S, IQ4_XS, Q2_K to Q6_K and Q8_0, and stores
  `ssm_alpha`/`ssm_beta` as Q8_0 (F32 in the Q4_0 file). Q4_0 uses Q4_0, Q4_1, Q5_K, Q6_K, Q8_0.
* Both files log `resolve_fused_ops: layer 3 is assigned to device CPU but Flash Attention ... CUDA0`; Q4_0 is correct
  with it, so the attention split is not the cause alone.

## Steps

1. **Kernel tests.** In the upstream worktree `D:/tools/llamacpp/vendor/llama.cpp-next` (branch
   `sub0/next-hybrid-reuse`, build dir `build`, Visual Studio 2026, CUDA), build only `test-backend-ops` (tests enabled
   for that target). Run on CUDA0 against CPU: `-o MUL_MAT`, `MUL_MAT_VEC` if it exists, `GET_ROWS`, for IQ1_S, IQ1_M,
   IQ2_XXS, IQ2_XS, IQ2_S, IQ3_XXS, IQ3_S, IQ4_XS and Q8_0. If the defaults pass, add cases at the model's shapes:
   5120-wide rows, batch 1 and 512, and the small output dimension of `ssm_alpha`/`ssm_beta`.
2. **Bisect by layer.** From `D:\Craig\GitHub\Sub0LlmEngine`:
   `python tools/sanity.py qwen38-27b-iq3 D:/tools/llamacpp/vendor/llama.cpp-next/build/bin/Release 5,6,7,8,...`
   to find the first `-ngl` that goes wrong, then list that layer's tensor types (gguf-py from the worktree, run with
   `python -I`).
3. **Bisect by type** if the kernel tests pass: requantized copies with
   `llama-quantize --allow-requantize --tensor-type <role>=<type>`, one role at a time (for example a Q4_0 copy with one
   role switched to a suspect type, or the IQ3_XXS file with `ssm_alpha`/`ssm_beta` as F32). Write copies to a scratch
   folder, never into `D:/LlmModels`.
4. **Old build.** Check whether the failing `test-backend-ops` case also fails on b9413
   (`D:/tools/llamacpp/vendor/llama.cpp`).

## Done means

The issue doc names the failing op, type and shape, with a minimal reproduction (ideally one `test-backend-ops` line)
and its evidence, and says which hypotheses are ruled out. Its status line says whether it is ready to report.

## Environment and constraints

* RTX 5070 Laptop 8 GB (sm_120, driver 617.14, CUDA 13.2), Intel Core Ultra 9 275HX, 63 GB RAM, Windows 11.
* Models: Sub0LlmModelRegistry folder `D:/LlmModels`, aliases `qwen38-27b-iq3` and `qwen38-27b-q4_0`.
* Ask the owner before any download, install or model fetch. Nothing leaves the machine; servers bind 127.0.0.1.
* Commit nothing without the owner's go-ahead (the repo holds uncommitted work from other sessions). No changes to
  Sub0Pipeline or Sub0Pub.
* One GPU job at a time: check no `llama-server` is running and respect `out/bench.lock`. The tuning server on port
  8781 can stay running.
