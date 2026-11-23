// The platform layer reaches Sub0Platform: an environment lookup and a captured child process work through the engine's own targets.
#include "check.hpp"
#include "sub0platform/proc.hpp"

int main()
{
    sub0platform::setEnvironment("SUB0ENGINE_TEST_VALUE", "present");
    const auto value = sub0platform::getEnvironment("SUB0ENGINE_TEST_VALUE");
    CHECK(value.has_value());
    CHECK(!value.has_value() || *value == "present");
    CHECK(!sub0platform::getEnvironment("SUB0ENGINE_TEST_UNSET_VALUE").has_value());
    return finish();
}
