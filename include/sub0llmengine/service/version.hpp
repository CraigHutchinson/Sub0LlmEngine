#pragma once
#include <string_view>

namespace sub0llmengine::service {

/// The build's version from git (Version.cmake): "<semver>-<commits>-g<hash>", with "-dirty" when the tree has changes.
[[nodiscard]] std::string_view fullVersion() noexcept;

}  // namespace sub0llmengine::service
