#include "sub0llmengine/evidence/http_bench.hpp"

#include "sub0llmengine/contracts/chat_wire.hpp"
#include "sub0llmengine/net/http.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <ctime>
#include <format>
#include <thread>

namespace sub0llmengine::evidence
{
namespace
{

using Clock = std::chrono::steady_clock;

constexpr std::array<const char*, 64> vocabulary = {
    "river", "stone", "light", "garden", "window", "paper", "engine", "forest", "silver", "morning", "bridge", "market", "winter", "copper", "harbor",
    "island", "valley", "thunder", "ribbon", "lantern", "meadow", "canyon", "orchard", "compass", "anchor", "blanket", "candle", "feather", "glacier",
    "hammer", "journey", "kettle", "ladder", "marble", "needle", "oyster", "pebble", "quartz", "rocket", "saddle", "timber", "umbrella", "velvet",
    "willow", "yellow", "zephyr", "amber", "basket", "cactus", "dragon", "ember", "falcon", "granite", "horizon", "ivory", "jungle", "kitten",
    "lemon", "mirror", "nectar", "oasis", "pepper", "quiver", "raven"};

struct PassResult
{
    bool ok = true;
    bool oom = false;
    std::string error;
    std::int64_t promptTokens = 0;
    std::int64_t completionTokens = 0;
    double seconds = 0;
};

/// B requests at once, one thread and one client each; the pass lasts until the slowest answers.
PassResult runPass(const HttpBenchSpec& spec, std::uint32_t passSeed, std::int64_t words, std::int64_t maxTokens, std::int64_t b)
{
    struct One
    {
        bool ok = false;
        bool oom = false;
        std::string error;
        contracts::ChatUsage usage;
    };
    std::vector<One> results(static_cast<std::size_t>(b));
    std::vector<std::thread> threads;
    const auto started = Clock::now();
    for (std::int64_t i = 0; i < b; ++i)
    {
        threads.emplace_back([&, i] {
            auto client = net::makeHttpClient();
            contracts::ChatRequest request{spec.model, syntheticPrompt(passSeed, static_cast<std::uint32_t>(i), words), maxTokens, spec.reasoningEffort};
            net::HttpRequest http{"POST", "/v1/chat/completions", {{"Content-Type", "application/json"}}, contracts::toJson(request)};
            auto& out = results[static_cast<std::size_t>(i)];
            auto answer = client->send(spec.host, spec.port, http, std::chrono::duration_cast<std::chrono::milliseconds>(spec.timeout));
            if (!answer)
            {
                out.error = answer.error().message;
                return;
            }
            if (answer->status != 200)
            {
                out.error = std::format("HTTP {}: {}", answer->status, answer->body.substr(0, 200));
                std::string lower = answer->body;
                std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                out.oom = lower.find("out of memory") != std::string::npos || lower.find("failed to allocate") != std::string::npos;
                return;
            }
            auto usage = contracts::parseChatUsage(answer->body);
            if (!usage)
            {
                out.error = usage.error().message;
                return;
            }
            out.usage = *usage;
            out.ok = true;
        });
    }
    for (auto& t : threads)
    {
        t.join();
    }
    PassResult pass;
    pass.seconds = std::chrono::duration<double>(Clock::now() - started).count();
    for (const auto& one : results)
    {
        if (!one.ok)
        {
            pass.ok = false;
            pass.oom = pass.oom || one.oom;
            if (pass.error.empty())
            {
                pass.error = one.error;
            }
        }
        pass.promptTokens += one.usage.promptTokens;
        pass.completionTokens += one.usage.completionTokens;
    }
    return pass;
}

std::string timestamp()
{
    const auto now = std::time(nullptr);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &now);
#else
    localtime_r(&now, &tm);
#endif
    return std::format("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
}

}  // namespace

std::string syntheticPrompt(std::uint32_t seed, std::uint32_t index, std::int64_t words)
{
    std::uint64_t state = (static_cast<std::uint64_t>(seed) << 32) ^ (static_cast<std::uint64_t>(index) * 0x9E3779B97F4A7C15ull) ^ 0xD1B54A32D192ED03ull;
    std::string text = "Read this list of words and then say OK.";
    text.reserve(static_cast<std::size_t>(words) * 8 + text.size());
    for (std::int64_t i = 0; i < words; ++i)
    {
        state = state * 6364136223846793005ull + 1442695040888963407ull;
        text += ' ';
        text += vocabulary[(state >> 33) % vocabulary.size()];
    }
    return text;
}

std::vector<contracts::BenchRecord> runHttpBench(const HttpBenchSpec& spec)
{
    std::vector<contracts::BenchRecord> records;
    // How many tokens a word costs on this server's tokenizer: one small request, so a long prompt lands near its depth.
    double tokensPerWord = 1.3;
    constexpr std::int64_t calibrationWords = 256;
    const auto probe = runPass(spec, spec.seed + 7919, calibrationWords, 1, 1);
    if (!probe.ok && probe.error.starts_with("http request to"))
    {
        return records;  // nothing is listening: no point to record, and an error row would pollute the history
    }
    if (probe.ok && probe.promptTokens > 0)
    {
        tokensPerWord = static_cast<double>(probe.promptTokens) / static_cast<double>(calibrationWords);
    }
    for (const auto depth : spec.depths)
    {
        const auto words = std::max<std::int64_t>(1, static_cast<std::int64_t>(static_cast<double>(depth) / tokensPerWord));
        for (const auto b : spec.concurrencies)
        {
            contracts::BenchRecord r;
            r.ts = timestamp();
            r.machine = spec.machine;
            r.backend = spec.backend;
            r.build = spec.build;
            r.model = spec.modelId.empty() ? spec.model : spec.modelId;
            r.params = spec.params;
            r.depth = depth;
            r.ntg = spec.ntg;
            r.concurrency = b;
            r.note = spec.note;
            const auto prefill = runPass(spec, spec.seed * 2, words, 1, b);
            auto fail = [&](const PassResult& pass) {
                r.outcome = pass.oom ? contracts::Outcome::Oom : contracts::Outcome::Error;
                r.error = pass.error;
                records.push_back(r);
            };
            if (!prefill.ok)
            {
                fail(prefill);
                continue;
            }
            const auto full = runPass(spec, spec.seed * 2 + 1, words, spec.ntg, b);
            if (!full.ok)
            {
                fail(full);
                continue;
            }
            const auto extraTokens = full.completionTokens - prefill.completionTokens;
            const auto extraSeconds = full.seconds - prefill.seconds;
            if (extraTokens <= 0 || extraSeconds <= 0)
            {
                PassResult odd;
                odd.error = std::format("no decode to measure: {} extra tokens in {:.3f} s (the reply stopped at once, or prefill dominated)", extraTokens, extraSeconds);
                fail(odd);
                continue;
            }
            r.outcome = contracts::Outcome::Ok;
            r.wallSec = prefill.seconds + full.seconds;
            r.ppTps = static_cast<double>(prefill.promptTokens) / prefill.seconds;
            r.tgTps = static_cast<double>(extraTokens) / extraSeconds;
            r.tgPerSeq = *r.tgTps / static_cast<double>(b);
            records.push_back(r);
        }
    }
    return records;
}

}  // namespace sub0llmengine::evidence
