#include "sub0llmengine/registry/registry.hpp"

#include <algorithm>
#include <fstream>
#include <iterator>
#include <sstream>

namespace sub0llmengine::registry
{
namespace
{

namespace contracts = sub0llmengine::contracts;

std::expected<std::string, RegistryError> slurp(const std::filesystem::path& path)
{
    std::ifstream in{path, std::ios::binary};
    if (!in)
    {
        return std::unexpected(RegistryError{ErrorKind::Unreadable, "cannot read " + path.string()});
    }
    return std::string{std::istreambuf_iterator<char>{in}, std::istreambuf_iterator<char>{}};
}

bool endsWithAny(std::string_view name, std::initializer_list<std::string_view> suffixes)
{
    return std::ranges::any_of(suffixes, [&](std::string_view s) { return name.ends_with(s); });
}

std::string lower(std::string_view s)
{
    std::string out{s};
    std::ranges::transform(out, out.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return out;
}

/// The registry's role for a file: the manifest's when written, else from the name (store.roleOf in the reference).
std::string roleOf(const contracts::RegistryFile& file)
{
    if (!file.role.empty())
    {
        return file.role;
    }
    const std::string n = lower(file.name);
    if (n.find("mmproj") != std::string::npos || (n.ends_with(".strata") && n.find("vision") != std::string::npos))
    {
        return "mmproj";
    }
    // -NNNNN-of-NNNNN.gguf: the first shard is the model, the rest are shards.
    if (n.size() > 21 && n.ends_with(".gguf"))
    {
        const auto tail = n.substr(n.size() - 21);  // "-00001-of-00002.gguf"
        const bool split = tail[0] == '-' && tail.substr(6, 4) == "-of-" && std::ranges::all_of(tail.substr(1, 5), ::isdigit) &&
                           std::ranges::all_of(tail.substr(10, 5), ::isdigit);
        if (split)
        {
            return tail.substr(1, 5) == "00001" ? "model" : "shard";
        }
    }
    if (n.find("imatrix") != std::string::npos)
    {
        return "imatrix";
    }
    if (endsWithAny(n, {".gguf", ".gguf_file", ".safetensors", ".basalt", ".strata", ".bin", ".onnx", ".pt", ".pth"}))
    {
        return "model";
    }
    if (n.ends_with("tokenizer.json") || n.ends_with("tokenizer.model") || n.ends_with("vocab.json") || n.ends_with("merges.txt"))
    {
        return "tokenizer";
    }
    return n.ends_with(".json") ? "config" : "other";
}

std::filesystem::path join(const std::filesystem::path& root, std::string_view relative)
{
    std::filesystem::path out = root;
    std::string part;
    for (const char c : relative)
    {
        if (c == '/' || c == '\\')
        {
            if (!part.empty())
            {
                out /= part;
            }
            part.clear();
        }
        else
        {
            part.push_back(c);
        }
    }
    if (!part.empty())
    {
        out /= part;
    }
    return out;
}

struct Spec
{
    std::string provider;
    std::string repo;
    std::string pattern;  // empty: every file
};

/// "hf:org/repo[@rev][#glob]" -> provider, repo, glob (catalog.parseSpec in the reference).
Spec parseSpec(std::string_view spec)
{
    Spec s;
    const auto colon = spec.find(':');
    s.provider = std::string{spec.substr(0, colon)};
    std::string_view rest = colon == std::string_view::npos ? std::string_view{} : spec.substr(colon + 1);
    const auto hash = rest.find('#');
    std::string_view body = rest.substr(0, hash);
    if (hash != std::string_view::npos)
    {
        s.pattern = std::string{rest.substr(hash + 1)};
    }
    s.repo = std::string{body.substr(0, body.find('@'))};
    return s;
}

bool sameName(const std::optional<std::string>& a, std::string_view b)
{
    return a.value_or("") == b;
}

}  // namespace

std::string_view toString(ArtifactState state) noexcept
{
    switch (state)
    {
    case ArtifactState::Present: return "present";
    case ArtifactState::Evicted: return "evicted";
    case ArtifactState::Available: return "available";
    case ArtifactState::Convertible: return "convertible";
    case ArtifactState::Unavailable: return "unavailable";
    }
    return "unavailable";
}

bool globMatches(std::string_view pattern, std::string_view text)
{
    std::size_t p = 0;
    std::size_t t = 0;
    std::size_t starP = std::string_view::npos;
    std::size_t starT = 0;
    while (t < text.size())
    {
        bool matched = false;
        std::size_t next = p;
        if (p < pattern.size() && pattern[p] == '*')
        {
            starP = p++;
            starT = t;
            continue;
        }
        if (p < pattern.size() && pattern[p] == '?')
        {
            matched = true;
            next = p + 1;
        }
        else if (p < pattern.size() && pattern[p] == '[')
        {
            const auto close = pattern.find(']', p + 2);
            if (close != std::string_view::npos)
            {
                std::size_t i = p + 1;
                const bool negate = pattern[i] == '!' || pattern[i] == '^';
                if (negate)
                {
                    ++i;
                }
                bool inClass = false;
                while (i < close)
                {
                    if (i + 2 < close && pattern[i + 1] == '-')
                    {
                        inClass = inClass || (text[t] >= pattern[i] && text[t] <= pattern[i + 2]);
                        i += 3;
                    }
                    else
                    {
                        inClass = inClass || text[t] == pattern[i];
                        ++i;
                    }
                }
                matched = inClass != negate;
                next = close + 1;
            }
            else
            {
                matched = text[t] == '[';
                next = p + 1;
            }
        }
        else if (p < pattern.size())
        {
            matched = pattern[p] == text[t];
            next = p + 1;
        }
        if (matched)
        {
            p = next;
            ++t;
        }
        else if (starP != std::string_view::npos)
        {
            p = starP + 1;
            t = ++starT;
        }
        else
        {
            return false;
        }
    }
    while (p < pattern.size() && pattern[p] == '*')
    {
        ++p;
    }
    return p == pattern.size();
}

Registry::Registry(std::filesystem::path root, contracts::RegistryIndex index, std::vector<contracts::ModelDefinition> models,
                   std::set<std::string> converters)
    : root_{std::move(root)}, index_{std::move(index)}, models_{std::move(models)}, converters_{std::move(converters)}
{
}

std::expected<Registry, RegistryError> Registry::open(const std::filesystem::path& root, std::set<std::string> converters)
{
    auto text = slurp(root / "registry.json");
    if (!text)
    {
        return std::unexpected(text.error());
    }
    auto index = contracts::parseRegistryIndex(*text);
    if (!index)
    {
        return std::unexpected(RegistryError{ErrorKind::Unreadable, "registry.json: " + index.error().message});
    }
    std::vector<contracts::ModelDefinition> models;
    const auto modelsDir = root / "models";
    std::error_code ec;
    if (std::filesystem::is_directory(modelsDir, ec))
    {
        std::vector<std::filesystem::path> files;
        for (const auto& item : std::filesystem::directory_iterator{modelsDir, ec})
        {
            if (item.path().extension() == ".json")
            {
                files.push_back(item.path());
            }
        }
        std::ranges::sort(files);
        for (const auto& file : files)
        {
            auto body = slurp(file);
            if (!body)
            {
                return std::unexpected(body.error());
            }
            auto model = contracts::parseModelDefinition(*body);
            if (!model)
            {
                return std::unexpected(RegistryError{ErrorKind::Unreadable, file.filename().string() + ": " + model.error().message});
            }
            models.push_back(std::move(*model));
        }
    }
    return Registry{root, std::move(*index), std::move(models), std::move(converters)};
}

bool Registry::hasModel(std::string_view name) const
{
    return std::ranges::any_of(models_, [&](const auto& m) { return m.name == name; });
}

const contracts::RegistryEntry* Registry::find(std::string_view id) const
{
    const auto it = std::ranges::find_if(index_.entries, [&](const auto& e) { return e.id == id; });
    return it == index_.entries.end() ? nullptr : &*it;
}

std::expected<ResolvedModel, RegistryError> Registry::resolve(std::string_view ref) const
{
    std::string target{ref};
    if (const auto alias = index_.aliases.find(target); alias != index_.aliases.end())
    {
        target = alias->second;
    }
    const auto hash = target.find('#');
    const std::string base = target.substr(0, hash);
    std::string fname = hash == std::string::npos ? std::string{} : target.substr(hash + 1);
    const auto* entry = find(base);
    if (!entry)
    {
        return std::unexpected(RegistryError{ErrorKind::Unknown, "no registry entry: " + base});
    }
    if (entry->evicted)
    {
        return std::unexpected(RegistryError{ErrorKind::Evicted, base + " was evicted from this machine; restore it with: python -m sub0llmregistry restore " + base});
    }
    const auto folder = join(root_, entry->dir);
    if (fname.empty())
    {
        std::vector<std::string> models;
        for (const auto& f : entry->files)
        {
            if (roleOf(f) == "model")
            {
                models.push_back(f.name);
            }
        }
        if (models.size() == 1)
        {
            fname = models.front();
        }
        else if (models.size() > 1)
        {
            std::string all;
            for (const auto& m : models)
            {
                all += (all.empty() ? "" : ", ") + m;
            }
            return std::unexpected(RegistryError{ErrorKind::Ambiguous, base + " holds " + std::to_string(models.size()) + " model files; name one with #file: " + all});
        }
    }
    if (fname.empty())
    {
        return ResolvedModel{folder, base};
    }
    return ResolvedModel{join(folder, fname), base + "#" + fname};
}

std::expected<std::vector<Artifact>, RegistryError> Registry::artifacts(std::string_view model) const
{
    const auto it = std::ranges::find_if(models_, [&](const auto& m) { return m.name == model; });
    if (it == models_.end())
    {
        return std::unexpected(RegistryError{ErrorKind::Unknown, "no model definition: " + std::string{model}});
    }
    std::vector<Artifact> out;
    for (const auto& def : it->artifacts)
    {
        // The versions that hold this artifact's files, found without the network: by their provider source, or tagged for it.
        std::vector<const contracts::RegistryEntry*> held;
        std::size_t covered = 0;
        for (const auto& specText : def.sources)
        {
            const Spec spec = parseSpec(specText);
            bool hit = false;
            for (const auto& e : index_.entries)
            {
                if (!e.source)
                {
                    continue;
                }
                const auto& repo = e.source->repo.empty() ? e.source->url : e.source->repo;
                if (e.source->provider != spec.provider || repo != spec.repo)
                {
                    continue;
                }
                const bool inside = spec.pattern.empty() || std::ranges::any_of(e.files, [&](const auto& f) {
                                        return f.name == spec.pattern || globMatches(spec.pattern, f.name);
                                    });
                if (inside)
                {
                    hit = true;
                    if (std::ranges::find(held, &e) == held.end())
                    {
                        held.push_back(&e);
                    }
                }
            }
            covered += hit;
        }
        bool tagged = false;
        for (const auto& e : index_.entries)
        {
            if (e.model == std::string{model} && sameName(e.variant, def.variant) && e.format == def.format)
            {
                tagged = true;
                if (std::ranges::find(held, &e) == held.end())
                {
                    held.push_back(&e);
                }
            }
        }
        Artifact a{def, ArtifactState::Unavailable, {}};
        const bool allCovered = !def.sources.empty() && covered == def.sources.size();
        if (!held.empty() && (allCovered || tagged))
        {
            a.state = std::ranges::any_of(held, [](const auto* e) { return e->evicted; }) ? ArtifactState::Evicted : ArtifactState::Present;
            a.id = held.front()->id;
        }
        else if (!def.sources.empty())
        {
            a.state = ArtifactState::Available;
        }
        else if (converters_.contains(def.converter))
        {
            a.state = ArtifactState::Convertible;
        }
        out.push_back(std::move(a));
    }
    return out;
}

std::expected<ResolvedModel, RegistryError> Registry::request(std::string_view model, std::span<const std::string> formats,
                                                              std::string_view variant, std::string_view vendor) const
{
    auto all = artifacts(model);
    if (!all)
    {
        return std::unexpected(all.error());
    }
    std::vector<const Artifact*> rows;
    for (const auto& a : *all)
    {
        const bool wanted = std::ranges::find(formats, a.definition.format) != formats.end();
        if (wanted && (variant.empty() || a.definition.variant == variant) && (vendor.empty() || a.definition.vendor == vendor))
        {
            rows.push_back(&a);
        }
    }
    const auto rank = [&](const Artifact* a) { return std::ranges::find(formats, a->definition.format) - formats.begin(); };
    std::ranges::stable_sort(rows, [&](const Artifact* a, const Artifact* b) { return rank(a) < rank(b); });
    for (const auto* row : rows)
    {
        if (row->state == ArtifactState::Present)
        {
            return resolve(row->id);
        }
    }
    std::string wanted;
    for (const auto& f : formats)
    {
        wanted += (wanted.empty() ? "" : "/") + f;
    }
    std::string message = std::string{model} + " has no " + wanted + " artifact on this machine";
    if (rows.empty())
    {
        message += "; the model definition lists none";
    }
    else
    {
        std::string list;
        for (const auto* r : rows)
        {
            list += (list.empty() ? "" : ", ") + r->definition.format + " " + r->definition.variant + " (" + std::string{toString(r->state)} + ")";
        }
        message += "; available: " + list + "; run: python -m sub0llmregistry request " + std::string{model} + " --format " + formats.front() + " --fetch";
    }
    return std::unexpected(RegistryError{ErrorKind::Unavailable, std::move(message)});
}

}  // namespace sub0llmengine::registry
