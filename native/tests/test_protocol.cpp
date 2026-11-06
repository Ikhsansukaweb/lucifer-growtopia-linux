// native/tests/test_protocol.cpp — uji kesetaraan C++ vs Python.
//
// Cara pakai:
//   .venv/bin/python native/tests/gen_golden.py   # tulis golden.bin
//   make -C native test                           # bandingkan
//
// Kalau satu byte beda, port-nya salah. Jangan lanjut ke modul lain.
#include "../protocol.h"

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

static std::string hex(const std::vector<uint8_t> &v, size_t batas = 48) {
    std::string s;
    char b[4];
    for (size_t i = 0; i < v.size() && i < batas; ++i) {
        std::snprintf(b, sizeof b, "%02x", v[i]);
        s += b;
    }
    if (v.size() > batas) s += "...";
    return s;
}

static std::vector<uint8_t> baca(const char *path, bool &ok) {
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        ok = false;
        return {};
    }
    std::vector<uint8_t> v((std::istreambuf_iterator<char>(f)),
                           std::istreambuf_iterator<char>());
    ok = true;
    return v;
}

static void uji_tank() {
    std::printf("== Tank 56 byte ==\n");
    Tank t;
    t.type = 3;
    t.int_x = 10;
    t.int_y = 11;
    t.value = 18;
    t.vector_x = 320.0f;
    t.vector_y = 352.0f;
    auto raw = t.bytes();
    cek("panjang 56 byte tanpa ext", raw.size() == TANK_SIZE,
        std::to_string(raw.size()));

    Tank lagi;
    std::vector<uint8_t> ext;
    cek("parse berhasil", Tank::parse(raw.data(), raw.size(), lagi, ext));
    cek("type bulat balik", lagi.type == 3);
    cek("int_x bulat balik", lagi.int_x == 10);
    cek("value bulat balik", lagi.value == 18);
    cek("vector_x bulat balik", lagi.vector_x == 320.0f);
    cek("ext kosong", ext.empty());

    auto dengan_ext = t.bytes({0xAA, 0xBB});
    cek("ext ikut dihitung", dengan_ext.size() == TANK_SIZE + 2,
        std::to_string(dengan_ext.size()));
    Tank t2;
    std::vector<uint8_t> ext2;
    Tank::parse(dengan_ext.data(), dengan_ext.size(), t2, ext2);
    cek("ext_length = 2", t2.extended_data_length == 2);
    cek("ext isi benar", ext2.size() == 2 && ext2[0] == 0xAA && ext2[1] == 0xBB);

    // ext_length lebih besar dari data nyata -> dipotong, tidak crash.
    auto rusak = dengan_ext;
    rusak[52] = 0xFF;
    rusak[53] = 0x00;
    Tank t3;
    std::vector<uint8_t> ext3;
    Tank::parse(rusak.data(), rusak.size(), t3, ext3);
    cek("ext kepanjangan dipotong", ext3.size() == 2, std::to_string(ext3.size()));

    cek("parse buffer pendek ditolak",
        !Tank::parse(raw.data(), TANK_SIZE - 1, t3, ext3));
}

static void uji_variant() {
    std::printf("== VariantList ==\n");

    VariantList vl;
    vl.append(Variant::from_string("OnSetBux"));
    vl.append(Variant::from_int(4321));
    vl.append(Variant::from_int(1));
    auto ser = vl.serialize();
    cek("serialize tidak kosong", !ser.empty(), hex(ser));
    cek("byte0 = jumlah variant", ser[0] == 3, std::to_string(ser[0]));

    VariantList lagi;
    cek("deserialize berhasil", VariantList::deserialize(ser.data(), ser.size(), lagi));
    cek("func_name terbaca", lagi.func_name() == "OnSetBux", lagi.func_name());
    cek("jumlah variant sama", lagi.size() == 3, std::to_string(lagi.size()));
    cek("arg1 = 4321", lagi.get(1) && lagi.get(1)->as_int32() == 4321,
        lagi.get(1) ? std::to_string(lagi.get(1)->as_int32()) : "null");

    // Bulat balik semua tipe.
    VariantList semua;
    semua.append(Variant::from_string("Uji"));
    semua.append(Variant::from_float(1.5f));
    semua.append(Variant::from_string("halo"));
    semua.append(Variant::from_vec2(1.0f, 2.0f));
    semua.append(Variant::from_vec3(3.0f, 4.0f, 5.0f));
    semua.append(Variant::from_uint(4000000000u));
    semua.append(Variant::from_int(-1234));
    auto s2 = semua.serialize();
    VariantList b2;
    VariantList::deserialize(s2.data(), s2.size(), b2);
    cek("7 variant bulat balik", b2.size() == 7, std::to_string(b2.size()));
    cek("float 1.5", b2.get(1) && b2.get(1)->as_float() == 1.5f);
    cek("string halo", b2.get(2) && b2.get(2)->as_string() == "halo");
    cek("vec2", b2.get(3) && b2.get(3)->as_vec2().y == 2.0f);
    cek("vec3", b2.get(4) && b2.get(4)->as_vec3().z == 5.0f);
    cek("uint besar", b2.get(5) && b2.get(5)->as_uint32() == 4000000000u);
    cek("int negatif", b2.get(6) && b2.get(6)->as_int32() == -1234);
}

