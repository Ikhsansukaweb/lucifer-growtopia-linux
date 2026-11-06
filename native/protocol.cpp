// lucifer/protocol.cpp — implementasi codec. Lihat protocol.h untuk kontrak.
//
// Semua penulisan byte WAJIB little-endian eksplisit (bukan memcpy struct)
// supaya hasilnya sama di x86 maupun arm64.
#include "protocol.h"

#include <cstring>
#include <stdexcept>

namespace lucifer {
namespace {

inline void put_u8(std::vector<uint8_t> &v, uint8_t x) { v.push_back(x); }

inline void put_u16(std::vector<uint8_t> &v, uint16_t x) {
    v.push_back(static_cast<uint8_t>(x & 0xFF));
    v.push_back(static_cast<uint8_t>((x >> 8) & 0xFF));
}

inline void put_u32(std::vector<uint8_t> &v, uint32_t x) {
    v.push_back(static_cast<uint8_t>(x & 0xFF));
    v.push_back(static_cast<uint8_t>((x >> 8) & 0xFF));
    v.push_back(static_cast<uint8_t>((x >> 16) & 0xFF));
    v.push_back(static_cast<uint8_t>((x >> 24) & 0xFF));
}

inline void put_i32(std::vector<uint8_t> &v, int32_t x) {
    put_u32(v, static_cast<uint32_t>(x));
}

inline void put_f32(std::vector<uint8_t> &v, float x) {
    uint32_t bits;
    static_assert(sizeof(bits) == sizeof(x), "float harus 32-bit");
    std::memcpy(&bits, &x, sizeof(bits));
    put_u32(v, bits);
}

inline uint16_t rd_u16(const uint8_t *p) {
    return static_cast<uint16_t>(p[0] | (p[1] << 8));
}
inline uint32_t rd_u32(const uint8_t *p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
inline int32_t rd_i32(const uint8_t *p) { return static_cast<int32_t>(rd_u32(p)); }
inline float rd_f32(const uint8_t *p) {
    uint32_t bits = rd_u32(p);
    float f;
    std::memcpy(&f, &bits, sizeof(f));
    return f;
}

// Python memakai str.strip() (spasi, tab, CR, LF). Implementasi setara.
inline std::string trim(std::string s) {
    auto bukan_spasi = [](unsigned char c) {
        return c != ' ' && c != '\t' && c != '\r' && c != '\n' && c != '\v' && c != '\f';
    };
    size_t awal = 0;
    while (awal < s.size() && !bukan_spasi(static_cast<unsigned char>(s[awal]))) ++awal;
    size_t akhir = s.size();
    while (akhir > awal && !bukan_spasi(static_cast<unsigned char>(s[akhir - 1]))) --akhir;
    return s.substr(awal, akhir - awal);
}

}  // namespace

const char *tank_name(NetGamePacket t) {
    switch (t) {
        case NetGamePacket::State: return "State";
        case NetGamePacket::CallFunction: return "CallFunction";
        case NetGamePacket::UpdateStatus: return "UpdateStatus";
        case NetGamePacket::TileChangeRequest: return "TileChangeRequest";
        case NetGamePacket::SendMapData: return "SendMapData";
        case NetGamePacket::SendTileUpdateData: return "SendTileUpdateData";
        case NetGamePacket::SendTileUpdateDataMultiple: return "SendTileUpdateDataMultiple";
        case NetGamePacket::TileActivateRequest: return "TileActivateRequest";
        case NetGamePacket::TileApplyDamage: return "TileApplyDamage";
        case NetGamePacket::SendInventoryState: return "SendInventoryState";
        case NetGamePacket::ItemActivateRequest: return "ItemActivateRequest";
        case NetGamePacket::ItemActivateObjectRequest: return "ItemActivateObjectRequest";
        case NetGamePacket::SendTileTreeState: return "SendTileTreeState";
        case NetGamePacket::ModifyItemInventory: return "ModifyItemInventory";
        case NetGamePacket::ItemChangeObject: return "ItemChangeObject";
        case NetGamePacket::SendLock: return "SendLock";
        case NetGamePacket::SendItemDatabaseData: return "SendItemDatabaseData";
        case NetGamePacket::SendParticleEffect: return "SendParticleEffect";
        case NetGamePacket::SetIconState: return "SetIconState";
        case NetGamePacket::ItemEffect: return "ItemEffect";
        case NetGamePacket::SetCharacterState: return "SetCharacterState";
        case NetGamePacket::PingReply: return "PingReply";
        case NetGamePacket::PingRequest: return "PingRequest";
        case NetGamePacket::GotPunched: return "GotPunched";
        case NetGamePacket::AppCheckResponse: return "AppCheckResponse";
        case NetGamePacket::AppIntegrityFail: return "AppIntegrityFail";
        case NetGamePacket::Disconnect: return "Disconnect";
        case NetGamePacket::BattleJoin: return "BattleJoin";
        case NetGamePacket::BattleEvent: return "BattleEvent";
        case NetGamePacket::UseDoor: return "UseDoor";
        case NetGamePacket::SendParental: return "SendParental";
        case NetGamePacket::GoneFishin: return "GoneFishin";
        case NetGamePacket::Steam: return "Steam";
        case NetGamePacket::PetBattle: return "PetBattle";
        case NetGamePacket::Npc: return "Npc";
        case NetGamePacket::Special: return "Special";
        case NetGamePacket::SendParticleEffectV2: return "SendParticleEffectV2";
        case NetGamePacket::ActivateArrowToItem: return "ActivateArrowToItem";
        case NetGamePacket::SelectTileIndex: return "SelectTileIndex";
        case NetGamePacket::SendPlayerTributeData: return "SendPlayerTributeData";
        case NetGamePacket::FTUESetItemToQuickInventory: return "FTUESetItemToQuickInventory";
        case NetGamePacket::PVENpc: return "PVENpc";
        case NetGamePacket::PVPCardBattle: return "PVPCardBattle";
        case NetGamePacket::PVEApplyPlayerDamage: return "PVEApplyPlayerDamage";
        case NetGamePacket::PVENPCPositionUpdate: return "PVENPCPositionUpdate";
        case NetGamePacket::SetExtraMods: return "SetExtraMods";
        case NetGamePacket::OnStepTileMod: return "OnStepTileMod";
    }
    return "?";
}

// ------------------------------------------------------------------- Tank --
std::vector<uint8_t> Tank::bytes(const std::vector<uint8_t> &ext) const {
    std::vector<uint8_t> out;
    out.reserve(TANK_SIZE + ext.size());
    put_u8(out, type);
    put_u8(out, object_type);
    put_u8(out, jump_count);
    put_u8(out, animation_type);
    put_u32(out, net_id);
    put_i32(out, target_net_id);
    put_u32(out, flags);
    put_f32(out, float_variable);
    put_u32(out, value);
    put_f32(out, vector_x);
    put_f32(out, vector_y);
    put_f32(out, vector_x2);
    put_f32(out, vector_y2);
    put_f32(out, particle_rotation);
    put_i32(out, int_x);
    put_i32(out, int_y);
    put_u32(out, static_cast<uint32_t>(ext.size()));  // bukan field mentah
    out.insert(out.end(), ext.begin(), ext.end());
    return out;
}

bool Tank::parse(const uint8_t *raw, size_t len, Tank &out, std::vector<uint8_t> &ext) {
    if (len < TANK_SIZE) return false;
    out.type = raw[0];
    out.object_type = raw[1];
    out.jump_count = raw[2];
    out.animation_type = raw[3];
    out.net_id = rd_u32(raw + 4);
    out.target_net_id = rd_i32(raw + 8);
    out.flags = rd_u32(raw + 12);
    out.float_variable = rd_f32(raw + 16);
    out.value = rd_u32(raw + 20);
    out.vector_x = rd_f32(raw + 24);
    out.vector_y = rd_f32(raw + 28);
    out.vector_x2 = rd_f32(raw + 32);
    out.vector_y2 = rd_f32(raw + 36);
    out.particle_rotation = rd_f32(raw + 40);
    out.int_x = rd_i32(raw + 44);
    out.int_y = rd_i32(raw + 48);
    out.extended_data_length = rd_u32(raw + 52);

    // Panjang ext dipotong ke sisa buffer: server kadang mengirim
    // extended_data_length lebih besar dari data yang benar-benar ada.
    size_t tersedia = len - TANK_SIZE;
    size_t n = out.extended_data_length;
    if (n > tersedia) n = tersedia;
    ext.assign(raw + TANK_SIZE, raw + TANK_SIZE + n);
    return true;
}

// ---------------------------------------------------------------- Variant --
Variant Variant::from_string(std::string s) {
    Variant v(VARIANT_STRING);
    v.s_ = std::move(s);
    return v;
}
Variant Variant::from_int(int32_t x) {
    Variant v(VARIANT_SIGNED);
    v.num_ = x;
    return v;
}
Variant Variant::from_uint(uint32_t x) {
    Variant v(VARIANT_UNSIGNED);
    v.num_ = x;
    return v;
}
Variant Variant::from_float(float x) {
    Variant v(VARIANT_FLOAT);
    v.num_ = x;
    return v;
}
Variant Variant::from_vec2(float x, float y) {
    Variant v(VARIANT_VEC2);
    v.v2_ = {x, y};
    return v;
}
Variant Variant::from_vec3(float x, float y, float z) {
    Variant v(VARIANT_VEC3);
    v.v3_ = {x, y, z};
    return v;
}

std::string Variant::as_string() const {
    if (kind_ == VARIANT_STRING) return s_;
    return {};  // bukan string -> kosong, bukan konversi angka
}

float Variant::as_float() const {
    switch (kind_) {
        case VARIANT_FLOAT:
        case VARIANT_SIGNED:
        case VARIANT_UNSIGNED:
            return static_cast<float>(num_);
        case VARIANT_STRING: {
            // Python memakai float(str); di sini cukup awalan numerik.
            try {
                return std::stof(s_);
            } catch (...) {
                return 0.0f;
            }
        }
        default:
            return 0.0f;
    }
}

int32_t Variant::as_int32() const {
    switch (kind_) {
        case VARIANT_FLOAT:
        case VARIANT_SIGNED:
        case VARIANT_UNSIGNED:
            return static_cast<int32_t>(num_);
        case VARIANT_STRING: {
            try {
                return static_cast<int32_t>(std::stoll(s_));
            } catch (...) {
                return 0;
            }
        }
        default:
            return 0;
    }
}

uint32_t Variant::unsigned_value() const {
    // JANGAN lewat as_int32(): nilai > 2^31 (mis. 4294967295) akan overflow
    // dan menghasilkan angka negatif. Python menyimpan uint apa adanya.
    switch (kind_) {
        case VARIANT_UNSIGNED:
        case VARIANT_FLOAT:
        case VARIANT_SIGNED: {
            const double d = num_;
            if (d < 0) return static_cast<uint32_t>(static_cast<int64_t>(d));
            return static_cast<uint32_t>(static_cast<uint64_t>(d));
        }
        case VARIANT_STRING: {
            try {
                return static_cast<uint32_t>(std::stoull(s_));
            } catch (...) {
                return 0;
            }
        }
        default:
            return 0;
    }
}

Vec2 Variant::as_vec2() const {
    if (kind_ == VARIANT_VEC2) return v2_;
    return {};
}

Vec3 Variant::as_vec3() const {
    if (kind_ == VARIANT_VEC3) return v3_;
    return {};
}

std::string VariantList::func_name() const {
    return items_.empty() ? std::string() : items_[0].as_string();
}

std::vector<uint8_t> VariantList::serialize() const {
    std::vector<uint8_t> out;
    out.reserve(1 + items_.size() * 8);
    put_u8(out, static_cast<uint8_t>(items_.size() & 0xFF));
    for (size_t i = 0; i < items_.size(); ++i) {
        const Variant &v = items_[i];
        put_u8(out, static_cast<uint8_t>(i & 0xFF));
        put_u8(out, v.kind());
        switch (v.kind()) {
            case VARIANT_FLOAT:
                put_f32(out, v.as_float());
                break;
            case VARIANT_STRING: {
                const std::string &s = v.str();
                put_u32(out, static_cast<uint32_t>(s.size()));
                out.insert(out.end(), s.begin(), s.end());
                break;
            }
            case VARIANT_VEC2: {
                Vec2 c = v.as_vec2();
                put_f32(out, c.x);
                put_f32(out, c.y);
                break;
            }
            case VARIANT_VEC3: {
                Vec3 c = v.as_vec3();
                put_f32(out, c.x);
                put_f32(out, c.y);
                put_f32(out, c.z);
                break;
            }
            case VARIANT_UNSIGNED:
                put_u32(out, v.unsigned_value());
                break;
            case VARIANT_SIGNED:
                put_i32(out, v.as_int32());
                break;
            default:
                // Tipe tak dikenal: berhenti seperti versi Python.
                return out;
        }
    }
    return out;
}

bool VariantList::deserialize(const uint8_t *data, size_t len, VariantList &out) {
    if (len == 0) return false;
    out.items_.clear();
    size_t off = 1;                   // byte 0 = jumlah variant
    const size_t n_declared = data[0];
    while (off + 2 <= len && out.items_.size() < n_declared) {
        off += 1;                     // index variant, diabaikan
        const uint8_t vtype = data[off];
        off += 1;
        switch (vtype) {
            case VARIANT_FLOAT:
                if (off + 4 > len) return true;
                out.items_.push_back(Variant::from_float(rd_f32(data + off)));
                off += 4;
                break;
            case VARIANT_STRING: {
                if (off + 4 > len) return true;
                const uint32_t slen = rd_u32(data + off);
                off += 4;
                if (off + slen > len) return true;
                out.items_.push_back(
                    Variant::from_string(std::string(reinterpret_cast<const char *>(data + off), slen)));
                off += slen;
                break;
            }
            case VARIANT_VEC2:
                if (off + 8 > len) return true;
                out.items_.push_back(Variant::from_vec2(rd_f32(data + off), rd_f32(data + off + 4)));
                off += 8;
                break;
            case VARIANT_VEC3:
                if (off + 12 > len) return true;
                out.items_.push_back(Variant::from_vec3(rd_f32(data + off), rd_f32(data + off + 4),
                                                        rd_f32(data + off + 8)));
                off += 12;
                break;
            case VARIANT_UNSIGNED:
                if (off + 4 > len) return true;
                out.items_.push_back(Variant::from_uint(rd_u32(data + off)));
                off += 4;
                break;
            case VARIANT_SIGNED:
                if (off + 4 > len) return true;
                out.items_.push_back(Variant::from_int(rd_i32(data + off)));
                off += 4;
                break;
            default:
                out.items_.push_back(Variant(vtype));
                return true;
        }
    }
    return true;
}

// ------------------------------------------------------------------ teks ---
TextFields decode_text(const uint8_t *data, size_t len) {
    std::string text(reinterpret_cast<const char *>(data), len);
    // Buang NUL dan karakter kontrol selain '\n' (server menempelkannya di
    // akhir nilai sehingga pesan jadi kotor).
    std::string bersih;
    bersih.reserve(text.size());
    for (unsigned char c : text) {
        if (c >= 0x20 || c == '\n') bersih.push_back(static_cast<char>(c));
    }

    TextFields out;
    size_t pos = 0;
    while (pos <= bersih.size()) {
        size_t akhir = bersih.find('\n', pos);
        if (akhir == std::string::npos) akhir = bersih.size();
        std::string baris = bersih.substr(pos, akhir - pos);
        if (!baris.empty() && baris.back() == '\r') baris.pop_back();
        if (!baris.empty()) {
            size_t sep = baris.find('|');
            if (sep == std::string::npos) {
                out[trim(baris)] = "";
            } else {
                out[trim(baris.substr(0, sep))] = trim(baris.substr(sep + 1));
            }
        }
        if (akhir == bersih.size()) break;
        pos = akhir + 1;
    }
    return out;
}

TextFields decode_text(const std::vector<uint8_t> &v) {
    return decode_text(v.data(), v.size());
}

std::vector<uint8_t> encode_text(const std::vector<std::pair<std::string, std::string>> &fields) {
    std::string s;
    for (const auto &kv : fields) {
        s += kv.first;
        s += '|';
        s += kv.second;
        s += '\n';
    }
    return std::vector<uint8_t>(s.begin(), s.end());
}

std::string remove_color(std::string_view text) {
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '`' && i + 1 < text.size()) {
            const unsigned char c = static_cast<unsigned char>(text[i + 1]);
            const bool kode = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                              (c >= '0' && c <= '9') || c == '#';
            if (kode) {
                ++i;  // lewati backtick + satu karakter kode
                continue;
            }
        }
        out.push_back(text[i]);
    }
    return out;
}

