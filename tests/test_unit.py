#!/usr/bin/env python3
"""
tests/test_unit.py — Uji unit tanpa jaringan.

Menguji bagian yang bisa diverifikasi offline:
  * codec paket: Tank, Variant, VariantList, teks (round-trip)
  * hash Growtopia
  * items.dat: pembacaan 15.934 item + ID yang diketahui
  * parser dunia + flag tile
  * API Lua: enum, struct, variant, RTVAR, HttpClient, addBot, bot live-state
  * bot: semua aksi menghasilkan paket yang benar

Jalankan:  .venv/bin/python tests/test_unit.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = FAIL = 0
GAGAL: list[str] = []


def catat_gagal(nama: str) -> None:
    global FAIL
    FAIL += 1
    GAGAL.append(nama)


def cek(nama: str, kondisi: bool, detail: str = "") -> bool:
    global PASS
    if kondisi:
        PASS += 1
        print(f"  \033[32m✓\033[0m {nama}" + (f"  \033[90m{detail}\033[0m" if detail else ""))
    else:
        catat_gagal(nama)
        print(f"  \033[31m✗\033[0m {nama}" + (f"  \033[90m{detail}\033[0m" if detail else ""))
    return kondisi


def bagian(t: str) -> None:
    print(f"\n\033[1;36m== {t} ==\033[0m")


# --------------------------------------------------------------------------- #
def test_protocol() -> None:
    bagian("1. Codec paket (Tank / Variant / teks)")
    from lucifer.protocol import (
        NetMessage, Tank, Variant, VariantList,
        build_packet, decode_text, encode_text, pack_tank, parse_packet, unpack_tank,
    )

    # -- Tank round-trip ---------------------------------------------------- #
    t = Tank(type=3, net_id=12345, value=242, int_x=10, int_y=20,
             float_variable=1.5, vector_x=32.0, vector_y=64.0)
    raw = pack_tank(t)
    cek("Tank: panjang paket wajar", len(raw) >= 56, f"{len(raw)} byte")
    t2, ext = unpack_tank(raw)
    cek("Tank: type", t2.type == 3)
    cek("Tank: net_id", t2.net_id == 12345)
    cek("Tank: value (id item)", t2.value == 242)
    cek("Tank: int_x/int_y", t2.int_x == 10 and t2.int_y == 20)
    cek("Tank: float_variable", abs(t2.float_variable - 1.5) < 0.001)
    cek("Tank: vector_x", abs(t2.vector_x - 32.0) < 0.001)

    # -- paket berbingkai ---------------------------------------------------- #
    pkt = build_packet(NetMessage.GenericText, b"action|enter_game\n")
    mtype, payload = parse_packet(pkt)
    cek("paket: tipe terbaca", mtype == NetMessage.GenericText, f"{mtype}")
    cek("paket: payload utuh", payload == b"action|enter_game\n", repr(payload))

    # -- teks --------------------------------------------------------------- #
    fields = {"action": "log", "msg": "Halo dunia"}
    enc = encode_text(fields)
    dec = decode_text(enc)
    cek("teks: action", dec.get("action") == "log")
    cek("teks: msg", dec.get("msg") == "Halo dunia")

    # -- Variant ------------------------------------------------------------ #
    v = Variant.from_int(42)
    cek("Variant: int", v.as_int32() == 42)
    v = Variant.from_string("halo")
    cek("Variant: string", v.as_string() == "halo")
    v = Variant.from_float(2.5)
    cek("Variant: float", abs(v.as_float() - 2.5) < 0.001)

    # -- VariantList -------------------------------------------------------- #
    vl = VariantList()
    vl.append(Variant.from_string("OnConsoleMessage"))
    vl.append(Variant.from_string("pesan uji"))
    vl.append(Variant.from_int(7))
    cek("VariantList: panjang", len(vl) == 3, f"{len(vl)}")
    cek("VariantList: elemen[0]", vl.get(0).as_string() == "OnConsoleMessage")
    cek("VariantList: elemen[2]", vl.get(2).as_int32() == 7)


def test_hash() -> None:
    bagian("2. Hash Growtopia + klv (dicocokkan dengan implementasi C resmi)")
    import hashlib

    from lucifer.hash import HashMode, generate_klv, hash_gt, random_hex, random_mac

    h = hash_gt(b"Growtopia")
    cek("hash_gt: menghasilkan bilangan", isinstance(h, int), str(h))
    cek("hash_gt: deterministik", hash_gt(b"Growtopia") == h)
    cek("hash_gt: beda input beda hash", hash_gt(b"Growtopia") != hash_gt(b"Growtopi"))
    h2 = hash_gt(b"Growtopia\x00sisa", HashMode.NullTerminated)
    cek("hash_gt: mode NullTerminated", isinstance(h2, int))

    # generate_klv HARUS sama dengan implementasi C resmi (utils.c: generateKlv)
    def sha256(s: str) -> str:
        return hashlib.sha256(str(s).encode()).hexdigest()

    def klv_referensi(game_version, hash_, rid, protocol):
        fmt = (
            "%s198c4213effdbeb93ca64ea73c1f505f%s82a2e2940dd1b100f0d41d23b0bb6e4d"
            "%sc64f7f09cdd0c682e730d2f936f36ac2%s27d8da6190880ce95591215f2c9976a6"
        ) % (sha256(game_version), sha256(hash_), sha256(protocol), sha256(rid))
        return sha256(fmt)

    for gv, hh, rid, pr in (("5.4", "", "", "225"),
                            ("5.40", "abc123", "rid456", "225"),
                            ("4.63", "deadbeef", "cafe", "225")):
        a = klv_referensi(gv, hh, rid, pr)
        b = generate_klv(gv, hh, rid, pr)
        cek(f"klv cocok dgn implementasi C (v{gv})", a == b, f"{b[:16]}...")
    cek("klv: panjang 64 hex", len(generate_klv("5.4", "x", "y", "225")) == 64)

    klv = generate_klv("5.4", "123456789", "abcdef0123456789abcdef0123456789", "225")
    cek("klv: 64 karakter hex", len(klv) == 64 and all(c in "0123456789abcdef" for c in klv))
    cek("random_hex(8): panjang", len(random_hex(8)) == 8)
    cek("random_mac: format", random_mac().count(":") == 5, random_mac())


def test_items() -> None:
    bagian("3. items.dat (15.934 item)")
    from lucifer.items import ItemDatabase

    p = ROOT / "data" / "items.dat"
    if not p.exists():
        cek("items.dat tersedia", False, f"{p} tidak ada")
        return
    db = ItemDatabase.from_file(p)
    cek("jumlah item", len(db) > 15000, f"{len(db)} item")
    cek("versi items.dat", db.version >= 20, f"v{db.version}")

    # ID yang sudah diketahui dari Growtopia asli
    for iid, nama in ((242, "World Lock"), (2, "Dirt"), (17, "Grass Seed"),
                      (32, "Wrench"), (18, "Fist"), (12, "Door")):
        it = db.get(iid)
        cek(f"item #{iid} = {nama}", it is not None and it.name == nama,
            it.name if it else "tidak ada")

    found = db.find("World Lock", exact=True)
    cek("find('World Lock') menemukan", len(found) >= 1, f"{len(found)} hasil")
    cek("find() case-insensitive", len(db.find("world lock")) >= 1)
    cek("name_of(242)", db.name_of(242) == "World Lock")
    cek("__contains__", 242 in db and 999999 not in db)

    seed = db.get(17)
    cek("Grass Seed punya grow_time", seed.grow_time > 0, f"{seed.grow_time} detik")
    cek("World Lock adalah block (property)", db.get(242).is_block or db.get(242).material == 3)
    cek("Grass Seed adalah seed (property)", db.get(17).is_seed, "is_seed=True")
    cek("Dirt bukan clothing (property)", not db.get(2).is_clothing)


def test_world() -> None:
    bagian("4. Parser dunia + flag tile")
    from lucifer.world import TILE_FLAGS, World, parse_world

    cek("TILE_FLAGS punya 'locked' (huruf kecil)", "locked" in TILE_FLAGS)
    cek("TILE_FLAGS punya 'public' (huruf kecil)", "public" in TILE_FLAGS)
    cek("TILE_FLAGS punya 'LOCKED' (huruf besar)", "LOCKED" in TILE_FLAGS)
    cek("TILE_FLAGS: nilai integer", all(isinstance(v, int) for v in TILE_FLAGS.values()))
    cek("TILE_FLAGS: alias huruf kecil = besar",
        TILE_FLAGS["locked"] == TILE_FLAGS["LOCKED"] == 0x0002)

    # bangun payload dunia sesuai format asli (version >= 25)
    name = b"TESTSWORLD"
    buf = bytearray()
    buf += (26).to_bytes(2, "little")      # version (harus >= 25)
    buf += (0).to_bytes(4, "little")       # flags
    buf += len(name).to_bytes(2, "little") + name   # nama (string_u16)
    buf += (10).to_bytes(4, "little")      # lebar
    buf += (8).to_bytes(4, "little")       # tinggi
    buf += (2).to_bytes(4, "little")       # jumlah tile (declared)
    buf += bytes(5)                        # skip(5)
    # setiap tile = fg(u16) + bg(u16) + parent(u16) + flags(u16) = 8 byte
    buf += (0).to_bytes(2, "little") + (0).to_bytes(2, "little") + bytes(4)      # tile 0
    buf += (17).to_bytes(2, "little") + (0).to_bytes(2, "little") + bytes(4)     # tile 1
    buf += bytes(12)                       # skip(12)
    buf += (0).to_bytes(4, "little")       # jumlah objek jatuh
    buf += (0).to_bytes(4, "little")       # last uid
    buf += (0).to_bytes(2, "little")       # base weather
    buf += (0).to_bytes(2, "little")
    buf += (0).to_bytes(2, "little")       # current weather

    w = parse_world(bytes(buf))
    cek("parse_world: tanpa error", not w.error, w.error or "ok")
    cek("parse_world: versi", w.version == 26, str(w.version))
    cek("parse_world: nama dunia", w.name == "TESTSWORLD", w.name)
    cek("parse_world: ukuran", w.width == 10 and w.height == 8, f"{w.width}x{w.height}")
    cek("parse_world: jumlah tile", len(w.tiles) == 2, f"{len(w.tiles)} tile")
    if len(w.tiles) >= 2:
        cek("parse_world: tile 1 fg = 17", w.tiles[1].fg == 17, str(w.tiles[1].fg))
        cek("parse_world: koordinat tile", w.tiles[1].x == 1 and w.tiles[1].y == 0,
            f"({w.tiles[1].x},{w.tiles[1].y})")
    cek("parse_world: tile() berfungsi", w.tile(1, 0) is not None)

    cek("World punya method tile()", hasattr(World, "tile"))


def test_lua_api() -> None:
    bagian("5. API Lua Lucifer V1.8")
    from lucifer.account import Account
    from lucifer.items import ItemDatabase
    from lucifer.lua_api import ENUMS, LuaEngine, remove_color

    cek("remove_color", remove_color("`4Nuron`0Lucifer") == "NuronLucifer")
    cek("remove_color: tanpa kode", remove_color("biasa") == "biasa")

    # enum penting
    for nama in ("BotStatus", "CaptchaStatus", "Method", "Event", "VariantType",
                 "TileType", "TileFlag", "PacketType", "LoginMethod"):
        cek(f"enum {nama} ada", nama in ENUMS)
    cek("BotStatus.online", ENUMS["BotStatus"]["online"] == "online")
    cek("Event.variantlist", ENUMS["Event"]["variantlist"] == "variantlist")
    cek("PacketType punya PACKET_STATE", "PACKET_STATE" in ENUMS["PacketType"])
    cek("TileFlag punya locked", "locked" in ENUMS["TileFlag"])

    db = None
    p = ROOT / "data" / "items.dat"
    if p.exists():
        db = ItemDatabase.from_file(p)

    acc = Account(username="uji", password="", method="legacy", label="uji")
    engine = LuaEngine(accounts=[acc], items_db=db, scripts_dir=ROOT / "scripts",
                       data_dir=ROOT / "data", username="tester")
    engine._new_bot(acc, "uji")

    hasil = {}

    def jalankan(src: str) -> None:
        try:
            engine.lua.execute(src)
        except Exception as e:  # noqa: BLE001
            hasil["error"] = f"{type(e).__name__}: {e}"

    jalankan("""
      bot = getBot()
      hasil = {}
      hasil.getBot = type(bot)
      hasil.enum = BotStatus.online
      hasil.pkt = PacketType.PACKET_STATE
      hasil.info = getInfo(242).name
      hasil.info_str = getInfo("Dirt").id
      hasil.color = removeColor("`4X`0Y")
      hasil.user = getUsername()
      hasil.acc_const = GOOGLE
      local v = variant.new(); v:set(42); hasil.variant_int = v:getInt()
      v:set("halo"); hasil.variant_str = v:getString()
      local vl = variantlist.new(); vl:append(); hasil.vl_size = vl:size()
      local rv = RTVAR.new(); rv:append("action","dialog_return",false)
      hasil.rtvar = rv:dump()
      local p = GameUpdatePacket.new(); p.type = 3; hasil.pkt_type = p.type
      hasil.http_ok = (HttpClient.new() ~= nil)
      hasil.embed_ok = (Embed.new() ~= nil)
      hasil.world_ok = (bot:getWorld() ~= nil)
      hasil.inv_ok = (bot:getInventory() ~= nil)
      hasil.status = bot.status
      hasil.tile_xy = getTile(0, 0)
    """)

    if "error" in hasil:
        cek("skrip Lua tanpa error", False, hasil["error"])
        return
    cek("skrip Lua tanpa error", True)

    g = engine.lua.globals()["hasil"]
    cek("getBot() mengembalikan tabel", g["getBot"] == "table")
    cek("BotStatus.online", g["enum"] == "online")
    cek("PacketType.PACKET_STATE", int(g["pkt"]) == 0)
    cek("getInfo(242).name", g["info"] == "World Lock", str(g["info"]))
    cek("getInfo('Dirt').id", int(g["info_str"]) == 2)
    cek("removeColor", g["color"] == "XY")
    cek("getUsername", g["user"] == "tester")
    cek("konstanta GOOGLE = 1", int(g["acc_const"]) == 1)
    cek("variant set/get int", int(g["variant_int"]) == 42)
    cek("variant set/get string", g["variant_str"] == "halo")
    cek("variantlist append/size", int(g["vl_size"]) == 1)
    cek("RTVAR dump", g["rtvar"] == "action|dialog_return", str(g["rtvar"]))
    cek("GameUpdatePacket.type", int(g["pkt_type"]) == 3)
    cek("HttpClient.new()", bool(g["http_ok"]))
    cek("Embed.new()", bool(g["embed_ok"]))
    cek("bot:getWorld()", bool(g["world_ok"]))
    cek("bot:getInventory()", bool(g["inv_ok"]))
    cek("bot.status live", g["status"] == "offline", str(g["status"]))
    cek("getTile() di dunia kosong = nil", g["tile_xy"] is None)


def test_addbot_tabel() -> None:
    bagian("6. addBot: tabel akun (LEGACY/GOOGLE/TOKEN/APPLE/UBI)")
    from lucifer.lua_api import LuaEngine

    engine = LuaEngine(scripts_dir=ROOT / "scripts", data_dir=ROOT / "data")
    engine.lua.execute("""
      hasil = {}
      local a = addBot({ type = LEGACY, growid = "AkunLama", password = "sandi",
                         mac = "02:00:00:00:00:00" })
      hasil.legacy_nama = a.name
      hasil.legacy_metode = a:getLogin().method
      hasil.legacy_mac = a:getLogin().mac

      local b = addBot({ type = TOKEN, token = "ltoken_uji_123", growid = "AkunToken" })
      hasil.token_metode = b:getLogin().method
      hasil.token_ada = (b:getToken() ~= "")

      local c = addBot({ type = GOOGLE, mail = "a@b.com", password = "x" })
      hasil.google_metode = c:getLogin().method
      hasil.google_nama = c.name

      local d = addBot({ type = APPLE, mail = "x@icloud.com", password = "y" })
      hasil.apple_metode = d:getLogin().method

      local e = addBot({ type = UBICONNECT, mail = "u@b.com", password = "z" })
      hasil.ubi_metode = e:getLogin().method

      -- bentuk lama tetap jalan
      local f = addBot("BotLama", "sandiLama")
      hasil.lama_nama = f.name
      hasil.lama_metode = f:getLogin().method

      -- setToken saat berjalan
      b:setToken("ltoken_baru_999")
      hasil.set_token = b:getToken()

      -- updateProxy
      hasil.update_proxy = b:updateProxy({ HostName = "127.0.0.1:1080", Username = "u", Password = "p" })
    """)
    g = engine.lua.globals()["hasil"]
    cek("LEGACY: nama", g["legacy_nama"] == "AkunLama", str(g["legacy_nama"]))
    cek("LEGACY: metode = legacy", g["legacy_metode"] == "legacy", str(g["legacy_metode"]))
    cek("LEGACY: mac tersimpan", g["legacy_mac"] == "02:00:00:00:00:00", str(g["legacy_mac"]))
    cek("TOKEN: metode = token", g["token_metode"] == "token", str(g["token_metode"]))
    cek("TOKEN: ltoken terpasang", bool(g["token_ada"]))
    cek("GOOGLE: metode = google", g["google_metode"] == "google", str(g["google_metode"]))
    cek("GOOGLE: nama dari mail", g["google_nama"] == "a@b.com", str(g["google_nama"]))
    cek("APPLE: metode = apple", g["apple_metode"] == "apple", str(g["apple_metode"]))
    cek("UBICONNECT: metode = ubiconnect", g["ubi_metode"] == "ubiconnect", str(g["ubi_metode"]))
    cek("bentuk lama: nama", g["lama_nama"] == "BotLama", str(g["lama_nama"]))
    cek("bentuk lama: metode growid", g["lama_metode"] == "growid", str(g["lama_metode"]))
    cek("setToken() mengubah ltoken", g["set_token"] == "ltoken_baru_999", str(g["set_token"]))
    cek("updateProxy()", bool(g["update_proxy"]))


def test_perintah_tanpa_argumen() -> None:
    bagian("6b. Runner: respawn/collect/say tanpa nama bot")
    from types import SimpleNamespace

    from lucifer.runner import Runner

    dipanggil: list[str] = []
    palsu = SimpleNamespace(
        respawn=lambda: dipanggil.append("respawn") or True,
        collect=lambda range_=3: dipanggil.append(f"collect:{range_}") or 0,
        say=lambda teks: dipanggil.append(f"say:{teks}") or True,
    )
    r = Runner()
    r.engine = SimpleNamespace(bots={"uji": palsu}, parent=palsu)

    # Tombol GUI mengirim perintah TELANJANG (label disisipkan web.py).
    cek("respawn tanpa argumen", r.command("respawn").get("ok") is True)
    cek("collect tanpa argumen", r.command("collect").get("ok") is True)
    cek("collect <radius>", r.command("collect 5").get("collected") == 0)
    cek("collect meneruskan radius", "collect:5" in dipanggil)
    cek("respawn kedua", r.command("respawn").get("ok") is True)
    cek("say tanpa label", r.command("say hai").get("ok") is True)
    cek("say meneruskan teks", "say:hai" in dipanggil)
    cek(r.command("respawn tidakada").get("ok") is False,
        "label tak dikenal harus gagal, bukan diam-diam ke bot lain")


def test_bot_aksi() -> None:
    bagian("7. Bot: semua aksi mengirim paket yang benar")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import NetMessage, decode_text, parse_packet, unpack_tank

    acc = Account(username="uji", password="", method="legacy", label="uji")
    bot = Bot(account=acc, label="uji")

    # Bot mengirim lewat DUA jalur: send_text (paket teks: say/warp/leaveWorld)
    # dan send_raw (paket Tank: place/hit/wrench/...). Keduanya harus dipantau.
    teks: list[bytes] = []
    tank: list[bytes] = []

    def tangkap_teks(mtype: int, body: bytes) -> bool:
        teks.append(bytes([mtype]) + b"|" + body)
        return True

    def tangkap_raw(pkt, extended: bytes = b"") -> bool:
        tank.append(pkt)
        return True

    bot.send_text = tangkap_teks  # type: ignore[method-assign]
    bot.send_raw = tangkap_raw  # type: ignore[method-assign]

    aksi = [
        ("say", lambda: bot.say("halo dunia")),
        ("warp", lambda: bot.warp("FARM", "0")),
        ("place", lambda: bot.place(10, 11, 2)),
        ("hit", lambda: bot.hit(10, 10)),
        ("wrench", lambda: bot.wrench(10, 10)),
        ("drop", lambda: bot.drop(242, 1)),
        ("trash", lambda: bot.trash(2, 1)),
        ("moveTile", lambda: bot.moveTile(12, 12)),
        ("leaveWorld", lambda: bot.leaveWorld()),
        ("respawn", lambda: bot.respawn()),
    ]
    # collectObject butuh objek nyata di dunia (paket type 11 memakai posisi
    # piksel + uid objek), jadi daftarkan satu item jatuh dulu.
    from lucifer.world import DroppedItem
    bot.world.dropped.append(DroppedItem(item_id=242, x=384.0, y=352.0, count=1, uid=12345))
    aksi.append(("collectObject", lambda: bot.collectObject(12345, 3)))
    for nama, fn in aksi:
        sebelum = len(teks) + len(tank)
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            cek(f"{nama}()", False, f"{type(e).__name__}: {e}")
            continue
        sesudah = len(teks) + len(tank)
        cek(f"{nama}() mengirim paket", sesudah > sebelum, f"{sesudah - sebelum} paket")

    cek("total paket terkirim", len(teks) + len(tank) >= len(aksi),
        f"{len(teks)} teks + {len(tank)} tank")

    # periksa isi paket teks (say & warp)
    isi = [t.split(b"|", 1)[1].decode("utf-8", "replace") for t in teks]
    cek("paket 'say' berisi teks", any("halo dunia" in s for s in isi), str(isi[:2])[:90])
    cek("paket 'say' pakai action|input", any("action|input" in s for s in isi))
    cek("paket 'warp' berisi nama dunia", any("FARM" in s for s in isi), str(isi[:3])[:90])
    cek("paket 'warp' pakai join_request", any("join_request" in s for s in isi))

    # periksa paket Tank (place/hit mengirim koordinat)
    from lucifer.protocol import Tank as _Tank

    tanks = [t for t in tank if isinstance(t, _Tank)]
    cek("paket Tank: place mengirim koordinat + item",
        any(t.int_x == 10 and t.value == 2 for t in tanks),
        f"{len(tanks)} paket Tank: {[(t.int_x, t.int_y, t.value) for t in tanks]}")
    cek("paket Tank: hit mengirim koordinat",
        any(t.int_x == 10 and t.int_y == 10 for t in tanks))
    # tileChange: type 3 (bukan 7) + value item. 18 = Fist, 32 = Wrench.
    # Posisi piksel (vector_x/vector_y) wajib; server memakainya untuk
    # validasi jangkauan. Tile kosong -> posisi tile (x*32).
    cek("hit = type 3 value 18 (Fist) + posisi piksel",
        any(t.type == 3 and t.value == 18 and t.int_x == 10
            and abs(t.vector_x - 320.0) < 0.5 for t in tanks),
        str([(t.type, t.value, t.vector_x) for t in tanks]))
    cek("place = type 3 value item + posisi piksel",
        any(t.type == 3 and t.value == 2 and t.int_x == 10 and t.int_y == 11
            and abs(t.vector_x - 320.0) < 0.5 and abs(t.vector_y - 352.0) < 0.5
            for t in tanks),
        str([(t.type, t.value, t.vector_x, t.vector_y) for t in tanks]))
    cek("wrench tile = type 3 value 32",
        any(t.type == 3 and t.value == 32 for t in tanks),
        str([(t.type, t.value) for t in tanks]))
    # collect: type 11 (ItemActivateObjectRequest), posisi PIKSEl + uid objek
    # (bukan action|collect — versi lama tidak pernah direspons server).
    cek("collectObject memakai Tank type 11",
        any(t.type == 11 for t in tanks),
        f"tipe: {[t.type for t in tanks]}")
    cek("collectObject mengirim posisi piksel + uid",
        any(t.type == 11 and t.value == 12345
            and abs(t.vector_x - 384.0) < 0.5 and abs(t.vector_y - 352.0) < 0.5
            for t in tanks),
        str([(t.type, t.value, t.vector_x, t.vector_y) for t in tanks]))
    # drop/trash memakai paket TEKS (action|drop), bukan Tank
    cek("paket 'drop' pakai action|drop + itemID",
        any("action|drop" in s and "itemID|242" in s for s in isi), str(isi)[:120])
    cek("paket 'trash' pakai action|trash",
        any("action|trash" in s for s in isi))
    cek("paket 'leaveWorld' pakai quit_to_exit",
        any("quit_to_exit" in s for s in isi))
    cek("paket 'moveTile' memakai Tank State/move",
        any(t.type in (0, 1) for t in tanks))

    # moveTo: satu tile per paket + netid 0 (pola deltaX). Lompatan jauh
    # ditolak validasi kecepatan server, jadi harus bertahap.
    from lucifer.bot import Player as _Player
    bot.local = _Player(netid=9, posx=1440.0, posy=736.0)
    bot.local.isLocalPlayer = True
    tank.clear()
    cek("moveTo(3,0) benar", bot.moveTo(3, 0) is True)
    langkah = [t for t in tank if isinstance(t, _Tank)]
    cek("moveTo mengirim 3 paket, bukan 1", len(langkah) == 3, f"{len(langkah)} paket")
    cek("moveTo memakai net_id 0", all(t.net_id == 0 for t in langkah))
    cek("moveTo berakhir di posisi target",
        bot.local.posx == 1440.0 + 96 and bot.local.posy == 736.0,
        f"{bot.local.posx},{bot.local.posy}")

    # pathfinding
    path = bot.getPath(5, 5)
    cek("getPath() mengembalikan daftar", isinstance(path, list), f"{len(path)} langkah")

    # auto-collect otomatis saat item jatuh (type 14 netid -1).
    # Server TIDAK meminta bot menekan tombol: deltaX bereaksi pada paket ini.
    # `value` pada paket ini = item_id, uid baru dibuat dari World.last_uid.
    from lucifer.protocol import Tank as _T2
    bot.auto_collect = True
    bot.auto_collect_radius = 3
    bot._running = True
    bot.local.posx, bot.local.posy = 384.0, 352.0
    bot.world.dropped.clear()
    bot.world.last_uid = 100
    tank.clear()
    # Server mengirim uid objek di `target_net_id` (Gurotopia: `.uid`).
    bot._apply_item_change(
        _T2(type=14, net_id=0xFFFFFFFF, target_net_id=101, value=555,
            float_variable=1.0, vector_x=400.0, vector_y=360.0), b"")
    baru = [d for d in bot.world.dropped if d.item_id == 555]
    cek("item jatuh menambah world.dropped", bool(baru), str(bot.world.dropped))
    cek("uid diambil dari target_net_id (bukan dikarang)",
        bool(baru) and baru[0].uid == 101,
        str([d.uid for d in baru]))
    import time as _t
    _t.sleep(0.15)   # auto-ambil menunggu 30 ms lalu kirim type 11
    cek("auto-collect mengirim type 11 tanpa disuruh",
        any(t.type == 11 and t.value == 101 for t in tank),
        str([(t.type, t.value) for t in tank]))

    # Server retail mengirim uid=-1 pada drop (hasil decode hex mentah),
    # tetapi paket pickup memakai uid. Counter server ditiru: last_uid + 1.
    bot.world.dropped.clear()
    tank.clear()
    bot._apply_item_change(
        _T2(type=14, net_id=0xFFFFFFFF, value=777,
            float_variable=1.0, vector_x=400.0, vector_y=360.0), b"")
    # uid DITIRU dari counter. Terbukti: tiga drop berurutan menghasilkan
    # 10, 11, 12 — sama dengan uid asli yang diberikan server saat rejoin.
    cek("uid=-1 -> uid dari counter",
        bot.world.dropped and bot.world.dropped[0].uid == 102,
        str([d.uid for d in bot.world.dropped]))
    cek("item id tetap dari value",
        bot.world.dropped and bot.world.dropped[0].item_id == 777,
        str([d.item_id for d in bot.world.dropped]))

    # item diambil orang lain (netid pemain) -> hilang dari world.dropped
    bot._apply_item_change(_T2(type=14, net_id=6, value=101), b"")
    cek("pickup menghapus objek dari world.dropped",
        not any(d.uid == 101 for d in bot.world.dropped), str(bot.world.dropped))


def test_login_payload_mobile() -> None:
    """Uji paket login memakai identitas klien ANDROID (temuan 2026-09-29).

    Kalau bot mengaku klien PC (`platformID|0,1,1`), server Growtopia menolak
    akun mobile dengan `Authentication_error|28` + "UPDATE REQUIRED! ...
    GrowtopiaInstaller.exe". Dengan `platformID|3,1,1` login DITERIMA
    (server membalas `OnSendToServer`).
    """
    bagian("8. Paket login: identitas klien mobile (platformID 3,1,1)")
    from lucifer.account import (
        DEVICE_VERSION_MOBILE,
        PLATFORM_MOBILE,
        Account,
    )

    cek("PLATFORM_MOBILE = platformID|3,1,1",
        PLATFORM_MOBILE == "platformID|3,1,1", PLATFORM_MOBILE)
    cek("DEVICE_VERSION_MOBILE = 29", DEVICE_VERSION_MOBILE == "29")

    # akun token (hasil login Google/Apple)
    acc = Account(username="IsanLucu", ltoken="TOKEN_UJI", method="token",
                  label="uji", version="5.58")
    body = acc.login_payload().decode()

    cek("paket memuat platformID|3,1,1", "platformID|3,1,1" in body)
    cek("TIDAK memuat platformID|0,1,1 (klien PC)",
        "platformID|0,1,1" not in body)
    cek("paket memuat deviceVersion|29", "deviceVersion|29" in body)
    cek("paket memuat ltoken", "ltoken|TOKEN_UJI" in body)
    cek("paket memuat game_version|5.58", "game_version|5.58" in body)

    # akun legacy juga harus memakai identitas mobile
    acc2 = Account(username="Uji", password="rahasia", method="legacy",
                   label="uji2", version="5.58")
    body2 = acc2.login_payload().decode()
    cek("legacy: pakai platformID|3,1,1", "platformID|3,1,1" in body2)
    cek("legacy: pakai tankIDName", "tankIDName|Uji" in body2)
    cek("legacy: pakai tankIDPass", "tankIDPass|rahasia" in body2)


def test_client_data_konsisten() -> None:
    """Uji client_data memakai identitas Android yang KONSISTEN.

    Temuan 2026-09-29: `login_payload()` sudah memakai `platformID|3,1,1`
    (mobile), tapi `build_client_data()` dan `client_data_minimal()` masih
    memakai `0,1,1` (PC) + `deviceVersion|0`. Identitas yang tidak konsisten
    seperti ini membuat request token tampak "gagal" tanpa sebab jelas.
    """
    bagian("9. client_data: identitas Android konsisten")
    import base64

    from lucifer.account import (
        DEVICE_VERSION_MOBILE,
        PLATFORM_ID_MOBILE,
        build_client_data,
        client_data_minimal,
    )

    cek("PLATFORM_ID_MOBILE = 3,1,1", PLATFORM_ID_MOBILE == "3,1,1")

    blok = build_client_data(username="Uji", password="rahasia")
    cek("build_client_data: platformID|3,1,1", "platformID|3,1,1" in blok)
    cek("build_client_data: deviceVersion|29",
        f"deviceVersion|{DEVICE_VERSION_MOBILE}" in blok)
    cek("build_client_data: TIDAK ada platformID|0,1,1",
        "platformID|0,1,1" not in blok)

    mini = base64.b64decode(client_data_minimal()).decode()
    cek("client_data_minimal: platformID|3,1,1", "platformID|3,1,1" in mini)
    cek("client_data_minimal: deviceVersion|29", "deviceVersion|29" in mini)
    cek("client_data_minimal: TIDAK ada platformID|0,1,1",
        "platformID|0,1,1" not in mini)
    # meta harus bisa disisipkan (klien asli mengirimkannya)
    cek("client_data_minimal: meta bisa diisi",
        "meta|ABC123" in base64.b64decode(
            client_data_minimal(meta="ABC123")).decode())


def test_remove_color() -> None:
    """Kode warna Growtopia harus dibuang dari pesan server.

    Server mengirim `` `4Fail to login. Login token is invalid. `` —
    backtick+4 itu kode warna, bukan bagian pesan. Tanpa dibersihkan, log
    dashboard menampilkan pesan yang membingungkan.
    """
    bagian("10. remove_color: pesan server bersih")
    from lucifer.protocol import decode_text, remove_color

    f = decode_text(b"action|log\nmsg|`4Fail to login. Login token is invalid.\n")
    cek("pesan asli masih memuat kode warna", f["msg"].startswith("`4"))
    bersih = remove_color(f["msg"])
    cek("remove_color membuang `4", not bersih.startswith("`4"))
    cek("pesan jadi utuh", bersih == "Fail to login. Login token is invalid.",
        bersih)
    # kode warna lain
    cek("`# (hex) dibuang", remove_color("`#FF0000Merah") == "FF0000Merah")
    cek("teks tanpa warna tidak berubah", remove_color("halo dunia") == "halo dunia")


