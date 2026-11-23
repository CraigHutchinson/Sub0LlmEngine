# Backend × Model Registry Integration

This document captures the requirements for how each backend (llama.cpp, Strata, Basalt) interacts with the
Sub0LlmModelRegistry (`D:\Craig\GitHub\Sub0LlmModelRegistry`). The registry stores model artifacts once in versioned
folders with manifests that record their format, sources, hashes, and GGUF facts. Backends consume models from the
registry, request specific formats, and may produce derived versions that the registry records.

## 1. Current Integration Surface

### 1.1 Engine → Registry Flow

```
engine.local.json (model: "qwen36-35b-a3b")
    │
    ▼
sub0llmengine/registry.py → resolve(cfg, ref)
    │
    ├── package().Registry(root).resolve(alias)  # full Python API
    ├── registry.json fallback                   # minimal JSON index
    └── plain file path                          # direct path, no registry
    │
    ▼
(path, registry_id_or_None)
    │
    ▼
backend.serverCommand(cfg, modelPath)
```

The engine's `registry.resolve()` returns an absolute file path and an optional registry id. The path is passed
directly to the backend's `serverCommand` as `modelPath`. The `process.model()` function enriches this with
`facts` (GGUF header analysis) and `exists` (file check).

### 1.2 What We Store Today

The registry currently holds **GGUF** models exclusively (both `hf:` downloads and `local/` derivations). The
`format` field in manifests is `"gguf"`. The `gguf.facts()` reader extracts layer counts, expert bytes per layer,
KV bytes per token, architecture, and quantization — all used by llama.cpp for placement planning.

### 1.3 What Backends Currently Request

| Backend | Model Format | Registry Path Handling | Format Conversion |
|---|---|---|---|
| llama.cpp | GGUF `.gguf` | Directly uses registry-resolved path | None; expects GGUF |
| Strata | GGUF `.gguf` (unverified) | Passes configured path to Strata | None; Strata loads GGUF natively |
| Basalt | `.basalt` model pack (unverified) | Passes configured path to Basalt | Basalt packs are NOT GGUF; registry does not support this format |

## 2. Backend-Specific Requirements

### 2.1 llama.cpp

**Current**: Fully compatible with registry GGUF storage.

**Requirements**:
- **Format**: Expects GGUF files. The registry's `gguf.facts()` reader already provides all the metadata
  llama.cpp needs (`expertBytesByLayer`, `kvBytesPerToken`, `blockCount`, `contextTrain`).
- **Resolution**: `registry.resolve()` already handles llama.cpp's needs — resolves alias → id → path,
  picks the main GGUF file from multi-file manifests, handles `#file` suffix for split models.
- **Facts**: The `process.model()` function already calls `registry.facts()` and stores them in the process
  state record (`engine.json`). These facts are used for placement prediction (`--n-cpu-moe N`).
- **Shards**: llama.cpp loads all shards from the same folder. The registry's `role: "shard"` handling
  in `resolve()` correctly picks the first shard as the main file.
- **mmproj**: The registry distinguishes `role: "model"` from `role: "mmproj"` — the resolve function
  excludes mmproj from auto-selection. Image input (M1) needs to pass the projector path separately.

**Gaps**:
- [ ] **GAP-001**: No registry support for non-GGUF model files that llama.cpp may eventually accept (safetensors,
  ONNX). The manifest schema's `format` field already allows `"safetensors" | "onnx" | "other"` but `gguf.facts()`
  only reads GGUF headers.
- [ ] **GAP-002**: No `derivedFrom` / `tool` recording for llama.cpp quantizations. When the engine runs
  `llama-quantize` to produce a new quantization from an existing GGUF, the registry should record:
  ```json
  {
    "derivedFrom": "hf/mudler/Qwen3.6-35B-A3B-APEX-GGUF@unpinned-20260520#a-Q4_0.gguf",
    "tool": {"name": "llama-quantize", "commit": "b12563", "command": "llama-quantize input.gguf output-Q8_0.gguf Q8_0"}
  }
  ```
- [ ] **GAP-003**: No automatic quantization pipeline. The engine should be able to:
  1. Query the registry for a compatible model (`query(moe=True, maxBytes=20*2**30)`)
  2. Ask the owner for approval
  3. Run `llama-quantize` to produce a new version
  4. Register the new version with `derivedFrom` pointing to the source
  5. Update the `model` config key to the new alias

### 2.2 Strata

**Current**: Adapter passes the configured model path to Strata's native CLI. No format verification or conversion.

