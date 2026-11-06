// lucifer/items.h — pembaca items.dat, port dari lucifer/items.py
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace lucifer {

// Kunci XOR nama item (literal di klien Growtopia).
inline constexpr const char *ITEM_NAME_SECRET = "PBG892FXX982ABC*";

struct Item {
    uint32_t id = 0;
    uint16_t flags = 0;
    uint8_t action_type = 0;
    uint8_t material = 0;
    std::string name;
    std::string texture_file_name;
    uint32_t texture_hash = 0;
    uint8_t visual_effect = 0;
    uint32_t cooking_ingredient = 0;
    uint8_t texture_x = 0;
    uint8_t texture_y = 0;
    uint8_t render_type = 0;
    uint8_t is_stripey_wallpaper = 0;
    uint8_t collision_type = 0;
    // Butuh berapa pukulan untuk memecah blok ini. Ini yang dipakai autofarm
    // untuk menentukan berapa kali memukul sebelum menyerah.
    uint8_t block_health = 0;
    uint32_t drop_chance = 0;
    uint8_t clothing_type = 0;
    uint16_t rarity = 0;
    uint8_t max_item = 0;
    std::string file_name;
    uint32_t file_hash = 0;
    std::string pet_name;
    std::string pet_prefix;
    std::string pet_suffix;
    std::string pet_ability;
    uint8_t seed_base_sprite = 0;
    uint8_t seed_overlay_sprite = 0;
    uint8_t tree_base_sprite = 0;
    uint8_t tree_overlay_sprite = 0;
    uint32_t base_color = 0;
    uint32_t overlay_color = 0;
    uint32_t ingredient = 0;
    uint32_t grow_time = 0;
    std::string extra_options;
    std::string texture_path_2;
    std::string extra_option2;
    std::string punch_option;
    std::string description;

    // action_type 19 menandai bibit (99,96% akurat pada v24); nama berakhiran
    // " Seed" dipakai sebagai cadangan.
    bool is_seed() const;
};

class ItemDatabase {
public:
    uint16_t version = 0;
    uint32_t count = 0;
    std::unordered_map<uint32_t, Item> items;
    std::unordered_map<std::string, uint32_t> by_name;  // lowercase -> id
    std::string source;
    uint32_t terbaca = 0;   // jumlah item yang berhasil dibaca

    bool dari_bytes(const uint8_t *data, size_t len, std::string src = "");
    bool dari_file(const std::string &path);

    const Item *get(uint32_t item_id) const;
    std::string name_of(uint32_t item_id) const;
    // Cari berdasarkan nama (case-insensitive). `exact` = harus sama persis.
    std::vector<const Item *> find(const std::string &kata, bool exact) const;
    size_t size() const { return items.size(); }
};

// XOR nama item dengan kunci; posisi kunci bergeser sebesar item_id.
std::string decode_item_name(const uint8_t *raw, size_t len, uint32_t item_id);

}  // namespace lucifer
