#include "sub0llmengine/service/version.hpp"

#include <Version.hpp>

namespace sub0llmengine::service {

std::string_view fullVersion() noexcept
{
    return sub0llmengine::version::version_full;
}

}  // namespace sub0llmengine::service
