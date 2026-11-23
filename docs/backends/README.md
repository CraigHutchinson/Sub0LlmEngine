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