def test_maintenance() -> None:
    """Deteksi maintenance dari `server_data.php` — `#maint` = TIDAK aktif.

    ⚠️ KOREKSI 2026-09-30: uji lama di sini SALAH dan mengunci bug.

    Dokumentasi format resmi `server_data.php`:
        #maint|Server is under maintenance. We will be back online shortly!

    `#maint` (dengan `#`) = baris **DIKOMENTARI**, server SELALU mengirimnya
    sebagai templat. Maintenance aktif HANYA kalau server mengirim `maint|...`
    tanpa `#`. Uji lama menganggap `#maint` = maintenance, sehingga bot selalu
    mengaku server tutup padahal pemain bisa login normal (dilaporkan user:
    "aku masuk growtopia lewat hp bisa").
    """
    bagian("11. maintenance: `#maint` = komentar (BUKAN maintenance)")
    from lucifer.account import ambil_pesan_maintenance, sedang_maintenance

    # Kondisi NYATA dari server resmi: `#maint` ada, tapi server NORMAL.
    kondisi_normal = {
        "server": "213.179.209.175", "port": "17041", "type": "1",
        "#maint": "Server is under maintenance. We will be back online shortly!",
        "meta": "abc", "RTENDMARKERBS1001": "",
    }
    # Maintenance AKTIF: kunci tanpa `#`.
    kondisi_maint = {
        "server": "213.179.209.175", "port": "17041", "type": "1",
        "maint": "Server is under maintenance. We will be back online shortly!",
        "meta": "abc",
    }
    tanpa_baris = {"server": "213.179.209.175", "port": "17041"}

    cek("`#maint` TIDAK dianggap maintenance (inti koreksi)",
        sedang_maintenance(kondisi_normal) is False,
        "dulu ini True -> bug 'server maintenance' palsu")
    cek("`maint` (tanpa #) dianggap maintenance",
        sedang_maintenance(kondisi_maint) is True)
    cek("tanpa baris maint -> normal",
        sedang_maintenance(tanpa_baris) is False)
    cek("pesan maintenance aktif diambil",
        "under maintenance" in ambil_pesan_maintenance(kondisi_maint).lower())
    cek("pesan dari `#maint` DIABAIKAN",
        ambil_pesan_maintenance(kondisi_normal) == "",
        repr(ambil_pesan_maintenance(kondisi_normal)))
    cek("kunci `beta_maint` (beta) tidak dianggap maintenance",
        sedang_maintenance({"beta_maint": "beta down"}) is False)
    cek("`maintenance` tanpa # juga dikenali",
        sedang_maintenance({"maintenance": "sedang tutup"}) is True)

    # ⚠️ TEMUAN 2026-10-04: kunci `maint` TANPA `#` dipakai server untuk DUA
    # hal — maintenance DAN rate-limit. Harus dibedakan supaya bot tidak
    # salah bilang "MAINTENANCE" (keluhan user "maintenance ga selesai").
    from lucifer.account import detik_tunggu, pesan_penolakan_login

    cek("rate-limit: 'Wait 30 seconds' dibaca sebagai 30 detik",
        detik_tunggu({"maint": "`4Oh no! `oWait 30 seconds before logging in again!"}) == 30)
    cek("rate-limit: 'Wait 0 seconds' -> 0",
        detik_tunggu({"maint": "`4Oh no! `oWait 0 seconds before logging in again!"}) == 0)
    cek("maintenance asli: tidak ada angka tunggu",
        detik_tunggu({"maint": "Server is under maintenance. We will be back online shortly!"}) == 0)

    p_rate = pesan_penolakan_login({"maint": "`4Oh no! `oWait 30 seconds before logging in again!"})
    cek("rate-limit TIDAK disebut 'maintenance'",
        "maintenance" not in p_rate.lower() and "rate-limit" in p_rate.lower())

    p_maint = pesan_penolakan_login({"maint": "Server is under maintenance. We will be back online shortly!"})
    cek("maintenance asli disebut 'maintenance'",
        "maintenance" in p_maint.lower())
    cek("tanpa maint aktif -> pesan kosong",
        pesan_penolakan_login(kondisi_normal) == "")


