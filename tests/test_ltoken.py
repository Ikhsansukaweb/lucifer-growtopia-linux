#!/usr/bin/env python3
"""
tests/test_ltoken.py — Uji modul ltoken (offline, tanpa HP & tanpa jaringan).

Menguji:
  * regex id_token (JWT) — positif & negatif
  * ltoken_dari_kredensial: bentuk base64 + isi (_token/growId/password/reg)
  * tangkap_id_token TIDAK menggantung saat tidak ada log (regresi bug hang)
  * pindai_buffer tidak meledak saat adb tak ada

Jalankan:  .venv/bin/python tests/test_ltoken.py
"""

from __future__ import annotations

import base64
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lucifer.ltoken import (  # noqa: E402
    ID_TOKEN_RE,
    hp_tersambung,
    ltoken_dari_kredensial,
    tangkap_id_token,
)

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

lulus = 0
gagal = 0


def cek(nama: str, syarat: bool, info: str = "") -> None:
    global lulus, gagal
    if syarat:
        lulus += 1
        print(f"  {GREEN}✓{RESET} {nama}")
    else:
        gagal += 1
        print(f"  {RED}✗{RESET} {nama}  {DIM}{info}{RESET}")


# --- JWT contoh (struktur benar, bukan token nyata) ---------------------- #
JWT = (
    "eyJhbGciOiJSUzI1NiIsImtpZCI6IlRFU1QifQ"
    ".eyJpc3MiOiJhY2NvdW50cy5nb29nbGUuY29tIiwic3ViIjoiMTIzNDU2Nzg5MCJ9"
    ".c2lnbmF0dXJlLXVqaS1hYmNkZWYxMjM0NTY3ODkw"
)


def uji_regex() -> None:
    print(f"\n{BOLD}1. Regex id_token (JWT){RESET}")
    cek("cocok dengan JWT utuh", bool(ID_TOKEN_RE.fullmatch(JWT)))
    cek("tertangkap di tengah kalimat",
        ID_TOKEN_RE.search(f"Token = {JWT}") is not None)
    cek("menolak teks biasa", ID_TOKEN_RE.search("halo dunia") is None)
    cek("menolak JWT dua segmen",
        ID_TOKEN_RE.search("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0") is None)
    # yang tertangkap harus persis token, bukan spasi/teks di sekitarnya
    m = ID_TOKEN_RE.search(f"[{JWT}]")
    cek("hasil search bersih (tanpa kurung)",
        m is not None and m.group(0) == JWT)


def uji_ltoken() -> None:
    print(f"\n{BOLD}2. ltoken dari kredensial{RESET}")
    lt = ltoken_dari_kredensial("IsanLucu", "SandiRahasia123")
    cek("menghasilkan teks", isinstance(lt, str) and len(lt) > 0)

    # ltoken adalah base64 dari string query
    isi = base64.b64decode(lt).decode("utf-8", "replace")
    cek("lapisan luar base64 valid", "_token=" in isi and "&growId=" in isi)

    # field wajib
    cek("memuat growId benar", "growId=IsanLucu" in isi)
    cek("memuat password benar", "password=SandiRahasia123" in isi)
    cek("memuat reg=0", "reg=0" in isi)
    cek("memuat _token=", isi.startswith("_token="))

    # _token adalah base64 dari blok client_data (tankIDName|...)
    m = re.search(r"_token=([^&]+)", isi)
    cek("_token ada isinya", m is not None)
    if m:
        cd = base64.b64decode(urllib.parse.unquote(m.group(1))).decode("utf-8", "replace")
        cek("client_data memuat tankIDName", "tankIDName|IsanLucu" in cd)
        cek("client_data memuat requestedName", "requestedName|" in cd)
        cek("client_data memuat protocol", "protocol|" in cd)

    # rid/mac acak (seperti klien asli) -> ltoken WAJAR berbeda tiap panggilan.
    lt2 = ltoken_dari_kredensial("IsanLucu", "SandiRahasia123")
    isi2 = base64.b64decode(lt2).decode("utf-8", "replace")
    cek("rid/mac acak -> ltoken berbeda tiap panggilan (seperti klien asli)", lt2 != lt)
    cek("tapi kredensial tetap sama di keduanya",
        "growId=IsanLucu" in isi2 and "password=SandiRahasia123" in isi2)

    # kalau client_data diberikan eksplisit, hasil harus deterministik
    cd_tetap = "tankIDName|IsanLucu\ntankIDPass|SandiRahasia123\nprotocol|225\n"
    cek("client_data eksplisit -> deterministik",
        ltoken_dari_kredensial("IsanLucu", "SandiRahasia123", client_data=cd_tetap)
        == ltoken_dari_kredensial("IsanLucu", "SandiRahasia123", client_data=cd_tetap))

    # kredensial beda -> ltoken beda
    cek("beda sandi -> beda ltoken",
        ltoken_dari_kredensial("IsanLucu", "lain") != lt)

    # reg=1 harus ikut berubah
    cek("reg=1 ikut berubah",
        "reg=1" in base64.b64decode(
            ltoken_dari_kredensial("IsanLucu", "x", reg=1)).decode("utf-8", "replace"))


