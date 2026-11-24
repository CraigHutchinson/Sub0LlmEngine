// A stand-in for a backend server, used by the supervision tests: answers /health with 503 while "loading" and 200 afterwards, and /v1/models.
//   fake_server --port N [--loading-ms M] [--exit-after-ms E]
// It runs until it is stopped; --exit-after-ms makes it exit by itself with code 3 (a crash during start-up).
#include "sub0llmengine/net/http.hpp"

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <thread>

int main(int argc, char** argv)
{
    using namespace sub0llmengine::net;
    std::uint16_t port = 0;
    long loadingMs = 0;
    long exitAfterMs = -1;
    for (int i = 1; i + 1 < argc; i += 2)
    {
        if (!std::strcmp(argv[i], "--port")) port = static_cast<std::uint16_t>(std::atoi(argv[i + 1]));
        else if (!std::strcmp(argv[i], "--loading-ms")) loadingMs = std::atol(argv[i + 1]);
        else if (!std::strcmp(argv[i], "--exit-after-ms")) exitAfterMs = std::atol(argv[i + 1]);
    }
    const auto started = std::chrono::steady_clock::now();
    auto front = makeHttpFront();
    auto bound = front->start("127.0.0.1", port, [&](const HttpRequest& req) {
        const bool loaded = std::chrono::steady_clock::now() - started >= std::chrono::milliseconds{loadingMs};
        if (req.target == "/health")
        {
            return loaded ? HttpResponse{200, {}, "{\"status\":\"ok\"}"} : HttpResponse{503, {}, "{\"error\":\"Loading model\"}"};
        }
        if (req.target == "/v1/models" && loaded)
        {
            return HttpResponse{200, {}, "{\"data\":[{\"id\":\"fake\"}]}"};
        }
        return HttpResponse{404, {}, ""};
    });
    if (!bound)
    {
        return 2;
    }
    for (;;)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds{50});
        if (exitAfterMs >= 0 && std::chrono::steady_clock::now() - started >= std::chrono::milliseconds{exitAfterMs})
        {
            return 3;
        }
    }
}
