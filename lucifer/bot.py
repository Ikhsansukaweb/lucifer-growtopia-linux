"""
lucifer.bot — Bot Growtopia: koneksi, state dunia, dan semua aksi.

Kelas Bot adalah jantung aplikasi: ia menyimpan koneksi ENet, identitas akun,
dunia yang sedang dimuat, inventaris, pemain lain, dan menyediakan aksi nyata
(chat, warp, tanam, pukul, koleksi, jalan, pathfinding).

API-nya sengaja dibuat SAMA dengan struktur `Bot` di dokumentasi Lucifer V1.8,
supaya skrip Lua yang ditulis untuk Lucifer bisa jalan di sini.
"""

from __future__ import annotations

import os
import collections
import logging
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import protocol as P
from .account import (Account, RedirectInfo, detik_tunggu,
                      fetch_server_data, pesan_penolakan_login,
                      sedang_maintenance)
from .enet import ENetHost
from .items import ItemDatabase
from . import nama as N
from .protocol import NetGamePacket as G, NetMessage as M, Tank
from .world import DroppedItem, Tile, World, parse_tile_updates, parse_world

log = logging.getLogger("lucifer.bot")

# Nama paket untuk jurnal debug (mengikuti NetGamePacket).
_TANK_NAMA = {int(v): v.name for v in G}


# ID item penting (dibuktikan dari data/items.dat v27: 18=Fist, 32=Wrench,
# 0=Blank). Nilai lama 18/0 salah label -> punch mengirim Wrench dan wrench
# mengirim Fist, jadi server tak pernah memecah blok.
ITEM_FIST = 18
ITEM_WRENCH = 32


@dataclass
class PesanServer:
    """Pesan penolakan dari server Growtopia.

    Dibuat agar bentuknya sama dengan `LoginResult` (punya `.ok`, `.message`),
    sehingga penangan event tidak perlu membedakan sumbernya.
    """

    message: str
    ok: bool = False
    method: str = "server"
    token: str = ""
    raw: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


_PesanServer = PesanServer  # nama internal pendek


TILE_ACTIVATE_WRENCH = ITEM_WRENCH  # type 3 `value`, bukan type 7


class BotStatus:
    """Status bot — nilainya sama dengan enum BotStatus di Lucifer."""

    offline = "offline"
    connecting = "connecting"
    online = "online"
    wrong_password = "wrong_password"
    account_banned = "account_banned"
    location_banned = "location_banned"
    version_update = "version_update"
    advanced_account_protection = "advanced_account_protection"
    server_overload = "server_overload"
    too_many_login = "too_many_login"
    maintenance = "maintenance"
    server_busy = "server_busy"
    guest_limit = "guest_limit"
    http_block = "http_block"
    bad_name_length = "bad_name_length"
    invalid_account = "invalid_account"
    error_connecting = "error_connecting"
    logon_fail = "logon_fail"
    captcha_requested = "captcha_requested"
    mod_entered = "mod_entered"
    high_load = "high_load"


# Pesan server -> status
_STATUS_MAP: list[tuple[tuple[str, ...], str]] = [
    (("wrong password", "incorrect password", "invalid password"), BotStatus.wrong_password),
    (("banned", "suspend"), BotStatus.account_banned),
    (("location", "country"), BotStatus.location_banned),
    (("update", "outdated", "version"), BotStatus.version_update),
    (("advanced account protection", "aap"), BotStatus.advanced_account_protection),
    (("too many", "try again in"), BotStatus.too_many_login),
    (("maintenance",), BotStatus.maintenance),
    (("overload",), BotStatus.server_overload),
    (("busy",), BotStatus.server_busy),
    (("guest",), BotStatus.guest_limit),
    (("name", "length"), BotStatus.bad_name_length),
    (("captcha", "human"), BotStatus.captcha_requested),
    (("login token is invalid", "token is invalid", "invalid login token",
      "login token expired", "token expired"), BotStatus.invalid_account),
    (("fail to login", "logon fail"), BotStatus.logon_fail),
]