def uji_tidak_menggantung() -> None:
    """Regresi: dulu tangkap_id_token() menggantung karena readline() blocking.

    Sekarang harus SELALU kembali dalam durasi + toleransi kecil, walau
    tidak ada satu pun baris log yang masuk.

    CATATAN: kalau HP tidak tersambung, fungsi memang kembali SEKETIKA dengan
    pesan "HP tidak tersambung" — itu perilaku BENAR (tidak ada gunanya
    menunggu). Karena itu uji "benar-benar menunggu" hanya berlaku saat ada HP.
    """
    print(f"\n{BOLD}3. Tidak menggantung (regresi bug){RESET}")
    ada_hp = hp_tersambung()
    durasi = 3
    t0 = time.time()
    r = tangkap_id_token(durasi=durasi, jalankan=False)
    dt = time.time() - t0
    cek(f"kembali <= {durasi + 6}s (nyata {dt:.1f}s)", dt <= durasi + 6,
        f"terlalu lama: {dt:.1f}s")
    if ada_hp:
        cek("kembali >= durasi (benar-benar menunggu)", dt >= durasi * 0.8,
            f"terlalu cepat: {dt:.1f}s")
    else:
        print(f"  {DIM}~ lewati 'benar-benar menunggu': HP tidak tersambung "
              f"(kembali seketika = perilaku benar){RESET}")
    cek("hasil berupa TangkapToken", hasattr(r, "ok") and hasattr(r, "pesan"))
    cek("ok=False saat tak ada token", r.ok is False)
    cek("pesan memberi petunjuk", "id_token" in r.pesan.lower()
        or "tersambung" in r.pesan.lower())


def uji_savedat() -> None:
    """Uji pembacaan refreshToken dari save.dat (struktur biner GT)."""
    print(f"\n{BOLD}4. refreshToken dari save.dat{RESET}")
    import struct  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from lucifer.ltoken import token_dari_savedat  # noqa: PLC0415

    # Bangun save.dat palsu dengan struktur ASLI (dibaca dari save.dat nyata):
    #   <nama field> <panjang uint32 LE> <nilai>   <- token (string panjang)
    #   <nama field> \x00 \x01 \x00\x00\x00 <panjang uint32 LE> <nilai>
    #                                              <- field string biasa
    TOKEN = ("X3Rva2VuPXRoaXMtaXMtYS1yZWZyZXNoLXRva2VuLXVqaS0xMjM0NTY3OA=="
             "LmFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6MDEyMzQ1Njc4OQ==")
    fcm = "APA91bFNRwBlSCZ8sTSuvGxFYpm96szTrKLpQ55H4wj0X"

    def field_token(nilai: str) -> bytes:
        """Field 'Token' — panjang uint32 LE LANGSUNG setelah nama."""
        b = nilai.encode()
        return b"Token" + struct.pack("<I", len(b)) + b

    def field_biasa(nama: str, nilai: str) -> bytes:
        """Field string biasa — ada 4 byte \x00\x01\x00\x00\x00 sebelum panjang."""
        b = nilai.encode()
        return nama.encode() + b"\x00\x01\x00\x00\x00" + struct.pack("<I", len(b)) + b

    isi = (
        b"\x01\x00\x00\x00" + field_biasa("FCMToken", fcm)
        + field_token(TOKEN) + field_biasa("growid", "231519886")
    )
    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
        f.write(isi)
        path = f.name

    hasil = token_dari_savedat(path)
    cek("token terbaca dari save.dat", hasil == TOKEN, f"dapat {len(hasil)} char")
    cek("TIDAK tertukar dengan FCMToken", "APA91b" not in hasil)

    # file tanpa field Token -> string kosong (tidak meledak)
    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
        f.write(b"\x01\x00\x00\x00" + field_biasa("FCMToken", fcm))
        path2 = f.name
    cek("file tanpa Token -> kosong (tidak error)", token_dari_savedat(path2) == "")


def uji_client_data() -> None:
    """clientData WAJIB untuk /player/growid/checktoken (terbukti di server)."""
    print(f"\n{BOLD}5. clientData wajib{RESET}")
    import base64 as _b64  # noqa: PLC0415

    from lucifer.account import client_data_minimal  # noqa: PLC0415

    cd = client_data_minimal()
    cek("menghasilkan teks base64", isinstance(cd, str) and len(cd) > 0)
    isi = _b64.b64decode(cd).decode("utf-8", "replace")
    cek("memuat protocol", "protocol|225" in isi)
    cek("memuat klv", "klv|" in isi)
    cek("memuat rid", "rid|" in isi)
    cek("memuat mac", "mac|" in isi)
    # rid acak tiap panggilan (seperti klien asli)
    cek("rid acak tiap panggilan", client_data_minimal() != cd)


def main() -> int:
    print(f"{BOLD}Uji modul ltoken — Lucifer Linux{RESET}")
    uji_regex()
    uji_ltoken()
    uji_tidak_menggantung()
    uji_savedat()
    uji_client_data()

    print("\n" + "=" * 62)
    warna = GREEN if gagal == 0 else RED
    print(f"{warna}{BOLD} HASIL: {lulus} lulus, {gagal} gagal{RESET}")
    print("=" * 62)
    return 1 if gagal else 0


if __name__ == "__main__":
    raise SystemExit(main())
