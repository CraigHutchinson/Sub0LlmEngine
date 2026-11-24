<#
Interim launcher for a Basalt server (until the engine CLI does this): the counterpart of the old llama.cpp Serve.ps1.
Reads basaltBin and basaltPack from engine.local.json (machine-local, not in the repository).
  .\tools\Serve-Basalt.ps1 -MaxContext 131072 -Kv fp8     # start, wait for /health, leave running
  .\tools\Serve-Basalt.ps1 -Stop                          # stop it
Anything else for basalt goes in -ExtraArgs, e.g. -ExtraArgs '--pool-workers','8'.
#>
param(
    [int]$Port = 8092,
    [int]$MaxContext = 131072,
    [string]$Kv = 'fp8',
    [int]$Parallel = 1,
    [string]$Alias = 'Inkling 2 Mini',
    [string[]]$ExtraArgs = @(),
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$cfg = Get-Content (Join-Path $root 'engine.local.json') -Raw | ConvertFrom-Json
$pidFile = Join-Path $root "out/basalt-$Port.pid"
New-Item -ItemType Directory -Force (Join-Path $root 'out') | Out-Null

if ($Stop) {
    if (Test-Path $pidFile) { Stop-Process -Id (Get-Content $pidFile) -Force -ErrorAction SilentlyContinue; Remove-Item $pidFile }
    return
}
$log = Join-Path $root "out/basalt-$Port.log"
$argv = @('serve', '--model', $cfg.basaltPack, '--alias', "`"$Alias`"", '--host', '127.0.0.1', '--port', $Port,
          '--max-context', $MaxContext, '--kv', $Kv, '--parallel', $Parallel) + $ExtraArgs
$p = Start-Process -FilePath $cfg.basaltBin -ArgumentList $argv -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
$p.Id | Set-Content $pidFile
Write-Host "basalt pid $($p.Id), log $log"
for ($i = 0; $i -lt 300; $i++) {
    if ($p.HasExited) { Write-Host "exited $($p.ExitCode)"; Get-Content "$log.err" -Tail 20; exit 1 }
    try { if ((Invoke-WebRequest "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { Write-Host "ready on http://127.0.0.1:$Port"; return } } catch {}
    Start-Sleep 2
}
Write-Host 'not ready after 10 minutes'; exit 1
