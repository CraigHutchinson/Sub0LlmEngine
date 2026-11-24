#pragma once
#include "sub0llmengine/supervision/instance.hpp"  // SupervisionError

#include <expected>
#include <filesystem>
#include <memory>
#include <string>

namespace sub0llmengine::supervision
{

/// Who holds the machine, as written beside the lock.
struct LeaseOwner
{
    std::string tool;     // absent from a record written by sub0perf
    std::string purpose;  // the record's "what"
    std::int64_t pid = 0;
    double time = 0;      // seconds since the epoch
};

/// The quiet machine, held by one tool at a time (docs/reviews/2026-11-24-family-responsibilities.md D4). A timing run, a fit, a bench and
/// anything else that must not share the GPU and the cores takes it first; the operating system releases it when the process ends, even
/// after a crash. A tool that cannot take it exits and says who holds it: it never waits silently.
///
/// The lock file is shared across the family (`<state dir>/sub0/machine.lock`); the owner record sits beside it, one JSON object with the
/// keys sub0perf's lock file uses (`pid`, `time`, `what`) plus `tool`, and is only a courtesy for the message, never the source of truth.
class MachineLease
{
public:
    MachineLease(MachineLease&&) noexcept;
    MachineLease& operator=(MachineLease&&) noexcept;
    MachineLease(const MachineLease&) = delete;
    MachineLease& operator=(const MachineLease&) = delete;
    ~MachineLease();

    /// `lockFile` empty = the per-user default. The error names the holder when there is one.
    [[nodiscard]] static std::expected<MachineLease, SupervisionError> acquire(const std::string& tool, const std::string& purpose,
                                                                              const std::filesystem::path& lockFile = {});

    /// `%LOCALAPPDATA%\sub0\machine.lock`, else `$XDG_STATE_HOME/sub0/machine.lock`, else `~/.local/state/sub0/machine.lock`.
    [[nodiscard]] static std::filesystem::path defaultLockFile();

    /// The record beside `lockFile`, if any (a stale record from a crashed holder may remain: the lock decides, not this).
    [[nodiscard]] static std::optional<LeaseOwner> readOwner(const std::filesystem::path& lockFile);

private:
    struct State;
    explicit MachineLease(std::unique_ptr<State> state);
    std::unique_ptr<State> state_;
};

}  // namespace sub0llmengine::supervision