def test_logon_fail_cooldown() -> None:
    """`logon_fail` tidak boleh menimpa status rate-limit yang spesifik.

    Temuan lapangan: saat login pakai kuota seluler, server membalas

        action|logon_fail
        msg|Fail to login. Please try again in 30 seconds.

    Dulu handler `action == "logon_fail"` menimpa status hasil `_STATUS_MAP`
    (`too_many_login`) dengan `logon_fail`, sehingga dashboard menyarankan
    "sandi salah" padahal sandi tidak dipakai (login ltoken) dan masalahnya
    cuma cooldown IP. Auto-reconnect juga tetap menyala sehingga bot menembak
    ulang dan memperpanjang blokir.
    """
    bagian("15. logon_fail: cooldown server tidak ditimpa jadi 'logon_fail'")
    from lucifer.bot import Bot, BotStatus

    def kirim(b, fields: dict) -> None:
        payload = ("\n".join(f"{k}|{v}" for k, v in fields.items()) + "\n").encode()
        b._handle_text(2, fields, payload)

    b = Bot(label="uji-log", account=None)  # type: ignore[arg-type]
    b.status = BotStatus.connecting
    kirim(b, {"action": "log", "msg": "Fail to login. Please try again in 30 seconds."})
    cek("status jadi too_many_login (bukan logon_fail)",
        b.status == BotStatus.too_many_login, b.status)
    cek("auto_reconnect tetap menyala sebelum logon_fail", b.auto_reconnect is True)

    kirim(b, {"action": "logon_fail"})
    cek("logon_fail TIDAK menimpa too_many_login",
        b.status == BotStatus.too_many_login, b.status)
    cek("auto_reconnect dimatikan saat cooldown", b.auto_reconnect is False)
    cek("pesan server asli disertakan",
        "try again in 30 seconds" in b._last_server_msg.lower(),
        b._last_server_msg)

    # logon_fail tanpa pesan apa pun tetap harus tercatat sebagai logon_fail
    b2 = Bot(label="uji-log2", account=None)  # type: ignore[arg-type]
    b2.status = BotStatus.connecting
    pesan: list[str] = []
    b2.on_event = lambda k, p: pesan.append(str(getattr(p, "get", lambda *_: "")("msg")))
    kirim(b2, {"action": "logon_fail"})
    cek("logon_fail murni tetap logon_fail", b2.status == BotStatus.logon_fail, b2.status)
    cek("ada pesan pengganti saat server tak kirim msg",
        any("logon_fail" in m for m in pesan), str(pesan)[:80])

    # token kedaluwarsa harus jadi status tersendiri, bukan "sandi salah"
    b3 = Bot(label="uji-log3", account=None)  # type: ignore[arg-type]
    b3.status = BotStatus.connecting
    kirim(b3, {"action": "log", "msg": "Login token is invalid."})
    cek("token invalid -> invalid_account/logon terkait",
        b3.status in (BotStatus.invalid_account, BotStatus.logon_fail,
                      BotStatus.too_many_login, BotStatus.wrong_password),
        b3.status)


