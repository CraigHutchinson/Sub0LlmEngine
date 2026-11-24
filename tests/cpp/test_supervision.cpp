// The supervision layer starts a server process, waits for it to load and answer, notices a crash during start-up, times out on a server
// that never loads, and stops it (the port is free again). A fake server stands in for the backends; nothing here needs a GPU.
#include "check.hpp"
#include "sub0llmengine/net/http.hpp"
#include "sub0llmengine/supervision/instance.hpp"

#include <chrono>
#include <filesystem>
#include <string>
#include <thread>
#include <vector>

namespace
{

using namespace sub0llmengine;
using namespace std::chrono_literals;

std::uint16_t freePort()
{
    auto front = net::makeHttpFront();
    auto port = front->start("127.0.0.1", 0, [](const net::HttpRequest&) { return net::HttpResponse{}; });
    front->stop();
    return port.value_or(0);
}

supervision::InstanceSpec fake(std::uint16_t port, const std::vector<std::string>& extra = {})
{
    supervision::InstanceSpec spec;
    spec.argv = {SUB0ENGINE_FAKE_SERVER, "--port", std::to_string(port)};
    spec.argv.insert(spec.argv.end(), extra.begin(), extra.end());
    spec.port = port;
    spec.logFile = std::filesystem::path{"test-tmp"} / ("supervision-" + std::to_string(port) + ".log");
    return spec;
}

}  // namespace

int main()
{
    auto client = net::makeHttpClient();

    // Loads for a moment (503), then answers 200; stop() ends it and the port refuses connections.
    {
        const auto port = freePort();
        CHECK(port != 0);
        auto instance = supervision::Instance::start(fake(port, {"--loading-ms", "700"}));
        CHECK(instance.has_value());
        if (!instance)
        {
            std::fprintf(stderr, "%s\n", instance.error().message.c_str());
            return finish();
        }
        CHECK(instance->alive());
        CHECK(instance->processId() > 0);
        const auto result = instance->waitReady(*client, 20s, 100ms);
        CHECK(result.outcome == supervision::Readiness::Ready);
        CHECK(instance->probe(*client) == supervision::Health::Ready);
        const auto code = instance->stop(5s);
        CHECK(code.has_value());
        CHECK(!instance->alive());
        CHECK(instance->probe(*client, 500ms) == supervision::Health::Down);
        CHECK(instance->stop(1s).has_value());  // stopping twice is harmless
    }

    // Exits by itself during start-up (a crash): reported as Exited with its code, not as a timeout.
    {
        const auto port = freePort();
        auto instance = supervision::Instance::start(fake(port, {"--loading-ms", "600000", "--exit-after-ms", "300"}));
        CHECK(instance.has_value());
        if (instance)
        {
            const auto result = instance->waitReady(*client, 20s, 100ms);
            CHECK(result.outcome == supervision::Readiness::Exited);
            CHECK(result.exitCode == 3);
        }
    }

    // Never finishes loading: TimedOut while the process is still alive, then stopped cleanly.
    {
        const auto port = freePort();
        auto instance = supervision::Instance::start(fake(port, {"--loading-ms", "600000"}));
        CHECK(instance.has_value());
        if (instance)
        {
            const auto result = instance->waitReady(*client, 1500ms, 100ms);
            CHECK(result.outcome == supervision::Readiness::TimedOut);
            CHECK(result.lastHealth == supervision::Health::Loading);
            CHECK(instance->alive());
            CHECK(instance->stop(5s).has_value());
        }
    }

    // A program that does not exist is refused with a sentence, not a crash.
    {
        supervision::InstanceSpec spec;
        spec.argv = {"definitely-not-a-program-sub0engine"};
        auto instance = supervision::Instance::start(spec);
        CHECK(!instance.has_value());
        CHECK(!instance.has_value() && instance.error().message.find("definitely-not-a-program-sub0engine") != std::string::npos);
        CHECK(!supervision::Instance::start(supervision::InstanceSpec{}).has_value());
    }
    return finish();
}
