// lucifer/http.h — klien HTTP loopback minimal (tanpa TLS, tanpa dependensi luar).
#pragma once

#include <string>

namespace lucifer {

struct Resp {
    int status = 0;
    std::string body;
    bool ok() const { return status >= 200 && status < 300; }
};

class Http {
public:
    explicit Http(std::string base) : base_(std::move(base)) {}

    Resp get(const std::string &path) { return call("GET", path, ""); }
    Resp post(const std::string &path, const std::string &json) {
        return call("POST", path, json);
    }

    const std::string &base() const { return base_; }

private:
    Resp call(const std::string &method, const std::string &path,
              const std::string &body);
    static std::string dechunk(const std::string &in);

    std::string base_;
};

// Escape isi string supaya aman ditempel ke badan JSON.
std::string jesc(const std::string &s);

}  // namespace lucifer