// ------------------------------------------------------------ bingkai ------
std::vector<uint8_t> build_packet(NetMessage type, const std::vector<uint8_t> &payload) {
    std::vector<uint8_t> out;
    out.reserve(4 + payload.size());
    put_u32(out, static_cast<uint32_t>(type));
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

bool parse_packet(const uint8_t *data, size_t len, uint32_t &type,
                  const uint8_t *&payload, size_t &payload_len) {
    if (len < 4) return false;
    type = rd_u32(data);
    payload = data + 4;
    payload_len = len - 4;
    return true;
}

// ------------------------------------------------- tabel action|... -------
const std::vector<ActionSpec> &actions() {
    static const std::vector<ActionSpec> tabel = {
#include "actions.inc"
    };
    return tabel;
}

bool build_action(const std::string &name,
                  const std::vector<std::pair<std::string, std::string>> &fields,
                  std::vector<uint8_t> &out) {
    const ActionSpec *spec = nullptr;
    for (const auto &a : actions()) {
        if (name == a.name) {
            spec = &a;
            break;
        }
    }
    if (spec == nullptr) return false;

    std::string s = "action|" + name;
    for (const char *key : spec->fields) {
        for (const auto &kv : fields) {
            if (kv.first == key) {
                s += '\n';
                s += key;
                s += '|';
                s += kv.second;
                break;
            }
        }
    }
    s += '\n';
    out.assign(s.begin(), s.end());
    return true;
}

}  // namespace lucifer
