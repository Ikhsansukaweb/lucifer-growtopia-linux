#!/usr/bin/env python3
"""Hasilkan native/tests/golden.bin dari implementasi Python.

Golden ini adalah **kebenaran acuan**: kalau port C++ menghasilkan byte
berbeda, port-nya salah. Jalankan ulang hanya kalau implementasi Python memang
diubah dengan sengaja.

Format berkas: [u32 panjang][bytes] berulang, urutan kasus sama dengan
switch di native/tests/test_protocol.cpp.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lucifer.protocol import (  # noqa: E402
    NetMessage, Tank, Variant, VariantList, build_action, build_packet,
)

HERE = Path(__file__).resolve().parent


def kasus() -> list[bytes]:
    out: list[bytes] = []

    # 1. Tank kosong
    out.append(Tank().to_bytes())

    # 2. Tank penuh + extended
    t = Tank(
        type=3, object_type=1, jump_count=2, animation_type=3,
        net_id=12345, target_net_id=-7, flags=0x30,
        float_variable=1.25, value=18,
        vector_x=320.0, vector_y=352.0,
        vector_x2=-1.5, vector_y2=2.5,
        particle_rotation=90.0, int_x=-3, int_y=44,
    )
    out.append(t.to_bytes(bytes([9, 8, 7])))

    # 3. VariantList campur
    vl = VariantList()
    vl.append(Variant.from_string("OnDialogRequest"))
    vl.append(Variant.from_string("embed_data|netID|1\nadd_popup_name|WrenchMenu|\n"))
    vl.append(Variant.from_int(-42))
    vl.append(Variant.from_uint(4294967295))
    vl.append(Variant.from_float(3.5))
    vl.append(Variant.from_vec2(1.0, 2.0))
    vl.append(Variant.from_vec3(3.0, 4.0, 5.0))
    out.append(vl.serialize())

    # 4. VariantList kosong
    out.append(VariantList().serialize())

    # 5. action|storenavigate (dua field, urutan tabel diuji)
    out.append(build_action("storenavigate", item="locks", selection="upgrade_backpack"))

    # 6. bingkai + tank
    t2 = Tank(type=11, value=777, vector_x=384.0, vector_y=352.0, int_x=1)
    out.append(build_packet(NetMessage.GamePacket, t2.to_bytes()))
    return out


def main() -> int:
    data = b"".join(struct.pack("<I", len(b)) + b for b in kasus())
    keluar = HERE / "golden.bin"
    keluar.write_bytes(data)
    print(f"golden.bin: {len(kasus())} kasus, {len(data)} byte -> {keluar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
