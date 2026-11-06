#!/usr/bin/env python3
"""Hasilkan native/tests/world_golden.bin dari dump SendMapData asli.

Sumber: /tmp/opencode/dump_map.bin (ditangkap LUCIFER_DUMP=1 saat bot masuk
world ISANLUCUUU). Yang disimpan: ringkasan hasil parse Python supaya parser
C++ bisa dibandingkan tanpa perlu items.dat.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lucifer.items import ItemDatabase  # noqa: E402
from lucifer.world import parse_world  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DUMP = Path("/tmp/opencode/dump_map.bin")


def main() -> int:
    if not DUMP.exists():
        print(f"dump tidak ada: {DUMP}")
        print("jalankan backend dengan LUCIFER_DUMP=1 lalu connect sekali.")
        return 1
    data = DUMP.read_bytes()
    db = None
    items = REPO / "data" / "items.dat"
    if items.exists():
        db = ItemDatabase.from_file(items)
    w = parse_world(data, db)

    # Format: [u32 len][payload mentah] [u32 n_tile]
    #         n_tile x { i32 x, i32 y, u16 fg, u16 bg, u16 flags, u8 extra }
    #         [u32 n_dropped] n_dropped x { u16 id, f32 x, f32 y, u8 count, u32 uid }
    out = bytearray()
    out += struct.pack("<I", len(data))
    out += data
    out += struct.pack("<I", len(w.tiles))
    for t in w.tiles:
        out += struct.pack("<iihHHB", t.x, t.y, t.fg, t.bg, t.flags, t.extra_type)
    out += struct.pack("<I", len(w.dropped))
    for d in w.dropped:
        out += struct.pack("<HffBI", d.item_id, d.x, d.y, d.count, d.uid)

    keluar = HERE / "world_golden.bin"
    keluar.write_bytes(bytes(out))
    print(f"world: {w.name} {w.width}x{w.height} tiles={len(w.tiles)} "
          f"dropped={len(w.dropped)} last_uid={w.last_uid} err={w.error!r}")
    print(f"-> {keluar} ({len(out)} byte)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
