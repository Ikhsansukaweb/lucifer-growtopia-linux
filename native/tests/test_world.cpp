// native/tests/test_world.cpp — parser dunia C++ vs golden Python.
//
// golden dihasilkan dari dump SendMapData ASLI (server Growtopia), jadi uji ini
// membuktikan port-nya benar pada data nyata, bukan data buatan.
#include "../world.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

using namespace lucifer;

static int LULUS = 0;
static int GAGAL = 0;

static void cek(const char *nama, bool kondisi, const std::string &info = "") {
    if (kondisi) {
        ++LULUS;
        std::printf("  \u2713 %s%s%s\n", nama, info.empty() ? "" : "  ",
                    info.empty() ? "" : info.c_str());
    } else {
        ++GAGAL;
        std::printf("  \u2717 %s  %s\n", nama, info.c_str());
    }
}

static std::vector<uint8_t> baca(const char *path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return {};
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)),
                                std::istreambuf_iterator<char>());
}

static uint32_t rd32(const std::vector<uint8_t> &v, size_t o) {
    return static_cast<uint32_t>(v[o]) | (static_cast<uint32_t>(v[o + 1]) << 8) |
           (static_cast<uint32_t>(v[o + 2]) << 16) |
           (static_cast<uint32_t>(v[o + 3]) << 24);
}
static int32_t rd_i32(const std::vector<uint8_t> &v, size_t o) {
    return static_cast<int32_t>(rd32(v, o));
}
static uint16_t rd16(const std::vector<uint8_t> &v, size_t o) {
    return static_cast<uint16_t>(v[o] | (v[o + 1] << 8));
}

