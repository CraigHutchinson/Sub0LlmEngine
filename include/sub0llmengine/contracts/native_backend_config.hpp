#pragma once
#include "sub0llmengine/contracts/bench_record.hpp"  // ContractError

#include <cstdint>
#include <expected>
#include <optional>
#include <string>
#include <string_view>

namespace sub0llmengine::contracts
{

/// Strata serves from its own run profile (native JSON written by Strata's tools); the engine adds only where it listens and how many
/// requests it overlaps. Paths are as written in the config; the supervision layer checks that the files exist.
struct StrataConfig
{
    std::string strataBin;
    std::string strataProfile;
    std::string host = "127.0.0.1";
    std::int64_t port = 8092;
    std::optional<std::int64_t> slots;
};

/// Basalt serves from its own server config, which must bind the same host and port as the engine config: the engine passes nothing else.
struct BasaltConfig
{
    std::string basaltBin;
    std::string basaltConfig;
};

[[nodiscard]] std::expected<StrataConfig, ContractError> parseStrataConfig(std::string_view json);
[[nodiscard]] std::expected<BasaltConfig, ContractError> parseBasaltConfig(std::string_view json);

}  // namespace sub0llmengine::contracts
