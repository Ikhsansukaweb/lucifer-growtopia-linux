#!/usr/bin/env python3
"""
tools/ltoken.py — Ambil `ltoken` Growtopia dari data login klien.

KENAPA ALAT INI ADA
-------------------
Klien Growtopia mengirim kredensial ke server dalam satu blok teks
`key|value` yang di-base64, isinya seperti:

    tankIDName|NamaGrowID
    tankIDPass|sandi
    ltoken|Xk9f...            <-- INI yang kita cari
    rid|A1B2C3...
    mac|02:00:00:00:00:00

Blok itu terlihat di proxy debug (mitmproxy/HTTP Toolkit) saat kamu login
sekali saja di HP/PC. Setelah didapat, `ltoken` bisa dipakai berkali-kali
oleh bot TANPA login Google lagi.

CARA PAKAI
----------
  1. Simpan blok client_data ke file:
         python3 tools/ltoken.py --file client_data.txt
  2. Atau tempel langsung sebagai argumen (pakai tanda kutip):
         python3 tools/ltoken.py --data "dGFua0lETmFtZXxOYW1h..."
  3. Atau dari clipboard (butuh xclip/wl-paste):
         python3 tools/ltoken.py --clipboard
  4. Simpan hasilnya langsung ke data/accounts.json:
         python3 tools/ltoken.py --file client_data.txt --save
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Dekode
# --------------------------------------------------------------------------- #
def _coba_base64(teks: str) -> str | None:
    """Dekode base64 (tahan terhadap padding hilang & spasi/baris baru)."""
    bersih = re.sub(r"\s+", "", teks)
    # URL-safe -> standar
    bersih = bersih.replace("-", "+").replace("_", "/")
    bersih += "=" * (-len(bersih) % 4)
    try:
        return base64.b64decode(bersih, validate=False).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return None


def parse_client_data(teks: str) -> dict[str, str]:
    """Ubah blok `key|value` (base64 atau teks biasa) menjadi dict.

    Mendukung tiga bentuk yang dipakai klien Growtopia:
      1. `key|value` per baris          (bentuk login/dashboard — paling umum)
      2. satu baris: `k1|v1|k2|v2|...`  (tanpa newline)
      3. keduanya dalam base64
    """
    hasil: dict[str, str] = {}

    def telan_per_baris(isi: str) -> None:
        for baris in re.split(r"[\r\n]+", isi):
            baris = baris.strip()
            if not baris or "|" not in baris:
                continue
            k, _, v = baris.partition("|")
            k = k.strip()
            if k:
                hasil.setdefault(k, v.strip())

    def telan_berpasangan(isi: str) -> None:
        """Urai 'k1|v1|k2|v2|...' (satu baris)."""
        bagian = [b.strip() for b in isi.strip().split("|")]
        for i in range(0, len(bagian) - 1, 2):
            k, v = bagian[i], bagian[i + 1]
            if k:
                hasil.setdefault(k, v)

    # Siapkan kandidat teks: apa adanya + versi base64 (kalau bisa didekode)
    kandidat = [teks]
    d = _coba_base64(teks)
    if d and d != teks:
        kandidat.append(d)

    for isi in kandidat:
        satu_baris = "\n" not in isi.strip() and "\r" not in isi

        # Bentuk 2: satu baris berpasangan — HARUS dicoba lebih dulu, karena
        # 'telan_per_baris' akan salah membaca 'tankIDName|X|ltoken|Y' sebagai
        # tankIDName = "X|ltoken|Y".
        if satu_baris and isi.count("|") >= 4:
            telan_berpasangan(isi)
            if "ltoken" in hasil:
                return hasil

        # Bentuk 1: key|value per baris
        telan_per_baris(isi)
        if "ltoken" in hasil:
            return hasil

    return hasil


def ambil_clipboard() -> str:
    for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"]):
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=5, check=False)
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", "replace")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


# --------------------------------------------------------------------------- #
# Simpan ke accounts.json
# --------------------------------------------------------------------------- #
def simpan_akun(nama: str, ltoken: str, label: str = "") -> Path:
    p = ROOT / "data" / "accounts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    akun: list[dict] = []
    if p.exists():
        try:
            akun = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(akun, dict):
                akun = akun.get("accounts", [])
        except (ValueError, OSError):
            akun = []

    label = label or (nama.lower() or "main")
    # ganti kalau label sudah ada, kalau tidak tambahkan
    for a in akun:
        if a.get("label") == label:
            a.update({"username": nama, "method": "token", "ltoken": ltoken})
            break
    else:
        akun.append({"label": label, "username": nama, "method": "token", "ltoken": ltoken})

    p.write_text(json.dumps(akun, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    p.chmod(0o600)  # berisi rahasia
    return p


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Ambil ltoken Growtopia dari blok client_data (hasil proxy debug).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--data", default="", help="blok client_data (base64 atau teks key|value)")
    src.add_argument("--file", default="", help="file berisi blok client_data")
    src.add_argument("--clipboard", action="store_true", help="ambil dari clipboard")
    ap.add_argument("--save", action="store_true", help="simpan ke data/accounts.json")
    ap.add_argument("--label", default="", help="label akun saat disimpan (default: nama growid)")
    ap.add_argument("--json", action="store_true", help="cetak hasil sebagai JSON")
    args = ap.parse_args(argv)

    # -- ambil sumber ------------------------------------------------------- #
    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"error: file tidak ada: {p}", file=sys.stderr)
            return 1
        teks = p.read_text(encoding="utf-8", errors="replace")
        sumber = f"file {p}"
    elif args.data:
        teks = args.data
        sumber = "argumen --data"
    elif args.clipboard:
        teks = ambil_clipboard()
        if not teks:
            print("error: clipboard kosong / butuh wl-paste atau xclip", file=sys.stderr)
            return 1
        sumber = "clipboard"
    else:
        ap.print_help()
        print("\ntip: jalankan `lucifer ltoken --help` untuk versi singkatnya.")
        return 0

    # -- urai --------------------------------------------------------------- #
    d = parse_client_data(teks)
    if not d:
        print("error: tidak ada field 'key|value' yang terbaca.", file=sys.stderr)
        print("       pastikan isinya blok client_data (mengandung 'ltoken|' atau 'tankIDName|').",
              file=sys.stderr)
        return 1

    nama = d.get("tankIDName", "")
    ltoken = d.get("ltoken", "")
    rid = d.get("rid", "")
    mac = d.get("mac", "")

    if args.json:
        print(json.dumps(
            {"sumber": sumber, "growid": nama, "ltoken": ltoken, "rid": rid, "mac": mac,
             "semua_field": sorted(d.keys())},
            indent=2, ensure_ascii=False))
        return 0 if ltoken else 1

    print("=" * 62)
    print(f" ltoken Growtopia — sumber: {sumber}")
    print("=" * 62)
    print(f"  GrowID      : {nama or '(tidak ada di blok ini)'}")
    print(f"  ltoken      : {ltoken or '(TIDAK DITEMUKAN)'}")
    print(f"  rid         : {rid or '-'}")
    print(f"  mac         : {mac or '-'}")
    print(f"  field lain  : {', '.join(sorted(d.keys()))}")
    print()

    if not ltoken:
        print("  ! Blok ini TIDAK memuat ltoken.")
        print("    Kemungkinan yang kamu tangkap adalah request login (belum ada ltoken),")
        print("    bukan request SETELAH login. Coba:")
        print("      - restart Growtopia lewat proxy, lalu lihat request ke")
        print("        login.growtopiagame.com atau request 'tankIDName' berikutnya")
        print("      - atau pakai `lucifer login --user NAMA --pass SANDI` (GrowID)")
        return 1

    print("  Langkah berikutnya:")
    print(f"    lucifer login --ltoken \"{ltoken[:12]}...\"     # simpan ke accounts.json")
    if args.save:
        p = simpan_akun(nama or "akun", ltoken, args.label)
        print()
        print(f"  ✓ tersimpan ke {p} (chmod 600)")
        print("    jalankan: lucifer doctor && lucifer run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
