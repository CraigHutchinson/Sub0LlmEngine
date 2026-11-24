#pragma once
#include "sub0llmengine/contracts/bench_record.hpp"  // ContractError, Params

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>
#include <vector>

namespace sub0llmengine::contracts
{

/// What `start` recorded about the engine it started (`out/engine.json`, format `sub0llmengine.engine.v1`, the same document the Python
/// reference writes: README "Using the engine from another project"). `status` and `stop` read it; a consumer reads it through `status --json`.
struct EngineRecord
{
    std::string format = "sub0llmengine.engine.v1";
    std::int64_t pid = 0;
    std::string url;  // the OpenAI-compatible base, ending in /v1
    std::string startedAt;
    std::string backend;
    std::string build;
    std::string modelId;    // the registry id, with #file when a file was chosen
    std::string modelPath;
    Params config;          // the effective settings the server was started with
    std::vector<std::string> command;
    std::string log;
};

[[nodiscard]] std::string toJson(const EngineRecord& record);
[[nodiscard]] std::expected<EngineRecord, ContractError> parseEngineRecord(std::string_view json);

/// The scalar members of a flat JSON object (strings, integers, reals, flags); nested values are skipped. For the machine-local
/// `engine.local.json`, whose keys the tools read by name.
[[nodiscard]] std::expected<Params, ContractError> parseFlatParams(std::string_view json);

}  // namespace sub0llmengine::contracts
