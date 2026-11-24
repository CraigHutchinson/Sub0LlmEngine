#pragma once
#include "sub0llmengine/contracts/native_backend_config.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace sub0llmengine::backends
{

/// `strata serve --profile <profile> --engine strata --host <host> --port <port> [--parallel <slots>]`, executable first. The profile is
/// native Strata JSON; its model, context and engine options stay in Strata's own configuration.
[[nodiscard]] std::vector<std::string> strataServerCommand(const contracts::StrataConfig& config);

/// `basalt serve --config <config>`, executable first. Basalt's config binds the port; the engine passes no overrides.
[[nodiscard]] std::vector<std::string> basaltServerCommand(const contracts::BasaltConfig& config);

/// What the engine decides when it serves a Basalt pack itself (no server config file): the pack, where it listens, and the levers the fit
/// search and the owner turn. Basalt reads the model name, sampling and tokenizer from the pack.
struct BasaltServe
{
    std::string bin;
    std::string pack;
    std::string alias;                       // the model name the API reports; empty: the pack's own
    std::string host = "127.0.0.1";
    std::uint16_t port = 8092;
    std::optional<std::int64_t> maxContext;  // total, shared by the slots (each gets an equal part)
    std::optional<std::int64_t> parallel;
    std::string kv;                          // fp8, fp16, ...; empty: the model's default
    std::vector<std::string> extra;          // further flags, in order, last (a lever step from the fit search)
};

/// `basalt serve --model <pack> ...`, executable first; only what is set is passed.
[[nodiscard]] std::vector<std::string> basaltPackCommand(const BasaltServe& serve);

/// A Windows batch launcher (.cmd or .bat) cannot be run directly: it goes through the command interpreter as
/// `<comspec> /d /c "<quoted command line>"`. Any other argv is returned unchanged. `windows` is the host, so the rule is testable anywhere.
[[nodiscard]] std::vector<std::string> wrapBatchLauncher(const std::vector<std::string>& argv, bool windows, const std::string& comspec);

/// One argument quoted the way the Windows C runtime reads it back (the rule of Python's subprocess.list2cmdline).
[[nodiscard]] std::string quoteWindowsArgument(const std::string& argument);

}  // namespace sub0llmengine::backends
