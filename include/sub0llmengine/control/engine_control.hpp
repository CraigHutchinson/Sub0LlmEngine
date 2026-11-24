#pragma once
#include "sub0llmengine/net/http.hpp"
#include "sub0llmengine/supervision/instance.hpp"

#include <chrono>
#include <cstdint>
#include <string>

namespace sub0llmengine::control
{

enum class StartKind
{
    Ready,    // the model loaded and the server answers; it keeps running
    Refused,  // the backend would not load it here (Basalt: the card is `shortfallMiB` too small); stopped
    Failed,   // the process exited, or printed an error; stopped; `message` is the line or the log's tail
    TimedOut, // no decision in time; stopped
};

struct StartResult
{
    StartKind kind = StartKind::Failed;
    std::int64_t pid = 0;
    std::int64_t shortfallMiB = 0;
    std::string message;
};

/// Starts a Basalt server and decides from its own output whether the model loaded: Basalt prints "ready" before it plans its weights, so
/// the health answer alone is not enough. On Ready the server is left running (it outlives the caller); on anything else it is stopped.
[[nodiscard]] StartResult startBasalt(const supervision::InstanceSpec& spec, net::IHttpClient& client, std::chrono::seconds timeout);

/// Ends a server this engine started: the process and everything below it (a launcher's children), then waits up to `grace`.
/// True when nothing of it is left running.
bool stopProcessTree(std::int64_t pid, std::chrono::seconds grace = std::chrono::seconds{15});

/// Whether `pid` is a running process.
[[nodiscard]] bool processRunning(std::int64_t pid);

}  // namespace sub0llmengine::control