**Requirements**:
- **Format**: Strata loads GGUF natively (same as llama.cpp). The registry's GGUF storage is compatible.
- **Resolution**: The engine currently passes the registry-resolved path directly. This works because Strata
  accepts GGUF files.
- **Facts**: Strata may need additional metadata beyond what `gguf.facts()` provides (e.g., expert placement
  preferences, context window settings). These should be stored in the manifest's `notes` or a new
  `backendSpecific` field.

**Gaps**:
- [ ] **GAP-004**: No format verification when the model path is resolved. Before launching Strata, the engine
  should verify the file is a valid GGUF (or whatever format Strata expects) by checking the magic bytes
  (`GGUF` at offset 0) or reading the header.
- [ ] **GAP-005**: No registry support for Strata's native model packs. If Strata supports a proprietary format
  (`.strata` packs), the registry needs a new `format: "strata"` area (e.g., `strata/<model>/<version>/`).
- [ ] **GAP-006**: Strata's `--version` reports `0.1.66` but the GitHub releases show `v0.2.20`. The version
  check tool (`versions.py`) cannot detect the installed version because `strata --version` output format
  (`strata 0.1.66`) doesn't match the GitHub tag format (`v0.2.20`). The `_detect_strata_version()` function
  needs to parse the CLI output.
- [ ] **GAP-007**: No model identity verification. When Strata loads a model, it may report its identity
  differently than the registry's alias. The engine should compare Strata's reported model name against
  the registry's alias and flag mismatches in the process state record.

### 2.3 Basalt

**Current**: Adapter passes the configured model path to Basalt's native CLI. Basalt uses `.basalt` model packs,
NOT GGUF. The registry does not currently support this format.

**Requirements**:
- **Format**: Basalt model packs (`.basalt`) are NOT GGUF. They are a proprietary format containing dense weights,
  experts, source tensors, embedding, PLE table, native projections, head, and draft layer data.
- **Resolution**: The registry cannot resolve Basalt model packs through the current GGUF-centric pipeline.
  The engine needs a separate resolution path for Basalt packs.
- **Facts**: Basalt's model pack contains different metadata than GGUF (expert profiles, routing tables,
  hyper-connection copies). The registry's `gguf.facts()` reader cannot extract this.

**Gaps**:
- [ ] **GAP-008**: **Critical**: Basalt model packs (`.basalt`) have no registry support. The manifest schema
  allows `format: "other"` but there is no `.basalt` area in the registry layout (currently only `hf/`,
  `local/`, `sub0llm/`). Basalt packs need their own area: `basalt/<model>/<version>/`.
- [ ] **GAP-009**: No Basalt-specific fact extraction. The registry needs a `basalt.facts()` reader (analogous
  to `gguf.facts()`) that extracts: expert count, expert bytes per layer, routing tables, PLE row count,
  KV storage mode (fp16/int8/q4_0), and context capacity from the pack.
- [ ] **GAP-010**: No Basalt model pack acquisition. The registry's `fetch` command works for `hf:` and `url:`
  providers. A `basalt:` provider is needed to acquire model packs from `basalt.jgulfo.com` or other sources.
- [ ] **GAP-011**: No Basalt model pack verification. Basalt packs should be verified against the provider's
  published checksums after download, before being committed to the registry.
- [ ] **GAP-012**: No Basalt expert profile management. Basalt learns expert placement at runtime and saves
  profiles (`--expert-profile-save`). These profiles should be stored in the registry alongside the model
  pack, linked via `derivedFrom`.

## 3. Cross-Backend Requirements

### 3.1 Format Compatibility Matrix

| Registry Format | llama.cpp | Strata | Basalt |
|---|---|---|---|
| `gguf` | ✅ Native | ✅ Native (unverified) | ❌ Incompatible |
| `safetensors` | ⚠️ Future | ⚠️ Unknown | ❌ Incompatible |
| `onnx` | ⚠️ Future | ⚠️ Unknown | ❌ Incompatible |
| `basalt` (`.basalt`) | ❌ Incompatible | ❌ Incompatible | ✅ Native |
| `strata` (`.strata`) | ❌ Incompatible | ✅ Native (unverified) | ❌ Incompatible |
| `sub0llm` (transformed) | ✅ After conversion | ✅ After conversion | ⚠️ Unknown |

### 3.2 Registry Layout Extensions

The registry layout (`spec/LAYOUT.md`) needs new areas for non-GGUF formats:

