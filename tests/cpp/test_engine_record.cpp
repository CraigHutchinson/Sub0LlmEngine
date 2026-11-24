// The engine record (sub0llmengine.engine.v1) round-trips, reads what the Python reference wrote, and the flat local config reads scalars only.
#include "check.hpp"
#include "sub0llmengine/contracts/engine_record.hpp"

#include <string>

int main()
{
    using namespace sub0llmengine::contracts;
    EngineRecord record;
    record.pid = 4242;
    record.url = "http://127.0.0.1:8092/v1";
    record.startedAt = "2026-11-24T16:30:00";
    record.backend = "basalt";
    record.build = "Basalt 0.5.7";
    record.modelId = "hf/jesdga/Inkling-2-Mini-Basalt@8f4f9b050b07#Inkling-2-Mini-NVFP4-DQ8.basalt";
    record.modelPath = "D:/LlmModels/hf/jesdga/pack.basalt";
    record.config = {{"maxContext", std::int64_t{94208}}, {"kv", std::string{"fp8"}}, {"slots", std::int64_t{1}}, {"drafter", false}, {"ratio", 0.5}};
    record.command = {"basalt", "serve", "--alias", "Inkling 2 Mini"};
    record.log = "out/basalt-8092.log";

    const auto text = toJson(record);
    const auto back = parseEngineRecord(text);
    CHECK(back.has_value());
    if (back)
    {
        CHECK_EQ(back->pid, std::int64_t{4242});
        CHECK_EQ(back->url, record.url);
        CHECK_EQ(back->modelId, record.modelId);
        CHECK_EQ(back->modelPath, record.modelPath);
        CHECK(back->config == record.config);
        CHECK(back->command == record.command);
        CHECK_EQ(toJson(*back), text);
    }

    // The Python reference's document: unknown members (identity, configLayers) are ignored.
    const auto python = parseEngineRecord(
        R"({"format":"sub0llmengine.engine.v1","pid":7,"url":"http://127.0.0.1:8092/v1","startedAt":"x","backend":"llamacpp","build":"b1",)"
        R"("model":{"id":"m","path":"p"},"config":{"ctx":8192,"flashAttn":"on","mmap":false,"nested":{"a":1}},"identity":{"machine":"m"},)"
        R"("configLayers":["a"],"command":["llama-server"],"log":"out/l.log"})");
    CHECK(python.has_value() && python->backend == "llamacpp" && python->config.size() == 3);
    CHECK(!parseEngineRecord("{}").has_value());
    CHECK(!parseEngineRecord("nope").has_value());

    const auto local = parseFlatParams(R"({"basaltBin":"D:/b/basalt.exe","threads":16,"mmap":false,"list":[1,2],"nothing":null})");
    CHECK(local.has_value() && local->size() == 3);
    CHECK(local.has_value() && std::get<std::string>(local->at("basaltBin")) == "D:/b/basalt.exe");
    CHECK(!parseFlatParams("[]").has_value());
    return finish();
}
