#include "sub0/engine/service/version.hpp"

#include <Version.hpp>

namespace sub0engine::service {

std::string_view fullVersion() noexcept
{
    return sub0engine::version::version_full;
}

}  // namespace sub0engine::service
