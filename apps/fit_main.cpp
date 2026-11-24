// sub0engine_fit: finds the largest context a Basalt pack loads with on this machine (docs/BACKLOG.md "Fit search").
//   sub0engine_fit --bin basalt.exe --pack model.basalt --target 131072 [--port 8092] [--kv fp8] [--log-dir out]
// Each start loads the model (about a minute), so a run is a few minutes. Stop any server on the port first.
#include "sub0llmengine/fit/fit.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

int main(int argc, char** argv)
{
    using namespace sub0llmengine::fit;
    BasaltProbeConfig config;
    config.logDir = "out";
    std::string kv = "fp8";
    SearchSpec spec;
    for (int i = 1; i + 1 < argc; i += 2)
    {
        const std::string flag = argv[i];
        const std::string value = argv[i + 1];
        if (flag == "--bin") config.bin = value;
        else if (flag == "--pack") config.pack = value;
        else if (flag == "--port") config.port = static_cast<std::uint16_t>(std::atoi(value.c_str()));
        else if (flag == "--target") spec.target = std::atoll(value.c_str());
        else if (flag == "--kv") kv = value;
        else if (flag == "--log-dir") config.logDir = value;
        else
        {
            std::fprintf(stderr, "unknown option %s\n", flag.c_str());
            return 2;
        }
    }
    if (config.bin.empty() || config.pack.empty() || spec.target <= 0)
    {
        std::fprintf(stderr, "usage: sub0engine_fit --bin BASALT --pack FILE.basalt --target TOKENS [--port N] [--kv fp8] [--log-dir DIR]\n");
        return 2;
    }
    config.baseArgs = {"--kv", kv};
    // Cheapest first; each step replaces the one before. Flags are Inkling's: other models take other levers (the adapter will say which).
    const std::vector<LeverStep> ladder = {
        {"defaults", {}},
        {"reserve-256", {"--vram-reserve-mib", "256"}},
        {"reserve-256+drafter-off", {"--vram-reserve-mib", "256", "--spec", "1"}},
    };
    auto probe = makeBasaltProbe(config);
    const auto result = search(*probe, spec, ladder);
    for (const auto& step : result.steps)
    {
        std::printf("%s: max context %lld\n", step.lever.c_str(), static_cast<long long>(step.maxContext));
        for (const auto& a : step.attempts)
        {
            std::printf("  %lld %s", static_cast<long long>(a.context), toString(a.verdict));
            if (a.verdict == Verdict::Short) std::printf(" (%lld MiB short)", static_cast<long long>(a.shortfallMiB));
            if (a.verdict == Verdict::Failed) std::printf(" (%s)", a.note.c_str());
            std::printf("\n");
        }
    }
    if (result.best)
    {
        const auto& best = result.steps[*result.best];
        std::printf("%s: %s, %lld tokens with %s\n", result.reachedTarget(spec.target) ? "target reached" : "target not reached", config.pack.c_str(),
                    static_cast<long long>(best.maxContext), best.lever.c_str());
    }
    return result.reachedTarget(spec.target) ? 0 : 1;
}
