#pragma once
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace sub0llmengine::fit
{

enum class Verdict
{
    Fits,    // the backend loaded with this context
    Short,   // the backend refused: the card is `shortfallMiB` too small
    Failed,  // anything else (crash, bad flag, timeout): the search stops, the note says why
};

[[nodiscard]] const char* toString(Verdict verdict) noexcept;

/// One start of a backend with one context and one set of lever arguments.
struct Attempt
{
    std::int64_t context = 0;
    Verdict verdict = Verdict::Failed;
    std::int64_t shortfallMiB = 0;  // Short only
    std::string note;
};

/// Starts a backend with `context` and `leverArgs`, reports how the start ended, and stops it. The search never looks inside.
class IProbe
{
public:
    virtual ~IProbe() = default;
    [[nodiscard]] virtual Attempt run(std::int64_t context, const std::vector<std::string>& leverArgs) = 0;
};

/// A named set of extra backend arguments. The ladder is tried cheapest first; each step's arguments replace the previous step's.
struct LeverStep
{
    std::string name;
    std::vector<std::string> args;
};

struct SearchSpec
{
    std::int64_t target = 0;                // the context the caller wants
    std::int64_t granularity = 1024;        // answers are multiples of this
    std::int64_t minContext = 4096;         // below this a step is given up
    int maxProbesPerStep = 8;
    double mibPerPosition = 24.0 / 1024.0;  // first guess of the slope, deliberately high (a low guess overshoots far down); two refusals replace it
};

struct StepResult
{
    std::string lever;
    std::int64_t maxContext = 0;  // largest context that loaded, 0 = none
    std::vector<Attempt> attempts;
};

struct SearchResult
{
    std::vector<StepResult> steps;
    std::optional<std::size_t> best;  // index into steps: the first to reach the target, else the one with the largest context
    [[nodiscard]] bool reachedTarget(std::int64_t target) const;
};

/// Finds, per lever step, the largest context that loads (a refusal's shortfall predicts the next try; bisection finishes near the edge) and
/// stops at the first step that reaches the target. A start costs a model load, so it probes as few times as it can.
[[nodiscard]] SearchResult search(IProbe& probe, const SearchSpec& spec, const std::vector<LeverStep>& ladder);

/// Reads Basalt's server output: "weights  loaded, ctx=N" is a fit, "spill plan: ... the card is N MiB short" a refusal, any other
/// "error:" line a failure. Nothing decisive yet: nullopt (keep waiting).
[[nodiscard]] std::optional<Attempt> parseBasaltOutcome(std::string_view log, std::int64_t context);

struct BasaltProbeConfig
{
    std::string bin;                    // basalt executable
    std::string pack;                   // .basalt file
    std::uint16_t port = 8092;
    std::vector<std::string> baseArgs;  // --kv fp8 and the like, before the lever's
    std::filesystem::path logDir;
    std::chrono::seconds timeout{600};
};

/// Runs `basalt serve` through the supervision layer and reads the outcome from its output.
[[nodiscard]] std::unique_ptr<IProbe> makeBasaltProbe(BasaltProbeConfig config);

}  // namespace sub0llmengine::fit
