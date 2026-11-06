// lucifer/items.cpp — port 1:1 dari lucifer/items.py
//
// items.dat v27 (16.480 item). Struktur per item bergantung versi; field yang
// muncul di versi lebih baru dibaca berurutan setelah blok tetap.
#include "items.h"

#include <algorithm>
#include <cstring>
#include <fstream>

namespace lucifer {
namespace {

struct R {
    const uint8_t *buf;
    size_t len;
    size_t pos = 0;
    bool gagal = false;

    R(const uint8_t *b, size_t n) : buf(b), len(n) {}
    bool cukup(size_t n) const { return pos + n <= len; }

    uint8_t u8() {
        if (!cukup(1)) { gagal = true; return 0; }
        return buf[pos++];
    }
    uint16_t u16() {
        if (!cukup(2)) { gagal = true; return 0; }
        const uint16_t v = static_cast<uint16_t>(buf[pos] | (buf[pos + 1] << 8));
        pos += 2;
        return v;
    }
    uint32_t u32() {
        if (!cukup(4)) { gagal = true; return 0; }
        const uint32_t v = static_cast<uint32_t>(buf[pos]) |
                           (static_cast<uint32_t>(buf[pos + 1]) << 8) |
                           (static_cast<uint32_t>(buf[pos + 2]) << 16) |
                           (static_cast<uint32_t>(buf[pos + 3]) << 24);
        pos += 4;
        return v;
    }
    void skip(size_t n) {
        if (!cukup(n)) { gagal = true; pos = len; return; }
        pos += n;
    }
    // String panjang-u16, byte mentah (latin-1, bukan utf-8 ketat).
    std::string string() {
        const uint16_t n = u16();
        if (!cukup(n)) { gagal = true; pos = len; return {}; }
        std::string s(reinterpret_cast<const char *>(buf + pos), n);
        pos += n;
        return s;
    }
    std::string cypher_string(uint32_t item_id) {
        const uint16_t n = u16();
        if (!cukup(n)) { gagal = true; pos = len; return {}; }
        std::string s = decode_item_name(buf + pos, n, item_id);
        pos += n;
        return s;
    }
};

Item read_item(R &r, uint16_t version) {
    Item it;
    it.id = r.u32();
    it.flags = r.u16();
    it.action_type = r.u8();
    it.material = r.u8();
    it.name = r.cypher_string(it.id);
    it.texture_file_name = r.string();
    it.texture_hash = r.u32();
    it.visual_effect = r.u8();
    it.cooking_ingredient = r.u32();
    it.texture_x = r.u8();
    it.texture_y = r.u8();
    it.render_type = r.u8();
    it.is_stripey_wallpaper = r.u8();
    it.collision_type = r.u8();
    it.block_health = r.u8();
    it.drop_chance = r.u32();
    it.clothing_type = r.u8();
    it.rarity = r.u16();
    it.max_item = r.u8();
    it.file_name = r.string();
    it.file_hash = r.u32();
    r.u32();  // audio_volume
    it.pet_name = r.string();
    it.pet_prefix = r.string();
    it.pet_suffix = r.string();
    it.pet_ability = r.string();
    it.seed_base_sprite = r.u8();
    it.seed_overlay_sprite = r.u8();
    it.tree_base_sprite = r.u8();
    it.tree_overlay_sprite = r.u8();
    it.base_color = r.u32();
    it.overlay_color = r.u32();
    it.ingredient = r.u32();
    it.grow_time = r.u32();
    r.u16();
    r.u16();  // is_rayman
    it.extra_options = r.string();
    it.texture_path_2 = r.string();
    it.extra_option2 = r.string();
    r.skip(80);

    if (version >= 11) it.punch_option = r.string();
    if (version >= 12) r.skip(13);
    if (version >= 13) r.skip(4);
    if (version >= 14) r.skip(4);
    if (version >= 15) {
        r.skip(25);
        r.string();
    }
    if (version >= 16) r.string();
    if (version >= 17) r.skip(4);
    if (version >= 18) r.skip(4);
    if (version >= 19) r.skip(9);
    if (version >= 21) r.skip(2);
    if (version >= 22) it.description = r.string();
    if (version >= 23) r.skip(4);
    if (version >= 24) r.skip(1);
    return it;
}

}  // namespace

bool Item::is_seed() const {
    return action_type == 19 || (name.size() >= 5 &&
                                 name.compare(name.size() - 5, 5, " Seed") == 0);
}

std::string decode_item_name(const uint8_t *raw, size_t len, uint32_t item_id) {
    const std::string key = ITEM_NAME_SECRET;
    const size_t klen = key.size();
    std::string out;
    out.resize(len);
    for (size_t i = 0; i < len; ++i) {
        out[i] = static_cast<char>(raw[i] ^ static_cast<uint8_t>(key[(i + item_id) % klen]));
    }
    return out;
}

bool ItemDatabase::dari_bytes(const uint8_t *data, size_t len, std::string src) {
    source = std::move(src);
    items.clear();
    by_name.clear();
    terbaca = 0;
    R r(data, len);
    try {
        version = r.u16();
        count = r.u32();

        // v25+ menambah 9 byte ekor per item yang layout aslinya belum
        // dipetakan. Strategi: baca item, lalu lewati 9 byte; kalau id tidak
        // berurutan, berhenti (item sebelum itu tetap akurat).
        for (uint32_t i = 0; i < count; ++i) {
            Item it = read_item(r, version);
            if (r.gagal) break;
            if (it.id != i) break;
            if (version >= 25) r.skip(9);
            std::string kunci = it.name;
            if (!kunci.empty() && kunci.back() == ' ') kunci.pop_back();
            for (auto &c : kunci) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            by_name.emplace(kunci, it.id);
            items[it.id] = std::move(it);
            terbaca = i + 1;
        }
        return terbaca > 0;
    } catch (...) {
        return terbaca > 0;
    }
}

bool ItemDatabase::dari_file(const std::string &path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        source = path;
        return false;
    }
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(f)),
                              std::istreambuf_iterator<char>());
    return dari_bytes(data.data(), data.size(), path);
}

const Item *ItemDatabase::get(uint32_t item_id) const {
    auto it = items.find(item_id);
    return it == items.end() ? nullptr : &it->second;
}

std::string ItemDatabase::name_of(uint32_t item_id) const {
    const Item *it = get(item_id);
    return it ? it->name : ("#" + std::to_string(item_id));
}

std::vector<const Item *> ItemDatabase::find(const std::string &kata, bool exact) const {
    std::string cari = kata;
    while (!cari.empty() && cari.back() == ' ') cari.pop_back();
    for (auto &c : cari) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));

    std::vector<const Item *> out;
    if (exact) {
        auto it = by_name.find(cari);
        if (it != by_name.end()) out.push_back(get(it->second));
        return out;
    }
    for (const auto &kv : items) {
        std::string nama = kv.second.name;
        for (auto &c : nama) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if (nama.find(cari) != std::string::npos) out.push_back(&kv.second);
    }
    std::sort(out.begin(), out.end(),
              [](const Item *a, const Item *b) { return a->id < b->id; });
    return out;
}

}  // namespace lucifer
