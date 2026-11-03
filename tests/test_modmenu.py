#!/usr/bin/env python3
"""tests/test_modmenu.py — uji skema mod menu + setter parameter fitur.

Skema (`lucifer.features.SKEMA_FITUR`) adalah satu sumber untuk GUI: kalau
kunci/tipe salah, form di GUI kosong atau mengirim nilai yang salah. Uji ini
menjaga kontrak itu tanpa jaringan.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lucifer.bot import Account, Bot  # noqa: E402
from lucifer.features import skema_fitur  # noqa: E402
from lucifer.web import Handler  # noqa: E402

LULUS = 0
GAGAL = 0
TIPE_SAH = {"toggle", "angka", "pecahan", "teks", "teks_panjang", "pilihan",
            "item", "tile", "tombol"}


def cek(nama: str, kondisi: bool, info: str = "") -> None:
    global LULUS, GAGAL
    if kondisi:
        LULUS += 1
        print(f"  \u2713 {nama}" + (f"  {info}" if info else ""))
    else:
        GAGAL += 1
        print(f"  \u2717 {nama}" + (f"  {info}" if info else ""))


def bot_uji() -> Bot:
    return Bot(Account(), items_db=None, label="uji")


print("== skema ==")
skema = skema_fitur()
cek("ada 6 fitur", len(skema) == 6, str([s["nama"] for s in skema]))
cek("tiap fitur punya fitur+kontrol",
    all(s.get("fitur") and s.get("kontrol") for s in skema))

b = bot_uji()
for s in skema:
    obj = getattr(b.fitur, s["fitur"], None)
    cek(f"{s['nama']}: objek ada di FiturBot", obj is not None)
    for k in s["kontrol"]:
        cek(f"{s['nama']}: tipe {k['tipe']} sah", k["tipe"] in TIPE_SAH, k["kunci"])
        if k["tipe"] == "tombol":
            # tombol = aksi di server, bukan atribut objek
            cek(f"{s['nama']}: tombol {k['aksi']} punya aksi",
                bool(k.get("aksi")), k["kunci"])
            continue
        cek(f"{s['nama']}: kunci {k['kunci']} ada di objek",
            hasattr(obj, k["kunci"]) or k["kunci"] in ("teks", "target_tiles"),
            k["kunci"])

print("== setter parameter ==")
srv = Handler.__new__(Handler)  # tanpa socket; hanya butuh _set_parameter
ad = b.fitur.autodrop
diterapkan = srv._set_parameter(ad, {"minimum": "321", "mode": "trash",
                                     "jeda": 1.5, "world": "FARM",
                                     "x": 4, "y": 5})
cek("minimum jadi int", ad.minimum == 321 and isinstance(ad.minimum, int))
cek("mode jadi str", ad.mode == "trash")
cek("jeda jadi float", ad.jeda == 1.5 and isinstance(ad.jeda, float))
cek("dunia/posisi tersimpan", (ad.world, ad.x, ad.y) == ("FARM", 4, 5))
cek("hasil dikembalikan", "minimum" in diterapkan)

ac = b.fitur.autocollect
srv._set_parameter(ac, {"item_id": "964", "radius": 7, "delay": "200", "jeda": 2})
cek("collect item_id int", ac.item_id == 964)
cek("collect radius/jeda", ac.radius == 7 and ac.jeda == 2.0)

srv._set_parameter(ac, {"tiles": [{"x": 5, "y": 6}, {"x": 7, "y": 8}], "mode": "Tile"})
cek("collect tiles jadi tuple", ac.tiles == [(5, 6), (7, 8)], str(ac.tiles))
cek("collect mode tersimpan", ac.mode == "Tile")
srv._set_parameter(ac, {"tiles": [[1, 2]]})
cek("collect tiles terima list", ac.tiles == [(1, 2)], str(ac.tiles))

cek("skema autofarm tile count 5",
    [k for k in skema_fitur() if k["fitur"] == "autofarm"][0]
    and [k.get("count") for k in [k for k in skema_fitur() if k["fitur"] == "autofarm"][0]["kontrol"]
         if k["tipe"] == "tile"] == [5])
cek("skema autocollect tile count 11",
    [k.get("count") for k in [k for k in skema_fitur() if k["fitur"] == "autocollect"][0]["kontrol"]
     if k["tipe"] == "tile"] == [11])

sp = b.fitur.spammer
srv._set_parameter(sp, {"delay": "900", "shuffle": True, "teks": "a\nb\n"})
cek("spammer daftar dari teks", sp.daftar == ["a", "b"], str(sp.daftar))
cek("spammer shuffle/delay", sp.shuffle is True and sp.delay == 900)

pf = b.fitur.path
srv._set_parameter(pf, {"block_jump": False, "teleport_path": True, "jeda": 0.2})
cek("pathfinder param", (pf.block_jump, pf.teleport_path, pf.jeda) == (False, True, 0.2))

rp = b.fitur.replay
srv._set_parameter(rp, {"loop": True, "custom_delay": 500})
cek("replay param", rp.loop is True and rp.custom_delay == 500)

print("=" * 62)
print(f" lulus: {LULUS}   gagal: {GAGAL}")
print("=" * 62)
sys.exit(1 if GAGAL else 0)
