#include "check.hpp"
#include "sub0llmengine/service/version.hpp"

int main()
{
    const auto v = sub0llmengine::service::fullVersion();
    CHECK(!v.empty());
    return finish();
}
