"""
lucifer.features — Fitur otomasi gaya deltaX/Lucifer, berbasis PAKET.

KENAPA MODUL INI ADA
--------------------
deltaX adalah mod menu Android yang menyuntik `libPowerKuy.so` ke proses game.
Fitur seperti ESP, noclip, ghost, visual-inventory ada di sisi *client* —
mereka hanya menggambar/mengubah memori lokal, jadi MUSTAHIL dibawa ke klien
protokol murni seperti Lucifer Linux.

Yang BISA dibawa: semua fitur yang hasilnya berupa paket ke server. Modul ini
berisi tepat itu, dengan nama alias mengikuti `assets/menu.json` deltaX supaya
mudah dicocokkan:

    autofarm_item_picker / autofarm_target_tile / autofarm_start
    autofarm_autocollect_start / auto_collect_mode / auto_collect_radius
    spammer_config_* / spammer_config_start
    findpath_config_item / findpath_config_blockjump / findpath_config_teleport_path
    cheat_config_autoenter / cheat_config_fastdrop_* / cheat_config_fasttrash_*
    automation_* / cmd_* (perintah chat)

Yang SENGAJA tidak diimplementasikan (butuh render/memori client):
    cheat_esp_player, cheat_esp_item, cheat_esp_ghost, noclip_and_ghost,
    features_invis_v2, visual_inventory_itemid, debug_* (dump paket mentah
    tetap ada di log, bukan menu), gravity, antibounce, Antipunch.

Dipakai dari Lua lewat `features.lua_api()` — lihat `lucifer/lua_api.py`.
"""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .bot import Bot, BotStatus
from .world import Tile, World

__all__ = [
    "FeatureError",
    "AutoFarm",
    "AutoCollect",
    "Spammer",
    "PathFinder",
    "AutoDrop",
    "Replay",
    "Growscan",
    "Commands",
    "FiturBot",
    "TILE_MENU",
    "SEMUA_ALIAS",
]


class FeatureError(RuntimeError):
    """Fitur dipakai dengan konfigurasi yang tidak sah."""


# --------------------------------------------------------------------------- #
# Nama alias -> fitur (untuk laporan "apa yang sudah dipindah")
# --------------------------------------------------------------------------- #
TILE_MENU: dict[str, str] = {
    # alias deltaX                              : keterangan
    "autofarm_start": "auto tanam/panen (paket hit + place)",
    "autofarm_autocollect_start": "ambil objek jatuh di sekitar",
    "autofarm_do_break": "atur boleh memecah",
    "autofarm_do_place": "atur boleh menanam",
    "autofarm_verify": "hanya pukul tile yang benar-benar siap panen",
    "autofarm_verify_pos": "cek posisi pemain sebelum lanjut",
    "autofarm_verify_delay": "jeda setelah menyesuaikan posisi (ms)",
    "autofarm_punch_count": "jumlah pukulan per tile",
    "autofarm_autopunch_delay": "jeda antar pukulan (ms)",
    "autofarm_autoplace_delay": "jeda antar tanam (ms)",
    "autofarm_config_overclock": "potong semua jeda 40%",
    "autofarm_config_showpunch": "kirim semua pukulan tanpa jeda",
    "autofarm_target_tile": "daftar tile sasaran (x,y)",
    "autofarm_item_picker": "id bibit yang ditanam",
    "autofarm_autocollect_delay": "jeda antar ambil objek (ms)",
    "autofarm_autocollect_block": "ikut ambil blok (id genap)",
    "autofarm_autocollect_seed": "ikut ambil bibit (id ganjil)",
    "autofarm_autodrop_start": "drop otomatis saat inventaris penuh",
    "autofarm_autodrop_minimum": "jumlah minimum sebelum dibuang",
    "autofarm_autodrop_x": "posisi X tempat drop",
    "autofarm_autodrop_y": "posisi Y tempat drop",
    "autofarm_autodrop_worldname": "dunia tujuan drop (kosong = dunia ini)",
    "autofarm_autopick_enable": "ambil item di dunia lain",
    "autofarm_autopick_world": "dunia sumber pick",
    "autofarm_autopick_mode": "mode pick: nearest | all",
    "autocollectstart": "ambil objek jatuh",
    "auto_collect_delay": "jeda antar ambil (ms)",
    "auto_collect_radius": "radius ambil (tile)",
    "spammer_config_start": "mulai spam chat",
    "spammer_config_texttospam": "teks/daftar teks spam",
    "spammer_config_delay": "jeda antar pesan (ms)",
    "spammer_config_shuffle": "acak urutan teks",
    "findpath_config_item": "cari tile berisi item",
    "findpath_config_blockjump": "hitung tile solid sebagai penghalang",
    "findpath_config_teleport_path": "pindah tile-per-tile tanpa jalan",
    "cheat_config_autoenter": "masuk dunia otomatis setelah warp",
    "cheat_config_fastdrop_active": "drop cepat (1 paket)",
    "cheat_config_fasttrash_active": "trash cepat (1 paket)",
    "automation_autocollect": "mode otomasi: ambil objek",
    "automation_autotake": "mode otomasi: ambil semua di tile",
    "automation_autosplice": "mode otomasi: splice bibit",
    "automation_start": "jalankan mode otomasi",
}

SEMUA_ALIAS = tuple(TILE_MENU)

# Item yang dianggap "bibit" saat menebak lahan kosong/tanah.
BG_TANAH = 14  # id background tanah standar Growtopia (Grass bg)


# --------------------------------------------------------------------------- #
# Dasar
# --------------------------------------------------------------------------- #
@dataclass
class _Siklus:
    """Status satu loop latar belakang yang bisa dihentikan."""

    nama: str
    aktif: bool = False
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: Optional[threading.Thread] = None

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3)
        self._thread = None
        self.aktif = False


def _tunggu(stop: threading.Event, detik: float) -> bool:
    """Tidur yang bisa dibatalkan. Return True kalau diminta berhenti."""
    return stop.wait(detik)


