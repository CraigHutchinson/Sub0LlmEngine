// The black-box bench measures prefill and decode speed of an OpenAI-compatible server it knows nothing else about. A fake server whose
// answer time is proportional to the tokens read and written stands in; its speeds are known, so the bench's numbers can be checked.
#include "check.hpp"
#include "sub0llmengine/contracts/chat_wire.hpp"
#include "sub0llmengine/evidence/http_bench.hpp"
#include "sub0llmengine/net/http.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <format>
#include <string>
#include <thread>

namespace
{

using namespace sub0llmengine;

// The fake reads 20,000 prompt tokens per second and writes 500 tokens per second, whatever else is going on.
constexpr double promptTokensPerSecond = 20000;
constexpr double replyTokensPerSecond = 500;

std::int64_t wordsIn(const std::string& body)
{
    // The request is JSON, but only the number of spaces in it matters to the fake: one token per word.
    return std::count(body.begin(), body.end(), ' ');
}

std::int64_t maxTokensOf(const std::string& body)
{
    const auto at = body.find("\"max_tokens\":");
    return at == std::string::npos ? 1 : std::atoll(body.c_str() + at + 13);
}

}  // namespace

int main()
{
    // Wire contract.
    {
        contracts::ChatRequest request{"Inkling 2 Mini", "say \"hi\"", 16, "none"};
        const auto text = contracts::toJson(request);
        CHECK(text.find("\"model\":\"Inkling 2 Mini\"") != std::string::npos);
        CHECK(text.find("say \\\"hi\\\"") != std::string::npos);
        CHECK(text.find("\"max_tokens\":16") != std::string::npos);
        CHECK(text.find("\"reasoning_effort\":\"none\"") != std::string::npos);
        const auto usage = contracts::parseChatUsage(R"({"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}})");
        CHECK(usage.has_value() && usage->promptTokens == 12 && usage->completionTokens == 3);
        CHECK(!contracts::parseChatUsage("{}").has_value());
        CHECK(!contracts::parseChatUsage("nope").has_value());
    }
    // Prompts differ per sequence and repeat for the same seed.
    {
        CHECK(evidence::syntheticPrompt(1, 0, 50) != evidence::syntheticPrompt(1, 1, 50));
        CHECK(evidence::syntheticPrompt(1, 0, 50) == evidence::syntheticPrompt(1, 0, 50));
        CHECK(evidence::syntheticPrompt(1, 0, 50) != evidence::syntheticPrompt(2, 0, 50));
    }

    auto front = net::makeHttpFront();
    auto port = front->start("127.0.0.1", 0, [](const net::HttpRequest& req) {
        if (req.body.find("\"model\":\"refuse\"") != std::string::npos)
        {
            return net::HttpResponse{400, {}, R"({"error":"prompt longer than the slot"})"};
        }
        const auto prompt = wordsIn(req.body);
        const auto reply = maxTokensOf(req.body);
        const double seconds = static_cast<double>(prompt) / promptTokensPerSecond + static_cast<double>(reply) / replyTokensPerSecond;
        std::this_thread::sleep_for(std::chrono::duration<double>(seconds));
        return net::HttpResponse{200, {}, std::format(R"({{"usage":{{"prompt_tokens":{},"completion_tokens":{}}}}})", prompt, reply)};
    });
    CHECK(port.has_value());
    if (!port)
    {
        return finish();
    }

    evidence::HttpBenchSpec spec;
    spec.port = *port;
    spec.model = "fake";
    spec.depths = {4000};
    spec.concurrencies = {1, 2};
    spec.ntg = 100;
    spec.machine = "test-machine";
    spec.backend = "fake";
    spec.params = {{"ctx", std::int64_t{8192}}};
    const auto records = evidence::runHttpBench(spec);
    CHECK_EQ(records.size(), std::size_t{2});
    for (const auto& r : records)
    {
        CHECK(r.outcome == contracts::Outcome::Ok);
        CHECK_EQ(r.depth, std::int64_t{4000});
        CHECK_EQ(r.backend, std::string{"fake"});
        CHECK(r.ppTps.has_value() && r.tgTps.has_value() && r.tgPerSeq.has_value());
        if (r.ppTps && r.tgTps)
        {
            // The fake front answers one request at a time, so B sequences take B times as long: the totals stay at the fake's own speeds.
            CHECK(*r.tgTps > 0.6 * replyTokensPerSecond && *r.tgTps < 1.4 * replyTokensPerSecond);
            CHECK(*r.ppTps > 0.3 * promptTokensPerSecond && *r.ppTps < 1.4 * promptTokensPerSecond);
            CHECK(std::abs(*r.tgPerSeq * static_cast<double>(r.concurrency) - *r.tgTps) < 1e-6);
        }
    }

    // A server that refuses gives an error record naming the reason, not a crash.
    {
        evidence::HttpBenchSpec bad = spec;
        bad.model = "refuse";
        bad.concurrencies = {1};
        const auto refused = evidence::runHttpBench(bad);
        CHECK_EQ(refused.size(), std::size_t{1});
        CHECK(refused.at(0).outcome == contracts::Outcome::Error);
        CHECK(refused.at(0).error.has_value() && refused.at(0).error->find("slot") != std::string::npos);
    }
    front->stop();
    return finish();
}
