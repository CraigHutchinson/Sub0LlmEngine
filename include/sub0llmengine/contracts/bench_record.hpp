#pragma once
#include <cstdint>
#include <expected>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace sub0llmengine::contracts
{

/// A contract error: a sentence for a person, with the line number when a file is being read.
struct ContractError
{
    std::string message;
};

/// One backend knob as the bench recorded it (an integer, a real, a flag or a name).
using ParamValue = std::variant<std::int64_t, double, bool, std::string>;
using Params = std::map<std::string, ParamValue>;

enum class Outcome
{
    Ok,
    Oom,
    Error,
};

[[nodiscard]] std::string_view toString(Outcome outcome) noexcept;

/// One measured point: a configuration (params) at a prompt depth and concurrency, with its outcome. The record in
/// bench/<machine>.jsonl, one JSON object per line; Python's bench.py writes the same fields (docs/DESIGN.md "Contracts").
struct BenchRecord
{
    std::string ts;
    std::string machine;
    std::string backend = "llamacpp";  // absent in the oldest records
    std::string build;
    std::string model;
    Params params;
    std::int64_t depth = 0;
    std::int64_t ntg = 0;
    std::int64_t concurrency = 0;  // "B" in the file
    std::int64_t vramBaseMiB = 0;
    std::optional<std::int64_t> peakVramMiB;
    std::optional<double> wallSec;
    std::string note;
    Outcome outcome = Outcome::Ok;
    std::optional<double> ppTps;
    std::optional<double> tgTps;
    std::optional<double> tgPerSeq;
    std::optional<std::string> error;
    std::optional<std::string> excluded;  // why a point is left out of rankings
};

[[nodiscard]] std::expected<BenchRecord, ContractError> parseBenchRecord(std::string_view jsonLine);

/// Every non-empty line of a bench JSONL file; stops at the first bad line, naming it.
[[nodiscard]] std::expected<std::vector<BenchRecord>, ContractError> parseBenchLines(std::string_view jsonl);

/// One JSON object on one line, no trailing newline. Fields in the order the file uses; absent optionals are written as null where the
/// file writes null (peakVramMiB, wallSec) and left out elsewhere.
[[nodiscard]] std::string toJson(const BenchRecord& record);

}  // namespace sub0llmengine::contracts
