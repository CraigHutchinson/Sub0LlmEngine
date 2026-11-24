#pragma once
#include "sub0llmengine/contracts/bench_record.hpp"  // ContractError

#include <cstdint>
#include <expected>
#include <optional>
#include <string>
#include <string_view>

namespace sub0llmengine::contracts
{

/// The part of an OpenAI-compatible chat request the bench sends: one user message, greedy sampling, a token cap. Every backend answers it.
struct ChatRequest
{
    std::string model;
    std::string prompt;
    std::int64_t maxTokens = 1;
    std::optional<std::string> reasoningEffort;  // "none" keeps a thinking model short
};

[[nodiscard]] std::string toJson(const ChatRequest& request);

/// What a reply reports about its own size.
struct ChatUsage
{
    std::int64_t promptTokens = 0;
    std::int64_t completionTokens = 0;
};

[[nodiscard]] std::expected<ChatUsage, ContractError> parseChatUsage(std::string_view json);

}  // namespace sub0llmengine::contracts