static void uji_teks() {
    std::printf("== teks ==\n");
    std::string s = "action|wrench\nnetid|1\n";
    auto f = decode_text(reinterpret_cast<const uint8_t *>(s.data()), s.size());
    cek("action terbaca", f["action"] == "wrench", f["action"]);
    cek("netid terbaca", f["netid"] == "1", f["netid"]);

    // NUL dibuang, '\n' dipertahankan.
    std::string kotor("msg|Fail to login\x00\n", 19);
    auto g = decode_text(reinterpret_cast<const uint8_t *>(kotor.data()), kotor.size());
    cek("NUL dibuang", g["msg"] == "Fail to login", g["msg"]);

    // Kunci tanpa '|' -> nilai kosong.
    std::string polos = "tanpakunci\n";
    auto h = decode_text(reinterpret_cast<const uint8_t *>(polos.data()), polos.size());
    cek("baris tanpa pipa tetap masuk", h.count("tanpakunci") == 1);

    cek("encode urutan tetap",
        encode_text({{"action", "respawn"}}) ==
            std::vector<uint8_t>({'a','c','t','i','o','n','|','r','e','s','p','a','w','n','\n'}));

    // Python: regex `[a-zA-Z0-9#] -> "``" TIDAK dianggap kode (backtick
    // bukan anggota kelas), jadi dua backtick itu dipertahankan.
    cek("remove_color `4 dan `w dibuang",
        remove_color("`4Fail`` to `wlogin") == "Fail`` to login",
        remove_color("`4Fail`` to `wlogin"));
    cek("remove_color tanpa kode", remove_color("polos") == "polos");
    cek("remove_color backtick di akhir", remove_color("abc`") == "abc`");
}

static void uji_action() {
    std::printf("== build_action ==\n");
    std::vector<uint8_t> out;
    // `respawn` BUKAN action (dikirim sebagai paket teks polos), jadi tidak
    // ada di tabel. Yang ada: `growid`, `quit`, `store`, dst.
    cek("growid dikenal", build_action("growid", {}, out));
    cek("growid = action|growid\\n",
        std::string(out.begin(), out.end()) == "action|growid\n",
        std::string(out.begin(), out.end()));

    cek("storenavigate dikenal",
        build_action("storenavigate", {{"item", "locks"}, {"selection", "upgrade_backpack"}}, out));
    cek("storenavigate urutan tabel",
        std::string(out.begin(), out.end()) ==
            "action|storenavigate\nitem|locks\nselection|upgrade_backpack\n",
        std::string(out.begin(), out.end()));

    cek("action tak dikenal ditolak", !build_action("tidakada", {}, out));

    // Field di luar tabel diabaikan (bukan error).
    cek("field asing diabaikan",
        build_action("growid", {{"aneh", "1"}}, out) &&
            std::string(out.begin(), out.end()) == "action|growid\n");

    cek("tabel punya 75 action", actions().size() == 75,
        std::to_string(actions().size()));
}