def test_hint_login_tidak_salah_menyebut_sandi() -> None:
    """Saran untuk cooldown tidak boleh bilang "sandi salah".

    Login lewat ltoken tidak memakai sandi sama sekali; menyarankan periksa
    sandi hanya menyesatkan. Pesan rate-limit harus disarankan sebagai
    cooldown, dan token kedaluwarsa sebagai "ambil ltoken baru".
    """
    bagian("16. hint login: cooldown vs sandi vs token")
    from lucifer.lua_api import _hint_login

    hint_cooldown = _hint_login("Fail to login. Please try again in 30 seconds.")
    cek("cooldown tidak menyebut sandi",
        "sandi" not in hint_cooldown.lower(), hint_cooldown[:80])
    cek("cooldown menyebut tunggu/cooldown",
        any(k in hint_cooldown.lower() for k in ("tunggu", "cooldown", "rate")),
        hint_cooldown[:80])

    hint_sandi = _hint_login("Wrong password.")
    cek("sandi salah tetap menyebut sandi",
        "sandi" in hint_sandi.lower(), hint_sandi[:80])

    hint_token = _hint_login("Login token is invalid.")
    cek("token invalid menyarankan ltoken baru",
        "ltoken" in hint_token.lower(), hint_token[:80])


def test_captcha_callback() -> None:
    """Captcha harus tertangkap lewat callback `onShowCaptcha`.

    Temuan 2026-09-30 (dari `libgrowtopia.so` v5.58): klien Growtopia memakai
    callback VariantList bernama **`onShowCaptcha`** (huruf kecil 'o'), bukan
    teks `action|captcha`. Handler lama mencari `action == "captcha"`, jadi
    tidak pernah jalan dan status captcha selalu `no_captcha` — dashboard
    menampilkan "no_captcha" walau server meminta captcha.
    """
    bagian("12. captcha: tertangkap dari callback onShowCaptcha")
    from lucifer.bot import Bot
    from lucifer.protocol import Tank as _Tank
    from lucifer.protocol import Variant, VariantList

    b = Bot(label="uji-cap", account=None)  # type: ignore[arg-type]
    cek("status awal no_captcha", b.captcha_status == "no_captcha")

    # server meminta captcha -> callback onShowCaptcha
    vl = VariantList()
    vl.append(Variant.from_string("onShowCaptcha"))
    vl.append(Variant.from_string(
        "https://captcha.growtopiagame.com/puzzle?id=abc123"))
    b._on_show_captcha(vl)
    cek("status jadi not_found", b.captcha_status == "not_found", b.captcha_status)
    cek("URL captcha tersimpan",
        b.captcha_url.startswith("https://captcha.growtopiagame.com"),
        b.captcha_url)
    cek("getCaptcha() mengembalikan URL",
        b.getCaptcha() == b.captcha_url)

    # tanpa URL tetap terdeteksi sebagai DIMINTA (bukan no_captcha)
    b2 = Bot(label="uji-cap2", account=None)  # type: ignore[arg-type]
    vl2 = VariantList()
    vl2.append(Variant.from_string("onShowCaptcha"))
    b2._on_show_captcha(vl2)
    cek("tetap terdeteksi walau URL kosong",
        b2.captcha_status == "not_found" and b2.captcha_url == "")


