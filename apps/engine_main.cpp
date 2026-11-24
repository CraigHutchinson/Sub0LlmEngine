// sub0llmengine: starts, inspects and stops the inference engine on this machine. First backend: Basalt.
//   sub0llmengine start  --backend basalt --model "Inkling 2 Mini" [--max-context N] [--parallel N] [--kv fp8] [--port N] [--alias NAME] [-- extra flags]
//   sub0llmengine command ...   the same, printing the command line and starting nothing
//   sub0llmengine status [--json]
//   sub0llmengine stop
// Settings come from the command line, over the machine-local engine.local.json (basaltBin, registry, basaltPack, basaltMaxContext,
// basaltParallel, basaltKv, basaltAlias, basaltBuild). Exit codes: 0 ok, 1 not started / nothing answers, 2 the machine is held for a timing run.
#include "sub0llmengine/backends/native_backends.hpp"
#include "sub0llmengine/contracts/engine_record.hpp"
#include "sub0llmengine/control/engine_control.hpp"
#include "sub0llmengine/net/http.hpp"
#include "sub0llmengine/registry/registry.hpp"
#include "sub0llmengine/supervision/machine_lease.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <format>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace
{

using namespace sub0llmengine;
namespace fs = std::filesystem;

std::string readText(const fs::path& path)
{
    std::ifstream in{path, std::ios::binary};
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

std::string now()
{
    const auto t = std::time(nullptr);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    return std::format("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
}

std::string textOf(const contracts::Params& p, const std::string& key)
{
    const auto it = p.find(key);
    if (it == p.end()) return {};
    if (const auto* s = std::get_if<std::string>(&it->second)) return *s;
    if (const auto* i = std::get_if<std::int64_t>(&it->second)) return std::to_string(*i);
    return {};
}

struct Options
{
    std::string command;
    std::string backend = "basalt";
    std::string model, pack, kv, alias, configFile = "engine.local.json", stateDir = "out";
    std::optional<std::int64_t> maxContext, parallel;
    std::uint16_t port = 8092;
    int timeoutSeconds = 600;
    bool json = false;
    std::vector<std::string> extra;
};

std::optional<Options> parse(int argc, char** argv)
{
    Options o;
    if (argc < 2) return std::nullopt;
    o.command = argv[1];
    for (int i = 2; i < argc; ++i)
    {
        const std::string flag = argv[i];
        if (flag == "--json") { o.json = true; continue; }
        if (flag == "--")
        {
            for (++i; i < argc; ++i) o.extra.emplace_back(argv[i]);
            break;
        }
        if (i + 1 >= argc) { std::fprintf(stderr, "%s needs a value\n", flag.c_str()); return std::nullopt; }
        const std::string value = argv[++i];
        if (flag == "--backend") o.backend = value;
        else if (flag == "--model") o.model = value;
        else if (flag == "--pack") o.pack = value;
        else if (flag == "--kv") o.kv = value;
        else if (flag == "--alias") o.alias = value;
        else if (flag == "--config") o.configFile = value;
        else if (flag == "--state-dir") o.stateDir = value;
        else if (flag == "--max-context") o.maxContext = std::atoll(value.c_str());
        else if (flag == "--parallel") o.parallel = std::atoll(value.c_str());
        else if (flag == "--port") o.port = static_cast<std::uint16_t>(std::atoi(value.c_str()));
        else if (flag == "--timeout") o.timeoutSeconds = std::atoi(value.c_str());
        else { std::fprintf(stderr, "unknown option %s\n", flag.c_str()); return std::nullopt; }
    }
    return o;
}

/// The basalt command and the model it names, from the options over the local config.
std::optional<std::pair<backends::BasaltServe, std::string>> plan(const Options& o, const contracts::Params& local)
{
    backends::BasaltServe serve;
    serve.bin = textOf(local, "basaltBin");
    if (serve.bin.empty())
    {
        std::fprintf(stderr, "no Basalt executable: set basaltBin in %s\n", o.configFile.c_str());
        return std::nullopt;
    }
    std::string modelId = o.model;
    serve.pack = !o.pack.empty() ? o.pack : textOf(local, "basaltPack");
    if (serve.pack.empty() || (!o.model.empty() && o.pack.empty()))
    {
        const auto root = textOf(local, "registry");
        if (o.model.empty() || root.empty())
        {
            std::fprintf(stderr, "no model: pass --model NAME (with registry set in %s) or --pack FILE\n", o.configFile.c_str());
            return std::nullopt;
        }
        auto registry = registry::Registry::open(root);
        if (!registry)
        {
            std::fprintf(stderr, "%s\n", registry.error().message.c_str());
            return std::nullopt;
        }
        const std::vector<std::string> formats = {"basalt"};
        auto resolved = registry->request(o.model, formats);
        if (!resolved)
        {
            std::fprintf(stderr, "%s\n", resolved.error().message.c_str());
            return std::nullopt;
        }
        serve.pack = resolved->path.generic_string();
        modelId = resolved->id;
    }
    serve.alias = !o.alias.empty() ? o.alias : textOf(local, "basaltAlias");
    serve.port = o.port;
    serve.maxContext = o.maxContext ? o.maxContext : (textOf(local, "basaltMaxContext").empty() ? std::nullopt : std::optional<std::int64_t>{std::atoll(textOf(local, "basaltMaxContext").c_str())});
    serve.parallel = o.parallel ? o.parallel : (textOf(local, "basaltParallel").empty() ? std::nullopt : std::optional<std::int64_t>{std::atoll(textOf(local, "basaltParallel").c_str())});
    serve.kv = !o.kv.empty() ? o.kv : textOf(local, "basaltKv");
    serve.extra = o.extra;
    return std::make_pair(serve, modelId);
}

fs::path recordFile(const Options& o) { return fs::path{o.stateDir} / "engine.json"; }

std::optional<contracts::EngineRecord> readRecord(const Options& o)
{
    const auto text = readText(recordFile(o));
    if (text.empty()) return std::nullopt;
    auto record = contracts::parseEngineRecord(text);
    return record ? std::optional{*record} : std::nullopt;
}

bool answers(net::IHttpClient& client, const contracts::EngineRecord& r)
{
    const auto port = static_cast<std::uint16_t>(std::atoi(r.url.substr(r.url.rfind(':') + 1).c_str()));
    auto reply = client.send("127.0.0.1", port, net::HttpRequest{"GET", "/health", {}, {}}, std::chrono::seconds{2});
    return reply && reply->status == 200;
}

int printRecord(const Options& o, const contracts::EngineRecord& r, bool running, bool healthy)
{
    if (o.json)
    {
        std::printf("%s\n", contracts::toJson(r).c_str());
    }
    else
    {
        std::printf("%s: %s pid %lld, %s, model %s\n", healthy ? "ready" : (running ? "running, not answering" : "stopped"), r.backend.c_str(),
                    static_cast<long long>(r.pid), r.url.c_str(), r.modelId.c_str());
    }
    return healthy ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv)
{
    const auto options = parse(argc, argv);
    if (!options || (options->command != "start" && options->command != "command" && options->command != "status" && options->command != "stop"))
    {
        std::fprintf(stderr, "usage: sub0llmengine start|command|status|stop [--backend basalt] [--model NAME | --pack FILE] [--max-context N] [--parallel N] [--kv K] "
                             "[--port N] [--alias NAME] [--json] [-- extra flags]\n");
        return 2;
    }
    const auto& o = *options;
    auto client = net::makeHttpClient();

    if (o.command == "status" || o.command == "stop")
    {
        const auto record = readRecord(o);
        if (!record)
        {
            std::printf("nothing recorded in %s\n", recordFile(o).string().c_str());
            return o.command == "stop" ? 0 : 1;
        }
        if (o.command == "status")
        {
            return printRecord(o, *record, control::processRunning(record->pid), answers(*client, *record));
        }
        const bool gone = control::stopProcessTree(record->pid);
        std::error_code ec;
        if (gone) fs::remove(recordFile(o), ec);
        std::printf("%s pid %lld\n", gone ? "stopped" : "could not stop", static_cast<long long>(record->pid));
        return gone ? 0 : 1;
    }

    if (o.backend != "basalt")
    {
        std::fprintf(stderr, "backend '%s' is not served by this command yet (basalt only)\n", o.backend.c_str());
        return 2;
    }
    contracts::Params local;
    if (const auto text = readText(o.configFile); !text.empty())
    {
        auto parsed = contracts::parseFlatParams(text);
        if (!parsed)
        {
            std::fprintf(stderr, "%s: %s\n", o.configFile.c_str(), parsed.error().message.c_str());
            return 2;
        }
        local = *parsed;
    }
    const auto planned = plan(o, local);
    if (!planned) return 2;
    const auto& [serve, modelId] = *planned;
    const auto argv0 = backends::basaltPackCommand(serve);
    if (o.command == "command")
    {
        for (const auto& part : argv0) std::printf("%s%s", backends::quoteWindowsArgument(part).c_str(), &part == &argv0.back() ? "\n" : " ");
        return 0;
    }

    // A running engine is never started twice; a timing run holds the machine and the engine does not start under it.
    if (const auto existing = readRecord(o); existing && control::processRunning(existing->pid))
    {
        std::printf("already running: ");
        return printRecord(o, *existing, true, answers(*client, *existing));
    }
    if (auto probe = supervision::MachineLease::acquire("sub0llmengine", "start check"); !probe)
    {
        std::fprintf(stderr, "not starting: %s\n", probe.error().message.c_str());
        return 2;
    }
    supervision::InstanceSpec spec;
    spec.argv = argv0;
    spec.host = serve.host;
    spec.port = serve.port;
    spec.logFile = fs::path{o.stateDir} / std::format("basalt-{}.log", serve.port);
    std::error_code ec;
    fs::remove(spec.logFile, ec);
    const auto result = control::startBasalt(spec, *client, std::chrono::seconds{o.timeoutSeconds});
    switch (result.kind)
    {
    case control::StartKind::Ready: break;
    case control::StartKind::Refused:
        std::fprintf(stderr, "refused: the card is %lld MiB short at --max-context %s; sub0engine_fit finds what fits\n", static_cast<long long>(result.shortfallMiB),
                     serve.maxContext ? std::to_string(*serve.maxContext).c_str() : "default");
        return 1;
    default:
        std::fprintf(stderr, "%s: %s\n", result.kind == control::StartKind::TimedOut ? "timed out" : "failed", result.message.c_str());
        return 1;
    }
    contracts::EngineRecord record;
    record.pid = result.pid;
    record.url = std::format("http://{}:{}/v1", serve.host, serve.port);
    record.startedAt = now();
    record.backend = "basalt";
    const auto buildName = !textOf(local, "basaltBuild").empty() ? textOf(local, "basaltBuild") : fs::path{serve.bin}.parent_path().parent_path().filename().string();
    record.build = buildName;
    record.modelId = modelId;
    record.modelPath = serve.pack;
    if (serve.maxContext) record.config["maxContext"] = *serve.maxContext;
    if (serve.parallel) record.config["slots"] = *serve.parallel;
    if (!serve.kv.empty()) record.config["kv"] = serve.kv;
    record.config["port"] = static_cast<std::int64_t>(serve.port);
    if (!serve.alias.empty()) record.config["alias"] = serve.alias;
    record.command = argv0;
    record.log = spec.logFile.generic_string();
    fs::create_directories(o.stateDir, ec);
    std::ofstream{recordFile(o), std::ios::trunc} << contracts::toJson(record) << '\n';
    return printRecord(o, record, true, true);
}