```
<root>/
  hf/...            # Hugging Face downloads (GGUF, safetensors)
  local/...         # Local derivations (quantizations, merges)
  sub0llm/...       # Sub0Llm transformations
  basalt/...        # Basalt model packs (NEW)
  strata/...        # Strata model packs (NEW, if applicable)
  onnx/...          # ONNX exports (future, NEW)
```

### 3.3 Model Identity and Backend Reporting

When the engine starts a backend, the process state record (`engine.json`) should include:

```json
{
  "model": {
    "ref": "qwen36-35b-a3b",
    "id": "hf/mudler/Qwen3.6-35B-A3B-APEX-GGUF@unpinned-20260520#a-Q4_0.gguf",
    "path": "D:/LlmModels/hf/mudler/Qwen3.6-35B-A3B-APEX-GGUF/unpinned-20260520/a-Q4_0.gguf",
    "format": "gguf",
    "backendFormat": "gguf",           // format as understood by the backend
    "exists": true,
    "facts": { "architecture": "qwen35moe", "blockCount": 40, ... },
    "backendFacts": null,              // backend-specific facts (Basalt expert profiles, etc.)
    "matchesBackend": true             // does the file match what the backend expects?
  }
}
```

### 3.4 Conversion Pipeline

When a backend requires a different format than what's in the registry:

```
registry id (GGUF)
    │
    ▼
backend-specific converter
    │
    ├── llama.cpp: llama-quantize (GGUF → GGUF, different quantization)
    ├── Strata: strata convert (GGUF → .strata, if applicable)
    └── Basalt: basalt pack (GGUF → .basalt, if applicable)
    │
    ▼
new version in registry (derivedFrom points to source)
    │
    ▼
engine config updated to new alias
```

**Requirements**:
- [ ] **GAP-013**: The engine needs a conversion pipeline that:
  1. Identifies the required format for the target backend
  2. Checks if the registry already has a compatible version
  3. If not, asks the owner for approval to run a converter
  4. Runs the converter (llama-quantize, basalt pack, etc.)
  5. Registers the new version with `derivedFrom` and `tool` in the manifest
  6. Updates the engine config to point to the new version

### 3.5 Backend-Specific Fact Extraction

The registry's `gguf.facts()` reader should be extended with backend-specific extractors:

```python
# In sub0llmregistry/
gguf.py       # GGUF header reader (existing)
basalt.py     # Basalt pack reader (NEW)
strata.py     # Strata pack reader (NEW, if applicable)
```

Each extractor should return a `facts` dict compatible with the manifest schema:

```python
# Basalt facts example
{
    "architecture": "qwen4exp",
    "expertCount": 256,
    "expertUsed": 8,
    "expertBytes": 12345678,
    "expertBytesPerLayer": [...],
    "kvStorage": "fp16",  # fp16 | int8 | q4_0 | k8v4
    "contextCapacity": 8192,
    "pleRowCount": 1048576,
    "mtpWindow": 32768,
}
```

## 4. Version Checking and Updates

### 4.1 Current State

The `versions.py` module (committed as `a317a06`) checks backend versions against their sources:

- **llama.cpp**: Uses `git describe` from the build directory → works well
- **Strata**: Tries `strata --version` but the output format (`strata 0.1.66`) doesn't match GitHub tags (`v0.2.20`)
- **Basalt**: No `--version` flag; falls back to `basaltVersion` config key

### 4.2 Registry-Backend Version Correlation

When the registry holds a model that was produced by a specific backend version, the engine should:

- [ ] **GAP-014**: Record the backend version that produced a derived model in the manifest's `tool` field:
  ```json
  {
    "tool": {
      "name": "basalt-pack",
      "version": "0.5.6",
      "command": "basalt pack --model input.gguf --output output.basalt"
    }
  }
  ```
- [ ] **GAP-015**: Warn when a model's producing backend version differs from the currently installed version.
  The engine should compare `tool.version` in the manifest against the installed backend version and flag
  potential compatibility issues.

### 4.3 Basalt Version Detection

Basalt does not support `--version`. The version detection in `versions.py` falls back to the `basaltVersion`
config key. Improvements needed:

- [ ] **GAP-016**: Parse Basalt's `serve --help` output for version information (the help text may contain
  version metadata in the build info).
- [ ] **GAP-017**: Check the Basalt binary's file version metadata (Windows `FileVersionInfo`) as a fallback.

## 5. Storage and Eviction Policy

### 5.1 Backend-Specific Eviction Rules

