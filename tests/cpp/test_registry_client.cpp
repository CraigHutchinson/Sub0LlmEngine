// The registry client answers like the reference tool over a tiny registry built with it (tests/fixtures/registry, written by
// tools/write_fixtures.py): alias and id resolution (main file, split shards, projectors, ambiguity, eviction), the derived state of each
// artifact of a model, and `request` by format with its refusals. It never touches the model files: only registry.json and models/.
#include "check.hpp"
#include "sub0llmengine/registry/registry.hpp"

#include <simdjson.h>

#include <fstream>
#include <iterator>
#include <string>
#include <vector>

namespace
{

using sub0llmengine::registry::ErrorKind;
using sub0llmengine::registry::Registry;

std::string slurp(const std::string& path)
{
    std::ifstream in{path, std::ios::binary};
    return std::string{std::istreambuf_iterator<char>{in}, std::istreambuf_iterator<char>{}};
}

const char* kindName(ErrorKind kind)
{
    switch (kind)
    {
    case ErrorKind::Evicted: return "evicted";
    case ErrorKind::Unknown: return "unknown";
    case ErrorKind::Ambiguous: return "ambiguous";
    case ErrorKind::Unavailable: return "unavailable";
    case ErrorKind::Unreadable: return "unreadable";
    }
    return "?";
}

/// Checks one answer against the reference's: the same path (relative to the registry) and id, or the same kind of refusal.
template <typename Answer>
void compare(const Answer& got, const std::filesystem::path& root, simdjson::ondemand::value want, const std::string& what)
{
    if (want["ok"].get_bool())
    {
        CHECK(got.has_value());
        if (!got)
        {
            std::fprintf(stderr, "%s: refused: %s\n", what.c_str(), got.error().message.c_str());
            return;
        }
        const std::string wantPath{want["path"].get_string().value()};
        const std::string wantId{want["id"].get_string().value()};
        const auto gotPath = got->path.lexically_relative(root).generic_string();
        if (gotPath != wantPath || got->id != wantId)
        {
            std::fprintf(stderr, "%s: got %s (%s), want %s (%s)\n", what.c_str(), gotPath.c_str(), got->id.c_str(), wantPath.c_str(), wantId.c_str());
        }
        CHECK_EQ(gotPath, wantPath);
        CHECK_EQ(got->id, wantId);
    }
    else
    {
        CHECK(!got.has_value());
        if (got)
        {
            std::fprintf(stderr, "%s: expected a refusal\n", what.c_str());
            return;
        }
        const std::string wantKind{want["kind"].get_string().value()};
        if (wantKind != kindName(got.error().kind))
        {
            std::fprintf(stderr, "%s: refused as %s, want %s\n", what.c_str(), kindName(got.error().kind), wantKind.c_str());
        }
        CHECK_EQ(std::string{kindName(got.error().kind)}, wantKind);
    }
}

}  // namespace

int main()
{
    using namespace sub0llmengine::registry;
    const std::filesystem::path root = std::filesystem::path{SUB0ENGINE_REPO_DIR} / "tests" / "fixtures" / "registry";
    auto registry = Registry::open(root);
    CHECK(registry.has_value());
    if (!registry)
    {
        std::fprintf(stderr, "%s\n", registry.error().message.c_str());
        return finish();
    }

    simdjson::padded_string text{slurp((root / "expected.json").string())};
    simdjson::ondemand::parser parser;
    auto doc = parser.iterate(text);

    int resolves = 0;
    for (auto item : doc["resolve"])
    {
        ++resolves;
        const std::string ref{item["ref"].get_string().value()};
        compare(registry->resolve(ref), root, item.value(), "resolve " + ref);
    }
    CHECK(resolves >= 10);

    int artifactRows = 0;
    for (auto model : doc["artifacts"].get_object())
    {
        const std::string name{model.unescaped_key().value()};
        auto got = registry->artifacts(name);
        CHECK(got.has_value());
        if (!got)
        {
            continue;
        }
        std::size_t i = 0;
        for (auto row : model.value())
        {
            ++artifactRows;
            CHECK(i < got->size());
            if (i >= got->size())
            {
                break;
            }
            const auto& a = (*got)[i++];
            const std::string wantState{row["state"].get_string().value()};
            const std::string wantId{row["id"].get_string().value()};
            if (std::string{toString(a.state)} != wantState || a.id != wantId)
            {
                std::fprintf(stderr, "%s %s %s: got %s [%s], want %s [%s]\n", name.c_str(), a.definition.format.c_str(), a.definition.variant.c_str(),
                             std::string{toString(a.state)}.c_str(), a.id.c_str(), wantState.c_str(), wantId.c_str());
            }
            CHECK_EQ(std::string{toString(a.state)}, wantState);
            CHECK_EQ(a.id, wantId);
            CHECK_EQ(a.definition.format, std::string{row["format"].get_string().value()});
        }
        CHECK_EQ(i, got->size());
    }
    CHECK(artifactRows >= 9);

    int requests = 0;
    for (auto item : doc["requests"])
    {
        ++requests;
        const std::string model{item["model"].get_string().value()};
        const std::string variant{item["variant"].get_string().value()};
        const std::string vendor{item["vendor"].get_string().value()};
        std::vector<std::string> formats;
        for (auto f : item["formats"])
        {
            formats.emplace_back(f.get_string().value());
        }
        compare(registry->request(model, formats, variant, vendor), root, item.value(), "request " + model + " " + formats.front() + " " + variant);
    }
    CHECK(requests >= 13);

    // A refusal names the registry command that would make the model available, and nothing was fetched.
    const std::vector<std::string> gguf{"gguf"};
    auto q4 = registry->request("toy", gguf, "Q4");
    CHECK(!q4.has_value() && q4.error().message.find("python -m sub0llmregistry request toy --format gguf --fetch") != std::string::npos);

    CHECK(globMatches("*.gguf", "a.gguf"));
    CHECK(!globMatches("*.gguf", "a.gguf.part"));
    CHECK(globMatches("split-0000[12]-of-00002.gguf", "split-00002-of-00002.gguf"));
    CHECK(!globMatches("split-0000[12]-of-00002.gguf", "split-00003-of-00002.gguf"));
    CHECK(globMatches("*[5n].strata", "Inkling-2-Mini-SQ-15.strata"));
    CHECK(!globMatches("*[5n].strata", "Inkling-2-Mini-SQ-10.strata"));
    CHECK(globMatches("a?c", "abc") && !globMatches("a?c", "ac"));
    CHECK(globMatches("[!x]*", "abc") && !globMatches("[!x]*", "xbc"));
    CHECK(globMatches("[a-c]z", "bz") && !globMatches("[a-c]z", "dz"));

    auto missing = Registry::open(root / "nowhere");
    CHECK(!missing.has_value() && missing.error().kind == ErrorKind::Unreadable);
    return finish();
}
