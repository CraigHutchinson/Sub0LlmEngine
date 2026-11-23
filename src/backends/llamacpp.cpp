#include "sub0llmengine/backends/llamacpp.hpp"

namespace sub0llmengine::backends
{
namespace
{

void add(std::vector<std::string>& argv, std::string_view flag, std::string value)
{
    argv.emplace_back(flag);
    argv.push_back(std::move(value));
}

}  // namespace

std::expected<std::vector<std::string>, BackendError> llamaServerCommand(const contracts::LlamaServerConfig& c, std::string_view executable,
                                                                          std::string_view modelPath, const LlamaCapabilities& capabilities)
{
    if (c.kvUnifiedPerSlot && *c.kvUnifiedPerSlot != 0 && !capabilities.kvUnifiedPerSlot)
    {
        return std::unexpected(BackendError{"kvUnifiedPerSlot is set but this build has no --kv-unified-per-slot (upstream since 2026-08, "
                                            "ggml-org/llama.cpp#24124): use a newer build or remove the key"});
    }
    std::vector<std::string> argv{std::string{executable}};
    add(argv, "-m", std::string{modelPath});
    add(argv, "--host", c.host);
    add(argv, "--port", std::to_string(c.port));
    add(argv, "-c", std::to_string(c.ctx));
    add(argv, "-np", std::to_string(c.slots));

    // Placement, memory and compute flags: shared with the bench in the reference.
    add(argv, "-ngl", std::to_string(c.gpuLayers));
    if (c.nCpuMoe)
    {
        add(argv, "-ncmoe", std::to_string(*c.nCpuMoe));
    }
    add(argv, "-fa", c.flashAttn);
    add(argv, "-ctk", c.cacheTypeK);
    add(argv, "-ctv", c.cacheTypeV);
    add(argv, "-b", std::to_string(c.batch));
    add(argv, "-ub", std::to_string(c.ubatch));
    add(argv, "-t", std::to_string(c.threads));
    if (capabilities.loadMode)
    {
        add(argv, "-lm", c.mmap ? "mmap" : "none");
    }
    else if (!c.mmap)
    {
        argv.emplace_back("--no-mmap");
    }
    if (c.kvUnified)
    {
        argv.emplace_back("-kvu");
    }

    add(argv, "--alias", c.alias);
    argv.emplace_back("--metrics");
    argv.emplace_back("--jinja");
    if (c.ctxCheckpoints)
    {
        add(argv, "-ctxcp", std::to_string(*c.ctxCheckpoints));
    }
    if (c.cacheRam)
    {
        add(argv, "-cram", std::to_string(*c.cacheRam));
    }
    if (c.kvUnifiedPerSlot && *c.kvUnifiedPerSlot != 0)
    {
        add(argv, "--kv-unified-per-slot", std::to_string(*c.kvUnifiedPerSlot));
    }
    argv.insert(argv.end(), c.extraArgs.begin(), c.extraArgs.end());
    return argv;
}

}  // namespace sub0llmengine::backends
