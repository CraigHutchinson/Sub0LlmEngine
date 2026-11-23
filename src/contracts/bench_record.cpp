#include "sub0llmengine/contracts/bench_record.hpp"

#include <simdjson.h>

#include <format>
#include <stdexcept>

namespace sub0llmengine::contracts
{
namespace
{

namespace od = simdjson::ondemand;

ContractError bad(std::string what)
{
    return ContractError{std::move(what)};
}

std::string str(od::value v)
{
    std::string_view s;
    if (v.get(s) != simdjson::SUCCESS)
    {
        throw std::runtime_error("expected a string");
    }
    return std::string{s};
}

std::int64_t integer(od::value v)
{
    std::int64_t n = 0;
    if (v.get(n) != simdjson::SUCCESS)
    {
        throw std::runtime_error("expected an integer");
    }
    return n;
}

double real(od::value v)
{
    double d = 0;
    if (v.get(d) != simdjson::SUCCESS)
    {
        throw std::runtime_error("expected a number");
    }
    return d;
}

bool isNull(od::value v)
{
    bool null = false;
    return v.is_null().get(null) == simdjson::SUCCESS && null;
}

ParamValue param(od::value v)
{
    od::json_type type{};
    if (v.type().get(type) != simdjson::SUCCESS)
    {
        throw std::runtime_error("unreadable parameter");
    }
    switch (type)
    {
    case od::json_type::boolean:
    {
        bool b = false;
        if (v.get(b) != simdjson::SUCCESS)
        {
            throw std::runtime_error("unreadable flag");
        }
        return b;
    }
    case od::json_type::string:
        return str(v);
    case od::json_type::number:
    {
        od::number_type kind{};
        if (v.get_number_type().get(kind) != simdjson::SUCCESS)
        {
            throw std::runtime_error("unreadable number");
        }
        if (kind == od::number_type::floating_point_number)
        {
            return real(v);
        }
        return integer(v);
    }
    default:
        throw std::runtime_error("a parameter must be a number, a flag or a string");
    }
}

Outcome outcomeOf(const std::string& s)
{
    if (s == "ok")
    {
        return Outcome::Ok;
    }
    if (s == "oom")
    {
        return Outcome::Oom;
    }
    if (s == "error")
    {
        return Outcome::Error;
    }
    throw std::runtime_error("unknown outcome '" + s + "'");
}

BenchRecord parse(std::string_view line)
{
    simdjson::padded_string padded{line};
    od::parser parser;
    od::document doc;
    if (parser.iterate(padded).get(doc) != simdjson::SUCCESS)
    {
        throw std::runtime_error("not valid JSON");
    }
    od::object obj;
    if (doc.get_object().get(obj) != simdjson::SUCCESS)
    {
        throw std::runtime_error("a bench record is a JSON object");
    }
    BenchRecord r;
    bool haveOutcome = false;
    for (auto field : obj)
    {
        std::string_view keyView;
        if (field.unescaped_key().get(keyView) != simdjson::SUCCESS)
        {
            throw std::runtime_error("unreadable key");
        }
        const std::string key{keyView};
        od::value v = field.value();
        if (key == "ts") r.ts = str(v);
        else if (key == "machine") r.machine = str(v);
        else if (key == "backend") r.backend = str(v);
        else if (key == "build") r.build = str(v);
        else if (key == "model") r.model = str(v);
        else if (key == "note") r.note = str(v);
        else if (key == "depth") r.depth = integer(v);
        else if (key == "ntg") r.ntg = integer(v);
        else if (key == "B") r.concurrency = integer(v);
        else if (key == "vramBaseMiB") r.vramBaseMiB = integer(v);
        else if (key == "peakVramMiB") { if (!isNull(v)) r.peakVramMiB = integer(v); }
        else if (key == "wallSec") { if (!isNull(v)) r.wallSec = real(v); }
        else if (key == "ppTps") { if (!isNull(v)) r.ppTps = real(v); }
        else if (key == "tgTps") { if (!isNull(v)) r.tgTps = real(v); }
        else if (key == "tgPerSeq") { if (!isNull(v)) r.tgPerSeq = real(v); }
        else if (key == "error") { if (!isNull(v)) r.error = str(v); }
        else if (key == "excluded") { if (!isNull(v)) r.excluded = str(v); }
        else if (key == "outcome") { r.outcome = outcomeOf(str(v)); haveOutcome = true; }
        else if (key == "params")
        {
            od::object params;
            if (v.get_object().get(params) != simdjson::SUCCESS)
            {
                throw std::runtime_error("params must be an object");
            }
            for (auto p : params)
            {
                std::string_view name;
                if (p.unescaped_key().get(name) != simdjson::SUCCESS)
                {
                    throw std::runtime_error("unreadable parameter name");
                }
                r.params.emplace(std::string{name}, param(p.value()));
            }
        }
        // Unknown fields are ignored: a contract gains fields without breaking readers (docs/DESIGN.md).
    }
    if (!haveOutcome)
    {
        throw std::runtime_error("no outcome");
    }
    return r;
}

void appendString(simdjson::builder::string_builder& sb, std::string_view key, std::string_view value)
{
    sb.escape_and_append_with_quotes(key);
    sb.append_colon();
    sb.escape_and_append_with_quotes(value);
}

template <typename Number>
void appendNumber(simdjson::builder::string_builder& sb, std::string_view key, Number value)
{
    sb.escape_and_append_with_quotes(key);
    sb.append_colon();
    sb.append(value);
}

void appendNull(simdjson::builder::string_builder& sb, std::string_view key)
{
    sb.escape_and_append_with_quotes(key);
    sb.append_colon();
    sb.append_null();
}

}  // namespace

std::string_view toString(Outcome outcome) noexcept
{
    switch (outcome)
    {
    case Outcome::Ok: return "ok";
    case Outcome::Oom: return "oom";
    case Outcome::Error: return "error";
    }
    return "error";
}

std::expected<BenchRecord, ContractError> parseBenchRecord(std::string_view jsonLine)
{
    try
    {
        return parse(jsonLine);
    }
    catch (const std::exception& e)
    {
        return std::unexpected(bad(e.what()));
    }
}

std::expected<std::vector<BenchRecord>, ContractError> parseBenchLines(std::string_view jsonl)
{
    std::vector<BenchRecord> out;
    std::size_t lineNo = 0;
    while (!jsonl.empty())
    {
        const auto end = jsonl.find('\n');
        std::string_view line = jsonl.substr(0, end);
        jsonl = end == std::string_view::npos ? std::string_view{} : jsonl.substr(end + 1);
        ++lineNo;
        while (!line.empty() && (line.back() == '\r' || line.back() == ' '))
        {
            line.remove_suffix(1);
        }
        if (line.empty())
        {
            continue;
        }
        auto record = parseBenchRecord(line);
        if (!record)
        {
            return std::unexpected(bad(std::format("line {}: {}", lineNo, record.error().message)));
        }
        out.push_back(std::move(*record));
    }
    return out;
}

std::string toJson(const BenchRecord& r)
{
    simdjson::builder::string_builder sb;
    sb.start_object();
    appendString(sb, "ts", r.ts);
    sb.append_comma();
    appendString(sb, "machine", r.machine);
    sb.append_comma();
    appendString(sb, "backend", r.backend);
    sb.append_comma();
    appendString(sb, "build", r.build);
    sb.append_comma();
    appendString(sb, "model", r.model);
    sb.append_comma();
    sb.escape_and_append_with_quotes("params");
    sb.append_colon();
    sb.start_object();
    bool first = true;
    for (const auto& [name, value] : r.params)
    {
        if (!first)
        {
            sb.append_comma();
        }
        first = false;
        sb.escape_and_append_with_quotes(name);
        sb.append_colon();
        if (const auto* i = std::get_if<std::int64_t>(&value)) sb.append(*i);
        else if (const auto* d = std::get_if<double>(&value)) sb.append(*d);
        else if (const auto* b = std::get_if<bool>(&value)) sb.append(*b);
        else sb.escape_and_append_with_quotes(std::get<std::string>(value));
    }
    sb.end_object();
    sb.append_comma();
    appendNumber(sb, "depth", r.depth);
    sb.append_comma();
    appendNumber(sb, "ntg", r.ntg);
    sb.append_comma();
    appendNumber(sb, "vramBaseMiB", r.vramBaseMiB);
    sb.append_comma();
    if (r.peakVramMiB) appendNumber(sb, "peakVramMiB", *r.peakVramMiB); else appendNull(sb, "peakVramMiB");
    sb.append_comma();
    if (r.wallSec) appendNumber(sb, "wallSec", *r.wallSec); else appendNull(sb, "wallSec");
    sb.append_comma();
    appendString(sb, "note", r.note);
    sb.append_comma();
    appendNumber(sb, "B", r.concurrency);
    sb.append_comma();
    appendString(sb, "outcome", toString(r.outcome));
    if (r.ppTps) { sb.append_comma(); appendNumber(sb, "ppTps", *r.ppTps); }
    if (r.tgTps) { sb.append_comma(); appendNumber(sb, "tgTps", *r.tgTps); }
    if (r.tgPerSeq) { sb.append_comma(); appendNumber(sb, "tgPerSeq", *r.tgPerSeq); }
    if (r.error) { sb.append_comma(); appendString(sb, "error", *r.error); }
    if (r.excluded) { sb.append_comma(); appendString(sb, "excluded", *r.excluded); }
    sb.end_object();
    return std::string{static_cast<std::string_view>(sb)};
}

}  // namespace sub0llmengine::contracts