@dataclass
class Player:
    """Pemain di dunia (struktur `Player` Lucifer)."""

    netid: int = 0
    userid: int = 0
    name: str = ""
    altName: str = ""
    country: str = ""
    bubble: str = ""
    posx: float = 0.0
    posy: float = 0.0
    vecx: float = 0.0
    vecy: float = 0.0
    avatarFlags: int = 0
    isModerator: bool = False
    isSuperModerator: bool = False
    isLocalPlayer: bool = False
    isFriendWithOwner: bool = False
    skincolor: int = 0
    clothes: dict[str, int] = field(default_factory=dict)

    @property
    def tile_x(self) -> int:
        return int(self.posx // 32)

    @property
    def tile_y(self) -> int:
        return int(self.posy // 32)

    def __str__(self) -> str:
        return f"Player({self.name!r} netid={self.netid} @{self.posx:.0f},{self.posy:.0f})"


@dataclass
class InventoryItem:
    id: int = 0
    count: int = 0
    isActive: bool = False


class Inventory:
    """Inventaris bot (struktur `Inventory` Lucifer)."""

    def __init__(self) -> None:
        self.items: dict[int, InventoryItem] = {}
        self.itemcount = 0
        self.slotcount = 0
        self.version = 0

    def getItem(self, item_id) -> Optional[InventoryItem]:
        if isinstance(item_id, str):
            try:
                item_id = int(item_id)
            except ValueError:
                return None
        return self.items.get(int(item_id))

    def getItems(self) -> dict[int, InventoryItem]:
        return dict(self.items)

    def getItemCount(self, item_id) -> int:
        it = self.getItem(item_id)
        return it.count if it else 0

    def tambah(self, item_id: int, jumlah: int = 1) -> None:
        """Naikkan jumlah item di inventaris lokal.

        Dipakai saat server mengirim `ItemChangeObject` dengan netid bot
        sendiri: server TIDAK mengirim ulang `SendInventoryState`, jadi tanpa
        ini inventaris di GUI membeku di kondisi saat join.
        """
        it = self.items.get(int(item_id))
        if it is None:
            self.items[int(item_id)] = InventoryItem(int(item_id), int(jumlah), False)
            self.itemcount = len(self.items)
        else:
            it.count += int(jumlah)

    def kurangi(self, item_id: int, jumlah: int = 1) -> None:
        """Turunkan jumlah item di inventaris lokal (kebalikan `tambah`)."""
        it = self.items.get(int(item_id))
        if it is None:
            return
        it.count -= int(jumlah)
        if it.count <= 0:
            self.items.pop(int(item_id), None)
            self.itemcount = len(self.items)

    # alias sesuai docs Lucifer
    findItem = getItemCount

    def canCollect(self, item_id: int) -> bool:
        return True

    def parse(self, data: bytes) -> None:
        """Baca paket SendInventoryState (tank type 9).

        Format asli (terverifikasi dari dump server 5.58):

            u8  version
            u16 slotcount
            u16 (tak dipakai)
            u16 itemcount
            itemcount x { u16 item_id, u8 count, u8 flags }

        `flags` bit 0 = item sedang di tangan.
        """
        self.items.clear()
        try:
            if len(data) < 7:
                return
            self.version = data[0]
            self.slotcount = struct.unpack_from("<H", data, 1)[0]
            self.itemcount = struct.unpack_from("<H", data, 5)[0]
            off = 7
            for _ in range(self.itemcount):
                if off + 4 > len(data):
                    break
                item_id, count, flags = struct.unpack_from("<HBB", data, off)
                off += 4
                if not item_id:
                    continue
                self.items[item_id] = InventoryItem(item_id, count, bool(flags & 0x01))
        except Exception as e:  # noqa: BLE001
            log.debug("parse inventory gagal: %s", e)

    def __str__(self) -> str:
        return f"Inventory({len(self.items)} jenis item)"


class Console:
    """Console per-bot (struktur `Console` Lucifer)."""

    def __init__(self) -> None:
        self.contents: list[str] = []

    def append(self, text: str) -> None:
        self.contents.append(str(text))

    def clear(self) -> None:
        self.contents.clear()


class Log:
    """Log per-bot (struktur `Log` Lucifer)."""

    def __init__(self) -> None:
        self.content = ""

    def append(self, text: str) -> None:
        self.content += str(text) + "\n"

    def clear(self) -> None:
        self.content = ""


class Chat:
    """Riwayat obrolan satu bot: chat dunia + pesan server + chat sendiri.

    Dipisah dari `Console` supaya di GUI bisa ditampilkan seperti chat in-game
    (nama pengirim + isi), bukan tercampur log teknis.
    """

    def __init__(self, batas: int = 400) -> None:
        self.baris: list[dict[str, Any]] = []
        self.batas = batas

    def tambah(self, pengirim: str, teks: str, jenis: str = "chat") -> dict[str, Any]:
        b = {
            "ts": time.strftime("%H:%M:%S"),
            "pengirim": str(pengirim or ""),
            "teks": str(teks or ""),
            "jenis": jenis,          # chat | server | sendiri | sistem
        }
        self.baris.append(b)
        if len(self.baris) > self.batas:
            del self.baris[: len(self.baris) - self.batas]
        return b

    def bersihkan(self) -> None:
        self.baris.clear()

    def terakhir(self, n: int = 200) -> list[dict[str, Any]]:
        return self.baris[-n:]


class Signal:
    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.type = 0


class Bot:
    """Satu bot Growtopia.

    Contoh:
        bot = Bot(Account(username="Nama", password="...", method="legacy"))
        bot.connect()
        bot.say("halo")
        bot.warp("WORLD")
    """

    def __init__(
        self,
        account: Optional[Account] = None,
        items_db: Optional[ItemDatabase] = None,
        proxy: Optional[str] = None,
        label: str = "",
        on_event: Optional[Callable[[str, Any], None]] = None,
    ) -> None:
        self.account = account or Account()
        self.label = label or self.account.label
        self.name = self.account.username or self.label
        self.status = BotStatus.offline
        self.items_db = items_db
        self.proxy = proxy or self.account.proxy
        # Relay UDP lokal bila bot memakai proxy (lihat `connect`).
        self._relay = None
        self.on_event = on_event

        self.host: Optional[ENetHost] = None
        self.world = World()
        self.inventory = Inventory()
        self.console = Console()
        self.chat = Chat()
        self.log = Log()
        self.signal = Signal()
        self.players: dict[int, Player] = {}
        self.local: Optional[Player] = None
        self._last_spawn_netid: int = 0
        self.gem_count = 0
        self.level = 0
        # Malady/illness (status sakit, hanya ada di kategori Surgeon).
        # Nama mengikuti konstanta klien: ILLNESS_* (luka biasa) dan
        # MALADY_* (penyakit surgeon). Retail TIDAK mengirim variant khusus
        # untuk ini; nilainya hanya muncul di teks dialog profil
        # ("... illness.``" / " degrees``"). Karena itu sumbernya sama dengan
        # level: dialog hasil wrench diri sendiri.
        self.malady = ""
        # Level hanya dikirim server di dialog profil; minta sekali per sesi.
        self._profil_diminta = False
        # Item terakhir yang jatuh: (px, py, waktu). Dipakai autofarm sebagai
        # bukti blok pecah. Posisi drop TIDAK pas di tile (item menyebar),
        # jadi pencocokan memakai jarak piksel, bukan nomor tile.
        self._drop_baru: list[tuple[float, float, float]] = []
        # Markup dialog terakhir (diagnosis format server).
        self.dialog_terakhir = ""
        self.playtime = 0
        self.captcha_status = "no_captcha"
        self.captcha_url = ""
        self.selected = False
        self.server: tuple[str, int] = ("", 0)
        self.meta = ""
        self.redirected = False

        # penjaga rekursi hook `onsendpacket`: handler Lua boleh mengirim
        # paket lain, tapi kiriman itu TIDAK boleh memicu hook lagi (deltaX
        # memakai pola ini untuk mengganti isi dialog sebelum dikirim).
        self._dalam_hook = False
        self._draw_ts = 0.0
        self._sapu_ts = 0.0
        # Batas percobaan collect per uid: sebagian objek memang tidak pernah
        # dibalas server. Tanpa ini sapuan berkala mengirim type 11 selamanya.
        self._ambil_n: dict[int, int] = {}
        self._ambil_ts: dict[int, float] = {}

        # perilaku otomatis (dipakai skrip)
        self.auto_reconnect = True
        # ⚠️ ANTI-ERCON (2026-10-04): sebelumnya loop reconnect menembak server
        # tiap 2 detik TANPA HENTI — inilah yang membuat IP kena rate-limit
        # ("ercon"/"keseringan minta login"). Sekarang: backoff eksponensial
        # (2s,4s,8s,…,60s) + batas percobaan. Kalau server MENOLAK (maintenance
        # / rate-limit), kita BERHENTI total — tidak menembak lagi.
        self.max_reconnect_attempts = 5
        self.reconnect_backoff = 2.0
        self.reconnect_backoff_max = 60.0
        self._reconnect_count = 0
        self.auto_accept = False
        # MATI secara default: kalau nyala, bot menyapu semua objek dalam
        # radius 3 tile tanpa diminta. Saat mati bot tetap mengambil objek
        # yang menempel di badannya (tile yang sama) — lihat `_boleh_ambil`.
        self.auto_collect = False
        self.auto_collect_radius = 3
        self.auto_leave_on_admin = False
        self.auto_leave_on_mod = False
        self.auto_tutorial = True
        self.legit_mode = False
        self.move_interval = 0
        self.move_range = 3
        self.rest_time = 0
        self.rest_interval = 0

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._last_ping_ts = 0.0
        self._last_server_msg = ""
        self._connected_at = 0.0
        self._action_log: collections.deque[str] = collections.deque(maxlen=200)
        # Jurnal paket untuk debugging: setiap paket masuk/keluar dicatat
        # (tipe, arah, ringkas isi). Ring buffer 500 baris terakhir.
        self.packet_log: collections.deque[dict] = collections.deque(maxlen=500)
        # Data redirect terakhir (dari OnSendToServer). Selama ada, ServerHello
        # berikutnya dibalas dengan paket login SUB-SERVER, bukan ltoken.
        self.redirect_info = None
        # Fitur otomasi (autofarm/autocollect/spammer/path/autodrop).
        # Import di dalam fungsi supaya tidak ada impor melingkar:
        # features.py mengimpor Bot dari modul ini.
        from .features import FiturBot  # noqa: PLC0415

        self.fitur = FiturBot(self)

    # ------------------------------------------------------------------ #
    # Info
    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:
        return f"Bot({self.label!r} status={self.status})"

    @property
    def ping(self) -> int:
        return self.host.ping if self.host else 0

    def getPing(self) -> int:
        return self.ping

    def getWorld(self) -> World:
        return self.world

    def getInventory(self) -> Inventory:
        return self.inventory

    def getConsole(self) -> Console:
        return self.console

    def getLog(self) -> Log:
        return self.log

    def getLogin(self):
        return self.account

    def getSignal(self) -> Signal:
        return self.signal

    def getCaptcha(self) -> str:
        return self.captcha_url

    def getPlaytime(self) -> int:
        return self.playtime

    def getAge(self) -> int:
        return 0

    def getActiveTime(self) -> str:
        if not self._connected_at:
            return "0s"
        return f"{int(time.time() - self._connected_at)}s"

    def isInWorld(self, name: str = "") -> bool:
        if not self.world.name:
            return False
        return self.world.name.upper() == name.upper() if name else True

    def isInTile(self, x_or_tile, y: int = -1) -> bool:
        if not self.local:
            return False
        if y < 0 and hasattr(x_or_tile, "x"):
            return self.local.tile_x == x_or_tile.x and self.local.tile_y == x_or_tile.y
        return self.local.tile_x == int(x_or_tile) and self.local.tile_y == int(y)

    # ------------------------------------------------------------------ #
    # Koneksi
    # ------------------------------------------------------------------ #
    def _segarkan_token(self, timeout: int = 15) -> None:
        """Tukar ltoken tersimpan dengan token game yang masih hangat.

        `checktoken` adalah REFRESH endpoint: token yang dikembalikan berlaku
        untuk SATU login game. Token tersimpan setelah dipakai login akan
        ditolak server (`Login token is invalid`) walau masih bisa di-refresh.
        Dibuktikan di log: token jam 18:35 -> login 18:42 sukses, lalu restart
        18:54 dengan token yang sama -> ditolak.

        Jadi setiap connect minta token baru dulu. Ini satu permintaan HTTP,
        bukan reconnect — tidak menambah risiko blokir IP.
        """
        if self.redirect_info is not None:
            return
        ltoken = (getattr(self.account, "_token", "") or self.account.ltoken or "").strip()
        if not ltoken or self.account.method in ("legacy", "growid"):
            return
        from .account import check_token  # noqa: PLC0415

        try:
            res = check_token(ltoken, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            self._emit("error", f"gagal segarkan token: {type(e).__name__}")
            return
        if res.ok and res.token:
            if res.token != ltoken:
                self.account.ltoken = res.token
                self.account._token = res.token
            self._emit("token_segar", res.message)
        else:
            self._emit("error", f"token ditolak checktoken: {res.message}")

    def connect(self, timeout_ms: int = 8000) -> bool:
        """Connect ke server Growtopia dan mulai loop jaringan."""
        if self._running:
            return True
        try:
            sd = fetch_server_data(self.account.protocol, self.account.version)
            self.meta = sd.get("meta", "")
            host, port = sd["server"], int(sd["port"])
        except Exception as e:  # noqa: BLE001
            self.status = BotStatus.error_connecting
            self._emit("error", f"gagal ambil server_data: {e}")
            return False

        # Server menolak login? HANYA kalau server mengirim `maint` TANPA `#`.
        # Baris `#maint` adalah komentar yang SELALU ada — bukan tanda apa pun
        # (koreksi 2026-09-30). Kunci `maint` aktif bisa berarti maintenance
        # ATAU rate-limit ("wait N seconds before logging in again") — maka
        # pesannya diterjemahkan oleh `pesan_penolakan_login` supaya jujur.
        if sedang_maintenance(sd):
            self.status = BotStatus.offline
            self._emit("error", pesan_penolakan_login(sd))
            # ⚠️ ANTI-ERCON: kalau server MENOLAK (maintenance atau rate-limit),
            # jangan pernah reconnect otomatis — menembak ulang hanya membuat
            # cooldown makin panjang. Tunggu sesuai perintah server.
            self.auto_reconnect = False
            tunggu = detik_tunggu(sd)
            if tunggu > 0:
                self._emit(
                    "error",
                    f"server minta tunggu {tunggu} detik — jangan login lagi "
                    f"sebelum itu, atau cooldown akan bertambah.",
                )
            return False

        # login (ambil ltoken kalau metode growid)
        self._segarkan_token()
        res = self.account.login(meta=self.meta)
        if not res.ok:
            self.status = BotStatus.logon_fail
            self._emit("login_failed", res)
            return False
        self._emit("login", res)

        proxy = None
        relay = None
        if self.proxy:
            from .proxy import parse as _parse_proxy  # noqa: PLC0415
            from .udprelay import RelayError, RelayUdp  # noqa: PLC0415
            try:
                _p = _parse_proxy(self.proxy)
            except ValueError as e:
                _p = None
                self._emit("error", f"proxy tidak valid ({e}) — connect tanpa proxy")

            if _p is not None:
                # `enet_host_use_proxy()` di enet.so RUSAK: ia kirim greeting
                # SOCKS5 lalu langsung menutup soket. Jadi proxy ditangani
                # sendiri lewat relay UDP lokal, dan ENet bicara ke loopback.
                try:
                    relay = RelayUdp(_p, (host, port)).start()
                except RelayError as e:
                    self.status = BotStatus.error_connecting
                    self._emit("error", f"proxy gagal: {e}")
                    return False

        target_host, target_port = (host, port)
        if relay is not None:
            target_host, target_port = "127.0.0.1", relay.port
            self._emit("info", f"proxy {self.proxy} aktif lewat relay "
                               f"127.0.0.1:{relay.port}")

        self.status = BotStatus.connecting
        self._relay = relay
        self.host = ENetHost()
        self.server = (host, port)
        if not self.host.connect(target_host, target_port, timeout_ms):
            self.status = BotStatus.maintenance
            # Server Growtopia TIDAK membalas sama sekali. Ini bukan soal
            # koneksi internet pengguna: UDP keluar sudah terbukti jalan
            # (DNS/NTP/STUN membalas), dan host game diam di semua port
            # 17000-17200. Penyebab paling umum: Growtopia maintenance.
            # Jangan menyuruh user "cek internet" — itu tuduhan yang salah.
            self._emit(
                "error",
                f"Server Growtopia tidak menjawab ({host}:{port}). "
                f"Kemungkinan besar Growtopia sedang maintenance — "
                f"bukan masalah koneksi/WiFi kamu. Jangan connect berulang; "
                f"tunggu sampai server pulih.",
            )
            if relay is not None:
                relay.close()
                self._relay = None
            return False

        self._connected_at = time.time()
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"bot-{self.label}", daemon=True)
        self._thread.start()
        return True

    def disconnect(self) -> None:
        self._stop.set()
        # Hentikan dulu semua loop fitur — kalau tidak, autofarm masih
        # memanggil hit() saat host sudah ditutup.
        try:
            self.fitur.stop_semua()
        except Exception:  # noqa: BLE001
            pass
        if self.host:
            try:
                self.host.disconnect(graceful=False)
            except Exception:
                pass
        self._running = False
        self.status = BotStatus.offline
        relay = getattr(self, "_relay", None)
        if relay is not None:
            try:
                relay.close()
            except Exception:  # noqa: BLE001
                pass
            self._relay = None
        # Data redirect hanya berlaku untuk satu sesi hospitalitas sub-server.
        # Menyimpannya melewati disconnect membuat connect berikutnya memakai
        # paket redirect basi (token mati) -> server diam.
        self.redirect_info = None
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None
        self._emit("disconnect", None)

    def reconnect(self) -> bool:
        self.disconnect()
        time.sleep(0.5)
        return self.connect()

    # ------------------------------------------------------------------ #
    # Loop jaringan
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        """Loop utama: layani event ENet dan tangani paket."""
        while not self._stop.is_set():
            try:
                ev = self.host.service(200) if self.host else None
            except Exception as e:  # noqa: BLE001
                log.debug("service error: %s", e)
                break

            if ev is None:
                continue

            if ev.kind == "connect":
                self.status = BotStatus.online
                self._reconnect_count = 0  # berhasil — reset hitungan ercon
                self._emit("connected", self.server)
            elif ev.kind in ("disconnect", "timeout"):
                self.status = BotStatus.offline
                self._emit("disconnected", ev.kind)
                if self.auto_reconnect and not self._stop.is_set():
                    self._reconnect_count += 1
                    if self._reconnect_count > self.max_reconnect_attempts:
                        # Berhenti menembak server. Ini mencegah ercon/rate-limit.
                        self._emit(
                            "error",
                            f"gagal reconnect {self._reconnect_count - 1}× — "
                            f"berhenti otomatis supaya IP tidak diblokir "
                            f"(ercon). Connect manual lagi nanti.",
                        )
                        break
                    # backoff eksponensial: 2s, 4s, 8s, ... maksimal 60s
                    jeda = min(
                        self.reconnect_backoff * (2 ** (self._reconnect_count - 1)),
                        self.reconnect_backoff_max,
                    )
                    self._emit(
                        "reconnect",
                        f"percobaan {self._reconnect_count}/"
                        f"{self.max_reconnect_attempts} dalam {jeda:.0f}s",
                    )
                    # tunggu, tapi tetap bisa dihentikan
                    if self._stop.wait(jeda):
                        break
                    try:
                        self.disconnect()
                        self.connect()
                    except Exception:  # noqa: BLE001
                        pass
                break
            elif ev.kind == "receive":
                try:
                    self._handle_packet(ev.data)
                except Exception as e:  # noqa: BLE001
                    log.warning("[%s] gagal menangani paket: %s", self.label, e)

            # tick `ondraw` (deltaX: pengganti render loop). Cukup ~20 Hz
            # supaya skrip yang memakai ondraw untuk timer tetap hidup.
            now = time.time()
            if now - self._draw_ts >= 0.05:
                delta = int((now - self._draw_ts) * 1000) if self._draw_ts else 0
                self._draw_ts = now
                self._emit("draw", delta)

            # Sapu objek yang SUDAH ada sebelum bot masuk / yang terlewat.
            # Item yang jatuh saat bot online sudah ditangani `_auto_ambil`
            # lewat paket type 14, tapi item lama tidak pernah memicu paket.
            if now - self._sapu_ts >= 2.0:
                self._sapu_ts = now
                try:
                    self._sapu_objek()
                except Exception:  # noqa: BLE001
                    pass

            # balas ping berkala (jaga koneksi)
            if now - self._last_ping_ts > 5:
                self._last_ping_ts = now

    def _emit(self, kind: str, payload: Any) -> None:
        self._action_log.append(f"{time.strftime('%H:%M:%S')} {kind}: {str(payload)[:160]}")
        if self.on_event:
            try:
                self.on_event(kind, payload)
            except Exception:  # noqa: BLE001
                pass

    # -- jurnal paket (debug) ------------------------------------------- #
    def catat_paket(self, arah: str, mtype: int, ringkas: Any) -> None:
        """Simpan satu baris jurnal paket (`in`/`out`) untuk debugging."""
        self.packet_log.append({
            "ts": time.strftime("%H:%M:%S"),
            "arah": arah,
            "type": int(mtype),
            "isi": str(ringkas)[:400],
        })

    def _ringkas_tank(self, t: Tank) -> str:
        """Ringkas TankPacket dengan nama manusiawi (lihat `lucifer/nama.py`)."""
        return N.ringkas_tank(t, self.items_db)
    # ------------------------------------------------------------------ #
    # Penanganan paket masuk
    # ------------------------------------------------------------------ #
    def _handle_packet(self, raw: bytes) -> None:
        mtype, payload = P.parse_packet(raw)

        # Jurnal debug: catat semua paket masuk apa adanya.
        if mtype == M.GamePacket and len(payload) >= P.TANK_SIZE:
            try:
                _tk, _ext = P.unpack_tank(payload)
                _hex = _ext[:48].hex() if int(_tk.type) in (5, 6, 9, 13, 14) else ""
                _var = ""
                if int(_tk.type) == int(G.CallFunction):
                    # Nama variant (OnSetPos/OnSpawn/...) jauh lebih berguna
                    # daripada panjang ext mentah saat men-debug posisi.
                    try:
                        _vl = P.VariantList.deserialize(_ext)
                        _arg = _vl.get(1)
                        _var = f" fn={_vl.func_name()} arg1={str(_arg.as_string() if _arg else '')[:80]!r}"
                    except Exception:  # noqa: BLE001
                        _var = " fn=<gagal>"
                self.catat_paket("in", mtype,
                                 f"{self._ringkas_tank(_tk)} ext={len(_ext)} {_hex}{_var}")
            except Exception:  # noqa: BLE001
                self.catat_paket("in", mtype, f"tank rusak ({len(payload)} B)")
        elif mtype in (M.GenericText, M.GameMessage):
            _f = P.decode_text(payload)
            _nama = _f.get("action") or _f.get("eventName") or ""
            self.catat_paket("in", mtype, f"{_nama} | {str(_f)[:300]}")
        else:
            self.catat_paket("in", mtype, f"{len(payload)} B")

        if mtype == M.ServerHello:
            # Sub-server (setelah OnSendToServer) tidak menerima `ltoken`.
            # Klien asli membalas ServerHello dengan paket login redirect.
            if self.redirect_info is not None:
                self.send_text(M.GenericText, self.account.redirect_payload(self.redirect_info))
            else:
                self.send_text(M.GenericText, self.account.login_payload())
            return

        if mtype in (M.GenericText, M.GameMessage):
            fields = P.decode_text(payload)
            self._handle_text(mtype, fields, payload)
            self._emit("game_message" if mtype == M.GameMessage else "generic_text", fields)
            return

        if mtype == M.GamePacket:
            tank, ext = P.unpack_tank(payload)
            self._handle_tank(tank, ext)
            return

        if mtype == M.Error:
            self._emit("error_packet", payload[:200])

    def _handle_text(self, mtype: int, fields: dict[str, str], payload: bytes) -> None:
        action = fields.get("action", "")

        if action == "log" or "msg" in fields:
            # Server mengirim pesan berwarna (`` `4Fail to login... ``).
            # Kode warna dibuang supaya log/console enak dibaca.
            msg = P.remove_color(fields.get("msg", ""))
            self.console.append(msg)
            self._last_server_msg = msg
            for keys, status in _STATUS_MAP:
                if any(k in msg.lower() for k in keys):
                    self.status = status
                    break
            self._emit("console", msg)
            # Pesan penting dari server (penolakan login, captcha, ban) juga
            # dikirim sebagai event tersendiri supaya bisa ditangani Lua &
            # tercatat di log dashboard — bukan cuma menumpuk di console.
            low = msg.lower()
            if any(k in low for k in ("fail to login", "try again", "captcha",
                                      "banned", "suspend", "overload", "full",
                                      "verify", "invalid")):
                self._emit("login_failed", _PesanServer(msg))

        if action == "logon_fail":
            # Jangan timpa status yang LEBIH SPESIFIK. Server mengirim
            # `action|logon_fail` bersama `msg|Fail to login. Please try again
            # in 30 seconds.` — pesan itu sudah dipetakan _STATUS_MAP ke
            # too_many_login. Menimpanya dengan logon_fail membuat user diberi
            # saran "sandi salah" padahal yang terjadi cuma cooldown IP.
            if self.status in (BotStatus.connecting, BotStatus.offline, ""):
                self.status = BotStatus.logon_fail
            fields.setdefault("msg", self._last_server_msg or "server menolak login (logon_fail)")
            self._emit("logon_fail", fields)
            # Cooldown dari server: hentikan auto-reconnect. Menembak ulang
            # hanya memperpanjang blokir (lihat catatan ANTI-ERCON di connect()).
            if self.status == BotStatus.too_many_login:
                self.auto_reconnect = False

        if "OnSuperMainStartAcceptLogon" in payload.decode("utf-8", "replace"):
            self.send_text(M.GenericText, b"action|enter_game\n")
            self._emit("entering_game", None)

        if "refresh_item_data" in action or fields.get("action") == "refresh_item_data":
            pass

        if action == "captcha" or "captcha" in fields:
            self.captcha_status = "not_found"
            self.captcha_url = fields.get("url", fields.get("captcha", ""))
            self._emit("captcha", self.captcha_url)

        if "tile_update" in action:
            self._emit("tile_update", fields)

    def _dump(self, nama: str, data: bytes) -> None:
        """Simpan payload mentah untuk diagnosis parser (LUCIFER_DUMP=1)."""
        if not os.environ.get("LUCIFER_DUMP"):
            return
        try:
            Path("/tmp/opencode").mkdir(parents=True, exist_ok=True)
            Path(f"/tmp/opencode/dump_{nama}.bin").write_bytes(data)
            log.info("dump %s: %d byte", nama, len(data))
        except Exception:  # noqa: BLE001
            pass

    def _handle_tank(self, tank: Tank, ext: bytes) -> None:
        t = tank.type
        # Rekam mentah paket agar format `SendTileUpdateData` dipastikan dari
        # data nyata, bukan tebakan. Aktif hanya bila LUCIFER_DUMP=1.
        if os.environ.get("LUCIFER_DUMP"):
            try:
                d = Path("/tmp/opencode")
                d.mkdir(parents=True, exist_ok=True)
                with (d / "tank_tile.log").open("a") as f:
                    f.write(f"type={t} ix={tank.int_x} iy={tank.int_y} "
                            f"val={tank.value} net={tank.net_id} "
                            f"obj={tank.object_type} fl={tank.flags} "
                            f"len={len(ext)} ext={ext[:96].hex()}\n")
            except Exception:  # noqa: BLE001
                pass

        if t == G.CallFunction:
            self._handle_variant(ext, tank)
        elif t == G.SendMapData:
            self._dump("map", ext)
            self.world = parse_world(ext, self.items_db)
            self.players.clear()
            self._profil_diminta = False
            self._emit("world_loaded", self.world)
            # Level hanya ada di dialog profil; minta sekali per world setelah
            # data dunia siap (urutan SendMapData/SetCharacterState tak dijamin).
            if self.local is not None and self.world.tiles:
                self._profil_diminta = True
                self.minta_profil()
        elif t == G.ModifyItemInventory:
            self._apply_modify_inventory(tank)
        elif t == G.SendInventoryState:
            self._dump("inv", ext)
            self.inventory.parse(ext)
            self._emit("inventory", self.inventory)
        elif t == G.SendItemDatabaseData:
            self._save_items(ext)
        elif t == G.TileApplyDamage:
            # Server mengirim type 8 tiap pukulan diterima, TANPA diikuti
            # type 5/6 untuk blok yang kita pukul sendiri. Jadi ini satu-
            # satunya umpan balik "pukulan ke-N diterima". Hitungan dipakai
            # autofarm untuk tahu kapan blok benar-benar pecah.
            self._apply_damage(tank)
        elif t == G.TileChangeRequest:
            # Server meng-ECHO `TileChangeRequest` kembali ke kita (netid =
            # netid bot) setelah aksi diterima. Ini konfirmasi NYATA untuk
            # `place`: `value` = item id yang benar-benar terpasang, jadi
            # stok lokal bisa dikurangi dari sini (server retail tidak
            # mengirim `ModifyItemInventory` untuk place).
            self._apply_tile_change_echo(tank)
        elif t == G.PingRequest:
            self._reply_ping(tank)
        elif t == G.SendTileUpdateData:
            self._apply_tile_update(tank, ext)
        elif t == G.SendTileUpdateDataMultiple:
            # Server retail mengirim type 6 (bukan type 5) untuk perubahan
            # blok hasil punch. Sebelum ini tidak ditangani sama sekali, jadi
            # `world` tak pernah berubah: tile yang sudah dipecah tetap terlihat
            # berisi, bot memukulnya terus, dan `taruh()` tidak punya sasaran.
            self._dump("tilemulti", ext)
            if os.environ.get("LUCIFER_DUMP"):
                try:
                    d = Path("/tmp/opencode")
                    d.mkdir(parents=True, exist_ok=True)
                    with (d / "tilemulti.log").open("a") as f:
                        f.write(f"{time.strftime('%H:%M:%S')} {len(ext)}B {ext.hex()}\n")
                except Exception:  # noqa: BLE001
                    pass
            self._apply_tile_updates(ext)
        elif t == G.ItemChangeObject:
            self._apply_item_change(tank, ext)
        elif t == G.State:
            self._apply_state(tank)
        elif t == G.SetCharacterState:
            self._apply_character_state(ext, tank)
        elif t == G.UpdateStatus:
            self._apply_status(ext)
        elif t == G.SendTileTreeState:
            self._emit("tree_state", ext[:64])

        self._emit("game_packet", tank)

    def _handle_variant(self, ext: bytes, tank: Tank) -> None:
        try:
            vl = P.VariantList.deserialize(ext)
        except Exception as e:  # noqa: BLE001
            log.debug("variant gagal diurai: %s", e)
            return
        fn = vl.func_name()
        self._emit("variant", (vl, tank.net_id))
        if fn == "OnDialogRequest":
            # Markup dialog ada di argumen PERTAMA (index 1), bukan index 2.
            # Jangan asal index: gabungkan semua argumen string supaya
            # `add_player_info` tetap ketemu walau server menaruh di posisi lain.
            teks = "\n".join(
                v.as_string() for v in vl.variants[1:]
                if v.kind == P.VARIANT_STRING and v.value
            )
            # `add_player_info|<nama>|<level>|<xp>|<xp_next>|` hanya muncul di
            # dialog hasil wrench diri sendiri. Ini satu-satunya sumber level
            # yang dikirim server retail (bukan paket status).
            self.dialog_terakhir = teks
            self._dump("dialog", teks.encode("utf-8", "replace"))
            self._baca_level_dialog(teks)
            self._emit("dialog", teks)
        elif fn == "OnSetBux":
            # OnSetBux(<gems>, <animate>, <supporter>, [vec3 jam]) — argumen
            # pertama = jumlah gem. Retail maupun server privat memakai ini.
            self._set_gems(vl.get(1).as_int32() if vl.get(1) else 0)
        elif fn in ("OnPlayerLeveledUp", "OnLevelUp"):
            # Server privat (Gurotopia) mengirim level baru di sini.
            self._set_level(vl.get(1).as_int32() if vl.get(1) else 0)

        if fn == "OnConsoleMessage":
            msg = P.remove_color(vl.get(1).as_string() if vl.get(1) else "")
            self.console.append(msg)
            self._emit("console", msg)
        elif fn == "OnSendToServer":
            self._on_send_to_server(vl)
        elif fn == "OnSuperMainStartAcceptLogonHrdxs47254722215a":
            self.send_text(M.GenericText, b"action|enter_game\n")
            self._emit("entering_game", None)
        elif fn in ("onShowCaptcha", "ShowCaptcha"):
            self._on_show_captcha(vl)
        elif fn == "OnCaptchaFailed":
            self.captcha_status = "failed"
            self._emit("captcha_failed", None)
        elif fn in ("OnSpawn", "OnAdd"):
            # OnSpawn membawa SATU string multi-baris, bukan argumen terpisah:
            #     spawn|avatar\nnetID|5\nuserID|...\nname|Budi\n...
            # Parser lama membaca argumen ke-2 sebagai nama → semua nama kosong.
            netid, nama = 0, ""
            try:
                teks = vl.get(1).as_string() if vl.get(1) else ""
                for baris in teks.split("\n"):
                    if "|" not in baris:
                        continue
                    k, v = baris.split("|", 1)
                    k = k.strip().lower()
                    if k == "netid":
                        netid = int(v.strip() or 0)
                    elif k == "name":
                        nama = P.remove_color(v.strip())
            except Exception:  # noqa: BLE001
                netid, nama = netid, ""
            if netid:
                pl = self.players.get(netid) or Player(netid=netid)
                if nama:
                    pl.name = nama
                # OnSpawn untuk nama sendiri = pemain lokal. Ini cara pasti
                # mendapat netid sendiri; paket `State` baru mengisi posisinya.
                if nama and self.name and nama == self.name:
                    pl.isLocalPlayer = True
                    self.local = pl
                self.players[netid] = pl
                # Spawn terakhir sebelum OnSetPos = diri sendiri: server
                # mengirim OnSpawn lalu OnSetPos untuk pemain lokal.
                self._last_spawn_netid = netid
                self._emit("player_add", pl)
        elif fn == "OnSetPos":
            # Posisi pemain LOKAL: OnSetPos(vec2). Dikirim server tepat setelah
            # spawn; ini satu-satunya sumber posisi awal yang bisa dipercaya.
            try:
                v = vl.get(1)
                val = getattr(v, "value", None)
                if isinstance(val, tuple) and len(val) >= 2:
                    x, y = float(val[0]), float(val[1])
                    if self.local is None:
                        # OnSetPos selalu mendahului/mengikuti OnSpawn diri
                        # sendiri, jadi pakai netid spawn terakhir.
                        netid = getattr(self, "_last_spawn_netid", 0) or (
                            sorted(self.players)[-1] if self.players else 0)
                        pl = self.players.get(netid) or Player(netid=netid)
                        pl.isLocalPlayer = True
                        self.local = pl
                        self.players[netid] = pl
                    self.local.posx, self.local.posy = x, y
                    self._emit("player_move", self.local)
            except Exception as e:  # noqa: BLE001
                log.debug("OnSetPos gagal: %s", e)
        elif fn == "OnRemove":
            try:
                netid = vl.get(1).as_int32() if vl.get(1) else 0
            except Exception:  # noqa: BLE001
                netid = 0
            if netid:
                self.players.pop(netid, None)
                self._emit("player_remove", netid)
        elif fn in ("OnTalkBubble",):
            # Obrolan dunia: OnTalkBubble(netid, teks, ...). Nama pengirim
            # dicari dari daftar player; kalau belum dikenal pakai netid.
            try:
                netid = vl.get(1).as_int32() if vl.get(1) else 0
                teks = P.remove_color(vl.get(2).as_string() if vl.get(2) else "")
            except Exception:  # noqa: BLE001
                netid, teks = 0, ""
            if teks:
                pl = self.players.get(netid)
                nama = (pl.name if pl else "") or f"#{netid}"
                jenis = "sendiri" if netid == (self.local.netid if self.local else -2) else "chat"
                self.chat.tambah(nama, teks, jenis)
                self.console.append(f"<{nama}> {teks}")
                self._emit("chat", {"netid": netid, "name": nama, "text": teks})

    def _on_show_captcha(self, vl: P.VariantList) -> None:
        """Server meminta captcha (callback `onShowCaptcha`).

        PENTING: klien Growtopia memakai callback VariantList bernama
        `onShowCaptcha` (huruf kecil 'o'), BUKAN teks `action|captcha`.
        Handler lama mencari `action == "captcha"` sehingga tidak pernah jalan
        dan status captcha selalu `no_captcha` — seolah server tidak pernah
        meminta captcha, padahal bisa jadi sedang meminta.
        """
        url = ""
        for i in range(1, len(vl)):
            v = vl.get(i)
            s = v.as_string() if v else ""
            if s.startswith("http") or "captcha" in s.lower():
                url = s
                break
        self.captcha_status = "not_found"
        self.captcha_url = url
        self._emit("captcha", url)

    def _on_send_to_server(self, vl: P.VariantList) -> None:
        """Server meminta pindah ke sub-server (redirect).

        Argumen `OnSendToServer` (dibuktikan dari `libgrowtopia.so`, fungsi
        pembangun paket redirect di 0x180218c / 0x1805490):

            [1] port (int)
            [2] token (int, -1 = pakai token sebelumnya)
            [3] user id (int)
            [4] "server|doorID|UUIDToken"
            [5] lmode (int)
            [6] tankIDName (string)

        Setelah ini ServerHello sub-server WAJIB dibalas paket login redirect
        (`user|`, `token|`, `UUIDToken|`, `lmode|`), bukan `ltoken` biasa.
        """
        try:
            port = vl.get(1).as_int32()
            token_i = vl.get(2).as_int32()
            uid = vl.get(3).as_int32()
            sd = (vl.get(4).as_string() if vl.get(4) else "").split("|")
            lmode = vl.get(5).as_int32() if vl.get(5) else 1
            tank_name = vl.get(6).as_string() if vl.get(6) else ""

            host = (sd[0] if sd else "").strip()
            door_id = sd[1].strip() if len(sd) > 1 else "0"
            uuid_raw = sd[2].strip() if len(sd) > 2 else ""

            prev = self.redirect_info
            token = str(token_i) if token_i >= 0 else (prev.token if prev else "")
            uuid_token = uuid_raw
            if (not uuid_token or uuid_token == "-1") and prev:
                uuid_token = prev.uuid_token
            if not tank_name and prev:
                tank_name = prev.tank_id_name

            self.redirect_info = RedirectInfo(
                server=host, port=port, token=token, user=str(uid),
                door_id=door_id or "0", uuid_token=uuid_token,
                lmode=str(lmode), tank_id_name=tank_name,
                meta=self.meta, rid=self.account.rid, mac=self.account.mac,
            )
            self.redirected = True
            self._emit("redirect", {"host": host, "port": port, "user": str(uid)})
            # PENTING: jalankan di thread loop ini (bukan thread baru).
            # Dulu redirect jalan di thread terpisah sementara _loop masih
            # memanggil service() pada host lama. Dua thread men-service host
            # yang sama bikin ServerHello dari sub-server bisa "dicuri" atau
            # hilang -> login sub-server tidak pernah selesai dan dunia tidak
            # pernah dimuat. Sekarang urutannya deterministik.
            self._redirect_to(host, port, token)
        except Exception as e:  # noqa: BLE001
            log.warning("redirect gagal: %s", e)

    def _redirect_to(self, host: str, port: int, token: str) -> None:
        try:
            if self.host:
                self.host.close()
            self.host = ENetHost()
            self.server = (host, int(port))
            if self.host.connect(host, int(port), 8000):
                self.status = BotStatus.online
                self.redirected = False
                self._emit("redirected", self.server)
        except Exception as e:  # noqa: BLE001
            self._emit("error", f"redirect: {e}")

    def _reply_ping(self, tank: Tank) -> None:
        reply = Tank(
            type=G.PingReply,
            net_id=tank.net_id,
            value=tank.value,
            vector_x=64.0,
            vector_y=64.0,
            vector_x2=1000.0,
            vector_y2=250.0,
            int_x=tank.int_x,
            int_y=tank.int_y,
        )
        self.send_raw(reply)

    # id tile -> jumlah pukulan yang sudah diterima server pada tile itu
    _hit_tiles: dict[tuple[int, int], int] = {}

    def _apply_damage(self, tank: Tank) -> None:
        """Catat satu pukulan yang diterima server (`TileApplyDamage`).

        Format: `int_x`/`int_y` = tile, `value` = nilai damage mentah
        (bukan jumlah total). Kita hanya butuh tahu tile mana yang kena,
        lalu hitungan sendiri dinaikkan satu.
        """
        key = (int(tank.int_x), int(tank.int_y))
        if key[0] < 0 or key[1] < 0:
            return
        self._hit_tiles[key] = self._hit_tiles.get(key, 0) + 1

    def ada_drop_dekat(self, x: int, y: int, radius_px: float = 40.0,
                       dalam_detik: float = 3.0) -> bool:
        """Apakah ada item jatuh di dekat tile ini baru-baru ini?

        Ini bukti blok pecah: server tidak mengirim paket "tile jadi kosong",
        tapi SELALU mengirim `ItemChangeObject` di posisi blok yang pecah
        (bloknya sendiri atau bibitnya). Posisi drop menyebar beberapa piksel,
        jadi dipakai jarak, bukan nomor tile.
        """
        cx, cy = x * 32 + 16, y * 32 + 16
        batas = time.time() - dalam_detik
        for dx, dy, ts in self._drop_baru:
            if ts < batas:
                continue
            if abs(dx - cx) <= radius_px and abs(dy - cy) <= radius_px:
                return True
        return False

    def bersihkan_drop(self) -> None:
        self._drop_baru.clear()

    def hit_count(self, x: int, y: int) -> int:
        """Jumlah pukulan yang sudah diterima server untuk tile ini."""
        return self._hit_tiles.get((int(x), int(y)), 0)

    def reset_hit(self, x: int, y: int) -> None:
        self._hit_tiles.pop((int(x), int(y)), None)

    def _apply_tile_change_echo(self, tank: Tank) -> None:
        """Kurangi stok lokal saat server mengonfirmasi `place`.

        Bukti dari jurnal paket nyata (server retail 5.58):

            in type=3(TileChangeRequest) netid=14 tile=(55,23) value=2

        `value` adalah item id yang berhasil ditaruh. Hanya aksi dengan item
        id > 0 yang mengurangi stok; `value == 18` (Fist) berarti pukulan,
        bukan pemakaian item.
        """
        item_id = int(tank.value)
        if item_id <= 0:
            return
        x, y = int(tank.int_x), int(tank.int_y)
        if item_id in (ITEM_FIST, ITEM_WRENCH):
            # Pukulan/wrench: bukan pemakaian item, tapi tetap kabar bahwa
            # tile ini disentuh. Jangan ubah isi dunia dari sini (server yang
            # menentukan kapan blok hilang).
            return
        # Place diterima server: blok ini BENAR-BENAR ada di dunia sekarang.
        # Tanpa menerapkannya ke `world` lokal, bot tidak tahu blok baru sudah
        # terpasang sehingga tidak pernah memecahnya lagi (dan peta GUI
        # tertinggal). Update lokal di sini, lalu biarkan type 5/6 menimpa
        # kalau server mengirimnya.
        lama = self.world.tile(x, y)
        if lama is not None and x >= 0 and y >= 0:
            baru = Tile(x=x, y=y, fg=item_id, bg=lama.bg,
                        parent=lama.parent, flags=0)
            self.world.update_tile(self.world.index_of(x, y), baru)
            self._emit("tile_update", baru)
        if self.inventory.getItemCount(item_id) <= 0:
            return
        self.inventory.kurangi(item_id, 1)
        self._emit("inventory", self.inventory)

    def _apply_modify_inventory(self, tank: Tank) -> None:
        """`ModifyItemInventory` (tank type 13) — stok satu item naik/turun.

        Format (Gurotopia `database/world.cpp:modify_item_inventory`):

            int32 @0 = (jumlah << 24) | 0x000d   -> item BERTAMBAH
                     = (jumlah << 16) | 0x000d   -> item BERKURANG
            value    = item id

        Byte 0 tetap 13 (tipe paket); byte 2 = berkurang, byte 3 = bertambah.
        Tanpa handler ini inventaris lokal tidak pernah berubah setelah
        menaruh/memecah blok, jadi `taruh()` mengira stok masih ada dan terus
        mengirim `tileChange` walau server sudah menolak.
        """
        try:
            item_id = int(tank.value)
            if item_id <= 0 or item_id == 112:   # 112 = gems, bukan item
                return
            tambah = int(tank.animation_type)    # byte 3
            kurang = int(tank.jump_count)        # byte 2
            if tambah:
                self.inventory.tambah(item_id, tambah)
            elif kurang:
                self.inventory.kurangi(item_id, kurang)
            else:
                return
            self._emit("inventory", self.inventory)
        except Exception as e:  # noqa: BLE001
            log.debug("modify inventory gagal: %s", e)

    def _apply_tile_update(self, tank: Tank, ext: bytes) -> None:
        """Terapkan pembaruan satu tile (SendTileUpdateData).

        Koordinat tile ada di TANK (`int_x`/`int_y` = px/py), BUKAN di ext.
        Ext hanya blok tergabung: u16 fg, u16 bg, u16 parent, u16 flags
        (`block::to_blob` di Gurotopia). Parser lama membaca tx/ty dari ext
        sehingga world tidak pernah berubah sesudah blok pecah, dan autofarm
        memukul tile yang sama terus.
        """
        try:
            if len(ext) < 8:
                return
            tx, ty = int(tank.int_x), int(tank.int_y)
            off = 0
            fg, bg, parent, flags = struct.unpack_from("<HHHH", ext, off)
            idx = self.world.index_of(tx, ty)
            old = self.world.tile(tx, ty)
            t = Tile(x=tx, y=ty, fg=fg, bg=bg, parent=parent, flags=flags)
            if old:
                t.seed_age, t.fruit_count, t.ready = old.seed_age, old.fruit_count, old.ready
            self.world.update_tile(idx, t)
            self._emit("tile_update", t)
        except Exception as e:  # noqa: BLE001
            log.debug("tile update gagal: %s", e)

    def _apply_tile_updates(self, ext: bytes) -> None:
        """Terapkan `SendTileUpdateDataMultiple` (Tank type 6)."""
        try:
            for t in parse_tile_updates(ext, self.items_db):
                idx = self.world.index_of(t.x, t.y)
                old = self.world.tile(t.x, t.y)
                if old is not None:
                    t.seed_age, t.fruit_count, t.ready = (
                        old.seed_age, old.fruit_count, old.ready)
                self.world.update_tile(idx, t)
                self._emit("tile_update", t)
        except Exception as e:  # noqa: BLE001
            log.debug("tile update multiple gagal: %s", e)

    def _sapu_objek(self) -> None:
        """Ambil objek dalam radius yang belum terambil.

        Paket `type 14` hanya datang untuk item yang jatuh SESUDAH bot masuk.
        Item yang sudah ada saat `SendMapData` tidak pernah memicu paket, jadi
        tanpa sapuan ini bot hanya bisa collect satu-dua item lalu diam
        (persis gejala yang dilaporkan).
        """
        if not self._running or not self.local:
            return
        for d in list(self.world.dropped):
            if self._boleh_ambil(d.x, d.y):
                self._auto_ambil(d.uid, d.x, d.y)

    def _boleh_ambil(self, x: float, y: float) -> bool:
        """Apakah objek ini boleh diambil otomatis?

        Urutan prioritas (sama dengan `AutoCollect.sekali`):

        1. **Tile terpilih MENANG** — kalau fitur AutoCollect punya daftar
           `tiles`, hanya objek di tile itu yang diambil. Radius dan
           `auto_collect` diabaikan sepenuhnya.
        2. `auto_collect` NYALA = semua objek dalam `auto_collect_radius`.
        3. `auto_collect` MATI = hanya tile tempat bot berdiri (perilaku
           normal Growtopia: menimpa item = terambil).

        Tanpa aturan (1) di sini, jalur otomatis `_auto_ambil` (dipanggil tiap
        `ItemChangeObject`) menyapu radius walau user sudah memilih tile —
        itu bug "udah diset tile tetap ambil radius".
        """
        if not self.local:
            return False
        pilih = getattr(getattr(self, "fitur", None), "autocollect", None)
        tiles = getattr(pilih, "tiles", None) if pilih is not None else None
        if tiles:
            return (int(x // 32), int(y // 32)) in set(map(tuple, tiles))
        if self.auto_collect:
            return self._in_range_px(x, y, self.auto_collect_radius)
        return (int(x // 32) == self.local.tile_x
                and int(y // 32) == self.local.tile_y)

    def _auto_ambil(self, uid: int, x: float, y: float) -> None:
        """Ambil otomatis satu objek yang jatuh di dekat bot.

        Meniru `automation.lua` deltaX: server mengirim `ItemChangeObject`
        (type 14, netid -1) saat item jatuh, lalu klien menunggu 30 ms dan
        mengirim `ItemActivateObjectRequest` (type 11) untuk uid itu.

        Percobaan dibatasi 3x per uid. Sebagian objek memang tidak bisa
        diambil (mis. item 112 di dunia ini tidak pernah dibalas server);
        tanpa batas, sapuan berkala mengirim type 11 selamanya untuk uid itu.
        """
        if not self._boleh_ambil(x, y):
            return
        uid_i = int(uid)
        now = time.time()
        if self._ambil_n.get(uid_i, 0) >= 3:
            return
        if now < self._ambil_ts.get(uid_i, 0.0):
            return
        self._ambil_n[uid_i] = self._ambil_n.get(uid_i, 0) + 1
        self._ambil_ts[uid_i] = now + 2.0

        def kerja() -> None:
            time.sleep(0.03)   # deltaX: sleep(30)
            if not self._running:
                return
            if not any(o.uid == uid_i for o in self.world.dropped):
                return
            self.collectObject(uid_i)

        threading.Thread(target=kerja, name=f"autocollect-{uid_i}",
                         daemon=True).start()

    def _apply_item_change(self, tank: Tank, ext: bytes) -> None:
        """ItemChangeObject (type 14): item muncul/hilang di dunia.

        TERVERIFIKASI dari paket nyata (bukan tebakan):

            netid = 0xFFFFFFFF (-1)  -> objek BARU muncul
            netid = <netid pemain>   -> objek DIAMBIL pemain itu

        Datanya ada di FIELD TANK, bukan extended (`ext=0` di semua paket):

            value      = uid objek (bukan item id)
            vector_x/y = posisi piksel

        Contoh nyata:
            type=14 netid=-1 pos=(1404,742) value=3    -> item jatuh
            type=14 netid=6  value=11                  -> bot ambil (uid 11)

        Tanpa handler ini `world.dropped` tidak pernah mengecil, jadi
        autocollect mengirim ulang uid yang sudah tidak ada dan berhenti
        setelah satu item.
        """
        try:
            uid = int(tank.value)
            if not uid:
                return
            if int(tank.net_id) in (-1, 0xFFFFFFFF, -3, 0xFFFFFFFD):
                x, y = float(tank.vector_x), float(tank.vector_y)
                # Layout asli `ItemChangeObject` (Gurotopia
                # `database/world.cpp:add_object` + `merge_object`):
                #
                #   netid            = -1 (baru) atau -3 (digabung ke objek lama)
                #   target_net_id    = UID objek          <- BUKAN dikarang sendiri
                #   float_variable   = JUMLAH item        <- BUKAN selalu 1
                #   value            = item id
                #   vector_x/y       = posisi piksel
                #
                # Versi lama mengarang uid dari `last_uid + 1` dan selalu
                # memakai count=1. Akibatnya drop 80 blok hanya terbaca 1, dan
                # uid yang dipakai `ItemActivateObjectRequest` tidak cocok
                # dengan yang dipegang server sehingga pengambilan gagal.
                item_id = int(tank.value)
                jumlah = int(tank.float_variable)
                if jumlah <= 0:
                    jumlah = 1
                uid_asli = int(tank.target_net_id)
                if uid_asli <= 0 or uid_asli == 0x7FFFFFFF:
                    self.world.last_uid = int(self.world.last_uid) + 1
                    uid_asli = int(self.world.last_uid)
                else:
                    # Server memberi uid; simpan supaya penomoran berikutnya
                    # tidak bentrok.
                    if uid_asli > int(self.world.last_uid):
                        self.world.last_uid = uid_asli

                lama = next((o for o in self.world.dropped if o.uid == uid_asli), None)
                if lama is not None:
                    # Objek yang sama di tile yang sama: jumlahnya bertambah.
                    lama.count = min(255, int(lama.count) + jumlah)
                    lama.x, lama.y = x, y
                    self._emit("dropped", uid_asli)
                else:
                    self.world.dropped.append(
                        DroppedItem(item_id=item_id, x=x, y=y,
                                    count=jumlah, uid=uid_asli))
                    self._emit("dropped", uid_asli)
                # Drop di tile X = blok di tile X baru saja pecah. Ini
                # SATU-SATUNYA bukti pecah yang dikirim server (tidak ada
                # paket tile-update untuk punch sendiri, dan `TileApplyDamage`
                # hanya konfirmasi pukulan, sering kurang dari jumlah pukulan).
                self._drop_baru.append((x, y, time.time()))
                if len(self._drop_baru) > 64:
                    del self._drop_baru[:32]
                self.catat_paket("in", 14,
                                 f"DROP uid={uid_asli} item_id={item_id} "
                                 f"count={jumlah} pos=({x:.0f},{y:.0f}) "
                                 f"radius={self.auto_collect_radius * 32}px "
                                 f"auto={self.auto_collect}")
                self._auto_ambil(uid_asli, x, y)
            else:
                # netid = pemain yang mengambil. Kalau itu BOT SENDIRI, server
                # tidak mengirim ulang inventaris (tidak ada type 9/13) — hanya
                # pesan console. Jadi tambahkan sendiri dari data objek yang
                # kita sudah tahu sebelumnya; bukan tebakan, server yang
                # menyatakan objek ini berpindah ke kita.
                diambil = next((o for o in self.world.dropped if o.uid == uid), None)
                self.world.dropped = [o for o in self.world.dropped if o.uid != uid]
                self._emit("picked", uid)
                if diambil is not None and (self.local is None
                                            or int(tank.net_id) == self.local.netid):
                    self.inventory.tambah(diambil.item_id, max(1, diambil.count))
                    self._emit("inventory", self.inventory)
        except Exception as e:  # noqa: BLE001
            log.debug("item change gagal: %s", e)

    def _apply_state(self, tank: Tank) -> None:
        """Posisi pemain dari paket `State` (type 0).

        Server mengirim gerakan lewat `State`, bukan `SetCharacterState`:
        `net_id` = pemain, `vector_x/vector_y` = posisi PIKSEl. `SetCharacterState`
        (type 20) di server ini datang dengan extended kosong, jadi tidak bisa
        dipakai. Tanpa handler ini `self.local` tak pernah terisi dan semua
        perintah gerak balas `{"ok": false}`.
        """
        try:
            netid = int(tank.net_id)
            if netid in (0, 0xFFFFFFFF) or netid < 0:
                return
            x, y = float(tank.vector_x), float(tank.vector_y)
            if x <= 0.0 and y <= 0.0:
                return
            pl = self.players.get(netid) or Player(netid=netid)
            pl.posx, pl.posy = x, y
            # JANGAN tebak pemain lokal dari "netid pertama tanpa nama": di
            # dunia ini pemain lain (netid 5) bergerak lebih dulu dan sempat
            # dianggap diri sendiri. Netid sendiri hanya dari `SetCharacterState`.
            if pl.name and self.name and pl.name == self.name:
                pl.isLocalPlayer = True
                self.local = pl
            elif self.local is not None and netid == self.local.netid:
                pl.isLocalPlayer = True
                self.local = pl
            self.players[netid] = pl
            self._emit("player_move", pl)
        except Exception as e:  # noqa: BLE001
            log.debug("state gagal: %s", e)

    def _apply_character_state(self, ext: bytes, tank: Optional[Tank] = None) -> None:
        """SetCharacterState: netid sendiri + state (bukan posisi).

        Extended data kosong di server ini; `net_id` ada di header tank dan
        itulah netid bot. Spawn pertama = diri sendiri (bot tak melihat dirinya
        lewat `OnSpawn`).
        """
        try:
            netid = int(tank.net_id) if tank is not None else 0
            if netid in (0, 0xFFFFFFFF):
                if len(ext) < 4:
                    return
                netid = struct.unpack_from("<I", ext, 0)[0]
            pl = self.players.get(netid) or Player(netid=netid)
            if self.local is None:
                pl.isLocalPlayer = True
                self.local = pl
            elif netid == self.local.netid:
                pl.isLocalPlayer = True
                self.local = pl
            self.players[netid] = pl
            self._emit("character_state", pl)
            if (not self._profil_diminta and self.world.tiles
                    and netid == self.local.netid):
                self._profil_diminta = True
                self.minta_profil()
        except Exception as e:  # noqa: BLE001
            log.debug("character state gagal: %s", e)

    def _apply_status(self, ext: bytes) -> None:
        """UpdateStatus (type 2): status pemain, BUKAN sumber level/gems.

        Server retail tidak mengirim `level|`/`gems|` di sini. Gem datang
        lewat variant `OnSetBux`, level lewat dialog profil (`add_player_info`).
        Teks di-parse kalau kebetulan ada (server privat), tapi jangan
        diandalkan.
        """
        if not ext:
            return
        try:
            text = ext.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return
        for line in text.split("\n"):
            if "|" not in line:
                continue
            k, v = line.split("|", 1)
            k = k.strip().lower()
            if k == "level":
                self._set_level(v.strip())
            elif k in ("gems", "gem_count"):
                self._set_gems(v.strip())

    def _set_gems(self, nilai: Any) -> None:
        try:
            n = int(float(nilai))
        except (TypeError, ValueError):
            return
        if n < 0:
            return
        self.gem_count = n
        self._emit("status_update", {"level": self.level, "gems": self.gem_count,
                                     "malady": self.malady})

    def _set_level(self, nilai: Any) -> None:
        try:
            n = int(float(nilai))
        except (TypeError, ValueError):
            return
        if n <= 0:
            return
        self.level = n
        self._emit("status_update", {"level": self.level, "gems": self.gem_count,
                                     "malady": self.malady})

    def _baca_level_dialog(self, teks: str) -> bool:
        """Ambil level dari dialog profil (`add_player_info`).

        Format baris: `add_player_info|<nama>|<level>|<xp>|<xp_next>|`
        Hanya dipakai kalau nilainya masuk akal (1..125), supaya dialog toko
        atau world lock tidak salah tafsir.
        """
        hasil = False
        for baris in teks.split("\n"):
            if baris.startswith(("add_player_info|", "add_player_info_small|")):
                kolom = baris.split("|")
                if len(kolom) >= 3:
                    hasil = self._coba_level(kolom[2]) or hasil
            # Gaya GrowServer: `add_smalltext|Level: 5 (10/100)|`
            elif baris.startswith("add_smalltext|Level:"):
                potong = baris.split("Level:", 1)[1].strip()
                hasil = self._coba_level(potong.split()[0] if potong else "") or hasil
            elif baris.startswith("add_smalltext|Gems:"):
                potong = baris.split("Gems:", 1)[1].strip()
                if potong:
                    self._set_gems(potong.split()[0])
            else:
                self._baca_malady_dialog(baris)
        return hasil

    # Nama malady/illness dari klien (rodata libgrowtopia.so), dipetakan ke
    # teks yang enak dibaca. Kunci = potongan yang dicari di dialog.
    MALADY_NAMA = {
        "ILLNESS_APPENDICITIS": "Appendicitis",
        "ILLNESS_BAD_DISC": "Bad Disc",
        "ILLNESS_BIGTRAUMA": "Big Trauma",
        "ILLNESS_BIRDFLU": "Bird Flu",
        "ILLNESS_BRAIN_TUMOR": "Brain Tumor",
        "ILLNESS_BROKEN_ARM": "Broken Arm",
        "ILLNESS_BROKEN_LEG": "Broken Leg",
        "ILLNESS_HEAD_INJURY": "Head Injury",
        "ILLNESS_HEART_ATTACK": "Heart Attack",
        "ILLNESS_KIDNEY_FAILURE": "Kidney Failure",
        "ILLNESS_LIVER": "Liver Damage",
        "ILLNESS_LOVESTRUCK": "Lovestruck",
        "ILLNESS_LUNG_TUMOR": "Lung Tumor",
        "ILLNESS_MONKEYFLU": "Monkey Flu",
        "ILLNESS_NOSEJOB": "Nose Job",
        "ILLNESS_SHATTERED": "Shattered",
        "ILLNESS_TRAUMA": "Trauma",
        "ILLNESS_TURTLEFLU": "Turtle Flu",
        "MALADY_BRAINWORMS": "Brainworms",
        "MALADY_BROKEN_HEART": "Broken Heart",
        "MALADY_CHAOS_INFECTION": "Chaos Infection",
        "MALADY_CHICKEN_FEET": "Chicken Feet",
        "MALADY_ECTO_BONES": "Ecto Bones",
        "MALADY_FATTY_LIVER": "Fatty Liver",
        "MALADY_GEM_CUTS": "Gem Cuts",
        "MALADY_GRUMBLETEETH": "Grumbeteeth",
        "MALADY_LUPUS": "Lupus",
        "MALADY_MOLDY_GUTS": "Moldy Guts",
        "MALADY_TORN_PUNCHING_MUSCLE": "Torn Punching Muscle",
        "MALADY_VICIOUS_BRAINWORMS": "Vicious Brainworms",
        "MALADY_VICIOUS_CHAOS_INFECTION": "Vicious Chaos Infection",
        "MALADY_VICIOUS_ECTO_BONES": "Vicious Ecto Bones",
        "MALADY_VICIOUS_FATTY_LIVER": "Vicious Fatty Liver",
        "MALADY_VICIOUS_LUPUS": "Vicious Lupus",
        "MALADY_VICIOUS_MOLDY_GUTS": "Vicious Moldy Guts",
    }

    # Frasa yang berarti "tidak sakit". Klien menulis `ILLNESS_CURED` /
    # `ILLNESS_NONE` di kondisi normal.
    MALADY_SEHAT = ("ILLNESS_CURED", "ILLNESS_NONE")

    def _baca_malady_dialog(self, baris: str) -> bool:
        """Ambil status malady dari satu baris dialog.

        Format retail belum terdokumentasi; yang ada di binary klien hanya
        potongan teks `%d degrees`` dan `illness.``` . Jadi pemindaian dibuat
        longgar: cocokkan nama konstanta (`MALADY_*` / `ILLNESS_*`) ATAU teks
        yang sudah enak dibaca ("Bird Flu"), lalu simpan sebagai satu string.
        Kalau tidak ketemu, status tidak diubah (bukan dikosongkan) supaya
        dialog toko tidak menghapus nilai yang sudah benar.
        """
        naik = baris.upper()
        for kunci in self.MALADY_SEHAT:
            if kunci in naik:
                self._set_malady("")
                return True
        # Nama terpanjang dulu: `MALADY_VICIOUS_LUPUS` mengandung
        # `MALADY_LUPUS`, jadi urutan naif akan salah petakan.
        for kunci, nama in sorted(self.MALADY_NAMA.items(),
                                  key=lambda kv: len(kv[0]), reverse=True):
            if kunci in naik:
                self._set_malady(nama)
                return True
        # Teks jadi: "Bird Flu" / "Vicious Lupus" dst (tanpa prefix konstanta).
        # Urut dari nama TERPANJANG supaya "Vicious Lupus" tidak tertangkap
        # lebih dulu sebagai "Lupus".
        for nama in sorted(self.MALADY_NAMA.values(), key=len, reverse=True):
            if nama.lower() in baris.lower():
                self._set_malady(nama)
                return True
        return False

    def _set_malady(self, nama: str) -> None:
        nama = (nama or "").strip()
        if nama == self.malady:
            return
        self.malady = nama
        self._emit("status_update", {"level": self.level, "gems": self.gem_count,
                                     "malady": self.malady})

    def _coba_level(self, nilai: Any) -> bool:
        """Terapkan level hanya kalau masuk akal (1..125)."""
        try:
            lvl = int(float(str(nilai).strip()))
        except (TypeError, ValueError):
            return False
        if not 1 <= lvl <= 125:
            return False
        self._set_level(lvl)
        return True

    def minta_profil(self) -> bool:
        """Minta dialog profil diri sendiri = satu-satunya sumber level retail.

        Format teks klien asli (`action|wrench\n|netid|<id>`): setelah server
        mengganti `\n` jadi `|`, `pipes[3]` harus `netid` dan `pipes[4]` = netid
        (lihat `action/wrench.cpp` di Gurotopia). Dialog balasannya memuat
        `add_player_info|<nama>|<level>|<xp>|<xp_next>|`.
        """
        if not self.local:
            return False
        return self.wrenchPlayer(self.local.netid)

    def _save_items(self, ext: bytes) -> None:
        """Terima items.dat dari server (dikompres zlib)."""
        import zlib  # noqa: PLC0415

        data = ext
        try:
            data = zlib.decompress(ext)
        except Exception:  # noqa: BLE001
            pass
        if len(data) < 100:
            return
        path = Path("data/items.dat")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            self.items_db = ItemDatabase.from_bytes(data, source=str(path))
            self._emit("items_loaded", len(self.items_db))
        except Exception as e:  # noqa: BLE001
            log.warning("items.dat tidak bisa dibaca: %s", e)
        self.send_text(M.GenericText, b"action|enter_game\n")

    # ------------------------------------------------------------------ #
    # Pengiriman
    # ------------------------------------------------------------------ #
    def send_text(self, mtype: int, body: bytes) -> bool:
        if not self.host:
            return False
        # Jurnal debug: catat paket keluar.
        try:
            _teks = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
            if int(mtype) == M.GamePacket and len(body) >= P.TANK_SIZE:
                _tk, _ext = P.unpack_tank(body)
                self.catat_paket("out", mtype, f"{self._ringkas_tank(_tk)} ext={len(_ext)}")
            else:
                _baris = [b for b in _teks.split("\n") if "|" in b]
                self.catat_paket("out", mtype, " ".join(_baris)[:300])
        except Exception:  # noqa: BLE001
            pass
        # Hook `onsendpacket` (deltaX). Mengembalikan True = paket dibatalkan
        # dan handler sudah mengirim penggantinya sendiri.
        if not self._dalam_hook and self.on_event:
            try:
                self._dalam_hook = True
                teks = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
                if self.on_event("send_packet", (teks, int(mtype))) is True:
                    return True
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._dalam_hook = False
        with self._lock:
            return self.host.send(P.build_packet(mtype, body))

    def send_packet(self, packet_type: int, packet: str) -> bool:
        """Kirim paket teks (GenericText/GameMessage)."""
        return self.send_text(int(packet_type), str(packet).encode("utf-8"))

    def send_raw(self, tank: Tank | Any, extended: bytes = b"") -> bool:
        """Kirim GamePacket (Tank)."""
        if not self.host:
            return False
        if not isinstance(tank, Tank):
            # Tabel Lua bisa punya field bernilai nil; `getattr` mengembalikan
            # None (bukan default) untuk atribut yang ada tapi kosong, jadi
            # konversi harus lewat helper yang aman.
            def _num(*kunci, bawaan=0, tipe=int):
                for k in kunci:
                    v = getattr(tank, k, None)
                    if v is None:
                        continue
                    try:
                        return tipe(v)
                    except (TypeError, ValueError):
                        continue
                return tipe(bawaan)

            tank = Tank(
                type=_num("type"),
                object_type=_num("object_type"),
                net_id=_num("netid", "net_id"),
                flags=_num("flags"),
                value=_num("item", "value"),
                float_variable=_num("float_var", "state", tipe=float),
                vector_x=_num("vec_x", "x", tipe=float),
                vector_y=_num("vec_y", "y", tipe=float),
                vector_x2=_num("vec2_x", "xs", tipe=float),
                vector_y2=_num("vec2_y", "ys", tipe=float),
                particle_rotation=_num("particle_rotation", tipe=float),
                int_x=_num("int_x", "px"),
                int_y=_num("int_y", "py"),
            )
        if not self._dalam_hook and self.on_event:
            try:
                self._dalam_hook = True
                self.on_event("send_raw", tank)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._dalam_hook = False
        body = tank.to_bytes(extended)
        return self.send_text(M.GamePacket, body)

    # ------------------------------------------------------------------ #
    # AKSI — semuanya mengirim paket nyata ke server
    # ------------------------------------------------------------------ #
    def say(self, text: str) -> bool:
        """Kirim pesan ke dunia.

        Teks yang diawali `/` dicoba dulu sebagai perintah lokal gaya deltaX
        (`/warp`, `/gscan`, `/help`, …). Kalau dikenali, pesan TIDAK dikirim
        ke server dan return True.
        """
        cmds = getattr(getattr(self, "fitur", None), "commands", None)
        if cmds is not None and str(text).strip().startswith("/"):
            try:
                if cmds.handle(text):
                    return True
            except Exception:  # noqa: BLE001
                pass
        self._emit("say", text)
        self.chat.tambah(self.name or "aku", text, "sendiri")
        return self.send_text(M.GenericText, f"action|input\n|text|{text}\n".encode())

    def warp(self, name: str, door_id: str = "0", tunggu: float = 10.0) -> bool:
        """Pindah ke dunia lain.

        Return True hanya kalau server benar-benar mengirim SendMapData untuk
        dunia tujuan (bukan sekadar paket join_request terkirim).
        """
        tujuan = name.strip()
        if not tujuan:
            return False
        self._emit("warp", tujuan)
        awal = self.world.name
        # Server Growtopia hanya memproses join_request lewat GameMessage (3).
        # Dengan GenericText (2) paketnya diterima tapi diabaikan — bot tetap
        # di dunia lama walau tak ada error. Diverifikasi di BESTI 2026-11-04.
        if not self.send_text(
            M.GameMessage, f"action|join_request\nname|{tujuan}\ninvitedWorld|{door_id}\n".encode()
        ):
            return False
        if self.host is None:  # offline/mock: tak ada SendMapData untuk ditunggu
            return True
        batas = time.time() + max(1.0, float(tunggu))
        while time.time() < batas:
            if self.world.name and self.world.name.upper() == tujuan.upper():
                return True
            if self.world.name != awal and self.world.name:
                return True
            time.sleep(0.2)
        return False

    def leaveWorld(self) -> bool:
        return self.send_text(M.GameMessage, b"action|quit_to_exit\n")

    def respawn(self) -> bool:
        return self.send_text(M.GenericText, b"action|respawn\n")

    def kirim(self, action: str, *args: Any, **fields: Any) -> bool:
        """Kirim `action|...` dari tabel `protocol.ACTIONS`.

        75 aksi Growtopia (gohomeworld, store, wardrobe_*, trade_*, mailbox_*,
        dll) sudah dipetakan lengkap dengan field-nya di `P.ACTIONS`, hasil
        ekstraksi literal `libgrowtopia.so`. Jadi tidak perlu satu method per
        fitur — cukup `bot.kirim("gohomeworld")`.

            bot.kirim("storenavigate", item="locks", selection="upgrade_backpack")
            bot.kirim("worldlock_storage_modify_amount", amount=5, type=2)

        Nilai juga boleh diberikan posisional (urutan = urutan field di
        `ACTIONS`), supaya enak dipanggil dari Lua:
            kirim("storenavigate", "locks", "upgrade_backpack")
        """
        spec = P.ACTIONS.get(action)
        if spec is None:
            raise KeyError(f"action tidak dikenal: {action!r}")
        # Dua gaya pemanggilan dari Lua:
        #   kirim("store", "location", "pausemenu")   -> pasangan kunci/nilai
        #   kirim("trade_lock", 1)                    -> posisional
        if args and isinstance(args[0], str) and args[0] in spec:
            if len(args) % 2:
                raise TypeError(
                    f"'{action}': pemanggilan gaya pasangan harus genap "
                    f"(kunci, nilai); diberi {len(args)} argumen"
                )
            for key, val in zip(args[0::2], args[1::2]):
                fields.setdefault(key, val)
        else:
            if len(args) > len(spec):
                raise TypeError(
                    f"'{action}' hanya punya {len(spec)} field ({', '.join(spec)}), "
                    f"diberi {len(args)}"
                )
            for key, val in zip(spec, args):
                fields.setdefault(key, val)
        self._emit("action", (action, fields))
        return self.send_text(M.GenericText, P.build_action(action, **fields))

    def enter(self, password: str = "") -> bool:
        if password:
            return self.send_text(
                M.GenericText,
                f"action|dialog_return\ndialog_name|password_reply\ntilex|{self.local.tile_x if self.local else 0}|\ntiley|{self.local.tile_y if self.local else 0}|\npassword|{password}\n".encode(),
            )
        return self.active(self.local.tile_x if self.local else 0, self.local.tile_y if self.local else 0)

    def use(self, item_id: int) -> bool:
        """Pakai item (konsumabel) — ItemActivateRequest."""
        self._emit("use", item_id)
        return self.send_raw(Tank(type=G.ItemActivateRequest, value=int(item_id)))

    def wear(self, item_id: int) -> bool:
        return self.use(item_id)

    def unwear(self, item_id: int) -> bool:
        return self.use(item_id)

    def drop(self, item_id: int, count: int = 1) -> bool:
        self._emit("drop", (item_id, count))
        return self.send_text(
            M.GenericText, f"action|drop\n|itemID|{int(item_id)}\n|count|{int(count)}\n".encode()
        )

    def trash(self, item_id: int, count: int = 1) -> bool:
        self._emit("trash", (item_id, count))
        return self.send_text(
            M.GenericText, f"action|trash\n|itemID|{int(item_id)}\n|count|{int(count)}\n".encode()
        )

    fastDrop = drop
    fastTrash = trash

    def _tile_change(self, x: int, y: int, value: int) -> bool:
        """Kirim `tileChange` = Tank type 3 (TileChangeRequest).

        Sumber: `lucifer/lua_deltax/library.lua:growtopia.tileChange`.

            x  = posisi PIKSEl asal pukulan
            px = tile x   -> int_x
            py = tile y   -> int_y
            value         -> int_data (18 = Fist = pukul, item id = taruh)

        `x/y` (vector_x/vector_y) wajib: server memakainya untuk cek jangkauan
        dan menolak paket tanpa posisi. Tile kosong atau bibit memakai posisi
        tile (seperti library deltaX), selain itu posisi pemain.
        """
        px, py = float(x * 32), float(y * 32)
        t = self.world.tile(int(x), int(y))
        # Aturan posisi dari `library.lua:tileChange` deltaX: tile KOSONG atau
        # BIBIT memakai posisi tile, selain itu posisi pemain. Tile berisi
        # blok ditaruh/dipukul dari posisi pemain — memakai posisi tile membuat
        # server menganggapnya di luar jangkauan dan menolak diam-diam.
        if t is None or not self.local:
            ox, oy = px, py
        elif t.fg == 0 or t.fg % 2 == 1:
            ox, oy = px, py
        else:
            ox, oy = self.local.posx, self.local.posy
        # Paket State (type 0) lebih dulu: ini yang membuat TANGAN bergerak.
        # Tanpa ini bot terlihat diam lalu blok tiba-tiba terpukul.
        # Nilai `state` dari `library.lua:tileChange` deltaX:
        #   2592/2608 = animasi pukul (kanan/kiri)
        #   3104/3120 = animasi taruh (kanan/kiri)
        if self.local is not None:
            ke_kiri = float(x * 32) < self.local.posx
            if int(value) == ITEM_FIST:
                state = 2608 if ke_kiri else 2592
            else:
                state = 3120 if ke_kiri else 3104
            self.send_raw(
                Tank(
                    type=G.State,
                    int_x=int(x), int_y=int(y),
                    value=int(value),
                    vector_x=ox, vector_y=oy,
                    # offset 16 = field `state` (Gurotopia: `.state = i32[4]`)
                    float_variable=float(state),
                )
            )
        return self.send_raw(
            Tank(
                type=G.TileChangeRequest,
                int_x=int(x), int_y=int(y),
                value=int(value),
                vector_x=ox, vector_y=oy,
            )
        )

    def place(self, x: int, y: int, item: int) -> bool:
        """Pasang blok/bibit di tile (value = item id)."""
        self._emit("place", (x, y, item))
        return self._tile_change(x, y, int(item))

    def hit(self, x: int, y: int) -> bool:
        """Pukul tile. Bukan type 7 (itu pintu/wrench), tapi type 3 value Fist."""
        self._emit("hit", (x, y))
        return self._tile_change(x, y, ITEM_FIST)

    def wrench(self, x: int, y: int) -> bool:
        """Wrench tile: type 3 value 32 (Wrench), sama seperti klien asli."""
        self._emit("wrench", (x, y))
        return self._tile_change(x, y, TILE_ACTIVATE_WRENCH)

    def wrenchPlayer(self, netid: int) -> bool:
        """Wrench pemain (buka profil) = paket TEKS `action|wrench`.

        Klien asli mengirim `action|wrench\n|netid|<id>`; server menormalkan
        `\n` → `|` sehingga `pipes[3] == "netid"`, `pipes[4] == id`
        (`include/action/wrench.cpp`, Gurotopia).
        """
        self._emit("wrench_player", int(netid))
        return self.send_text(
            M.GenericText,
            f"action|wrench\n|netid|{int(netid)}\n".encode(),
        )

    def active(self, x: int, y: int) -> bool:
        """Aktifkan tile (tombol/pintu/objek)."""
        self._emit("active", (x, y))
        return self.send_raw(Tank(type=G.TileActivateRequest, int_x=int(x), int_y=int(y), value=0))

    def collectObject(self, oid: int, range_: int = 3) -> bool:
        """Ambil objek jatuh lewat `ItemActivateObjectRequest` (type 11).

        Sumber: `decrypted_lua/automation.lua` deltaX (`takeObject`):

            pkt.type  = 11
            pkt.x     = object.pos.x      -- PIKSEl, bukan tile
            pkt.y     = object.pos.y
            pkt.px    = object.invbit
            pkt.value = object.id         -- uid objek, bukan item id

        Pemetaan ke TankPacket: `x/y` -> vector_x/vector_y, `px` -> int_x,
        `value` -> value. `action|collect` TIDAK dipakai server — paket inilah
        yang benar.
        """
        self._emit("collect", oid)
        d = next((o for o in self.world.dropped if o.uid == int(oid)), None)
        if d is None:
            return False
        return self.send_raw(
            Tank(
                type=G.ItemActivateObjectRequest,
                value=int(d.uid),
                vector_x=float(d.x),
                vector_y=float(d.y),
                int_x=int(d.count),
            )
        )

    def collect(self, range_: int = 3, interval: int = 0) -> int:
        """Ambil objek jatuh dalam jarak tertentu. Return jumlah yang diambil.

        `range_` dihitung dalam tile; objek yang lebih jauh tetap didekati
        supaya server mengizinkan pengambilan.
        """
        n = 0
        for d in list(self.world.dropped):
            if self._in_range_px(d.x, d.y, range_):
                if self.collectObject(d.uid):
                    n += 1
                if interval:
                    time.sleep(interval / 1000.0)
        return n

    def retrieve(self, x: int, y: int, count: int = 200) -> bool:
        """Ambil isi storage (gaia/seed pack) di tile."""
        return self.send_text(
            M.GenericText, f"action|retrieve\n|tilex|{int(x)}\n|tiley|{int(y)}\n|count|{int(count)}\n".encode()
        )

    def buy(self, store_id_or_item, count: int = 0, max_price: int = 0) -> bool:
        if isinstance(store_id_or_item, str) and not count:
            return self.send_text(
                M.GenericText, f"action|buy\n|itemID|{store_id_or_item}\n".encode()
            )
        return self.send_text(
            M.GenericText,
            f"action|buy\n|itemID|{int(store_id_or_item)}\n|count|{int(count)}\n|max_price|{int(max_price)}\n".encode(),
        )

    # -- gerakan --------------------------------------------------------- #
    def moveTo(self, dx: int, dy: int) -> bool:
        """Geser sebesar dx,dy tile dari posisi sekarang, satu tile per paket.

        Server menolak lompatan jauh (validasi kecepatan), jadi kirim bertahap
        seperti klien asli, bukan satu paket 3 tile sekaligus.
        """
        if not self.local:
            return False
        langkah = max(abs(dx), abs(dy))
        if langkah == 0:
            return True
        sx = (dx > 0) - (dx < 0)
        sy = (dy > 0) - (dy < 0)
        kecepatan = 123.0  # px/detik; di atas ~300 server menolak (speedhack)
        ok = True
        for _ in range(langkah):
            ok = self._send_move(
                self.local.posx + sx * 32.0, self.local.posy + sy * 32.0,
                kecepatan_x=sx * kecepatan, kecepatan_y=sy * kecepatan,
                jeda=32.0 / kecepatan,
            ) and ok
        return ok

    def moveTile(self, x: int, y: int) -> bool:
        """Pindah ke tile absolut (x,y) dengan kecepatan wajar.

        Tanpa kecepatan di `vector_x2/vector_y2` server menolak paket sebagai
        speedhack walau jaraknya cuma satu tile.
        """
        tx, ty = float(x * 32.0), float(y * 32.0)
        vx = vy = 0.0
        if self.local:
            dx = tx - self.local.posx
            dy = ty - self.local.posy
            if dx or dy:
                jarak = (dx * dx + dy * dy) ** 0.5
                vx, vy = dx / jarak * 123.0, dy / jarak * 123.0
        return self._send_move(tx, ty, kecepatan_x=vx, kecepatan_y=vy, jeda=0.26)

    def moveLeft(self, range_: int = 1) -> bool:
        return self.moveTo(-abs(int(range_)), 0)

    def moveRight(self, range_: int = 1) -> bool:
        return self.moveTo(abs(int(range_)), 0)

    def moveUp(self, range_: int = 1) -> bool:
        return self.moveTo(0, -abs(int(range_)))

    def moveDown(self, range_: int = 1) -> bool:
        return self.moveTo(0, abs(int(range_)))

    def _send_move(
        self, x: float, y: float, jeda: float = 0.0,
        kecepatan_x: float = 0.0, kecepatan_y: float = 0.0,
    ) -> bool:
        """Kirim State; posisi lokal diperbarui sendiri (prediksi).

        Server Growtopia TIDAK mengecho `State`/`SetCharacterState` balik ke
        pengirim — diverifikasi lewat dump paket: setelah kirim State, tak ada
        satu pun paket netid sendiri yang masuk (deltaX pun memakai prediksi
        lokal, lihat `library.lua`). Menunggu echo = selalu gagal. Jadi: kirim,
        lalu anggap berhasil kalau paket keluar; kalau kebetulan ada echo,
        posisi diperbaiki dari data server.
        """
        self._emit("move", (round(x, 1), round(y, 1)))
        # Pola diambil dari paket `State` pemain NYATA di server ini
        # (diverifikasi dari jurnal paket, bukan tebakan):
        #
        #   type=0 netid=12 tile=(-1,-1) pos=(1717,834) vec2=(121,0)  flags=0x20
        #   type=0 netid=12 tile=(-1,-1) pos=1719,834  vec2=(-84,0)  flags=0x30
        #
        # int_x/int_y = -1 (bukan nomor tile!), flags 0x20 = hadap kanan,
        # 0x10 ditambahkan saat hadap kiri (0x30). Mengisi int_x dengan
        # x//32 membuat server mengabaikan paket.
        arah_kiri = kecepatan_x < 0
        tank = Tank(
            type=G.State,
            vector_x=float(x),
            vector_y=float(y),
            # vector_x2/vector_y2 = KECEPATAN (px/detik), bukan posisi.
            vector_x2=float(kecepatan_x),
            vector_y2=float(kecepatan_y),
            int_x=-1,
            int_y=-1,
            flags=0x30 if arah_kiri else 0x20,
        )
        # net_id sengaja 0: deltaX (`library.lua:tileChange`) juga tidak pernah
        # mengisi netid — server mengenali pengirim dari koneksi, dan menebak
        # netid sendiri berisiko menggeser avatar pemain lain.
        if not self.send_raw(tank):
            return False
        # Prediksi lokal: tanpa ini panggilan `move` beruntun selalu dihitung
        # dari posisi lama dan bot kembali ke tempat semula.
        if self.local:
            self.local.posx, self.local.posy = float(x), float(y)
            self.players[self.local.netid] = self.local
            self._emit("player_move", self.local)
        if jeda > 0:
            time.sleep(float(jeda))
        return True

    def setDirection(self, faceleft: bool) -> bool:
        return self.send_raw(Tank(type=G.State, object_type=1 if faceleft else 0))

    def setSkin(self, skin_id: int) -> bool:
        return self.send_raw(Tank(type=G.SetCharacterState, value=int(skin_id)))

    def setBubble(self, bubble) -> bool:
        val = {"none": 0, "talk": 1, "brb": 2}.get(str(bubble).lower(), 0)
        return self.send_raw(Tank(type=G.SetIconState, value=val))

    # -- pathfinding ------------------------------------------------------ #
    def getPath(self, x: int, y: int) -> list[tuple[int, int]]:
        """BFS sederhana di atas tile dunia. Return list (x,y) atau []."""
        if not self.local or not self.world.tiles:
            return []
        sx, sy = self.local.tile_x, self.local.tile_y
        tx, ty = int(x), int(y)
        if (sx, sy) == (tx, ty):
            return []
        if not self.world.tile(tx, ty):
            return []

        def walkable(cx: int, cy: int) -> bool:
            t = self.world.tile(cx, cy)
            if t is None:
                return False
            # blok solid tanpa akses tidak dilewati; pintu/plaftorm dilewati
            return not (t.fg and t.fg not in (0,))

        seen = {(sx, sy)}
        queue: collections.deque[tuple[int, int, list]] = collections.deque([(sx, sy, [])])
        limit = 20000
        steps = 0
        while queue and steps < limit:
            steps += 1
            cx, cy, path = queue.popleft()
            if (cx, cy) == (tx, ty):
                return path
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in seen or not walkable(nx, ny):
                    continue
                seen.add((nx, ny))
                queue.append((nx, ny, path + [(nx, ny)]))
        return []

    def findPath(self, x: int, y: int) -> bool:
        """Cari jalan lalu tempuh tile per tile."""
        path = self.getPath(x, y)
        if not path:
            return False
        for (px, py) in path:
            self.moveTile(px, py)
            time.sleep((self.move_interval or 120) / 1000.0)
        return True

    findWorldPath = findPath

    def _in_range_px(self, x: float, y: float, range_: int) -> bool:
        if not self.local:
            return False
        return abs(x - self.local.posx) <= range_ * 32 and abs(y - self.local.posy) <= range_ * 32

    # -- util ------------------------------------------------------------- #
    def hasAccess(self, x: int, y: int) -> bool:
        t = self.world.tile(int(x), int(y))
        if not t:
            return False
        return (not t.is_locked) or t.owner_uid == (self.local.userid if self.local else -1)

    def getItemCount(self, item_id) -> int:
        return self.inventory.getItemCount(item_id)

    def itemName(self, item_id: int) -> str:
        if not self.items_db:
            return f"#{item_id}"
        return self.items_db.name_of(int(item_id))

    def findItemId(self, name: str) -> int:
        if not self.items_db:
            return 0
        found = self.items_db.find(name, exact=True) or self.items_db.find(name)
        return found[0].id if found else 0

    def wait_for_world(self, timeout: float = 20.0) -> bool:
        """Tunggu sampai data dunia termuat."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.world.tiles:
                return True
            time.sleep(0.2)
        return False

    def wait_until_online(self, timeout: float = 30.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.status == BotStatus.online:
                return True
            time.sleep(0.2)
        return False

    def stats(self) -> dict[str, Any]:
        """Ringkasan untuk CLI / Web UI."""
        return {
            "label": self.label,
            "name": self.name,
            "status": self.status,
            "ping": self.ping,
            "server": f"{self.server[0]}:{self.server[1]}" if self.server[0] else "",
            "world": self.world.name,
            "world_size": f"{self.world.width}x{self.world.height}",
            "tiles": len(self.world.tiles),
            "players": len(self.players),
            "dropped": len(self.world.dropped),
            "inventory_items": len(self.inventory.items),
            "level": self.level,
            "gems": self.gem_count,
            "malady": self.malady,
            "active_time": self.getActiveTime(),
            "captcha": self.captcha_status,
            "redirected": self.redirected,
            "proxy": self.proxy or "",
            "recent": list(self._action_log)[-12:],
        }
