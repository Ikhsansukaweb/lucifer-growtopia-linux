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
    "Automation",
    "AutoWrench",
    "ModExit",
    "Parameter",
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
# Jangkauan `tileChange`: klien asli menolak tile > 4 dari pemain.
JANGKAU_TILE = 4


def dalam_jangkau(bot: Bot, t: Tile, jangkau: int = JANGKAU_TILE) -> bool:
    if bot.local is None:
        return True
    cx, cy = bot.local.posx + 10, bot.local.posy + 15
    tx, ty = t.x * 32 + 16, t.y * 32 + 16
    return (tx - cx) ** 2 + (ty - cy) ** 2 <= (32 * jangkau) ** 2


def urut_baris(bot: Bot, tiles: list[Tile]) -> list[Tile]:
    """Urut KIRI -> KANAN lalu ATAS -> BOTTOM, seperti menyapu lahan.

    Versi lama mengurutkan berdasarkan jarak ke pemain, sehingga tile yang
    sudah dekat dipukul berulang sementara tile jauh tertinggal — hasilnya
    "break tidak urut" dan sebagian tile hanya kena sedikit pukulan.
    Urutan baris membuat tiap tile diselesaikan sekali lalu pindah ke
    tetangganya.
    """
    return sorted(tiles, key=lambda t: (t.y, t.x))


def urut_dekat(bot: Bot, tiles: list[Tile]) -> list[Tile]:
    return urut_baris(bot, tiles)


def dekati(bot: Bot, t: Tile, jangkau: int = JANGKAU_TILE) -> bool:
    """Apakah tile sasaran bisa dikerjakan dari posisi sekarang.

    Fungsi ini TIDAK menggerakkan bot. Versi lama memanggil `findPath` lalu
    `moveTo` di dalam loop otomasi, sehingga bot berjalan sendiri keliling
    dunia (dan sempat nyangkut di White Door saat baru masuk world). Gerakan
    harus datang dari user atau dari fitur PathFinder, bukan efek samping
    autofarm.
    """
    return dalam_jangkau(bot, t, jangkau)


