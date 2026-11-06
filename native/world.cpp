// lucifer/world.cpp — port 1:1 dari lucifer/world.py
//
// Pembaca memakai penanda posisi + batas panjang; kalau data terpotong,
// pembacaan berhenti dan `error` diisi (mirip try/except di Python).
#include "world.h"

#include <cstring>

namespace lucifer {
namespace {

struct Reader {
    const uint8_t *buf;
    size_t len;
    size_t pos = 0;
    bool gagal = false;

    Reader(const uint8_t *b, size_t n) : buf(b), len(n) {}

    bool cukup(size_t n) const { return pos + n <= len; }

    uint8_t u8() {
        if (!cukup(1)) {
            gagal = true;
            return 0;
        }
        return buf[pos++];
    }
    uint16_t u16() {
        if (!cukup(2)) {
            gagal = true;
            return 0;
        }
        const uint16_t v = static_cast<uint16_t>(buf[pos] | (buf[pos + 1] << 8));
        pos += 2;
        return v;
    }
    uint32_t u32() {
        if (!cukup(4)) {
            gagal = true;
            return 0;
        }
        const uint32_t v = static_cast<uint32_t>(buf[pos]) |
                           (static_cast<uint32_t>(buf[pos + 1]) << 8) |
                           (static_cast<uint32_t>(buf[pos + 2]) << 16) |
                           (static_cast<uint32_t>(buf[pos + 3]) << 24);
        pos += 4;
        return v;
    }
    int32_t i32() { return static_cast<int32_t>(u32()); }
    float f32() {
        uint32_t bits = u32();
        float f;
        std::memcpy(&f, &bits, sizeof(f));
        return f;
    }
    void skip(size_t n) {
        if (!cukup(n)) {
            gagal = true;
            pos = len;
            return;
        }
        pos += n;
    }
    // string u16 panjang + byte (bukan null-terminated)
    std::string string_u16() {
        const uint16_t n = u16();
        if (!cukup(n)) {
            gagal = true;
            pos = len;
            return {};
        }
        std::string s(reinterpret_cast<const char *>(buf + pos), n);
        pos += n;
        return s;
    }
};

// Item yang selalu membawa blok CBOR (u32 panjang + data) setelah extra.
bool cbor_item(uint16_t id) {
    switch (id) {
        case 15376:  // Party Projector
        case 15546:  // Auction Block
        case 3548:   // Battle Pet Cage
        case 12598:  // Offering Table
        case 14662:  // Operating Table
        case 14666:  // Auto Surgeon Station
            return true;
        default:
            break;
    }
    return id >= 8624 && id <= 8714 && ((id - 8624) % 6) == 0;
}

void set_ready(Tile &t, GrowTimeFn fn, void *user) {
    t.grow_time = fn ? fn(user, t.fg) : 0;
    t.ready = t.grow_time != 0 && t.seed_age >= t.grow_time;
}

// Extra data per tipe (1..81). Tabel diambil dari world_manager milik
// Growtopia-PythonBot; urutan baca WAJIB sama supaya offset tidak bergeser.
void read_extra(Reader &r, Tile &t, GrowTimeFn fn, void *user) {
    switch (t.extra_type) {
        case 1:  // Sign
            t.label = r.string_u16();
            r.u8();
            break;
        case 2:  // Door
            t.label = r.string_u16();
            r.u32();
            break;
        case 3: {  // Lock
            r.u8();
            t.owner_uid = r.u32();
            const uint32_t n = r.u32();
            for (uint32_t i = 0; i < n && i < 4096; ++i) r.u32();
            r.u8();
            r.skip(7);
            if (t.fg == 5814) r.skip(16);
            break;
        }
        case 4:  // Seed / tanaman
            t.seed_age = r.u32();
            t.fruit_count = r.u8();
            set_ready(t, fn, user);
            break;
        case 6:
        case 7:
        case 12:  // Mailbox / Bulletin / DonationBox
            t.label = r.string_u16();
            r.string_u16();
            r.string_u16();
            r.u8();
            break;
        case 8:  // Dice
            r.u8();
            break;
        case 9:  // Chemical source
            t.seed_age = r.u32();
            set_ready(t, fn, user);
            if (t.fg == 10656) r.skip(4);
            break;
        case 10:
            r.u32();
            r.u8();
            break;
        case 11:
            r.u32();
            r.string_u16();
            break;
        case 14:  // Mannequin
            t.label = r.string_u16();
            r.u8();
            r.u32();
            for (int i = 0; i < 9; ++i) r.u16();
            break;
        case 15:
            r.u32();
            break;
        case 16:
            r.u8();
            break;
        case 17:
            break;
        case 18:
            r.u8();
            r.u32();
            break;
        case 19:
            for (int i = 0; i < 9; ++i) r.u16();
            break;
        case 20:  // Crystal
            t.label = r.string_u16();
            break;
        case 21:
            r.string_u16();
            r.u32();
            r.u8();
            break;
        case 22:
            break;
        case 23:
            r.u32();
            break;
        case 24:
            r.u32();
            r.i32();
            break;
        case 25: {  // Fish tank port
            r.u8();
            const uint32_t n = r.u32();
            r.skip(static_cast<size_t>(n / 2) * 8);
            break;
        }
        case 26:
            r.skip(5);
            break;
        case 27:
            r.u32();
            break;
        case 28:
            r.u16();
            r.u32();
            break;
        case 30:
            r.u8();
            r.u32();
            break;
        case 31:  // Silkworm
            r.u8();
            r.string_u16();
            for (int i = 0; i < 4; ++i) r.u32();
            r.u8();
            for (int i = 0; i < 4; ++i) r.u32();
            break;
        case 32: {
            const uint16_t n = r.u16();
            r.skip(static_cast<size_t>(n) * 4);
            break;
        }
        case 33:
            t.label = r.string_u16();
            break;
        case 34:
            break;
        case 35:
            r.u32();
            r.string_u16();
            break;
        case 36:
            r.string_u16();
            r.skip(12);
            break;
        case 37: {
            r.string_u16();
            const uint32_t n = r.u32();
            r.u32();
            r.skip(static_cast<size_t>(n) * 4);
            break;
        }
        case 38:
        case 39:
        case 40:
        case 41:
            r.u32();
            break;
        case 42:
            r.skip(21);
            break;
        case 43:
            r.skip(16);
            break;
        case 44: {
            r.u8();
            r.u32();
            const uint32_t n = r.u32();
            r.skip(static_cast<size_t>(n) * 4);
            break;
        }
        case 45:
            break;
        case 47:
            r.string_u16();
            r.u32();
            r.u8();
            break;
        case 48:  // Portrait: 26 byte setelah label
            t.label = r.string_u16();
            r.skip(26);
            break;
        case 49:
            r.u32();
            r.u32();
            r.u8();
            break;
        case 50:
            r.u32();
            break;
        case 51:
        case 52:
            break;
        case 53:
            r.u32();
            r.u32();
            break;
        case 54: {
            const uint16_t n = r.u16();
            r.skip(n);
            break;
        }
        case 55: {
            r.u32();
            const uint32_t n = r.u32();
            r.skip(static_cast<size_t>(n) * 8);
            r.skip(12);
            break;
        }
        case 56:
            r.string_u16();
            r.u32();
            break;
        case 57:
            r.u32();
            break;
        case 58:
        case 59:
            break;
        case 60:
            r.u32();
            r.u8();
            break;
        case 61:
            r.u32();
            r.u16();
            for (int i = 0; i < 4; ++i) r.u32();
            break;
        case 62:  // Item sucker
            r.u32();
            r.u32();
            r.u16();
            r.u32();
            break;
        case 63: {  // CyBot
            r.u32();
            r.u32();
            const uint32_t n = r.u32();
            for (uint32_t i = 0; i < n; ++i) {
                r.u32();
                r.u32();
                r.skip(7);
            }
            break;
        }
        case 65:  // Guild item
            r.skip(17);
            break;
        case 66:
            r.u8();
            break;
        case 67: {
            r.u32();
            const uint32_t n = r.u32();
            r.skip(static_cast<size_t>(n) * 4);
            break;
        }
        case 68:
        case 69:
            r.u32();
            r.u32();
            r.u32();
            if (t.extra_type == 69) r.u32();
            break;
        case 72:
            for (int i = 0; i < 3; ++i) r.u32();
            break;
        case 73:
            r.u32();
            break;
        case 74:
            break;
        case 75:
            r.u32();
            r.u16();
            r.u8();
            break;
        case 77: {
            r.u32();
            const uint32_t n = r.u32();
            r.skip(static_cast<size_t>(n) * 4);
            break;
        }
        case 79:
            break;
        case 80:
            r.u8();
            r.u32();
            r.u8();
            r.u8();
            r.u8();
            break;
        case 81:
            r.u32();
            r.u16();
            r.u16();
            break;
        default:
            // Tipe belum dikenal: berhenti membaca extra supaya tidak
            // menggeser offset tile berikutnya secara acak.
            r.gagal = true;
            break;
    }
}

Tile read_tile(Reader &r, int32_t x, int32_t y, GrowTimeFn fn, void *user) {
    Tile t;
    t.x = x;
    t.y = y;
    t.fg = r.u16();
    t.bg = r.u16();
    t.parent = r.u16();
    t.flags = r.u16();

    if (t.flags & TILE_HAS_PARENT) r.u16();
    if (t.flags & TILE_EXTRA_DATA) {
        t.extra_type = r.u8();
        read_extra(r, t, fn, user);
    }
    if (cbor_item(t.fg)) {
        const uint32_t n = r.u32();
        if (r.cukup(n)) {
            t.raw_extra.assign(r.buf + r.pos, r.buf + r.pos + n);
            r.pos += n;
        } else {
            r.gagal = true;
        }
    }
    return t;
}

}  // namespace

Tile *World::tile(int x, int y) {
    if (x < 0 || y < 0 || x >= static_cast<int>(width) || y >= static_cast<int>(height)) {
        return nullptr;
    }
    const int idx = index_of(x, y);
    if (idx < 0 || static_cast<size_t>(idx) >= tiles.size()) return nullptr;
    return &tiles[static_cast<size_t>(idx)];
}

const Tile *World::tile(int x, int y) const {
    return const_cast<World *>(this)->tile(x, y);
}

bool World::update_tile(int index, const Tile &t) {
    if (index < 0 || static_cast<size_t>(index) >= tiles.size()) return false;
    tiles[static_cast<size_t>(index)] = t;
    return true;
}

std::vector<Tile *> World::find_items(uint16_t item_id) {
    std::vector<Tile *> out;
    for (auto &t : tiles) {
        if (t.fg == item_id) out.push_back(&t);
    }
    return out;
}

std::vector<Tile *> World::find_seeds(bool ready_only) {
    std::vector<Tile *> out;
    for (auto &t : tiles) {
        if (t.is_seed() && (!ready_only || t.ready)) out.push_back(&t);
    }
    return out;
}

World parse_world(const uint8_t *data, size_t len, GrowTimeFn fn, void *user) {
    World w;
    Reader r(data, len);
    try {
        w.version = r.u16();
        if (w.version < 25) {
            w.error = "versi dunia terlalu lama: " + std::to_string(w.version);
            return w;
        }
        w.flags = r.u32();
        w.name = r.string_u16();
        w.width = r.u32();
        w.height = r.u32();
        const uint32_t declared = r.u32();
        r.skip(5);

        if (declared > 0xFE01) {
            w.error = "tile_count tidak wajar: " + std::to_string(declared);
            return w;
        }

        w.tiles.reserve(declared);
        for (uint32_t i = 0; i < declared; ++i) {
            const int32_t x = w.width ? static_cast<int32_t>(i % w.width) : 0;
            const int32_t y = w.width ? static_cast<int32_t>(i / w.width) : 0;
            w.tiles.push_back(read_tile(r, x, y, fn, user));
            if (r.gagal) break;
        }

        r.skip(12);
        const uint32_t n_dropped = r.u32();
        w.last_uid = r.u32();
        for (uint32_t i = 0; i < n_dropped && !r.gagal; ++i) {
            DroppedItem d;
            d.item_id = r.u16();
            d.x = r.f32();
            d.y = r.f32();
            d.count = r.u8();
            d.flags = r.u8();
            d.uid = r.u32();
            w.dropped.push_back(d);
        }
        w.base_weather = r.u16();
        r.u16();
        w.current_weather = r.u16();
        if (r.gagal) {
            w.error = "data dunia terpotong di offset " + std::to_string(r.pos) +
                      "/" + std::to_string(len);
        }
    } catch (const std::exception &e) {
        w.error = e.what();
    }
    return w;
}

std::vector<Tile> parse_tile_updates(const uint8_t *data, size_t len, GrowTimeFn fn,
                                      void *user) {
    std::vector<Tile> out;
    Reader r(data, len);
    while (r.cukup(8)) {
        const uint32_t x = r.u32();
        const uint32_t y = r.u32();
        if (x == 0xFFFFFFFF || y == 0xFFFFFFFF) break;
        Tile t = read_tile(r, static_cast<int32_t>(x), static_cast<int32_t>(y), fn, user);
        out.push_back(std::move(t));
        if (r.gagal) break;
    }
    return out;
}

}  // namespace lucifer
