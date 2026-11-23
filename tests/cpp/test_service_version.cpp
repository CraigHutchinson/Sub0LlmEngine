#include "check.hpp"
#include "sub0/engine/service/version.hpp"

int main()
{
    const auto v = sub0engine::service::fullVersion();
    CHECK(!v.empty());
    return finish();
}