int main() {
    std::printf("== UJI PARSER DUNIA NATIVE ==\n");

    auto g = baca("native/tests/world_golden.bin");
    if (g.empty()) g = baca("tests/world_golden.bin");
    if (g.empty()) {
        cek("world_golden.bin ada", false,
            "jalankan: .venv/bin/python native/tests/gen_world_golden.py");
        std::printf("\n lulus: %d   gagal: %d\n", LULUS, GAGAL);
        return 1;
    }

    // --- payload SendMapData mentah ---
    size_t off = 0;
    const uint32_t n_payload = rd32(g, off);
    off += 4;
    const uint8_t *payload = g.data() + off;
    off += n_payload;

    World w = parse_world(payload, n_payload);
    cek("parse tanpa error", w.error.empty(), w.error);
    cek("versi >= 25", w.version >= 25, std::to_string(w.version));
    cek("nama dunia", w.name == "ISANLUCUUU", w.name);
    cek("ukuran 100x60", w.width == 100 && w.height == 60,
        std::to_string(w.width) + "x" + std::to_string(w.height));
    cek("6000 tile", w.tiles.size() == 6000, std::to_string(w.tiles.size()));
    cek("last_uid 77", w.last_uid == 77, std::to_string(w.last_uid));

    // --- bandingkan isi tiap tile dengan hasil Python ---
    const uint32_t n_tile = rd32(g, off);
    off += 4;
    cek("jumlah tile sama dengan Python", n_tile == w.tiles.size(),
        std::to_string(n_tile) + " vs " + std::to_string(w.tiles.size()));

    size_t beda_tile = 0;
    std::string tile_pertama_beda;
    for (uint32_t i = 0; i < n_tile && off + 15 <= g.size(); ++i) {
        const int32_t x = rd_i32(g, off);
        const int32_t y = rd_i32(g, off + 4);
        const uint16_t fg = rd16(g, off + 8);
        const uint16_t bg = rd16(g, off + 10);
        const uint16_t flags = rd16(g, off + 12);
        const uint8_t extra = g[off + 14];
        off += 15;

        const Tile *t = w.tile(x, y);
        bool sama = t != nullptr && t->x == x && t->y == y && t->fg == fg &&
                    t->bg == bg && t->flags == flags && t->extra_type == extra;
        if (!sama) {
            ++beda_tile;
            if (tile_pertama_beda.empty()) {
                char buf[160];
                if (t == nullptr) {
                    std::snprintf(buf, sizeof buf, "tile (%d,%d) null di C++", x, y);
                } else {
                    std::snprintf(buf, sizeof buf,
                                  "tile (%d,%d): C++ fg=%u bg=%u fl=0x%04x ex=%u | "
                                  "py fg=%u bg=%u fl=0x%04x ex=%u",
                                  x, y, t->fg, t->bg, t->flags, t->extra_type, fg, bg,
                                  flags, extra);
                }
                tile_pertama_beda = buf;
            }
        }
    }
    cek("semua tile identik dengan Python", beda_tile == 0,
        beda_tile ? std::to_string(beda_tile) + " beda; " + tile_pertama_beda : "");

    // --- dropped item ---
    const uint32_t n_drop = rd32(g, off);
    off += 4;
    cek("jumlah objek jatuh sama", n_drop == w.dropped.size(),
        std::to_string(n_drop) + " vs " + std::to_string(w.dropped.size()));
    size_t beda_drop = 0;
    for (uint32_t i = 0; i < n_drop && off + 15 <= g.size(); ++i) {
        const uint16_t id = rd16(g, off);
        float fx, fy;
        std::memcpy(&fx, g.data() + off + 2, 4);
        std::memcpy(&fy, g.data() + off + 6, 4);
        const uint8_t count = g[off + 10];
        const uint32_t uid = rd32(g, off + 11);
        off += 15;

        const DroppedItem &d = w.dropped[i];
        if (d.item_id != id || d.x != fx || d.y != fy || d.count != count || d.uid != uid) {
            ++beda_drop;
        }
    }
    cek("semua objek jatuh identik", beda_drop == 0, std::to_string(beda_drop) + " beda");

    // --- helper World ---
    const Tile *t0 = w.tile(0, 0);
    cek("tile(0,0) ada", t0 != nullptr);
    cek("tile di luar batas = null", w.tile(-1, 0) == nullptr && w.tile(100, 0) == nullptr);
    cek("index_of", w.index_of(5, 2) == 205, std::to_string(w.index_of(5, 2)));

    // update_tile mengubah isi
    Tile ubah;
    ubah.x = 3;
    ubah.y = 3;
    ubah.bg = 14;
    w.update_tile(w.index_of(3, 3), ubah);
    const Tile *t3 = w.tile(3, 3);
    cek("update_tile bekerja", t3 != nullptr && t3->fg == 0 && t3->bg == 14);

    // --- parse_tile_updates (type 6) dengan data buatan ---
    // Dua tile: (10,20) fg=0 bg=52 ; (11,21) fg=2 bg=52 ; penutup 0xFFFFFFFF
    std::vector<uint8_t> up;
    auto tulis32 = [&up](uint32_t v) {
        up.push_back(static_cast<uint8_t>(v & 0xFF));
        up.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
        up.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
        up.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
    };
    auto tulis16 = [&up](uint16_t v) {
        up.push_back(static_cast<uint8_t>(v & 0xFF));
        up.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    };
    tulis32(10); tulis32(20); tulis16(0); tulis16(52); tulis16(0); tulis16(0);
    tulis32(11); tulis32(21); tulis16(2); tulis16(52); tulis16(0); tulis16(0);
    tulis32(0xFFFFFFFF);

    auto hasil = parse_tile_updates(up.data(), up.size());
    cek("type 6: dua tile terbaca", hasil.size() == 2, std::to_string(hasil.size()));
    if (hasil.size() == 2) {
        cek("type 6: tile pertama", hasil[0].x == 10 && hasil[0].y == 20 &&
                                       hasil[0].fg == 0 && hasil[0].bg == 52);
        cek("type 6: tile kedua", hasil[1].x == 11 && hasil[1].y == 21 &&
                                     hasil[1].fg == 2 && hasil[1].bg == 52);
    }

    // Data terpotong: tidak boleh crash, hanya berhenti.
    auto potong = parse_tile_updates(up.data(), 12);
    cek("type 6 data terpotong tidak crash", potong.size() <= 2,
        std::to_string(potong.size()));

    std::printf("\n lulus: %d   gagal: %d\n", LULUS, GAGAL);
    return GAGAL == 0 ? 0 : 1;
}
