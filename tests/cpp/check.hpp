#pragma once
// Tiny test helpers: no framework dependency. A test program ends with `return finish();`, which turns the failure count into the exit
// code (cmake/CheckTests.cmake fails any test that uses CHECK without it).
#include <cstdio>

inline int gFailures = 0;
#define CHECK(cond) do { if (!(cond)) { std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); ++gFailures; } } while (0)
#define CHECK_EQ(a, b) do { auto&& _a = (a); auto&& _b = (b); if (!(_a == _b)) { std::fprintf(stderr, "%s:%d: CHECK_EQ failed: %s != %s\n", __FILE__, __LINE__, #a, #b); ++gFailures; } } while (0)
inline int finish() { if (gFailures) std::fprintf(stderr, "%d check(s) failed\n", gFailures); return gFailures ? 1 : 0; }
