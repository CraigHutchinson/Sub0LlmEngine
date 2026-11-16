# The model registry

Every model weight file on this machine lives under this folder, once. Tools (llama.cpp, Sub0Llm, Sub0Squad, anything
else) find a model through the registry, by alias or by its full id, never by a path they made up.

## Layout

```
<registry>\
  README.md            this file
  aliases.json         hand-edited: short names -> a registry id (the only file you edit to "upgrade" a model)
  registry.json        GENERATED from every MANIFEST.json and aliases.json (Registry.ps1 index); do not edit
  Registry.ps1         list | index | resolve <alias-or-id> | verify [-Hash] | new-manifest
  hf\                  upstream downloads, exactly as published; never edited in place
    <org>\<repo>\<revision>\<files...>
  sub0llm\             Sub0Llm transformations (custom formats: S0L5 .bin, .moeq, .bbq, .bbq.pair, ...)
    <model>\<variant>\<version>\<files...>
  local\               other local derivations (our own llama-quantize outputs, merges, LoRA adapters, imatrix files)
    <model>\<variant>\<version>\<files...>
  _incoming\           partial downloads and work in progress; nothing may reference a path in here
```

Every leaf folder (`<revision>` or `<version>`) is one **version** and holds a `MANIFEST.json`. A version is
**immutable** once its manifest is written: to change a model, make a new version beside it and move the alias.
Old versions stay until deleted on purpose, so a result recorded against an id can always be reproduced.

### Naming

| Part | Rule | Examples |
|---|---|---|
| `<org>\<repo>` | the Hugging Face repo id, unchanged | `mudler\Qwen3.6-35B-A3B-APEX-GGUF` |
| `<revision>` | the HF commit, first 12 hex chars; `unpinned-YYYYMMDD` (date obtained) when the commit was not recorded | `198f08841147`, `unpinned-20260520` |
| `<model>` | lower-case base model name, `-` separated | `qwen4-full48`, `qwen4-sub4` |
| `<variant>` | what differs between siblings: precision, format, recipe | `q`, `bf16`, `fp8`, `fp8-q`, `o5-headonly` |
| `<version>` | `YYYYMMDD`, plus `-label` when two are made the same day | `20260923`, `20260911-recheck` |

### Registry ids

`<area>/<path>@<version>`, with `#<file>` to name one file of a multi-file version:

```
hf/mudler/Qwen3.6-35B-A3B-APEX-GGUF@unpinned-20260520#Qwen3.6-35B-A3B-APEX-I-Compact.gguf
sub0llm/qwen4-full48/bf16@20260923
```

A split GGUF (`-00001-of-0000N.gguf`) is named by its first shard; llama.cpp loads the rest from the same folder.

## MANIFEST.json

```json
{
  "id": "sub0llm/qwen4-full48/bf16@20260923",
  "format": "sub0llm-s0l5",             // gguf | gguf-mmproj | safetensors | sub0llm-s0l5 | sub0llm-moeq | ...
  "architecture": "qwen3-moe",          // free text, optional
  "files": [ { "name": "qwen4_full48_q_bf16.bin", "bytes": 9876543210, "sha256": null } ],
  "source": { "kind": "hf", "repo": "org/repo", "revision": "<full sha or null>", "url": null },
  "derivedFrom": "hf/unsloth/Qwen3.8-Flash-Next-GGUF@unpinned-20260903",   // for sub0llm/ and local/
  "tool": { "name": "sub0llm-transplant", "commit": "<git sha>", "command": "..." },
  "created": "2026-09-23",
  "notes": "..."
}
```

`source` is for downloads, `derivedFrom` + `tool` for anything we made. `sha256` may be `null` until
`Registry.ps1 verify -Hash` fills it (hashing 100 GB takes a while); `bytes` is always checked.

## Using it

```powershell
<registry>\Registry.ps1 list                      # every version, its format and size
<registry>\Registry.ps1 resolve qwen36-35b-a3b    # -> absolute path of the file (what launchers pass to -m)
<registry>\Registry.ps1 index                     # rebuild registry.json after adding a version or editing aliases.json
<registry>\Registry.ps1 verify                    # every manifest's files exist with the recorded size
```

Tools that cannot run PowerShell read `registry.json` (`aliases` -> id -> `entries[id].path` / `files`). From WSL
the same tree is `/mnt/d/LlmModels/...`.

## Adding a model

1. Download into `_incoming\` (a download is the owner's go-ahead; set `HF_TOKEN` only in the environment).
2. Move it to its final folder (same drive: a rename, instant).
3. `Registry.ps1 new-manifest <folder> -Format gguf -Repo org/repo -Revision <sha>` (or `-DerivedFrom <id>`), then edit notes.
4. Point or add an alias in `aliases.json`; `Registry.ps1 index`.

## Migrating existing folders

Move a folder into its version folder (same drive: a rename) and leave a directory junction at the old path
(`New-Item -ItemType Junction -Path OLD -Target NEW`) so code that still names the old path keeps working; remove the
junction once nothing refers to it. Record each move in a `MIGRATION.log` at the registry root.