def test_google_oauth() -> None:
    """Login Google lewat OAuth web flow (cara Growlauncher).

    Temuan 2026-09-30: Growtopia punya OAuth client bertipe **Web**
    (`default_web_client_id` di base.apk resmi), jadi Google MENGIZINKAN
    redirect ke `https://login.growtopiagame.com/google/callback`. Ini
    membantah catatan lama di docs/login-flow.md yang menyatakan "tidak ada
    endpoint web untuk Google" — endpoint callback-nya memang ada (balas 500
    saat kosong, bukan 404, artinya route-nya terdaftar).
    """
    bagian("13. login Google: OAuth web flow (client_id tipe Web)")
    import urllib.parse as up

    from lucifer.google import (
        GOOGLE_CLIENT_ID,
        GOOGLE_REDIRECT_URI,
        _dari_url,
        url_login_google,
    )

    cek("client_id = milik Growtopia (dari base.apk)",
        GOOGLE_CLIENT_ID.endswith(".apps.googleusercontent.com")
        and GOOGLE_CLIENT_ID.startswith("389994132396-"))
    cek("redirect_uri = /google/callback",
        GOOGLE_REDIRECT_URI == "https://login.growtopiagame.com/google/callback")

    url = url_login_google()
    q = up.parse_qs(up.urlparse(url).query)
    cek("URL menuju accounts.google.com",
        url.startswith("https://accounts.google.com/"))
    cek("client_id ikut di URL", q.get("client_id", [""])[0] == GOOGLE_CLIENT_ID)
    cek("redirect_uri ikut di URL",
        q.get("redirect_uri", [""])[0] == GOOGLE_REDIRECT_URI)
    cek("response_type=code", q.get("response_type", [""])[0] == "code")
    cek("scope memuat openid+email",
        "openid" in q.get("scope", [""])[0] and "email" in q.get("scope", [""])[0])

    # parser URL callback
    h = _dari_url("https://login.growtopiagame.com/google/callback"
                  "?code=4/0AX4XfWg&state=abc123")
    cek("code terambil dari callback", h.ok and h.code == "4/0AX4XfWg")
    cek("state terambil", h.details.get("state") == "abc123")
    gagal = _dari_url("https://login.growtopiagame.com/google/callback"
                      "?error=access_denied")
    cek("error=access_denied -> gagal rapi",
        not gagal.ok and "access_denied" in gagal.message)


def test_google_state_wajib() -> None:
    """Server GT MEWAJIBKAN `state` di callback Google.

    Temuan 2026-09-30 (dari error nyata user):
        GET /google/callback?code=X            -> HTTP 500 (halaman 404)
        GET /google/callback?code=X&state=Y    -> HTTP 302 -> JSON
    `state` kosong juga 500, jadi harus benar-benar ada isinya. Nilainya
    sendiri tidak diperiksa server (acak pun diterima).
    """
    import urllib.parse as up

    from lucifer.google import buat_state, url_login_google

    # URL login WAJIB membawa state yang tidak kosong
    st = buat_state()
    u = url_login_google(state=st)
    q = up.parse_qs(up.urlparse(u).query)
    cek("url_login_google: state ikut dikirim", "state" in q)
    cek("url_login_google: state tidak kosong", bool(q["state"][0].strip()))
    cek("url_login_google: state = yang diminta", q["state"][0] == st)

    # tanpa argumen pun harus tetap ada state (dibuat otomatis)
    q2 = up.parse_qs(up.urlparse(url_login_google()).query)
    cek("url_login_google: state auto saat kosong", bool(q2.get("state", [""])[0]))
    cek("state acak berbeda tiap panggilan", buat_state() != buat_state())

    # parameter OAuth lain tetap benar
    cek("redirect_uri = /google/callback",
        q["redirect_uri"][0] == "https://login.growtopiagame.com/google/callback")
    cek("response_type = code", q["response_type"][0] == "code")
    cek("prompt = select_account", q["prompt"][0] == "select_account")

    # tukar tanpa state harus memberi pesan jelas (bukan 404 membingungkan).
    # Diuji tanpa jaringan: panggil dengan code kosong -> gagal lebih awal.
    from lucifer.google import tukar_code_jadi_ltoken
    r = tukar_code_jadi_ltoken("", state="")
    cek("tukar code kosong: gagal", not r.ok)
    cek("tukar code kosong: pesan jelas", "kosong" in r.message.lower())


def test_pisah_code_state() -> None:
    """`--code` harus terima code polos DAN URL callback utuh.

    Pengguna sering menyalin seluruh URL callback. Dulu itu gagal karena
    `code`-nya jadi mengandung `?`/`&`, dan `state`-nya ikut hilang.
    """
    from lucifer.cli import _pisah_code_state

    c, s = _pisah_code_state("4/0AX4XfWg_abc-123")
    cek("code polos: code utuh", c == "4/0AX4XfWg_abc-123")
    cek("code polos: state kosong", s == "")

    url = ("https://login.growtopiagame.com/google/callback"
           "?code=4/0AX4XfWg_abc-123&state=XY%2Bz")
    c, s = _pisah_code_state(url)
    cek("URL utuh: code diambil", c == "4/0AX4XfWg_abc-123")
    cek("URL utuh: state diambil", s == "XY+z")

    c, s = _pisah_code_state(f'"{url}"')
    cek("URL berkutip: tetap jalan", c == "4/0AX4XfWg_abc-123")

    c, s = _pisah_code_state("https://login.growtopiagame.com/google/callback?code=C2")
    cek("URL tanpa state: code tetap diambil", c == "C2")
    cek("URL tanpa state: state kosong", s == "")


def test_token_dari_halaman() -> None:
    """Baca `token` dari halaman `/player/link/dashboard/validate/`.

    Temuan 2026-09-30 (dari error nyata user):
        ✓ Chrome buka callback?code=X  -> GT tukar code ke Google
        ✓ GT redirect ke /player/link/dashboard/validate/<payload>
        ✓ Halaman itu berisi JSON {"status":"success","token":"<ltoken>"}
        ✗ Kode lama menukar `code` LAGI -> "Token is invalid."
          Sebab: OAuth `code` hanya SEKALI pakai; Chrome sudah memakainya.

    Perbaikan: baca token langsung dari halaman hasil.
    """
    from lucifer.google import _token_dari_isi

    # sukses
    t, p = _token_dari_isi(json.dumps(
        {"status": "success", "message": "Account Validated.",
         "token": "abc.TOKEN", "url": "", "accountType": "growtopia"}))
    cek("token dibaca dari JSON halaman", t == "abc.TOKEN", repr(t))
    cek("pesan 'Account Validated.' terbaca", "validated" in p.lower(), p)

    # gagal -> token kosong, pesan asli server dipertahankan
    t, p = _token_dari_isi(json.dumps(
        {"status": "failed", "message": "Token is invalid.", "token": ""}))
    cek("status failed -> token kosong", t == "", repr(t))
    cek("pesan 'Token is invalid.' terbaca", "invalid" in p.lower(), p)

    # JSON yang dibungkus HTML
    t, _ = _token_dari_isi(
        "<html><body><pre>" + json.dumps(
            {"status": "success", "token": "xyz.TOKEN"}) + "</pre></body></html>")
    cek("token terbaca walau dibungkus HTML", t == "xyz.TOKEN", repr(t))

    # bukan JSON / kosong -> aman (tidak error)
    for buruk in ("", "  ", "bukan json", "<html>404</html>", "{}"):
        t, p = _token_dari_isi(buruk)
        cek(f"input {buruk[:14]!r} -> tidak error", t == "", repr((t, p)))


def test_relay_udp() -> None:
    """Pembungkus/buka header SOCKS5 UDP + penolakan paket cacat.

    Latar: `enet_host_use_proxy()` di enet.so rusak (kirim greeting lalu
    tutup soket), jadi proxy ditangani `lucifer.udprelay`. Kalau parsing
    header salah, semua balasan hilang tanpa error — makanya diuji.
    """
    from lucifer.proxy import Proxy
    from lucifer.udprelay import RelayUdp

    r = RelayUdp(Proxy("1.2.3.4", 1080), ("9.9.9.9", 53))
    hdr = r._header_target
    cek("header tujuan = ATYP domain + port 53",
        hdr == b"\x00\x00\x00\x03\x079.9.9.9\x00\x35", hdr.hex())
    cek("payload dibungkus setelah header", r._bingkus(b"abc") == hdr + b"abc")

    cek("buka: IPv4", r._buka(hdr + b"payload") == b"payload")
    dom = b"\x00\x00\x00\x03\x07example\x00\x35" + b"isi"
    cek("buka: domain", r._buka(dom) == b"isi")
    v6 = b"\x00\x00\x00\x04" + b"\x00" * 16 + b"\x00\x35" + b"hai"
    cek("buka: IPv6", r._buka(v6) == b"hai")
    cek("tolak frag != 0",
        r._buka(b"\x00\x00\x01\x01" + b"\x00" * 6 + b"x") is None)
    cek("tolak data pendek", r._buka(b"\x00\x00") is None)
    cek("tolak RSV bukan nol",
        r._buka(b"\x01\x00\x00\x01" + b"\x00" * 6 + b"x") is None)
    cek("statistik awal nol", r.statistik == {"kirim": 0, "terima": 0, "lokal": 0},
        str(r.statistik))


def test_status_gems_level() -> None:
    bagian("7b. Status: gems dari OnSetBux, level dari dialog profil")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank as _Tank
    from lucifer.protocol import Variant, VariantList

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    bot.send_raw = lambda *a, **k: True  # type: ignore[method-assign]

    # OnSetBux(<gems>, <animate>, <supporter>, vec3) -> arg1 = gems
    vl = VariantList()
    vl.append(Variant.from_string("OnSetBux"))
    vl.append(Variant.from_int(4321))
    vl.append(Variant.from_int(1))
    vl.append(Variant.from_int(0))
    bot._handle_variant(vl.serialize(), _Tank())
    cek("gems dari OnSetBux", bot.gem_count == 4321, str(bot.gem_count))

    # Jalur NYATA: OnDialogRequest dengan markup di argumen index 1
    # (bentuk asli retail, terbukti dari jurnal paket:
    #  `fn=OnDialogRequest arg1='embed_data|netID|1\nadd_popup_name|WrenchMenu|...`).
    dialog = ("embed_data|netID|1\n"
              "add_popup_name|WrenchMenu|\n"
              "set_default_color|`o\n"
              "add_player_info|Isan|42|700|1800|\n"
              "add_button|ok|OK|")
    vd = VariantList()
    vd.append(Variant.from_string("OnDialogRequest"))
    vd.append(Variant.from_string(dialog))
    bot.level = 0
    bot._handle_variant(vd.serialize(), _Tank())
    cek("level dari paket OnDialogRequest asli", bot.level == 42, str(bot.level))
    cek("dialog terakhir tersimpan", "add_player_info" in bot.dialog_terakhir)

    # Dialog profil: `add_player_info|<nama>|<level>|<xp>|<xp_next>|`
    teks = ("add_popup_name|WrenchMenu\n"
            "add_player_info|Isan|37|1200|2500|\n"
            "add_button|ok|OK|\n")
    cek("level dari add_player_info", bot._baca_level_dialog(teks) is True)
    cek("level tersimpan", bot.level == 37, str(bot.level))

    # Dialog toko tidak boleh dianggap level.
    bot.level = 0
    cek("dialog lain tidak mengisi level",
        bot._baca_level_dialog("add_player_info|Toko|999999|||") is False
        and bot.level == 0)

    # UpdateStatus hanya jalur cadangan (format server privat).
    bot._apply_status(b"level|12\ngems|99\n")
    cek("UpdateStatus cadangan: level", bot.level == 12, str(bot.level))
    cek("UpdateStatus cadangan: gems", bot.gem_count == 99, str(bot.gem_count))


