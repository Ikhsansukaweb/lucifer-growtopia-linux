#!/usr/bin/env python3
"""
tools/bukti_login.py — Bukti nyata isi request ke login.growtopiagame.com.

Menjalankan alur login persis seperti bot, lalu mencetak SETIAP request dan
respons pada lapisan HTTP (isi yang dibungkus TLS). Sandi & token disamarkan
otomatis sehingga aman di-paste ke chat/issue.

Pakai:
    .venv/bin/python tools/bukti_login.py
    .venv/bin/python tools/bukti_login.py --user NamaSaya --pass Rahasia
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lucifer.account import (  # noqa: E402
    DASHBOARD_VALKEY,
    GAME_UA,
    LOGIN_HOST,
    SERVER_DATA_URLS,
    build_client_data,
    fetch_server_data,
)

try:
    import requests
except ImportError:  # pragma: no cover
    print("butuh paket 'requests' (pip install requests)")
    raise SystemExit(1)


def samarkan(teks: str, rahasia: list[str]) -> str:
    """Ganti nilai sensitif dengan penanda, agar aman ditampilkan."""
    out = str(teks)
    for r in rahasia:
        if r:
            out = out.replace(r, "[DISAMARKAN]")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Buktikan isi request login Growtopia")
    ap.add_argument("--user", default="contoh_pengguna", help="nama GrowID")
    ap.add_argument("--pass", dest="sandi", default="sandi_contoh_123",
                    help="sandi (disamarkan di keluaran)")
    ap.add_argument("--protocol", type=int, default=225)
    ap.add_argument("--version", default="5.4")
    a = ap.parse_args()

    rahasia = [a.sandi]

    print("=" * 72)
    print(" BAGIAN 1 — YANG DIKIRIM (request keluar)")
    print("=" * 72)

    print("\n[1] Ambil daftar server (server_data.php)")
    try:
        sd = fetch_server_data(protocol=a.protocol, version=a.version)
        print(f"    URL   : {SERVER_DATA_URLS[0]}")
        print(f"    hasil : server={sd.get('server')} port={sd.get('port')}")
        print(f"    meta  : {str(sd.get('meta'))[:64]}")
    except Exception as e:  # noqa: BLE001
        print(f"    (gagal ambil server_data: {e})")
        sd = {"meta": ""}

    print("\n[2] Blok client_data yang dikirim ke /player/login/dashboard")
    blob = build_client_data(
        protocol=a.protocol, version=a.version, meta=sd.get("meta", ""),
        username=a.user, password=a.sandi,
    )
    blob = str(blob)
    for baris in blob.split("\n"):
        if baris.strip():
            print("      " + samarkan(baris, rahasia))

    data_field = base64.b64encode(blob.encode()).decode()
    print("\n    dikirim sebagai form field 'data' (base64):")
    print("      data=" + samarkan(data_field, rahasia)[:88] + "...")
    print("\n    header:")
    print(f"      User-Agent   : {GAME_UA}")
    print("      Content-Type : application/x-www-form-urlencoded")

    print("\n" + "=" * 72)
    print(" BAGIAN 2 — YANG DIAMBIL (respons server)")
    print("=" * 72)

    s = requests.Session()
    s.headers.update({"User-Agent": GAME_UA})
    url = f"{LOGIN_HOST}/player/login/dashboard"

    r1 = s.post(url, data={"data": data_field}, allow_redirects=False, timeout=30)
    print(f"\n[3] POST {url}")
    print(f"    -> HTTP {r1.status_code}")
    loc = r1.headers.get("Location", "")
    print(f"    -> Location: {samarkan(loc, rahasia)[:96]}")

    if r1.status_code in (301, 302, 303, 307, 308) and loc:
        target = loc if loc.startswith("http") else LOGIN_HOST + loc
        print(f"\n[4] GET {samarkan(target, rahasia)[:96]}...")
        print("    (redirect WAJIB diikuti dengan GET — POST ke URL ini -> 405)")
        r2 = s.get(target, timeout=30)
        print(f"    -> HTTP {r2.status_code}")
        print(f"    -> Content-Type: {r2.headers.get('Content-Type')}")
        print("    -> body JSON:")
        try:
            j = json.loads(r2.text)
            for k, v in j.items():
                if k.lower() in ("token", "ltoken") and v:
                    v = "[TOKEN ADA — DISAMARKAN]"
                elif k.lower() == "url" and v:
                    v = samarkan(v, rahasia)
                print(f"         {k:12s} = {v}")
            if j.get("token"):
                print("\n    >>> 'token' di atas ITULAH ltoken yang dipakai bot.")
        except ValueError:
            print(f"         (bukan JSON) {r2.text[:200]}")
    else:
        print("\n    (tidak ada redirect — bentuk respons tak terduga)")

    print("\n" + "=" * 72)
    print(" RINGKASAN")
    print("=" * 72)
    print("""
  DIKIRIM : POST /player/login/dashboard
            data = base64 dari blok key|value:
              tankIDName (nama akun), tankIDPass (SANDI), protocol,
              game_version, klv, meta, rid, mac, platformID, lmode

  DIAMBIL : 302 -> GET /player/link/dashboard/validate/<payload>
            JSON: {status, message, token, url, accountType, accountAge}

            'token' = ltoken -> dipakai bot untuk login ke server game (ENet).
            Sandi TIDAK dipakai lagi setelah ltoken didapat.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
