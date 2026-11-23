// The net layer's client and front talk to each other on loopback: a POST is echoed reversed with a header, an unknown path gets 404, and a
// handler that throws becomes a 500 instead of killing the front.
#include "check.hpp"
#include "sub0llmengine/net/http.hpp"

#include <algorithm>
#include <chrono>

int main()
{
    using namespace sub0llmengine::net;
    auto front = makeHttpFront();
    auto started = front->start("127.0.0.1", 0, [](const HttpRequest& req) {
        if (req.target == "/boom")
        {
            throw 1;
        }
        if (req.target != "/echo")
        {
            return HttpResponse{404, {}, "no such path"};
        }
        std::string body = req.body;
        std::reverse(body.begin(), body.end());
        return HttpResponse{200, {{"X-Method", req.method}, {"Content-Type", "text/plain"}}, body};
    });
    CHECK(started.has_value());
    if (!started)
    {
        return finish();
    }
    auto client = makeHttpClient();
    const auto timeout = std::chrono::seconds{5};

    auto echo = client->send("127.0.0.1", *started, HttpRequest{"POST", "/echo", {}, "abc123"}, timeout);
    CHECK(echo.has_value());
    if (echo)
    {
        CHECK_EQ(echo->status, 200);
        CHECK_EQ(echo->body, std::string{"321cba"});
        const bool hasMethod = std::any_of(echo->headers.begin(), echo->headers.end(),
                                           [](const auto& h) { return h.first == "X-Method" && h.second == "POST"; });
        CHECK(hasMethod);
    }
    auto missing = client->send("127.0.0.1", *started, HttpRequest{"GET", "/nope", {}, ""}, timeout);
    CHECK(missing.has_value() && missing->status == 404);
    auto boom = client->send("127.0.0.1", *started, HttpRequest{"GET", "/boom", {}, ""}, timeout);
    CHECK(boom.has_value() && boom->status == 500);
    auto again = client->send("127.0.0.1", *started, HttpRequest{"POST", "/echo", {}, "xy"}, timeout);
    CHECK(again.has_value() && again->body == "yx");

    front->stop();
    front->stop();  // safe twice
    auto refused = client->send("127.0.0.1", *started, HttpRequest{}, std::chrono::seconds{2});
    CHECK(!refused.has_value());
    return finish();
}
