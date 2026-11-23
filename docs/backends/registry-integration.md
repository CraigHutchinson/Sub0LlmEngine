# Backends and the model registry

How each backend consumes models from Sub0LlmModelRegistry (`D:\Craig\GitHub\Sub0LlmModelRegistry`, data in
`D:\LlmModels`). Engine side: `registry.resolve(cfg, ref)` returns `(absolute path, registry id or None)` and
`process.model()` adds GGUF `facts`; the path goes to `backend.serverCommand`. The registry holds GGUF only today.

| Backend | Model format | Registry today | Needed |
|---|---|---|---|
| llama.cpp | GGUF (+ `mmproj` role) | Complete: alias, shards, facts, eviction | Nothing for serving |
| Strata | GGUF run through its own model prep (unverified: `strata models` reads setup-written run configs) | Path only | Verify what a Strata run config references before assuming the registry file is used |
| Basalt | `.basalt` pack, not GGUF | None | A pack area, a provider and a reader (below) |
| Inkling 2 Mini (shared test model) | llama.cpp: Unsloth GGUF (mainline build >= b12600); Strata: `.strata` or the GGUF; Basalt: `.basalt` | GGUF only | Strata and Basalt areas, so one model has three registered artifacts |

## Gaps, in the order they block the shootout

1. **Model identity per backend** (blocks). The state record knows a registry id, but Strata and Basalt load a file
   named by their own profile/config. Compare the model each server reports on `/v1/models` with the configured
   `model` and record a mismatch instead of trusting it.
2. **Basalt packs** (blocks Basalt). A `basalt/<model>/<version>/` area, `format: "basalt"`, a `basalt:` provider
   (published checksum verified before commit) and a header reader giving what the pack states (experts, KV storage,
   context capacity). Never route a pack through `gguf.facts()`; `format` must stop a backend loading an incompatible
   file (`backends` that can use a manifest, derived from `format`, not stored per model).
3. **Strata model preparation** (blocks Strata). Strata downloads and prepares models itself (the no-change plan
   proposed 68.5 GB). Decide whether the registry adopts what it prepares (`adopt`, checked against the provider) or
   Strata keeps its own store and the registry records only a reference.
4. **Derived artifacts.** Record `derivedFrom` and `tool` (`name`, `version`, `command`) for anything a backend
   produces: `llama-quantize` output, `.basalt` packs, Basalt expert profiles (`--expert-profile-save`). These are
   local, so they are never evicted. The manifest already has both fields; the engine does not fill them.
5. **Conversion.** Only after 1 to 4: an owner-approved step that finds a compatible version in the registry and
   otherwise runs the backend's converter and registers the result. Hold until a converter is verified.
6. **Version correlation.** Warn when a manifest's `tool.version` differs from the installed backend
   (`python -m sub0llmengine.versions` reads the installed one).

Not planned until evidence asks for it: per-model compatibility lists, `backendFacts` blocks, a Strata pack area before
Strata's store is understood.

## Eviction

Downloads from a provider can be evicted and restored (`registry restore`); anything with `derivedFrom` or under
`local/` is never evicted. A backend-specific pack follows the same rule once its provider can re-fetch it.

## References

[Registry layout](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/spec/LAYOUT.md),
[manifest schema](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/spec/manifest.schema.json),
[Strata](strata.md), [Basalt](basalt.md), [backlog](../BACKLOG.md).
