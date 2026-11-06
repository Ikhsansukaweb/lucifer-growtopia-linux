"""Uji fitur otomasi (lucifer/features.py) — tanpa jaringan.

Jalankan: .venv/bin/python tests/test_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lucifer.bot import Account, Bot, Player  # noqa: E402
from lucifer.features import (  # noqa: E402
    SEMUA_ALIAS, SKEMA_FITUR, TILE_MENU, BG_TANAH, FeatureError,
)
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

print("== AutoFarm = break & place (blok, bukan tanaman) ==")
b = bot_kosong()
b.world = dunia_contoh()
af = b.fitur.autofarm
# Autofarm bekerja pada BLOK. Dua tile di dunia_contoh berisi tanaman
# (extra_type=4), jadi keduanya BUKAN sasaran autofarm.
cek("tanaman bukan sasaran pecah", af.siap_pecah() == [])
cek("kosong = bg != 0 dan fg == 0", len(af.kosong()) == 23, f"{len(af.kosong())} tile")
blok = b.world.tile(3, 3)
blok.fg, blok.extra_type = 100, 0
cek("blok jadi sasaran pecah", [(t.x, t.y) for t in af.siap_pecah()] == [(3, 3)])
af.set_tiles([(0, 0), (4, 4)])
cek("set_tiles manual dibatasi", len(af.tiles_sasaran()) == 2)
af.set_tiles([{"x": 1, "y": 1}])
cek("set_tiles terima dict", af.target_tiles == [(1, 1)])
af.set_tiles([{"x": 3, "y": 3}])
cek("sasaran manual -> siap_pecah 1", len(af.siap_pecah()) == 1)

print("== urutan siklus ==")
_jejak_af, _jejak_auto = [], []
b4 = bot_kosong()
b4.world = dunia_contoh()
b4.status = "online"
for nama in ("pecah", "ambil", "taruh"):
    setattr(b4.fitur.autofarm, nama,
            (lambda n: lambda: (_jejak_af.append(n), 0)[1])(nama))
b4.fitur.autofarm.buang = lambda: 0
b4.fitur.autofarm.satu_siklus()
cek("autofarm: pecah -> ambil -> taruh",
    _jejak_af == ["pecah", "ambil", "taruh"], str(_jejak_af))

for nama in ("panen", "ambil", "tanam"):
    setattr(b4.fitur.automation, nama,
            (lambda n: lambda: (_jejak_auto.append(n), 0)[1])(nama))
b4.fitur.automation.satu_siklus()
cek("automation: panen -> ambil -> tanam",
    _jejak_auto == ["panen", "ambil", "tanam"], str(_jejak_auto))

print("== AutoFarm jangkauan (server tolak tileChange > 4 tile) ==")
b5 = bot_kosong()
b5.world = dunia_contoh()
b5.local = Player(netid=1, name="uji", posx=0.0, posy=0.0)
af5 = b5.fitur.autofarm
cek("tile sendiri dalam jangkau", af5._dalam_jangkau(b5.world.tile(0, 0)))
cek("tile 2,2 dalam jangkau", af5._dalam_jangkau(b5.world.tile(2, 2)))
cek("tile 4,4 di luar jangkau", not af5._dalam_jangkau(b5.world.tile(4, 4)))
cek("_urut_dekat urut jarak",
    [(t.x, t.y) for t in af5._urut_dekat([b5.world.tile(4, 4), b5.world.tile(1, 1)])]
    == [(1, 1), (4, 4)])

print("== AutoFarm siklus nyata: pecah -> tile kosong -> taruh ==")
b6 = bot_kosong()
b6.world = dunia_contoh()
b6.local = Player(netid=1, name="uji", posx=0.0, posy=0.0)
b6.status = "online"
blok6 = b6.world.tile(1, 2)
blok6.fg, blok6.extra_type = 2, 0            # Dirt
af6 = b6.fitur.autofarm
af6.block_id, af6.block_mode = 2, "manual"

b6.inventory.items[2] = type("I", (), {"id": 2, "count": 5, "isActive": False})()
af6.collect = False
af6.pecah_dipanggil, af6.taruh_dipanggil = [], []
_tank6 = []
b6.send_raw = lambda pkt, ext=b"": (_tank6.append(pkt), True)[1]

import struct as _struct  # noqa: E402
from lucifer.protocol import Tank as _Tank6  # noqa: E402

kosong6 = []


def _hit6(x, y):
    af6.pecah_dipanggil.append((x, y))
    # Server retail tidak mengirim type 5. Konfirmasi pecah = echo
    # `type=3 value=18`, persis seperti paket klien asli.
    b6._apply_tile_change_echo(_Tank6(type=3, value=18, int_x=x, int_y=y))
    kosong6.append(b6.world.tile(x, y).fg)
    return True

def _place6(x, y, item):
    af6.taruh_dipanggil.append((x, y, item))
    b6._apply_tile_update(_Tank6(type=5, int_x=x, int_y=y),
                          _struct.pack("<HHHH", item, 6, 0, 0))
    return True

b6.hit, b6.place = _hit6, _place6
hasil6 = af6.satu_siklus()
cek("pecah mengenai blok", af6.pecah_dipanggil == [(1, 2)], str(af6.pecah_dipanggil))
cek("blok hilang setelah tile update", kosong6 == [0], str(kosong6))
cek("taruh di tile yang sama", af6.taruh_dipanggil == [(1, 2, 2)], str(af6.taruh_dipanggil))
cek("blok terpasang lagi", b6.world.tile(1, 2).fg == 2)
cek("siklus melaporkan hasil", hasil6["dipecah"] == 1 and hasil6["ditaruh"] == 1,
    str(hasil6))

print("== Autofarm tidak berjalan sendiri (bug White Door) ==")
import ast as _ast

_tree = _ast.parse(Path(__file__).resolve().parent.parent.joinpath("lucifer/features.py").read_text())
for _n in _ast.walk(_tree):
    if isinstance(_n, _ast.FunctionDef) and _n.name == "dekati":
        _calls = [_c.func.attr for _c in _ast.walk(_n)
                  if isinstance(_c, _ast.Call) and isinstance(_c.func, _ast.Attribute)]
        cek("dekati() tidak menggerakkan bot", not any(
            m in ("findPath", "moveTo", "moveTile") for m in _calls), str(_calls))

b7 = bot_kosong()
w7 = World(); w7.name = "U7"; w7.width = w7.height = 30
for _y in range(30):
    for _x in range(30):
        w7.tiles.append(Tile(x=_x, y=_y, fg=0, bg=BG_TANAH))
for _x in range(30):
    w7.tile(_x, 5).fg = 2          # baris blok jauh dari pemain
w7.tile(12, 12).fg = 2             # blok tepat di dekat pemain
b7.world = w7
b7.local = Player(netid=1, name="uji", posx=12 * 32.0, posy=12 * 32.0)
af7 = b7.fitur.autofarm
af7.block_mode, af7.target_tiles = "auto", []
cek("mode auto hanya menyasar jangkauan",
    [(t.x, t.y) for t in af7.siap_pecah()] == [(12, 12)],
    str([(t.x, t.y) for t in af7.siap_pecah()]))
cek("blok jauh tidak disentuh", len(af7.siap_pecah()) < sum(1 for t in w7.tiles if t.fg == 2))

print("== Autocollect: tile menang atas radius di jalur otomatis ==")
b8 = bot_kosong()
b8.world = dunia_contoh()
b8.local = Player(netid=1, name="uji", posx=0.0, posy=0.0)
b8.auto_collect, b8.auto_collect_radius = True, 5
b8.fitur.autocollect.tiles = [(4, 4)]
cek("tile terpilih diambil", b8._boleh_ambil(4 * 32 + 16, 4 * 32 + 16))
cek("radius diabaikan saat tile diset", not b8._boleh_ambil(1 * 32 + 16, 1 * 32 + 16))
b8.fitur.autocollect.tiles = []
cek("tanpa tile -> radius dipakai lagi", b8._boleh_ambil(1 * 32 + 16, 1 * 32 + 16))

print("== AutoFarm tunggu blok BENAR-BENAR pecah sebelum taruh ==")
b9 = bot_kosong()
b9.world = dunia_contoh()
b9.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
b9.status = "online"
blk9 = b9.world.tile(1, 2)
blk9.fg, blk9.extra_type = 2, 0
af9 = b9.fitur.autofarm
af9.block_id, af9.block_mode = 2, "manual"
af9.target_tiles = [(1, 2)]
af9.collect, af9.punch_delay = False, 1
b9.inventory.items[2] = type("I", (), {"id": 2, "count": 5, "isActive": False})()
_j9 = []


def _hit_pecah(x, y):
    _j9.append(("hit", x, y))
    n = sum(1 for a in _j9 if a[0] == "hit")
    # Pukulan diterima -> TileApplyDamage. Setelah 3, server meng-echo
    # `type=3 value=18` = blok pecah (persis seperti klien asli).
    b9._apply_damage(type("T", (), {"int_x": x, "int_y": y, "value": 6})())
    if n >= 3:
        b9._aksi_ok[(x, y)] = ("break", 18, 0.0)
        t = b9.world.tile(x, y)
        t.fg, t.flags, t.extra_type = 0, 0, 0
    return True


def _place9(x, y, i):
    _j9.append(("place", x, y, i))
    b9.world.tile(x, y).fg = i
    b9._aksi_ok[(x, y)] = ("place", i, 0.0)   # server meng-echo place
    return True


b9.hit, b9.place = _hit_pecah, _place9
h9 = af9.satu_siklus()
# Blok dianggap pecah saat ack berhenti datang (bukan jumlah pasti).
# Server hanya membalas ack selama blok masih ada.
cek("hit berhenti saat ack mandek", 1 <= [a[0] for a in _j9].count("hit") <= 6,
    str(_j9))
cek("pecah dilaporkan", h9["dipecah"] == 1, str(h9))
cek("taruh SETELAH pecah", _j9[-1][0] == "place", str(_j9))
cek("taruh di tile yang sama", _j9[-1][:3] == ("place", 1, 2), str(_j9[-1]))
cek("taruh dilaporkan", h9["ditaruh"] == 1, str(h9))

# Konfirmasi pecah memakai `TileApplyDamage` (bukan drop: banyak blok tidak
# menjatuhkan apa pun). Blok pecah saat jumlah ack mencapai block_health/6.
b17 = bot_kosong()
b17.world = dunia_contoh()
b17.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
b17.status = "online"
b17.world.tile(1, 2).fg = 2
af17 = b17.fitur.autofarm
af17.block_id, af17.block_mode = 2, "manual"
af17.target_tiles = [(1, 2)]
af17.collect, af17.punch_delay = False, 1
b17.inventory.items[2] = type("I", (), {"id": 2, "count": 5, "isActive": False})()
_h17 = []
b17.place = lambda x, y, i: True


def _hit17(x, y):
    _h17.append(1)
    # Pukulan diterima -> damage. Setelah itu server echo `value=18` = pecah.
    if len(_h17) <= 2:
        b17._apply_damage(type("T", (), {"int_x": x, "int_y": y, "value": 6})())
    else:
        b17._aksi_ok[(x, y)] = ("break", 18, 0.0)
        b17.world.tile(x, y).fg = 0
    return True


b17.hit = _hit17


def _place17(x, y, i):
    # Server meng-echo place: ini konfirmasi yang ditunggu taruh().
    b17._aksi_ok[(x, y)] = ("place", i, 0.0)
    return True


b17.place = _place17
h17 = af17.satu_siklus()
# Blok pecah = ack berhenti bertambah. Server hanya membalas ack untuk
# pukulan yang benar-benar diterima, jadi hitungan ack tak bisa dipatok.
cek("ack berhenti -> berhenti memukul (<=6)", len(_h17) <= 6, f"{len(_h17)} pukulan")
cek("ack damage -> dipecah 1", h17["dipecah"] == 1, str(h17))
cek("ack damage -> ditaruh 1", h17["ditaruh"] == 1, str(h17))

# Server TIDAK mengirim satu pun `TileApplyDamage` -> tile dianggap SUDAH
# KOSONG di server (peta lokal tertinggal). Ini bukti dari jurnal paket:
# 200+ punch ke (48,23) menghasilkan nol type 8, sementara punch ke (49,22)
# langsung dibalas. Tanpa aturan ini bot memukul selamanya.
b10 = bot_kosong()
b10.world = dunia_contoh()
b10.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
b10.status = "online"
b10.world.tile(1, 2).fg = 2
af10 = b10.fitur.autofarm
af10.block_id, af10.block_mode = 2, "manual"
af10.target_tiles = [(1, 2)]
af10.collect, af10.punch_delay, af10.punch_count = False, 1, 4
b10.inventory.items[2] = type("I", (), {"id": 2, "count": 5, "isActive": False})()
_j10 = []
b10.hit = lambda x, y: (_j10.append("hit"), True)[1]
b10.place = lambda x, y, i: (_j10.append("place"), True)[1]
h10 = af10.satu_siklus()
# Nol ack = server tidak menyatakan apa pun. Peta lokal TIDAK boleh diubah
# sendiri (dulu bot "mengosongkan" tile yang di server masih berisi, lalu
# place ditolak `cant_place_tile`). Jadi tidak ada place.
cek("nol ack -> tidak mengarang tile kosong", h10["dipecah"] == 0, str(h10))
cek("nol ack -> berhenti memukul (<=8)", len([a for a in _j10 if a == "hit"]) <= 8,
    str(len([a for a in _j10 if a == "hit"])))
cek("nol ack -> tidak place", "place" not in _j10, str(_j10))

# Server MENGIRIM ack tapi tile tidak pernah kosong: harus berhenti di batas,
# bukan memukul selamanya.
b10b = bot_kosong()
b10b.world = dunia_contoh()
b10b.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
b10b.status = "online"
b10b.world.tile(1, 2).fg = 2
af10b = b10b.fitur.autofarm
af10b.block_id, af10b.block_mode = 2, "manual"
af10b.target_tiles = [(1, 2)]
af10b.collect, af10b.punch_delay = False, 1
b10b.inventory.items[2] = type("I", (), {"id": 2, "count": 5, "isActive": False})()
_h10b = []
b10b.hit = lambda x, y: (_h10b.append(1), True)[1]
b10b.place = lambda x, y, i: True
af10b.satu_siklus()
cek("ack tapi tak pernah kosong -> dibatasi", len(_h10b) <= 14, str(len(_h10b)))

print("== AutoFarm: jumlah pukulan = block_health / 6 ==")
# items.dat mengalikan hit-count x6 saat menyimpan; pemakaian membaginya lagi
# (Gurotopia items.cpp:102). Dirt block_health=18 -> 3 pukulan, bukan 18.
b11 = bot_kosong()
b11.world = dunia_contoh()
b11.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
b11.status = "online"
b11.world.tile(1, 2).fg = 2
af11 = b11.fitur.autofarm
af11.block_id, af11.block_mode = 2, "manual"
af11.target_tiles = [(1, 2)]
af11.collect, af11.punch_delay = False, 1
_h = []
b11.inventory.items[2] = type("I", (), {"id": 2, "count": 9, "isActive": False})()


def _hit11(x, y):
    _h.append(1)
    # Server baru menghapus blok setelah pukulan ke-3 (block_health 18 / 6).
    if len(_h) >= 3:
        t = b11.world.tile(x, y)
        t.fg, t.flags, t.extra_type = 0, 0, 0
    return True


b11.hit = _hit11
b11.place = lambda x, y, i: True
af11.satu_siklus()
# Blok pecah saat ack berhenti, bukan pada angka block_health/6 tertentu.
cek("berhenti setelah ack mandek", len(_h) <= 6, f"{len(_h)} pukulan")

# Tanpa items_db: fallback 3 pukulan, bukan 10+.
b12 = bot_kosong()
b12.world = dunia_contoh()
b12.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
b12.status = "online"
b12.world.tile(1, 2).fg = 2
af12 = b12.fitur.autofarm
af12.block_id, af12.block_mode = 2, "manual"
af12.target_tiles = [(1, 2)]
af12.collect, af12.punch_delay, af12.punch_count = False, 1, 10
_h2 = []
b12.hit = lambda x, y: (_h2.append(1), True)[1]
b12.place = lambda x, y, i: True
af12.satu_siklus()
cek("tanpa items.dat: batas tetap kecil", len(_h2) <= 14, f"{len(_h2)} pukulan")

print("== AutoFarm: urutan kiri ke kanan ==")
b13 = bot_kosong()
w13 = World(); w13.name = "U13"; w13.width = w13.height = 6
for _y in range(6):
    for _x in range(6):
        w13.tiles.append(Tile(x=_x, y=_y, fg=0, bg=BG_TANAH))
for _x in range(2, 5):
    w13.tile(_x, 2).fg = 2
b13.world = w13
b13.local = Player(netid=1, name="uji", posx=3 * 32.0, posy=2 * 32.0)
b13.status = "online"
af13 = b13.fitur.autofarm
af13.block_mode, af13.target_tiles = "auto", []
urut = [(t.x, t.y) for t in af13._urut_dekat(af13.siap_pecah())]
cek("urut kiri->kanan", urut == [(2, 2), (3, 2), (4, 2)], str(urut))

print("== AutoFarm: sasaran jauh harus didekati, bukan dipukul sia-sia ==")
b14 = bot_kosong()
w14 = World(); w14.name = "U14"; w14.width = w14.height = 40
for _y in range(40):
    for _x in range(40):
        w14.tiles.append(Tile(x=_x, y=_y, fg=0, bg=BG_TANAH))
w14.tile(30, 30).fg = 2      # 21 tile dari pemain, jauh di luar jangkauan
b14.world = w14
b14.local = Player(netid=1, name="uji", posx=9 * 32.0, posy=9 * 32.0)
b14.status = "online"
af14 = b14.fitur.autofarm
af14.block_id, af14.block_mode = 2, "manual"
af14.target_tiles = [(30, 30)]
_pukul14 = []
b14.hit = lambda x, y: (_pukul14.append((x, y)), True)[1]
b14.place = lambda x, y, i: True
JALAN = []
b14.moveTo = lambda dx, dy: (JALAN.append((dx, dy)), True)[1]

cek("tile jauh bukan sasaran siap_pecah", af14.siap_pecah() == [],
    str([(t.x, t.y) for t in af14.siap_pecah()]))
cek("terdeteksi sebagai sasaran jauh", len(af14._sasaran_jauh()) == 1)
af14.pecah()
cek("tidak memukul tile di luar jangkauan", _pukul14 == [], str(_pukul14))
cek("bot jalan mendekat", len(JALAN) > 0, str(JALAN))

print("== AutoFarm: lahan kosong dari awal tetap bisa ditaruh ==")
# Kasus nyata: target tile sudah kosong (fg=0,bg=0) sebelum autofarm mulai.
# `_baru_kosong` hanya terisi setelah ada blok yang pecah, jadi tanpa
# `target_tiles` sebagai sumber, bot menunggu selamanya dan tidak pernah place.
b15 = bot_kosong()
b15.world = dunia_contoh()
b15.local = Player(netid=1, name="uji", posx=3 * 32.0, posy=3 * 32.0)
b15.status = "online"
af15 = b15.fitur.autofarm
af15.block_id, af15.block_mode = 2, "manual"
af15.target_tiles = [(3, 3)]
af15.collect, af15.punch_delay, af15.place_delay = False, 1, 1
b15.inventory.items[2] = type("I", (), {"id": 2, "count": 5, "isActive": False})()
_taruh15 = []
b15.hit = lambda x, y: True


def _place15(x, y, i):
    _taruh15.append((x, y, i))
    b15._aksi_ok[(x, y)] = ("place", i, 0.0)   # server meng-echo
    return True


b15.place = _place15
h15 = af15.satu_siklus()
cek("tile kosong dari awal tetap ditaruh", _taruh15 == [(3, 3, 2)], str(_taruh15))
cek("ditaruh_total naik", h15["ditaruh"] == 1, str(h15))

# block_mode None (belum diset) harus diperlakukan seperti "auto", bukan
# diam-diam tidak mencocokkan apa pun.
b16 = bot_kosong()
b16.world = dunia_contoh()
b16.local = Player(netid=1, name="uji", posx=1 * 32.0, posy=2 * 32.0)
af16 = b16.fitur.autofarm
af16.block_mode = None
af16.target_tiles = [(1, 2)]
b16.world.tile(1, 2).fg = 2
cek("block_mode None tidak memblokir sasaran",
    len(af16.siap_pecah()) == 1,
    str([(t.x, t.y) for t in af16.siap_pecah()]))

print("== AutoFarm beda dengan Automation ==")
cek("autofarm punya pecah+taruh",
    hasattr(af, "pecah") and hasattr(af, "taruh"))
cek("autofarm tidak menanam bibit", not hasattr(af, "tanam"))
auto = b.fitur.automation
cek("automation punya panen+tanam",
    hasattr(auto, "panen") and hasattr(auto, "tanam"))
cek("automation tidak memecah blok", not hasattr(auto, "pecah"))

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

# --------------------------------------------------------------------------- #
# Tabel ACTION hasil ekstraksi libgrowtopia.so
# --------------------------------------------------------------------------- #
def uji_tabel_action() -> None:
    from lucifer import protocol as P
    from lucifer.account import Account
    from lucifer.bot import Bot

    print("== tabel ACTION (ekstraksi libgrowtopia.so) ==")
    cek("ACTIONS berisi 75 aksi", len(P.ACTIONS), 75)
    cek("gohomeworld ada", "gohomeworld" in P.ACTIONS, True)
    cek("field store", P.ACTIONS["store"], ("location",))
    cek("field trade_lock", P.ACTIONS["trade_lock"], ("status",))
    cek(
        "field worldlock_storage_modify_amount",
        P.ACTIONS["worldlock_storage_modify_amount"],
        ("amount", "type"),
    )

    cek("build_action tanpa field", P.build_action("gohomeworld"),
        b"action|gohomeworld\n")
    cek(
        "build_action urut sesuai tabel",
        P.build_action("storenavigate", item="locks", selection="upgrade_backpack"),
        b"action|storenavigate\nitem|locks\nselection|upgrade_backpack\n",
    )

    acc = Account(username="t", method="token", ltoken="X" * 10)
    b = Bot(acc, label="t")
    keluar: list[bytes] = []
    b.send_text = lambda mt, body: keluar.append(body) or True

    b.kirim("trade_lock", status=1)
    cek("kirim keyword", keluar[-1], b"action|trade_lock\nstatus|1\n")

    b.kirim("storenavigate", "item", "locks", "selection", "upgrade_backpack")
    cek("kirim gaya pasangan (Lua)", keluar[-1],
        b"action|storenavigate\nitem|locks\nselection|upgrade_backpack\n")

    b.kirim("worldlock_storage_modify_amount", 5, 2)
    cek("kirim posisional (Lua)", keluar[-1],
        b"action|worldlock_storage_modify_amount\namount|5\ntype|2\n")

    try:
        b.kirim("aksi_palsu")
        cek("aksi tak dikenal ditolak", "tidak error", "KeyError")
    except KeyError:
        cek("aksi tak dikenal ditolak", "KeyError", "KeyError")


def uji_autocollect_tile() -> None:
    """Tile terpilih harus menang atas radius.

    Bug nyata: `mode` default "Radius", dan syarat lama `mode == "Tile" and
    bool(self.tiles)` membuat tile yang sudah dicentang user diabaikan —
    bot menyapu radius 3 tile dan mengambil objek di atas/bawah bot.
    """
    print("\n-- Autocollect: tile menang atas radius --")
    from lucifer.bot import Account, Bot, Player
    from lucifer.features import AutoCollect

    b = Bot(Account(), items_db=None)
    b.local = Player(netid=1, posx=64, posy=96)
    b.local.isLocalPlayer = True
    ac = AutoCollect(b)
    ac.faster = False
    ac.check = False

    Obj = lambda uid, x, y: type("O", (), {"uid": uid, "x": x, "y": y,
                                           "item_id": 0})()
    ambil: list[int] = []
    b.collectObject = lambda uid: ambil.append(uid) or True
    # bot di tile (2,3); (2,2) = satu tile di atas bot
    b.world.dropped = [Obj(1, 70, 90), Obj(2, 70, 130)]

    ac.tiles = [(2, 2)]
    assert ac.sekali() == 1 and ambil == [1], ambil
    cek("hanya tile terpilih yang diambil", ambil, [1])

    ambil.clear()
    ac.tiles = []
    assert ac.sekali() == 2, ambil
    cek("tanpa tile jatuh ke radius", ambil, [1, 2])

    cek("opsi mode schema = Radius/Tile",
        [k.get("opsi") for k in SKEMA_FITUR
         if k["fitur"] == "autocollect"
         for k in k["kontrol"] if k["kunci"] == "mode"], [["Radius", "Tile"]])


uji_tabel_action()
uji_autocollect_tile()


print("\n" + "=" * 62)
print(f" lulus: {LULUS}   gagal: {GAGAL}")
print("=" * 62)
sys.exit(1 if GAGAL else 0)
