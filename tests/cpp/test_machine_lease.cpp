// The machine lease is held by one tool at a time; a second taker is refused with the holder's name, and the lease is free again when released.
#include "check.hpp"
#include "sub0llmengine/supervision/machine_lease.hpp"

#include <filesystem>
#include <string>

int main()
{
    using namespace sub0llmengine::supervision;
    const auto lockFile = std::filesystem::path{"test-tmp"} / "lease" / "machine.lock";
    std::filesystem::remove_all(lockFile.parent_path());

    {
        auto first = MachineLease::acquire("sub0engine_fit", "context search", lockFile);
        CHECK(first.has_value());
        const auto owner = MachineLease::readOwner(lockFile);
        CHECK(owner.has_value() && owner->tool == "sub0engine_fit" && owner->purpose == "context search" && owner->pid > 0);

        auto second = MachineLease::acquire("sub0perf", "timing", lockFile);
        CHECK(!second.has_value());
        CHECK(!second.has_value() && second.error().message.find("sub0engine_fit") != std::string::npos);
        CHECK(!second.has_value() && second.error().message.find("context search") != std::string::npos);

        auto moved = std::move(*first);  // moving keeps the hold
        CHECK(!MachineLease::acquire("sub0perf", "timing", lockFile).has_value());
    }
    // Released: the next taker gets it, and the old record is gone.
    CHECK(!MachineLease::readOwner(lockFile).has_value());
    auto again = MachineLease::acquire("sub0perf", "timing", lockFile);
    CHECK(again.has_value());
    CHECK(MachineLease::readOwner(lockFile)->tool == "sub0perf");

    // The default file is per user and under a sub0 folder.
    CHECK(MachineLease::defaultLockFile().filename() == "machine.lock");
    CHECK(MachineLease::defaultLockFile().parent_path().filename() == "sub0");
    return finish();
}
