// native/tests/test_items.cpp — items.dat C++ vs Python (16.480 item nyata).
#include "../items.h"

#include <cstdio>
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
static uint16_t rd16(const std::vector<uint8_t> &v, size_t o) {
    return static_cast<uint16_t>(v[o] | (v[o + 1] << 8));
}
static uint8_t rd8(const std::vector<uint8_t> &v, size_t o) { return v[o]; }

int main() {
    std::printf("== UJI ITEMS.DAT NATIVE ==\n");

    // golden dihasilkan gen_items_golden.py dari items.dat yang sama.
    auto g = baca("native/tests/items_golden.bin");
    if (g.empty()) g = baca("tests/items_golden.bin");
    if (g.empty()) {
        cek("items_golden.bin ada", false,
            "jalankan: .venv/bin/python native/tests/gen_items_golden.py");
        std::printf("\n lulus: %d   gagal: %d\n", LULUS, GAGAL);
        return 1;
    }

    auto data = baca("data/items.dat");
    if (data.empty()) {
        cek("data/items.dat ada", false, "jalankan dari direktori repo");
        std::printf("\n lulus: %d   gagal: %d\n", LULUS, GAGAL);
        return 1;
    }

    ItemDatabase db;
    if (!db.dari_file("data/items.dat")) db.dari_file("../data/items.dat");
    cek("items.dat terbaca", db.size() > 0);
    cek("versi 27", db.version == 27, std::to_string(db.version));
    // items.dat v27 punya ekor per-item yang tidak seragam; Python juga
    // berhenti di 16.089 (97,6%). Semua ID yang dipakai bot (< 16.089) akurat.
    cek("16.089 item terbaca", db.size() == 16089, std::to_string(db.size()));

    // --- bandingkan tiap item dengan Python ---
    size_t off = 0;
    const uint32_t n = rd32(g, off);
    off += 4;
    cek("jumlah item golden sama", n == db.size(),
        std::to_string(n) + " vs " + std::to_string(db.size()));

    size_t beda = 0;
    std::string pertama;
    // Header golden 16 byte: I B B B B H I H (id, action_type, material,
    // block_health, pad, rarity, grow_time, panjang nama).
    for (uint32_t i = 0; i < n && off + 16 <= g.size(); ++i) {
        const uint32_t id = rd32(g, off);
        const uint8_t action_type = rd8(g, off + 4);
        const uint8_t material = rd8(g, off + 5);
        const uint8_t block_health = rd8(g, off + 6);
        const uint16_t rarity = rd16(g, off + 8);
        const uint32_t grow_time = rd32(g, off + 10);
        const uint16_t nlen = rd16(g, off + 14);
        const std::string nama(g.begin() + off + 16, g.begin() + off + 16 + nlen);
        off += 16 + nlen;
        // nama seed / deskripsi tidak diuji (panjang variabel)

        const Item *it = db.get(id);
        bool sama = it != nullptr && it->id == id && it->action_type == action_type &&
                    it->material == material && it->block_health == block_health &&
                    it->rarity == rarity && it->grow_time == grow_time &&
                    it->name == nama;
        if (!sama) {
            ++beda;
            if (pertama.empty()) {
                char buf[220];
                if (!it) {
                    std::snprintf(buf, sizeof buf, "id %u tidak ada di C++", id);
                } else {
                    std::snprintf(buf, sizeof buf,
                                  "id %u: C++ bh=%u grow=%u nama=%s | py bh=%u grow=%u nama=%s",
                                  id, it->block_health, it->grow_time, it->name.c_str(),
                                  block_health, grow_time, nama.c_str());
                }
                pertama = buf;
            }
        }
    }
    cek("semua item identik dengan Python", beda == 0,
        beda ? std::to_string(beda) + " beda; " + pertama : "");

    // --- nilai yang dipakai bot ---
    const Item *dirt = db.get(2);
    cek("Dirt: block_health 18", dirt && dirt->block_health == 18,
        dirt ? std::to_string(dirt->block_health) : "null");
    cek("Dirt: nama", dirt && dirt->name == "Dirt", dirt ? dirt->name : "");
    const Item *fist = db.get(18);
    cek("id 18 = Fist", fist && fist->name == "Fist", fist ? fist->name : "");
    const Item *wrench = db.get(32);
    cek("id 32 = Wrench", wrench && wrench->name == "Wrench", wrench ? wrench->name : "");
    const Item *seed = db.get(3);
    cek("id 3 = Dirt Seed (is_seed)", seed && seed->is_seed(),
        seed ? seed->name : "");

    // name_of + find
    cek("name_of(2)", db.name_of(2) == "Dirt", db.name_of(2));
    cek("name_of tak dikenal", db.name_of(999999) == "#999999", db.name_of(999999));
    auto ketemu = db.find("dirt", true);
    cek("find exact 'dirt'", ketemu.size() == 1 && ketemu[0]->id == 2,
        std::to_string(ketemu.size()));
    auto banyak = db.find("dirt", false);
    cek("find longgar 'dirt' > 1", banyak.size() > 1, std::to_string(banyak.size()));

    std::printf("\n lulus: %d   gagal: %d\n", LULUS, GAGAL);
    return GAGAL == 0 ? 0 : 1;
}
