#pragma once
#include "sub0llmengine/contracts/native_backend_config.hpp"

#include <string>
#include <vector>

namespace sub0llmengine::backends
{

/// `strata serve --profile <profile> --engine strata --host <host> --port <port> [--parallel <slots>]`, executable first. The profile is
/// native Strata JSON; its model, context and engine options stay in Strata's own configuration.
[[nodiscard]] std::vector<std::string> strataServerCommand(const contracts::StrataConfig& config);

/// `basalt serve --config <config>`, executable first. Basalt's config binds the port; the engine passes no overrides.
[[nodiscard]] std::vector<std::string> basaltServerCommand(const contracts::BasaltConfig& config);

/// A Windows batch launcher (.cmd or .bat) cannot be run directly: it goes through the command interpreter as
/// `<comspec> /d /c "<quoted command line>"`. Any other argv is returned unchanged. `windows` is the host, so the rule is testable anywhere.
[[nodiscard]] std::vector<std::string> wrapBatchLauncher(const std::vector<std::string>& argv, bool windows, const std::string& comspec);

/// One argument quoted the way the Windows C runtime reads it back (the rule of Python's subprocess.list2cmdline).
[[nodiscard]] std::string quoteWindowsArgument(const std::string& argument);

}  // namespace sub0llmengine::backends
