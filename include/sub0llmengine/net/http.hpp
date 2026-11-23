#pragma once
#include <chrono>
#include <cstdint>
#include <expected>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sub0llmengine::net
{

/// The net layer's one error type: a sentence for a person.
struct NetError
{
    std::string message;
};

using Headers = std::vector<std::pair<std::string, std::string>>;

struct HttpRequest
{
    std::string method = "GET";
    std::string target = "/";
    Headers headers;
    std::string body;
};

struct HttpResponse
{
    int status = 200;
    Headers headers;
    std::string body;
};

/// Called once per request, on the front's thread: keep it short, and never throw out of it.
using HttpHandler = std::function<HttpResponse(const HttpRequest&)>;

/// A client for one request at a time to a server on this machine or the network. No Boost type appears here: the seam
/// (docs/SERVICE.md) lets the transport change (HTTP/2 later) without touching a caller.
class IHttpClient
{
public:
    virtual ~IHttpClient() = default;
    [[nodiscard]] virtual std::expected<HttpResponse, NetError> send(std::string_view host, std::uint16_t port, const HttpRequest& request,
                                                                     std::chrono::milliseconds timeout) = 0;
};

/// A server that answers every request through one handler. Bind only addresses on this machine unless the owner says otherwise.
class IHttpFront
{
public:
    virtual ~IHttpFront() = default;
    /// Starts listening (port 0 picks a free one) and returns the port actually bound.
    [[nodiscard]] virtual std::expected<std::uint16_t, NetError> start(std::string_view host, std::uint16_t port, HttpHandler handler) = 0;
    /// Stops accepting, finishes the request in progress and joins the thread. Safe to call twice.
    virtual void stop() noexcept = 0;
};

[[nodiscard]] std::unique_ptr<IHttpClient> makeHttpClient();
[[nodiscard]] std::unique_ptr<IHttpFront> makeHttpFront();

}  // namespace sub0llmengine::net