class AutoFarm:
    """Auto tanam + panen, setara `autofarm_*` deltaX.

    Semua parameter di bawah mengikuti `assets/menu.json` deltaX (sub-kategori
    Automation/Autofarm), jadi tiap tombol di sana punya padanan di sini:

      autofarm_item_picker       block_id (break & place blok yang sama)
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
        # Autofarm = BREAK & PLACE blok. Satu kolom item saja (deltaX:
        # "Block to break"): blok yang dipecah, dan blok yang sama ditaruh
        # kembali. Tanam/panen tanaman ada di Automation.
        self.block_id = 0
        self.block_mode = "auto"
        self.target_tiles: list[tuple[int, int]] = []
        self.debug = False
        self.verify_debug = False

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
        self.dipeeah_total = 0
        self.ditaruh_total = 0
        self.diambil_total = 0
        # Blok yang terakhir pecah; dipakai mode block_mode="auto" saat
        # menaruh lagi tanpa perlu isi id manual.
        self._blok_terakhir = 0
        # Tile yang baru dipecah siklus ini: satu-satunya tempat menaruh blok.
        self._baru_kosong: set[tuple[int, int]] = set()
        # Kesalahan siklus terakhir (dulu ditelan `except: pass`).
        self.error_terakhir = ""
        self._s = _Siklus("autofarm")

    # -- sasaran --------------------------------------------------------- #
    def atur(self, **kw) -> dict[str, Any]:
        """Set parameter sekaligus, nama kunci = alias deltaX tanpa `autofarm_`.

        Dipakai dashboard & Lua supaya tidak perlu satu method per tombol:

            af.atur(block_id=2, punch_count=3, punch_delay=120, faster=True,
                    do_place=False, collect=False, drop_aktif=True)

        Kunci tak dikenal diabaikan (bukan error) supaya skrip lama tetap jalan.
        """
        peta = {
            "block_id": "block_id",
            "item_picker": "block_id",
            "block_mode": "block_mode",
            "debug": "debug",
            "verify_debug": "verify_debug",
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
            elif nama in ("drop_mode", "drop_world", "pick_world", "pick_mode",
                          "block_mode"):
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

    def siap_pecah(self) -> list[Tile]:
        """Tile sasaran yang berisi BLOK siap dipecah (autofarm = break).

        Autofarm bekerja pada blok, bukan tanaman: tile dianggap sasaran bila
        `fg` terisi dan bukan tanaman (`is_seed`). Tanaman siap panen milik
        Automation. `block_mode="manual"` membatasi ke satu id blok.

        Saat `target_tiles` KOSONG, sasaran dibatasi ke tile dalam jangkauan
        pukul. Versi lama mengembalikan semua blok se-dunia (ribuan tile) dan
        bot berjalan mencari semuanya.
        """
        out = []
        for t in self.tiles_sasaran():
            if t.fg == 0 or t.is_seed:
                continue
            # Mode "auto" tanpa id = semua blok. Jangan pukul pintu, sign,
            # lock, atau blok milik orang lain: server tetap menolak, tapi
            # paketnya spam dan bisa dianggap griefing.
            if t.extra_type in self.EXTRA_BUKAN_BLOK:
                continue
            if not self.bot.hasAccess(t.x, t.y):
                continue
            if (self.block_mode or "auto") == "manual" and self.block_id and t.fg != self.block_id:
                continue
            # SELALU batasi jangkauan, termasuk saat tile manual diisi.
            # Server menolak `tileChange` di luar 4 tile tanpa memberi kabar
            # apa pun: paket terkirim, tidak ada `TileApplyDamage` balik, dan
            # tile tidak pernah pecah. Versi lama hanya memfilter mode auto,
            # sehingga target manual yang jauh dipukul sia-sia selamanya.
            if not self._dalam_jangkau(t):
                continue
            out.append(t)
        return out

    def kosong(self) -> list[Tile]:
        """Tile sasaran bekas pecahan yang bisa ditanami/ditaruh blok lagi."""
        return [t for t in self.tiles_sasaran()
                if t.fg == 0 and t.bg != 0 and self.bot.hasAccess(t.x, t.y)]

    def kosong_siklus(self) -> list[Tile]:
        """Tile yang boleh ditaruh blok: bekas pecah siklus ini, atau manual.

        `kosong()` mengembalikan SEMUA tile kosong di dunia; kalau dipakai
        untuk menaruh, autofarm menanam blok di sembarang tempat dan
        inventory habis. Jadi taruh dibatasi ke tile yang baru dipecah.

        Tile yang BARU dipukul siklus ini tetap dianggap sasaran walau
        `world` masih mencatat `fg != 0`: klien asli (lihat
        `automation.lua` deltaX) tidak menunggu konfirmasi `SendTileUpdateData`
        sebelum menanam lagi — server yang memutuskan. Menunggu konfirmasi
        membuat bot tidak pernah menaruh apa pun saat server tidak mengirim
        pembaruan tile.
        """
        w = self.bot.world
        # JANGAN pakai `target_tiles` sebagai cadangan. Itu membuat bot
        # menaruh blok di tile yang BELUM pernah dipecah siklus ini — dan
        # kalau tile itu masih berisi blok, paket place ditolak server
        # sementara hitungan `ditaruh_total` tetap naik.
        out = []
        posisi = set(self._baru_kosong)
        # Tile sasaran yang MEMANG kosong dari awal juga harus ditaruh.
        # Kalau tidak, autofarm tidak pernah mulai di lahan yang belum ada
        # bloknya: `_baru_kosong` hanya terisi setelah ada blok yang pecah,
        # jadi bot menunggu selamanya.
        posisi |= set(self.target_tiles)
        for x, y in posisi:
            t = w.tile(x, y)
            if t is None or not self.bot.hasAccess(x, y):
                continue
            if t.fg == 0:
                out.append(t)
        return out

    # Jangkauan pukul: server menolak `tileChange` di luar 4 tile dari pemain
    # (klien asli: `isInside(player.pos+10/+15, 32*4, tile*32+16)`). Autofarm
    # wajib mendekat dulu, bukan memukul seluruh dunia.
    JANGKAU = JANGKAU_TILE

    # extra_type yang bukan blok biasa: sign(1), door(2), lock(3), mailbox(6),
    # bulletin(7), donation box(12). Jangan dipecah autofarm.
    EXTRA_BUKAN_BLOK = (1, 2, 3, 6, 7, 12)

    def _dalam_jangkau(self, t: Tile) -> bool:
        return dalam_jangkau(self.bot, t, self.JANGKAU)

    def _sasaran_jauh(self) -> list[Tile]:
        """Sasaran yang ada tapi belum terjangkau dari posisi sekarang."""
        w = self.bot.world
        posisi = list(self.target_tiles)
        out = []
        for x, y in posisi:
            t = w.tile(x, y)
            if t is None or t.fg == 0 or t.is_seed:
                continue
            if (self.block_mode or "auto") == "manual" and self.block_id and t.fg != self.block_id:
                continue
            if t.extra_type in self.EXTRA_BUKAN_BLOK:
                continue
            if not self._dalam_jangkau(t):
                out.append(t)
        return out

    def _hampiri_jika_jauh(self) -> bool:
        """Jalan ke dekat sasaran terjauh yang belum terjangkau.

        Dipanggil di awal `pecah()`. Tanpa ini, tile manual yang jauh tidak
        akan pernah pecah: paket terkirim tapi ditolak server diam-diam.
        """
        jauh = self._sasaran_jauh()
        if not jauh:
            return False
        b = self.bot
        if b.local is None:
            return False
        t = urut_baris(b, jauh)[0]
        batas = self.JANGKAU - 1
        dx = max(-batas, min(batas, t.x - b.local.tile_x))
        dy = max(-batas, min(batas, t.y - b.local.tile_y))
        if dx == 0 and dy == 0:
            return False
        b.moveTo(dx, dy)
        return self._dalam_jangkau(t)

    def _urut_dekat(self, tiles: list[Tile]) -> list[Tile]:
        return urut_dekat(self.bot, tiles)

    def _dekati(self, t: Tile) -> bool:
        return dekati(self.bot, t, self.JANGKAU)

    # Berapa lama menunggu `TileApplyDamage` untuk satu pukulan (detik).
    # Satu RTT ke server Growtopia ~0,3-1 detik; 1,5 detik cukup longgar.
    TUNGGU_ACK = 1.5
    # Berapa kali berturut-turut tanpa ack sebelum blok dianggap pecah.
    MANDDEK_TOLERAN = 2

    # Berapa lama menunggu balasan server untuk satu pukulan (detik).
    TUNGGU_ACK = 2.0

    def _pukul_sekali_tunggu_ack(self, t: Tile) -> str:
        """Kirim SATU pukulan, tunggu balasan server.

        Mengembalikan:
          "pecah"  -> server meng-echo type=3 value=18 (blok pecah)
          "terima" -> server kirim TileApplyDamage (pukulan diterima, blok ada)
          "diam"   -> tidak ada balasan dalam batas waktu
        """
        b = self.bot
        b.reset_aksi(t.x, t.y)
        sebelum = b.hit_count(t.x, t.y)
        b.hit(t.x, t.y)
        t0 = time.time()
        while time.time() - t0 < self.TUNGGU_ACK:
            if self._s._stop.is_set() or b.status != BotStatus.online:
                return "diam"
            # Konfirmasi PECAH: server meng-echo type=3 value=18 untuk tile ini.
            if b.break_diterima(t.x, t.y):
                return "pecah"
            # Pukulan diterima, blok masih ada.
            if b.hit_count(t.x, t.y) > sebelum:
                return "terima"
            if _tunggu(self._s._stop, 0.05):
                return "diam"
        return "diam"

    def _pukul_sampai_pecah(self, t: Tile) -> bool:
        """Pukul sampai server MENGONFIRMASI blok pecah.

        Satu-satunya bukti yang dipakai: echo `TileChangeRequest` dengan
        `value == 18` untuk tile ini (server mengirimnya saat blok pecah).
        Butuh berapa pukulan pun, tidak masalah — bot menunggu balasan tiap
        pukulan, jadi laju kirim otomatis mengikuti server.

        `TileApplyDamage` hanya berarti "pukulan diterima, blok masih ada".
        Tidak ada tebakan jumlah pukulan, tidak ada pengosongan peta lokal.
        """
        b = self.bot
        batas = 60          # pengaman mutlak; bukan target
        for _ in range(batas):
            if self._s._stop.is_set() or b.status != BotStatus.online:
                return False
            if not self._dalam_jangkau(t):
                return False
            if b.break_diterima(t.x, t.y):
                return True

            hasil = self._pukul_sekali_tunggu_ack(t)
            if hasil == "pecah":
                return True
            if hasil == "diam":
                # Server tidak menjawab apa pun. Jangan mengarang: berhenti.
                return False
        return b.break_diterima(t.x, t.y)

    # -- jeda ------------------------------------------------------------- #
    # Server Growtopia membatasi laju `TileChangeRequest`. Bukti dari jurnal
    # paket: 8 pukulan dalam ~1,5 detik hanya menghasilkan 2 `TileApplyDamage`
    # — sisanya dibuang diam-diam. Jeda di bawah nilai ini percuma: paket
    # terkirim tapi tidak diproses.
    JEDA_MIN_PUKUL_MS = 300

    def _jeda(self, ms: float) -> float:
        """Terapkan `faster` ke jeda, tapi TIDAK untuk pukul/taruh.

        `faster` (overclock) memotong jeda 40%. Untuk `TileChangeRequest` itu
        membuat laju melebihi batas server, sehingga mayoritas paket dibuang
        dan siklus justru jadi lebih lambat (banyak pukulan sia-sia).
        """
        nilai = float(ms)
        if self.faster:
            nilai *= 0.6
        return nilai / 1000.0

    def _jeda_aksi(self, ms: float) -> float:
        """Jeda khusus pukul/taruh, dengan batas bawah aman dari server.

        `faster` sengaja TIDAK diterapkan di sini: memotong jeda aksi membuat
        paket dibuang server, dan siklus jadi lebih lambat karena banyak
        pukulan sia-sia.
        """
        nilai = max(float(ms), float(self.JEDA_MIN_PUKUL_MS))
        return nilai / 1000.0

    # -- aksi -------------------------------------------------------------- #
    def pecah(self) -> int:
        """Pukul blok sampai pecah (autofarm_do_break)."""
        if not self.do_break:
            return 0
        # Masuk jangkauan dulu kalau sasaran masih jauh (maks 3 langkah per
        # panggilan supaya tidak menggantung di tempat terhalang).
        for _ in range(3):
            if not self._hampiri_jika_jauh():
                break
        n = 0
        for t in self._urut_dekat(self.siap_pecah()):
            if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                break
            if not self._dalam_jangkau(t):
                continue
            # Ingat blok apa yang pecah: mode "auto" memakainya lagi saat
            # menaruh, jadi tidak perlu isi id blok manual.
            self._blok_terakhir = t.fg
            if not self._pukul_sampai_pecah(t):
                # Belum pecah: JANGAN masuk daftar taruh. Menaruh di atas blok
                # yang masih utuh = paket ditolak dan blok berikutnya tidak
                # pernah diproses.
                continue
            self._baru_kosong.add((t.x, t.y))
            n += 1
            self.dipeeah_total += 1
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

    # Berapa pukulan tanpa ack sebelum dianggap "sedang diproses server".
    # Nilai ini BUKAN jumlah pukulan untuk memecah blok — hanya batas sabar.
    SABAR_ACK = 3

    def _tunggu_konfirmasi_place(self, x: int, y: int, item: int,
                                 batas_detik: float = 2.0) -> str:
        """Tunggu server menyatakan place BERHASIL.

        Konfirmasi = echo `TileChangeRequest` dengan `value == item` di tile
        yang sama (terbukti ada di jurnal paket: `in netid=13 value=2`).

        Mengembalikan "ok" | "tolak" | None (belum ada kabar).
        """
        b = self.bot
        t0 = time.time()
        while time.time() - t0 < batas_detik:
            if self._s._stop.is_set() or b.status != BotStatus.online:
                return None
            # Peta lokal sudah berisi item ini -> server menyatakan terpasang.
            t = b.world.tile(x, y)
            if (t is not None and t.fg == item) or b.place_diterima(x, y, item):
                b.bersihkan_aksi(x, y)
                return "ok"
            if b.place_ditolak(x, y, item):
                b.bersihkan_aksi(x, y)
                return "tolak"
            if _tunggu(self._s._stop, 0.05):
                return None
        return None

    def taruh(self) -> int:
        """Taruh blok SATU PER SATU, tunggu konfirmasi server tiap tile.

        Tidak ada spam: satu `place` dikirim, lalu menunggu echo
        `TileChangeRequest` untuk tile itu. Kalau server menolak, tile
        dilewati (tidak diulang terus). Kalau tidak ada kabar sama sekali
        dalam 2 detik, tile dilewati juga — lebih baik lanjut ke tile lain
        daripada mengulang paket yang tak pernah diproses.
        """
        blok = self.block_id or self._blok_terakhir
        if not self.do_place or not blok:
            return 0
        n = 0
        for t in self._urut_dekat(self.kosong_siklus()):
            if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                break
            if self.bot.inventory.getItemCount(blok) <= 0:
                break
            if not self._dalam_jangkau(t) and not self._hampiri_jika_jauh():
                continue
            if not self._dalam_jangkau(t):
                continue

            self.bot.reset_aksi(t.x, t.y)
            self.bot.place(t.x, t.y, blok)
            hasil = self._tunggu_konfirmasi_place(t.x, t.y, blok)
            if hasil == "ok":
                self._baru_kosong.discard((t.x, t.y))
                n += 1
                self.ditaruh_total += 1
            else:
                # "tolak" / None: jangan ulangi tile ini di siklus yang sama.
                self._baru_kosong.discard((t.x, t.y))
            if _tunggu(self._s._stop, self._jeda_aksi(self.place_delay)):
                break
        return n

    def buang(self) -> int:
        """Drop/trash item yang melewati `drop_minimum` (autofarm_autodrop_*)."""
        if not self.drop_aktif:
            return 0
        inv = self.bot.inventory
        n = 0
        target = self.block_id if self.block_id else 0
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
        """Satu putaran penuh: buang -> ambil -> pecah blok -> taruh blok.

        Ini break & place: blok dipecah lalu ditaruh lagi di tile yang sama.
        Tanam/panen tanaman ada di :class:`Automation`.
        """
        # Urutan penting: blok yang baru pecah langsung diambil (dijatuhkan
        # tepat di tile itu), baru ditaruh lagi. Kalau diambil lebih dulu,
        # hasil pecahan baru terambil satu siklus kemudian.
        # Pecah harus TUNTAS dulu: kalau `taruh()` jalan sementara masih ada
        # blok yang belum pecah, bot memindahkan blok yang sama bolak-balik
        # dan tile yang belum selesai tertinggal. Ulangi `pecah()` sampai
        # tidak ada sasaran tersisa (maks 8 putaran supaya tidak menggantung).
        dibuang = self.buang()
        # Reset daftar "baru pecah" SEKALI per siklus. Kalau direset di dalam
        # `pecah()` (yang dipanggil berulang), tile yang sudah pecah di
        # putaran sebelumnya hilang dari daftar dan tidak pernah ditaruh lagi.
        self._baru_kosong = set()

        # Kalau di tile sasaran SUDAH ada blok yang kita farm, langsung mode
        # BREAK. Jangan menaruh blok baru di atas blok yang ada: paket place
        # akan ditolak server dan siklus jadi lambat.
        if self.do_break and self.siap_pecah():
            # lompat langsung ke tahap pecah (lewati place di siklus ini)
            dipecah = 0
            for _ in range(3):
                n = self.pecah()
                dipecah += n
                if n == 0:
                    break
            diambil = self.ambil()
            hasil = {
                "dibuang": dibuang,
                "dipecah": dipecah,
                "diambil": diambil,
                "ditaruh": self.taruh(),
            }
            self.siklus.append(hasil["dipecah"] + hasil["ditaruh"])
            return hasil
        dipecah = 0
        for _ in range(3):
            n = self.pecah()
            dipecah += n
            if n == 0:
                break
        diambil = self.ambil()
        hasil = {
            "dibuang": dibuang,
            "dipecah": dipecah,
            "diambil": diambil,
            "ditaruh": self.taruh(),
        }
        self.siklus.append(hasil["dipecah"] + hasil["ditaruh"])
        return hasil

    # -- loop -------------------------------------------------------------- #
    def start(self, jeda: float | None = None) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        if not self.bot.world.tiles:
            raise FeatureError("dunia belum termuat — masuk world dulu")
        if self.do_place and self.block_mode == "manual" and not self.block_id:
            raise FeatureError("block_id belum diset (autofarm_item_picker)")

        bila_none = self.siklus_delay / 1000.0
        self._s = _Siklus("autofarm", aktif=True)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    self.satu_siklus()
                except Exception as e:  # noqa: BLE001
                    # JANGAN telan diam-diam: tanpa jejak, "sekali jalan lalu
                    # diam" mustahil didiagnosis. Simpan kesalahan terakhir
                    # dan siarkan ke log/console.
                    self.error_terakhir = f"{type(e).__name__}: {e}"
                    try:
                        self.bot._emit("error", f"autofarm: {self.error_terakhir}")
                    except Exception:  # noqa: BLE001
                        pass
                    log.debug("autofarm siklus gagal: %s", e)
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
            "block_id": self.block_id,
            "block_mode": self.block_mode,
            "tiles": len(self.target_tiles),
            "siap_pecah": len(self.siap_pecah()) if self.bot.world.tiles else 0,
            "error": self.error_terakhir,
            "kosong": len(self.kosong()) if self.bot.world.tiles else 0,
            "siklus": len(self.siklus),
            "dipecah_total": self.dipeeah_total,
            "ditaruh_total": self.ditaruh_total,
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
        self.item_disable: list[int] = []   # collectfilter_itemdisabletake
        self.nilai = 0            # filter_collect_valuetake
        self.inventory_check = False
        self.debug_area = False
        self.debug = False
        self.aktif = False
        self.total = 0
        self._s = _Siklus("autocollect")

    def sekali(self) -> int:
        # Tile terpilih MENANG atas radius. `mode` default "Radius", jadi
        # kalau syaratnya `mode == "Tile"` pilihan tile user diabaikan dan
        # bot menyapu radius 3 tile — persis bug yang dilaporkan.
        pakai_tile = bool(self.tiles)
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
            if d.item_id in self.item_disable:
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
                "item_disable": list(self.item_disable), "nilai": self.nilai,
                "inventory_check": self.inventory_check,
                "debug_area": self.debug_area, "debug": self.debug,
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
        self.autodelay = False        # spammer_config_autodelay
        self.delay_long = 4000        # spammer_config_delay_long
        self.autocolor = False        # spammer_config_autocolor
        self.sendclient = False       # spammer_config_sendclient
        self.autoenter = False        # cheat_config_autoenter
        self.replay_after_enter = False   # spammer_replay_active
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

    def _warnai(self, teks: str) -> str:
        """`autocolor` = sisipkan kode warna acak di depan pesan."""
        if not self.autocolor:
            return teks
        warna = random.choice("0123456789abcdef")
        return f"`{warna}{teks}`0"

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
        ok = self.bot.say(self._warnai(teks))
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
                "delay": self.delay, "terkirim": self.terkirim,
                "autodelay": self.autodelay, "delay_long": self.delay_long,
                "autocolor": self.autocolor, "shuffle": self.shuffle}


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
        self.debug_paths = False
        self.current_loc = False
        self.overclock = False
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
        self.raw = False               # replay_record_active_raw
        self.text_packet = False       # replay_record_active_text
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
# Automation — tanam & panen berkelanjutan (`automation_*` deltaX)
# --------------------------------------------------------------------------- #
class Automation:
    """Tanam/panen otomatis terpisah dari AutoFarm.

    Bedanya dengan :class:`AutoFarm`: Autofarm = pecah **dan** tanam di tile
    pilihan (break + place). Automation = siklus tanam/panen di lahan sendiri,
    tile ditentukan otomatis dari isi dunia, dengan jeda tanam dan jeda panen
    terpisah seperti deltaX.

    Paket yang dipakai sama dengan AutoFarm (`hit`, `place`) — keduanya sudah
    terbukti diterima server, jadi kelas ini tidak menambah tebakan protokol.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.aktif = False
        self.item = 0                 # automation_item (bibit)
        self.mode = "Plant & Harvest"  # automation_mode
        self.safe_delay = True
        self.delay_plant = 250        # ms
        self.delay_harvest = 250      # ms
        self.antimiss = True
        self.start_from_bottom = False
        self.autocollect = True
        self.autodrop = False
        self.autodrop_minimum = 180
        self.autodrop_x = 0
        self.autodrop_y = 0
        self.autodrop_facing = "auto"
        self.autotake = False
        self.autotake_minimum = 1
        self.autosplice = False
        self.splice_item = 0
        self.autosplice_minimum_planted = 1
        self.debug = False
        self.smart_delay = True
        self.dipanen_total = 0
        self.ditanam_total = 0
        # Tile yang baru dipanen: satu-satunya tempat menanam bibit lagi.
        self._baru_kosong: set[tuple[int, int]] = set()
        self._s = _Siklus("automation")

    # -- lahan ------------------------------------------------------------ #
    def _tiles(self) -> list[Tile]:
        w = self.bot.world
        if not w.tiles:
            return []
        out = [t for t in w.tiles if t.bg != 0]
        # automation_start_from_bottom: kerjakan baris bawah dulu.
        if self.start_from_bottom:
            out.sort(key=lambda t: (-t.y, t.x))
        return out

    def siap_panen(self) -> list[Tile]:
        return [t for t in self._tiles() if t.is_seed and (t.ready or not self.antimiss)]

    def kosong(self) -> list[Tile]:
        return [t for t in self._tiles() if t.fg == 0 and t.bg != 0]

    def kosong_siklus(self) -> list[Tile]:
        """Hanya tile bekas panen siklus ini; kalau kosong, tidak menanam."""
        w = self.bot.world
        out = []
        for x, y in self._baru_kosong:
            t = w.tile(x, y)
            if t is not None and t.fg == 0 and t.bg != 0:
                out.append(t)
        return out

    # -- aksi -------------------------------------------------------------- #
    def panen(self) -> int:
        if self.mode == "Plant":
            return 0
        n = 0
        self._baru_kosong = set()
        for t in urut_dekat(self.bot, self.siap_panen()):
            if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                break
            if not dekati(self.bot, t):
                continue

            # Panen = pukul sampai server MENGONFIRMASI (echo `type=3
            # value=18`). Satu pukulan tidak cukup untuk tanaman yang butuh
            # beberapa hit, dan tanpa konfirmasi bot bisa lanjut menanam di
            # atas tanaman yang belum terpetik.
            if not self._pukul_sampai_pecah(t):
                continue
            self._baru_kosong.add((t.x, t.y))
            n += 1
            self.dipanen_total += 1
            if _tunggu(self._s._stop, self.delay_harvest / 1000.0):
                break
        return n

    def tanam(self) -> int:
        if self.mode == "Harvest":
            return 0
        if not self.item:
            raise FeatureError("automation_item belum diset")
        n = 0
        for t in urut_dekat(self.bot, self.kosong_siklus()):
            if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                break
            # Stok dibaca ulang tiap tile (server bisa menurunkan stok).
            if self.bot.inventory.getItemCount(self.item) <= 0:
                break
            if not dekati(self.bot, t):
                continue

            # Tanam SATU per satu, tunggu echo `type=3 value=<seed>` dari
            # server — bukti nyata dari klien asli:
            #   in type=3 netid=1 tile=(57,23) value=3(Dirt Seed) anim=4
            self.bot.reset_aksi(t.x, t.y)
            self.bot.place(t.x, t.y, self.item)
            t0 = time.time()
            berhasil = False
            while time.time() - t0 < 2.0:
                if self._s._stop.is_set() or self.bot.status != BotStatus.online:
                    break
                if self.bot.place_diterima(t.x, t.y, self.item):
                    berhasil = True
                    break
                if self.bot.place_ditolak(t.x, t.y, self.item):
                    break
                if _tunggu(self._s._stop, 0.05):
                    break
            self._baru_kosong.discard((t.x, t.y))
            if berhasil:
                n += 1
                self.ditanam_total += 1
            if _tunggu(self._s._stop, self.delay_plant / 1000.0):
                break
        return n

    def ambil(self) -> int:
        if not self.autocollect:
            return 0
        return self.bot.collect(range_=3, interval=0 if self.smart_delay else 120)

    # -- loop -------------------------------------------------------------- #
    def satu_siklus(self) -> dict[str, int]:
        """Satu putaran: panen -> ambil hasil -> tanam bibit."""
        panen = self.panen()
        ambil = self.ambil()
        tanam = self.tanam()
        return {"diambil": ambil, "dipanen": panen, "ditanam": tanam}

    def start(self, jeda: float | None = None) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        if not self.bot.world.tiles:
            raise FeatureError("dunia belum termuat — masuk world dulu")
        if self.mode != "Harvest" and not self.item:
            raise FeatureError("automation_item belum diset (item to farm)")
        self._s = _Siklus("automation", aktif=True)
        interval = 1.0 if jeda is None else float(jeda)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    self.satu_siklus()
                except Exception:  # noqa: BLE001
                    pass
                if _tunggu(self._s._stop, interval):
                    break
            self._s.aktif = False
            self.aktif = False

        self._s._thread = threading.Thread(target=loop, name="lucifer-automation", daemon=True)
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
        return {"aktif": self._s.aktif, "item": self.item, "mode": self.mode,
                "dipanen": self.dipanen_total, "ditanam": self.ditanam_total}


