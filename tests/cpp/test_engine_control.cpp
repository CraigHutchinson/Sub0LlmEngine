// Starting a Basalt server decides from its own output, not from the health answer alone: it loads, or it is refused with the shortfall, or it
// crashes, or it never decides; and a server that is Ready outlives the call and is ended with everything below it. A fake server stands in.
#include "check.hpp"
#include "sub0llmengine/control/engine_control.hpp"
#include "sub0llmengine/net/http.hpp"

#include <chrono>
#include <filesystem>
#include <string>
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

supervision::InstanceSpec fake(std::uint16_t port, const std::vector<std::string>& extra)
{
    supervision::InstanceSpec spec;
    spec.argv = {SUB0ENGINE_FAKE_SERVER, "--port", std::to_string(port)};
    spec.argv.insert(spec.argv.end(), extra.begin(), extra.end());
    spec.port = port;
    spec.logFile = std::filesystem::path{"test-tmp"} / ("control-" + std::to_string(port) + ".log");
    std::filesystem::remove(spec.logFile);
    return spec;
}

}  // namespace

int main()
{
    auto client = net::makeHttpClient();

    // Loads, answers, and keeps running after the call; stopping ends it.
    {
        const auto port = freePort();
        const auto result = control::startBasalt(fake(port, {"--loading-ms", "700"}), *client, 30s);
        CHECK(result.kind == control::StartKind::Ready);
        CHECK(result.pid > 0);
        CHECK(control::processRunning(result.pid));
        auto answer = client->send("127.0.0.1", port, net::HttpRequest{"GET", "/health", {}, {}}, 2s);
        CHECK(answer.has_value() && answer->status == 200);
        CHECK(control::stopProcessTree(result.pid, 10s));
        CHECK(!control::processRunning(result.pid));
        CHECK(!client->send("127.0.0.1", port, net::HttpRequest{"GET", "/health", {}, {}}, 500ms).has_value());
    }
    // Refused: the shortfall comes back, and nothing is left running.
    {
        const auto result = control::startBasalt(fake(freePort(), {"--refuse-short", "321"}), *client, 30s);
        CHECK(result.kind == control::StartKind::Refused);
        CHECK_EQ(result.shortfallMiB, std::int64_t{321});
        CHECK(!control::processRunning(result.pid));
    }
    // Exits by itself before it loads: Failed, with a sentence, not a timeout.
    {
        const auto result = control::startBasalt(fake(freePort(), {"--loading-ms", "600000", "--exit-after-ms", "300"}), *client, 30s);
        CHECK(result.kind == control::StartKind::Failed);
        CHECK(result.message.find("exited") != std::string::npos);
    }
    // Never decides: TimedOut, and it is stopped.
    {
        const auto result = control::startBasalt(fake(freePort(), {"--loading-ms", "600000"}), *client, 2s);
        CHECK(result.kind == control::StartKind::TimedOut);
        CHECK(result.pid > 0 && !control::processRunning(result.pid));
    }
    // A program that does not exist is Failed with its name.
    {
        supervision::InstanceSpec spec;
        spec.argv = {"definitely-not-a-program-sub0engine"};
        const auto result = control::startBasalt(spec, *client, 5s);
        CHECK(result.kind == control::StartKind::Failed && result.message.find("definitely-not-a-program-sub0engine") != std::string::npos);
    }
    return finish();
}
