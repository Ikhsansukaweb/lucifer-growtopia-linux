#include "http.h"

#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace lucifer {

std::string jesc(const std::string &s) {
    std::string o;
    o.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default:
                if (c < 0x20) {
                    char b[8];
                    std::snprintf(b, sizeof b, "\\u%04x", c);
                    o += b;
                } else {
                    o += static_cast<char>(c);
                }
        }
    }
    return o;
}

std::string Http::dechunk(const std::string &in) {
    std::string out;
    size_t i = 0;
    while (i < in.size()) {
        size_t eol = in.find("\r\n", i);
        if (eol == std::string::npos) break;
        long len = std::strtol(in.c_str() + i, nullptr, 16);
        if (len <= 0) break;
        i = eol + 2;
        if (i + static_cast<size_t>(len) > in.size()) break;
        out.append(in, i, static_cast<size_t>(len));
        i += static_cast<size_t>(len) + 2;
    }
    return out.empty() ? in : out;
}

Resp Http::call(const std::string &method, const std::string &path,
                const std::string &body) {
    Resp out;
    std::string host = "127.0.0.1";
    int port = 8787;

    std::string hp = base_;
    const std::string scheme = "http://";
    if (hp.rfind(scheme, 0) == 0) hp = hp.substr(scheme.size());
    auto slash = hp.find('/');
    if (slash != std::string::npos) hp = hp.substr(0, slash);
    auto colon = hp.rfind(':');
    if (colon != std::string::npos) {
        host = hp.substr(0, colon);
        port = std::atoi(hp.c_str() + colon + 1);
    } else if (!hp.empty()) {
        host = hp;
    }

    addrinfo hints{};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo *res = nullptr;
    const std::string port_s = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_s.c_str(), &hints, &res) != 0) return out;

    int fd = -1;
    for (addrinfo *p = res; p; p = p->ai_next) {
        fd = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (fd < 0) continue;
        if (::connect(fd, p->ai_addr, p->ai_addrlen) == 0) break;
        ::close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    if (fd < 0) return out;

    std::string req = method + " " + path + " HTTP/1.1\r\n";
    req += "Host: " + host + ":" + port_s + "\r\n";
    req += "Connection: close\r\n";
    req += "Accept: application/json\r\n";
    if (!body.empty() || method == "POST") {
        req += "Content-Type: application/json\r\n";
        req += "Content-Length: " + std::to_string(body.size()) + "\r\n";
    }
    req += "\r\n";
    req += body;

    size_t sent = 0;
    while (sent < req.size()) {
        ssize_t n = ::send(fd, req.data() + sent, req.size() - sent, MSG_NOSIGNAL);
        if (n <= 0) break;
        sent += static_cast<size_t>(n);
    }

    std::string raw;
    char buf[16384];
    for (;;) {
        ssize_t n = ::recv(fd, buf, sizeof buf, 0);
        if (n <= 0) break;
        raw.append(buf, static_cast<size_t>(n));
        if (raw.size() > (32u << 20)) break;
    }
    ::close(fd);

    auto hdr_end = raw.find("\r\n\r\n");
    if (hdr_end == std::string::npos) return out;
    std::sscanf(raw.c_str(), "HTTP/%*d.%*d %d", &out.status);
    std::string head = raw.substr(0, hdr_end);
    out.body = raw.substr(hdr_end + 4);
    if (head.find("chunked") != std::string::npos) out.body = dechunk(out.body);
    return out;
}

}  // namespace lucifer
