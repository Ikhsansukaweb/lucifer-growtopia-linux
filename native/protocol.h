// lucifer/protocol.h — codec protokol Growtopia, port 1:1 dari lucifer/protocol.py
//
// Semua tipe di sini WAJIB menghasilkan byte identik dengan versi Python.
// Uji kesetaraan ada di native/tests/test_protocol.cpp (membandingkan dump
// dari Python). Kalau satu field bergeser, seluruh bot salah baca.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <variant>
#include <vector>

namespace lucifer {

// ------------------------------------------------------------------ pesan --
enum class NetMessage : uint32_t {
    Unknown = 0,
    ServerHello = 1,
    GenericText = 2,
    GameMessage = 3,
    GamePacket = 4,
    Error = 5,
    Track = 6,
    ClientLogRequest = 7,
    ClientLogResponse = 8,
};

enum class NetGamePacket : uint8_t {
    State = 0,
    CallFunction = 1,
    UpdateStatus = 2,
    TileChangeRequest = 3,
    SendMapData = 4,
    SendTileUpdateData = 5,
    SendTileUpdateDataMultiple = 6,
    TileActivateRequest = 7,
    TileApplyDamage = 8,
    SendInventoryState = 9,
    ItemActivateRequest = 10,
    ItemActivateObjectRequest = 11,
    SendTileTreeState = 12,
    ModifyItemInventory = 13,
    ItemChangeObject = 14,
    SendLock = 15,
    SendItemDatabaseData = 16,
    SendParticleEffect = 17,
    SetIconState = 18,
    ItemEffect = 19,
    SetCharacterState = 20,
    PingReply = 21,
    PingRequest = 22,
    GotPunched = 23,
    AppCheckResponse = 24,
    AppIntegrityFail = 25,
    Disconnect = 26,
    BattleJoin = 27,
    BattleEvent = 28,
    UseDoor = 29,
    SendParental = 30,
    GoneFishin = 31,
    Steam = 32,
    PetBattle = 33,
    Npc = 34,
    Special = 35,
    SendParticleEffectV2 = 36,
    ActivateArrowToItem = 37,
    SelectTileIndex = 38,
    SendPlayerTributeData = 39,
    FTUESetItemToQuickInventory = 40,
    PVENpc = 41,
    PVPCardBattle = 42,
    PVEApplyPlayerDamage = 43,
    PVENPCPositionUpdate = 44,
    SetExtraMods = 45,
    OnStepTileMod = 46,
};

const char *tank_name(NetGamePacket t);

// ------------------------------------------------------------------- Tank --
// Layout 56 byte, little-endian, tanpa padding. Sama persis dengan
// TankPacket di lucifer/enet.py.
constexpr int TANK_SIZE = 56;

struct Tank {
    uint8_t type = 0;
    uint8_t object_type = 0;
    uint8_t jump_count = 0;
    uint8_t animation_type = 0;
    uint32_t net_id = 0;
    int32_t target_net_id = 0;
    uint32_t flags = 0;
    float float_variable = 0.0f;
    uint32_t value = 0;
    float vector_x = 0.0f;
    float vector_y = 0.0f;
    float vector_x2 = 0.0f;
    float vector_y2 = 0.0f;
    float particle_rotation = 0.0f;
    int32_t int_x = 0;
    int32_t int_y = 0;
    uint32_t extended_data_length = 0;

    // Serialisasi 56 byte + extended. `extended_data_length` dihitung dari
    // panjang `ext` (tidak dipakai dari field mentah).
    std::vector<uint8_t> bytes(const std::vector<uint8_t> &ext = {}) const;

