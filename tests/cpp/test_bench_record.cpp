// The contracts layer reads the real bench history (bench/<machine>.jsonl, 1,000+ records written by the Python reference) to the same
// numbers the reference reports (tests/fixtures/bench/summary.json, written by tools/write_fixtures.py), and writes records that read back
// unchanged. Malformed input is refused with the line it is on.
#include "check.hpp"
#include "sub0llmengine/contracts/bench_record.hpp"

#include <simdjson.h>

#include <cmath>
#include <fstream>
#include <iterator>
#include <string>

namespace
{

std::string slurp(const std::string& path)
{
    std::ifstream in{path, std::ios::binary};
    return std::string{std::istreambuf_iterator<char>{in}, std::istreambuf_iterator<char>{}};
}

bool near(double a, double b)
{
    return std::fabs(a - b) <= 1e-6 * std::max(1.0, std::fabs(b));
}

}  // namespace

int main()
{
    using namespace sub0llmengine::contracts;
    const std::string repo = SUB0ENGINE_REPO_DIR;

    simdjson::padded_string summaryText{slurp(repo + "/tests/fixtures/bench/summary.json")};
    simdjson::ondemand::parser summaryParser;
    auto doc = summaryParser.iterate(summaryText);
    std::int64_t rows = doc["rows"].get_int64();
    std::int64_t withExcluded = doc["withExcluded"].get_int64();
    std::int64_t nullPeak = doc["nullPeakVram"].get_int64();
    std::int64_t nullWall = doc["nullWallSec"].get_int64();
    std::int64_t maxDepth = doc["maxDepth"].get_int64();
    std::int64_t maxConcurrency = doc["maxConcurrency"].get_int64();
    double sumTg = doc["sumTgTps"].get_double();
    double sumPp = doc["sumPpTps"].get_double();
    std::int64_t ok = doc["outcomes"]["ok"].get_int64();
    std::int64_t oom = doc["outcomes"]["oom"].get_int64();
    std::int64_t err = doc["outcomes"]["error"].get_int64();
    std::string source = std::string{doc["source"].get_string().value()};

    const auto text = slurp(repo + "/" + source);
    CHECK(!text.empty());
    auto records = parseBenchLines(text);
    CHECK(records.has_value());
    if (!records)
    {
        std::fprintf(stderr, "%s\n", records.error().message.c_str());
        return finish();
    }

    CHECK_EQ(static_cast<std::int64_t>(records->size()), rows);
    std::int64_t nOk = 0, nOom = 0, nErr = 0, nExcluded = 0, nNullPeak = 0, nNullWall = 0, depth = 0, conc = 0;
    double tg = 0, pp = 0;
    for (const auto& r : *records)
    {
        nOk += r.outcome == Outcome::Ok;
        nOom += r.outcome == Outcome::Oom;
        nErr += r.outcome == Outcome::Error;
        nExcluded += r.excluded.has_value();
        nNullPeak += !r.peakVramMiB.has_value();
        nNullWall += !r.wallSec.has_value();
        depth = std::max(depth, r.depth);
        conc = std::max(conc, r.concurrency);
        tg += r.tgTps.value_or(0);
        pp += r.ppTps.value_or(0);
    }
    CHECK_EQ(nOk, ok);
    CHECK_EQ(nOom, oom);
    CHECK_EQ(nErr, err);
    CHECK_EQ(nExcluded, withExcluded);
    CHECK_EQ(nNullPeak, nullPeak);
    CHECK_EQ(nNullWall, nullWall);
    CHECK_EQ(depth, maxDepth);
    CHECK_EQ(conc, maxConcurrency);
    CHECK(near(tg, sumTg));
    CHECK(near(pp, sumPp));

    // Written records read back unchanged, and the writer is stable (what it writes it rewrites byte for byte).
    std::size_t differing = 0;
    for (const auto& r : *records)
    {
        const auto json = toJson(r);
        auto back = parseBenchRecord(json);
        if (!back || toJson(*back) != json || back->params != r.params || back->outcome != r.outcome || back->depth != r.depth ||
            back->concurrency != r.concurrency || back->tgTps != r.tgTps || back->excluded != r.excluded)
        {
            ++differing;
        }
    }
    CHECK_EQ(differing, std::size_t{0});

    // Refusals name the line.
    auto badLine = parseBenchLines("{\"outcome\":\"ok\"}\n{not json}\n");
    CHECK(!badLine.has_value());
    CHECK(!badLine.has_value() && badLine.error().message.starts_with("line 2:"));
    CHECK(!parseBenchRecord(R"({"outcome":"maybe"})").has_value());
    CHECK(!parseBenchRecord(R"({"ts":"x"})").has_value());  // no outcome
    auto minimal = parseBenchRecord(R"({"outcome":"oom","B":4,"future":{"field":1}})");  // unknown fields are ignored
    CHECK(minimal.has_value() && minimal->concurrency == 4 && minimal->backend == "llamacpp");
    return finish();
}
