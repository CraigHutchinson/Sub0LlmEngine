#include "sub0llmengine/contracts/llama_config.hpp"

#include "json_fields.hpp"

#include <simdjson.h>

#include <stdexcept>

namespace sub0llmengine::contracts
{
namespace
{

namespace od = simdjson::ondemand;
using json::flag;
using json::integer;
using json::text;

/// Argument strings may be written as numbers in a config (an extra flag's value); they are kept as text.
std::string argument(od::value v)
{
    od::json_type type{};
    if (v.type().get(type) != simdjson::SUCCESS)
    {
        throw std::runtime_error("'extraArgs' holds an unreadable item");
    }
    if (type == od::json_type::string)
    {
        return text(v, "extraArgs");
    }
    if (type == od::json_type::number)
    {
        return std::string{simdjson::to_json_string(v).value()};
    }
    throw std::runtime_error("'extraArgs' items must be strings or numbers");
}

}  // namespace

std::expected<LlamaServerConfig, ContractError> parseLlamaServerConfig(std::string_view json)
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
        LlamaServerConfig c;
        for (auto field : obj)
        {
            std::string_view keyView;
            if (field.unescaped_key().get(keyView) != simdjson::SUCCESS)
            {
                throw std::runtime_error("unreadable key");
            }
            const std::string key{keyView};
            od::value v = field.value();
            bool null = false;
            if (v.is_null().get(null) == simdjson::SUCCESS && null)
            {
                continue;  // null means "not set", as an absent key does
            }
            if (key == "host") c.host = text(v, key);
            else if (key == "port") c.port = integer(v, key);
            else if (key == "ctx") c.ctx = integer(v, key);
            else if (key == "slots") c.slots = integer(v, key);
            else if (key == "gpuLayers") c.gpuLayers = integer(v, key);
            else if (key == "nCpuMoe") c.nCpuMoe = integer(v, key);
            else if (key == "flashAttn") c.flashAttn = text(v, key);
            else if (key == "cacheTypeK") c.cacheTypeK = text(v, key);
            else if (key == "cacheTypeV") c.cacheTypeV = text(v, key);
            else if (key == "batch") c.batch = integer(v, key);
            else if (key == "ubatch") c.ubatch = integer(v, key);
            else if (key == "threads") c.threads = integer(v, key);
            else if (key == "mmap") c.mmap = flag(v, key);
            else if (key == "kvUnified") c.kvUnified = flag(v, key);
            else if (key == "alias") c.alias = text(v, key);
            else if (key == "ctxCheckpoints") c.ctxCheckpoints = integer(v, key);
            else if (key == "cacheRam") c.cacheRam = integer(v, key);
            else if (key == "kvUnifiedPerSlot") c.kvUnifiedPerSlot = integer(v, key);
            else if (key == "extraArgs")
            {
                od::array items;
                if (v.get_array().get(items) != simdjson::SUCCESS)
                {
                    throw std::runtime_error("'extraArgs' must be a list");
                }
                for (auto item : items)
                {
                    c.extraArgs.push_back(argument(item.value()));
                }
            }
        }
        return c;
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

}  // namespace sub0llmengine::contracts