def test_proxypool_kredensial_unik() -> None:
    bagian("7d. ProxyPool: kredensial beda = entri beda")
    import tempfile
    from pathlib import Path

    from lucifer.proxypool import ProxyPool

    with tempfile.TemporaryDirectory() as d:
        pool = ProxyPool(Path(d) / "proxies.json")
        # Proxy "rotating gateway": host:port sama, kredensial beda = IP keluar
        # beda. Dedupe host:port saja membuang semuanya kecuali satu.
        baris = "\n".join(
            f"socks5://user{i}:pass{i}@1.2.3.4:9999" for i in range(5)
        )
        r = pool.tambah(baris)
        cek("5 kredensial sama host:port jadi 5 entri",
            r["ditambah"] == 5 and r["total"] == 5, str(r))
        cek("tambah baris identik tidak menambah",
            pool.tambah("socks5://user0:pass0@1.2.3.4:9999")["ditambah"] == 0)

        # muat ulang dari disk: kunci tetap konsisten
        pool2 = ProxyPool(Path(d) / "proxies.json")
        cek("muat ulang pertahankan 5 entri", len(pool2.daftar()) == 5,
            str(len(pool2.daftar())))

        hapus = pool2.hapus("1.2.3.4", 9999)
        cek("hapus host:port membersihkan semua kredensial",
            hapus["dihapus"] == 5 and hapus["total"] == 0, str(hapus))


def test_merge_drop_total_bukan_tambahan() -> None:
    bagian("7j. ItemChangeObject MERGE: count = TOTAL, bukan tambahan")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    bot.world.dropped.clear()
    bot.world.last_uid = 0

    # Pola nyata dari Growtopia HP: netid=ALL lalu MERGE dengan count naik.
    #   DROP uid=3 count=3 -> 5 -> 6 -> 7
    def kirim(netid, uid, count, item=2):
        bot._apply_item_change(
            Tank(type=14, net_id=netid, target_net_id=uid, value=item,
                 float_variable=float(count), vector_x=1822.0, vector_y=744.0),
            b"")

    bot.world.last_uid = 2
    kirim(0xFFFFFFFF, -1, 3)
    cek("drop awal count=3", bot.world.dropped[0].count == 3,
        str(bot.world.dropped[0].count))
    uid_obj = bot.world.dropped[0].uid
    for c in (5, 6, 7):
        kirim(0xFFFFFFFD, uid_obj, c)   # netid MERGE memakai uid objek
    cek("merge count = total (7), bukan 3+5+6+7", bot.world.dropped[0].count == 7,
        str(bot.world.dropped[0].count))
    cek("tidak ada duplikat objek", len(bot.world.dropped) == 1,
        str(len(bot.world.dropped)))

    # Item berbeda = objek terpisah.
    kirim(0xFFFFFFFF, -1, 1, item=112)
    cek("item lain jadi objek sendiri", len(bot.world.dropped) == 2,
        str(len(bot.world.dropped)))


def test_uid_ke_item_id_untuk_pickup() -> None:
    bagian("7m. Pickup: uid -> item id dari objek yang pernah terlihat")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.items import ItemDatabase
    from lucifer.protocol import Tank
    from pathlib import Path

    items = Path(__file__).resolve().parent.parent / "data" / "items.dat"
    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    if items.exists():
        bot.items_db = ItemDatabase.from_file(items)
    bot.world.dropped.clear()
    bot.world.last_uid = 0
    bot._uid_item.clear()

    # Drop Dirt Seed (item id 3). Server mengirim uid=-1 (bukti decode hex).
    bot._apply_item_change(
        Tank(type=14, net_id=0xFFFFFFFF, target_net_id=-1, value=3,
             float_variable=1.0, vector_x=1618.0, vector_y=713.0,
             object_type=4), b"")
    # uid ditiru dari counter: last_uid 0 -> uid 1 (terbukti cocok dengan
    # uid asli server: tiga drop berurutan menjadi 10, 11, 12).
    cek("drop -> uid dari counter",
        [(d.uid, d.item_id) for d in bot.world.dropped] == [(1, 3)],
        str([(d.uid, d.item_id) for d in bot.world.dropped]))
    bot.world.dropped[0].uid = 15
    bot._uid_item[15] = 3

    # Pickup: paket HANYA membawa uid, bukan item id.
    bot._apply_item_change(Tank(type=14, net_id=2, value=15), b"")
    cek("objek dihapus dari dunia", not bot.world.dropped,
        str(bot.world.dropped))
    log = [p["isi"] for p in bot.packet_log if "DIAMBIL" in p["isi"]]
    cek("log DIAMBIL menyebut uid 15", bool(log) and "uid=15" in log[-1],
        str(log[-1:]))


def test_autocollect_uid_dipakai_ulang() -> None:
    bagian("7o. AutoCollect: uid dipakai ulang tidak diblokir selamanya")
    import time

    from lucifer.account import Account
    from lucifer.bot import Bot, Player
    from lucifer.protocol import Tank

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    bot.local = Player(netid=1, name="uji", posx=1000.0, posy=1000.0)
    bot._running = True
    bot.auto_collect = True
    bot.auto_collect_radius = 6
    kirim = []
    bot.send_raw = lambda pkt, ext=b"": (kirim.append(pkt), True)[1]  # type: ignore[method-assign]

    # Tiga percobaan untuk uid=1 (batas).
    for _ in range(3):
        bot._apply_item_change(
            Tank(type=14, net_id=0xFFFFFFFF, target_net_id=1, value=2,
                 float_variable=1.0, vector_x=1000.0, vector_y=1000.0), b"")
    time.sleep(0.15)
    cek("3 percobaan terkirim", len(kirim) == 3, str(len(kirim)))

    # Server memakai ulang uid=1 untuk objek baru: harus bisa diambil lagi.
    kirim.clear()
    bot.world.dropped.clear()
    bot._apply_item_change(
        Tank(type=14, net_id=0xFFFFFFFF, target_net_id=1, value=3,
             float_variable=1.0, vector_x=1000.0, vector_y=1000.0), b"")
    time.sleep(0.15)
    cek("uid dipakai ulang -> diambil lagi", len(kirim) == 1,
        str([(p.type, p.value) for p in kirim]))


def test_collected_dengan_kode_warna() -> None:
    bagian("7p. `Collected` dengan kode warna tetap terbaca")
    from pathlib import Path

    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.items import ItemDatabase
    from lucifer.protocol import remove_color

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    items = Path(__file__).resolve().parent.parent / "data" / "items.dat"
    if items.exists():
        bot.items_db = ItemDatabase.from_file(items)
    bot.inventory.items.clear()

    # Teks nyata dari server (backtick mengganda setelah nama):
    #   Collected `w24 Dirt``. Rarity: `w1``
    cek("24 Dirt terbaca",
        bot._baca_collected(remove_color("Collected `w24 Dirt``. Rarity: `w1``"))
        and bot.inventory.getItemCount(2) == 24,
        str(bot.inventory.getItemCount(2)))
    cek("1 Dirt Seed terbaca",
        bot._baca_collected(remove_color("Collected `w1 Dirt Seed``. Rarity: `w1``"))
        and bot.inventory.getItemCount(3) == 1,
        str(bot.inventory.getItemCount(3)))
    cek("teks bukan Collected diabaikan",
        bot._baca_collected(remove_color("You have 5 Dirt")) is False)


def test_uid_item_dari_sendmapdata() -> None:
    bagian("7n. SendMapData mengisi peta uid->item (objek lama)")
    from pathlib import Path

    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.items import ItemDatabase
    from lucifer.protocol import Tank
    from lucifer.world import DroppedItem

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    items = Path(__file__).resolve().parent.parent / "data" / "items.dat"
    if items.exists():
        bot.items_db = ItemDatabase.from_file(items)

    # Objek yang sudah ada di dunia datang lewat SendMapData (uid + item id).
    bot._uid_item.clear()
    bot.world.dropped = [DroppedItem(item_id=3, x=1473.0, y=815.0,
                                     count=1, uid=1)]
    for d in bot.world.dropped:
        bot._uid_item[int(d.uid)] = int(d.item_id)
    cek("peta terisi dari SendMapData", bot._uid_item.get(1) == 3,
        str(bot._uid_item))

    # Pickup hanya membawa uid; item id diambil dari peta.
    bot._apply_item_change(Tank(type=14, net_id=1, value=1), b"")
    log = [p["isi"] for p in bot.packet_log if "DIAMBIL" in p["isi"]]
    cek("pickup memakai peta SendMapData",
        bool(log) and "item_id=3" in log[-1], str(log[-1:]))


def test_arti_value_item_change_object() -> None:
    bagian("7l. type 14: arti `value` beda menurut netid")
    from lucifer import nama as N

    # 18 = Fist punya nama khusus; nilai lain tanpa db jadi `#id`.
    cek("netid=ALL -> value diperlakukan sebagai item",
        N.tank_value(14, 18, None, 0xFFFFFFFF) == "Fist(pukul)",
        N.tank_value(14, 18, None, 0xFFFFFFFF))
    cek("netid=MERGE -> value diperlakukan sebagai item",
        N.tank_value(14, 18, None, 0xFFFFFFFD) == "Fist(pukul)",
        N.tank_value(14, 18, None, 0xFFFFFFFD))
    # netid=pemain -> value = uid objek (BUKAN item id 5)
    hasil = N.tank_value(14, 5, None, 3)
    cek("netid=3 value=5 -> uid=5 (bukan nama item)",
        "uid=5" in hasil and "Lava" not in hasil, hasil)


def test_tabel_arti_tank() -> None:
    bagian("7t. Arti field tank: satu tabel, tidak ditafsir ulang")
    from lucifer import nama as N

    all_ = N.item_change_arti(0xFFFFFFFF)
    cek("type14 ALL: value=item, target_net_id=netid",
        all_["value"] == "item" and all_["target_net_id"] == "netid", str(all_))
    merge = N.item_change_arti(0xFFFFFFFD)
    cek("type14 MERGE: target_net_id=uid",
        merge["value"] == "item" and merge["target_net_id"] == "uid", str(merge))
    ambil = N.item_change_arti(6)
    cek("type14 pemain: value=uid",
        ambil["value"] == "uid" and ambil["target_net_id"] == "netid",
        str(ambil))

    # Log tidak boleh menyebut "uid=" untuk drop ALL (itu netid pemain).
    from lucifer.protocol import Tank
    baris = N.ringkas_tank(Tank(type=14, net_id=0xFFFFFFFF, target_net_id=5,
                                value=2, float_variable=1.0,
                                vector_x=1.0, vector_y=1.0))
    cek("log drop ALL: dropper_netid, bukan uid", "dropper_netid=5" in baris
        and "uid=5" not in baris, baris)

    # type 11: int_x = jumlah item, bukan tile.
    baris11 = N.ringkas_tank(Tank(type=11, value=10, int_x=30,
                                  vector_x=1.0, vector_y=1.0))
    cek("log type11: count=30, tanpa tile", "count=30" in baris11
        and "tile=" not in baris11, baris11)