    // Baca dari buffer mentah. Mengembalikan false kalau < TANK_SIZE.
    static bool parse(const uint8_t *raw, size_t len, Tank &out,
                      std::vector<uint8_t> &ext);
};

// ---------------------------------------------------------------- Variant --
enum VariantKind : uint8_t {
    VARIANT_UNKNOWN = 0,
    VARIANT_FLOAT = 1,
    VARIANT_STRING = 2,
    VARIANT_VEC2 = 3,
    VARIANT_VEC3 = 4,
    VARIANT_UNSIGNED = 5,
    VARIANT_SIGNED = 9,
};

struct Vec2 {
    float x = 0, y = 0;
};
struct Vec3 {
    float x = 0, y = 0, z = 0;
};

class Variant {
public:
    Variant() = default;
    explicit Variant(uint8_t kind) : kind_(kind) {}

    static Variant from_string(std::string s);
    static Variant from_int(int32_t v);
    static Variant from_uint(uint32_t v);
    static Variant from_float(float v);
    static Variant from_vec2(float x, float y);
    static Variant from_vec3(float x, float y, float z);

    uint8_t kind() const { return kind_; }
    bool is_string() const { return kind_ == VARIANT_STRING; }

    // Akses longgar seperti versi Python: tipe salah -> nilai default.
    std::string as_string() const;
    float as_float() const;
    int32_t as_int32() const;
    // Nilai unsigned apa adanya (tanpa lewat int32, supaya > 2^31 tidak
    // overflow). Python: `as_uint32 = as_int32 & 0xFFFFFFFF`.
    uint32_t as_uint32() const { return unsigned_value(); }
    uint32_t unsigned_value() const;
    Vec2 as_vec2() const;
    Vec3 as_vec3() const;

    const std::string &str() const { return s_; }

private:
    uint8_t kind_ = VARIANT_UNKNOWN;
    std::string s_;
    double num_ = 0;   // float / signed / unsigned
    Vec2 v2_{};
    Vec3 v3_{};
};

class VariantList {
public:
    VariantList() = default;

    Variant &append(Variant v) {
        items_.push_back(std::move(v));
        return items_.back();
    }
    size_t size() const { return items_.size(); }
    bool empty() const { return items_.empty(); }
    const Variant *get(size_t i) const {
        return i < items_.size() ? &items_[i] : nullptr;
    }
    const Variant *operator[](size_t i) const { return get(i); }
    std::string func_name() const;

    // Byte pertama = jumlah variant; tiap variant: index(u8) kind(u8) data.
    std::vector<uint8_t> serialize() const;
    static bool deserialize(const uint8_t *data, size_t len, VariantList &out);

private:
    std::vector<Variant> items_;
};

// ------------------------------------------------------------------ teks ---
// `key|value\n` -> map. Kunci duplikat: yang terakhir menang (sama seperti
// klien). NUL dan karakter kontrol dibuang, hanya '\n' dipertahankan.
using TextFields = std::unordered_map<std::string, std::string>;

TextFields decode_text(const uint8_t *data, size_t len);
TextFields decode_text(const std::vector<uint8_t> &v);

// Urutan kunci dipertahankan sesuai `fields`.
std::vector<uint8_t> encode_text(const std::vector<std::pair<std::string, std::string>> &fields);

// Buang kode warna Growtopia: backtick + satu karakter alfanumerik/'#'.
std::string remove_color(std::string_view text);

// ------------------------------------------------------------ bingkai ------
std::vector<uint8_t> build_packet(NetMessage type, const std::vector<uint8_t> &payload = {});
bool parse_packet(const uint8_t *data, size_t len, uint32_t &type,
                  const uint8_t *&payload, size_t &payload_len);

// ------------------------------------------------- tabel action|... -------
// Hasil ekstraksi literal dari libgrowtopia.so 5.58. Dipakai `Bot::kirim`.
struct ActionSpec {
    const char *name;
    std::vector<const char *> fields;
};
const std::vector<ActionSpec> &actions();

// Bangun `action|<name>\n<field>|<nilai>\n...` sesuai urutan tabel.
// Mengembalikan false kalau action tidak dikenal.
bool build_action(const std::string &name,
                  const std::vector<std::pair<std::string, std::string>> &fields,
                  std::vector<uint8_t> &out);

}  // namespace lucifer
