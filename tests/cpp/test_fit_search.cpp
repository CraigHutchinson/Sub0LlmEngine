// The fit search finds the largest context a backend loads, from as few starts as it can; the Basalt log reader turns server output into
// a verdict. A model of the card stands in for the backend; nothing here needs a GPU.
#include "check.hpp"
#include "sub0llmengine/fit/fit.hpp"

#include <cmath>
#include <string>

namespace
{

using namespace sub0llmengine::fit;

// A card with `budgetMiB` for the context: it holds a position in `kibPerPosition` KiB; a lever (name in args) adds `bonusMiB`.
class FakeCard final : public IProbe
{
public:
    FakeCard(double budgetMiB, double kibPerPosition) : budget_{budgetMiB}, kib_{kibPerPosition} {}

    Attempt run(std::int64_t context, const std::vector<std::string>& leverArgs) override
    {
        ++starts;
        if (failOn == context)
        {
            return Attempt{context, Verdict::Failed, 0, "crashed"};
        }
        const double room = budget_ + (leverArgs.empty() ? 0.0 : bonus);
        const double need = static_cast<double>(context) * kib_ / 1024.0;
        if (need <= room)
        {
            return Attempt{context, Verdict::Fits, 0, ""};
        }
        return Attempt{context, Verdict::Short, static_cast<std::int64_t>(std::ceil(need - room)), ""};
    }

    int starts = 0;
    double bonus = 0;
    std::int64_t failOn = -1;

private:
    double budget_;
    double kib_;
};

}  // namespace

int main()
{
    // Fits at once: one start.
    {
        FakeCard card{4000, 14};  // fits 292,571 positions
        const auto result = search(card, SearchSpec{.target = 131072}, {{"base", {}}});
        CHECK(result.reachedTarget(131072));
        CHECK_EQ(card.starts, 1);
    }
    // Short: the refusal predicts the edge, so a few starts land within one granule of the real limit (1,400 MiB / 14 KiB = 102,400).
    {
        FakeCard card{1400, 14};
        const auto result = search(card, SearchSpec{.target = 131072}, {{"base", {}}});
        CHECK(result.best.has_value());
        const auto step = result.steps.at(0);
        CHECK(!result.reachedTarget(131072));
        CHECK(step.maxContext <= 102400 && step.maxContext > 102400 - 1024);
        CHECK(card.starts <= 5);
    }
    // A wrong first guess of the slope (real cost 20 KiB, guessed 14) still converges.
    {
        FakeCard card{1400, 20};  // 71,680 positions
        const auto result = search(card, SearchSpec{.target = 131072}, {{"base", {}}});
        CHECK(result.steps.at(0).maxContext <= 71680 && result.steps.at(0).maxContext > 71680 - 1024);
        CHECK(card.starts <= 8);
    }
    // The ladder moves to the next lever when the first cannot reach the target, and stops at the first that does.
    {
        FakeCard card{1400, 14};
        card.bonus = 600;  // any lever with arguments: 2,000 MiB = 146,285 positions
        const auto result = search(card, SearchSpec{.target = 131072}, {{"base", {}}, {"reserve", {"--x"}}, {"never", {"--y"}}});
        CHECK_EQ(result.steps.size(), std::size_t{2});
        CHECK(result.reachedTarget(131072));
        CHECK_EQ(result.steps.at(*result.best).lever, std::string{"reserve"});
    }
    // When nothing reaches the target the best step is the one with the largest context.
    {
        FakeCard card{1400, 14};
        card.bonus = 100;
        const auto result = search(card, SearchSpec{.target = 262144}, {{"base", {}}, {"reserve", {"--x"}}});
        CHECK_EQ(result.steps.size(), std::size_t{2});
        CHECK(!result.reachedTarget(262144));
        CHECK_EQ(result.steps.at(*result.best).lever, std::string{"reserve"});
    }
    // A failure (not a refusal) stops the step: a wrong flag is not a smaller context's problem.
    {
        FakeCard card{1400, 14};
        card.failOn = 131072;
        const auto result = search(card, SearchSpec{.target = 131072}, {{"base", {}}});
        CHECK_EQ(card.starts, 1);
        CHECK_EQ(result.steps.at(0).maxContext, std::int64_t{0});
        CHECK(result.steps.at(0).attempts.at(0).verdict == Verdict::Failed);
    }
    // Basalt's output, as it printed on the 8 GB card.
    {
        const auto fits = parseBasaltOutcome(
            "[server] placed   cuda0 1.2GiB 1.3s\n[server] loaded   16.8GiB 4.9s  cuda0=1.3GiB ram=15.5GiB\n[server] weights  loaded, ctx=94208 images=off\n", 94208);
        CHECK(fits.has_value() && fits->verdict == Verdict::Fits);
        const auto refused = parseBasaltOutcome(
            "[server] ready    http://127.0.0.1:8092/v1\r\n[server] error: inkling2: spill plan: even with every expert in RAM the card is 516 MiB short (--max-context 131072)\r\n",
            131072);
        CHECK(refused.has_value() && refused->verdict == Verdict::Short && refused->shortfallMiB == 516);
        const auto bad = parseBasaltOutcome("[server] error: x.basalt: unknown argument: --kv-resident\n", 4096);
        CHECK(bad.has_value() && bad->verdict == Verdict::Failed);
        CHECK(!parseBasaltOutcome("[server] ready    http://127.0.0.1:8092/v1\n[server] planning weight allocation\n", 4096).has_value());
    }
    return finish();
}
