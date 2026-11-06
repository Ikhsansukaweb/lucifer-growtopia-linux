#!/usr/bin/env python3
"""Hasilkan native/tests/items_golden.bin dari data/items.dat.

Menyimpan field yang dipakai bot (block_health, grow_time, rarity, nama) untuk
setiap item, supaya parser C++ bisa dibandingkan byte-per-byte dengan Python.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from lucifer.items import ItemDatabase  # noqa: E402


def main() -> int:
    path = REPO / "data" / "items.dat"
    if not path.exists():
        print(f"tidak ada: {path}")
        return 1
    db = ItemDatabase.from_file(path)

    out = bytearray()
    out += struct.pack("<I", len(db.items))
    for item_id in sorted(db.items):
        it = db.items[item_id]
        nama = it.name.encode("utf-8")
        out += struct.pack(
            "<IBBBBHI H",
            it.id, it.action_type, it.material, it.block_health, 0,
            it.rarity, it.grow_time, len(nama),
        )
        out += nama

    keluar = HERE / "items_golden.bin"
    keluar.write_bytes(bytes(out))
    print(f"items: {len(db.items)} v{db.version} -> {keluar} ({len(out)} byte)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
