#include "sub0llmengine/supervision/machine_lease.hpp"

#include "sub0platform/file.hpp"
#include "sub0platform/proc.hpp"

#include <chrono>
#include <ctime>
#include <format>
#include <fstream>
#include <sstream>

namespace sub0llmengine::supervision
{
namespace
{

std::filesystem::path ownerFileOf(const std::filesystem::path& lockFile)
{
    auto path = lockFile;
    path += ".owner";
    return path;
}

std::string localTime()
{
    const auto now = std::time(nullptr);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &now);
#else
    localtime_r(&now, &tm);
#endif
    return std::format("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
}

std::string describe(const std::optional<LeaseOwner>& owner)
{
    if (!owner)
    {
        return "another process holds the machine (no owner record)";
    }
    return std::format("{} holds the machine since {} for {} (pid {})", owner->tool, owner->since, owner->purpose, owner->pid);
}

}  // namespace

struct MachineLease::State
{
    sub0platform::FileLock lock;
    std::filesystem::path ownerFile;
};

MachineLease::MachineLease(std::unique_ptr<State> state) : state_{std::move(state)} {}
MachineLease::MachineLease(MachineLease&&) noexcept = default;
MachineLease& MachineLease::operator=(MachineLease&&) noexcept = default;

MachineLease::~MachineLease()
{
    if (state_ && state_->lock.isHeld())
    {
        std::error_code ec;
        std::filesystem::remove(state_->ownerFile, ec);  // before the lock goes: nobody reads a record that is not theirs
    }
}

std::filesystem::path MachineLease::defaultLockFile()
{
    if (const auto local = sub0platform::getEnvironment("LOCALAPPDATA"); local && !local->empty())
    {
        return std::filesystem::path{*local} / "sub0" / "machine.lock";
    }
    if (const auto xdg = sub0platform::getEnvironment("XDG_STATE_HOME"); xdg && !xdg->empty())
    {
        return std::filesystem::path{*xdg} / "sub0" / "machine.lock";
    }
    const auto home = sub0platform::getEnvironment("HOME").value_or(".");
    return std::filesystem::path{home} / ".local" / "state" / "sub0" / "machine.lock";
}

std::optional<LeaseOwner> MachineLease::readOwner(const std::filesystem::path& lockFile)
{
    std::ifstream in{ownerFileOf(lockFile)};
    std::string line;
    if (!in || !std::getline(in, line))
    {
        return std::nullopt;
    }
    LeaseOwner owner;
    std::istringstream fields{line};
    std::string pid;
    if (!std::getline(fields, owner.tool, '\t') || !std::getline(fields, owner.purpose, '\t') || !std::getline(fields, pid, '\t') ||
        !std::getline(fields, owner.since, '\t'))
    {
        return std::nullopt;
    }
    owner.pid = std::atoll(pid.c_str());
    return owner;
}

std::expected<MachineLease, SupervisionError> MachineLease::acquire(const std::string& tool, const std::string& purpose,
                                                                    const std::filesystem::path& lockFileIn)
{
    const auto lockFile = lockFileIn.empty() ? defaultLockFile() : lockFileIn;
    std::error_code ec;
    std::filesystem::create_directories(lockFile.parent_path(), ec);
    auto taken = sub0platform::FileLock::tryExclusive(lockFile);
    if (!taken)
    {
        return std::unexpected(SupervisionError{"cannot open the machine lock " + lockFile.string() + ": " + taken.error().what()});
    }
    if (!*taken)
    {
        return std::unexpected(SupervisionError{describe(readOwner(lockFile))});
    }
    auto state = std::make_unique<State>();
    state->lock = std::move(**taken);
    state->ownerFile = ownerFileOf(lockFile);
    std::ofstream out{state->ownerFile, std::ios::trunc};
    // Tab-separated, one line: a record a person can read with any tool, and the tool name and purpose carry no tabs.
    out << tool << '\t' << purpose << '\t' << sub0platform::currentProcess() << '\t' << localTime() << '\n';
    return MachineLease{std::move(state)};
}

}  // namespace sub0llmengine::supervision