# --------------------------------------------------------------------------- #
# Auto Wrench — buka wrench pemain/tile terdekat berkala (`cheat_autowrench`)
# --------------------------------------------------------------------------- #
class AutoWrench:
    """Wrench otomatis. Paket: `TileActivateRequest` value=32 (wrench)."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.aktif = False
        self.enable = False
        self.mode = "Player"        # cheat_autowrench_mode: Player | Tile
        self.fastwrench = "Normal"  # cheat_fastwrench
        self.fastwrench_enable = False
        self.enhanced = False
        self.enable = False
        self.autowrench = False
        self.target_x = 0
        self.target_y = 0
        self.jeda = 1.0
        self.total = 0
        self._s = _Siklus("autowrench")

    def _target(self) -> Optional[tuple[int, int]]:
        if self.mode == "Tile":
            if self.target_x or self.target_y:
                return (self.target_x, self.target_y)
            if self.bot.local:
                return (self.bot.local.tile_x, self.bot.local.tile_y)
            return None
        # Player: pemain lain terdekat.
        me = self.bot.local
        if me is None:
            return None
        kandidat = [p for p in self.bot.players.values() if p.netid != me.netid]
        if not kandidat:
            return None
        dekat = min(kandidat, key=lambda p: (p.posx - me.posx) ** 2 + (p.posy - me.posy) ** 2)
        return (dekat.tile_x, dekat.tile_y)

    def sekali(self) -> bool:
        t = self._target()
        if t is None:
            return False
        ok = self.bot.wrench(t[0], t[1])
        if ok:
            self.total += 1
        return ok

    def start(self, jeda: float = 0) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        self._s = _Siklus("autowrench", aktif=True)
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

        self._s._thread = threading.Thread(target=loop, name="lucifer-autowrench", daemon=True)
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
        return {"aktif": self._s.aktif, "mode": self.mode, "total": self.total}


# --------------------------------------------------------------------------- #
# Moderator Exit — keluar cepat saat moderator masuk (`mod_exit_*` deltaX)
# --------------------------------------------------------------------------- #
class ModExit:
    """Drop item di posisi tetap lalu warp keluar saat moderator terdeteksi.

    Pendeteksian memakai daftar `bot.players` (nama + flag moderator). Karena
    server tidak selalu mengirim flag moderator, tombol Trigger di GUI juga
    memanggil :meth:`jalankan` secara manual.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.enable = False
        self.mode = "Drop & Exit"
        self.drop_world = ""
        self.drop_pos_x = 0
        self.drop_pos_y = 0
        self.donate_world = ""
        self.donate_player_pos_x = 0
        self.donate_player_pos_y = 0
        self.donate_pos_x = 0
        self.donate_pos_y = 0
        self.jeda = 1.0
        self.aktif = False
        self.terakhir = ""
        self._s = _Siklus("modexit")

    def moderator(self) -> list[str]:
        """Nama pemain yang ditandai moderator (kalau server mengirimnya)."""
        return [p.name or f"#{p.netid}" for p in self.bot.players.values()
                if (p.isModerator or p.isSuperModerator)
                and not p.isLocalPlayer]

    def jalankan(self, alasan: str = "manual") -> dict[str, Any]:
        """Aksi keluar: buang semua item lalu warp ke dunia drop."""
        b = self.bot
        dibuang = 0
        for item_id, it in list(b.inventory.items.items()):
            try:
                b.drop(item_id, it.count)
                dibuang += 1
            except Exception:  # noqa: BLE001
                pass
        keluar = False
        if self.drop_world:
            keluar = b.warp(self.drop_world)
        self.terakhir = alasan
        return {"ok": True, "alasan": alasan, "dibuang": dibuang,
                "warp": keluar, "moderator": self.moderator()}

    def start(self, jeda: float = 0) -> bool:
        if self._s.aktif:
            return True
        if self.bot.status != BotStatus.online:
            raise FeatureError("bot belum online — connect dulu")
        self._s = _Siklus("modexit", aktif=True)
        interval = float(jeda) if jeda else float(self.jeda)

        def loop() -> None:
            while not self._s._stop.is_set():
                try:
                    if self.moderator():
                        self.jalankan("moderator terdeteksi")
                        break
                except Exception:  # noqa: BLE001
                    pass
                if _tunggu(self._s._stop, interval):
                    break
            self._s.aktif = False
            self.aktif = False

        self._s._thread = threading.Thread(target=loop, name="lucifer-modexit", daemon=True)
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
        return {"aktif": self._s.aktif, "moderator": self.moderator(),
                "terakhir": self.terakhir}


