# Testing and tiers

Python reference tests: `python -m unittest discover -s tests` (no GPU, nothing starts a model). C++ tests: `tests/cpp/test_*.cpp`,
each ending `return finish();` (`cmake/CheckTests.cmake` fails one that does not).

## Labels (cmake/TestTiers.cmake)

Every ctest test has exactly one **tier** and one **area**, and any **needs**; configure fails otherwise.

| Label | Values | Meaning |
|---|---|---|
| tier | `smoke` | fast, no hardware: CI on every push |
| | `full` | long suites: CI at tags, `ci:full`, weekly |
| | `local` | needs this machine; never scheduled by CI |
| `area:<name>` | structure platform net contracts evidence backends supervision registry control service reference tooling | the layer or concern covered |
| `needs:<x>` | gpu backend network admin | any needs forces tier `local`; `needs:gpu` takes the `gpu` resource lock |
| `cost:slow` | | a long test inside its tier |

## Presets

| `ctest --preset` | Runs | Where |
|---|---|---|
| `quick` | not full, not local | CI smoke |
| `full` | smoke + full | CI full |
| `local` | everything | owner, before pushing |
| `gpu` | `needs:gpu` only | owner |

CI can therefore never schedule a test that needs a GPU or a backend. Performance is measured locally (sub0perf workflows,
docs/SERVICE.md), not in CI. The label grammar and rules are written to be lifted into the family's shared spec; each project
that adopts it feeds its additions back (areas stay per project, tiers and needs are shared).
