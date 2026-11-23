// The backends layer builds llama-server command lines identical to the Python reference's for a set of configs and build capabilities
// (tests/fixtures/backends/llamacpp_command.json, written by tools/write_fixtures.py), including the refusal when a build lacks a flag.
#include "check.hpp"
#include "sub0llmengine/backends/llamacpp.hpp"
#include "sub0llmengine/contracts/llama_config.hpp"

#include <simdjson.h>

#include <fstream>
#include <iterator>
#include <string>

int main()
{
    using namespace sub0llmengine;
    std::ifstream in{std::string{SUB0ENGINE_REPO_DIR} + "/tests/fixtures/backends/llamacpp_command.json", std::ios::binary};
    simdjson::padded_string text{std::string{std::istreambuf_iterator<char>{in}, std::istreambuf_iterator<char>{}}};
    simdjson::ondemand::parser parser;
    auto doc = parser.iterate(text);
    int cases = 0;
    for (auto item : doc["cases"])
    {
        ++cases;
        const std::string name{item["name"].get_string().value()};
        const std::string configJson{simdjson::to_json_string(item["config"]).value()};
        backends::LlamaCapabilities caps;
        caps.loadMode = item["capabilities"]["loadMode"].get_bool();
        caps.kvUnifiedPerSlot = item["capabilities"]["kvUnifiedPerSlot"].get_bool();
        const std::string executable{item["executable"].get_string().value()};
        const std::string model{item["model"].get_string().value()};
        const bool expectError = item["error"].get_bool();

        auto config = contracts::parseLlamaServerConfig(configJson);
        CHECK(config.has_value());
        if (!config)
        {
            std::fprintf(stderr, "case %s: %s\n", name.c_str(), config.error().message.c_str());
            continue;
        }
        auto argv = backends::llamaServerCommand(*config, executable, model, caps);
        if (expectError)
        {
            if (argv.has_value())
            {
                std::fprintf(stderr, "case %s: expected a refusal\n", name.c_str());
            }
            CHECK(!argv.has_value());
            continue;
        }
        CHECK(argv.has_value());
        if (!argv)
        {
            std::fprintf(stderr, "case %s: %s\n", name.c_str(), argv.error().message.c_str());
            continue;
        }
        std::vector<std::string> want;
        for (auto a : item["argv"])
        {
            want.emplace_back(a.get_string().value());
        }
        if (*argv != want)
        {
            std::fprintf(stderr, "case %s differs\n", name.c_str());
        }
        CHECK(*argv == want);
    }
    CHECK(cases >= 10);

    auto notAnObject = contracts::parseLlamaServerConfig("[1,2]");
    CHECK(!notAnObject.has_value());
    auto wrongType = contracts::parseLlamaServerConfig(R"({"ctx":"big"})");
    CHECK(!wrongType.has_value() && wrongType.error().message.find("ctx") != std::string::npos);
    return finish();
}
