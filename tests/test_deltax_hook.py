"""Uji hook deltaX: onvariant, ongamepacket, onvalue, onsendpacket, ondraw."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lucifer.protocol as P  # noqa: E402
from lucifer.lua_api import LuaEngine  # noqa: E402

LULUS = GAGAL = 0
GAGAL_NAMA: list[str] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> bool:
    global LULUS, GAGAL
    if kondisi:
        LULUS += 1
        print(f"  ✓ {nama}" + (f"  {detail}" if detail else ""))
    else:
        GAGAL += 1
        GAGAL_NAMA.append(nama)
        print(f"  ✗ {nama}  {detail}")
    return kondisi


class HostPalsu:
    """Host ENet palsu: kiriman ditampung, bukan dikirim."""

    def __init__(self) -> None:
        self.kirim: list[bytes] = []

    def send(self, data: bytes) -> bool:
        self.kirim.append(bytes(data))
        return True


def buat_engine():
    eng = LuaEngine(data_dir="/tmp/opencode/data_uji", scripts_dir="/tmp/opencode/skrip_uji")
    eng.on_log = lambda s: None
    return eng


def uji_variant_field() -> None:
    print("== var.v1/v2 + packet.x/px ==")
    eng = buat_engine()
    vl = P.VariantList()
    vl.append(P.Variant.from_string("OnDialogRequest"))
    vl.append(P.Variant.from_string("isi dialog"))
    t = eng._variantlist_to_lua(vl)
    cek("var.v1 terbaca", t.v1 == "OnDialogRequest", repr(t.v1))
    cek("var.v2 terbaca", t.v2 == "isi dialog", repr(t.v2))
    cek("var.v3 nil untuk variant kosong", t.v3 is None)

    tank = P.Tank(type=14, net_id=-1, vector_x=96.0, vector_y=160.0, int_x=3, int_y=5)
    pkt = eng._game_packet_from_tank(tank)
    cek("packet.x = piksel", pkt.x == 96.0, str(pkt.x))
    cek("packet.y = piksel", pkt.y == 160.0, str(pkt.y))
    cek("packet.px = tile", pkt.px == 3, str(pkt.px))
    cek("packet.py = tile", pkt.py == 5, str(pkt.py))
    cek("packet.netid", pkt.netid == -1, str(pkt.netid))


def uji_hook_variant() -> None:
    print("== addHook onvariant / ongamepacket ==")
    eng = buat_engine()
    hasil: list[str] = []
    eng.lua.execute("""
        function onVariant(var, packet)
            _catat("var1=" .. tostring(var.v1))
            _catat("netid=" .. tostring(packet.netid))
            if var.v1 == "OnTextOverlay" then var.v2 = "diubah" return true end
        end
        function onGamePacket(packet)
            _catat("pkt=" .. tostring(packet.type) .. "@" .. tostring(packet.px) .. "," .. tostring(packet.py))
        end
        addHook(onVariant, "onvariant")
        addHook(onGamePacket, "ongamepacket")
    """)
    eng.lua.globals()._catat = hasil.append

    vl = P.VariantList()
    vl.append(P.Variant.from_string("OnTextOverlay"))
    vl.append(P.Variant.from_string("halo"))
    eng._route_event("variant", (vl, 42))
    cek("onVariant menerima var + packet", "var1=OnTextOverlay" in hasil, str(hasil))
    cek("packet.netid tersedia", "netid=42" in hasil, str(hasil))

    # deltaX menimpa `var.v2` lalu memanggil `sendVariant(var, packet)` —
    # jadi yang diuji adalah hasil kiriman, bukan objek Python-nya.
    bot = eng._new_bot(type("A", (), {"label": "uji", "username": "uji", "proxy": ""})())
    host = HostPalsu()
    bot.host = host
    eng.lua.execute("""
        local var = {}
        var.v1 = "OnTextOverlay"
        var.v2 = "halo"
        onVariant(var, {netid = 0})
        sendVariant(var)
    """)
    mentah = host.kirim[-1] if host.kirim else b""
    cek("var.v2 hasil edit ikut terkirim", b"diubah" in mentah and b"halo" not in mentah,
        str(mentah[:80]))

    eng._route_event("game_packet", P.Tank(type=14, int_x=7, int_y=9))
    cek("onGamePacket menerima packet", "pkt=14@7,9" in hasil, str(hasil))


def uji_hook_value() -> None:
    print("== editValue -> onvalue ==")
    eng = buat_engine()
    hasil: list[str] = []
    eng.lua.execute("""
        function onValue(tipe, nama, nilai)
            _catat(tostring(tipe) .. ":" .. nama .. "=" .. tostring(nilai))
        end
        addHook(onValue, "onvalue")
        editValue("autodrop_posx", 12)
        editValue("auto_toggle", true)
    """)
    eng.lua.globals()._catat = hasil.append
    eng._pump_once(0.05)
    eng._pump_once(0.05)
    cek("onvalue angka (tipe 1)", "1:autodrop_posx=12" in hasil, str(hasil))
    cek("onvalue toggle (tipe 0)", "0:auto_toggle=true" in hasil, str(hasil))


def uji_hook_sendpacket() -> None:
    print("== onsendpacket (sinkron, bisa membatalkan) ==")
    eng = buat_engine()
    bot = eng._new_bot(type("A", (), {"label": "uji", "username": "uji", "proxy": ""})())
    host = HostPalsu()
    bot.host = host
    hasil: list[str] = []
    eng.lua.execute("""
        function onSendPacket(teks, tipe)
            _catat("kirim:" .. tipe .. ":" .. teks:sub(1, 12))
            if teks:find("action|quit_to_exit") then return true end
        end
        addHook(onSendPacket, "onsendpacket")
    """)
    eng.lua.globals()._catat = hasil.append

    terkirim = bot.send_packet(2, "action|input\n|text|halo\n")
    cek("paket normal tetap terkirim", terkirim and len(host.kirim) == 1, str(len(host.kirim)))
    cek("hook melihat paket keluar", any("kirim:2:action|input" in h for h in hasil), str(hasil))

    jumlah = len(host.kirim)
    bot.send_packet(2, "action|quit_to_exit\n")
    cek("hook bisa membatalkan paket", len(host.kirim) == jumlah, str(len(host.kirim)))
    cek("tidak ada rekursi hook", len([h for h in hasil if "kirim:2" in h]) == 2, str(hasil))

    eng.lua.execute("removeHook('onsendpacket')")
    bot.send_packet(2, "action|quit_to_exit\n")
    cek("removeHook melepas hook", len(host.kirim) == jumlah + 1)


def uji_hook_draw() -> None:
    print("== ondraw ==")
    eng = buat_engine()
    hasil: list[int] = []
    eng.lua.execute("""
        function onDraw(delta)
            _catat(delta)
        end
        addHook(onDraw, "ondraw")
    """)
    eng.lua.globals()._catat = hasil.append
    eng._route_event("draw", 50)
    cek("ondraw menerima delta", hasil == [50], str(hasil))


def uji_send_variant_urutan() -> None:
    print("== sendVariant v1..vN ==")
    eng = buat_engine()
    bot = eng._new_bot(type("A", (), {"label": "uji", "username": "uji", "proxy": ""})())
    host = HostPalsu()
    bot.host = host
    eng.lua.execute("""
        var = {}
        var.v1 = "OnDialogRequest"
        var.v2 = "isi"
        var.v10 = "akhir"
        var.type = 999
        sendVariant(var)
    """)
    cek("paket variant terkirim", len(host.kirim) == 1, str(len(host.kirim)))
    mentah = host.kirim[0] if host.kirim else b""
    isi = mentah[8 + P.TANK_SIZE:] if len(mentah) > 8 + P.TANK_SIZE else b""
    i1, i2, i10 = isi.find(b"OnDialogRequest"), isi.find(b"isi"), isi.find(b"akhir")
    cek("v1/v2/v10 tersusun numerik", -1 < i1 < i2 < i10, f"idx={i1},{i2},{i10}")
    cek("kunci non-v tidak ikut", b"\x99" not in isi.replace(b"\x00\x00\x00", b""))


def main() -> int:
    uji_variant_field()
    uji_hook_variant()
    uji_hook_value()
    uji_hook_sendpacket()
    uji_hook_draw()
    uji_send_variant_urutan()
    print(f"\n lulus: {LULUS}   gagal: {GAGAL}")
    if GAGAL_NAMA:
        print(" gagal:", ", ".join(GAGAL_NAMA))
    return 1 if GAGAL else 0


if __name__ == "__main__":
    raise SystemExit(main())