# --------------------------------------------------------------------------- #
# Parameter saja — fitur yang paketnya belum terbukti
# --------------------------------------------------------------------------- #
class Parameter:
    """Wadah nilai form untuk fitur yang paketnya belum terbukti di server.

    Kenapa ada: mod menu harus punya bentuk yang sama dengan deltaX (semua
    kolom tersedia dan tersimpan), tapi mengirim paket tebakan ke Growtopia
    berisiko kick/ban. Jadi kelas ini hanya menyimpan parameter + status, dan
    menandai `didukung = False` supaya GUI menampilkan catatan.
    """

    didukung = False

    def __init__(self, bot: Bot, nama: str, **awal: Any) -> None:
        self.bot = bot
        self.nama = nama
        self.aktif = False
        self.catatan = "parameter tersimpan; paket ke server belum terbukti"
        for k, v in awal.items():
            setattr(self, k, v)

    def start(self, *a: Any, **kw: Any) -> bool:
        self.aktif = True
        return True

    def stop(self) -> None:
        self.aktif = False

    @property
    def berjalan(self) -> bool:
        return self.aktif

    def info(self) -> dict[str, Any]:
        return {"aktif": self.aktif, "didukung": self.didukung,
                "catatan": self.catatan}


# --------------------------------------------------------------------------- #
# Kumpulan fitur per bot + API untuk Lua
# --------------------------------------------------------------------------- #
class FiturBot:
    """Wadah semua fitur untuk satu Bot."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.autofarm = AutoFarm(bot)
        self.autocollect = AutoCollect(bot)
        self.automation = Automation(bot)
        self.autowrench = AutoWrench(bot)
        self.modexit = ModExit(bot)
        self.spammer = Spammer(bot)
        self.path = PathFinder(bot)
        self.autodrop = AutoDrop(bot)
        self.replay = Replay(bot)
        self.growscan = Growscan(bot)
        self.commands = Commands(bot)
        # Fishing / AutoCrime / Ghost / Copy Song: paketnya belum terbukti
        # diterima server, jadi hanya menyimpan parameter (lihat `Parameter`).
        self.fishing = Parameter(bot, "Fishing")
        self.autocrime = Parameter(bot, "AutoCrime")
        self.ghost = Parameter(bot, "Ghost")
        self.copysong = Parameter(bot, "Copy Song")
        # Kolom deltaX yang belum punya perilaku sendiri tetap disimpan supaya
        # form tidak kehilangan isian saat Simpan/Nyalakan.
        for fitur in ("spammer", "autofarm", "automation", "autocollect",
                      "fishing", "autocrime", "copysong", "ghost", "replay",
                      "autowrench", "modexit"):
            obj = getattr(self, fitur, None)
            if obj is None:
                continue
            for k, v in parameter_default(fitur).items():
                if not hasattr(obj, k):
                    setattr(obj, k, v)

    def stop_semua(self) -> None:
        for f in (self.autofarm, self.autocollect, self.automation,
                  self.autowrench, self.modexit, self.spammer,
                  self.autodrop, self.replay):
            try:
                f.stop()
            except Exception:  # noqa: BLE001
                pass

    def status(self) -> dict[str, Any]:
        return {
            "autofarm": self.autofarm.info(),
            "autocollect": self.autocollect.info(),
            "automation": self.automation.info(),
            "autowrench": self.autowrench.info(),
            "modexit": self.modexit.info(),
            "fishing": self.fishing.info(),
            "autocrime": self.autocrime.info(),
            "ghost": self.ghost.info(),
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
            "autofarm_set_block": lambda i: setattr(af, "block_id", int(i)) or af.block_id,
            # nama lama, dipertahankan supaya skrip yang sudah ada tetap jalan
            "autofarm_set_seed": lambda i: setattr(af, "block_id", int(i)) or af.block_id,
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
#   toggle  -> GtkSwitch      angka -> spin button    teks -> entry
#   pilihan -> combo          item  -> entry ID item  tile -> pemilih grid
#   tombol  -> tombol aksi (lihat `aksi`, ditangani web.py)
# `kunci` = nama atribut di objek fitur, jadi server tidak perlu tahu nama
# tombol deltaX. Daftar & urutannya mengikuti docs/deltax-fitur.json.
SKEMA_FITUR: list[dict] = [
    {
        "nama": 'Spammer',
        "kategori": 'Automation',
        "fitur": 'spammer',
        "keterangan": 'spam chat berulang',
        "kontrol": [
            {"kunci": 'delay', "label": 'Delay spam (ms)', "tipe": 'angka', "min": 100, "maks": 60000, "langkah": 100},
            {"kunci": 'autodelay', "label": 'Auto delay', "tipe": 'toggle'},
            {"kunci": 'delay_long', "label": 'Delay detected spam (ms)', "tipe": 'angka', "min": 500, "maks": 300000, "langkah": 500},
            {"kunci": 'autocolor', "label": 'Random Color', "tipe": 'toggle'},
            {"kunci": 'shuffle', "label": 'Random Order', "tipe": 'toggle'},
            {"kunci": 'sendclient', "label": 'Send to Client', "tipe": 'toggle'},
            {"kunci": 'texttospam', "label": 'Text to spam', "tipe": 'teks'},
            {"kunci": 'addtolist', "label": 'Add to list', "tipe": 'tombol', "aksi": 'add', "gaya": 'ghost'},
            {"kunci": 'clearlist', "label": 'Clear list', "tipe": 'tombol', "aksi": 'refresh', "gaya": 'ghost'},
            {"kunci": 'autoenter', "label": 'Auto Re-enter', "tipe": 'toggle'},
            {"kunci": 'active', "label": 'Auto replay after enter', "tipe": 'toggle'},
            {"kunci": 'actions', "label": 'Get all actions', "tipe": 'tombol', "aksi": 'ambil_aksi', "gaya": 'ghost'},
        ],
    },
    {
        "nama": 'Autofarm',
        "kategori": 'Automation',
        "fitur": 'autofarm',
        "keterangan": 'break & place: pecah blok lalu taruh blok yang sama',
        "kontrol": [
            {"kunci": 'block_id', "label": 'Block to break & place (ID)', "tipe": 'item'},
            {"kunci": 'block_mode', "label": 'Mode blok', "tipe": 'pilihan', "opsi": ['auto', 'manual']},
            {"kunci": 'target_tile', "label": 'Select tile to break', "tipe": 'tile', "count": 5},
            {"kunci": 'verify', "label": 'Verify before punch', "tipe": 'toggle'},
            {"kunci": 'do_break', "label": 'Break', "tipe": 'toggle'},
            {"kunci": 'do_place', "label": 'Place', "tipe": 'toggle'},
            {"kunci": 'punch_count', "label": 'Hit Count', "tipe": 'angka', "min": 1, "maks": 40, "langkah": 1},
            {"kunci": 'autopunch_delay', "label": 'Delay Break', "tipe": 'angka', "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": 'autoplace_delay', "label": 'Delay place', "tipe": 'angka', "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": 'debug', "label": 'Autofarm Debug', "tipe": 'toggle'},
            {"kunci": 'verify_pos', "label": 'Verify pos before continue', "tipe": 'toggle'},
            {"kunci": 'verify_debug', "label": 'Verify pos debug', "tipe": 'toggle'},
            {"kunci": 'verify_delay', "label": 'Delay after teleport', "tipe": 'angka', "min": 1000, "maks": 10000, "langkah": 100},
            {"kunci": 'config_overclock', "label": 'Faster break', "tipe": 'toggle'},
            {"kunci": 'config_showpunch', "label": 'Show punch', "tipe": 'toggle'},
            {"kunci": 'autocollect_start', "label": 'Auto collect', "tipe": 'toggle'},
            {"kunci": 'autocollect_delay', "label": 'Delay', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'autocollect_block', "label": 'Collect block', "tipe": 'toggle'},
            {"kunci": 'autocollect_seed', "label": 'Collect seed', "tipe": 'toggle'},
            {"kunci": 'autocollect_debug', "label": 'Debug', "tipe": 'toggle'},
            {"kunci": 'autodrop_start', "label": 'Auto drop', "tipe": 'toggle'},
            {"kunci": 'autodrop_minimum', "label": 'Minimum to drop', "tipe": 'angka', "min": 0, "maks": 40000, "langkah": 10},
            {"kunci": 'autodrop_x', "label": 'Position x block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'autodrop_y', "label": 'Position y block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'autodrop_current_pos', "label": 'Current position', "tipe": 'tombol', "aksi": 'pos', "gaya": 'ghost'},
            {"kunci": 'autodrop_worldname', "label": 'World to drop', "tipe": 'teks'},
            {"kunci": 'autodrop_worldname_current', "label": 'Current world', "tipe": 'tombol', "aksi": 'aksi', "gaya": 'ghost'},
            {"kunci": 'autopick_enable', "label": 'Auto pick', "tipe": 'toggle'},
            {"kunci": 'autopick_world', "label": 'World to pick', "tipe": 'teks'},
            {"kunci": 'autopick_world_current', "label": 'Current world', "tipe": 'tombol', "aksi": 'world', "gaya": 'ghost'},
            {"kunci": 'autopick_mode', "label": 'Auto pick mode', "tipe": 'pilihan', "opsi": ['nearest', 'all']},
        ],
    },
    {
        "nama": 'Automation',
        "kategori": 'Automation',
        "fitur": 'automation',
        "keterangan": 'harvest & plant: panen tanaman lalu tanam bibit',
        "kontrol": [
            {"kunci": 'item', "label": 'Item to farm', "tipe": 'item'},
            {"kunci": 'autocollect', "label": 'Enable Auto Collect', "tipe": 'toggle'},
            {"kunci": 'mode', "label": 'Mode', "tipe": 'pilihan', "opsi": ['Plant & Harvest', 'Plant', 'Harvest']},
            {"kunci": 'safe_delay', "label": 'Safe delay', "tipe": 'toggle'},
            {"kunci": 'delay_plant', "label": 'Delay plant (ms)', "tipe": 'angka', "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": 'delay_harvest', "label": 'Delay harvest (ms)', "tipe": 'angka', "min": 0, "maks": 5000, "langkah": 10},
            {"kunci": 'antimiss', "label": 'Anti Miss', "tipe": 'toggle'},
            {"kunci": 'start_from_bottom', "label": 'Start from bottom', "tipe": 'toggle'},
            {"kunci": 'autodrop', "label": 'Enable Auto Drop', "tipe": 'toggle'},
            {"kunci": 'autodrop_minimum', "label": 'Minimum to drop', "tipe": 'angka', "min": 0, "maks": 40000, "langkah": 10},
            {"kunci": 'autodrop_x', "label": 'Drop position X', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'autodrop_y', "label": 'Drop position Y', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'autodrop_current_pos', "label": 'Current position', "tipe": 'tombol', "aksi": 'pos', "gaya": 'ghost'},
            {"kunci": 'autodrop_facing', "label": 'Facing when drop', "tipe": 'pilihan', "opsi": ['A', 'B']},
            {"kunci": 'autotake', "label": 'Enable Auto Take', "tipe": 'toggle'},
            {"kunci": 'autotake_minimum', "label": 'Minimum to take', "tipe": 'angka', "min": 0, "maks": 40000, "langkah": 1},
            {"kunci": 'autosplice', "label": 'Enable Auto Splice', "tipe": 'toggle'},
            {"kunci": 'splice_item', "label": 'Item to splice', "tipe": 'item'},
            {"kunci": 'autosplice_minimum_planted', "label": 'Minimum planted before splice', "tipe": 'angka', "min": 0, "maks": 40000, "langkah": 1},
            {"kunci": 'debug', "label": 'Automation Debug', "tipe": 'toggle'},
            {"kunci": 'smart_delay', "label": 'Smart Delay', "tipe": 'toggle'},
        ],
    },
    {
        "nama": 'Auto Collect',
        "kategori": 'Automation',
        "fitur": 'autocollect',
        "keterangan": 'ambil objek jatuh di sekitar',
        "kontrol": [
            {"kunci": 'itemtotake', "label": 'Item', "tipe": 'item'},
            {"kunci": 'valuetake', "label": 'Specified value', "tipe": 'angka', "min": 0, "maks": 40000, "langkah": 1},
            {"kunci": 'itemdisabletake', "label": 'Item', "tipe": 'item'},
            {"kunci": 'delay', "label": 'Delay', "tipe": 'angka', "min": 100, "maks": 60000, "langkah": 100},
            {"kunci": 'faster', "label": 'Fast take', "tipe": 'toggle'},
            {"kunci": 'check', "label": 'Check before take', "tipe": 'toggle'},
            {"kunci": 'inventory_check', "label": 'Inventory check', "tipe": 'toggle'},
            {"kunci": 'debug_area', "label": 'Debug area', "tipe": 'toggle'},
            {"kunci": 'debug', "label": 'Debug take', "tipe": 'toggle'},
            {"kunci": 'mode', "label": 'Auto collect mode', "tipe": 'pilihan', "opsi": ['Radius', 'Tile']},
            {"kunci": 'radius', "label": 'Radius auto collect', "tipe": 'angka', "min": 1, "maks": 15, "langkah": 1},
            {"kunci": 'tile', "label": 'Select tile to collect', "tipe": 'tile', "count": 5},
        ],
    },
    {
        "nama": 'Fishing',
        "kategori": 'Automation',
        "fitur": 'fishing',
        "keterangan": 'mancing otomatis (parameter saja)',
        "kontrol": [
            {"kunci": 'config_bait', "label": 'Bait', "tipe": 'item'},
            {"kunci": 'config_delay', "label": 'Delay after catch', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'config_direct', "label": 'Direction', "tipe": 'pilihan', "opsi": ['A', 'B']},
            {"kunci": 'config_delaymode', "label": 'Delay after trigger mode', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'config_minimum_to_move', "label": 'Minimum items in front to move', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'autoteleport', "label": 'Auto teleport back', "tipe": 'toggle'},
            {"kunci": 'automove', "label": 'Auto move', "tipe": 'toggle'},
            {"kunci": 'action_catch', "label": 'Action after catch', "tipe": 'pilihan', "opsi": ['Auto', 'None']},
            {"kunci": 'action_catch_filter', "label": 'Filter Action', "tipe": 'pilihan', "opsi": ['All', 'Fish', 'Junk']},
            {"kunci": 'action_enable', "label": 'Enable Action', "tipe": 'toggle'},
        ],
    },
    {
        "nama": 'AutoCrime',
        "kategori": 'Automation',
        "fitur": 'autocrime',
        "keterangan": 'mode crime (parameter saja)',
        "kontrol": [
            {"kunci": 'is_active', "label": 'AutoCrime', "tipe": 'toggle'},
        ],
    },
    {
        "nama": 'Copy Song',
        "kategori": 'Automation',
        "fitur": 'copysong',
        "keterangan": 'salin lagu dunia (parameter saja)',
        "kontrol": [
            {"kunci": 'place_mode', "label": 'Automation mode', "tipe": 'pilihan', "opsi": ['Normal', 'Fast']},
            {"kunci": 'debug', "label": 'Debug', "tipe": 'toggle'},
            {"kunci": 'filename', "label": 'Filename', "tipe": 'teks'},
            {"kunci": 'filename_current', "label": 'Current world', "tipe": 'tombol', "aksi": 'aksi', "gaya": 'ghost'},
            {"kunci": 'filename_add', "label": 'Add', "tipe": 'tombol', "aksi": 'add', "gaya": 'ghost'},
            {"kunci": 'file_refresh', "label": 'Refresh', "tipe": 'tombol', "aksi": 'refresh', "gaya": 'ghost'},
            {"kunci": 'refresh_required', "label": 'Refresh required', "tipe": 'tombol', "aksi": 'refresh', "gaya": 'ghost'},
            {"kunci": 'start_copy', "label": 'Copy world song', "tipe": 'tombol', "aksi": 'mulai', "gaya": 'ghost'},
        ],
    },
    {
        "nama": 'Ghost',
        "kategori": 'Automation',
        "fitur": 'ghost',
        "keterangan": 'ghost/npc (parameter saja)',
        "kontrol": [
            {"kunci": 'cheat_auto_esp_ghost', "label": 'Auto Punch Ghost', "tipe": 'toggle'},
            {"kunci": 'show_punch', "label": 'Show Punch', "tipe": 'toggle'},
            {"kunci": 'jar', "label": 'Auto put jar', "tipe": 'toggle'},
            {"kunci": 'config_radius', "label": 'Search Radius', "tipe": 'angka', "min": 0, "maks": 100, "langkah": 1},
            {"kunci": 'config_min_in_radius', "label": 'Minimum ghost stay before put jar', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'debug', "label": 'Debug', "tipe": 'toggle'},
            {"kunci": 'debug_distance', "label": 'Show Distance', "tipe": 'toggle'},
            {"kunci": 'debug_target', "label": 'Show Target', "tipe": 'toggle'},
            {"kunci": 'debug_line', "label": 'Show Line', "tipe": 'toggle'},
            {"kunci": 'debug_state', "label": 'Show Ghost State', "tipe": 'toggle'},
            {"kunci": 'debug_type', "label": 'Show Ghost Type', "tipe": 'toggle'},
            {"kunci": 'debug_circle', "label": 'Show Radius Rectangle', "tipe": 'toggle'},
            {"kunci": 'cheat_esp_ghost', "label": 'Esp Ghost', "tipe": 'toggle'},
            {"kunci": 'auto_teleport', "label": 'Auto Teleport', "tipe": 'toggle'},
            {"kunci": 'normal', "label": 'Normal Ghost', "tipe": 'toggle'},
            {"kunci": 'mind', "label": 'Mind Ghost', "tipe": 'toggle'},
            {"kunci": 'winter', "label": 'Winter Ghost', "tipe": 'toggle'},
        ],
    },
    {
        "nama": 'Auto Drop',
        "kategori": 'World',
        "fitur": 'autodrop',
        "keterangan": 'buang item saat inventaris melewati batas',
        "kontrol": [
            {"kunci": 'minimum', "label": 'Minimum to drop', "tipe": 'angka', "min": 0, "maks": 40000, "langkah": 10},
            {"kunci": 'mode', "label": 'Cara buang', "tipe": 'pilihan', "opsi": ['drop', 'trash']},
            {"kunci": 'jeda', "label": 'Jeda antar siklus (detik)', "tipe": 'pecahan', "min": 0.2, "maks": 60, "langkah": 0.1},
            {"kunci": 'world', "label": 'Dunia tujuan buang', "tipe": 'teks'},
            {"kunci": 'x', "label": 'Posisi X buang (0 = sekarang)', "tipe": 'angka', "min": 0, "maks": 500, "langkah": 1},
            {"kunci": 'y', "label": 'Posisi Y buang (0 = sekarang)', "tipe": 'angka', "min": 0, "maks": 500, "langkah": 1},
        ],
    },
    {
        "nama": 'Path Finder',
        "kategori": 'World',
        "fitur": 'path',
        "keterangan": 'cari jalan ke koordinat lalu tempuh',
        "kontrol": [
            {"kunci": 'x', "label": 'Tujuan X', "tipe": 'angka', "min": 0, "maks": 500, "langkah": 1},
            {"kunci": 'y', "label": 'Tujuan Y', "tipe": 'angka', "min": 0, "maks": 500, "langkah": 1},
            {"kunci": 'block_jump', "label": 'Tile padat = penghalang', "tipe": 'toggle'},
            {"kunci": 'teleport_path', "label": 'Teleport per tile', "tipe": 'toggle'},
            {"kunci": 'debug_paths', "label": 'Debug paths', "tipe": 'toggle'},
            {"kunci": 'current_loc', "label": 'Debug current location', "tipe": 'toggle'},
            {"kunci": 'overclock', "label": 'Overclock', "tipe": 'toggle'},
            {"kunci": 'jeda', "label": 'Jeda antar langkah (detik)', "tipe": 'pecahan', "min": 0, "maks": 2, "langkah": 0.02},
        ],
    },
    {
        "nama": 'Replay',
        "kategori": 'Automation',
        "fitur": 'replay',
        "keterangan": 'rekam & putar ulang aksi',
        "kontrol": [
            {"kunci": 'record_active', "label": 'Record', "tipe": 'toggle'},
            {"kunci": 'play_active', "label": 'Play', "tipe": 'toggle'},
            {"kunci": 'loop', "label": 'Loop', "tipe": 'toggle'},
            {"kunci": 'record_active_raw', "label": 'Raw Packet', "tipe": 'toggle'},
            {"kunci": 'record_active_text', "label": 'Text Packet', "tipe": 'toggle'},
            {"kunci": 'custom_delay', "label": 'Custom delay (ms)', "tipe": 'angka', "min": 0, "maks": 60000, "langkah": 50},
            {"kunci": 'clear', "label": 'Clear Actions', "tipe": 'tombol', "aksi": 'refresh', "gaya": 'ghost'},
            {"kunci": 'filename', "label": 'Filename', "tipe": 'teks'},
            {"kunci": 'filename_add', "label": 'Add', "tipe": 'tombol', "aksi": 'add', "gaya": 'ghost'},
            {"kunci": 'action_refresh', "label": 'Refresh', "tipe": 'tombol', "aksi": 'refresh', "gaya": 'ghost'},
            {"kunci": 'file_refresh', "label": 'Refresh', "tipe": 'tombol', "aksi": 'refresh', "gaya": 'ghost'},
        ],
    },
    {
        "nama": 'Auto Wrench',
        "kategori": 'Automation',
        "fitur": 'autowrench',
        "keterangan": 'wrench pemain/tile berkala',
        "kontrol": [
            {"kunci": 'fastwrench', "label": 'Fast wrench mode', "tipe": 'pilihan', "opsi": ['Normal', 'Fast', 'Turbo']},
            {"kunci": 'fastwrench_enable', "label": 'Enable', "tipe": 'toggle'},
            {"kunci": 'fastwrench_enhanced', "label": 'Enhanced Mode', "tipe": 'toggle'},
            {"kunci": 'autowrench', "label": 'Auto Wrench', "tipe": 'toggle'},
            {"kunci": 'autowrench_mode', "label": 'Auto wrench mode', "tipe": 'pilihan', "opsi": ['Player', 'Tile']},
        ],
    },
    {
        "nama": 'Moderator Exit',
        "kategori": 'Automation',
        "fitur": 'modexit',
        "keterangan": 'keluar cepat saat moderator masuk',
        "kontrol": [
            {"kunci": 'enable', "label": 'Enable', "tipe": 'toggle'},
            {"kunci": 'mode', "label": 'Autoexit mode', "tipe": 'pilihan', "opsi": ['Plant & Harvest', 'Plant', 'Harvest']},
            {"kunci": 'drop_world', "label": 'World to drop', "tipe": 'teks'},
            {"kunci": 'current_world', "label": 'Current world', "tipe": 'tombol', "aksi": 'world', "gaya": 'ghost'},
            {"kunci": 'drop_pos_x', "label": 'Position x block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'drop_pos_y', "label": 'Position y block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'current_drop', "label": 'Current position', "tipe": 'tombol', "aksi": 'pos', "gaya": 'ghost'},
            {"kunci": 'donate_world', "label": 'World to donate', "tipe": 'teks'},
            {"kunci": 'current_world_donate', "label": 'Current world', "tipe": 'tombol', "aksi": 'world', "gaya": 'ghost'},
            {"kunci": 'donate_player_pos_x', "label": 'Position x block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'donate_player_pos_y', "label": 'Position y block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'current_donate', "label": 'Current position', "tipe": 'tombol', "aksi": 'pos', "gaya": 'ghost'},
            {"kunci": 'donate_pos_x', "label": 'Position x block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'donate_pos_y', "label": 'Position y block', "tipe": 'angka', "min": 0, "maks": 100000, "langkah": 1},
            {"kunci": 'find_donate', "label": 'Auto find nearest', "tipe": 'tombol', "aksi": 'cari', "gaya": 'ghost'},
            {"kunci": 'DEBUG_MOD_JOIN', "label": 'Trigger', "tipe": 'tombol', "aksi": 'trigger', "gaya": 'ghost'},
        ],
    },
]



# Kunci skema = nama atribut nyata di objek fitur. Tabel ini menerjemahkan
# nama kolom deltaX (yang dipakai saat membangun daftar di atas) ke atribut
# yang benar-benar dibaca kode, supaya Simpan/Nyalakan tidak mengirim kunci
# yang tidak dikenal.
_ALIAS_ATTR: dict[str, dict[str, str]] = {
    "spammer": {
        "texttospam": "teks",
        "active": "replay_after_enter",
    },
    "autofarm": {
        "item_picker": "block_id",
        "target_tile": "target_tiles",
        "autopunch_delay": "punch_delay",
        "autoplace_delay": "place_delay",
        "config_overclock": "faster",
        "config_showpunch": "show_punch",
        "autocollect_start": "collect",
        "autocollect_delay": "collect_delay",
        "autocollect_block": "collect_block",
        "autocollect_seed": "collect_seed",
        "autodrop_start": "drop_aktif",
        "autodrop_minimum": "drop_minimum",
        "autodrop_x": "drop_x",
        "autodrop_y": "drop_y",
        "autodrop_worldname": "drop_world",
        "autopick_enable": "pick_aktif",
        "autopick_world": "pick_world",
        "autopick_mode": "pick_mode",
    },
    "autocollect": {
        "itemtotake": "item_id",
        "valuetake": "nilai",
        "itemdisabletake": "item_disable",
        "tile": "tiles",
    },
    "replay": {
        "record_active": "aktif",
        "play_active": "memutar",
        "record_active_raw": "raw",
        "record_active_text": "text_packet",
        "filename": "file",
    },
    "autowrench": {
        "fastwrench_enhanced": "enhanced",
        "autowrench_mode": "mode",
    },
    "fishing": {
        "config_bait": "bait",
        "config_delay": "delay",
        "config_direct": "direct",
        "config_delaymode": "delaymode",
        "config_minimum_to_move": "minimum_to_move",
        "action_catch_filter": "action_catch_filter",
    },
    "ghost": {
        "cheat_auto_esp_ghost": "auto_esp_ghost",
        "show_punch": "auto_esp_ghost_show_punch",
        "jar": "auto_esp_ghost_jar",
        "config_radius": "radius",
        "config_min_in_radius": "min_in_radius",
        "debug": "auto_esp_ghost_debug",
    },
    "copysong": {
        "place_mode": "place_mode",
        "start_copy": "start_copy",
    },
}

for _kat in SKEMA_FITUR:
    _peta = _ALIAS_ATTR.get(_kat["fitur"], {})
    for _k in _kat["kontrol"]:
        _asli = _k["kunci"]
        _baru = _peta.get(_asli, _asli)
        if _baru != _asli:
            _k["alias"] = _asli
            _k["kunci"] = _baru


def skema_fitur() -> list[dict]:
    """Skema panel untuk GUI (kategori + kontrol + nilai sekarang)."""
    return SKEMA_FITUR


def parameter_default(fitur: str) -> dict[str, Any]:
    """Nilai awal tiap kontrol satu kategori, diturunkan dari SKEMA_FITUR.

    Dipakai `FiturBot` untuk memasang atribut yang belum ada (kolom deltaX
    yang paketnya belum terbukti). Turunan, bukan tabel kedua: kalau skema
    berubah, default ikut berubah.
    """
    out: dict[str, Any] = {}
    for kat in SKEMA_FITUR:
        if kat["fitur"] != fitur:
            continue
        for k in kat["kontrol"]:
            tipe = k["tipe"]
            if tipe == "tombol":
                continue
            if tipe == "toggle":
                out.setdefault(k["kunci"], False)
            elif tipe == "angka":
                out.setdefault(k["kunci"], k.get("min", 0))
            elif tipe == "pilihan":
                out.setdefault(k["kunci"], (k.get("opsi") or [""])[0])
            elif tipe == "tile":
                out.setdefault(k["kunci"], [])
            elif tipe == "item":
                out.setdefault(k["kunci"], 0)
            else:
                out.setdefault(k["kunci"], "")
    return out
