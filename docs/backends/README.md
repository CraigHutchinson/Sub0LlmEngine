# Backend setup

Sub0LlmEngine can launch llama.cpp, Strata and Basalt through backend-specific adapters. The Strata and Basalt adapters
use each runtime's native profile/config file; they do not install engines, fetch models, translate model formats or
claim that the backends' benchmark scores are interchangeable.

| Backend | Adapter config | Shared sweep | Verified here |
|---|---|---|---|
| llama.cpp | `binDir`, model and llama.cpp knobs | Yes | Existing project path |
| Strata | `strataBin`, `strataProfile`, model path | No; use Strata's profiler separately | Signed CUDA 13 engine installed; no-model binary check |
| Basalt | `basaltBin`, `basaltConfig`, model path | No; use Basalt's profiler separately | Windows x64 CLI/help and isolated dependency check; no inference |

Use the backend's own supported installer/configuration workflow to create its profile. Put the adapter keys in the
normal engine config layer (`engine.local.json`, an environment config, or `--config`). Keep the `model` path aligned
with the model referenced by the native profile so the engine's state record describes the same artifact. Do not copy
llama.cpp-only tuning knobs into another backend's native config.

The adapters launch a backend server and query `/health` plus `/v1/models`. For non-llama.cpp backends, status can
discover the model name and context when reported by those endpoints, but live busy-slot telemetry remains unavailable.
The native run/config file controls backend-specific settings; its path and SHA-256 fingerprint are recorded for
identity, but its contents are not expanded into the shared tuning axes. Shared profiling refuses Strata and Basalt
rather than normalizing incomparable output.

Actual model inference, image requests, wrapper/child shutdown behavior, and performance comparisons remain unverified.
The machine's llama.cpp server was left running during acquisition checks; do not start a GPU-backed backend until that
server is stopped by its owner.

- [Strata](strata.md): signed release acquisition, installation and CLI verification.
- [Basalt](basalt.md): release acquisition and isolated CLI/dependency checks.
- [Registry integration](registry-integration.md): how each backend consumes Sub0LlmModelRegistry models, and the gaps.

## Smoke results (2026-11-23, RTX 5070 Laptop 8 GB)

Fixed prompts at temperature 0, `/v1/chat/completions`, thinking off, against the owner's running profile (4 slots,
131,072 ctx, `-ncmoe 32`, q8_0 KV). Native server timings; not comparable with other engines' numbers until their
workloads match.

| Backend | Model | Cold start (wake + 102 tok) | Decode warm | Prefill 5.6k tokens |
|---|---|---|---|---|
| llama.cpp b12576 | Qwen3.6-35B-A3B APEX I-Compact | 11.5 s | 57 tok/s | 1,309 tok/s (decode 48 tok/s after it) |

### Inkling 2 Mini on all three engines (2026-11-23, same machine, 8 GB VRAM, 64 GB RAM)

Model `inkling-2-mini`, requested by format from the registry. One slot, 8k context, the same prompts (a 29-token code
request, then a 6.4k-token summary), temperature 0, native server timings. Each artifact is a different quantization
and each engine applies its own thinking default, so read these as "what you get on this laptop", not a like-for-like
kernel comparison.

| Engine | Artifact | Placement | Decode (tok/s) | Prefill 6.4k (tok/s) | Notes |
|---|---|---|---|---|---|
| llama.cpp b12665 (master) | Unsloth UD-Q3_K_XL GGUF, 12.7 GB | `-ncmoe 17 --no-op-offload`, 5.4 GB VRAM | 19.4 | 70 | Thinks by default (empty `content` at 128 tokens). Without `--no-op-offload` the compute buffer is 7 to 8 GB and the load fails |
| Strata 0.2.20 (engine 0.1.66) | SQ-15 `.strata`, 13.4 GB | its own plan, 6.7 GB VRAM | about 10 | about 500 | Answered without thinking, so decode is end-to-end (63 tokens in 7 s) |
| Basalt 0.5.6 | NVFP4-DQ8 `.basalt`, 18.4 GB | engine's cache, 15 GB in RAM, 1.9 GB VRAM | 37 | 1,542 | Thinks by default; drafting accepted 76% |

Basalt was fastest by a wide margin on this card (the backlog's hypothesis holds for this model). llama.cpp's slow
prefill is the CPU-resident experts. How each was started: llama.cpp `llama-server` directly; Strata `strata launch
--family inkling-2-mini --model sq-15 --data-dir <hard-linked registry files>`; Basalt `basalt serve --model <pack>
--max-context 8192`. The adapters need a native profile/config file, so these runs did not go through
`python -m sub0llmengine start`; building that path (and the config each backend needs) is the next adapter step.

#### Same GGUF file on llama.cpp and Strata (Inkling 2 Mini UD-Q3_K_XL, 2026-11-23)

Strata runs a GGUF it did not download (`strata launch --model-path file.gguf`), so llama.cpp and Strata can be compared on
the identical file (8k context, one slot, same prompts). Basalt cannot read GGUF, so it stays a separate row above.

| Engine | Decode (tok/s) | Prefill 6.4k (tok/s) | VRAM |
|---|---|---|---|
| llama.cpp b12665, `-ncmoe 17 --no-op-offload` | 19.4 | 70 | 5.4 GB |
| Strata 0.2.20 | 11.4 | 336 | 6.8 GB |

Same weights, so the earlier gap between Strata's own SQ-15 file and llama.cpp was partly the quantization: Strata
prefill is 4.8 times llama.cpp's here, and llama.cpp decodes 1.7 times faster. (llama.cpp ran with thinking on, Strata
answered directly; decode rates are per generated token.)

### Qwen datapoints and what each engine can run here (2026-11-23)

The same Qwen files could not be compared across all three engines on this 8 GB laptop:

| Model (file) | llama.cpp b12665 | Strata 0.2.20 | Basalt 0.5.6 |
|---|---|---|---|
| Qwen3.5-9B Q4_K_M (identical GGUF, 5.7 GB) | decode 46 to 55 tok/s, prefill 2,168 tok/s, 5.4 GB VRAM | refused: "this model type is not supported by the Strata engine" | no pack, and `convert.py --gguf` refuses a dense model (no expert tensors) |
| Qwen3.8-27B Q4_0 (identical GGUF, 15 GB) | decode 5.3, prefill 314 (`-fit on`, 6.1 GB VRAM) | refused (same reason) | no |
| Qwen3.8-27B QUASAR NVFP4 (official checkpoint) | converted here to GGUF: decode 4.2, prefill 362, 6.0 GB VRAM | refused | published pack: refused to load, "out of device memory for 16384 MiB of weights on CUDA0" |

So the Inkling 2 Mini rows above are the only three-engine datapoint on this machine. For Qwen the registry can hold every
artifact, and llama.cpp measures all of them; Strata supports other model families, and Basalt's dense Qwen needs about
16 GB of VRAM. The converted NVFP4 GGUF is the like-for-like llama.cpp counterpart of Basalt's pack: the same QUASAR
revision `4a22293a`, NVFP4 codes and scales copied, not re-rounded (llama.cpp's converter; the Basalt pack's SHA-256
matches the one its docs publish).
