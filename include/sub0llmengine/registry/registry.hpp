#pragma once
#include "sub0llmengine/contracts/registry_files.hpp"

#include <expected>
#include <filesystem>
#include <set>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace sub0llmengine::registry
{

enum class ErrorKind
{
    Unreadable,   // the registry folder or one of its files cannot be read
    Unknown,      // no such alias, id or model
    Evicted,      // the files were deleted to save space; the registry's `restore` brings them back
    Ambiguous,    // several model files and none was named (`id#file`)
    Unavailable,  // the model has no usable artifact in the wanted formats on this machine
};

/// A sentence for a person that names the registry command that would fix it where one exists.
struct RegistryError
{
    ErrorKind kind;
    std::string message;
};

struct ResolvedModel
{
    std::filesystem::path path;  // the model file (or the version folder when it holds no model file)
    std::string id;              // the registry id, with #file when a file was chosen
};

enum class ArtifactState
{
    Present,      // on disk
    Evicted,      // known, files deleted to save space
    Available,    // not on disk, but a provider source is listed
    Convertible,  // not on disk, but a converter that is installed can make it from another artifact
    Unavailable,
};

struct Artifact
{
    contracts::ArtifactDefinition definition;
    ArtifactState state = ArtifactState::Unavailable;
    std::string id;  // the version that holds it, when present or evicted
};

[[nodiscard]] std::string_view toString(ArtifactState state) noexcept;

/// A read-only view of a Sub0LlmModelRegistry folder, as the registry's own reference tool sees it (docs/backends/registry-integration.md).
/// It never downloads, converts or restores: when something is missing it says which registry command would make it available, and the
/// owner decides.
class Registry
{
public:
    /// Reads <root>/registry.json and <root>/models/*.json. `converters` names the converter plugins installed (artifacts that need
    /// one are only Convertible when it is there).
    [[nodiscard]] static std::expected<Registry, RegistryError> open(const std::filesystem::path& root, std::set<std::string> converters = {});

    [[nodiscard]] const std::filesystem::path& root() const noexcept { return root_; }
    [[nodiscard]] bool hasModel(std::string_view name) const;

    /// An alias, id or id#file to its file; see the registry's spec/LAYOUT.md "Ids" for the main-file rule.
    [[nodiscard]] std::expected<ResolvedModel, RegistryError> resolve(std::string_view ref) const;

    /// Every artifact of a model with its state, derived without the network.
    [[nodiscard]] std::expected<std::vector<Artifact>, RegistryError> artifacts(std::string_view model) const;

    /// The first present artifact of `model` in the first of `formats` that has one (the caller's preference order), optionally narrowed
    /// to a variant or vendor. Nothing is fetched: a model that is not on disk is an Unavailable error naming the command to run.
    [[nodiscard]] std::expected<ResolvedModel, RegistryError> request(std::string_view model, std::span<const std::string> formats,
                                                                      std::string_view variant = {}, std::string_view vendor = {}) const;

private:
    Registry(std::filesystem::path root, contracts::RegistryIndex index, std::vector<contracts::ModelDefinition> models, std::set<std::string> converters);

    [[nodiscard]] const contracts::RegistryEntry* find(std::string_view id) const;

    std::filesystem::path root_;
    contracts::RegistryIndex index_;
    std::vector<contracts::ModelDefinition> models_;
    std::set<std::string> converters_;
};

/// Shell-style glob as the registry's provider specs use it: `*`, `?`, `[abc]`, `[a-z]` and `[!x]`.
[[nodiscard]] bool globMatches(std::string_view pattern, std::string_view text);

}  // namespace sub0llmengine::registry
