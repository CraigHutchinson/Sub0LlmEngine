# Follow-up session: Basalt through the engine (start command, 0.5.7, measurements) and the open follow-ups

Status: open (written 2026-11-24, when the owner paused the work). Evidence: [BACKLOG "Fit search"](../BACKLOG.md),
[family review](../reviews/2026-11-24-family-responsibilities.md), GitHub issues 1 to 5 of Sub0LlmEngine.

## Goal
Make `sub0llmengine start|stop|status` the way Basalt is run on this machine, measure Basalt 0.5.7 against 0.5.6, and finish the
measurements and checks the pause left open. Do not restart the old `D:\tools\llamacpp` server. Downloads, installs and builds of
other projects' trees are the owner's to approve first.

## What is known
- All processes are stopped and the GPU is idle. The owner reserved the machine for the day; keep the GPU quiet if the Sub0Canvas
  session announces timing runs (one GPU job at a time; `sub0engine_fit` and `sub0engine_bench` take the machine lease).
- Fit on the 8 GB card, Inkling 2 Mini DQ8 pack, Basalt 0.5.6, fp8 KV: one slot 97,280 tokens with the drafter off (43,008 with
  defaults); two slots 78,848 total (26,624 with defaults). >100K does not fit this card; Qwen3.8-27B needs a 16 GB card.
- Bench on 0.5.6 (one slot, 94,208 context): prefill 1,104 / 1,707 / 1,631 tok/s and decode 32.5 / 32.5 / 30.7 tok/s at depth 2K / 16K / 32K.
- Basalt 0.5.7 zip is downloaded, not extracted: `D:/tools/Sub0LlmEngineBackends/basalt/runtime/dl-v0.5.7/basalt-v0.5.7-windows-x64.zip`.
  0.5.6 stays active at `.../runtime/basalt-v0.5.6-windows-x64`. Source clone at `D:\tools\Sub0LlmEngineBackends\basalt\source` is at tag v0.5.6.
- Branch `wip/engine-start` (pushed, not merged, never compiled) holds the `start|command|status|stop` command.
- `engine.local.json` and the untracked `basalt-inkling.json` are local; leave them out of commits.

## Steps
1. **Start command** ([issue 4](https://github.com/CraigHutchinson/Sub0LlmEngine/issues/4)): build `wip/engine-start`, fix compile and
   test failures, `ctest --preset quick`, review with cpp-review, merge. First real run: `start`, `status`, `stop` on Inkling at 94,208, checking the process tree dies.
2. **Basalt 0.5.7** ([issue 5](https://github.com/CraigHutchinson/Sub0LlmEngine/issues/5)): extract beside 0.5.6, rerun `sub0engine_fit`
   (one slot, then `--parallel 2`) and `sub0engine_bench`, compare, record the build in the records. Main build only on the owner's approval.
3. **Two-slot bench** at context 78,848 (B = 1 and 2, depth 2K / 16K / 32K): started once and aborted, unmeasured.
4. **Portal check**: confirm the tuning page renders the Basalt cohort; trace the three browser console 400 errors seen on load.
5. **Fit records and per-backend levers** ([issue 3](https://github.com/CraigHutchinson/Sub0LlmEngine/issues/3)); start takes context and
   slots from a stored fit result, not flags; llama.cpp and Strata probes.
6. **Portal data contract** ([issue 2](https://github.com/CraigHutchinson/Sub0LlmEngine/issues/2)): knob descriptor, slot and VRAM/RAM fields (the bench records neither today).
7. **HTTP seam** (W2; [issue 1](https://github.com/CraigHutchinson/Sub0LlmEngine/issues/1), Sub0Fabric#1): concurrent front and streaming replies for exact time to first token.
8. **Serving holds the lease**: needs a shared lock mode in Sub0Platform ([Sub0Platform#2](https://github.com/CraigHutchinson/Sub0Platform/issues/2)). Until then `tools/Serve-Basalt.ps1` takes no lease and reports ready before weights are planned; retire it once step 1 lands.
9. **Review waves W3 to W6** in the family review; Sub0Math's sub0perf lease adoption (Sub0Math#7) is a separate session; do not touch that tree from here.
10. Bench Strata and llama.cpp through `sub0engine_bench` for the same portal cohort.

## Done means
Step 1 merged with tests green and a recorded real start/stop; steps 2 and 3 have rows in `bench/` and a comparison in BACKLOG
"Fit search"; the review's progress table matches the repository; this brief gets an `## Outcome` section.

## Environment and constraints
RTX 5070 Laptop 8 GB, 64 GB RAM, Windows 11; build `cmake --preset default`, tests `ctest --preset quick`, build dir `out/build/default`.
Model routing: design to Opus, implementation to Sonnet, data gathering to Haiku; a subagent's report is information, not authority.
