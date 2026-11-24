#pragma once
#include "sub0llmengine/net/http.hpp"

#include <chrono>
#include <cstdint>
#include <expected>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace sub0llmengine::supervision
{

struct SupervisionError
{
    std::string message;
};

/// What to run and where to look for it. The argv comes from a backend adapter (backends layer); the engine never builds a shell string.
struct InstanceSpec
{
    std::vector<std::string> argv;            // argv[0] is the program
    std::filesystem::path logFile;            // stdout and stderr, appended
    std::string host = "127.0.0.1";
    std::uint16_t port = 8092;
    std::string healthPath = "/health";       // 200: serving, 503: still loading (llama.cpp, Strata and Basalt all answer so)
};

enum class Health
{
    Down,       // nothing is listening yet (or any more)
    Loading,    // listening, model not ready (503)
    Ready,      // 200
    Unhealthy,  // any other answer
};

[[nodiscard]] const char* toString(Health health) noexcept;

enum class Readiness
{
    Ready,
    Exited,    // the process ended before it was ready; see WaitResult::exitCode and the log file
    TimedOut,  // still alive and not ready when the time ran out
};

struct WaitResult
{
    Readiness outcome = Readiness::TimedOut;
    Health lastHealth = Health::Down;
    std::optional<int> exitCode;
};

/// One backend server process the engine started: it owns the child, which leads its own process group (a Windows job object), so stopping
/// it ends the whole tree, including a launcher wrapper's children. Destroying an Instance neither waits nor kills (a server may outlive the
/// caller on purpose); stop() ends it.
class Instance
{
public:
    Instance(Instance&&) noexcept;
    Instance& operator=(Instance&&) noexcept;
    Instance(const Instance&) = delete;
    Instance& operator=(const Instance&) = delete;
    ~Instance();

    [[nodiscard]] static std::expected<Instance, SupervisionError> start(const InstanceSpec& spec);

    [[nodiscard]] std::int64_t processId() const noexcept;
    [[nodiscard]] const InstanceSpec& spec() const noexcept { return spec_; }

    /// Whether the process is still running.
    [[nodiscard]] bool alive();

    /// One health request. Never throws; a refused connection is Down.
    [[nodiscard]] Health probe(net::IHttpClient& client, std::chrono::milliseconds timeout = std::chrono::milliseconds{1000}) const;

    /// Polls until the server answers 200, the process exits, or `timeout` passes.
    [[nodiscard]] WaitResult waitReady(net::IHttpClient& client, std::chrono::milliseconds timeout,
                                       std::chrono::milliseconds poll = std::chrono::milliseconds{200});

    /// Asks the process (its whole group) to stop, waits up to `grace`, then ends it. Returns the exit code when it exited on its own terms.
    std::optional<int> stop(std::chrono::milliseconds grace = std::chrono::seconds{10});

private:
    struct State;
    Instance(InstanceSpec spec, std::unique_ptr<State> state);

    InstanceSpec spec_;
    std::unique_ptr<State> state_;
};

}  // namespace sub0llmengine::supervision
