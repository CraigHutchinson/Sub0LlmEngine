# Backends and the model registry

How each backend consumes models from Sub0LlmModelRegistry (`D:\Craig\GitHub\Sub0LlmModelRegistry`, data in
`D:\LlmModels`). Engine side: `registry.resolve(cfg, ref)` returns `(absolute path, registry id or None)` and
`process.model()` adds GGUF `facts`; the path goes to `backend.serverCommand`. The registry holds GGUF only today.

| Backend | Model format | Registry today | Needed |
|---|---|---|---|
| llama.cpp | GGUF (+ `mmproj` role) | Complete: alias, shards, facts, eviction | Nothing for serving |
| Strata | `.strata` (native) or GGUF | `format: "strata"` stored and requested | Verify a Strata run config can point at the registry file |
| Basalt | `.basalt` pack, not GGUF | `format: "basalt"` stored and requested | A pack header reader |
| Inkling 2 Mini (shared test model) | llama.cpp: Unsloth GGUF (mainline build >= b12600); Strata: `.strata` or the GGUF; Basalt: `.basalt` | GGUF only | One model definition, three artifacts (`inkling-2-mini`) |

## How a backend asks for a model (built 2026-11-23)

The registry's model definitions (`<root>/models/<name>.json`, see its LAYOUT "Models and artifacts") list a model's
artifacts per format, vendor and variant, each with a provider source or a converter. Config `model` may be such a name
(`inkling-2-mini`): the engine asks for the formats the backend declares (`modelFormats()`: llama.cpp `gguf`; Strata
`strata`, then `gguf`; Basalt `basalt`), narrowed by `modelVariant` / `modelVendor`, and gets a path or a refusal that names
`python -m sub0llmregistry request <name> --format <f> --fetch` (the owner's go-ahead; it lists sizes and asks).
The engine never fetches or converts itself. The registry holds the definition, the state, the download, the conversion
plugins and the `derivedFrom` / `tool` record.

## Gaps, in the order they block the shootout

1. **Model identity per backend** (blocks). The state record knows a registry id, but Strata and Basalt load a file
   named by their own profile/config. Compare the model each server reports on `/v1/models` with the configured
   `model` and record a mismatch instead of trusting it.
2. **Basalt packs**: stored and requested (`format: "basalt"`, fetched by the `hf` provider into `hf/jesdga/...`, checksum
   from the Hub). Open: a header reader giving what the pack states (experts, KV storage, context capacity). Never route a
   pack through `gguf.facts()`.
3. **Strata model preparation** (blocks Strata). Strata downloads and prepares models itself (the no-change plan
   proposed 68.5 GB). Decide whether the registry adopts what it prepares (`adopt`, checked against the provider) or
   Strata keeps its own store and the registry records only a reference.
4. **Derived artifacts.** Record `derivedFrom` and `tool` (`name`, `version`, `command`) for anything a backend
   produces: `llama-quantize` output, `.basalt` packs, Basalt expert profiles (`--expert-profile-save`). These are
   local, so they are never evicted. The manifest already has both fields; the engine does not fill them.
5. **Conversion.** The plumbing exists (converter plugins, `from`, `derivedFrom`/`tool` recorded, tested with a fake). No
   real converter is written: `llama-quantize` and Basalt's `convert.py` need verified commands first.
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
