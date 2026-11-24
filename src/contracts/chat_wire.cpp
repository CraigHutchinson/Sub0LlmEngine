#include "sub0llmengine/contracts/chat_wire.hpp"

#include "json_fields.hpp"

#include <simdjson.h>

namespace sub0llmengine::contracts
{

std::string toJson(const ChatRequest& request)
{
    simdjson::builder::string_builder sb;
    sb.start_object();
    sb.escape_and_append_with_quotes("model");
    sb.append_colon();
    sb.escape_and_append_with_quotes(request.model);
    sb.append_comma();
    sb.escape_and_append_with_quotes("messages");
    sb.append_colon();
    sb.start_array();
    sb.start_object();
    sb.escape_and_append_with_quotes("role");
    sb.append_colon();
    sb.escape_and_append_with_quotes("user");
    sb.append_comma();
    sb.escape_and_append_with_quotes("content");
    sb.append_colon();
    sb.escape_and_append_with_quotes(request.prompt);
    sb.end_object();
    sb.end_array();
    sb.append_comma();
    sb.escape_and_append_with_quotes("max_tokens");
    sb.append_colon();
    sb.append(request.maxTokens);
    sb.append_comma();
    sb.escape_and_append_with_quotes("temperature");
    sb.append_colon();
    sb.append(std::int64_t{0});
    if (request.reasoningEffort)
    {
        sb.append_comma();
        sb.escape_and_append_with_quotes("reasoning_effort");
        sb.append_colon();
        sb.escape_and_append_with_quotes(*request.reasoningEffort);
    }
    sb.end_object();
    std::string_view view;
    if (sb.view().get(view) != simdjson::SUCCESS)
    {
        return {};
    }
    return std::string{view};
}

std::expected<ChatUsage, ContractError> parseChatUsage(std::string_view jsonText)
{
    try
    {
        namespace od = simdjson::ondemand;
        simdjson::padded_string padded{jsonText};
        od::parser parser;
        od::document doc;
        od::object root;
        if (parser.iterate(padded).get(doc) != simdjson::SUCCESS || doc.get_object().get(root) != simdjson::SUCCESS)
        {
            throw std::runtime_error("the reply is not a JSON object");
        }
        od::object usage;
        if (root["usage"].get_object().get(usage) != simdjson::SUCCESS)
        {
            throw std::runtime_error("the reply has no usage");
        }
        ChatUsage out;
        od::value value;
        if (usage["prompt_tokens"].get(value) != simdjson::SUCCESS) throw std::runtime_error("usage has no prompt_tokens");
        out.promptTokens = json::integer(value, "prompt_tokens");
        if (usage["completion_tokens"].get(value) != simdjson::SUCCESS) throw std::runtime_error("usage has no completion_tokens");
        out.completionTokens = json::integer(value, "completion_tokens");
        return out;
    }
    catch (const std::exception& e)
    {
        return std::unexpected(ContractError{e.what()});
    }
}

}  // namespace sub0llmengine::contracts
