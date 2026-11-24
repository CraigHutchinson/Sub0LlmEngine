#include "sub0llmengine/fit/fit.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace sub0llmengine::fit
{
namespace
{

std::int64_t floorTo(std::int64_t value, std::int64_t step)
{
    return value - (value % step);
}

StepResult searchStep(IProbe& probe, const SearchSpec& spec, const LeverStep& step)
{
    StepResult out;
    out.lever = step.name;
    constexpr auto none = std::numeric_limits<std::int64_t>::max();
    std::int64_t lo = 0;       // largest context known to fit
    std::int64_t hi = none;    // smallest context known to be refused
    std::int64_t hiShort = 0;  // its shortfall
    double slope = spec.mibPerPosition;
    bool confirmed = false;
    std::int64_t context = floorTo(spec.target, spec.granularity);
    for (int n = 0; n < spec.maxProbesPerStep && context >= spec.minContext; ++n)
    {
        const Attempt attempt = probe.run(context, step.args);
        out.attempts.push_back(attempt);
        if (attempt.verdict == Verdict::Failed)
        {
            break;
        }
        if (attempt.verdict == Verdict::Fits)
        {
            lo = std::max(lo, context);
            if (lo >= spec.target)
            {
                break;
            }
        }
        else
        {
            if (hi != none && hi > context && hiShort > attempt.shortfallMiB)
            {
                slope = static_cast<double>(hiShort - attempt.shortfallMiB) / static_cast<double>(hi - context);
            }
            if (context < hi)
            {
                hi = context;
                hiShort = attempt.shortfallMiB;
            }
        }
        if (hi == none)
        {
            break;  // nothing refused yet and the last start fit: it was the target
        }
        // The refusal's shortfall says how far to step down; between a fit and a refusal, take the predicted edge, else the middle.
        std::int64_t next = floorTo(hi - static_cast<std::int64_t>(std::ceil(static_cast<double>(hiShort) / slope)), spec.granularity);
        if (next <= lo || next >= hi)
        {
            // The prediction is the edge we already hold: confirm it with the next granule up (one refusal ends the step); if that fits
            // too the slope guess was off, so bisect from there.
            next = confirmed ? floorTo(lo + (hi - lo) / 2, spec.granularity) : lo + spec.granularity;
            confirmed = true;
        }
        if (next <= lo || next >= hi || hi - lo <= spec.granularity)
        {
            break;
        }
        context = next;
    }
    out.maxContext = lo;
    return out;
}

}  // namespace

const char* toString(Verdict verdict) noexcept
{
    switch (verdict)
    {
    case Verdict::Fits: return "fits";
    case Verdict::Short: return "short";
    case Verdict::Failed: return "failed";
    }
    return "failed";
}

bool SearchResult::reachedTarget(std::int64_t target) const
{
    return best && steps[*best].maxContext >= target;
}

SearchResult search(IProbe& probe, const SearchSpec& spec, const std::vector<LeverStep>& ladder)
{
    SearchResult result;
    for (const auto& step : ladder)
    {
        result.steps.push_back(searchStep(probe, spec, step));
        const auto index = result.steps.size() - 1;
        if (!result.best || result.steps[index].maxContext > result.steps[*result.best].maxContext)
        {
            result.best = index;
        }
        if (result.steps[index].maxContext >= spec.target)
        {
            break;
        }
    }
    return result;
}

}  // namespace sub0llmengine::fit
