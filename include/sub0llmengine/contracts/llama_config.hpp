#pragma once
#include "sub0llmengine/contracts/bench_record.hpp"  // ContractError

#include <cstdint>
#include <expected>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace sub0llmengine::contracts
{

/// The llama.cpp serving knobs of an engine config (config/engine.defaults.json, engine.local.json), with the defaults
/// sub0llmengine/backends/llamacpp.py applies. Keys not listed here are ignored: the config also carries machine paths and other
/// backends' settings.
struct LlamaServerConfig
{
    std::string host = "127.0.0.1";
    std::int64_t port = 8092;
    std::int64_t ctx = 32768;
    std::int64_t slots = 4;
    std::int64_t gpuLayers = 99;
    std::optional<std::int64_t> nCpuMoe;
    std::string flashAttn = "on";
    std::string cacheTypeK = "q8_0";
    std::string cacheTypeV = "q8_0";
    std::int64_t batch = 2048;
    std::int64_t ubatch = 512;
    std::int64_t threads = -1;
    bool mmap = false;
    bool kvUnified = true;
    std::string alias = "local";
    std::optional<std::int64_t> ctxCheckpoints;
    std::optional<std::int64_t> cacheRam;
    std::optional<std::int64_t> kvUnifiedPerSlot;
    std::vector<std::string> extraArgs;
};

/// A JSON object (an engine config layer already merged) to the serving knobs; a knob of the wrong type is refused by name.
[[nodiscard]] std::expected<LlamaServerConfig, ContractError> parseLlamaServerConfig(std::string_view json);

}  // namespace sub0llmengine::contracts
