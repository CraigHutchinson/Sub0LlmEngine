# Basalt

## Acquired release

Basalt `0.5.6` for Windows x64 was acquired from the official release page and extracted under
`D:\tools\Sub0LlmEngineBackends\basalt\`, outside the repository. The archive SHA-256 was
`9a8998db0c7c3a7719e58816d46d9fd03e468481ff7e6ac1f71414c02568f668`.

The release's CLI checks passed for `basalt.exe --help`, `basalt-bench.exe --help` and `basalt.exe serve --help`.
Python requirements were installed in an isolated virtual environment and `pip check` reported no broken requirements.
`basalt.exe --version` is not a supported command. No model pack was downloaded, no server was started, and no inference
or GPU profiling was run. The separately running llama.cpp server was left untouched.

## Configure the adapter

Create a Basalt server config with Basalt's own tooling, then set the CLI and config path in an engine config layer:

```json
{
  "backend": "basalt",
  "basaltBin": "D:/path/to/the/extracted/windows-x64/basalt.exe",
  "basaltConfig": "D:/path/to/basalt-server-config.json",
  "basaltVersion": "0.5.6",
  "model": "D:/path/to/the/model-used-by-the-config",
  "host": "127.0.0.1",
  "port": 8092,
  "slots": 1
}
```

`basaltConfig` is native Basalt config; Sub0LlmEngine does not synthesize it or install `.basalt` model packs. Keep
`model` aligned with the artifact in that config. The adapter runs:

```text
basalt serve --config <basaltConfig>
```

Basalt's config must bind the same host and port as the engine config; unlike Strata's CLI, this adapter does not append
host/port or concurrency overrides. Set Basalt-specific context and concurrency settings in the native config.

The current status integration uses `/health` and `/v1/models` for model/context information; busy-slot telemetry remains unavailable.
The shared benchmark sweep refuses Basalt until native benchmark results can be stored separately from, and compared
carefully with, llama.cpp metrics. The release wrapper's child-process shutdown behavior has not been validated; validate
that lifecycle before relying on managed stop for a real Basalt server.