static void uji_bingkai() {
    std::printf("== bingkai paket ==\n");
    auto pkt = build_packet(NetMessage::GamePacket, {1, 2, 3});
    cek("panjang = 4 + payload", pkt.size() == 7, std::to_string(pkt.size()));
    uint32_t tipe = 0;
    const uint8_t *payload = nullptr;
    size_t plen = 0;
    cek("parse berhasil", parse_packet(pkt.data(), pkt.size(), tipe, payload, plen));
    cek("tipe = 4", tipe == 4, std::to_string(tipe));
    cek("payload 3 byte", plen == 3);
    cek("payload isi", payload[0] == 1 && payload[2] == 3);
    cek("buffer pendek ditolak", !parse_packet(pkt.data(), 3, tipe, payload, plen));
}

static void uji_golden() {
    std::printf("== golden (dibandingkan dengan Python) ==\n");
    bool ok = false;
    auto golden = baca("native/tests/golden.bin", ok);
    if (!ok) golden = baca("tests/golden.bin", ok);
    if (!ok) {
        cek("golden.bin ada", false,
            "jalankan: .venv/bin/python native/tests/gen_golden.py");
        return;
    }

    // Format golden: [u32 panjang][bytes] berulang, untuk tiap kasus.
    size_t off = 0;
    int kasus = 0;
    int cocok = 0;
    while (off + 4 <= golden.size()) {
        uint32_t n = static_cast<uint32_t>(golden[off]) |
                     (static_cast<uint32_t>(golden[off + 1]) << 8) |
                     (static_cast<uint32_t>(golden[off + 2]) << 16) |
                     (static_cast<uint32_t>(golden[off + 3]) << 24);
        off += 4;
        if (off + n > golden.size()) break;
        std::vector<uint8_t> harap(golden.begin() + off, golden.begin() + off + n);
        off += n;
        ++kasus;

        // Bangun ulang kasus yang sama dengan kode C++.
        std::vector<uint8_t> dapat;
        switch (kasus) {
            case 1: {  // Tank kosong
                Tank t;
                dapat = t.bytes();
                break;
            }
            case 2: {  // Tank penuh
                Tank t;
                t.type = 3; t.object_type = 1; t.jump_count = 2; t.animation_type = 3;
                t.net_id = 12345; t.target_net_id = -7; t.flags = 0x30;
                t.float_variable = 1.25f; t.value = 18;
                t.vector_x = 320.0f; t.vector_y = 352.0f;
                t.vector_x2 = -1.5f; t.vector_y2 = 2.5f;
                t.particle_rotation = 90.0f; t.int_x = -3; t.int_y = 44;
                dapat = t.bytes({9, 8, 7});
                break;
            }
            case 3: {  // VariantList campur
                VariantList vl;
                vl.append(Variant::from_string("OnDialogRequest"));
                vl.append(Variant::from_string("embed_data|netID|1\nadd_popup_name|WrenchMenu|\n"));
                vl.append(Variant::from_int(-42));
                vl.append(Variant::from_uint(4294967295u));
                vl.append(Variant::from_float(3.5f));
                vl.append(Variant::from_vec2(1.0f, 2.0f));
                vl.append(Variant::from_vec3(3.0f, 4.0f, 5.0f));
                dapat = vl.serialize();
                break;
            }
            case 4: {  // VariantList kosong
                VariantList vl;
                dapat = vl.serialize();
                break;
            }
            case 5: {  // teks action|storenavigate
                build_action("storenavigate",
                             {{"item", "locks"}, {"selection", "upgrade_backpack"}}, dapat);
                break;
            }
            case 6: {  // bingkai + tank
                Tank t;
                t.type = 11; t.value = 777; t.vector_x = 384.0f; t.vector_y = 352.0f;
                t.int_x = 1;
                dapat = build_packet(NetMessage::GamePacket, t.bytes());
                break;
            }
            default:
                continue;
        }
        if (dapat == harap) {
            ++cocok;
        } else {
            cek("kasus golden cocok", false,
                "kasus " + std::to_string(kasus) + ": dapat " + hex(dapat) +
                    " harap " + hex(harap));
        }
    }
    cek("semua kasus golden cocok", kasus > 0 && cocok == kasus,
        std::to_string(cocok) + "/" + std::to_string(kasus));
}

int main() {
    std::printf("== UJI PROTOKOL NATIVE ==\n");
    uji_tank();
    uji_variant();
    uji_teks();
    uji_action();
    uji_bingkai();
    uji_golden();
    std::printf("\n lulus: %d   gagal: %d\n", LULUS, GAGAL);
    return GAGAL == 0 ? 0 : 1;
}
