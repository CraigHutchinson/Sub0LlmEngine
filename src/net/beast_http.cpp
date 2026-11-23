#include "sub0llmengine/net/http.hpp"

#include <boost/asio.hpp>
#include <boost/beast.hpp>

#include <exception>
#include <thread>

namespace sub0llmengine::net
{
namespace
{

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
using tcp = asio::ip::tcp;

NetError fail(const std::string& what, const std::exception& e)
{
    return NetError{what + ": " + e.what()};
}

class BeastClient final : public IHttpClient
{
public:
    std::expected<HttpResponse, NetError> send(std::string_view host, std::uint16_t port, const HttpRequest& request,
                                               std::chrono::milliseconds timeout) override
    {
        try
        {
            asio::io_context io;
            beast::tcp_stream stream{io};
            stream.expires_after(timeout);
            stream.connect(tcp::endpoint{asio::ip::make_address(std::string{host}), port});

            http::request<http::string_body> req{http::string_to_verb(request.method), request.target, 11};
            req.set(http::field::host, std::string{host});
            req.set(http::field::connection, "close");
            for (const auto& [name, value] : request.headers)
            {
                req.set(name, value);
            }
            req.body() = request.body;
            req.prepare_payload();
            http::write(stream, req);

            beast::flat_buffer buffer;
            http::response<http::string_body> res;
            http::read(stream, buffer, res);
            beast::error_code ignored;
            stream.socket().shutdown(tcp::socket::shutdown_both, ignored);

            HttpResponse out;
            out.status = static_cast<int>(res.result_int());
            for (const auto& field : res)
            {
                out.headers.emplace_back(std::string{field.name_string()}, std::string{field.value()});
            }
            out.body = std::move(res.body());
            return out;
        }
        catch (const std::exception& e)
        {
            return std::unexpected(fail("http request to " + std::string{host} + ":" + std::to_string(port) + " failed", e));
        }
    }
};

class BeastFront final : public IHttpFront
{
public:
    ~BeastFront() override { stop(); }

    std::expected<std::uint16_t, NetError> start(std::string_view host, std::uint16_t port, HttpHandler handler) override
    {
        if (thread_.joinable())
        {
            return std::unexpected(NetError{"the http front is already running"});
        }
        try
        {
            handler_ = std::move(handler);
            acceptor_ = std::make_unique<tcp::acceptor>(io_, tcp::endpoint{asio::ip::make_address(std::string{host}), port});
            const auto bound = acceptor_->local_endpoint().port();
            thread_ = std::thread{[this] { run(); }};
            return bound;
        }
        catch (const std::exception& e)
        {
            acceptor_.reset();
            return std::unexpected(fail("cannot listen on " + std::string{host} + ":" + std::to_string(port), e));
        }
    }

    void stop() noexcept override
    {
        if (!thread_.joinable())
        {
            return;
        }
        // Closing from another thread does not wake a blocking accept on POSIX, so the front accepts asynchronously: the close is
        // posted onto the io thread, which then runs out of work and returns.
        asio::post(io_, [this] {
            beast::error_code ignored;
            acceptor_->close(ignored);
        });
        thread_.join();
        acceptor_.reset();
        io_.restart();
    }

private:
    void run()
    {
        accept();
        io_.run();
    }

    /// One request at a time on the io thread: a handler is short by contract (http.hpp), and a second client waits in the backlog.
    void accept()
    {
        acceptor_->async_accept([this](beast::error_code ec, tcp::socket socket) {
            if (!ec)
            {
                serve(socket);
            }
            if (acceptor_->is_open())
            {
                accept();
            }
        });
    }

    void serve(tcp::socket& socket) noexcept
    {
        beast::error_code ec;
        beast::flat_buffer buffer;
        http::request<http::string_body> req;
        http::read(socket, buffer, req, ec);
        if (ec)
        {
            return;
        }
        HttpRequest in;
        in.method = std::string{req.method_string()};
        in.target = std::string{req.target()};
        for (const auto& field : req)
        {
            in.headers.emplace_back(std::string{field.name_string()}, std::string{field.value()});
        }
        in.body = std::move(req.body());

        HttpResponse out;
        try
        {
            out = handler_(in);
        }
        catch (...)
        {
            out = HttpResponse{500, {}, "internal error"};
        }
        http::response<http::string_body> res{static_cast<http::status>(out.status), req.version()};
        for (const auto& [name, value] : out.headers)
        {
            res.set(name, value);
        }
        res.set(http::field::connection, "close");
        res.body() = std::move(out.body);
        res.prepare_payload();
        http::write(socket, res, ec);
        socket.shutdown(tcp::socket::shutdown_send, ec);
    }

    asio::io_context io_;
    std::unique_ptr<tcp::acceptor> acceptor_;
    HttpHandler handler_;
    std::thread thread_;
};

}  // namespace

std::unique_ptr<IHttpClient> makeHttpClient()
{
    return std::make_unique<BeastClient>();
}

std::unique_ptr<IHttpFront> makeHttpFront()
{
    return std::make_unique<BeastFront>();
}

}  // namespace sub0llmengine::net
