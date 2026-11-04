"""Uji regresi parser tile: panjang extra Portrait (48) dan Mannequin (14).

Fixture `dump_map.bin` (payload SendMapData BESTI) tidak disimpan di repo,
jadi uji ini membangun payload sintetis dengan susunan byte yang sama seperti
yang terbukti benar dari dump asli:

  Portrait  @31390: flags=0x19 et=48 label(len 10) + 26 byte
  Mannequin @35205: flags=0x11 et=14 label(len 15) + u8 + u32 + 9*u16

Kalau salah satu panjangnya digeser, tile sesudahnya desync dan jumlah tile
tak lagi cocok.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lucifer.world import parse_world  # noqa: E402

LULUS = GAGAL = 0
GAGAL_NAMA: list[str] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> bool:
    global LULUS, GAGAL
    if kondisi:
        LULUS += 1
        print(f"  \u2713 {nama}" + (f"  {detail}" if detail else ""))
    else:
        GAGAL += 1
        GAGAL_NAMA.append(nama)
        print(f"  \u2717 {nama}  {detail}")
    return kondisi


def kosong() -> bytes:
    return struct.pack("<HHHH", 0, 0, 0, 0)


def portrait(label: str) -> bytes:
    b = struct.pack("<HHHH", 15950, 0, 0, 0x0019) + b"\x30"
    b += struct.pack("<H", len(label)) + label.encode()
    return b + b"\x00" * 26


def mannequin(label: str) -> bytes:
    b = struct.pack("<HHHH", 9202, 0, 0, 0x0011) + b"\x0e"
    b += struct.pack("<H", len(label)) + label.encode()
    b += b"\x00" + struct.pack("<I", 0)
    return b + b"\x00" * (9 * 2)


def ubin(nama: str, w: int, h: int, isi: list[bytes]) -> bytes:
    b = struct.pack("<H", 27)
    b += struct.pack("<I", 0)
    b += struct.pack("<H", len(nama)) + nama.encode()
    b += struct.pack("<II", w, h)
    b += struct.pack("<I", len(isi))
    b += b"\x00" * 5
    b += b"".join(isi)
    b += b"\x00" * 12
    b += struct.pack("<II", 0, 0)      # dropped: 0 item
    b += struct.pack("<HHH", 0, 0, 22)  # weather
    return b


def main() -> int:
    # 6x2 = 12 tile: portrait & mannequin di tengah, sisanya kosong.
    isi = [kosong() for _ in range(12)]
    isi[3] = portrait("`cLiaamS``")
    isi[8] = mannequin("`0Hai Yo.orin! ")
    data = ubin("UJI", 6, 2, isi)

    w = parse_world(data)
    cek("parse tanpa error", not w.error, w.error)
    cek("jumlah tile utuh", len(w.tiles) == 12, f"{len(w.tiles)} tile")
    cek("tile sesudah portrait tetap kosong", w.tiles[4].fg == 0, str(w.tiles[4].fg))
    cek("portrait: fg", w.tiles[3].fg == 15950, str(w.tiles[3].fg))
    cek("portrait: label terbaca", w.tiles[3].label == "`cLiaamS``", repr(w.tiles[3].label))
    cek("mannequin: fg", w.tiles[8].fg == 9202, str(w.tiles[8].fg))
    cek("mannequin: label terbaca", w.tiles[8].label == "`0Hai Yo.orin! ", repr(w.tiles[8].label))
    cek("tile terakhir dihitung", w.tiles[11].x == 5 and w.tiles[11].y == 1,
        f"({w.tiles[11].x},{w.tiles[11].y})")

    print()
    print("=" * 62)
    print(f" lulus: {LULUS}   gagal: {GAGAL}")
    if GAGAL:
        print(" yang gagal:")
        for n in GAGAL_NAMA:
            print("  -", n)
        return 1
    print(" PARSER TILE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
