# Sub0LlmEngine

Run, measure and tune local LLM inference engines, and find models through a machine-wide registry.

It takes the engine boilerplate out of the projects that use a model (first [Sub0Squad](https://github.com/CraigHutchinson/Sub0Squad)):
one place that knows how to start an engine with the right placement for *this* machine, how fast each configuration
is, and where the weights are. Backends: **llama.cpp** today; strata and Sub0Llm are planned behind the same interface
(`sub0llmengine/backends/`).

Python 3.10+, standard library only. Windows and Linux (including WSL).

## The triangle

On a machine whose GPU cannot hold the whole model, three things trade against each other through one memory budget:

* **decode speed**: tokens per second per sequence, and for all sequences together;
* **context length**: how many tokens each sequence can hold (KV cache);
* **concurrency**: how many sequences decode at once (server slots).

The knobs that move a configuration around the triangle: how many MoE layers keep their experts on the CPU
(`nCpuMoe`; each layer moved to the GPU costs VRAM and buys decode speed), the total context (`ctx`, KV cache in VRAM),
the slot count, the micro-batch (`ubatch`, a compute buffer that buys prefill speed) and CPU threads. Every point is
measured, failures included, and kept per machine in `bench/<machine>.jsonl`, so the working region and its edge build
up over successive runs.

## Quick start

```sh
python -m sub0llmengine machine          # this machine's id (the bench history file name)
cp config/engine.defaults.json engine.local.json    # then edit: binDir, model, placement (keep only the keys you change)
python -m sub0llmengine config           # the effective configuration and the server command it makes
python -m sub0llmengine serve            # the tuning page: http://127.0.0.1:8781/
python -m sub0llmengine sweep --ctx 65536,131072 --ncmoe 32,36,40 --depth 2048 --B 1,4,8
python -m sub0llmengine start            # serve the chosen configuration (OpenAI-compatible, 127.0.0.1)
python -m sub0llmengine status           # slots, context per slot, and the line to give a client
python -m sub0llmengine stop
```

A bench needs the whole GPU, so `sweep` refuses while the engine is running.

## The tuning page

`serve` opens a local page over the history:

* **Heatmap**: any two axes (CPU MoE layers, total context, concurrency, depth, ubatch, threads, KV type, model, build),
  a layer to colour by (decode all sequences, decode per sequence, prefill, peak VRAM, works/fails, runs measured), and
  filters for the other axes. Cells that ran out of memory are hatched red. Combine by best, latest or median.
* **Speed · context · concurrency**: every successful run as a dot, x = context per sequence, y = speed, colour/size = B.
* **History**: every run over time.
* **Selection**: click a cell to see its runs; *Use this configuration* saves it to `engine.local.json`.
* **Queue a sweep**: comma lists per knob; runs one at a time in the background.

## Configuration

Layers, later wins: `config/engine.defaults.json` < `engine.local.json` (gitignored, this machine) < `$SUB0LLMENGINE_CONFIG`
< `--config FILE`. Changes made from the page go to the top layer.

| Key | Meaning |
|---|---|
| `backend` | `llamacpp` (default) |
| `binDir` | folder with `llama-server` and `llama-batched-bench` |
| `model`, `registry` | a registry alias or id, or a plain file path; the registry folder (`$SUB0_MODEL_REGISTRY` wins) |
| `host`, `port`, `alias` | where the server listens and the model name it answers to |
| `ctx`, `slots`, `kvUnified` | total context, server slots, one KV pool shared by the slots (each slot may use up to `ctx`) |
| `nCpuMoe`, `gpuLayers` | MoE layers whose experts stay on the CPU; layers on the GPU |
| `ubatch`, `batch`, `threads` | micro-batch, logical batch, CPU threads |
| `cacheTypeK/V`, `flashAttn`, `mmap` | KV cache quantization, flash attention, memory-mapped load |
| `ctxCheckpoints`, `cacheRam` | per-slot context checkpoints (prompt reuse on hybrid models), host prompt cache MiB |
| `squadCtx` | the context a client should plan per request (printed by `status`) |
| `extraArgs` | passed to the server as-is |

## Model registry

`registry/` holds the registry's explainer and tool (`README.md`, `Registry.ps1`); a machine's registry is a folder
such as `D:\LlmModels` with a copy of them. Layout: `hf/<org>/<repo>/<revision>/` for downloads as published,
`sub0llm/<model>/<variant>/<version>/` for Sub0Llm's custom formats, `local/...` for our own derivations; every
version folder has a `MANIFEST.json`, `aliases.json` maps short names to ids, and `registry.json` is generated.

## Results on the reference machine

[docs/RESULTS.md](docs/RESULTS.md): Intel Core Ultra 9 275HX, RTX 5070 Laptop (8 GB), 64 GB, Qwen3.6-35B-A3B.

## Licence

MIT, see [LICENSE](LICENSE).
