# Strata

## Acquired release

The Windows x64 Strata control package and CUDA 13 engine were acquired from the official release page into
`D:\tools\Sub0LlmEngineBackends\strata\`, outside the repository. The downloaded archives were SHA-256 verified:

| Package | SHA-256 |
|---|---|
| Control package | `2130761067a1c83a6066027866d1dde087402a820859e4008b113a3e5f758122` |
| Windows x64 CUDA 13 engine | `d0fa583e60aaf1d256926b6ea9889ff3ce42a98dbf56f2b556703a76b65e0a64` |

The engine was installed into the isolated `D:\tools\Sub0LlmEngineBackends\strata\components\` directory using Strata's
offline installer, which verified the package signature. It registered engine `0.1.66` (`windows-x86_64`, `cuda13`,
build `2e87c08db18a+cuda13.0`, `signed: true`). `strata --version` reports the control version and the engine build
(`strata 0.2.20 (build 0.1.66; ...)`); 0.2.20 is also the latest GitHub release (checked 2026-11-23). No model was
installed or loaded.

The CLI reported no active Strata launch. A no-change plan was checked and not executed; it proposed a 68.5 GB model
download. No Strata inference or GPU profiling was run. The separate llama.cpp server was not stopped or modified.

## Configure the adapter

Create a Strata run profile using Strata's documented workflow. Point the engine config to that profile and the Strata
control CLI:

```json
{
  "backend": "strata",
  "strataBin": "D:/tools/Sub0LlmEngineBackends/strata/control/bin/strata.cmd",
  "strataProfile": "D:/path/to/strata-run-profile.json",
  "strataVersion": "0.1.66",
  "model": "D:/path/to/the-model-used-by-the-profile",
  "host": "127.0.0.1",
  "port": 8093,
  "slots": 2
}
```

`strataProfile` is native Strata JSON; Sub0LlmEngine does not synthesize or rewrite it. Set `model` to the same artifact
the profile uses. The adapter runs:

```text
strata serve --profile <strataProfile> --engine strata --host <host> --port <port> --parallel <slots>
```

On Windows, `.cmd` launchers are executed through `COMSPEC`. The serving process binds the configured host/port, and
`slots` is passed as Strata's parallelism override. Set the profile's model, context and other engine options in Strata's
own configuration. If invoking a different CLI entry point or platform build, set `strataBin` to that executable.

The current status integration uses `/health` and `/v1/models` for model/context information; busy-slot telemetry remains unavailable.
The shared benchmark sweep refuses Strata until results can be represented without conflating Strata's native metrics
with llama.cpp measurements.

## Reproduce acquisition checks

From the extracted control package, use the signed offline installer with an isolated component directory:

```powershell
.\strata.cmd components install-file D:\path\to\strata-engine-0.1.66-windows-x86_64-cuda-cuda13.tar.gz `
  --components-dir D:\tools\Sub0LlmEngineBackends\strata\components --json
.\strata.cmd components engines --components-dir D:\tools\Sub0LlmEngineBackends\strata\components --json
```

Use the release page's published checksums before installation. `components install-file` verifies the package signature
and performs the binary-only `--version` check when no model is installed.
