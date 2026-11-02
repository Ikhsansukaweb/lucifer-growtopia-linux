"""
lucifer.bot — Bot Growtopia: koneksi, state dunia, dan semua aksi.

Kelas Bot adalah jantung aplikasi: ia menyimpan koneksi ENet, identitas akun,
dunia yang sedang dimuat, inventaris, pemain lain, dan menyediakan aksi nyata
(chat, warp, tanam, pukul, koleksi, jalan, pathfinding).

API-nya sengaja dibuat SAMA dengan struktur `Bot` di dokumentasi Lucifer V1.8,
supaya skrip Lua yang ditulis untuk Lucifer bisa jalan di sini.
"""

from __future__ import annotations

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
from .protocol import NetGamePacket as G, NetMessage as M, Tank
from .world import Tile, World, parse_world

log = logging.getLogger("lucifer.bot")

# ID item penting
ITEM_WRENCH = 18
ITEM_FIST = 0


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


TILE_ACTIVATE_WRENCH = ITEM_WRENCH


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

    # alias sesuai docs Lucifer
    findItem = getItemCount

    def canCollect(self, item_id: int) -> bool:
        return True

    def parse(self, data: bytes) -> None:
        """Baca paket SendInventoryState (tank type 9)."""
        self.items.clear()
        try:
            off = 0
            if len(data) < 2:
                return
            # Beberapa versi memakai u16 version, sebagian tidak.
            self.slotcount = data[off] if off < len(data) else 0
            off += 1
            self.itemcount = data[off]
            off += 1
            for _ in range(self.itemcount):
                if off + 4 > len(data):
                    break
                item_id = struct.unpack_from("<H", data, off)[0]
                off += 2
                if item_id == 0:
                    # slot kosong: ada 1 byte tambahan
                    off += 1
                    continue
                if off >= len(data):
                    break
                count = data[off]
                off += 1
                if off >= len(data):
                    break
                flags = data[off]
                off += 1
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
        self.on_event = on_event

        self.host: Optional[ENetHost] = None
        self.world = World()
        self.inventory = Inventory()
        self.console = Console()
        self.log = Log()
        self.signal = Signal()
        self.players: dict[int, Player] = {}
        self.local: Optional[Player] = None
        self.gem_count = 0
        self.level = 0
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
        self.auto_collect = False
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
        res = self.account.login(meta=self.meta)
        if not res.ok:
            self.status = BotStatus.logon_fail
            self._emit("login_failed", res)
            return False
        self._emit("login", res)

        proxy = None
        if self.proxy:
            from .proxy import parse as _parse_proxy  # noqa: PLC0415
            try:
                _p = _parse_proxy(self.proxy)
                proxy = _p.tuple4() if _p else None
            except ValueError as e:
                self._emit("error", f"proxy tidak valid ({e}) — connect tanpa proxy")

        self.status = BotStatus.connecting
        self.host = ENetHost(proxy=proxy)
        self.server = (host, port)
        if not self.host.connect(host, port, timeout_ms):
            self.status = BotStatus.error_connecting
            # ENet connect gagal bisa berarti: (a) Growtopia maintenance —
            # sudah diperiksa di atas, atau (b) jaringan/firewall/IP bermasalah.
            self._emit(
                "error",
                f"ENet connect gagal ke {host}:{port} — cek koneksi internet, "
                f"firewall, atau VPN/proxy. Kalau internet normal, server "
                f"Growtopia mungkin sedang sibuk; coba lagi sebentar.",
            )
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

    # ------------------------------------------------------------------ #
    # Penanganan paket masuk
    # ------------------------------------------------------------------ #
    def _handle_packet(self, raw: bytes) -> None:
        mtype, payload = P.parse_packet(raw)

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

    def _handle_tank(self, tank: Tank, ext: bytes) -> None:
        t = tank.type

        if t == G.CallFunction:
            self._handle_variant(ext, tank)
        elif t == G.SendMapData:
            self.world = parse_world(ext, self.items_db)
            self.players.clear()
            self._emit("world_loaded", self.world)
        elif t == G.SendInventoryState:
            self.inventory.parse(ext)
            self._emit("inventory", self.inventory)
        elif t == G.SendItemDatabaseData:
            self._save_items(ext)
        elif t == G.PingRequest:
            self._reply_ping(tank)
        elif t == G.SendTileUpdateData:
            self._apply_tile_update(ext)
        elif t == G.SetCharacterState:
            self._apply_character_state(ext)
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
            self._emit("dialog", vl.get(2).as_string() if vl.get(2) else "")

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
        elif fn in ("OnTalkBubble",):
            pass

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

    def _apply_tile_update(self, ext: bytes) -> None:
        """Terapkan pembaruan satu tile (SendTileUpdateData)."""
        try:
            if len(ext) < 8:
                return
            tx, ty = struct.unpack_from("<ii", ext, 0)
            off = 8
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

    def _apply_character_state(self, ext: bytes) -> None:
        """Update posisi/keadaan pemain (SetCharacterState)."""
        try:
            if len(ext) < 4:
                return
            netid = struct.unpack_from("<I", ext, 0)[0]
            off = 4
            if off + 5 > len(ext):
                return
            x, y = struct.unpack_from("<ff", ext, off)
            off += 8
            if off + 1 > len(ext):
                return
            flags = ext[off]
            off += 1
            pl = self.players.get(netid) or Player(netid=netid)
            pl.posx, pl.posy = x, y
            if netid == (self.local.netid if self.local else -1):
                pl.isLocalPlayer = True
                self.local = pl
            self.players[netid] = pl
            self._emit("player_move", pl)
        except Exception as e:  # noqa: BLE001
            log.debug("character state gagal: %s", e)

    def _apply_status(self, ext: bytes) -> None:
        """UpdateStatus: baca level/gems dari payload teks di dalamnya."""
        try:
            text = ext.decode("utf-8", "replace")
            for line in text.split("\n"):
                if "|" not in line:
                    continue
                k, v = line.split("|", 1)
                k = k.strip().lower()
                if k == "level":
                    self.level = int(v.strip() or 0)
                elif k in ("gems", "gem_count"):
                    self.gem_count = int(v.strip() or 0)
            self._emit("status_update", {"level": self.level, "gems": self.gem_count})
        except Exception:  # noqa: BLE001
            pass

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
            tank = Tank(
                type=int(getattr(tank, "type", 0)),
                object_type=int(getattr(tank, "object_type", 0)),
                net_id=int(getattr(tank, "netid", getattr(tank, "net_id", 0))),
                flags=int(getattr(tank, "flags", 0)),
                value=int(getattr(tank, "item", getattr(tank, "value", 0))),
                float_variable=float(getattr(tank, "float_var", 0.0)),
                vector_x=float(getattr(tank, "vec_x", 0.0)),
                vector_y=float(getattr(tank, "vec_y", 0.0)),
                vector_x2=float(getattr(tank, "vec2_x", 0.0)),
                vector_y2=float(getattr(tank, "vec2_y", 0.0)),
                particle_rotation=float(getattr(tank, "particle_rotation", 0.0)),
                int_x=int(getattr(tank, "int_x", 0)),
                int_y=int(getattr(tank, "int_y", 0)),
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
        return self.send_text(M.GenericText, f"action|input\n|text|{text}\n".encode())

    def warp(self, name: str, door_id: str = "0") -> bool:
        """Pindah ke dunia lain."""
        self._emit("warp", name)
        return self.send_text(
            M.GenericText, f"action|join_request\nname|{name}\ninvitedWorld|{door_id}\n".encode()
        )

    def leaveWorld(self) -> bool:
        return self.send_text(M.GenericText, b"action|quit_to_exit\n")

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

    def place(self, x: int, y: int, item: int) -> bool:
        """Pasang blok di posisi tile."""
        self._emit("place", (x, y, item))
        return self.send_raw(
            Tank(type=G.TileChangeRequest, int_x=int(x), int_y=int(y), value=int(item))
        )

    def hit(self, x: int, y: int) -> bool:
        """Pukul tile."""
        self._emit("hit", (x, y))
        return self.send_raw(Tank(type=G.TileActivateRequest, int_x=int(x), int_y=int(y), value=0))

    def wrench(self, x: int, y: int) -> bool:
        """Wrench tile."""
        self._emit("wrench", (x, y))
        return self.send_raw(
            Tank(type=G.TileActivateRequest, int_x=int(x), int_y=int(y), value=TILE_ACTIVATE_WRENCH)
        )

    def wrenchPlayer(self, netid: int) -> bool:
        """Wrench pemain (buka profil)."""
        pl = self.players.get(int(netid))
        if not pl:
            return False
        return self.wrench(pl.tile_x, pl.tile_y)

    def active(self, x: int, y: int) -> bool:
        """Aktifkan tile (tombol/pintu/objek)."""
        self._emit("active", (x, y))
        return self.send_raw(Tank(type=G.TileActivateRequest, int_x=int(x), int_y=int(y), value=0))

    def collectObject(self, oid: int, range_: int = 3) -> bool:
        """Ambil objek jatuh berdasarkan object id."""
        self._emit("collect", oid)
        return self.send_text(M.GenericText, f"action|collect\n|objectID|{int(oid)}\n".encode())

    def collect(self, range_: int = 3, interval: int = 0) -> int:
        """Ambil semua objek dalam jarak tertentu. Return jumlah yang diambil."""
        n = 0
        for d in list(self.world.dropped):
            if self._in_range_px(d.x, d.y, range_):
                self.collectObject(d.uid)
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
        """Geser sebesar dx,dy tile dari posisi sekarang."""
        if not self.local:
            return False
        x = self.local.posx + dx * 32
        y = self.local.posy + dy * 32
        return self._send_move(x, y)

    def moveTile(self, x: int, y: int) -> bool:
        return self._send_move(x * 32.0, y * 32.0)

    def moveLeft(self, range_: int = 1) -> bool:
        return self.moveTo(-abs(int(range_)), 0)

    def moveRight(self, range_: int = 1) -> bool:
        return self.moveTo(abs(int(range_)), 0)

    def moveUp(self, range_: int = 1) -> bool:
        return self.moveTo(0, -abs(int(range_)))

    def moveDown(self, range_: int = 1) -> bool:
        return self.moveTo(0, abs(int(range_)))

    def _send_move(self, x: float, y: float) -> bool:
        self._emit("move", (round(x, 1), round(y, 1)))
        return self.send_raw(
            Tank(
                type=G.State,
                vector_x=float(x),
                vector_y=float(y),
                vector_x2=float(x),
                vector_y2=float(y),
                net_id=self.local.netid if self.local else 0,
            )
        )

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
            "active_time": self.getActiveTime(),
            "captcha": self.captcha_status,
            "redirected": self.redirected,
            "proxy": self.proxy or "",
            "recent": list(self._action_log)[-12:],
        }
