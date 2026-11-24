#pragma once
// Private to the contracts layer: typed reads from a simdjson on-demand value, each throwing a sentence that names the key. Callers catch
// std::exception at the contract boundary and turn it into a ContractError, so simdjson never reaches a public header.
#include <simdjson.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>

namespace sub0llmengine::contracts::json
{

namespace od = simdjson::ondemand;

[[nodiscard]] inline std::string text(od::value v, std::string_view key)
{
    std::string_view s;
    if (v.get(s) != simdjson::SUCCESS)
    {
        throw std::runtime_error("'" + std::string{key} + "' must be a string");
    }
    return std::string{s};
}

[[nodiscard]] inline std::int64_t integer(od::value v, std::string_view key)
{
    std::int64_t n = 0;
    if (v.get(n) != simdjson::SUCCESS)
    {
        throw std::runtime_error("'" + std::string{key} + "' must be an integer");
    }
    return n;
}

[[nodiscard]] inline double real(od::value v, std::string_view key)
{
    double d = 0;
    if (v.get(d) != simdjson::SUCCESS)
    {
        throw std::runtime_error("'" + std::string{key} + "' must be a number");
    }
    return d;
}

[[nodiscard]] inline bool flag(od::value v, std::string_view key)
{
    bool b = false;
    if (v.get(b) != simdjson::SUCCESS)
    {
        throw std::runtime_error("'" + std::string{key} + "' must be true or false");
    }
    return b;
}

[[nodiscard]] inline bool isNull(od::value v)
{
    bool null = false;
    return v.is_null().get(null) == simdjson::SUCCESS && null;
}

}  // namespace sub0llmengine::contracts::json
