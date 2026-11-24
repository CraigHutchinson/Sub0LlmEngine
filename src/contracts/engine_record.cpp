#include "sub0llmengine/contracts/engine_record.hpp"

#include "json_fields.hpp"

#include <simdjson.h>

namespace sub0llmengine::contracts
{
namespace
{

namespace od = simdjson::ondemand;

template <typename Field>
std::string keyOf(Field& field)
{
    std::string_view key;
    if (field.unescaped_key().get(key) != simdjson::SUCCESS)
    {
        throw std::runtime_error("unreadable key");
    }
    return std::string{key};
}

od::object rootOf(od::parser& parser, const simdjson::padded_string& padded, od::document& doc)
{
    od::object root;
    if (parser.iterate(padded).get(doc) != simdjson::SUCCESS || doc.get_object().get(root) != simdjson::SUCCESS)
    {
        throw std::runtime_error("expected a JSON object");
    }
    return root;
}

/// One scalar as a Param, or nullopt for null, arrays and objects.
std::optional<ParamValue> scalarOf(od::value v)
{
    od::json_type type{};
    if (v.type().get(type) != simdjson::SUCCESS)
    {
        throw std::runtime_error("unreadable value");
    }
    switch (type)
    {
    case od::json_type::string: return json::text(v, "value");
    case od::json_type::boolean: return json::flag(v, "value");
    case od::json_type::number:
    {
        od::number_type kind{};
        if (v.get_number_type().get(kind) != simdjson::SUCCESS)
        {
            throw std::runtime_error("unreadable number");
        }
        if (kind == od::number_type::floating_point_number) return json::real(v, "value");
        return json::integer(v, "value");
    }
    default: return std::nullopt;
    }
}

void appendParam(simdjson::builder::string_builder& sb, const ParamValue& value)
{
    if (const auto* i = std::get_if<std::int64_t>(&value)) sb.append(*i);
    else if (const auto* d = std::get_if<double>(&value)) sb.append(*d);
    else if (const auto* b = std::get_if<bool>(&value)) sb.append(*b);
    else sb.escape_and_append_with_quotes(std::get<std::string>(value));
}

void key(simdjson::builder::string_builder& sb, std::string_view name)
{
    sb.escape_and_append_with_quotes(name);
    sb.append_colon();
}

}  // namespace

std::string toJson(const EngineRecord& r)
{
    simdjson::builder::string_builder sb;
    sb.start_object();
    key(sb, "format");
    sb.escape_and_append_with_quotes(r.format);
    sb.append_comma();
    key(sb, "pid");
    sb.append(r.pid);
    sb.append_comma();
    key(sb, "url");
    sb.escape_and_append_with_quotes(r.url);
    sb.append_comma();
    key(sb, "startedAt");
    sb.escape_and_append_with_quotes(r.startedAt);
    sb.append_comma();
    key(sb, "backend");
    sb.escape_and_append_with_quotes(r.backend);
    sb.append_comma();
    key(sb, "build");
    sb.escape_and_append_with_quotes(r.build);
    sb.append_comma();
    key(sb, "model");
    sb.start_object();
    key(sb, "id");
    sb.escape_and_append_with_quotes(r.modelId);
    sb.append_comma();
    key(sb, "path");
    sb.escape_and_append_with_quotes(r.modelPath);
    sb.end_object();
    sb.append_comma();
    key(sb, "config");
    sb.start_object();
    bool first = true;
    for (const auto& [name, value] : r.config)
    {
        if (!first) sb.append_comma();
        first = false;
        key(sb, name);
        appendParam(sb, value);
    }
    sb.end_object();
    sb.append_comma();
    key(sb, "command");
    sb.start_array();
    first = true;
    for (const auto& part : r.command)
    {
        if (!first) sb.append_comma();
        first = false;
        sb.escape_and_append_with_quotes(part);
    }
    sb.end_array();
    sb.append_comma();
    key(sb, "log");
    sb.escape_and_append_with_quotes(r.log);
    sb.end_object();
    std::string_view view;
    if (sb.view().get(view) != simdjson::SUCCESS)
    {
        return {};
    }
    return std::string{view};
}

std::expected<EngineRecord, ContractError> parseEngineRecord(std::string_view jsonText)
{
    try
    {
        simdjson::padded_string padded{jsonText};
        od::parser parser;
        od::document doc;
        EngineRecord r;
        r.format.clear();
        for (auto field : rootOf(parser, padded, doc))
        {
            const std::string name = keyOf(field);
            od::value v = field.value();
            if (json::isNull(v)) continue;
            if (name == "format") r.format = json::text(v, name);
            else if (name == "pid") r.pid = json::integer(v, name);
            else if (name == "url") r.url = json::text(v, name);
            else if (name == "startedAt") r.startedAt = json::text(v, name);
            else if (name == "backend") r.backend = json::text(v, name);
            else if (name == "build") r.build = json::text(v, name);
            else if (name == "log") r.log = json::text(v, name);
            else if (name == "model")
            {
                od::object model;
                if (v.get_object().get(model) != simdjson::SUCCESS) throw std::runtime_error("'model' must be an object");
                for (auto part : model)
                {
                    const std::string partName = keyOf(part);
                    od::value partValue = part.value();
                    if (json::isNull(partValue)) continue;
                    if (partName == "id") r.modelId = json::text(partValue, partName);
                    else if (partName == "path") r.modelPath = json::text(partValue, partName);
                }
            }
            else if (name == "config")
            {
                od::object config;
                if (v.get_object().get(config) != simdjson::SUCCESS) throw std::runtime_error("'config' must be an object");
                for (auto part : config)
                {
                    const std::string partName = keyOf(part);
                    if (auto value = scalarOf(part.value())) r.config[partName] = *value;
                }
            }
            else if (name == "command")
            {
                od::array command;
                if (v.get_array().get(command) != simdjson::SUCCESS) throw std::runtime_error("'command' must be a list");
                for (auto item : command) r.command.push_back(json::text(item.value(), "command"));
            }
        }
        if (r.format != "sub0llmengine.engine.v1")
        {
            throw std::runtime_error("not a sub0llmengine.engine.v1 record");
        }
        return r;
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

std::expected<Params, ContractError> parseFlatParams(std::string_view jsonText)
{
    try
    {
        simdjson::padded_string padded{jsonText};
        od::parser parser;
        od::document doc;
        Params out;
        for (auto field : rootOf(parser, padded, doc))
        {
            const std::string name = keyOf(field);
            if (auto value = scalarOf(field.value())) out[name] = *value;
        }
        return out;
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

}  // namespace sub0llmengine::contracts
