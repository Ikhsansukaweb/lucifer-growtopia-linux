"""Uji fitur otomasi (lucifer/features.py) — tanpa jaringan.

Jalankan: .venv/bin/python tests/test_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lucifer.bot import Account, Bot  # noqa: E402
from lucifer.features import SEMUA_ALIAS, TILE_MENU, BG_TANAH, FeatureError  # noqa: E402
from lucifer.world import Tile, World  # noqa: E402

LULUS = 0
GAGAL = 0


def cek(nama: str, kondisi: bool, info: str = "") -> None:
    global LULUS, GAGAL
    if kondisi:
        LULUS += 1
        print(f"  \u2713 {nama}" + (f"  {info}" if info else ""))
    else:
        GAGAL += 1
        print(f"  \u2717 {nama}" + (f"  {info}" if info else ""))


def bot_kosong() -> Bot:
    return Bot(Account(), items_db=None, label="uji")


def dunia_contoh() -> World:
    """5x5: bg tanah semua, satu bibit siap panen, satu bibit belum siap."""
    w = World()
    w.name = "UJI"
    w.width = w.height = 5
    for y in range(5):
        for x in range(5):
            w.tiles.append(Tile(x=x, y=y, fg=0, bg=BG_TANAH))
    siap = w.tile(1, 1)
    siap.fg, siap.extra_type, siap.ready = 100, 4, True
    belum = w.tile(2, 2)
    belum.fg, belum.extra_type, belum.ready = 101, 4, False
    return w


print("== alias menu deltaX ==")
cek("alias terisi", len(SEMUA_ALIAS) > 20, f"{len(SEMUA_ALIAS)} alias")
cek("semua alias punya keterangan", all(TILE_MENU[k] for k in SEMUA_ALIAS))

print("== AutoFarm pemilihan tile ==")
b = bot_kosong()
b.world = dunia_contoh()
af = b.fitur.autofarm
cek("siap_panen hanya yang ready", [ (t.x, t.y) for t in af.siap_panen() ] == [(1, 1)])
cek("kosong = bg != 0 dan fg == 0", len(af.kosong()) == 23, f"{len(af.kosong())} tile")
af.set_tiles([(0, 0), (4, 4)])
cek("set_tiles manual dibatasi", len(af.tiles_sasaran()) == 2)
af.set_tiles([{"x": 1, "y": 1}])
cek("set_tiles terima dict", af.target_tiles == [(1, 1)])
cek("sasaran manual -> siap_panen 1", len(af.siap_panen()) == 1)

print("== AutoFarm tolak start tanpa syarat ==")
b2 = bot_kosong()
for nama, fn in (("offline", lambda: b2.fitur.autofarm.start()),
                 ("tanpa world", lambda: (setattr(b2, "status", "online"),
                                          b2.fitur.autofarm.start())[1])):
    try:
        fn()
        cek(nama + " ditolak", False)
    except FeatureError:
        cek(nama + " ditolak", True)

print("== PathFinder BFS ==")
b3 = bot_kosong()
b3.world = dunia_contoh()
b3.status = "online"
from lucifer.bot import Player  # noqa: E402

b3.local = Player(netid=1, name="aku", posx=8.0, posy=8.0)
pf = b3.fitur.path
jalur = pf.cari(3, 0)
cek("jalur ketemu", len(jalur) == 3, f"{jalur}")
cek("titik akhir benar", jalur[-1] == (3, 0))
cek("tujuan sama -> kosong", pf.cari(0, 0) == [])
pf.block_jump = False
cek("tanpa block_jump tetap ketemu", pf.cari(3, 0)[-1] == (3, 0))
b3.world.tile(2, 0).fg = 500
pf.block_jump = True
jalur2 = pf.cari(2, 0)
cek("tile terpasang jadi tujuan tetap boleh", jalur2[-1] == (2, 0))
cek("tujuan di luar dunia -> kosong", pf.cari(99, 99) == [])

print("== Spammer ==")
sp = b3.fitur.spammer
sp.tambah("halo")
sp.tambah("halo")
sp.tambah("hai")
cek("duplikat dibuang", sp.daftar == ["halo", "hai"])
sp._idx = 0
urut = [sp._berikut(), sp._berikut(), sp._berikut()]
cek("urutan bergilir", urut == ["halo", "hai", "halo"], f"{urut}")
sp.shuffle = True
cek("shuffle tetap dari daftar", sp._berikut() in sp.daftar)
sp.bersihkan()
cek("bersihkan kosong", sp.daftar == [])

print("== Growscan ==")
gs = b3.fitur.growscan.scan()
cek("growscan baca nama world", gs["world"] == "UJI")
cek("growscan hitung tanaman (2 bibit)",
    gs["tanaman"] == [{"id": 100, "nama": "#100", "jumlah": 1},
                      {"id": 101, "nama": "#101", "jumlah": 1}],
    str(gs["tanaman"]))
cek("growscan hitung blok terpasang (dimutasi uji PathFinder)",
    gs["blok"] == [{"id": 500, "nama": "#500", "jumlah": 1}], str(gs["blok"]))
cek("growscan sertakan ukuran world", gs["ukuran"] == "5x5")

print("== Replay rekam & putar (tanpa jaringan) ==")
rp = b3.fitur.replay
aksi_terkirim: list[tuple] = []
b3.send_text = lambda mtype, body: aksi_terkirim.append((mtype, body)) or True  # type: ignore[method-assign]
rp.mulai_rekam()
b3.hit(1, 1)
b3.place(2, 2, 100)
rp.stop_rekam()
cek("2 aksi terekam", len(rp.aksi) == 2, str([a["aksi"] for a in rp.aksi]))
cek("urutan aksi benar", [a["aksi"] for a in rp.aksi] == ["hit", "place"])
cek("args terekam", rp.aksi[1]["args"] == [2, 2, 100])
cek("hook dilepas setelah stop", getattr(b3.hit, "__name__", "") != "luar")

import tempfile as _tmp  # noqa: E402

with _tmp.TemporaryDirectory() as d:
    rp.folder = Path(d)
    rp.simpan("uji")
    cek("simpan berkas replay", (Path(d) / "uji.json").exists())
    rp.bersihkan()
    cek("muat berkas replay", rp.muat("uji") == 2)
    cek("daftar berkas replay", rp.daftar_berkas() == ["uji.json"])

try:
    rp.bersihkan()
    rp.putar()
    cek("putar tanpa aksi ditolak", False)
except FeatureError:
    cek("putar tanpa aksi ditolak", True)

print("== Perintah chat (cmd_* deltaX) ==")
cm = b3.fitur.commands


def balasan() -> str:
    return b3.console.contents[-1] if b3.console.contents else ""


cek("non-slash diabaikan", cm.handle("halo") is False)
cek("slash tak dikenal diabaikan", cm.handle("/tidakada") is False)
cek("/help ditangani", cm.handle("/help") is True)
cek("help menyebut /warp", "/warp" in balasan())
cek("/alias dibuat", cm.handle("/alias wp2 warp START") is True)
cek("alias tersimpan", cm.alias.get("wp2") == "warp START")
cek("/aliases tampil", cm.handle("/aliases") is True and "wp2" in balasan())
cek("/unalias", cm.handle("/unalias wp2") is True and "wp2" not in cm.alias)
cek("/disable mematikan", cm.handle("/disable gscan") is True and not cm.aktif["gscan"])
cek("perintah mati -> ditangani tapi tak jalan", cm.handle("/gscan") is True)
cek("/enable menyalakan", cm.handle("/enable gscan") is True and cm.aktif["gscan"])
cek("/warp kirim paket", cm.handle("/warp FARM") is True)
cek("riwayat world terisi", cm.riwayat_world == ["UJI"], str(cm.riwayat_world))
cek("/finditem id ketemu", cm.handle("/finditem 100") is True and "1 tile" in balasan())
cek("/finditem tak ada", cm.handle("/finditem 9999") is True and "tidak" in balasan().lower())
cek("/back ke dunia sebelumnya", cm.handle("/back") is True)

print("== say() merutekan slash ke perintah ==")
b3.console.contents.clear()
aksi_terkirim.clear()
b3.say("/help")
cek("say('/help') tidak kirim paket", not aksi_terkirim, f"{len(aksi_terkirim)} paket")
b3.say("halo dunia")
cek("say biasa tetap kirim paket", len(aksi_terkirim) == 1)

print("== Lua API ==")
api = b.fitur.lua_api()
cek("api punya autofarm_start", "autofarm_start" in api)
cek("api punya findpath_to", "findpath_to" in api)
cek("api punya features_menu", api["features_menu"]()["autofarm_start"])

print("== stop_semua aman saat idle ==")
b.fitur.stop_semua()
cek("stop_semua tidak melempar", True)

print("\n" + "=" * 62)
print(f" lulus: {LULUS}   gagal: {GAGAL}")
print("=" * 62)
sys.exit(1 if GAGAL else 0)