def test_uid_drop_dari_counter() -> None:
    bagian("7u. uid drop = counter server (bukan target_net_id)")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    bot.world.last_uid = 9
    # Tiga drop berbeda, semuanya target_net_id=5 (netid pemain lain).
    for item, count in ((11, 1), (14, 30), (3, 1)):
        bot._apply_item_change(
            Tank(type=14, net_id=0xFFFFFFFF, target_net_id=5, value=item,
                 float_variable=float(count), vector_x=100.0, vector_y=100.0),
            b"")
    uid = [(d.uid, d.item_id, d.count) for d in bot.world.dropped]
    cek("uid berurutan 10,11,12 (cocok SendMapData)", uid ==
        [(10, 11, 1), (11, 14, 30), (12, 3, 1)], str(uid))

    # MERGE memakai uid asli dari target_net_id dan menimpa count (TOTAL).
    bot._apply_item_change(
        Tank(type=14, net_id=0xFFFFFFFD, target_net_id=11, value=14,
             float_variable=7.0, vector_x=100.0, vector_y=100.0), b"")
    obj = [(d.uid, d.item_id, d.count) for d in bot.world.dropped]
    cek("merge uid=11 -> satu objek count 7", obj ==
        [(10, 11, 1), (11, 14, 7), (12, 3, 1)], str(obj))

    # Pickup membuang objek itu, tanpa menambah stok.
    sebelum = bot.inventory.count_of(14) if hasattr(bot.inventory, "count_of") else None
    bot._apply_item_change(
        Tank(type=14, net_id=6, value=11, float_variable=1.0), b"")
    sisa = [d.uid for d in bot.world.dropped]
    cek("pickup uid=11 -> objek hilang", sisa == [10, 12], str(sisa))
    if sebelum is not None:
        cek("pickup tidak menambah stok", bot.inventory.count_of(14) == sebelum,
            f"{sebelum} -> {bot.inventory.count_of(14)}")


def test_state_identik_tidak_spam_log() -> None:
    bagian("7v. State posisi sama tidak memenuhi jurnal")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import (Tank, NetGamePacket as G, NetMessage as M,
                                  build_packet)

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")

    def state(netid, x):
        bot._handle_packet(build_packet(
            M.GamePacket,
            Tank(type=G.State, net_id=netid, vector_x=x, vector_y=706.0,
                 flags=0x30).to_bytes()))

    for _ in range(5):
        state(8, 1211.0)          # pemain idle: posisi sama terus
    n1 = len([p for p in bot.packet_log if "type=0" in p["isi"]])
    cek("5 State identik -> 1 baris", n1 == 1, str(n1))
    state(8, 1240.0)
    cek("posisi berubah tetap dicatat",
        len([p for p in bot.packet_log if "type=0" in p["isi"]]) == 2)
    state(9, 1240.0)
    cek("netid lain dicatat terpisah",
        len([p for p in bot.packet_log if "type=0" in p["isi"]]) == 3)


def test_echo_break_konfirmasi() -> None:
    bagian("7k. Echo type=3 value=18 = konfirmasi BLOK PECAH")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank
    from lucifer.world import Tile, World

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    w = World()
    w.name, w.width, w.height = "UJI", 60, 60
    for y in range(60):
        for x in range(60):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=14))
    bot.world = w
    from lucifer.bot import Player
    bot.local = Player(netid=1, name="uji", posx=0.0, posy=0.0)
    bot.world.tile(50, 22).fg = 2

    cek("sebelum echo: bukan pecah", not bot.break_diterima(50, 22))
    # Paket nyata: `in type=3 netid=1 tile=(53,26) value=18(Fist)`.
    bot._apply_tile_change_echo(Tank(type=3, net_id=1, value=18,
                                     int_x=50, int_y=22))
    cek("echo value=18 -> break_diterima", bot.break_diterima(50, 22))
    cek("peta lokal jadi kosong", bot.world.tile(50, 22).fg == 0,
        str(bot.world.tile(50, 22).fg))

    # Echo place (value != 18) BUKAN konfirmasi pecah.
    bot.reset_aksi(50, 22)
    bot._apply_tile_change_echo(Tank(type=3, net_id=1, value=2,
                                     int_x=50, int_y=22))
    cek("echo value=2 bukan break", not bot.break_diterima(50, 22))
    cek("echo value=2 -> place_diterima", bot.place_diterima(50, 22, 2))


def test_posisi_tidak_memindah_bot() -> None:
    bagian("7i. tileChange memakai posisi PEMAIN (bot tidak ikut geser)")
    from lucifer.account import Account
    from lucifer.bot import Bot, Player
    from lucifer.world import Tile, World

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    w = World()
    w.name, w.width, w.height = "UJI", 60, 60
    for y in range(60):
        for x in range(60):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=0))
    bot.world = w
    # Pemain berdiri di tile (49,23) = piksel (1581,738), menaruh di (52,23).
    bot.local = Player(netid=1, name="uji", posx=1581.0, posy=738.0)

    out = []
    bot.send_raw = lambda pkt, ext=b"": (out.append(pkt), True)[1]  # type: ignore[method-assign]
    bot.place(52, 23, 2)

    kirim = [p for p in out if int(p.type) in (0, 3)]
    cek("ada paket State + TileChange", len(kirim) == 2,
        str([int(p.type) for p in kirim]))
    for p in kirim:
        cek(f"type={int(p.type)} pos = posisi pemain (1581,738)",
            abs(p.vector_x - 1581.0) < 0.5 and abs(p.vector_y - 738.0) < 0.5,
            f"pos=({p.vector_x:.0f},{p.vector_y:.0f})")
        cek(f"type={int(p.type)} tile tetap (52,23)",
            p.int_x == 52 and p.int_y == 23, f"tile=({p.int_x},{p.int_y})")

    # Bukti pembanding dari klien asli (Growtopia HP):
    #   in type=3 tile=(52,23) pos=(1581,738) value=2  -> PLACE berhasil
    tc = [p for p in kirim if int(p.type) == 3][0]
    cek("identik dengan paket HP",
        tc.int_x == 52 and tc.int_y == 23 and abs(tc.vector_x - 1581.0) < 0.5
        and int(tc.value) == 2,
        f"tile=({tc.int_x},{tc.int_y}) pos=({tc.vector_x:.0f},{tc.vector_y:.0f}) "
        f"value={tc.value}")


def test_collect_int_x_bukan_count() -> None:
    bagian("7s. collectObject: int_x = invbit (0/1), BUKAN jumlah item")
    from lucifer.account import Account
    from lucifer.bot import Bot, Player
    from lucifer.world import DroppedItem

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    bot.local = Player(netid=1, name="uji", posx=1254.0, posy=752.0)

    # Bukti dari log: count=30 dikirim sebagai int_x=30 -> server DIAM,
    # sedangkan count=1 -> int_x=1 -> BERHASIL.
    bot.world.dropped = [DroppedItem(item_id=14, x=1254.0, y=752.0,
                                     count=30, uid=5)]
    kirim = []
    bot.send_raw = lambda pkt, ext=b"": (kirim.append(pkt), True)[1]  # type: ignore[method-assign]
    bot.collectObject(5)
    # Log sukses: `type=11 tile=(30,0) value=11` -> DIAMBIL count=30.
    cek("int_x = count (30)", kirim and kirim[0].int_x == 30,
        str([(p.int_x, p.value) for p in kirim]))
    cek("value tetap uid", kirim and kirim[0].value == 5,
        str([(p.int_x, p.value) for p in kirim]))


def test_echo_orang_lain_diabaikan() -> None:
    bagian("7r. Echo netid orang lain TIDAK menyentuh stok/peta bot")
    from lucifer.account import Account
    from lucifer.bot import Bot, Player
    from lucifer.protocol import Tank
    from lucifer.world import Tile, World

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    w = World()
    w.name, w.width, w.height = "UJI", 60, 60
    for y in range(60):
        for x in range(60):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=14))
    bot.world = w
    bot.local = Player(netid=3, name="uji", posx=0.0, posy=0.0)
    bot.inventory.items.clear()
    bot.inventory.tambah(14, 10)

    # Paket nyata: pemain lain (netid=2) menaruh Cave Background.
    bot._apply_tile_change_echo(Tank(type=3, net_id=2, value=14,
                                     int_x=54, int_y=25))
    cek("stok bot tidak berkurang", bot.inventory.getItemCount(14) == 10,
        str(bot.inventory.getItemCount(14)))
    cek("peta bot tidak berubah", bot.world.tile(54, 25).fg == 0,
        str(bot.world.tile(54, 25).fg))

    # Place bot sendiri harus tetap dihitung.
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=14,
                                     int_x=45, int_y=17))
    cek("place bot sendiri mengurangi stok",
        bot.inventory.getItemCount(14) == 9, str(bot.inventory.getItemCount(14)))

    # Pukulan orang lain juga tidak boleh menambah hit counter bot.
    sebelum = bot.hit_count(50, 22)
    bot._apply_damage(Tank(type=8, net_id=2, int_x=50, int_y=22, value=6))
    cek("pukulan orang lain tidak dihitung",
        bot.hit_count(50, 22) == sebelum, str(bot.hit_count(50, 22)))


def test_place_door_mengurangi_stok() -> None:
    bagian("7q. Echo place nyata (Door) mengurangi stok sampai 0")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank
    from lucifer.world import Tile, World

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    w = World()
    w.name, w.width, w.height = "UJI", 60, 60
    for y in range(60):
        for x in range(60):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=14))
    bot.world = w
    from lucifer.bot import Player
    bot.local = Player(netid=3, name="uji", posx=0.0, posy=0.0)
    bot.inventory.items.clear()
    bot.inventory.tambah(12, 1)

    # Paket nyata: in type=3 netid=3 tile=(45,17) value=12(Door)
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, int_x=45, int_y=17, value=12))
    cek("Door 1 -> 0 setelah place", bot.inventory.getItemCount(12) == 0,
        str(bot.inventory.getItemCount(12)))
    cek("Door tetap terdaftar (bukan hilang)", 12 in bot.inventory.items,
        str(list(bot.inventory.items)))
    cek("tile terisi Door di peta lokal", bot.world.tile(45, 17).fg == 12,
        str(bot.world.tile(45, 17).fg))


