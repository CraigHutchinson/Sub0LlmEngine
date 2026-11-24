#include "sub0llmengine/contracts/registry_files.hpp"

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

od::object objectOf(od::value v, std::string_view what)
{
    od::object obj;
    if (v.get_object().get(obj) != simdjson::SUCCESS)
    {
        throw std::runtime_error(std::string{what} + " must be an object");
    }
    return obj;
}

od::array arrayOf(od::value v, std::string_view what)
{
    od::array arr;
    if (v.get_array().get(arr) != simdjson::SUCCESS)
    {
        throw std::runtime_error(std::string{what} + " must be a list");
    }
    return arr;
}

RegistrySource sourceOf(od::value v)
{
    RegistrySource s;
    for (auto field : objectOf(v, "source"))
    {
        const std::string key = keyOf(field);
        od::value value = field.value();
        if (json::isNull(value))
        {
            continue;
        }
        if (key == "provider" || key == "kind") s.provider = json::text(value, key);
        else if (key == "repo") s.repo = json::text(value, key);
        else if (key == "url") s.url = json::text(value, key);
    }
    return s;
}

RegistryEntry entryOf(od::value v)
{
    RegistryEntry e;
    for (auto field : objectOf(v, "an entry"))
    {
        const std::string key = keyOf(field);
        od::value value = field.value();
        if (json::isNull(value))
        {
            continue;
        }
        if (key == "id") e.id = json::text(value, key);
        else if (key == "format") e.format = json::text(value, key);
        else if (key == "dir") e.dir = json::text(value, key);
        else if (key == "model") e.model = json::text(value, key);
        else if (key == "variant") e.variant = json::text(value, key);
        else if (key == "vendor") e.vendor = json::text(value, key);
        else if (key == "evicted") e.evicted = true;  // an object while evicted, null or absent otherwise
        else if (key == "source") e.source = sourceOf(value);
        else if (key == "files")
        {
            for (auto item : arrayOf(value, "files"))
            {
                RegistryFile f;
                for (auto part : objectOf(item.value(), "a file"))
                {
                    const std::string name = keyOf(part);
                    od::value partValue = part.value();
                    if (json::isNull(partValue))
                    {
                        continue;
                    }
                    if (name == "name") f.name = json::text(partValue, name);
                    else if (name == "role") f.role = json::text(partValue, name);
                }
                e.files.push_back(std::move(f));
            }
        }
    }
    return e;
}

std::vector<std::string> sourcesOf(od::value v)
{
    std::vector<std::string> out;
    od::json_type type{};
    if (v.type().get(type) != simdjson::SUCCESS)
    {
        throw std::runtime_error("unreadable source");
    }
    if (type == od::json_type::string)
    {
        out.push_back(json::text(v, "source"));
    }
    else
    {
        for (auto item : arrayOf(v, "source"))
        {
            out.push_back(json::text(item.value(), "source"));
        }
    }
    return out;
}

ArtifactDefinition artifactOf(od::value v)
{
    ArtifactDefinition a;
    for (auto field : objectOf(v, "an artifact"))
    {
        const std::string key = keyOf(field);
        od::value value = field.value();
        if (json::isNull(value))
        {
            continue;
        }
        if (key == "format") a.format = json::text(value, key);
        else if (key == "vendor") a.vendor = json::text(value, key);
        else if (key == "variant") a.variant = json::text(value, key);
        else if (key == "converter") a.converter = json::text(value, key);
        else if (key == "source") a.sources = sourcesOf(value);
    }
    if (a.format.empty())
    {
        throw std::runtime_error("an artifact needs a format");
    }
    return a;
}

}  // namespace

std::expected<RegistryIndex, ContractError> parseRegistryIndex(std::string_view jsonText)
{
    try
    {
        simdjson::padded_string padded{jsonText};
        od::parser parser;
        od::document doc;
        od::object root;
        if (parser.iterate(padded).get(doc) != simdjson::SUCCESS || doc.get_object().get(root) != simdjson::SUCCESS)
        {
            throw std::runtime_error("registry.json is a JSON object");
        }
        RegistryIndex index;
        for (auto field : root)
        {
            const std::string key = keyOf(field);
            if (key == "aliases")
            {
                for (auto alias : objectOf(field.value(), "aliases"))
                {
                    const std::string name = keyOf(alias);
                    index.aliases.emplace(name, json::text(alias.value(), name));
                }
            }
            else if (key == "entries")
            {
                for (auto entry : objectOf(field.value(), "entries"))
                {
                    index.entries.push_back(entryOf(entry.value()));
                }
            }
        }
        return index;
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

std::expected<ModelDefinition, ContractError> parseModelDefinition(std::string_view jsonText)
{
    try
    {
        simdjson::padded_string padded{jsonText};
        od::parser parser;
        od::document doc;
        od::object root;
        if (parser.iterate(padded).get(doc) != simdjson::SUCCESS || doc.get_object().get(root) != simdjson::SUCCESS)
        {
            throw std::runtime_error("a model definition is a JSON object");
        }
        ModelDefinition model;
        for (auto field : root)
        {
            const std::string key = keyOf(field);
            if (key == "name")
            {
                model.name = json::text(field.value(), key);
            }
            else if (key == "artifacts")
            {
                for (auto item : arrayOf(field.value(), "artifacts"))
                {
                    model.artifacts.push_back(artifactOf(item.value()));
                }
            }
        }
        if (model.name.empty())
        {
            throw std::runtime_error("a model definition needs a name");
        }
        return model;
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

}  // namespace sub0llmengine::contracts