# --------------------------------------------------------------------------- #
# AutoFarm
# --------------------------------------------------------------------------- #
class AutoFarm:
    """Auto tanam + panen, setara `autofarm_*` deltaX.

    Semua parameter di bawah mengikuti `assets/menu.json` deltaX (sub-kategori
    Automation/Autofarm), jadi tiap tombol di sana punya padanan di sini:

      autofarm_item_picker       seed_id
      autofarm_target_tile       set_tiles()
      autofarm_verify            verify
      autofarm_do_break          do_break
      autofarm_do_place          do_place
      autofarm_punch_count       punch_count
      autofarm_autopunch_delay   punch_delay
      autofarm_autoplace_delay   place_delay
      autofarm_config_overclock  faster      (jeda dipotong 40%)
      autofarm_config_showpunch  show_punch  (hit berulang tanpa jeda ekstra)
      autofarm_autocollect_*     collect / collect_delay / collect_block / collect_seed
      autofarm_autodrop_*        drop_aktif / drop_minimum / drop_x / drop_y / drop_world
      autofarm_autopick_*        pick_aktif / pick_world / pick_mode
      autofarm_verify_pos        verify_pos
      autofarm_verify_delay      verify_delay

    Alur satu siklus (meniru `automation.lua` deltaX):

        buang  ->  pindah dunia (kalau perlu)  ->  ambil  ->  panen  ->  tanam

    Semua aksi lewat paket nyata: `bot.hit`, `bot.place`, `bot.collectObject`,
    `bot.drop`, `bot.trash`, `bot.warp`.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.aktif = False

        # -- sasaran ----------------------------------------------------- #
        self.seed_id = 0
        self.target_tiles: list[tuple[int, int]] = []

        # -- apa yang dikerjakan ------------------------------------------ #
        self.do_break = True
        self.do_place = True
        self.verify = True          # verifikasi tile siap panen sebelum pukul
        self.verify_pos = False     # verifikasi posisi pemain sebelum lanjut
        self.verify_delay = 250     # ms, jeda setelah menyesuaikan posisi

        # -- kecepatan ---------------------------------------------------- #
        self.punch_count = 1
        self.punch_delay = 180      # ms
        self.place_delay = 220      # ms
        self.siklus_delay = 1000    # ms, jeda antar siklus
        self.faster = False         # autofarm_config_overclock
        self.show_punch = False     # autofarm_config_showpunch

        # -- auto collect -------------------------------------------------- #
        self.collect = True
        self.collect_delay = 120
        self.collect_radius = 3
        self.collect_block = True    # ambil blok (id genap)
        self.collect_seed = True     # ambil bibit (id ganjil)

        # -- auto drop ----------------------------------------------------- #
        self.drop_aktif = False
        self.drop_minimum = 180
        self.drop_x = 0
        self.drop_y = 0
        self.drop_world = ""         # dunia tujuan drop (kosong = dunia ini)
        self.drop_mode = "drop"      # "drop" | "trash"
        self.drop_total = 0

        # -- auto pick (telur/seed pack di dunia lain) --------------------- #
        self.pick_aktif = False
        self.pick_world = ""
        self.pick_mode = "nearest"   # "nearest" | "all"

        # -- hasil --------------------------------------------------------- #
        self.siklus: list[int] = []
        self.dipanen_total = 0
        self.ditanam_total = 0
        self.diambil_total = 0
        self._s = _Siklus("autofarm")

    # -- sasaran --------------------------------------------------------- #
    def atur(self, **kw) -> dict[str, Any]:
        """Set parameter sekaligus, nama kunci = alias deltaX tanpa `autofarm_`.

        Dipakai dashboard & Lua supaya tidak perlu satu method per tombol:

            af.atur(seed_id=3, punch_count=3, punch_delay=120, faster=True,
                    do_place=False, collect=False, drop_aktif=True)

        Kunci tak dikenal diabaikan (bukan error) supaya skrip lama tetap jalan.
        """
        peta = {
            "seed_id": "seed_id",
            "item_picker": "seed_id",
            "target_tile": "target_tiles",
            "verify": "verify",
            "verify_pos": "verify_pos",
            "verify_delay": "verify_delay",
            "do_break": "do_break",
            "do_place": "do_place",
            "punch_count": "punch_count",
            "autopunch_delay": "punch_delay",
            "punch_delay": "punch_delay",
            "autoplace_delay": "place_delay",
            "place_delay": "place_delay",
            "siklus_delay": "siklus_delay",
            "overclock": "faster",
            "faster": "faster",
            "showpunch": "show_punch",
            "show_punch": "show_punch",
            # autocollect
            "autocollect_start": "collect",
            "collect": "collect",
            "autocollect_delay": "collect_delay",
            "collect_delay": "collect_delay",
            "collect_radius": "collect_radius",
            "autocollect_block": "collect_block",
            "collect_block": "collect_block",
            "autocollect_seed": "collect_seed",
            "collect_seed": "collect_seed",
            # autodrop
            "autodrop_start": "drop_aktif",
            "drop_aktif": "drop_aktif",
            "autodrop_minimum": "drop_minimum",
            "drop_minimum": "drop_minimum",
            "autodrop_x": "drop_x",
            "drop_x": "drop_x",
            "autodrop_y": "drop_y",
            "drop_y": "drop_y",
            "autodrop_worldname": "drop_world",
            "drop_world": "drop_world",
            "drop_mode": "drop_mode",
            # autopick
            "autopick_enable": "pick_aktif",
            "pick_aktif": "pick_aktif",
            "autopick_world": "pick_world",
            "pick_world": "pick_world",
            "autopick_mode": "pick_mode",
            "pick_mode": "pick_mode",
        }
        diterapkan = {}
        for kunci, nilai in kw.items():
            nama = peta.get(str(kunci))
            if nama is None:
                continue
            if nama == "target_tiles":
                self.set_tiles(nilai)
            elif nama in ("do_break", "do_place", "verify", "verify_pos", "faster",
                          "show_punch", "collect", "collect_block", "collect_seed",
                          "drop_aktif", "pick_aktif"):
                setattr(self, nama, bool(nilai))
            elif nama in ("drop_mode", "drop_world", "pick_world", "pick_mode"):
                setattr(self, nama, str(nilai))
            else:
                setattr(self, nama, int(nilai))
            diterapkan[nama] = getattr(self, nama)
        return diterapkan

    def set_tiles(self, tiles) -> list[tuple[int, int]]:
        """Tetapkan tile sasaran. Terima list (x,y) atau list dict {x,y}."""
        out: list[tuple[int, int]] = []
        for t in tiles or []:
            if isinstance(t, (list, tuple)) and len(t) >= 2:
                out.append((int(t[0]), int(t[1])))
            elif isinstance(t, dict):
                out.append((int(t.get("x", 0)), int(t.get("y", 0))))
            elif hasattr(t, "x") and hasattr(t, "y"):
                out.append((int(t.x), int(t.y)))
        self.target_tiles = out
        return out

    def tiles_sasaran(self) -> list[Tile]:
        """Tentukan tile kerja: manual kalau diisi, kalau tidak latar tanah."""
        w = self.bot.world
        if not w.tiles:
            return []
        if self.target_tiles:
            out = []
            for x, y in self.target_tiles:
                t = w.tile(x, y)
                if t is not None:
                    out.append(t)
            return out
        return [t for t in w.tiles if t.bg != 0]

    def siap_panen(self) -> list[Tile]:
        """Tile sasaran yang tanamannya sudah bisa dipetik.

        `verify` mematikan memeriksa `ready`; tanpa itu semua tile bertanaman
        dipukul (lebih cepat, tapi memboroskan pukulan).
        """
        out = []
        for t in self.tiles_sasaran():
            if not t.is_seed:
                continue
            if self.verify and not t.ready:
                continue
            out.append(t)
        return out

    def kosong(self) -> list[Tile]:
        """Tile sasaran yang bisa ditanami."""
        return [t for t in self.tiles_sasaran() if t.fg == 0 and t.bg != 0]

    # -- jeda ------------------------------------------------------------- #
    def _jeda(self, ms: float) -> float:
        """Terapkan `faster` (overclock) ke semua jeda."""
        return (float(ms) * 0.6 if self.faster else float(ms)) / 1000.0

    # -- aksi -------------------------------------------------------------- #
    def panen(self) -> int:
        if not self.do_break:
            return 0
        n = 0
        for t in self.siap_panen():
            if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                break
            for _ in range(max(1, int(self.punch_count))):
                self.bot.hit(t.x, t.y)
                # `showpunch` = kirim semua pukulan tanpa jeda; default beri jeda
                # supaya server sempat memproses tiap pukulan.
                if not self.show_punch:
                    if _tunggu(self._s._stop, self._jeda(self.punch_delay)):
                        return n
            n += 1
            self.dipanen_total += 1
        return n

    def ambil(self) -> int:
        """Ambil objek jatuh. Filter blok/bibit mengikuti `collect_block`/`collect_seed`."""
        if not self.collect:
            return 0
        total = 0
        for _ in range(4):
            w = self.bot.world
            n = 0
            for d in list(w.dropped):
                if self._s._stop.is_set():
                    return total
                if not self.bot._in_range_px(d.x, d.y, self.collect_radius):
                    continue
                # id bibit = ganjil, id blok = genap (konvensi Growtopia)
                if d.item_id % 2 == 0 and not self.collect_block:
                    continue
                if d.item_id % 2 == 1 and not self.collect_seed:
                    continue
                self.bot.collectObject(d.uid)
                n += 1
                if self.collect_delay:
                    if _tunggu(self._s._stop, self._jeda(self.collect_delay)):
                        return total
            total += n
            self.diambil_total += n
            if n == 0:
                break
            if _tunggu(self._s._stop, 0.35):
                break
        return total

    def tanam(self) -> int:
        if not self.do_place or not self.seed_id:
            return 0
        punya = self.bot.inventory.getItemCount(self.seed_id)
        n = 0
        for t in self.kosong():
            if n >= punya:
                break
            if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                break
            self.bot.place(t.x, t.y, self.seed_id)
            n += 1
            self.ditanam_total += 1
            if _tunggu(self._s._stop, self._jeda(self.place_delay)):
                break
        return n

    def buang(self) -> int:
        """Drop/trash item yang melewati `drop_minimum` (autofarm_autodrop_*)."""
        if not self.drop_aktif:
            return 0
        inv = self.bot.inventory
        n = 0
        target = self.seed_id if self.seed_id else 0
        for item_id, it in list(inv.items.items()):
            if target and item_id not in (target, target - 1):
                continue
            if it.count < self.drop_minimum:
                continue
            if self._s._stop.is_set():
                break
            if self.drop_mode == "trash":
                self.bot.trash(item_id, it.count)
            else:
                self.bot.drop(item_id, it.count)
            n += 1
            if _tunggu(self._s._stop, self._jeda(self.place_delay)):
                break
        self.drop_total += n
        return n

    # -- siklus ------------------------------------------------------------ #
    def satu_siklus(self) -> dict[str, int]:
        """Satu putaran penuh: buang -> ambil -> panen -> tanam."""
        hasil = {
            "dibuang": self.buang(),
            "diambil": self.ambil(),
            "dipanen": self.panen(),
            "ditanam": self.tanam(),
        }
        self.siklus.append(hasil["dipanen"] + hasil["ditanam"])
        return hasil

    # -- loop -------------------------------------------------------------- #
    def start(self, jeda: float | None = None) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        if not self.bot.world.tiles:
            raise FeatureError("dunia belum termuat — masuk world dulu")
        if self.do_place and not self.seed_id:
            raise FeatureError("seed_id belum diset (autofarm_item_picker)")

        bila_none = self.siklus_delay / 1000.0
        self._s = _Siklus("autofarm", aktif=True)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    self.satu_siklus()
                except Exception:  # noqa: BLE001
                    pass
                if _tunggu(self._s._stop, bila_none if jeda is None else float(jeda)):
                    break
            self._s.aktif = False
            self.aktif = False

        self._s._thread = threading.Thread(target=loop, name="lucifer-autofarm", daemon=True)
        self._s._thread.start()
        self.aktif = True
        return True

    def stop(self) -> None:
        self._s.stop()
        self.aktif = False

    @property
    def berjalan(self) -> bool:
        return self._s.aktif

    def info(self) -> dict[str, Any]:
        return {
            "aktif": self._s.aktif,
            "seed_id": self.seed_id,
            "tiles": len(self.target_tiles),
            "siap_panen": len(self.siap_panen()) if self.bot.world.tiles else 0,
            "kosong": len(self.kosong()) if self.bot.world.tiles else 0,
            "siklus": len(self.siklus),
            "dipanen_total": self.dipanen_total,
            "ditanam_total": self.ditanam_total,
            "diambil_total": self.diambil_total,
            "dibuang_total": self.drop_total,
            "do_break": self.do_break,
            "do_place": self.do_place,
            "verify": self.verify,
            "punch_count": self.punch_count,
            "punch_delay": self.punch_delay,
            "place_delay": self.place_delay,
            "siklus_delay": self.siklus_delay,
            "faster": self.faster,
            "collect": self.collect,
            "collect_radius": self.collect_radius,
            "collect_block": self.collect_block,
            "collect_seed": self.collect_seed,
            "drop_aktif": self.drop_aktif,
            "drop_minimum": self.drop_minimum,
            "drop_world": self.drop_world,
            "pick_aktif": self.pick_aktif,
            "pick_world": self.pick_world,
        }


# --------------------------------------------------------------------------- #
# AutoCollect
# --------------------------------------------------------------------------- #
class AutoCollect:
    """Ambil objek jatuh terus-menerus (`auto_collect_*` deltaX)."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.radius = 3
        self.delay = 150          # ms jeda antar objek
        self.jeda = 0.5           # detik jeda antar siklus
        self.item_id = 0          # 0 = semua item
        self.tiles: list[tuple[int, int]] = []   # kosong = semua tile
        self.mode = "Radius"      # "Radius" | "Tile"
        self.faster = True        # tanpa jeda antar objek
        self.check = True         # cek objek masih ada sebelum diambil
        self.aktif = False
        self.total = 0
        self._s = _Siklus("autocollect")

    def sekali(self) -> int:
        # mode Tile = hanya objek yang jatuh di tile terpilih
        pakai_tile = self.mode == "Tile" and bool(self.tiles)
        if self.faster:
            interval = 0
        else:
            interval = self.delay
        if not self.item_id and not pakai_tile:
            n = self.bot.collect(range_=self.radius, interval=interval)
            self.total += n
            return n
        # filter: item tertentu dan/atau tile sasaran
        n = 0
        for d in list(self.bot.world.dropped):
            if self.item_id and d.item_id != self.item_id:
                continue
            if pakai_tile:
                tx, ty = int(d.x // 32), int(d.y // 32)
                if (tx, ty) not in self.tiles:
                    continue
            elif not self.bot._in_range_px(d.x, d.y, self.radius):
                continue
            if self.check and not any(o.uid == d.uid for o in self.bot.world.dropped):
                continue
            self.bot.collectObject(d.uid)
            n += 1
            if interval:
                time.sleep(interval / 1000.0)
        self.total += n
        return n

    def start(self, jeda: float = 0) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        self._s = _Siklus("autocollect", aktif=True)
        interval = float(jeda) if jeda else float(self.jeda)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    self.sekali()
                except Exception:  # noqa: BLE001
                    pass
                if _tunggu(self._s._stop, interval):
                    break
            self._s.aktif = False
            self.aktif = False

        self._s._thread = threading.Thread(target=loop, name="lucifer-autocollect", daemon=True)
        self._s._thread.start()
        self.aktif = True
        return True

    def stop(self) -> None:
        self._s.stop()
        self.aktif = False

    @property
    def berjalan(self) -> bool:
        return self._s.aktif

    def info(self) -> dict[str, Any]:
        return {"aktif": self._s.aktif, "radius": self.radius,
                "jeda": self.jeda, "item_id": self.item_id,
                "mode": self.mode, "faster": self.faster, "check": self.check,
                "tiles": [list(t) for t in self.tiles],
                "diambil": self.total,
                "objek_dunia": len(self.bot.world.dropped)}


# --------------------------------------------------------------------------- #
# Spammer
# --------------------------------------------------------------------------- #
class Spammer:
    """Spam chat berkala (`spammer_config_*` deltaX)."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.daftar: list[str] = []
        self.delay = 1200        # ms
        self.shuffle = False
        self.aktif = False
        self.terkirim = 0
        self._s = _Siklus("spammer")
        self._idx = 0

    def tambah(self, teks: str) -> list[str]:
        teks = str(teks).strip()
        if teks and teks not in self.daftar:
            self.daftar.append(teks)
        return list(self.daftar)

    def bersihkan(self) -> None:
        self.daftar.clear()
        self._idx = 0

    def _berikut(self) -> str:
        if not self.daftar:
            return ""
        if self.shuffle:
            return random.choice(self.daftar)
        t = self.daftar[self._idx % len(self.daftar)]
        self._idx += 1
        return t

    def sekali(self) -> bool:
        teks = self._berikut()
        if not teks:
            return False
        ok = self.bot.say(teks)
        if ok:
            self.terkirim += 1
        return ok

    def start(self) -> bool:
        if self._s.aktif:
            return True
        if not self.daftar:
            raise FeatureError("daftar spam kosong (spammer_config_texttospam)")
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        self._s = _Siklus("spammer", aktif=True)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    self.sekali()
                except Exception:  # noqa: BLE001
                    pass
                if _tunggu(self._s._stop, max(0.3, self.delay / 1000)):
                    break
            self._s.aktif = False
            self.aktif = False

        self._s._thread = threading.Thread(target=loop, name="lucifer-spammer", daemon=True)
        self._s._thread.start()
        self.aktif = True
        return True

    def stop(self) -> None:
        self._s.stop()
        self.aktif = False

    @property
    def berjalan(self) -> bool:
        return self._s.aktif

    def info(self) -> dict[str, Any]:
        return {"aktif": self._s.aktif, "jumlah_teks": len(self.daftar),
                "delay": self.delay, "terkirim": self.terkirim}


# --------------------------------------------------------------------------- #
# PathFinder
# --------------------------------------------------------------------------- #
class PathFinder:
    """Cari jalan ke tile lalu tempuh (`findpath_config_*` deltaX).

    Beda dengan `Bot.getPath()`: di sini penghalang memperhitungkan tile
    terpasang (fg != 0) bila `block_jump` aktif, dan `teleport_path`
    mengirim posisi langsung tanpa berhenti di tiap tile.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.block_jump = True
        self.teleport_path = False
        self.jeda = 0.12
        self.x = 0               # tujuan terakhir (dipakai GUI)
        self.y = 0

    def bisa_dilewati(self, x: int, y: int) -> bool:
        w = self.bot.world
        t = w.tile(x, y)
        if t is None:
            return False
        if not self.block_jump:
            return True
        return t.fg == 0

    def cari(self, x: int, y: int) -> list[tuple[int, int]]:
        """BFS 4 arah. Return jalur tanpa tile awal, kosong bila tak ada."""
        import collections  # noqa: PLC0415

        b = self.bot
        w = b.world
        if not b.local or not w.tiles:
            return []
        sx, sy = b.local.tile_x, b.local.tile_y
        tx, ty = int(x), int(y)
        if (sx, sy) == (tx, ty) or w.tile(tx, ty) is None:
            return []
        seen = {(sx, sy)}
        q: collections.deque[tuple[int, int, list[tuple[int, int]]]] = collections.deque(
            [(sx, sy, [])])
        langkah = 0
        while q and langkah < 40000:
            langkah += 1
            cx, cy, jalur = q.popleft()
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in seen:
                    continue
                if (nx, ny) != (tx, ty) and not self.bisa_dilewati(nx, ny):
                    continue
                if w.tile(nx, ny) is None:
                    continue
                seen.add((nx, ny))
                baru = jalur + [(nx, ny)]
                if (nx, ny) == (tx, ty):
                    return baru
                q.append((nx, ny, baru))
        return []

    def jalan(self, x: int, y: int) -> bool:
        jalur = self.cari(x, y)
        if not jalur:
            return False
        if self.teleport_path:
            # Pindah langsung ke tujuan (server tetap menerima State packet).
            self.bot.moveTile(int(x), int(y))
            return True
        for px, py in jalur:
            if self.bot.status != BotStatus.online:
                return False
            self.bot.moveTile(px, py)
            time.sleep(self.jeda)
        return True

    def cari_item(self, item_id: int) -> list[tuple[int, int]]:
        """Cari tile yang berisi item tertentu (`findpath_config_item`)."""
        return [(t.x, t.y) for t in self.bot.world.find_items(int(item_id))]

    def terdekat_item(self, item_id: int) -> Optional[tuple[int, int]]:
        kandidat = self.cari_item(item_id)
        if not kandidat or not self.bot.local:
            return None
        lx, ly = self.bot.local.tile_x, self.bot.local.tile_y
        return min(kandidat, key=lambda p: abs(p[0] - lx) + abs(p[1] - ly))

    def info(self) -> dict[str, Any]:
        p = self.bot.local
        return {
            "posisi": (p.tile_x, p.tile_y) if p else None,
            "block_jump": self.block_jump,
            "teleport_path": self.teleport_path,
        }


# --------------------------------------------------------------------------- #
# AutoDrop / AutoTrash (cheat_config_fastdrop_* / fasttrash_*)
# --------------------------------------------------------------------------- #
class AutoDrop:
    """Drop/trash otomatis item yang jumlahnya melewati batas."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.aktif = False
        self.minimum = 200
        self.mode = "drop"       # "drop" | "trash"
        self.jeda = 2.0          # detik antar siklus
        self.world = ""          # kosong = dunia sekarang
        self.x = 0               # 0 = posisi sekarang
        self.y = 0
        self.item_ids: list[int] = []
        self._s = _Siklus("autodrop")
        self.total = 0

    def _pindah_ke_lokasi(self) -> None:
        """Warp / geser ke titik buang bila diatur."""
        b = self.bot
        if self.world and b.world.name != self.world:
            b.warp(self.world)
            for _ in range(40):
                if b.world.name == self.world:
                    break
                time.sleep(0.25)
        if self.x or self.y:
            if b.local and (b.local.tile_x != self.x or b.local.tile_y != self.y):
                b.moveTile(self.x, self.y)
                time.sleep(0.2)

    def start(self, jeda: float = 0) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        self._s = _Siklus("autodrop", aktif=True)
        interval = float(jeda) if jeda else float(self.jeda)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    self._satu()
                except Exception:  # noqa: BLE001
                    pass
                if _tunggu(self._s._stop, interval):
                    break
            self._s.aktif = False
            self.aktif = False

        self._s._thread = threading.Thread(target=loop, name="lucifer-autodrop", daemon=True)
        self._s._thread.start()
        self.aktif = True
        return True

    def _satu(self) -> int:
        inv = self.bot.inventory
        n = 0
        pindah = bool(self.world) or bool(self.x) or bool(self.y)
        sudah_pindah = False
        for item_id, it in list(inv.items.items()):
            if self.item_ids and item_id not in self.item_ids:
                continue
            if it.count < self.minimum:
                continue
            if pindah and not sudah_pindah:
                self._pindah_ke_lokasi()
                sudah_pindah = True
            if self.mode == "trash":
                self.bot.trash(item_id, it.count)
            else:
                self.bot.drop(item_id, it.count)
            n += 1
        self.total += n
        return n

    def stop(self) -> None:
        self._s.stop()
        self.aktif = False

    def info(self) -> dict[str, Any]:
        return {"aktif": self._s.aktif, "mode": self.mode,
                "minimum": self.minimum, "jeda": self.jeda,
                "world": self.world, "x": self.x, "y": self.y,
                "dibuang": self.total}


# --------------------------------------------------------------------------- #
# Replay — rekam & putar ulang aksi (replay_record_* / replay_play_* deltaX)
# --------------------------------------------------------------------------- #
# Metode Bot yang ikut direkam. Semua ini mengirim paket nyata, jadi
# memutarnya ulang = mengulang aksi yang sama ke server.
AKSI_REPLAY = (
    "say", "warp", "leaveWorld", "respawn", "enter", "use", "wear", "unwear",
    "drop", "trash", "place", "hit", "wrench", "wrenchPlayer", "active",
    "collectObject", "retrieve", "buy", "moveTile", "moveTo", "moveLeft",
    "moveRight", "moveUp", "moveDown", "setDirection",
)


class Replay:
    """Rekam aksi keluar lalu putar ulang (`replay_*` deltaX).

    Rekaman disimpan sebagai JSON: `[{"aksi": "hit", "args": [1, 2], "t": 0.83}]`
    dengan `t` = detik sejak rekaman mulai, supaya tempo tetap mirip aslinya.
    """

    def __init__(self, bot: Bot, folder: str | Path = "data/replay") -> None:
        self.bot = bot
        self.folder = Path(folder)
        self.aktif = False
        self.memutar = False
        self.loop = False
        self.custom_delay = 0          # ms; 0 = pakai tempo rekaman
        self.file = "rekaman.json"     # berkas terakhir yang dipakai
        self.aksi: list[dict[str, Any]] = []
        self._t0 = 0.0
        self._asli: dict[str, Callable[..., Any]] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- rekam ------------------------------------------------------------ #
    def _pasang_hook(self) -> None:
        for nama in AKSI_REPLAY:
            fn = getattr(self.bot, nama, None)
            if fn is None or nama in self._asli:
                continue
            self._asli[nama] = fn
            setattr(self.bot, nama, self._bungkus(nama, fn))

    def _lepas_hook(self) -> None:
        for nama, fn in self._asli.items():
            setattr(self.bot, nama, fn)
        self._asli.clear()

    def _bungkus(self, nama: str, fn: Callable[..., Any]):
        def luar(*args, **kw):
            if self.aktif:
                self.aksi.append({
                    "aksi": nama, "args": list(args),
                    "t": round(time.time() - self._t0, 3),
                })
            return fn(*args, **kw)

        return luar

    def mulai_rekam(self, bersihkan: bool = True) -> int:
        if bersihkan:
            self.aksi.clear()
        self._t0 = time.time()
        self._pasang_hook()
        self.aktif = True
        return len(self.aksi)

    def stop_rekam(self) -> int:
        self.aktif = False
        self._lepas_hook()
        return len(self.aksi)

    # -- simpan / muat ---------------------------------------------------- #
    def simpan(self, nama: str = "") -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        nama = nama or self.file or "rekaman.json"
        self.file = nama
        nama = nama if nama.endswith(".json") else nama + ".json"
        p = self.folder / nama
        p.write_text(json.dumps(self.aksi, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(p)

    def muat(self, nama: str = "") -> int:
        nama = nama or self.file or "rekaman.json"
        self.file = nama
        nama = nama if nama.endswith(".json") else nama + ".json"
        p = self.folder / nama
        if not p.exists():
            raise FeatureError(f"berkas replay tidak ada: {p}")
        self.aksi = json.loads(p.read_text(encoding="utf-8"))
        return len(self.aksi)

    def daftar_berkas(self) -> list[str]:
        if not self.folder.exists():
            return []
        return sorted(f.name for f in self.folder.glob("*.json"))

    # -- putar ------------------------------------------------------------ #
    def putar(self, ulang: bool = False) -> bool:
        if self.memutar:
            return True
        if not self.aksi:
            raise FeatureError("belum ada aksi terekam")
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        self.loop = bool(ulang)
        self._stop = threading.Event()
        self.memutar = True

        def loop() -> None:
            while True:
                t_lalu = 0.0
                for a in list(self.aksi):
                    if self._stop.is_set():
                        break
                    jeda = (self.custom_delay / 1000.0) if self.custom_delay else (
                        float(a.get("t", 0)) - t_lalu)
                    t_lalu = float(a.get("t", 0))
                    if jeda > 0 and self._stop.wait(min(jeda, 10.0)):
                        break
                    fn = getattr(self.bot, a.get("aksi", ""), None)
                    if fn is None:
                        continue
                    try:
                        fn(*(a.get("args") or []))
                    except Exception:  # noqa: BLE001
                        pass
                if self._stop.is_set() or not self.loop:
                    break
                if self._stop.wait(1.0):
                    break
            self.memutar = False

        self._thread = threading.Thread(target=loop, name="lucifer-replay", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self.memutar = False
        if self.aktif:
            self.stop_rekam()

    def bersihkan(self) -> None:
        self.aksi.clear()

    def info(self) -> dict[str, Any]:
        return {"merekam": self.aktif, "memutar": self.memutar,
                "aksi": len(self.aksi), "loop": self.loop,
                "custom_delay": self.custom_delay,
                "berkas": self.daftar_berkas()}


# --------------------------------------------------------------------------- #
# Growscan — pindai isi dunia (cheat_growscan_* deltaX)
# --------------------------------------------------------------------------- #
class Growscan:
    """Pindai isi dunia: item yang terpasang dan objek jatuh.

    Ini murni pembacaan `world.tiles` yang sudah diterima bot — tidak perlu
    fitur klien apa pun.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    def scan(self) -> dict[str, Any]:
        w = self.bot.world
        db = self.bot.items_db
        blok: dict[int, int] = {}
        tanam: dict[int, int] = {}
        for t in w.tiles:
            if t.fg:
                target = tanam if t.is_seed else blok
                target[t.fg] = target.get(t.fg, 0) + 1
        jatuh: dict[int, int] = {}
        for d in w.dropped:
            jatuh[d.item_id] = jatuh.get(d.item_id, 0) + d.amount
        nama = (db.name_of if db else (lambda i: f"#{i}"))

        def rapikan(d: dict[int, int]) -> list[dict[str, Any]]:
            return [{"id": k, "nama": nama(k), "jumlah": v}
                    for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

        return {
            "world": w.name, "ukuran": f"{w.width}x{w.height}",
            "total_tile": len(w.tiles),
            "tanaman": rapikan(tanam), "blok": rapikan(blok),
            "jatuh": rapikan(jatuh),
            "pemain": [p.name for p in self.bot.players.values()],
        }


# --------------------------------------------------------------------------- #
# Perintah chat gaya deltaX (/warp, /help, /finditem, /gscan, ...)
# --------------------------------------------------------------------------- #
class Commands:
    """Perintah chat yang diketik bot sendiri (cmd_* deltaX).

    Dipanggil dari `Bot.say()`: kalau teks diawali `/` dan dikenali, perintah
    dijalankan lokal dan TIDAK dikirim ke server.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.aktif = {
            "warp": True, "back": True, "help": True, "aliases": True,
            "alias": True, "unalias": True, "finditem": True, "gscan": True,
            "pullall": True, "kickall": True, "banall": True,
        }
        self.alias: dict[str, str] = {}
        self.riwayat_world: list[str] = []
        self._last_world = ""

    # -- util ------------------------------------------------------------- #
    def _daftar_perintah(self) -> dict[str, str]:
        return {
            "warp <dunia>": "pindah dunia (/wp)",
            "back": "kembali ke dunia sebelumnya (/b)",
            "finditem <nama|id>": "cari tile berisi item",
            "gscan": "pindai isi dunia",
            "pullall": "tarik semua pemain ke posisi bot",
            "kickall": "keluarkan semua pemain (butuh akses)",
            "banall": "ban semua pemain (butuh akses)",
            "alias <nama> <perintah>": "buat alias perintah",
            "unalias <nama>": "hapus alias",
            "aliases": "daftar alias",
            "help": "daftar perintah",
            "enable <perintah>": "aktifkan perintah",
            "disable <perintah>": "matikan perintah",
        }

    def _balas(self, teks: str) -> None:
        self.bot.console.append(teks)
        self.bot._emit("console", teks)

    # -- dispatcher ------------------------------------------------------- #
    def handle(self, teks: str) -> bool:
        """Return True kalau teks adalah perintah yang ditangani."""
        t = str(teks).strip()
        if not t.startswith("/") or len(t) < 2:
            return False
        isi = t[1:]
        bagian = isi.split(maxsplit=1)
        nama = bagian[0].lower()
        arg = bagian[1].strip() if len(bagian) > 1 else ""

        # perluas alias (satu tingkat, cukup untuk pemakaian normal)
        if nama in self.alias:
            return self.handle("/" + self.alias[nama] + (" " + arg if arg else ""))

        if nama in ("wp",):
            nama = "warp"
        if nama in ("b",):
            nama = "back"

        if nama in ("enable", "disable"):
            target = arg.lower()
            if target not in self.aktif:
                self._balas(f"perintah tidak dikenal: {target}")
                return True
            self.aktif[target] = (nama == "enable")
            self._balas(f"{target}: {'aktif' if self.aktif[target] else 'mati'}")
            return True

        if not self.aktif.get(nama, False):
            if nama in self._perintah_dikenal():
                self._balas(f"perintah /{nama} sedang dimatikan (/enable {nama})")
                return True
            return False

        fn = getattr(self, "_cmd_" + nama, None)
        if fn is None:
            return False
        try:
            fn(arg)
        except Exception as e:  # noqa: BLE001
            self._balas(f"/{nama} gagal: {type(e).__name__}: {e}")
        return True

    def _perintah_dikenal(self) -> set[str]:
        return {k[5:] for k in dir(self) if k.startswith("_cmd_")}

    # -- perintah --------------------------------------------------------- #
    def _cmd_help(self, arg: str) -> None:
        baris = [f"/{k} — {v}" for k, v in self._daftar_perintah().items()]
        self._balas("perintah tersedia:\n" + "\n".join(baris))

    def _cmd_warp(self, arg: str) -> None:
        if not arg:
            self._balas("pakai: /warp <nama dunia>")
            return
        if self.bot.world.name:
            self.riwayat_world.append(self.bot.world.name)
        self._last_world = arg
        self.bot.warp(arg)
        self._balas(f"warp -> {arg}")

    def _cmd_back(self, arg: str) -> None:
        if not self.riwayat_world:
            self._balas("tidak ada dunia sebelumnya")
            return
        tujuan = self.riwayat_world.pop()
        self._balas(f"kembali -> {tujuan}")
        self.bot.warp(tujuan)

    def _cmd_finditem(self, arg: str) -> None:
        if not arg:
            self._balas("pakai: /finditem <nama|id>")
            return
        item_id = int(arg) if arg.isdigit() else self.bot.findItemId(arg)
        if not item_id:
            self._balas(f"item tidak ditemukan: {arg}")
            return
        tiles = self.bot.world.find_items(item_id)
        if not tiles:
            self._balas(f"{self.bot.itemName(item_id)} tidak ada di dunia ini")
            return
        self._balas(f"{self.bot.itemName(item_id)}: {len(tiles)} tile -> "
                    + ", ".join(f"({t.x},{t.y})" for t in tiles[:20]))

    def _cmd_gscan(self, arg: str) -> None:
        hasil = self.bot.fitur.growscan.scan()
        baris = [f"{c['nama']} x{c['jumlah']}" for c in hasil["blok"][:15]]
        tanam = [f"{c['nama']} x{c['jumlah']}" for c in hasil["tanaman"][:15]]
        self._balas(
            f"growscan {hasil['world']} {hasil['ukuran']} · "
            f"{len(hasil['blok'])} jenis blok, {len(hasil['tanaman'])} jenis tanaman\n"
            f"blok: {', '.join(baris) or '-'}\n"
            f"tanam: {', '.join(tanam) or '-'}"
        )

    def _cmd_pullall(self, arg: str) -> None:
        if not self.bot.local:
            self._balas("bot belum di dunia")
            return
        x, y = self.bot.local.tile_x, self.bot.local.tile_y
        n = 0
        for p in self.bot.players.values():
            if p is self.bot.local:
                continue
            if self.bot.wrenchPlayer(p.netid):
                n += 1
        self._balas(f"pullall: {n} pemain ditarik ke ({x},{y})")

    def _cmd_kickall(self, arg: str) -> None:
        n = 0
        for p in self.bot.players.values():
            if p is self.bot.local:
                continue
            if p.tile_x is not None and self.bot.wrenchPlayer(p.netid):
                n += 1
        self._balas(f"kickall: {n} pemain")

    def _cmd_banall(self, arg: str) -> None:
        n = 0
        for p in self.bot.players.values():
            if p is self.bot.local:
                continue
            if self.bot.wrenchPlayer(p.netid):
                n += 1
        self._balas(f"banall: {n} pemain (butuh akses world)")

    def _cmd_alias(self, arg: str) -> None:
        bagian = arg.split(maxsplit=1)
        if len(bagian) < 2:
            self._balas("pakai: /alias <nama> <perintah>")
            return
        self.alias[bagian[0].lower()] = bagian[1]
        self._balas(f"alias {bagian[0]} -> {bagian[1]}")

    def _cmd_unalias(self, arg: str) -> None:
        if self.alias.pop(arg.lower(), None) is None:
            self._balas(f"alias tidak ada: {arg}")
        else:
            self._balas(f"alias {arg} dihapus")

    def _cmd_aliases(self, arg: str) -> None:
        if not self.alias:
            self._balas("belum ada alias")
            return
        self._balas("\n".join(f"/{k} -> {v}" for k, v in self.alias.items()))

    def info(self) -> dict[str, Any]:
        return {"aktif": dict(self.aktif), "alias": dict(self.alias),
                "riwayat_world": list(self.riwayat_world[-5:])}


# --------------------------------------------------------------------------- #
# Kumpulan fitur per bot + API untuk Lua
# --------------------------------------------------------------------------- #
class FiturBot:
    """Wadah semua fitur untuk satu Bot."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.autofarm = AutoFarm(bot)
        self.autocollect = AutoCollect(bot)
        self.spammer = Spammer(bot)
        self.path = PathFinder(bot)
        self.autodrop = AutoDrop(bot)
        self.replay = Replay(bot)
        self.growscan = Growscan(bot)
        self.commands = Commands(bot)

    def stop_semua(self) -> None:
        for f in (self.autofarm, self.autocollect, self.spammer,
                  self.autodrop, self.replay):
            try:
                f.stop()
            except Exception:  # noqa: BLE001
                pass

    def status(self) -> dict[str, Any]:
        return {
            "autofarm": self.autofarm.info(),
            "autocollect": self.autocollect.info(),
            "spammer": self.spammer.info(),
            "autodrop": self.autodrop.info(),
            "path": self.path.info(),
            "replay": self.replay.info(),
            "commands": self.commands.info(),
        }

    def lua_api(self) -> dict[str, Callable[..., Any]]:
        """Fungsi yang dipasang ke engine Lua (nama mengikuti deltaX)."""
        af, ac, sp, pa, ad = (self.autofarm, self.autocollect, self.spammer,
                              self.path, self.autodrop)
        rp, gs, cm = self.replay, self.growscan, self.commands
        return {
            # autofarm
            "autofarm_start": lambda **kw: af.start(
                float(kw["jeda"]) if "jeda" in kw else None
            ),
            "autofarm_stop": af.stop,
            "autofarm_status": af.info,
            "autofarm_atur": af.atur,
            "autofarm_set_tiles": af.set_tiles,
            "autofarm_set_seed": lambda i: setattr(af, "seed_id", int(i)) or af.seed_id,
            "autofarm_step": af.satu_siklus,
            "autofarm_buang": af.buang,
            # autocollect
            "autocollect_start": lambda **kw: ac.start(float(kw.get("jeda", 0.5))),
            "autocollect_stop": ac.stop,
            "autocollect_status": ac.info,
            "autocollect_set_radius": lambda r: setattr(ac, "radius", int(r)) or ac.radius,
            # spammer
            "spammer_start": sp.start,
            "spammer_stop": sp.stop,
            "spammer_status": sp.info,
            "spammer_add": sp.tambah,
            "spammer_clear": sp.bersihkan,
            "spammer_set_delay": lambda ms: setattr(sp, "delay", int(ms)) or sp.delay,
            # pathfinding
            "findpath_to": pa.jalan,
            "findpath_find": pa.cari,
            "findpath_item": lambda i: pa.terdekat_item(int(i)),
            "findpath_set_blockjump": lambda v: setattr(pa, "block_jump", bool(v)),
            "findpath_set_teleport": lambda v: setattr(pa, "teleport_path", bool(v)),
            # autodrop
            "autodrop_start": lambda **kw: ad.start(float(kw.get("jeda", 2.0))),
            "autodrop_stop": ad.stop,
            "autodrop_status": ad.info,
            "autodrop_set_mode": lambda m: setattr(ad, "mode", str(m)) or ad.mode,
            "autodrop_set_minimum": lambda n: setattr(ad, "minimum", int(n)) or ad.minimum,
            # replay
            "replay_record_start": rp.mulai_rekam,
            "replay_record_stop": rp.stop_rekam,
            "replay_play_start": rp.putar,
            "replay_stop": rp.stop,
            "replay_clear": rp.bersihkan,
            "replay_save": rp.simpan,
            "replay_load": rp.muat,
            "replay_files": rp.daftar_berkas,
            "replay_status": rp.info,
            # growscan
            "growscan": gs.scan,
            # perintah chat
            "command": cm.handle,
            "command_status": cm.info,
            # umum
            "features_stop_all": self.stop_semua,
            "features_status": self.status,
            "features_menu": lambda: dict(TILE_MENU),
        }


# --------------------------------------------------------------------------- #
# Skema panel: satu sumber untuk GUI (kiri = kategori, kanan = pengaturan)
# --------------------------------------------------------------------------- #
# Tiap kategori punya daftar kontrol. GUI menggambar kontrol sesuai `tipe`:
#   toggle  -> GtkSwitch
#   angka   -> spin button
#   teks    -> entry
#   pilihan -> combo (nilai ada di `opsi`)
#   item    -> entry ID item + pencarian nama
#   tile    -> entry "x,y x,y"
# Tiap kontrol menyebut `kunci` = nama atribut di objek fitur, jadi server
# tidak perlu tahu nama tombol deltaX.
SKEMA_FITUR: list[dict] = [
    {
        "nama": "Autofarm",
        "kategori": "automation",
        "fitur": "autofarm",
        "keterangan": "panen → tanam → ambil, berulang di tile sasaran",
        "kontrol": [
            {"kunci": "seed_id", "label": "Bibit yang ditanam (ID)", "tipe": "item"},
            {"kunci": "target_tiles", "label": "Tile sasaran", "tipe": "tile", "count": 5},
            {"kunci": "do_break", "label": "Boleh memecah", "tipe": "toggle"},
            {"kunci": "do_place", "label": "Boleh menanam", "tipe": "toggle"},
            {"kunci": "verify", "label": "Cek tile siap panen", "tipe": "toggle"},
            {"kunci": "verify_pos", "label": "Cek posisi pemain", "tipe": "toggle"},
            {"kunci": "verify_delay", "label": "Jeda setelah teleport (ms)", "tipe": "angka", "min": 1000, "maks": 10000, "langkah": 100},
            {"kunci": "punch_count", "label": "Hit count (pukulan per tile)", "tipe": "angka", "min": 1, "maks": 40, "langkah": 1},
            {"kunci": "punch_delay", "label": "Delay break (ms)", "tipe": "angka", "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": "place_delay", "label": "Delay place (ms)", "tipe": "angka", "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": "siklus_delay", "label": "Jeda antar siklus (ms)", "tipe": "angka", "min": 0, "maks": 60000, "langkah": 100},
            {"kunci": "faster", "label": "Overclock (potong jeda 40%)", "tipe": "toggle"},
            {"kunci": "show_punch", "label": "Kirim semua pukulan tanpa jeda", "tipe": "toggle"},
            {"kunci": "collect", "label": "Ambil objek saat memanen", "tipe": "toggle"},
            {"kunci": "collect_delay", "label": "Jeda ambil (ms)", "tipe": "angka", "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": "collect_radius", "label": "Radius ambil", "tipe": "angka", "min": 1, "maks": 15, "langkah": 1},
            {"kunci": "collect_block", "label": "Ikut ambil blok", "tipe": "toggle"},
            {"kunci": "collect_seed", "label": "Ikut ambil bibit", "tipe": "toggle"},
            {"kunci": "drop_aktif", "label": "Drop saat inventaris penuh", "tipe": "toggle"},
            {"kunci": "drop_minimum", "label": "Minimum sebelum drop", "tipe": "angka", "min": 0, "maks": 40000, "langkah": 10},
            {"kunci": "drop_x", "label": "Drop di X", "tipe": "angka", "min": 0, "maks": 200, "langkah": 1},
            {"kunci": "drop_y", "label": "Drop di Y", "tipe": "angka", "min": 0, "maks": 200, "langkah": 1},
            {"kunci": "drop_world", "label": "Dunia tujuan drop", "tipe": "teks"},
            {"kunci": "drop_mode", "label": "Cara buang", "tipe": "pilihan", "opsi": ["drop", "trash"]},
            {"kunci": "pick_aktif", "label": "Ambil item di dunia lain", "tipe": "toggle"},
            {"kunci": "pick_world", "label": "Dunia sumber pick", "tipe": "teks"},
            {"kunci": "pick_mode", "label": "Mode pick", "tipe": "pilihan", "opsi": ["nearest", "all"]},
        ],
    },
    {
        "nama": "Auto Collect",
        "kategori": "collect",
        "fitur": "autocollect",
        "keterangan": "ambil objek jatuh di sekitar bot",
        "kontrol": [
            {"kunci": "mode", "label": "Mode ambil", "tipe": "pilihan", "opsi": ["Radius", "Tile"]},
            {"kunci": "radius", "label": "Radius auto collect", "tipe": "angka", "min": 1, "maks": 11, "langkah": 1},
            {"kunci": "tiles", "label": "Tile collect", "tipe": "tile", "count": 11},
            {"kunci": "item_id", "label": "Hanya item ini (ID, 0 = semua)", "tipe": "item"},
            {"kunci": "delay", "label": "Delay (ms)", "tipe": "angka", "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": "faster", "label": "Fast take", "tipe": "toggle"},
            {"kunci": "check", "label": "Check before take", "tipe": "toggle"},
            {"kunci": "jeda", "label": "Jeda antar siklus (detik)", "tipe": "pecahan", "min": 0, "maks": 30, "langkah": 0.05},
        ],
    },
    {
        "nama": "Spammer",
        "kategori": "spammer",
        "fitur": "spammer",
        "keterangan": "kirim teks berulang ke dunia",
        "kontrol": [
            {"kunci": "delay", "label": "Jeda antar pesan (ms)", "tipe": "angka", "min": 100, "maks": 60000, "langkah": 100},
            {"kunci": "shuffle", "label": "Acak urutan teks", "tipe": "toggle"},
            {"kunci": "teks", "label": "Daftar teks (satu per baris)", "tipe": "teks_panjang"},
        ],
    },
    {
        "nama": "Auto Drop",
        "kategori": "autodrop",
        "fitur": "autodrop",
        "keterangan": "buang item saat inventaris melewati batas",
        "kontrol": [
            {"kunci": "minimum", "label": "Minimum to drop", "tipe": "angka", "min": 0, "maks": 4000, "langkah": 10},
            {"kunci": "mode", "label": "Cara buang", "tipe": "pilihan", "opsi": ["drop", "trash"]},
            {"kunci": "jeda", "label": "Jeda antar siklus (detik)", "tipe": "pecahan", "min": 0.2, "maks": 60, "langkah": 0.1},
            {"kunci": "world", "label": "Dunia tujuan buang", "tipe": "teks"},
            {"kunci": "x", "label": "Posisi X buang (0 = sekarang)", "tipe": "angka", "min": 0, "maks": 500, "langkah": 1},
            {"kunci": "y", "label": "Posisi Y buang (0 = sekarang)", "tipe": "angka", "min": 0, "maks": 500, "langkah": 1},
        ],
    },
    {
        "nama": "Path Finder",
        "kategori": "pathfinder",
        "fitur": "path",
        "keterangan": "cari jalan ke koordinat lalu tempuh",
        "kontrol": [
            {"kunci": "x", "label": "Tujuan X", "tipe": "angka", "min": 0, "maks": 500, "langkah": 1},
            {"kunci": "y", "label": "Tujuan Y", "tipe": "angka", "min": 0, "maks": 500, "langkah": 1},
            {"kunci": "block_jump", "label": "Tile padat = penghalang", "tipe": "toggle"},
            {"kunci": "teleport_path", "label": "Teleport per tile", "tipe": "toggle"},
            {"kunci": "jeda", "label": "Jeda antar langkah (detik)", "tipe": "pecahan", "min": 0, "maks": 2, "langkah": 0.02},
        ],
    },
    {
        "nama": "Replay",
        "kategori": "replay",
        "fitur": "replay",
        "keterangan": "rekam gerakan lalu putar ulang",
        "kontrol": [
            {"kunci": "rekam", "label": "Mulai rekam", "tipe": "tombol", "aksi": "record", "gaya": "primary"},
            {"kunci": "berhenti_rekam", "label": "Stop rekam", "tipe": "tombol", "aksi": "stop_record", "gaya": "ghost"},
            {"kunci": "putar", "label": "Putar rekaman", "tipe": "tombol", "aksi": "play", "gaya": "primary"},
            {"kunci": "berhenti", "label": "Stop putar", "tipe": "tombol", "aksi": "stop", "gaya": "ghost"},
            {"kunci": "simpan", "label": "Simpan ke berkas", "tipe": "tombol", "aksi": "save", "gaya": "ghost"},
            {"kunci": "muat", "label": "Muat dari berkas", "tipe": "tombol", "aksi": "load", "gaya": "ghost"},
            {"kunci": "hapus", "label": "Hapus rekaman", "tipe": "tombol", "aksi": "clear", "gaya": "danger"},
            {"kunci": "file", "label": "Nama berkas", "tipe": "teks"},
            {"kunci": "loop", "label": "Ulang terus", "tipe": "toggle"},
            {"kunci": "custom_delay", "label": "Jeda khusus (ms)", "tipe": "angka", "min": 0, "maks": 60000, "langkah": 50},
        ],
    },
]


def skema_fitur() -> list[dict]:
    """Skema panel untuk GUI (kategori + kontrol + nilai sekarang)."""
    return SKEMA_FITUR
