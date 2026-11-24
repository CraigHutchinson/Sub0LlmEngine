#include "sub0llmengine/control/engine_control.hpp"

#include "sub0llmengine/fit/fit.hpp"
#include "sub0platform/proc.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <thread>
#include <vector>

namespace sub0llmengine::control
{
namespace
{

using namespace std::chrono_literals;

std::string readFile(const std::filesystem::path& path)
{
    std::ifstream in{path, std::ios::binary};
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

/// The last `lines` lines of the log, for a person to read when a start failed.
std::string tail(const std::string& log, int lines)
{
    std::size_t at = log.size();
    for (int n = 0; n < lines && at != std::string::npos && at > 0; ++n)
    {
        at = log.rfind('\n', at - 1);
    }
    return at == std::string::npos ? log : log.substr(at + 1);
}

StartResult stopped(supervision::Instance& instance, StartKind kind, std::string message, std::int64_t shortfall = 0)
{
    const auto pid = instance.processId();
    (void)stopProcessTree(pid);
    return StartResult{kind, pid, shortfall, std::move(message)};
}

}  // namespace

StartResult startBasalt(const supervision::InstanceSpec& spec, net::IHttpClient& client, std::chrono::seconds timeout)
{
    auto started = supervision::Instance::start(spec);
    if (!started)
    {
        return StartResult{StartKind::Failed, 0, 0, started.error().message};
    }
    auto& instance = *started;
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline)
    {
        std::this_thread::sleep_for(500ms);
        const bool alive = instance.alive();
        const auto log = readFile(spec.logFile);
        if (const auto outcome = fit::parseBasaltOutcome(log, 0))
        {
            if (outcome->verdict == fit::Verdict::Short)
            {
                return stopped(instance, StartKind::Refused, outcome->note, outcome->shortfallMiB);
            }
            if (outcome->verdict == fit::Verdict::Failed)
            {
                return stopped(instance, StartKind::Failed, outcome->note);
            }
            // Loaded: now the server must answer, which it does within moments.
            const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
            const auto ready = instance.waitReady(client, std::max(left, std::chrono::milliseconds{5000}), 200ms);
            if (ready.outcome == supervision::Readiness::Ready)
            {
                return StartResult{StartKind::Ready, instance.processId(), 0, outcome->note};
            }
            return stopped(instance, StartKind::Failed, "the model loaded but the server does not answer: " + tail(readFile(spec.logFile), 5));
        }
        if (!alive)
        {
            return StartResult{StartKind::Failed, instance.processId(), 0, "the server exited before it loaded:\n" + tail(log, 8)};
        }
    }
    return stopped(instance, StartKind::TimedOut, "no decision from the server in time:\n" + tail(readFile(spec.logFile), 5));
}

bool processRunning(std::int64_t pid)
{
    const auto start = sub0platform::processStart(pid);
    return start && sub0platform::isAlive(pid, *start);
}

bool stopProcessTree(std::int64_t pid, std::chrono::seconds grace)
{
    std::vector<std::int64_t> all = sub0platform::descendants(pid);
    all.push_back(pid);
    for (const auto id : all)
    {
        if (!sub0platform::terminateProcess(id))
        {
            (void)sub0platform::killProcess(id);
        }
    }
    const auto deadline = std::chrono::steady_clock::now() + grace;
    const auto anyRunning = [&] {
        return std::any_of(all.begin(), all.end(), [](std::int64_t id) { return processRunning(id); });
    };
    while (anyRunning() && std::chrono::steady_clock::now() < deadline)
    {
        std::this_thread::sleep_for(200ms);
    }
    if (anyRunning())
    {
        for (const auto id : all)
        {
            (void)sub0platform::killProcess(id);
        }
        std::this_thread::sleep_for(1s);
    }
    return !anyRunning();
}

}  // namespace sub0llmengine::control
