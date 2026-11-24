#pragma once
#include "sub0llmengine/contracts/bench_record.hpp"  // ContractError

#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace sub0llmengine::contracts
{

// What the engine reads of a Sub0LlmModelRegistry folder: the generated index (registry.json) and the model definitions
// (models/<name>.json). The registry's spec/LAYOUT.md is the authority; fields the engine does not use are ignored.

struct RegistrySource
{
    std::string provider;  // "hf", "url", ... ("kind" in the oldest manifests)
    std::string repo;
    std::string url;
};

struct RegistryFile
{
    std::string name;  // relative to the version folder, '/' separated
    std::string role;  // model | mmproj | shard | imatrix | adapter | tokenizer | config | other; empty when the manifest has none
};

struct RegistryEntry
{
    std::string id;
    std::string format;
    std::string dir;  // the version folder relative to the registry root, '/' separated
    std::vector<RegistryFile> files;
    std::optional<RegistrySource> source;
    bool evicted = false;  // the files were deleted to save space; the registry's `restore` brings them back
    std::optional<std::string> model;
    std::optional<std::string> variant;
    std::optional<std::string> vendor;
};

struct RegistryIndex
{
    std::map<std::string, std::string> aliases;  // short name -> id (or id#file)
    std::vector<RegistryEntry> entries;
};

struct ArtifactDefinition
{
    std::string format;
    std::string vendor;
    std::string variant;
    std::string converter;
    std::vector<std::string> sources;  // provider specs, e.g. "hf:org/repo#glob"; all must be present for the artifact to be
};

struct ModelDefinition
{
    std::string name;
    std::vector<ArtifactDefinition> artifacts;  // the preferred variant of a format is listed first
};

[[nodiscard]] std::expected<RegistryIndex, ContractError> parseRegistryIndex(std::string_view json);
[[nodiscard]] std::expected<ModelDefinition, ContractError> parseModelDefinition(std::string_view json);

}  // namespace sub0llmengine::contracts
