#!/usr/bin/env python3
"""Uji lapisan kompatibilitas deltaX (`lucifer/compat_deltax.py`).

Yang diuji: nama API yang dipakai skrip fitur deltaX asli benar-benar ada dan
berperilaku sama. Skrip acuan = `assets/misc/*.lua.enc` deltaX yang sudah
didekripsi (lihat `RE_libPowerKuy.md`), bukan rekaan.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lucifer.account import Account  # noqa: E402
from lucifer.bot import Bot, Player  # noqa: E402
from lucifer.lua_api import LuaEngine  # noqa: E402
from lucifer.world import DroppedItem, Tile, World  # noqa: E402

LULUS = 0
GAGAL = 0


def cek(nama: str, kondisi: bool, info: str = "") -> None:
    global LULUS, GAGAL
    if kondisi:
        LULUS += 1
        print(f"  \u2713 {nama}" + (f"  {info}" if info else ""))
    else:
        GAGAL += 1
        print(f"  \u2717 {nama}" + (f"  {info}" if info else ""))


def buat_engine(data_dir: str | Path | None = None) -> tuple[LuaEngine, Bot, list]:
    acc = Account(username="uji", method="token", ltoken="X" * 10)
    b = Bot(acc, label="uji")

    w = World(name="UJI", width=4, height=2)
    tiles = [Tile(x=x, y=y, fg=0, bg=2) for y in range(2) for x in range(4)]
    tiles[0].fg = 3
    tiles[0].extra_type = 4
    tiles[0].flags = 1
    tiles[0].ready = True
    w.tiles = tiles
    w.dropped = [DroppedItem(item_id=3, x=16, y=16, count=1, uid=55)]
    b.world = w
    b.local = Player(netid=1, name="aku", posx=16.0, posy=16.0, isLocalPlayer=True)

    eng = LuaEngine(accounts=[acc], data_dir=data_dir or tempfile.mkdtemp())
    eng.parent = b
    if getattr(eng, "bots", None) is not None:
        eng.bots["uji"] = b

    keluar: list = []
    b.send_packet = lambda t, body: keluar.append(("text", int(t), body)) or True
    b.send_raw = lambda tk, ext=b"": keluar.append(
        ("raw", int(tk.type), tk.int_x, tk.int_y, tk.value)
    ) or True
    b.getPath = lambda x, y: [(1, 1), (0, 0)]
    b.moveTile = lambda x, y: True
    return eng, b, keluar


def uji_global() -> None:
    print("== global API deltaX terpasang ==")
    eng, _, _ = buat_engine()
    g = eng.lua.globals()
    for nama in (
        "getLocal", "getTiles", "getTile", "getObjectList", "getWorldTileMap",
        "getCurrentWorldName", "GetInventory", "getItemInfoByID",
        "getItemInfoByName", "getValue", "editValue", "setValue", "bindValue",
        "sendPacket", "SendPacket", "sendPacketRaw", "sendVariant",
        "addHook", "removeHook", "runCoroutine", "Sleep", "CSleep",
        "LogToConsole", "log", "isInside", "getTime", "FindPath",
        "applyHook", "await", "UserInterface", "growtopia",
    ):
        cek(f"global {nama}", g[nama] is not None)


def uji_nilai() -> None:
    print("== getValue / editValue / bindValue ==")
    eng, _, _ = buat_engine()
    ok = eng.run_script_source(
        """
        editValue("x", 5)
        assert(getValue(1, "x") == 5, "editValue -> getValue")
        local f = bindValue(1, "x", 9)
        assert(f() == 5, "bindValue pakai nilai tersimpan")
        local d = bindValue(1, "kosong", 42)
        assert(d() == 42, "bindValue pakai default")
        setValue("Antibounce", true)
        assert(getValue(0, "Antibounce") == true, "setValue")
        return true
        """,
        "uji_nilai",
    )
    cek("getValue/editValue/bindValue/setValue", ok)


def uji_nilai_persisten() -> None:
    print("== nilai tersimpan ke disk ==")
    d = tempfile.mkdtemp()
    eng, _, _ = buat_engine(d)
    eng.run_script_source('editValue("simpan_ini", 123) return true', "set")
    eng2, _, _ = buat_engine(d)
    ok = eng2.run_script_source(
        'assert(getValue(1, "simpan_ini") == 123, "nilai hilang") return true',
        "get",
    )
    cek("nilai bertahan antar-engine", ok)


def uji_dunia() -> None:
    print("== data dunia ==")
    eng, _, _ = buat_engine()
    ok = eng.run_script_source(
        """
        local tiles = getTiles()
        assert(#tiles == 8, "jumlah tile " .. #tiles)
        assert(tiles[1].extra == true, "extra")
        assert(tiles[1].readyharvest == true, "readyharvest")
        assert(tiles[1].itemid == 3, "itemid")
        assert(getTile(0, 0).fg == 3, "getTile isi")
        assert(getTile(1, 0).fg == 0, "getTile kosong")
        assert(getTile(9, 9) == nil, "getTile di luar dunia")
        local objs = getObjectList()
        assert(#objs == 1, "jumlah objek")
        assert(objs[1].itemid == 3 and objs[1].id == 55, "objek")
        assert(objs[1].pos.x == 16, "posisi objek")
        local m = getWorldTileMap()
        assert(m.size.x == 4 and m.size.y == 2, "ukuran dunia")
        assert(getCurrentWorldName() == "UJI", "nama dunia")
        local me = getLocal()
        assert(me.pos.x == 16 and me.posX == 16, "posisi lokal")
        assert(me.netID == 1, "netid lokal")
        return true
        """,
        "uji_dunia",
    )
    cek("getTiles/getTile/getObjectList/getLocal", ok)


def uji_kirim() -> None:
    print("== pengiriman paket ==")
    eng, _, keluar = buat_engine()
    ok = eng.run_script_source(
        """
        sendPacket(2, "action|respawn\\n")
        sendPacketRaw(false, {type=3, px=1, py=1, value=14})
        sendPacketRaw(false, {type=7, px=2, py=0})
        sendVariant({v1="OnNameChanged", v2="Budi"}, nil, 5)
        return true
        """,
        "uji_kirim",
    )
    cek("skrip jalan", ok)
    cek(
        "sendPacket teks",
        keluar[0][0] == "text" and keluar[0][2] == "action|respawn\n",
        repr(keluar[0]),
    )
    cek("sendPacketRaw TileChange", keluar[1] == ("raw", 3, 1, 1, 14), str(keluar[1]))
    cek("sendPacketRaw TileActivate", keluar[2] == ("raw", 7, 2, 0, 0), str(keluar[2]))
    cek("sendVariant CallFunction", keluar[3][0] == "raw" and keluar[3][1] == 1)


def uji_findpath_terbalik() -> None:
    print("== FindPath terbalik (True = gagal) ==")
    eng, b, _ = buat_engine()
    ok = eng.run_script_source(
        """
        assert(FindPath(0, 0) == false, "jalur ada harus False")
        return true
        """,
        "fp_ada",
    )
    cek("FindPath jalur ada -> False", ok)

    b.getPath = lambda x, y: []
    ok2 = eng.run_script_source(
        'assert(FindPath(0, 0) == true, "jalur kosong harus True") return true',
        "fp_kosong",
    )
    cek("FindPath jalur kosong -> True", ok2)


def uji_skrip_automation_asli() -> None:
    print("== skrip automation.lua deltaX asli ==")
    asli = (
        Path.home()
        / ".hermes/workspace/growlauncher/decrypted_lua/automation.lua"
    )
    if not asli.exists():
        print("  (dilewati: berkas acuan tidak ada)")
        return
    src = asli.read_text(encoding="utf-8")
    # `while true do ... end` di akhir skrip = loop abadi; dipotong untuk uji.
    src = src[: src.rindex("while true do")]
    src += """
    editValue("autoharvest_isactive", true)
    editValue("automation_base_itemid", 3)
    AutoHarvest.Loop()
    AutoPlant.Loop()
    return true
    """
    eng, _, keluar = buat_engine()
    ok = eng.run_script_source(src, "automation_asli")
    cek("automation.lua termuat & jalan", ok)
    mentah = [k for k in keluar if k[0] == "raw"]
    cek(
        "AutoHarvest memukul tile siap panen",
        any(k[1] == 3 and k[4] == 18 for k in mentah),
        str(mentah),
    )


def main() -> int:
    uji_global()
    uji_nilai()
    uji_nilai_persisten()
    uji_dunia()
    uji_kirim()
    uji_findpath_terbalik()
    uji_skrip_automation_asli()
    print("\n" + "=" * 62)
    print(f" lulus: {LULUS}   gagal: {GAGAL}")
    print("=" * 62)
    return 1 if GAGAL else 0


if __name__ == "__main__":
    sys.exit(main())
