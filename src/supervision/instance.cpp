#include "sub0llmengine/supervision/instance.hpp"

#include "sub0platform/process.hpp"

#include <thread>

namespace sub0llmengine::supervision
{

struct Instance::State
{
    sub0platform::Child child;
    std::optional<sub0platform::ExitStatus> ended;
};

const char* toString(Health health) noexcept
{
    switch (health)
    {
    case Health::Down: return "down";
    case Health::Loading: return "loading";
    case Health::Ready: return "ready";
    case Health::Unhealthy: return "unhealthy";
    }
    return "down";
}

Instance::Instance(InstanceSpec spec, std::unique_ptr<State> state) : spec_{std::move(spec)}, state_{std::move(state)} {}
Instance::Instance(Instance&&) noexcept = default;
Instance& Instance::operator=(Instance&&) noexcept = default;
Instance::~Instance() = default;

std::expected<Instance, SupervisionError> Instance::start(const InstanceSpec& spec)
{
    if (spec.argv.empty())
    {
        return std::unexpected(SupervisionError{"no command to run"});
    }
    sub0platform::ProcessSpec process;
    process.argv = spec.argv;
    process.outputFile = spec.logFile;
    process.appendOutput = true;
    process.newSession = true;  // its own process group (Windows: a job object): stop() ends the whole tree
    if (!spec.logFile.empty() && spec.logFile.has_parent_path())
    {
        std::error_code ec;
        std::filesystem::create_directories(spec.logFile.parent_path(), ec);
    }
    auto child = sub0platform::spawn(process);
    if (!child)
    {
        return std::unexpected(SupervisionError{"cannot start " + spec.argv.front() + ": " + child.error().what()});
    }
    auto state = std::make_unique<State>();
    state->child = std::move(*child);
    return Instance{spec, std::move(state)};
}

std::int64_t Instance::processId() const noexcept
{
    return state_->child.id();
}

bool Instance::alive()
{
    if (!state_->ended)
    {
        state_->ended = state_->child.wait(std::chrono::milliseconds{0});
    }
    return !state_->ended.has_value();
}

Health Instance::probe(net::IHttpClient& client, std::chrono::milliseconds timeout) const
{
    auto answer = client.send(spec_.host, spec_.port, net::HttpRequest{"GET", spec_.healthPath, {}, {}}, timeout);
    if (!answer)
    {
        return Health::Down;
    }
    if (answer->status == 200)
    {
        return Health::Ready;
    }
    return answer->status == 503 ? Health::Loading : Health::Unhealthy;
}

WaitResult Instance::waitReady(net::IHttpClient& client, std::chrono::milliseconds timeout, std::chrono::milliseconds poll)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    WaitResult result;
    for (;;)
    {
        if (!alive())
        {
            result.outcome = Readiness::Exited;
            result.exitCode = state_->ended->shellCode();
            return result;
        }
        result.lastHealth = probe(client, std::min(poll * 5, std::chrono::milliseconds{2000}));
        if (result.lastHealth == Health::Ready)
        {
            result.outcome = Readiness::Ready;
            return result;
        }
        if (std::chrono::steady_clock::now() + poll >= deadline)
        {
            result.outcome = Readiness::TimedOut;
            return result;
        }
        std::this_thread::sleep_for(poll);
    }
}

std::optional<int> Instance::stop(std::chrono::milliseconds grace)
{
    if (!alive())
    {
        return state_->ended->shellCode();
    }
    (void)state_->child.terminate();
    state_->ended = state_->child.wait(grace);
    if (!state_->ended)
    {
        (void)state_->child.kill();
        state_->ended = state_->child.wait(std::chrono::seconds{5});
    }
    if (!state_->ended)
    {
        return std::nullopt;
    }
    return state_->ended->shellCode();
}

}  // namespace sub0llmengine::supervision
