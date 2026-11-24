#include "sub0llmengine/backends/native_backends.hpp"

#include <algorithm>
#include <cctype>

namespace sub0llmengine::backends
{

std::vector<std::string> strataServerCommand(const contracts::StrataConfig& c)
{
    std::vector<std::string> argv{c.strataBin, "serve", "--profile", c.strataProfile, "--engine", "strata", "--host", c.host, "--port",
                                  std::to_string(c.port)};
    if (c.slots)
    {
        argv.emplace_back("--parallel");
        argv.push_back(std::to_string(*c.slots));
    }
    return argv;
}

std::vector<std::string> basaltServerCommand(const contracts::BasaltConfig& c)
{
    return {c.basaltBin, "serve", "--config", c.basaltConfig};
}

std::string quoteWindowsArgument(const std::string& arg)
{
    const bool needQuotes = arg.empty() || arg.find_first_of(" \t") != std::string::npos;
    std::string out;
    if (needQuotes)
    {
        out.push_back('"');
    }
    std::size_t backslashes = 0;
    for (const char ch : arg)
    {
        if (ch == '\\')
        {
            ++backslashes;
        }
        else if (ch == '"')
        {
            out.append(backslashes * 2 + 1, '\\');
            out.push_back('"');
            backslashes = 0;
        }
        else
        {
            out.append(backslashes, '\\');
            backslashes = 0;
            out.push_back(ch);
        }
    }
    out.append(backslashes, '\\');
    if (needQuotes)
    {
        out.append(backslashes, '\\');  // trailing backslashes are doubled before the closing quote
        out.push_back('"');
    }
    return out;
}

std::vector<std::string> wrapBatchLauncher(const std::vector<std::string>& argv, bool windows, const std::string& comspec)
{
    if (!windows || argv.empty())
    {
        return argv;
    }
    std::string exe = argv.front();
    std::transform(exe.begin(), exe.end(), exe.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const bool batch = exe.ends_with(".cmd") || exe.ends_with(".bat");
    if (!batch)
    {
        return argv;
    }
    std::string line;
    for (const auto& a : argv)
    {
        if (!line.empty())
        {
            line.push_back(' ');
        }
        line += quoteWindowsArgument(a);
    }
    return {comspec.empty() ? "cmd.exe" : comspec, "/d", "/c", line};
}

}  // namespace sub0llmengine::backends