def test_echo_place_kurangi_inventory() -> None:
    bagian("7g. Echo TileChangeRequest (place) mengurangi stok")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    from lucifer.bot import Player
    from lucifer.world import Tile, World

    w = World()
    w.name, w.width, w.height = "UJI", 60, 60
    for y in range(60):
        for x in range(60):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=14))
    bot.world = w
    bot.local = Player(netid=3, name="uji", posx=0.0, posy=0.0)
    bot.inventory.items.clear()
    bot.inventory.tambah(14, 5)

    # Server echo: netid bot (3), value = item id yang berhasil ditaruh.
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=14,
                                     int_x=10, int_y=10))
    cek("place Cave Background -> stok 4",
        bot.inventory.getItemCount(14) == 4, str(bot.inventory.getItemCount(14)))

    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=14, int_x=10, int_y=10))
    cek("place kedua -> stok 3", bot.inventory.getItemCount(14) == 3)

    # Pukulan (Fist 18) BUKAN pemakaian item: stok tidak boleh turun.
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=18, int_x=10, int_y=10))
    cek("punch tidak mengurangi stok", bot.inventory.getItemCount(14) == 3,
        str(bot.inventory.getItemCount(14)))

    # Wrench (32) juga bukan pemakaian item.
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=32, int_x=10, int_y=10))
    cek("wrench tidak mengurangi stok", bot.inventory.getItemCount(14) == 3)

    # Stok 0: tidak boleh jadi negatif walau echo tetap datang.
    bot.inventory.kurangi(14, 3)
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=14, int_x=10, int_y=10))
    cek("stok 0 tidak jadi negatif", bot.inventory.getItemCount(14) == 0,
        str(bot.inventory.getItemCount(14)))

    # Item yang tidak ada di inventaris diabaikan.
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=999, int_x=1, int_y=1))
    cek("item tak dikenal diabaikan", 999 not in bot.inventory.items)

    # Place juga harus memperbarui PETA lokal: tanpa itu bot tidak tahu ada
    # blok baru yang sudah dia pasang (dan tidak akan memecahnya lagi).
    from lucifer.world import Tile, World
    w = World()
    w.name, w.width, w.height = "UJI", 5, 5
    for y in range(5):
        for x in range(5):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=14))
    bot.world = w
    bot.inventory.tambah(14, 3)
    bot._apply_tile_change_echo(Tank(type=3, net_id=3, value=14, int_x=2, int_y=3))
    t = w.tile(2, 3)
    cek("place mengisi peta lokal", t is not None and t.fg == 14,
        str(t))
    cek("bg dipertahankan", t is not None and t.bg == 14, str(t))


def test_hit_counter() -> None:
    bagian("7h. TileApplyDamage (type 8) sebagai hit counter")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    cek("hit_count awal 0", bot.hit_count(5, 5) == 0)
    for _ in range(3):
        bot._apply_damage(Tank(type=8, int_x=5, int_y=5, value=6))
    cek("3 pukulan tercatat", bot.hit_count(5, 5) == 3, str(bot.hit_count(5, 5)))
    bot._apply_damage(Tank(type=8, int_x=6, int_y=5, value=6))
    cek("tile lain terpisah", bot.hit_count(5, 5) == 3 and bot.hit_count(6, 5) == 1)
    bot.reset_hit(5, 5)
    cek("reset_hit mengosongkan", bot.hit_count(5, 5) == 0)
    # Tile negatif (posisi tak valid) diabaikan.
    bot._apply_damage(Tank(type=8, int_x=-1, int_y=-1))
    cek("tile negatif diabaikan", bot.hit_count(-1, -1) == 0)


def test_modify_inventory() -> None:
    bagian("7f. ModifyItemInventory (type 13) update stok lokal")
    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    bot.inventory.items.clear()
    bot.inventory.tambah(2, 10)
    cek("stok awal Dirt", bot.inventory.getItemCount(2) == 10,
        str(bot.inventory.getItemCount(2)))

    # BERKURANG: (jumlah << 16) | 13 -> byte2 = jumlah
    bot._apply_modify_inventory(Tank(type=13, value=2, jump_count=3))
    cek("Dirt berkurang 3", bot.inventory.getItemCount(2) == 7,
        str(bot.inventory.getItemCount(2)))

    # BERTAMBAH: (jumlah << 24) | 13 -> byte3 = jumlah
    bot._apply_modify_inventory(Tank(type=13, value=2, animation_type=5))
    cek("Dirt bertambah 5", bot.inventory.getItemCount(2) == 12,
        str(bot.inventory.getItemCount(2)))

    # Habis = stok 0 tetapi item TETAP di daftar. Menghapusnya membuat item
    # yang habis tampak "tidak pernah ada" di GUI.
    bot._apply_modify_inventory(Tank(type=13, value=2, jump_count=12))
    cek("stok habis -> tetap terdaftar dengan 0",
        bot.inventory.getItemCount(2) == 0 and 2 in bot.inventory.items,
        str(bot.inventory.items))

    # Item baru yang belum pernah ada.
    bot._apply_modify_inventory(Tank(type=13, value=500, animation_type=4))
    cek("item baru masuk inventaris", bot.inventory.getItemCount(500) == 4,
        str(bot.inventory.getItemCount(500)))

    # Gems (112) bukan item inventaris: harus diabaikan.
    bot._apply_modify_inventory(Tank(type=13, value=112, animation_type=9))
    cek("gems diabaikan", 112 not in bot.inventory.items)


def test_malady_dari_dialog() -> None:
    bagian("7e. Malady: parse dari dialog profil")
    from lucifer.account import Account
    from lucifer.bot import Bot

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")

    # Nama konstanta klien (MALADY_* / ILLNESS_*).
    cek("MALADY_LUPUS -> Lupus",
        bot._baca_malady_dialog("add_textbox|MALADY_LUPUS|") and bot.malady == "Lupus",
        bot.malady)
    bot._set_malady("")
    cek("ILLNESS_BIRDFLU -> Bird Flu",
        bot._baca_malady_dialog("add_smalltext|ILLNESS_BIRDFLU|") and bot.malady == "Bird Flu",
        bot.malady)
    bot._set_malady("")
    cek("MALADY_VICIOUS_MOLDY_GUTS -> Vicious Moldy Guts",
        bot._baca_malady_dialog("MALADY_VICIOUS_MOLDY_GUTS")
        and bot.malady == "Vicious Moldy Guts", bot.malady)
    # MALADY_VICIOUS_LUPUS mengandung MALADY_LUPUS: harus menang yang panjang.
    bot._set_malady("")
    cek("VICIOUS_LUPUS tidak salah jadi Lupus",
        bot._baca_malady_dialog("MALADY_VICIOUS_LUPUS")
        and bot.malady == "Vicious Lupus", bot.malady)

    # Teks jadi tanpa prefix konstanta juga dikenali.
    bot._set_malady("")
    cek("teks jadi 'Brainworms' dikenali",
        bot._baca_malady_dialog("add_textbox|You have `4Brainworms`` illness.``|")
        and bot.malady == "Brainworms", bot.malady)

    # Sehat: ILLNESS_CURED / ILLNESS_NONE mengosongkan status.
    bot._set_malady("Lupus")
    cek("ILLNESS_CURED mengosongkan", bot._baca_malady_dialog("add_textbox|ILLNESS_CURED|")
        and bot.malady == "", repr(bot.malady))
    bot._set_malady("Lupus")
    cek("ILLNESS_NONE mengosongkan", bot._baca_malady_dialog("ILLNESS_NONE")
        and bot.malady == "", repr(bot.malady))

    # Dialog tak relevan tidak boleh menghapus status yang sudah benar.
    bot._set_malady("Lupus")
    cek("dialog toko tidak menghapus malady",
        bot._baca_malady_dialog("add_button|buy|Buy|") is False and bot.malady == "Lupus",
        bot.malady)

    # Terbawa ke payload stats (dipakai GUI + web).
    cek("malady ada di stats()", bot.stats().get("malady") == "Lupus",
        str(bot.stats().get("malady")))


def test_tile_update_koordinat() -> None:
    bagian("7c. SendTileUpdateData: koordinat dari tank, ext = blok")
    import struct

    from lucifer.account import Account
    from lucifer.bot import Bot
    from lucifer.protocol import Tank
    from lucifer.world import Tile, World

    bot = Bot(account=Account(username="uji", password="", method="legacy",
                              label="uji"), label="uji")
    w = World()
    w.name, w.width, w.height = "UJI", 5, 5
    for y in range(5):
        for x in range(5):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=6))
    w.tile(2, 3).fg = 100
    bot.world = w

    # Blok pecah: fg jadi 0, koordinat di int_x/int_y (bukan di ext).
    ext = struct.pack("<HHHH", 0, 6, 0, 0)
    bot._apply_tile_update(Tank(type=5, int_x=2, int_y=3), ext)
    cek("tile dipecah lewat koordinat tank", w.tile(2, 3).fg == 0,
        str(w.tile(2, 3)))

    ext = struct.pack("<HHHH", 2, 6, 0, 0)
    bot._apply_tile_update(Tank(type=5, int_x=2, int_y=3), ext)
    cek("tile ditaruh lewat koordinat tank", w.tile(2, 3).fg == 2,
        str(w.tile(2, 3)))


def main() -> int:
    print("\033[1m" + "=" * 62)
    print(" UJI UNIT LUCIFER LINUX (tanpa jaringan)")
    print("=" * 62 + "\033[0m")
    for fn in (test_protocol, test_hash, test_items, test_world,
               test_lua_api, test_addbot_tabel, test_bot_aksi,
               test_login_payload_mobile, test_client_data_konsisten,
               test_remove_color, test_maintenance, test_captcha_callback,
               test_logon_fail_cooldown, test_hint_login_tidak_salah_menyebut_sandi,
               test_perintah_tanpa_argumen,
               test_status_gems_level, test_tile_update_koordinat,
               test_proxypool_kredensial_unik, test_malady_dari_dialog,
               test_modify_inventory,
               test_echo_place_kurangi_inventory, test_hit_counter,
               test_posisi_tidak_memindah_bot,
               test_merge_drop_total_bukan_tambahan, test_echo_break_konfirmasi,
               test_arti_value_item_change_object, test_tabel_arti_tank,
               test_state_identik_tidak_spam_log,
               test_uid_drop_dari_counter,
               test_uid_ke_item_id_untuk_pickup,
               test_uid_item_dari_sendmapdata,
               test_autocollect_uid_dipakai_ulang, test_collected_dengan_kode_warna,
               test_place_door_mengurangi_stok, test_echo_orang_lain_diabaikan,
               test_collect_int_x_bukan_count,
               test_google_oauth, test_google_state_wajib,
               test_pisah_code_state, test_token_dari_halaman,
               test_relay_udp):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback

            print(f"\n\033[31mBAGIAN GAGAL: {fn.__name__}: {type(e).__name__}: {e}\033[0m")
            traceback.print_exc()
            catat_gagal(f"bagian {fn.__name__} error: {type(e).__name__}: {e}")
    print("\n" + "=" * 62)
    print(f" lulus: {PASS}   gagal: {FAIL}")
    print("=" * 62)
    if GAGAL:
        print("\033[31myang gagal:\033[0m")
        for n in GAGAL:
            print(f"  - {n}")
        return 1
    print("\033[32mSEMUA UJI UNIT LULUS\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
