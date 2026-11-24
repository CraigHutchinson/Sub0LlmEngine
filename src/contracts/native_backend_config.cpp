#include "sub0llmengine/contracts/native_backend_config.hpp"

#include "json_fields.hpp"

#include <simdjson.h>

namespace sub0llmengine::contracts
{
namespace
{

namespace od = simdjson::ondemand;

/// Calls `apply(key, value)` for every non-null member of a config object; any error becomes a ContractError.
template <typename Apply>
std::expected<void, ContractError> forEachMember(std::string_view json, Apply apply)
{
    try
    {
        simdjson::padded_string padded{json};
        od::parser parser;
        od::document doc;
        od::object obj;
        if (parser.iterate(padded).get(doc) != simdjson::SUCCESS || doc.get_object().get(obj) != simdjson::SUCCESS)
        {
            throw std::runtime_error("an engine config is a JSON object");
        }
        for (auto field : obj)
        {
            std::string_view key;
            if (field.unescaped_key().get(key) != simdjson::SUCCESS)
            {
                throw std::runtime_error("unreadable key");
            }
            od::value v = field.value();
            if (!json::isNull(v))
            {
                apply(std::string{key}, v);
            }
        }
        return {};
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

}  // namespace

std::expected<StrataConfig, ContractError> parseStrataConfig(std::string_view jsonText)
{
    StrataConfig c;
    auto read = forEachMember(jsonText, [&](const std::string& key, od::value v) {
        if (key == "strataBin") c.strataBin = json::text(v, key);
        else if (key == "strataProfile") c.strataProfile = json::text(v, key);
        else if (key == "host") c.host = json::text(v, key);
        else if (key == "port") c.port = json::integer(v, key);
        else if (key == "slots") c.slots = json::integer(v, key);
    });
    if (!read)
    {
        return std::unexpected(read.error());
    }
    return c;
}

std::expected<BasaltConfig, ContractError> parseBasaltConfig(std::string_view jsonText)
{
    BasaltConfig c;
    auto read = forEachMember(jsonText, [&](const std::string& key, od::value v) {
        if (key == "basaltBin") c.basaltBin = json::text(v, key);
        else if (key == "basaltConfig") c.basaltConfig = json::text(v, key);
    });
    if (!read)
    {
        return std::unexpected(read.error());
    }
    return c;
}

}  // namespace sub0llmengine::contracts
