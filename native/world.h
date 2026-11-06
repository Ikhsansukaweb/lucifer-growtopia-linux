// lucifer/world.h — parser dunia Growtopia, port dari lucifer/world.py
//
// Payload `SendMapData` (tank type 4):
//   u16 version, u32 flags, string16 name, u32 w, u32 h, u32 tile_count,
//   skip 5, tile_count x tile, skip 12, u32 dropped_count, u32 last_uid,
//   dropped_count x item, u16 base_weather, u16 pad, u16 current_weather
//
// `parse_tile_updates` membaca type 6 (SendTileUpdateDataMultiple):
//   diulang: u32 x, u32 y, <blok tile>   penutup: u32 0xFFFFFFFF
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace lucifer {

// Bit flag tile. Nama ganda (LOCKED/HAS_PARENT, FLIPPED/ROTATED_LEFT) memang
// berbagi nilai yang sama di protokol.
enum TileFlag : uint16_t {
    TILE_EXTRA_DATA = 0x0001,
    TILE_HAS_PARENT = 0x0002,
    TILE_LOCKED = 0x0002,
    TILE_SPLICED = 0x0004,
    TILE_SEED = 0x0008,
    TILE_SEEDLING = 0x0010,
    TILE_FLIPPED = 0x0020,
    TILE_ROTATED_LEFT = 0x0020,
    TILE_OPEN = 0x0040,
    TILE_PUBLIC = 0x0080,
    TILE_BG_ON = 0x0100,
    TILE_FG_ALT = 0x0200,
    TILE_WATER = 0x0400,
    TILE_GLUE = 0x0800,
    TILE_FIRE = 0x1000,
    TILE_PAINT_RED = 0x2000,
    TILE_PAINT_GREEN = 0x4000,
    TILE_PAINT_BLUE = 0x8000,
    TILE_PAINT_YELLOW = 0x0004,
};

struct Tile {
    int32_t x = 0, y = 0;
    uint16_t fg = 0, bg = 0;
    uint16_t parent = 0;
    uint16_t flags = 0;
    uint8_t extra_type = 0;
    uint32_t seed_age = 0;
    uint8_t fruit_count = 0;
    bool ready = false;
    uint32_t grow_time = 0;
    uint32_t owner_uid = 0;
    std::string label;
    std::vector<uint8_t> raw_extra;

    bool has(uint16_t flag) const { return (flags & flag) != 0; }
    bool has_extra() const { return has(TILE_EXTRA_DATA); }
    bool is_locked() const { return has(TILE_LOCKED); }
    bool is_seed() const { return extra_type == 4; }
    bool empty() const { return fg == 0 && bg == 0; }
};

struct DroppedItem {
    uint16_t item_id = 0;
    float x = 0.0f, y = 0.0f;
    uint8_t count = 0;
    uint8_t flags = 0;
    uint32_t uid = 0;
};

class World {
public:
    std::string name;
    uint32_t width = 0, height = 0;
    std::vector<Tile> tiles;
    std::vector<DroppedItem> dropped;
    uint16_t base_weather = 0;
    uint16_t current_weather = 0;
    uint16_t version = 0;
    uint32_t flags = 0;
    // uid tertinggi dari server. `ItemChangeObject` tidak membawa uid; klien
    // menaikkan nilai ini sendiri untuk menomori objek baru.
    uint32_t last_uid = 0;
    std::string error;

    size_t tile_count() const { return static_cast<size_t>(width) * height; }

    Tile *tile(int x, int y);
    const Tile *tile(int x, int y) const;
    int index_of(int x, int y) const { return y * static_cast<int>(width) + x; }
    bool update_tile(int index, const Tile &t);
    std::vector<Tile *> find_items(uint16_t item_id);
    std::vector<Tile *> find_seeds(bool ready_only);
};

// `grow_time` diisi dari items.dat kalau `grow_time_of` diberikan.
// Callback itu menerima id item dan mengembalikan grow_time (0 kalau tak ada).
using GrowTimeFn = uint32_t (*)(void *user, uint16_t item_id);

// Parse payload SendMapData. Selalu mengembalikan World; kalau gagal,
// `error` berisi alasannya (tidak melempar exception).
World parse_world(const uint8_t *data, size_t len, GrowTimeFn grow_time_of = nullptr,
                  void *user = nullptr);

// Parse payload SendTileUpdateDataMultiple (type 6).
std::vector<Tile> parse_tile_updates(const uint8_t *data, size_t len,
                                     GrowTimeFn grow_time_of = nullptr,
                                     void *user = nullptr);

}  // namespace lucifer
