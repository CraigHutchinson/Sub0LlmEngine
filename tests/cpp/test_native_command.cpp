// Strata and Basalt command lines, the Windows batch-launcher wrapping and the Windows argument quoting match the Python reference
// (tests/fixtures/backends/native_command.json, written by tools/write_fixtures.py).
#include "check.hpp"
#include "sub0llmengine/backends/native_backends.hpp"
#include "sub0llmengine/contracts/native_backend_config.hpp"

#include <simdjson.h>

#include <fstream>
#include <iterator>
#include <string>
#include <vector>

int main()
{
    using namespace sub0llmengine;
    std::ifstream in{std::string{SUB0ENGINE_REPO_DIR} + "/tests/fixtures/backends/native_command.json", std::ios::binary};
    simdjson::padded_string text{std::string{std::istreambuf_iterator<char>{in}, std::istreambuf_iterator<char>{}}};
    simdjson::ondemand::parser parser;
    auto doc = parser.iterate(text);

    int cases = 0;
    for (auto item : doc["cases"])
    {
        ++cases;
        const std::string name{item["name"].get_string().value()};
        const std::string kind{item["kind"].get_string().value()};
        const std::string configJson{simdjson::to_json_string(item["config"]).value()};
        const bool windows = item["windows"].get_bool();
        const std::string comspec{item["comspec"].get_string().value()};
        std::vector<std::string> want;
        for (auto a : item["argv"])
        {
            want.emplace_back(a.get_string().value());
        }

        std::vector<std::string> argv;
        if (kind == "strata")
        {
            auto config = contracts::parseStrataConfig(configJson);
            CHECK(config.has_value());
            if (!config) continue;
            argv = backends::strataServerCommand(*config);
        }
        else
        {
            auto config = contracts::parseBasaltConfig(configJson);
            CHECK(config.has_value());
            if (!config) continue;
            argv = backends::basaltServerCommand(*config);
        }
        argv = backends::wrapBatchLauncher(argv, windows, comspec);
        if (argv != want)
        {
            std::fprintf(stderr, "case %s differs\n", name.c_str());
        }
        CHECK(argv == want);
    }
    CHECK(cases >= 7);

    int quoted = 0;
    for (auto item : doc["quoting"])
    {
        ++quoted;
        const std::string input{item["in"].get_string().value()};
        const std::string want{item["out"].get_string().value()};
        const auto got = backends::quoteWindowsArgument(input);
        if (got != want)
        {
            std::fprintf(stderr, "quote [%s]: got [%s] want [%s]\n", input.c_str(), got.c_str(), want.c_str());
        }
        CHECK_EQ(got, want);
    }
    CHECK(quoted >= 9);

    CHECK(!contracts::parseStrataConfig(R"({"port":"high"})").has_value());
    CHECK(!contracts::parseBasaltConfig("[]").has_value());
    // Serving a pack directly (no config file): only what is set is passed, the lever flags last.
    {
        backends::BasaltServe serve;
        serve.bin = "basalt";
        serve.pack = "m.basalt";
        const std::vector<std::string> bare = {"basalt", "serve", "--model", "m.basalt", "--host", "127.0.0.1", "--port", "8092"};
        CHECK(backends::basaltPackCommand(serve) == bare);
        serve.alias = "Inkling 2 Mini";
        serve.maxContext = 94208;
        serve.kv = "fp8";
        serve.parallel = 2;
        serve.extra = {"--spec", "1"};
        const std::vector<std::string> full = {"basalt", "serve", "--model", "m.basalt", "--host", "127.0.0.1", "--port", "8092", "--alias", "Inkling 2 Mini",
                                               "--max-context", "94208", "--kv", "fp8", "--parallel", "2", "--spec", "1"};
        CHECK(backends::basaltPackCommand(serve) == full);
    }
    return finish();
}
