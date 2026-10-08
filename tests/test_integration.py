#!/usr/bin/env python3
"""
tests/test_integration.py — Uji rantai penuh ke server Growtopia ASLI.

Yang diuji (semuanya nyata, bukan tiruan):
  1. server_data.php resmi bisa diambil
  2. ENet patch Growtopia bisa connect ke server game
  3. ServerHello diterima -> artinya codec + CRC32 + range coder benar
  4. Paket balasan server bisa diuraikan (teks Growtopia)
  5. Rantai LENGKAP: skrip Lua -> API Bot -> ENet -> server GT -> balasan

Jalankan:  .venv/bin/python tests/test_integration.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL, SKIP = 0, 0, 0


def cek(nama: str, kondisi: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if kondisi:
        PASS += 1
        print(f"  \033[32m✓\033[0m {nama}" + (f"  \033[90m{detail}\033[0m" if detail else ""))
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {nama}" + (f"  \033[90m{detail}\033[0m" if detail else ""))
    return kondisi


def bagian(judul: str) -> None:
    print(f"\n\033[1;36m== {judul} ==\033[0m")


# --------------------------------------------------------------------------- #
def test_server_data() -> dict:
    bagian("1. Endpoint server_data.php resmi")
    from lucifer.account import fetch_server_data

    t0 = time.time()
    sd = fetch_server_data()
    dt = (time.time() - t0) * 1000
    cek("respons diterima", bool(sd), f"{dt:.0f} ms")
    cek("ada 'server'", bool(sd.get("server")), sd.get("server", ""))
    cek("ada 'port'", bool(sd.get("port")), sd.get("port", ""))
    cek("ada 'meta'", bool(sd.get("meta")), sd.get("meta", "")[:24] + "...")
    return sd


def test_enet_handshake(sd: dict) -> bool:
    bagian("2. Handshake ENet ke server game (patch Ubisoft)")
    from lucifer.enet import ENetHost, library_path
    from lucifer.protocol import NetMessage, parse_packet

    cek("library ENet dimuat", bool(library_path()), str(library_path()))
    host, port = sd["server"], int(sd["port"])

    h = ENetHost()
    t0 = time.time()
    ok = h.connect(host, port, 8000)
    cek("ENet connect", ok, f"{(time.time()-t0)*1000:.0f} ms -> {host}:{port}")
    if not ok:
        h.close()
        return False

    cek("ping terbaca", h.ping >= 0, f"{h.ping} ms")

    tipe_diterima = []
    got_hello = False
    deadline = time.time() + 12
    while time.time() < deadline:
        ev = h.service(1500)
        if ev.kind == "receive":
            mtype, payload = parse_packet(ev.data)
            tipe_diterima.append(mtype)
            if mtype == NetMessage.ServerHello:
                got_hello = True
                break
        elif ev.kind in ("disconnect", "timeout"):
            break

    cek("ServerHello diterima", got_hello, f"tipe={tipe_diterima}")
    h.close()
    return got_hello


def test_packet_roundtrip(sd: dict) -> bool:
    bagian("3. Codec paket (kirim login -> terima balasan server)")
    from lucifer.enet import ENetHost
    from lucifer.protocol import NetMessage, build_packet, decode_text, parse_packet

    h = ENetHost()
    if not h.connect(sd["server"], int(sd["port"]), 8000):
        cek("connect", False)
        h.close()
        return False

    # tunggu ServerHello
    for _ in range(8):
        ev = h.service(1500)
        if ev.kind == "receive":
            mtype, _ = parse_packet(ev.data)
            if mtype == NetMessage.ServerHello:
                break

    # kirim login legacy (kredensial sengaja salah — yang diuji jalurnya, bukan akunnya)
    payload = b"tankIDName|lucifer_linux_probe\ntankIDPass|invalid\nprotocol|225\ngame_version|5.4\nplatformID|0,1,1\n"
    h.send(build_packet(NetMessage.GenericText, payload))

    balasan = ""
    deadline = time.time() + 10
    while time.time() < deadline:
        ev = h.service(1500)
        if ev.kind == "receive":
            mtype, body = parse_packet(ev.data)
            if mtype in (NetMessage.GameMessage, NetMessage.GenericText):
                d = decode_text(body)
                balasan = d.get("msg") or d.get("action") or ""
                if balasan:
                    break
        elif ev.kind in ("disconnect", "timeout"):
            break
    h.close()

    cek("server membalas paket terurai", bool(balasan), balasan[:80])
    return bool(balasan)


def test_lua_chain() -> bool:
    bagian("4. Rantai LENGKAP: skrip Lua -> Bot -> ENet -> server GT")
    from lucifer.account import Account, fetch_server_data
    from lucifer.items import ItemDatabase
    from lucifer.lua_api import LuaEngine

    sd = fetch_server_data()
    items = None
    p = ROOT / "data" / "items.dat"
    if p.exists():
        items = ItemDatabase.from_file(p)
        cek("items.dat dimuat", True, f"{len(items)} item v{items.version}")

    # Kredensial dummy: yang diuji adalah rantai transport + runtime Lua,
    # bukan validitas akun. Server GT akan menjawab "Fail to login" — itu
    # justru bukti paket kita diterima dan dijawab server asli.
    acc = Account(username="lucifer_linux_probe", password="invalid", method="legacy", label="probe")
    engine = LuaEngine(accounts=[acc], items_db=items, scripts_dir=ROOT / "scripts",
                       data_dir=ROOT / "data", username="uji")
    engine._new_bot(acc, "probe")

    script = ROOT / "examples" / "_uji_integrasi.lua"
    ok_script = engine.run_script_file(script)
    cek("skrip Lua dieksekusi", ok_script)

    # tunggu sampai skrip selesai (skrip sendiri memompa event via sleep)
    t0 = time.time()
    bot = engine.bots["probe"]
    while time.time() - t0 < 45:
        engine._pump_once(0.2)
        if engine.console_lines and time.time() - t0 > 5:
            if any("KESIMPULAN" in ln for ln in engine.console_lines):
                break
        if bot.status == "offline" and time.time() - t0 > 20:
            break

    balasan = [ln for ln in engine.console_lines if "EVENT dari server" in ln]
    cek("event server sampai ke handler Lua", bool(balasan),
        balasan[0].split("EVENT dari server")[-1].strip()[:70] if balasan else "tidak ada")
    cek("bot membuat koneksi ENet nyata", bot.server is not None,
        f"{bot.server[0]}:{bot.server[1]}" if bot.server else "")

    engine.stop()
    return bool(balasan)


def main() -> int:
    print("\033[1m" + "=" * 62)
    print(" UJI INTEGRASI LUCIFER LINUX -> SERVER GROWTOPIA ASLI")
    print("=" * 62 + "\033[0m")

    try:
        sd = test_server_data()
        hello = test_enet_handshake(sd)
        balasan = test_packet_roundtrip(sd)
        lua_ok = test_lua_chain()
    except KeyboardInterrupt:
        print("\ndihentikan")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"\n\033[31merror tak terduga: {type(e).__name__}: {e}\033[0m")
        import traceback

        traceback.print_exc()
        return 1

    print("\n" + "=" * 62)
    print(f" lulus: {PASS}   gagal: {FAIL}")
    print("=" * 62)
    if FAIL == 0 and hello and balasan and lua_ok:
        print("\033[32mSEMUA UJI NYATA LULUS — rantai Lua -> ENet -> Growtopia bekerja\033[0m")
        return 0
    print("\033[31mADA UJI YANG GAGAL\033[0m")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
