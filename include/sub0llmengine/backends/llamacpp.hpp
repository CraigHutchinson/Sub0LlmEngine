#pragma once
#include "sub0llmengine/contracts/llama_config.hpp"

#include <expected>
#include <string>
#include <string_view>
#include <vector>

namespace sub0llmengine::backends
{

struct BackendError
{
    std::string message;
};

/// What the installed llama-server accepts, probed from its `--help` by the supervision layer; the command builder stays pure.
struct LlamaCapabilities
{
    bool loadMode = false;          // `-lm` / `--load-mode` replaced `--no-mmap` upstream in late 2026
    bool kvUnifiedPerSlot = false;  // `--kv-unified-per-slot` (ggml-org/llama.cpp#24124)
};

/// The argv that serves an OpenAI-compatible API with llama-server (executable first), the same arguments, in the same order, as
/// sub0llmengine/backends/llamacpp.py serverCommand (the Python reference writes tests/fixtures/backends/llamacpp_command.json).
[[nodiscard]] std::expected<std::vector<std::string>, BackendError> llamaServerCommand(const contracts::LlamaServerConfig& config,
                                                                                       std::string_view executable, std::string_view modelPath,
                                                                                       const LlamaCapabilities& capabilities);

}  // namespace sub0llmengine::backends
