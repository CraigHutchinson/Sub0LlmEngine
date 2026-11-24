// sub0engine_bench: measures a running OpenAI-compatible server (llama.cpp, Strata or Basalt) and appends bench records the tuning page reads.
//   sub0engine_bench --port 8092 --model "Inkling 2 Mini" --backend basalt --machine ID --out bench/ID.jsonl
//                    [--build LABEL] [--model-id REGISTRY_ID] [--depth 2048,16384] [--b 1,2] [--ntg 128] [--param key=value]...
// Output follows the sub0perf habit: one verdict line, the records in the --out file (open it only when a line needs it).
#include "sub0llmengine/contracts/bench_record.hpp"
#include "sub0llmengine/evidence/http_bench.hpp"
#include "sub0llmengine/supervision/machine_lease.hpp"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace
{

std::vector<std::int64_t> numbers(const std::string& text)
{
    std::vector<std::int64_t> out;
    std::stringstream in{text};
    for (std::string part; std::getline(in, part, ',');)
    {
        out.push_back(std::atoll(part.c_str()));
    }
    return out;
}

sub0llmengine::contracts::ParamValue paramValue(const std::string& text)
{
    char* end = nullptr;
    const auto n = std::strtoll(text.c_str(), &end, 10);
    if (!text.empty() && *end == '\0') return static_cast<std::int64_t>(n);
    if (text == "true" || text == "false") return text == "true";
    return text;
}

}  // namespace

int main(int argc, char** argv)
{
    using namespace sub0llmengine;
    evidence::HttpBenchSpec spec;
    std::string out;
    for (int i = 1; i + 1 < argc; i += 2)
    {
        const std::string flag = argv[i];
        const std::string value = argv[i + 1];
        if (flag == "--port") spec.port = static_cast<std::uint16_t>(std::atoi(value.c_str()));
        else if (flag == "--host") spec.host = value;
        else if (flag == "--model") spec.model = value;
        else if (flag == "--model-id") spec.modelId = value;
        else if (flag == "--backend") spec.backend = value;
        else if (flag == "--machine") spec.machine = value;
        else if (flag == "--build") spec.build = value;
        else if (flag == "--depth") spec.depths = numbers(value);
        else if (flag == "--b") spec.concurrencies = numbers(value);
        else if (flag == "--ntg") spec.ntg = std::atoll(value.c_str());
        else if (flag == "--out") out = value;
        else if (flag == "--param")
        {
            const auto eq = value.find('=');
            if (eq == std::string::npos) { std::fprintf(stderr, "--param wants key=value\n"); return 2; }
            spec.params[value.substr(0, eq)] = paramValue(value.substr(eq + 1));
        }
        else { std::fprintf(stderr, "unknown option %s\n", flag.c_str()); return 2; }
    }
    if (spec.model.empty() || spec.backend.empty() || spec.machine.empty() || out.empty())
    {
        std::fprintf(stderr, "usage: sub0engine_bench --port N --model NAME --backend NAME --machine ID --out FILE.jsonl [--depth a,b] [--b a,b] [--ntg N] [--param k=v]...\n");
        return 2;
    }
    // The quiet machine, or a sentence naming who holds it (docs/reviews/2026-11-24-family-responsibilities.md D4).
    auto lease = sub0llmengine::supervision::MachineLease::acquire("sub0engine_bench", "http bench");
    if (!lease)
    {
        std::fprintf(stderr, "%s\n", lease.error().message.c_str());
        return 3;
    }
    const auto records = evidence::runHttpBench(spec);
    std::ofstream file{out, std::ios::app};
    int ok = 0;
    for (const auto& r : records)
    {
        file << contracts::toJson(r) << '\n';
        ok += r.outcome == contracts::Outcome::Ok;
        if (r.outcome == contracts::Outcome::Ok)
            std::printf("  depth %lld B %lld: prefill %.0f tok/s, decode %.1f tok/s (%.1f per sequence)\n", static_cast<long long>(r.depth),
                        static_cast<long long>(r.concurrency), *r.ppTps, *r.tgTps, *r.tgPerSeq);
        else
            std::printf("  depth %lld B %lld: %s %s\n", static_cast<long long>(r.depth), static_cast<long long>(r.concurrency),
                        std::string{contracts::toString(r.outcome)}.c_str(), r.error.value_or("").c_str());
    }
    std::printf("bench: %s %d of %zu points ok; records appended to %s\n", ok == static_cast<int>(records.size()) ? "PASS" : "FAIL", ok, records.size(), out.c_str());
    return ok == static_cast<int>(records.size()) ? 0 : 1;
}
