#include "sub0llmengine/fit/fit.hpp"
#include "sub0llmengine/supervision/instance.hpp"

#include <charconv>
#include <format>
#include <fstream>
#include <sstream>
#include <thread>

namespace sub0llmengine::fit
{
namespace
{

std::string readFile(const std::filesystem::path& path)
{
    std::ifstream in{path, std::ios::binary};
    std::ostringstream text;
    text << in.rdbuf();
    return text.str();
}

class BasaltProbe final : public IProbe
{
public:
    explicit BasaltProbe(BasaltProbeConfig config) : config_{std::move(config)} {}

    Attempt run(std::int64_t context, const std::vector<std::string>& leverArgs) override
    {
        supervision::InstanceSpec spec;
        spec.argv = {config_.bin, "serve", "--model", config_.pack, "--port", std::to_string(config_.port), "--max-context", std::to_string(context)};
        spec.argv.insert(spec.argv.end(), config_.baseArgs.begin(), config_.baseArgs.end());
        spec.argv.insert(spec.argv.end(), leverArgs.begin(), leverArgs.end());
        spec.port = config_.port;
        spec.logFile = config_.logDir / std::format("fit-{}-{}.log", config_.port, context);
        std::error_code ec;
        std::filesystem::remove(spec.logFile, ec);

        auto instance = supervision::Instance::start(spec);
        if (!instance)
        {
            return Attempt{context, Verdict::Failed, 0, instance.error().message};
        }
        Attempt result{context, Verdict::Failed, 0, "no decision before the time limit"};
        const auto deadline = std::chrono::steady_clock::now() + config_.timeout;
        while (std::chrono::steady_clock::now() < deadline)
        {
            std::this_thread::sleep_for(std::chrono::milliseconds{500});
            const bool exited = !instance->alive();
            if (auto outcome = parseBasaltOutcome(readFile(spec.logFile), context))
            {
                result = *outcome;
                break;
            }
            if (exited)
            {
                result.note = "the server exited without a decision; see " + spec.logFile.string();
                break;
            }
        }
        (void)instance->stop(std::chrono::seconds{15});
        return result;
    }

private:
    BasaltProbeConfig config_;
};

}  // namespace

std::optional<Attempt> parseBasaltOutcome(std::string_view log, std::int64_t context)
{
    std::optional<Attempt> failure;
    while (!log.empty())
    {
        const auto end = log.find('\n');
        std::string_view line = log.substr(0, end);
        log = end == std::string_view::npos ? std::string_view{} : log.substr(end + 1);
        while (!line.empty() && line.back() == '\r')
        {
            line.remove_suffix(1);
        }
        if (line.find("weights") != std::string_view::npos && line.find("loaded, ctx=") != std::string_view::npos)
        {
            return Attempt{context, Verdict::Fits, 0, std::string{line}};
        }
        const auto mib = line.find(" MiB short");
        if (mib != std::string_view::npos && line.find("spill plan") != std::string_view::npos)
        {
            const auto start = line.rfind(' ', mib - 1);
            std::int64_t shortfall = 0;
            const auto digits = line.substr(start + 1, mib - start - 1);
            if (std::from_chars(digits.data(), digits.data() + digits.size(), shortfall).ec == std::errc{})
            {
                return Attempt{context, Verdict::Short, shortfall, std::string{line}};
            }
        }
        if (!failure && line.find("error:") != std::string_view::npos)
        {
            failure = Attempt{context, Verdict::Failed, 0, std::string{line}};
        }
    }
    return failure;
}

std::unique_ptr<IProbe> makeBasaltProbe(BasaltProbeConfig config)
{
    return std::make_unique<BasaltProbe>(std::move(config));
}

}  // namespace sub0llmengine::fit
