#pragma once
#include "sub0llmengine/contracts/bench_record.hpp"

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace sub0llmengine::evidence
{

/// A black-box bench: it asks any OpenAI-compatible server (llama.cpp, Strata, Basalt) the same questions, so engines are compared on the
/// same footing and their points land in one bench history.
struct HttpBenchSpec
{
    std::string host = "127.0.0.1";
    std::uint16_t port = 8092;
    std::string model;                          // the name the server reports (/v1/models)
    std::vector<std::int64_t> depths{2048};     // prompt tokens per sequence
    std::vector<std::int64_t> concurrencies{1}; // B: sequences at once
    std::int64_t ntg = 128;                     // tokens generated per sequence
    std::optional<std::string> reasoningEffort = "none";
    std::chrono::seconds timeout{900};
    std::uint32_t seed = 1;

    // Identity of the records written (docs/TUNING_MAP.md "Evidence boundaries").
    std::string machine;
    std::string backend;
    std::string build;
    std::string modelId;                        // the registry id (the record's "model"); falls back to `model`
    contracts::Params params;                   // the configuration the server was started with
    std::string note = "http-bench";
};

/// Runs every depth x concurrency and returns one record each. Per point, two passes of B sequences with distinct prompts:
/// the first caps the reply at one token (so its time is the prefill), the second at `ntg` (prefill plus decode). Decode speed is the
/// extra tokens over the extra time. A server that refuses or fails gives an Oom or Error record, not an exception.
[[nodiscard]] std::vector<contracts::BenchRecord> runHttpBench(const HttpBenchSpec& spec);

/// A prompt of `words` words from a fixed vocabulary, different for each (seed, index): no two sequences share a prefix, so a prompt
/// cache cannot make one pass cheaper than the other.
[[nodiscard]] std::string syntheticPrompt(std::uint32_t seed, std::uint32_t index, std::int64_t words);

}  // namespace sub0llmengine::evidence