| Backend | Evictable? | Restore Method | Notes |
|---|---|---|---|
| llama.cpp (GGUF from hf:) | ✅ Yes | `registry restore` | Provider can re-fetch |
| llama.cpp (GGUF from local/) | ❌ No | N/A | Never evicted |
| llama.cpp (quantized GGUF) | ❌ No | N/A | `derivedFrom` means local |
| Strata (GGUF from hf:) | ✅ Yes | `registry restore` | Same as llama.cpp |
| Strata (.strata pack) | ⚠️ TBD | TBD | Needs strata-specific restore |
| Basalt (.basalt pack from provider) | ✅ Yes | `registry restore` | Needs basalt provider |
| Basalt (.basalt pack local) | ❌ No | N/A | Never evicted |

### 5.2 Cross-Backend Storage Isolation

When multiple backends are installed on the same machine:

- [ ] **GAP-018**: The registry should track which backends are compatible with each stored model. When a
  model is resolved, the engine should verify that the target backend can use it (format check).
- [ ] **GAP-019**: Model packs for different backends should be stored in separate areas to avoid confusion:
  - `basalt/qwen36-35b/expert-profile@20261123` — Basalt expert profile
  - `local/qwen36-35b/Q8_0@20261123` — llama.cpp quantization
  - `hf/mudler/Qwen3.6-35B-A3B-APEX-GGUF@unpinned-20260520` — original GGUF download

## 6. Migration and Compatibility

### 6.1 Existing Models

The current registry on the development machine holds 14 versions (5 GGUF downloads, 9 Sub0Llm transformations).
All are GGUF format. When Strata and Basalt adapters are used:

- [ ] **GAP-020**: Verify that existing GGUF models in the registry are compatible with Strata and Basalt.
  The engine should run a compatibility check before launching a non-llama.cpp backend with a registry model.
- [ ] **GAP-021**: Document which GGUF architectures are known to work with each backend. The registry's
  `facts.architecture` field should include a `compatibleBackends` list.

### 6.2 Registry Schema Extensions

The manifest schema (`spec/manifest.schema.json`) needs extensions for backend-specific metadata:

```json
{
  "schema": "sub0llm-model-registry/manifest/1",
  "id": "...",
  "format": "gguf",
  "backendFormats": ["gguf", "safetensors"],  // formats this model can be used with
  "compatibleBackends": ["llamacpp", "strata"],  // backends known to work with this model
  "facts": { ... },
  "backendFacts": {  // backend-specific facts (optional)
    "basalt": { "expertCount": 256, "kvStorage": "fp16" },
    "strata": { "contextWindow": 8192 }
  }
}
```

## 7. Priority Summary

| Gap | Priority | Description |
|---|---|---|
| GAP-008 | **Critical** | Basalt model packs have no registry support (no `.basalt` area) |
| GAP-009 | **Critical** | No Basalt-specific fact extraction from model packs |
| GAP-010 | **High** | No Basalt model pack acquisition provider |
| GAP-012 | **High** | No Basalt expert profile management in registry |
| GAP-013 | **High** | No conversion pipeline between formats |
| GAP-006 | **Medium** | Strata version mismatch (CLI vs GitHub tags) |
| GAP-007 | **Medium** | No model identity verification across backends |
| GAP-002 | **Medium** | No `derivedFrom` recording for quantizations |
| GAP-003 | **Medium** | No automatic quantization pipeline |
| GAP-001 | **Low** | No non-GGUF format support for llama.cpp (future) |
| GAP-014 | **Low** | Backend version recording in manifests |
| GAP-015 | **Low** | Backend version compatibility warnings |
| GAP-016 | **Low** | Basalt version detection from help/binary metadata |
| GAP-018 | **Low** | Cross-backend storage isolation |
| GAP-020 | **Low** | Existing model compatibility verification |

## 8. References

- [Registry Format Spec](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/spec/LAYOUT.md)
- [Registry Manifest Schema](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/spec/manifest.schema.json)
- [Registry README](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/README.md)
- [Registry gguf.facts()](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/sub0llmregistry/gguf.py)
- [Registry store.py](https://github.com/CraigHutchinson/Sub0LlmModelRegistry/blob/main/sub0llmregistry/store.py)
- [Engine registry.py](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/sub0llmengine/registry.py)
- [Engine process.py](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/sub0llmengine/process.py)
- [Engine llamacpp backend](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/sub0llmengine/backends/llamacpp.py)
- [Engine strata backend](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/sub0llmengine/backends/strata.py)
- [Engine basalt backend](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/sub0llmengine/backends/basalt.py)
- [Engine versions.py](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/sub0llmengine/versions.py)
- [Backlog](https://github.com/CraigHutchinson/Sub0LlmEngine/blob/main/docs/BACKLOG.md)
