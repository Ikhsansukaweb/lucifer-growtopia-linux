"""
lucifer.lua_api — Implementasi API Lua Lucifer V1.8 untuk Linux.

Modul ini mengekspos ke Lua SELURUH permukaan API yang didokumentasikan di
`docs/functions.md`, `docs/structs.md`, dan `docs/enums.md` milik Lucifer:

  Global     : sleep, print, read, write, getInfo, getInfos, addBot, removeBot,
               getBot, addUbiBot, addEvent, listenEvents, unlistenEvents,
               removeEvent, removeEvents, removeColor, getProxyManager,
               getWorldManager, addProxy, removeProxy, getUsername, runThread
  Shortcut   : getTile, getTiles, getTilesSafe, getObject, getObjects, getPlayer,
               getPlayers, getNPC, getNPCs, getLocal, hasAccess, getWorld,
               getInventory
  Struct     : Bot, World, Tile, Player, Inventory, InventoryItem, ItemInfo,
               NetObject, NPC, Signal, Console, Log, Login, PathNode, Growscan,
               GameUpdatePacket, Vector2, Vector3, variant, variantlist,
               RTParam, RTVAR, Embed, Webhook, HttpResult, HttpClient,
               ProxyManager, WorldManager
  Enum       : BotStatus, CaptchaStatus, Method, Event, VariantType, GeigerArea,
               Role, Bubble, StorageType, Proxy, PlayerState, TileType, TileFlag,
               NpcType, PacketType

Catatan: skrip Lua Lucifer ditulis dengan gaya `obj:method(...)`. Semua method
di sini menerima `self` sebagai argumen pertama agar gaya itu bekerja.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import protocol as P
from .account import Account
from .bot import Bot, BotStatus, InventoryItem, Player
from .items import ItemDatabase
from .protocol import NetGamePacket as G, NetMessage as M, Tank
from .world import TILE_FLAGS

log = logging.getLogger("lucifer.lua")

try:
    from lupa import LuaRuntime  # type: ignore
except ImportError as e:  # pragma: no cover
    raise RuntimeError(
        "Butuh paket 'lupa' untuk menjalankan skrip Lua.\n"
        "Install: pip install lupa"
    ) from e


COLOR_RE = re.compile(r"`[a-zA-Z0-9#]")


def remove_color(text: str) -> str:
    """Hapus kode warna Growtopia (`4, `c, `#, ...).

    Delegasi ke `protocol.remove_color` supaya hanya ada SATU definisi regex
    kode warna di seluruh proyek (versi `protocol` bisa dipakai tanpa `lupa`).
    """
    return P.remove_color(text)


# Penjelasan penyebab kegagalan login, dipakai agar pesan di dashboard
# langsung memberi tahu apa yang harus dilakukan pengguna.
_HINT_LOGIN = (
    (("wrong password", "incorrect password", "invalid password", "password is incorrect"),
     "sandi salah — periksa nama GrowID dan sandi"),
    # "Please try again in 30 seconds" / "too many request_token commands"
    (("try login again", "try again", "too many", "rate limit"),
     "server membatasi login (rate-limit/cooldown) — tunggu sesuai detik di pesan, "
     "jangan connect berulang karena cooldown makin panjang"),
    (("captcha", "are you human"), "server minta verifikasi — buka Growtopia resmi sekali untuk menyelesaikannya"),
    (("verify", "verification", "not verified"), "akun belum diverifikasi — cek email di growtopiagame.com"),
    (("suspend", "banned", "is ban"), "akun terkena sanksi dari Growtopia"),
    (("banned device", "device id"), "perangkat/IP diblokir sementara"),
    (("server is full", "server full", "overload", "busy", "try later"), "server Growtopia penuh — coba lagi sebentar"),
    (("name", "length"), "nama akun tidak valid (terlalu pendek/panjang)"),
    (("expired", "invalid token", "token invalid", "token mismatch",
      "token is invalid", "login token"), 
     "ltoken tidak valid/kedaluwarsa — ambil ltoken baru lewat panel Login"),
    (("guest",), "batas akun tamu — daftarkan akun GrowID"),
    (("connection", "timeout", "timed out"), "koneksi ke server Growtopia bermasalah — cek internet"),
)


def _hint_login(pesan: str) -> str:
    """Terjemahkan pesan penolakan server jadi saran praktis (atau '')."""
    low = str(pesan).lower()
    for kunci, saran in _HINT_LOGIN:
        if any(k in low for k in kunci):
            return saran
    return ""


# --------------------------------------------------------------------------- #
# HTTP helper (untuk HttpClient / Webhook)
# --------------------------------------------------------------------------- #
class HttpResult:
    def __init__(self, status: int = 0, body: str = "", error: int = 0, error_msg: str = "") -> None:
        self.status = status
        self.body = body
        self.error = error
        self._error_msg = error_msg

    def getError(self) -> str:
        return self._error_msg

    def __repr__(self) -> str:
        return f"HttpResult(status={self.status}, error={self.error})"


class HttpClient:
    def __init__(self) -> None:
        self.content = ""
        self.method = "GET"
        self.headers: dict[str, str] = {}
        self.url = ""
        self._proxy: Optional[tuple[str, str]] = None

    def setMethod(self, method) -> None:
        self.method = str(method).upper()

    def setProxy(self, proxy_type, proxydata: str) -> None:
        scheme = str(proxy_type).lower()
        if scheme in ("none", ""):
            self._proxy = None
        else:
            self._proxy = (scheme, proxydata)

    def removeProxy(self) -> None:
        self._proxy = None

    def request(self) -> HttpResult:
        try:
            data = self.content.encode("utf-8") if self.content else None
            req = urllib.request.Request(self.url, data=data, method=self.method.upper() or "GET")
            for k, v in (self.headers or {}).items():
                req.add_header(str(k), str(v))
            if self._proxy:
                scheme, addr = self._proxy
                if scheme.startswith("http"):
                    opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({"http": addr, "https": addr})
                    )
                    resp = opener.open(req, timeout=30)
                else:
                    return HttpResult(0, "", 1, f"proxy '{scheme}' belum didukung (butuh PySocks)")
            else:
                resp = urllib.request.urlopen(req, timeout=30)
            body = resp.read().decode("utf-8", "replace")
            return HttpResult(resp.status, body)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            return HttpResult(e.code, body, 0, "")
        except Exception as e:  # noqa: BLE001
            return HttpResult(0, "", 1, f"{type(e).__name__}: {e}")


class Embed:
    def __init__(self) -> None:
        self.use = False
        self.color = 0
        self.title = ""
        self.type = "rich"
        self.description = ""
        self.url = ""
        self.thumbnail = ""
        self.image = ""
        self.footer: dict[str, str] = {"text": "", "icon_url": ""}
        self.author: dict[str, str] = {"name": "", "url": "", "icon_url": ""}
        self.fields: list[dict[str, Any]] = []

    def addField(self, name: str, value: str, is_inline: bool = False) -> None:
        self.fields.append({"name": str(name), "value": str(value), "inline": bool(is_inline)})

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"title": self.title, "type": self.type, "description": self.description}
        if self.color:
            d["color"] = int(self.color)
        if self.url:
            d["url"] = self.url
        if self.footer.get("text"):
            d["footer"] = self.footer
        if self.author.get("name"):
            d["author"] = self.author
        if self.fields:
            d["fields"] = self.fields
        if self.thumbnail:
            d["thumbnail"] = {"url": self.thumbnail}
        if self.image:
            d["image"] = {"url": self.image}
        return d


class Webhook:
    def __init__(self, url: str = "") -> None:
        self.url = url
        self.content = ""
        self.username = ""
        self.avatar_url = ""
        self.embed1 = Embed()
        self.embed2 = Embed()
        self._last_id: Optional[int] = None

    def makeContent(self) -> str:
        payload: dict[str, Any] = {}
        if self.content:
            payload["content"] = self.content
        if self.username:
            payload["username"] = self.username
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        embeds = [e.to_dict() for e in (self.embed1, self.embed2) if getattr(e, "use", False)]
        if embeds:
            payload["embeds"] = embeds
        return json.dumps(payload)

    def send(self) -> bool:
        try:
            req = urllib.request.Request(
                self.url,
                data=self.makeContent().encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            try:
                self._last_id = json.loads(body).get("id")
            except Exception:  # noqa: BLE001
                pass
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("webhook gagal: %s", e)
            return False

    def edit(self, message_id) -> bool:
        try:
            url = f"{self.url}/messages/{int(message_id)}"
            req = urllib.request.Request(
                url, data=self.makeContent().encode(),
                headers={"Content-Type": "application/json"}, method="PATCH",
            )
            urllib.request.urlopen(req, timeout=20).read()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("webhook edit gagal: %s", e)
            return False


class RTVAR:
    """Runtime variable (key|value) seperti RTVAR Lucifer."""

    def __init__(self, initial: str = "") -> None:
        self._params: list[tuple[str, str, bool]] = []
        if initial:
            self.parse(initial)

    def append(self, key: str, value, separator: bool = False) -> None:
        self._params.append((str(key), str(value), bool(separator)))

    def parse(self, text: str) -> None:
        self._params.clear()
        for line in str(text).split("\n"):
            if not line:
                continue
            if "|" in line:
                k, v = line.split("|", 1)
                self._params.append((k, v, False))
            else:
                self._params.append((line, "", False))

    def dump(self) -> str:
        return "\n".join(f"{k}|{v}" for k, v, _ in self._params)

    def params(self) -> str:
        return self.dump()

    def contains(self, key: str) -> bool:
        return any(k == str(key) for k, _, _ in self._params)

    def get(self, key: str) -> str:
        for k, v, _ in self._params:
            if k == str(key):
                return v
        return ""

    def getInt(self, key: str) -> int:
        try:
            return int(float(self.get(key) or 0))
        except ValueError:
            return 0

    getLong = getInt

    def getParam(self, key: str):
        return (self.get(key), False) if self.contains(key) else None

    def getParams(self, key: str) -> list[str]:
        return [v for k, v, _ in self._params if k == str(key)]

    def erase(self, key: str) -> None:
        self._params = [p for p in self._params if p[0] != str(key)]

    def size(self) -> int:
        return len(self._params)

    def modify(self, key: str, parameters, hasSeperator: bool = False) -> None:
        self.erase(key)
        for p in parameters or []:
            self.append(key, p, hasSeperator)

    def find(self, key: str):
        return self.getParam(key)


# --------------------------------------------------------------------------- #
# Enum Lucifer
# --------------------------------------------------------------------------- #
ENUMS: dict[str, dict[str, Any]] = {
    "BotStatus": {
        "offline": "offline", "online": "online", "wrong_password": "wrong_password",
        "account_banned": "account_banned", "location_banned": "location_banned",
        "version_update": "version_update",
        "advanced_account_protection": "advanced_account_protection",
        "server_overload": "server_overload", "too_many_login": "too_many_login",
        "maintenance": "maintenance", "server_busy": "server_busy",
        "guest_limit": "guest_limit", "http_block": "http_block",
        "bad_name_length": "bad_name_length", "invalid_account": "invalid_account",
        "error_connecting": "error_connecting", "logon_fail": "logon_fail",
        "captcha_requested": "captcha_requested", "mod_entered": "mod_entered",
        "high_load": "high_load", "connecting": "connecting",
    },
    "CaptchaStatus": {
        "no_captcha": "no_captcha", "not_found": "not_found", "solved": "solved",
        "solving": "solving", "wrong": "wrong", "failed": "failed",
        "no_access": "no_access", "invalid_key": "invalid_key", "invalid_token": "invalid_token",
    },
    "Method": {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH",
               "delete": "DELETE", "head": "HEAD"},
    "Event": {"variantlist": "variantlist", "game_message": "game_message",
              "generic_text": "generic_text", "update_packet": "update_packet",
              "track_packet": "track_packet", "console": "console",
              "world_loaded": "world_loaded", "tile_update": "tile_update",
              "player_move": "player_move", "inventory": "inventory",
              "say": "say", "warp": "warp", "connected": "connected",
              "disconnected": "disconnected", "logon_fail": "logon_fail",
              "captcha": "captcha", "login": "login", "entering_game": "entering_game"},
    "VariantType": {"float": 1, "string": 2, "vector2": 3, "vector3": 4,
                    "uint32": 5, "int32": 9, "unused": 0, "component": 6,
                    "entity": 7, "unknown": 0},
    "GeigerArea": {"null": 0, "red": 1, "yellow": 2, "green": 3, "rapid": 4, "prize": 5},
    "Role": {"farm": 0, "build": 1, "surg": 2, "fish": 3, "cook": 4, "startopia": 5},
    "Bubble": {"none": 0, "talk": 1, "brb": 2},
    "StorageType": {"pack": 0, "seed": 1},
    "Proxy": {"none": "none", "http": "http", "https": "https", "socks5": "socks5"},
    "PlayerState": {"none": 0, "moving": 1, "idle": 2},
    "TileType": {"basic": 0, "sign": 1, "door": 2, "lock": 3, "seed": 4, "mailbox": 6,
                 "bulletin": 7, "dice": 8, "chemical": 9, "achievement": 10,
                 "heart_monitor": 11, "donation_box": 12, "mannequin": 14,
                 "game_pack": 16, "game_generator": 17, "crystal": 20, "spotlight": 22,
                 "display_block": 23, "vending": 24, "fish_tank": 25, "forge": 27,
                 "giving_tree": 28, "steam_organ": 30, "silk_worm": 31,
                 "sewing_machine": 32, "country_flag": 33, "weather_machine": 40,
                 "storage": 54, "cooking_oven": 55, "audio_rack": 56},
    "TileFlag": {k: v for k, v in TILE_FLAGS.items()},
    "NpcType": {"ghost": 0, "pinata": 1, "other": 2},
    "LoginMethod": {"legacy": 0, "growid": 0, "google": 1, "ubiconnect": 2,
                    "token": 3, "apple": 4, "steam": 5},
    "PacketType": {name: int(member) for name, member in G.__members__.items()},
}

# Nama tambahan agar `PacketType.PACKET_STATE` dsb. juga dikenali
ENUMS["PacketType"].update(
    {f"PACKET_{name.upper()}": int(member) for name, member in G.__members__.items()}
)

# Konstanta jenis akun yang bisa dipakai langsung: addBot({ type = GOOGLE })
ACCOUNT_TYPE_CONSTS: dict[str, int] = {
    "LEGACY": 0, "GROWID": 0, "GOOGLE": 1, "UBICONNECT": 2,
    "TOKEN": 3, "APPLE": 4, "STEAM": 5,
}


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class LuaEngine:
    """Menjalankan skrip Lua Lucifer di atas satu atau banyak Bot.

    Peran:
      * membuat LuaRuntime (lupa) dan mendaftarkan seluruh API Lucifer
      * memuat file skrip (.lua) dari folder scripts/
      * menjembatani event dari bot (Python thread) ke fungsi Lua (addEvent)
      * menyediakan sleep/runThread yang bisa dihentikan
    """

    def __init__(
        self,
        accounts: Optional[list[Account]] = None,
        items_db: Optional[ItemDatabase] = None,
        scripts_dir: str | Path = "scripts",
        data_dir: str | Path = "data",
        username: str = "linux",
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.accounts = accounts or []
        self.items_db = items_db
        self.scripts_dir = Path(scripts_dir)
        self.data_dir = Path(data_dir)
        self.username = username
        self.on_log = on_log

        self.bots: dict[str, Bot] = {}
        self.parent: Optional[Bot] = None
        self.events: dict[str, list[Any]] = {}
        self.threads: list[threading.Thread] = []
        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._stop = threading.Event()
        # Hentikan HANYA skrip yang sedang jalan. Dipisah dari `_stop` karena
        # `stop()` juga memutus koneksi semua bot — user yang cuma ingin
        # menghentikan loop Lua tidak boleh ikut keluar dari dunia.
        self._script_stop = threading.Event()
        self._listening = False
        self._listen_until = 0.0
        self._lua_lock = threading.RLock()
        self._loaded_files: list[Path] = []
        self._scripts: dict[str, str] = {}
        self.console_lines: list[str] = []

        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self._register_api()

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    def log_line(self, text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        self.console_lines.append(line)
        if len(self.console_lines) > 500:
            del self.console_lines[:100]
        if self.on_log:
            self.on_log(line)
        else:
            print(line, flush=True)

    # ------------------------------------------------------------------ #
    # Registrasi API
    # ------------------------------------------------------------------ #
    def _register_api(self) -> None:
        lua = self.lua
        g = lua.globals()

        # --- dasar --------------------------------------------------------- #
        def lua_print(*args):
            self.log_line(" ".join(str(a) for a in args))
        g.print = lua_print
        g.sleep = self._sleep
        g.read = self._read_file
        g.write = self._write_file
        g.removeColor = lambda text: remove_color(text)
        g.getUsername = lambda: self.username

        # --- item database ------------------------------------------------- #
        g.getInfo = self._get_info
        g.getInfos = self._get_infos

        # --- bot ----------------------------------------------------------- #
        g.addBot = self._add_bot
        g.addUbiBot = self._add_ubi_bot
        g.removeBot = self._remove_bot
        g.getBot = self._get_bot

        # --- event --------------------------------------------------------- #
        g.addEvent = self._add_event
        g.removeEvent = self._remove_event
        g.removeEvents = self._remove_events
        g.listenEvents = self._listen_events
        g.unlistenEvents = self._unlisten_events
        g.runThread = self._run_thread

        # --- proxy --------------------------------------------------------- #
        g.getProxyManager = self._get_proxy_manager
        g.getWorldManager = self._get_world_manager
        g.addProxy = self._add_proxy
        g.removeProxy = self._remove_proxy

        # --- shortcut ------------------------------------------------------ #
        g.getWorld = lambda bot=None: self._world_of(bot)
        g.getInventory = lambda bot=None: self._inventory_of(bot)
        g.getLocal = lambda bot=None: self._local_of(bot)
        g.getTile = lambda x, y, bot=None: self._tile_of(x, y, bot)
        g.getTiles = lambda bot=None: self._tiles_of(bot)
        g.getTilesSafe = lambda bot=None: self._tiles_of(bot)
        g.getObject = lambda oid, bot=None: self._object_of(oid, bot)
        g.getObjects = lambda bot=None: self._objects_of(bot)
        g.getPlayer = lambda key, bot=None: self._player_of(key, bot)
        g.getPlayers = lambda bot=None: self._players_of(bot)
        g.getNPC = lambda npcid, bot=None: None
        g.getNPCs = lambda bot=None: lua.table()
        g.hasAccess = lambda x, y, bot=None: self._has_access(x, y, bot)
        g.ServerAlive = lambda bot=None: self._server_alive(bot)
        g.TotalHit = lambda bot=None: self._total_hit(bot)

        # --- enum ---------------------------------------------------------- #
        for enum_name, members in ENUMS.items():
            t = lua.table()
            for k, v in members.items():
                t[k] = v
            g[enum_name] = t

        # konstanta jenis akun: LEGACY, GOOGLE, UBICONNECT, TOKEN, APPLE, STEAM
        for name, value in ACCOUNT_TYPE_CONSTS.items():
            g[name] = value

        # --- kelas/struct -------------------------------------------------- #
        g.variant = self._class_variant()
        g.variantlist = self._class_variantlist()
        g.GameUpdatePacket = self._class_game_packet()
        g.HttpClient = self._class_http_client()
        g.Webhook = self._class_webhook()
        g.Embed = self._class_embed()
        g.RTVAR = self._class_rtvar()
        g.Vector2 = self._class_vector("2")
        g.Vector3 = self._class_vector("3")
        self._register_features(g)
        from .compat_deltax import pasang as _pasang_deltax  # noqa: PLC0415

        _pasang_deltax(self)

    # ------------------------------------------------------------------ #
    # Fitur otomasi gaya deltaX
    # ------------------------------------------------------------------ #
    def _register_features(self, g) -> None:
        """Pasang fungsi fitur (autofarm/autocollect/spammer/...) ke tabel Lua.

        Nama fungsi sengaja mengikuti alias `assets/menu.json` deltaX supaya
        skrip Lucifer dan daftar fitur deltaX bisa dicocokkan satu-satu.
        Setiap fungsi menerima `bot=` opsional untuk multi-akun.
        """

        def fitur(bot=None):
            b = self._resolve_bot(bot)
            return b.fitur if b is not None else None

        def bungkus(nama: str):
            """Pembungkus yang meneruskan bot= ke FiturBot yang benar."""

            def luar(*args, **kw):
                label = kw.pop("bot", None)
                if nama == "kirim":
                    b = self._resolve_bot(label)
                    if b is None:
                        raise RuntimeError("belum ada bot")
                    return b.kirim(*args, **kw)
                if nama == "features_menu":
                    from .features import TILE_MENU  # noqa: PLC0415

                    return dict(TILE_MENU)
                fb = fitur(label)
                if fb is None:
                    raise RuntimeError(
                        "belum ada bot — tambahkan akun dulu "
                        "(lihat README: Login GrowID / Login Google)")
                fn = fb.lua_api().get(nama)
                if fn is None:
                    raise RuntimeError(f"fitur '{nama}' tidak tersedia di bot ini")
                return fn(*args)

            return luar

        from .features import SEMUA_ALIAS  # noqa: PLC0415

        tambahan = (
            "autofarm_stop", "autofarm_status", "autofarm_set_tiles",
            "autofarm_set_block", "autofarm_set_seed", "autofarm_step",
            "autocollect_stop", "autocollect_status", "autocollect_set_radius",
            "spammer_stop", "spammer_status", "spammer_add", "spammer_clear",
            "spammer_set_delay",
            "findpath_to", "findpath_find", "findpath_item",
            "findpath_set_blockjump", "findpath_set_teleport",
            "autodrop_start", "autodrop_stop", "autodrop_status",
            "autodrop_set_mode", "autodrop_set_minimum",
            "replay_record_start", "replay_record_stop", "replay_play_start",
            "replay_stop", "replay_clear", "replay_save", "replay_load",
            "replay_files", "replay_status",
            "growscan", "command", "command_status",
            "features_stop_all", "features_status", "features_menu",
            "kirim",
        )
        for nama in tuple(SEMUA_ALIAS) + tambahan:
            g[nama] = bungkus(nama)

    # ------------------------------------------------------------------ #
    # Implementasi API: dasar
    # ------------------------------------------------------------------ #
    def _sleep(self, ms) -> None:
        """sleep(ms) ala Lucifer: TETAP memompa event selama menunggu.

        Ini penting — di Lucifer, sleep() bukan sekadar tidur: event yang datang
        dari server tetap dikirim ke handler Lua. Tanpa ini, event menumpuk di
        antrean dan skrip yang memakai `sleep()` tidak pernah menerima apa pun.
        """
        try:
            total = max(0.0, float(ms) / 1000.0)
        except (TypeError, ValueError):
            return
        end = time.time() + total
        while True:
            if self._stop.is_set() or self._script_stop.is_set():
                raise LuaStop()
            if self._listening and time.time() > self._listen_until:
                raise LuaStop()
            remaining = end - time.time()
            if remaining <= 0:
                return
            # pompa event (kecuali kita sendiri sedang di dalam listenEvents)
            if not self._listening:
                self._pump_once(min(0.05, remaining))
            else:
                time.sleep(min(0.05, remaining))

    def _pump_once(self, timeout: float) -> bool:
        """Ambil satu event dari antrean dan kirim ke handler Lua."""
        try:
            kind, payload = self._queue.get(timeout=timeout)
        except queue.Empty:
            return False
        self._route_event(kind, payload)
        return True

    def _route_event(self, kind: str, payload: Any) -> None:
        """Teruskan event ke semua nama event Lua yang relevan."""
        if kind == "variant":
            self._dispatch("variant", payload)
            self._dispatch("update_packet", payload[1])
        elif kind == "game_packet":
            self._dispatch("game_packet", payload)
        elif kind in ("game_message", "generic_text"):
            self._dispatch("game_message", payload)
            self._dispatch("generic_text", payload)
        elif kind == "connected":
            self._dispatch("connected", payload)
        elif kind == "disconnected":
            self._dispatch("disconnected", payload)
        elif kind == "logon_fail":
            self._dispatch("logon_fail", payload)
        elif kind == "captcha":
            self._dispatch("captcha", payload)
        elif kind == "entering_game":
            self._dispatch("entering_game", payload)
        elif kind == "login":
            self._dispatch("login", payload)
        elif kind == "console":
            self._dispatch("console", payload)
            self._dispatch("say", payload)
        else:
            self._dispatch(kind, payload)

    def _resolve_path(self, path: str) -> Path:
        p = Path(str(path))
        if p.is_absolute():
            return p
        return (self.data_dir / p).resolve()

    def _read_file(self, path: str) -> str:
        try:
            return self._resolve_path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            self.log_line(f"read({path!r}) gagal: {e}")
            return ""

    def _write_file(self, path: str, content: str) -> None:
        try:
            p = self._resolve_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(content), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            self.log_line(f"write({path!r}) gagal: {e}")

    # ------------------------------------------------------------------ #
    # Item info
    # ------------------------------------------------------------------ #
    def _item_info_table(self, item):
        t = self.lua.table()
        if item is None:
            return t
        t.id = item.id
        t.name = item.name
        t.editable_type = item.action_type
        t.item_category = item.material
        t.action_type = item.action_type
        t.hit_sound_type = item.visual_effect
        t.item_kind = item.material
        t.collision_type = item.collision_type
        t.clothing_type = item.clothing_type
        t.rarity = item.rarity
        t.seed_color = item.seed_base_sprite
        t.seed_overlay_color = item.seed_overlay_sprite
        t.grow_time = item.grow_time
        t.drop_chance = item.drop_chance
        t.texture = item.texture_file_name
        t.texture_hash = item.texture_hash
        t.texture_x = item.texture_x
        t.texture_y = item.texture_y
        t.file_name = item.file_name
        t.block_health = item.block_health
        t.strength = item.block_health
        t.max_item = item.max_item
        t.level_required = item.level_required
        t.null_Item = "\x00" in item.name
        return t

    def _get_info(self, key):
        if not self.items_db:
            return self.lua.table()
        if isinstance(key, str):
            try:
                return self._item_info_table(self.items_db.get(int(key)))
            except ValueError:
                found = self.items_db.find(key, exact=True) or self.items_db.find(key)
                return self._item_info_table(found[0] if found else None)
        return self._item_info_table(self.items_db.get(int(key)))

    def _get_infos(self):
        t = self.lua.table()
        if not self.items_db:
            return t
        for i, item in enumerate(self.items_db, start=1):
            t[i] = self._item_info_table(item)
        return t

    # ------------------------------------------------------------------ #
    # Bot
    # ------------------------------------------------------------------ #
    def _new_bot(self, account: Account, label: str = "") -> Bot:
        bot = Bot(
            account=account,
            items_db=self.items_db,
            label=label or account.label,
            on_event=self._on_bot_event,
        )
        self.bots[bot.label] = bot
        if self.parent is None:
            self.parent = bot
        return bot

    def _add_bot(self, name, *args):
        """addBot(...) — mendukung DUA bentuk seperti Lucifer:

        Bentuk lama (paling umum dipakai skrip):
            addBot(name [, password] [, mac] [, rid])

        Bentuk tabel (gaya SurferBot/Lucifer baru):
            addBot({ type = GOOGLE, mail = "...", password = "...", ... })
            addBot({ type = TOKEN, token = "ltoken...", growid = "Nama" })
            addBot({ type = LEGACY, growid = "Nama", password = "..." })
        """
        # -- bentuk tabel --------------------------------------------------- #
        if not isinstance(name, str):
            acc, label = self._account_from_table(name)
            if acc is None:
                self.log_line("addBot: tabel akun tidak dikenali")
                return None
            if label in self.bots:
                return self._bot_table(self.bots[label])
            return self._bot_table(self._new_bot(acc, label))

        # -- bentuk lama ---------------------------------------------------- #
        name = str(name)
        if name in self.bots:
            return self._bot_table(self.bots[name])

        password = mac = rid = ""
        if len(args) == 1:
            password = str(args[0])
        elif len(args) == 2:
            mac, rid = str(args[0]), str(args[1])
        elif len(args) >= 3:
            password, mac, rid = str(args[0]), str(args[1]), str(args[2])

        acc = Account(
            username=name,
            password=password or os.environ.get("LUCIFER_PASS", ""),
            method="growid" if password else "legacy",
            label=name,
        )
        if mac:
            acc.mac = mac
        if rid:
            acc.rid = rid
        return self._bot_table(self._new_bot(acc, name))

    # Jenis akun yang dikenali di tabel addBot
    ACCOUNT_TYPES = {
        "LEGACY": "legacy", "GROWID": "growid", "GOOGLE": "google",
        "UBICONNECT": "ubiconnect", "UBI": "ubiconnect", "APPLE": "apple",
        "TOKEN": "token", "STEAM": "growid", "SOCIAL": "google",
    }

    def _account_from_table(self, tbl) -> tuple[Optional[Account], str]:
        """Ubah tabel akun Lua (type/mail/password/token/...) jadi Account."""
        def get(key, default=""):
            """Ambil nilai dari tabel Lua; 0 dan false tetap dianggap NILAI SAH."""
            try:
                v = tbl[key]
            except Exception:  # noqa: BLE001
                return default
            if v is None:
                return default
            return v

        raw_type = str(get("type", "")).strip().upper()
        # dukung juga angka (0=LEGACY, 1=GOOGLE, ...) seperti konstanta Lucifer
        if raw_type.isdigit():
            raw_type = ["LEGACY", "GOOGLE", "UBICONNECT", "TOKEN", "APPLE", "STEAM"][
                int(raw_type) % 6
            ]
        method = self.ACCOUNT_TYPES.get(raw_type, "growid")

        growid = str(get("growid", "") or get("username", "") or "")
        mail = str(get("mail", "") or get("email", "") or "")
        password = str(get("password", "") or "")
        token = str(get("token", "") or get("ltoken", "") or "")
        label = str(get("label", "") or growid or mail or "bot")

        if method == "token" or (token and not password and not growid):
            # ltoken siap pakai — cara paling andal
            acc = Account(username=growid or label, method="token", ltoken=token, label=label)
        elif method in ("google", "apple", "ubiconnect"):
            acc = Account(
                username=growid or label, method=method, mail=mail,
                social_token=str(get("social_token", "") or get("id_token", "") or token),
                secret_key=str(get("secretKey", "") or get("secret_key", "")),
                token_url=str(get("tokenUrl", "") or get("token_url", "")),
                cookies=str(get("cookies", "") or ""),
                label=label,
            )
        elif method == "legacy":
            acc = Account(username=growid, password=password, method="legacy", label=label)
        else:
            acc = Account(username=growid, password=password, method="growid", label=label)

        for field_name in ("mac", "rid"):
            v = get(field_name, "")
            if v:
                setattr(acc, field_name, str(v))
        proxy = str(get("proxy", "") or "")
        if proxy and proxy != "/":
            acc.proxy = proxy
        return acc, acc.label

    def _add_ubi_bot(self, mail: str, password: str, username: str = "", social_token: str = ""):
        """addUbiBot(mail, password [, username] [, social_token]) — Ubisoft Connect.

        Ubisoft memakai OAuth. Kalau kamu punya token OAuth-nya (dari login
        browser), token itu ditukar jadi ltoken lewat /player/social/login.
        Kalau tidak, bot dicatat saja dan kamu bisa memakai ltoken langsung.
        """
        label = username or mail
        if label in self.bots:
            return self._bot_table(self.bots[label])
        acc = Account(
            username=username or mail, method="ubiconnect", mail=mail,
            password=password, social_token=social_token, label=label,
        )
        if not social_token:
            self.log_line(
                f"addUbiBot('{label}'): belum ada social_token Ubisoft. Login Ubisoft "
                "butuh OAuth — ambil tokennya dari browser lalu isi 'social_token', "
                "atau pakai ltoken langsung (method TOKEN)."
            )
        return self._bot_table(self._new_bot(acc, label))

    def _remove_bot(self, name=None):
        target = str(name) if name else (self.parent.label if self.parent else None)
        if not target or target not in self.bots:
            return False
        bot = self.bots.pop(target)
        try:
            bot.disconnect()
        except Exception:  # noqa: BLE001
            pass
        if self.parent is bot:
            self.parent = next(iter(self.bots.values()), None)
        return True

    def _get_bot(self, name=None):
        if name is None:
            return self._bot_table(self.parent) if self.parent else None
        bot = self.bots.get(str(name))
        return self._bot_table(bot) if bot else None

    def _bots_of(self, bot=None) -> list[Bot]:
        if bot is not None:
            b = self._resolve_bot(bot)
            return [b] if b else []
        return list(self.bots.values())

    def _resolve_bot(self, bot) -> Optional[Bot]:
        if bot is None:
            return self.parent
        if isinstance(bot, Bot):
            return bot
        if isinstance(bot, str):
            return self.bots.get(bot)
        label = getattr(bot, "label", None) or getattr(bot, "_label", None)
        if label:
            return self.bots.get(str(label))
        return self.parent

    def _bot_table(self, bot: Optional[Bot]):
        """Bangun tabel Lua `Bot` lengkap dengan method-nya.

        Nilai yang berubah-ubah (status, gems, level, ...) TIDAK disalin, tapi
        dibaca langsung lewat metatable `__index` — jadi `bot.status` di Lua
        selalu mencerminkan keadaan bot saat itu, bukan snapshot.
        """
        if bot is None:
            return None
        t = self.lua.table()
        t.label = bot.label
        t.move_interval = bot.move_interval
        t.move_range = bot.move_range
        t.rest_time = bot.rest_time
        t.rest_interval = bot.rest_interval
        t.consume_id = 0
        t.consume_interval = 0
        t.consumed_once = False
        t.auto_reconnect = bot.auto_reconnect
        t.auto_accept = bot.auto_accept
        t.auto_collect = bot.auto_collect
        t.auto_leave_on_admin = bot.auto_leave_on_admin
        t.auto_leave_on_mod = bot.auto_leave_on_mod
        t.auto_ban = False
        t.auto_tutorial = bot.auto_tutorial
        t.auto_consume = False
        t.auto_trash = False
        t.auto_rest_mode = False
        t.auto_take_pickaxe = False
        t.auto_expand_inventory = False
        t.legit_mode = bot.legit_mode
        t.reconnect_interval = 5
        t.ignore_gems = False
        t.ignore_essences = False
        t.object_collect_delay = 0
        t.collect_all = True
        t.collect_path_check = False
        t.collect_interval = 100
        t.collect_range = 3

        # -- nilai live (dibaca saat diakses, bukan disalin) ---------------- #
        # Metatable HARUS dibuat di sisi Lua dengan fungsi Lua asli: kalau
        # __index-nya fungsi Python, lupa akan memperlakukannya sebagai objek
        # Python saat diakses, bukan memanggilnya.
        def live(key):
            k = str(key)
            if k == "name":
                return bot.name
            if k == "status":
                return bot.status
            if k == "captcha_status":
                return bot.captcha_status
            if k == "selected":
                return bot.selected
            if k == "gem_count":
                return bot.gem_count
            if k == "level":
                return bot.level
            if k == "server":
                if bot.server:
                    s = self.lua.table()
                    s[1], s[2] = bot.server[0], bot.server[1]
                    return s
                return None
            if k == "world_name":
                return bot.world.name if bot.world else ""
            if k == "is_online":
                return bot.status == BotStatus.online
            if k == "token":
                return bot.account._token or bot.account.ltoken
            if k == "pearl_count" or k == "voucher_count":
                return 0
            if k == "is_account_secured":
                return False
            return None

        setmeta = self.lua.eval(
            "function(t, f) return setmetatable(t, {__index = function(_, k) return f(k) end}) end"
        )
        setmeta(t, live)

        def method(fn):
            def wrapper(self_tbl, *args, **kwargs):
                # teruskan nilai properti yang mungkin diubah skrip ke bot
                try:
                    _sync_props(self_tbl, bot)
                except Exception:  # noqa: BLE001
                    pass
                return fn(bot, *args, **kwargs)
            return wrapper

        t.getWorld = method(lambda b: self._world_table(b))
        t.getInventory = method(lambda b: self._inventory_table(b))
        t.getConsole = method(lambda b: self._console_table(b))
        t.getLog = method(lambda b: self._log_table(b))
        t.getLogin = method(lambda b: self._login_table(b))
        t.getProxy = method(lambda b: b.proxy or "")
        t.getPlaytime = method(lambda b: b.getPlaytime())
        t.getAge = method(lambda b: b.getAge())
        t.getActiveTime = method(lambda b: b.getActiveTime())
        t.getPing = method(lambda b: b.getPing())
        t.getSignal = method(lambda b: self._signal_table(b))
        t.getCaptcha = method(lambda b: b.getCaptcha())
        t.connect = method(lambda b: b.connect())
        t.disconnect = method(lambda b: b.disconnect())
        t.reconnect = method(lambda b: b.reconnect())
        t.sendRaw = method(lambda b, pkt: b.send_raw(pkt))
        t.sendPacket = method(lambda b, ptype, pkt: b.send_packet(int(ptype), str(pkt)))
        t.warp = method(lambda b, name, door="0": b.warp(str(name), str(door)))
        t.say = method(lambda b, text: b.say(str(text)))
        t.use = method(lambda b, item_id: b.use(int(item_id)))
        t.wear = method(lambda b, item_id: b.wear(int(item_id)))
        t.unwear = method(lambda b, item_id: b.unwear(int(item_id)))
        t.drop = method(lambda b, item_id, count=1: b.drop(int(item_id), int(count)))
        t.trash = method(lambda b, item_id, count=1: b.trash(int(item_id), int(count)))
        t.fastDrop = method(lambda b, item_id, count=1: b.drop(int(item_id), int(count)))
        t.fastTrash = method(lambda b, item_id, count=1: b.trash(int(item_id), int(count)))
        t.buy = method(lambda b, a, c=0, m=0: b.buy(a, int(c), int(m)))
        t.retrieve = method(lambda b, x, y, count=200: b.retrieve(int(x), int(y), int(count)))
        t.active = method(lambda b, x, y: b.active(int(x), int(y)))
        t.leaveWorld = method(lambda b: b.leaveWorld())
        t.setBubble = method(lambda b, bubble: b.setBubble(bubble))
        t.place = method(lambda b, x, y, item: b.place(int(x), int(y), int(item)))
        t.hit = method(lambda b, x, y: b.hit(int(x), int(y)))
        t.wrench = method(lambda b, x, y: b.wrench(int(x), int(y)))
        t.wrenchPlayer = method(lambda b, netid: b.wrenchPlayer(int(netid)))
        t.moveTo = method(lambda b, dx, dy: b.moveTo(int(dx), int(dy)))
        t.moveTile = method(lambda b, x, y: b.moveTile(int(x), int(y)))
        t.moveLeft = method(lambda b, r=1: b.moveLeft(int(r)))
        t.moveRight = method(lambda b, r=1: b.moveRight(int(r)))
        t.moveUp = method(lambda b, r=1: b.moveUp(int(r)))
        t.moveDown = method(lambda b, r=1: b.moveDown(int(r)))
        t.enter = method(lambda b, pw="": b.enter(str(pw)))
        t.respawn = method(lambda b: b.respawn())
        t.getPath = method(lambda b, x, y: self._path_table(b.getPath(int(x), int(y))))
        t.findPath = method(lambda b, x, y: b.findPath(int(x), int(y)))
        t.findWorldPath = method(lambda b, x, y: b.findPath(int(x), int(y)))
        t.collectObject = method(lambda b, oid, r=3: b.collectObject(int(oid), int(r)))
        t.collect = method(lambda b, r=3, i=100: b.collect(int(r), int(i)))
        t.isInWorld = method(lambda b, name="": b.isInWorld(str(name)))
        t.isInTile = method(lambda b, a, y=-1: b.isInTile(a, int(y)))
        t.updateBot = method(lambda b, name, *a: self._update_bot(b, str(name), *a))
        t.setSkin = method(lambda b, skin_id: b.setSkin(int(skin_id)))
        t.setDirection = method(lambda b, faceleft: b.setDirection(bool(faceleft)))
        t.setCountry = method(lambda b, country: setattr(b, "country", str(country)))
        t.setMac = method(lambda b, mac: setattr(b.account, "mac", str(mac)))
        t.setRid = method(lambda b, rid: setattr(b.account, "rid", str(rid)))
        t.setToken = method(lambda b, tok: self._set_token(b, str(tok)))
        t.setSecret = method(lambda b, key: setattr(b.account, "secret_key", str(key)))
        t.setRecovery = method(lambda b, mail: setattr(b.account, "mail", str(mail)))
        t.updateAccount = method(lambda b, tbl: self._update_account(b, tbl))
        t.updateProxy = method(lambda b, tbl: self._update_proxy(b, tbl))
        t.getToken = method(lambda b: b.account._token or b.account.ltoken)
        t.runScript = method(lambda b, content: self.run_script_source(str(content), label=b.label))
        t.stopScript = method(lambda b: self._unlisten_events())
        t._label = bot.label
        return t

    def _set_token(self, bot: Bot, token: str) -> bool:
        """setToken(ltoken) — pakai token login yang sudah ada.

        PENTING: harus mengubah `_token` (yang benar-benar dikirim ke server),
        bukan hanya `ltoken` — kalau tidak, `setToken()` dari Lua tidak
        berpengaruh dan bot tetap memakai token lama.
        """
        bot.account.ltoken = token
        bot.account._token = token
        bot.account.method = "token"
        return True

    def _update_account(self, bot: Bot, tbl) -> bool:
        """updateAccount(tabel) — ubah kredensial bot saat berjalan."""
        acc, label = self._account_from_table(tbl)
        if acc is None:
            return False
        # pertahankan label lama kalau tabel tidak menyebut label
        keep = bot.label
        acc.label = keep
        bot.account = acc
        bot.name = acc.username or acc.mail or keep
        return True

    def _update_proxy(self, bot: Bot, tbl) -> bool:
        """updateProxy({HostName=..., Username=..., Password=...})"""
        try:
            host = str(tbl["HostName"] or "")
            user = str(tbl["Username"] or "")
            pw = str(tbl["Password"] or "")
        except Exception:  # noqa: BLE001
            return False
        bot.proxy = f"{user}:{pw}:{host}" if user or pw else host
        self.log_line(f"proxy bot '{bot.label}' -> {host}")
        return True

    def _update_bot(self, bot: Bot, name: str, *args):
        bot.account.username = name
        bot.name = name
        if len(args) == 1:
            bot.account.password = str(args[0])
        elif len(args) == 2:
            bot.account.mac, bot.account.rid = str(args[0]), str(args[1])
        elif len(args) >= 3:
            bot.account.password, bot.account.mac, bot.account.rid = str(args[0]), str(args[1]), str(args[2])
        return True

    # ------------------------------------------------------------------ #
    # Struct kecil
    # ------------------------------------------------------------------ #
    def _world_table(self, bot: Optional[Bot]):
        w = (bot or self.parent).world if (bot or self.parent) else None
        t = self.lua.table()
        if w is None:
            return t
        t.name = w.name
        t.x = w.width
        t.y = w.height
        t.tile_count = len(w.tiles)
        t.version = w.version
        t.public = not any(tile.is_locked for tile in w.tiles[:200])
        t.tiles = self._tiles_of(bot)
        t.objects = self._objects_of(bot)
        t.players = self._players_of(bot)
        t.npcs = self.lua.table()
        t.growscan = self._growscan_table(bot)

        def get_tile(self_tbl, x, y):
            return self._tile_of(int(x), int(y), bot)

        def get_object(self_tbl, oid):
            return self._object_of(oid, bot)

        def get_player(self_tbl, key):
            return self._player_of(key, bot)

        def get_npc(self_tbl, npcid):
            return None

        t.getTile = get_tile
        t.getObject = get_object
        t.getPlayer = get_player
        t.getNPC = get_npc
        t.getTiles = lambda self_tbl: self._tiles_of(bot)
        t.getTilesSafe = lambda self_tbl: self._tiles_of(bot)
        t.getObjects = lambda self_tbl: self._objects_of(bot)
        t.getPlayers = lambda self_tbl: self._players_of(bot)
        t.getNPCs = lambda self_tbl: self.lua.table()
        t.getLocal = lambda self_tbl: self._local_of(bot)
        t.getTileParent = lambda self_tbl, tile: self._tile_of(
            getattr(tile, "x", 0), getattr(tile, "y", 0), bot
        )
        t.hasAccess = lambda self_tbl, x, y: self._has_access(int(x), int(y), bot)
        t.hasAdventure = lambda self_tbl, item: False
        t.isValidPosition = lambda self_tbl, x, y: bool(
            w and 0 <= int(x) < w.width and 0 <= int(y) < w.height
        )
        return t

    def _tile_of(self, x, y, bot=None):
        b = self._resolve_bot(bot)
        if not b:
            return None
        tile = b.world.tile(int(x), int(y))
        if tile is None:
            return None
        return self._tile_table(tile, b)

    def _tile_table(self, tile, bot: Optional[Bot] = None):
        t = self.lua.table()
        t.x = tile.x
        t.y = tile.y
        t.fg = tile.fg
        t.foreground = tile.fg
        t.bg = tile.bg
        t.background = tile.bg
        t.parent = tile.parent
        t.flags = tile.flags
        t.extra_type = tile.extra_type
        t.seed_age = tile.seed_age
        t.fruit_count = tile.fruit_count
        t.ready = tile.ready

        def hasFlag(self_tbl, flag):
            return bool(tile.flags & int(flag))

        def hasExtra(self_tbl):
            return tile.has_extra

        def getExtra(self_tbl):
            if not tile.has_extra:
                return None
            e = self.lua.table()
            e.type = tile.extra_type
            e.owner_uid = tile.owner_uid
            e.label = tile.label
            e.seed_age = tile.seed_age
            e.fruit_count = tile.fruit_count
            e.grow_time = tile.grow_time
            e.ready = tile.ready
            return e

        def canHarvest(self_tbl):
            return bool(tile.ready)

        t.hasFlag = hasFlag
        t.hasExtra = hasExtra
        t.getExtra = getExtra
        t.canHarvest = canHarvest
        return t

    def _tiles_of(self, bot=None):
        b = self._resolve_bot(bot)
        out = self.lua.table()
        if not b:
            return out
        for i, tile in enumerate(b.world.tiles, start=1):
            out[i] = self._tile_table(tile, b)
        return out

    def _object_of(self, oid, bot=None):
        b = self._resolve_bot(bot)
        if not b:
            return None
        for d in b.world.dropped:
            if d.uid == int(oid):
                return self._object_table(d)
        return None

    def _object_table(self, d):
        t = self.lua.table()
        t.id = d.item_id
        t.x = d.x
        t.y = d.y
        t.count = d.count
        t.flags = d.flags
        t.oid = d.uid
        t.tile_x = int(d.x // 32)
        t.tile_y = int(d.y // 32)
        return t

    def _objects_of(self, bot=None):
        b = self._resolve_bot(bot)
        out = self.lua.table()
        if not b:
            return out
        for i, d in enumerate(b.world.dropped, start=1):
            out[i] = self._object_table(d)
        return out

    def _player_table(self, pl: Player):
        t = self.lua.table()
        t.name = pl.name
        t.altName = pl.altName
        t.country = pl.country
        t.netid = pl.netid
        t.userid = pl.userid
        t.bubble = pl.bubble
        t.posx = pl.posx
        t.posy = pl.posy
        t.tile_x = int(pl.posx // 32) if pl.posx else 0
        t.tile_y = int(pl.posy // 32) if pl.posy else 0
        t.vecx = pl.vecx
        t.vecy = pl.vecy
        t.avatarFlags = pl.avatarFlags
        t.isModerator = pl.isModerator
        t.isSuperModerator = pl.isSuperModerator
        t.isLocalPlayer = pl.isLocalPlayer
        t.isFriendWithOwner = pl.isFriendWithOwner
        t.skincolor = pl.skincolor
        t.flag2019 = 0
        t.roleskin = 0
        t.roleicon = 0
        c = self.lua.table()
        for k, v in (pl.clothes or {}).items():
            c[k] = v
        for k in ("hat", "shirt", "pants", "shoes", "face", "hand", "wings", "mask", "neck", "ances"):
            if c[k] is None:
                c[k] = 0
        c.unk1 = 0
        c.unk2 = 0
        t.clothes = c
        return t

    def _local_of(self, bot=None):
        b = self._resolve_bot(bot)
        if not b or not b.local:
            return None
        return self._player_table(b.local)

    def _player_of(self, key, bot=None):
        b = self._resolve_bot(bot)
        if not b:
            return None
        if isinstance(key, str):
            for pl in b.players.values():
                if pl.name.lower() == key.lower():
                    return self._player_table(pl)
            return None
        pl = b.players.get(int(key))
        return self._player_table(pl) if pl else None

    def _players_of(self, bot=None):
        b = self._resolve_bot(bot)
        out = self.lua.table()
        if not b:
            return out
        for i, pl in enumerate(b.players.values(), start=1):
            out[i] = self._player_table(pl)
        return out

    def _inventory_table(self, bot=None):
        b = self._resolve_bot(bot)
        t = self.lua.table()
        if not b:
            return t
        items = self.lua.table()
        for i, it in enumerate(b.inventory.items.values(), start=1):
            e = self.lua.table()
            e.id = it.id
            e.count = it.count
            e.isActive = it.isActive
            items[i] = e
        t.items = items
        t.itemcount = len(b.inventory.items)
        t.slotcount = b.inventory.slotcount or len(b.inventory.items)
        t.version = b.inventory.version

        def getItem(self_tbl, item_id):
            it = b.inventory.getItem(item_id)
            if not it:
                return None
            e = self.lua.table()
            e.id = it.id
            e.count = it.count
            e.isActive = it.isActive
            return e

        def getItems(self_tbl):
            return items

        def findItem(self_tbl, item_id):
            return b.inventory.getItemCount(item_id)

        def canCollect(self_tbl, item_id):
            return True

        t.getItem = getItem
        t.getItems = getItems
        t.findItem = findItem
        t.getItemCount = findItem
        t.canCollect = canCollect
        return t

    def _console_table(self, bot=None):
        b = self._resolve_bot(bot)
        t = self.lua.table()
        if not b:
            return t
        contents = self.lua.table()
        for i, line in enumerate(b.console.contents, start=1):
            contents[i] = line
        t.contents = contents

        def append(self_tbl, text):
            b.console.append(str(text))
            self.log_line(f"[console:{b.label}] {text}")

        t.append = append
        return t

    def _log_table(self, bot=None):
        b = self._resolve_bot(bot)
        t = self.lua.table()
        if not b:
            return t
        t.content = b.log.content

        def append(self_tbl, text):
            b.log.append(str(text))
            self.log_line(f"[log:{b.label}] {text}")

        def clear(self_tbl):
            b.log.clear()

        t.append = append
        t.clear = clear
        return t

    def _login_table(self, bot=None):
        b = self._resolve_bot(bot)
        t = self.lua.table()
        if not b:
            return t
        t.mac = b.account.mac
        t.rid = b.account.rid
        t.username = b.account.username
        t.method = b.account.method
        return t

    def _signal_table(self, bot=None):
        b = self._resolve_bot(bot)
        t = self.lua.table()
        t.x = b.signal.x if b else 0
        t.y = b.signal.y if b else 0
        t.type = b.signal.type if b else 0
        return t

    def _growscan_table(self, bot=None):
        b = self._resolve_bot(bot)
        t = self.lua.table()
        tiles_map = self.lua.table()
        objs_map = self.lua.table()
        if b:
            for tile in b.world.tiles:
                if tile.fg:
                    tiles_map[tile.fg] = (tiles_map[tile.fg] or 0) + 1
            for d in b.world.dropped:
                objs_map[d.item_id] = (objs_map[d.item_id] or 0) + 1
        t.tiles = tiles_map
        t.objects = objs_map
        t.getTiles = lambda self_tbl: tiles_map
        t.getObjects = lambda self_tbl: objs_map
        return t

    def _path_table(self, path: list[tuple[int, int]]):
        out = self.lua.table()
        for i, (x, y) in enumerate(path, start=1):
            n = self.lua.table()
            n.x = x
            n.y = y
            out[i] = n
        return out

    def _has_access(self, x, y, bot=None) -> bool:
        b = self._resolve_bot(bot)
        return bool(b and b.hasAccess(int(x), int(y)))

    def _total_hit(self, bot=None) -> int:
        """Jumlah `TileApplyDamage` yang sudah diterima bot ini."""
        b = self._resolve_bot(bot)
        return int(b.total_hit_diterima()) if b else 0

    def _server_alive(self, bot=None) -> bool:
        """True bila server masih mengirim paket (bukan maintenance).

        Skrip pembersih dunia memakainya untuk berhenti menembak saat koneksi
        sudah mati; menembak soket mati memperpanjang blokir/ercon.
        """
        b = self._resolve_bot(bot)
        return bool(b and b.status == BotStatus.online and not b._server_diam())

    # ------------------------------------------------------------------ #
    # Kelas-kelas Lua
    # ------------------------------------------------------------------ #
    def _class_variant(self):
        lua = self.lua

        def new():
            t = lua.table()
            t._kind = P.VARIANT_STRING
            t._value = ""
            t.getType = lambda self_tbl: self_tbl._kind
            t.print = lambda self_tbl: str(self_tbl._value)

            def _set(self_tbl, a, b=None, c=None):
                if b is not None and c is not None:
                    self_tbl._kind, self_tbl._value = P.VARIANT_VEC3, (a, b, c)
                elif b is not None:
                    self_tbl._kind, self_tbl._value = P.VARIANT_VEC2, (a, b)
                elif isinstance(a, str):
                    self_tbl._kind, self_tbl._value = P.VARIANT_STRING, a
                elif isinstance(a, bool):
                    self_tbl._kind, self_tbl._value = P.VARIANT_SIGNED, int(a)
                elif isinstance(a, float) and not float(a).is_integer():
                    self_tbl._kind, self_tbl._value = P.VARIANT_FLOAT, float(a)
                else:
                    self_tbl._kind, self_tbl._value = P.VARIANT_SIGNED, int(a or 0)

            t.set = _set
            t.reset = lambda self_tbl: _set(self_tbl, "")
            t.getString = lambda self_tbl: str(self_tbl._value)
            t.getInt = lambda self_tbl: int(self_tbl._value or 0)
            t.getFloat = lambda self_tbl: float(self_tbl._value or 0.0)

            def _vec2(self_tbl):
                v = lua.table()
                val = self_tbl._value if isinstance(self_tbl._value, tuple) else (0, 0)
                v.x, v.y = float(val[0]), float(val[1])
                return v

            def _vec3(self_tbl):
                v = lua.table()
                val = self_tbl._value if isinstance(self_tbl._value, tuple) and len(self_tbl._value) == 3 else (0, 0, 0)
                v.x, v.y, v.z = float(val[0]), float(val[1]), float(val[2])
                return v

            t.getVector2 = _vec2
            t.getVector3 = _vec3
            return t

        return lua.table(new=new)

    def _class_variantlist(self):
        lua = self.lua

        def new():
            t = lua.table()
            t._list = lua.table()
            t._n = 0

            def get(self_tbl, index):
                return self_tbl._list[int(index) + 1] if self_tbl._list[int(index) + 1] is not None else None

            def append(self_tbl, variant=None):
                if variant is None:
                    variant = self._class_variant()["new"]()
                self_tbl._n = int(self_tbl._n) + 1
                self_tbl._list[self_tbl._n] = variant
                return variant

            def print_(self_tbl):
                parts = []
                for i in range(1, int(self_tbl._n) + 1):
                    v = self_tbl._list[i]
                    parts.append(str(v.print() if v and v.print else ""))
                return " | ".join(parts)

            t.get = get
            t.append = append
            t.print = print_
            t.size = lambda self_tbl: self_tbl._n
            return t

        return lua.table(new=new)

    def _class_game_packet(self):
        lua = self.lua

        def new():
            t = lua.table()
            t.type = 0
            t.object_type = 0
            t.count1 = 0
            t.count2 = 0
            t.netid = 0
            t.item = 0
            t.flags = 0
            t.float_var = 0.0
            t.int_data = 0
            t.vec_x = 0.0
            t.vec_y = 0.0
            t.vec2_x = 0.0
            t.vec2_y = 0.0
            t.pos_x = 0.0
            t.pos_y = 0.0
            t.pos2_x = 0.0
            t.pos2_y = 0.0
            t.particle_rotation = 0.0
            t.int_x = 0
            t.int_y = 0
            t.extended_data = ""

            def to_tank(self_tbl):
                ext = str(self_tbl.extended_data or "").encode()
                return Tank(
                    type=int(self_tbl.type or 0),
                    object_type=int(self_tbl.object_type or 0),
                    jump_count=int(self_tbl.count1 or 0),
                    animation_type=int(self_tbl.count2 or 0),
                    net_id=int(self_tbl.netid or 0),
                    flags=int(self_tbl.flags or 0),
                    value=int(self_tbl.item or 0),
                    float_variable=float(self_tbl.float_var or 0.0),
                    vector_x=float(self_tbl.vec_x or self_tbl.pos_x or 0.0),
                    vector_y=float(self_tbl.vec_y or self_tbl.pos_y or 0.0),
                    vector_x2=float(self_tbl.vec2_x or self_tbl.pos2_x or 0.0),
                    vector_y2=float(self_tbl.vec2_y or self_tbl.pos2_y or 0.0),
                    particle_rotation=float(self_tbl.particle_rotation or 0.0),
                    int_x=int(self_tbl.int_x or 0),
                    int_y=int(self_tbl.int_y or 0),
                ), ext

            t._to_tank = to_tank
            return t

        return lua.table(new=new)

    def _class_http_client(self):
        def new():
            return HttpClient()
        return self.lua.table(new=new)

    def _class_webhook(self):
        def new(url=""):
            return Webhook(str(url))
        return self.lua.table(new=new)

    def _class_embed(self):
        return self.lua.table(new=lambda: Embed())

    def _class_rtvar(self):
        def new(initial=""):
            return RTVAR(str(initial) if initial else "")
        return self.lua.table(new=new)

    def _class_vector(self, dim: str):
        def new(a=0.0, b=0.0, c=0.0):
            t = self.lua.table()
            t.x, t.y = float(a or 0), float(b or 0)
            if dim == "3":
                t.z = float(c or 0)
            return t
        return self.lua.table(new=new)

    # ------------------------------------------------------------------ #
    # Proxy / World manager
    # ------------------------------------------------------------------ #
    def _get_proxy_manager(self):
        t = self.lua.table()
        t.localize = False
        t.spread = False
        t._list = self.lua.table()
        t._limit = 0

        def addProxy(self_tbl, data):
            n = int(t._list["_n"] or 0) + 1
            t._list["_n"] = n
            t._list[n] = str(data)
            return True

        def removeProxy(self_tbl, ip, port):
            items = [t._list[i] for i in range(1, int(t._list["_n"] or 0) + 1)]
            keep = [x for x in items if not x.startswith(f"{ip}:{port}")]
            new = self.lua.table()
            for i, x in enumerate(keep, start=1):
                new[i] = x
            new["_n"] = len(keep)
            t._list = new
            return True

        def setLimit(self_tbl, n):
            t._limit = int(n)
            return True

        t.addProxy = addProxy
        t.removeProxy = removeProxy
        t.setLimit = setLimit
        return t

    def _get_world_manager(self):
        t = self.lua.table()
        t._farms = self.lua.table()
        t._n = 0

        def addFarm(self_tbl, farm):
            t._n = int(t._n) + 1
            t._farms[t._n] = str(farm)
            return True

        def removeFarm(self_tbl, farm):
            items = [t._farms[i] for i in range(1, int(t._n) + 1)]
            keep = [x for x in items if x != str(farm)]
            new = self.lua.table()
            for i, x in enumerate(keep, start=1):
                new[i] = x
            t._farms = new
            t._n = len(keep)
            return True

        def getFarms(self_tbl):
            return t._farms

        t.addFarm = addFarm
        t.removeFarm = removeFarm
        t.getFarms = getFarms
        return t

    def _add_proxy(self, data: str) -> bool:
        if self.parent:
            self.parent.proxy = str(data)
        self.log_line(f"proxy ditambahkan: {data}")
        return True

    def _remove_proxy(self, ip: str, port) -> bool:
        if self.parent and self.parent.proxy and str(ip) in self.parent.proxy:
            self.parent.proxy = None
        return True

    # ------------------------------------------------------------------ #
    # Event system
    # ------------------------------------------------------------------ #
    def _add_event(self, event, fn) -> bool:
        key = str(event)
        self.events.setdefault(key, []).append(fn)
        return True

    def _remove_event(self, event) -> bool:
        self.events.pop(str(event), None)
        return True

    def _remove_events(self) -> bool:
        self.events.clear()
        return True

    def _on_bot_event(self, kind: str, payload: Any) -> None:
        """Dipanggil dari thread jaringan bot -> masuk antrean event Lua."""
        # Peristiwa penting diteruskan ke log supaya TERLIHAT di dashboard,
        # bukan cuma tersimpan di status bot. Tanpa ini, pengguna hanya melihat
        # "logon_fail" tanpa tahu kenapa (sandi salah? captcha? server penuh?).
        if kind == "login_failed":
            pesan = getattr(payload, "message", "") or "login ditolak"
            self.log_line(f"[login] GAGAL: {pesan}")
            hint = _hint_login(pesan)
            if hint:
                self.log_line(f"[login] saran: {hint}")
        elif kind == "logon_fail":
            fields = payload if isinstance(payload, dict) else {}
            msg = str(fields.get("msg") or fields.get("error") or "").strip()
            if msg:
                self.log_line(f"[login] server menolak: {msg}")
                hint = _hint_login(msg)
                if hint:
                    self.log_line(f"[login] saran: {hint}")
        elif kind == "error":
            self.log_line(f"[error] {payload}")

        # Hook keluar (`onsendpacket`/`onsendpacketraw`) harus sinkron: nilainya
        # menentukan paket dikirim atau dibatalkan, jadi tidak boleh lewat antrean.
        if kind in ("send_packet", "send_raw"):
            return self._dispatch_sync(kind, payload)

        self._queue.put((kind, payload))
        return None

    def _dispatch_sync(self, kind: str, payload: Any) -> bool:
        """Jalankan handler Lua langsung di thread pemanggil; True = batal."""
        daftar = list(self.events.get(kind, []))
        if not daftar:
            return False
        hasil = False
        with self._lua_lock:
            for fn in daftar:
                try:
                    if self._call_event(fn, kind, payload) is True:
                        hasil = True
                except LuaStop:
                    raise
                except Exception as e:  # noqa: BLE001
                    self.log_line(f"[hook:{kind}] error: {type(e).__name__}: {e}")
        return hasil

    def _dispatch(self, kind: str, payload: Any) -> None:
        """Jalankan fungsi Lua yang terdaftar untuk event ini."""
        handlers = list(self.events.get(kind, []))
        # alias: game_message & generic_text memakai nama event yang sama
        if kind in ("console",):
            handlers += list(self.events.get("console", []))
        for fn in handlers:
            try:
                self._call_event(fn, kind, payload)
            except LuaStop:
                raise
            except Exception as e:  # noqa: BLE001
                self.log_line(f"[event:{kind}] error: {type(e).__name__}: {e}")

    def _call_event(self, fn, kind: str, payload: Any) -> None:
        if kind == "variant":
            vl, netid = payload
            fn(self._variantlist_to_lua(vl), int(netid))
        elif kind in ("game_message", "generic_text"):
            fn(self._text_to_lua(payload))
        elif kind in ("update_packet", "game_packet"):
            fn(self._game_packet_from_tank(payload))
        elif kind == "value":
            tipe, nama, val = payload
            fn(int(tipe), str(nama), val)
        elif kind == "send_packet":
            teks, mtype = payload
            return fn(teks, int(mtype))
        elif kind == "send_raw":
            return fn(self._game_packet_from_tank(payload))
        elif kind == "dialog":
            fn(str(payload))
        elif kind == "world_loaded":
            fn(self._world_table(self.parent))
        elif kind == "tile_update":
            fn(self._tile_table(payload, self.parent))
        elif kind == "player_move":
            fn(self._player_table(payload))
        elif kind == "inventory":
            fn(self._inventory_table(self.parent))
        elif kind == "console":
            fn(str(payload))
        elif kind in ("say", "warp", "drop", "trash", "place", "hit", "wrench", "active",
                      "move", "collect", "use", "redirect"):
            fn(payload if not isinstance(payload, tuple) else list(payload))
        else:
            fn(payload)

    def _variantlist_to_lua(self, vl: P.VariantList):
        t = self.lua.table()
        t._n = len(vl)
        t._raw = vl

        # deltaX membaca variant lewat field `v1`, `v2`, ... (`var.v2:find(...)`)
        # dan MENULIS balik ke situ sebelum `sendVariant(var, packet)`. Tanpa
        # field ini semua handler `onvariant` di skrip deltaX mati diam-diam.
        for _i, _v in enumerate(vl.variants, start=1):
            t[f"v{_i}"] = _v.value

        def get(self_tbl, index):
            v = vl.get(int(index))
            if v is None:
                return None
            return self._variant_to_lua(v)

        def print_(self_tbl):
            return " | ".join(str(v.value) for v in vl.variants)

        t.get = get
        t.print = print_
        t.size = lambda self_tbl: len(vl)
        return t

    def _variant_to_lua(self, v: P.Variant):
        t = self.lua.table()
        t._kind = v.kind
        t._value = v.value
        t.getType = lambda self_tbl: v.kind
        t.print = lambda self_tbl: str(v.value)
        t.getString = lambda self_tbl: v.as_string()
        t.getInt = lambda self_tbl: v.as_int32()
        t.getFloat = lambda self_tbl: v.as_float()

        def getVector2(self_tbl):
            x, y = v.as_vec2()
            o = self.lua.table()
            o.x, o.y = x, y
            return o

        def getVector3(self_tbl):
            x, y, z = v.as_vec3()
            o = self.lua.table()
            o.x, o.y, o.z = x, y, z
            return o

        t.getVector2 = getVector2
        t.getVector3 = getVector3
        return t

    def _text_to_lua(self, fields: dict):
        t = self.lua.table()
        for k, v in (fields or {}).items():
            t[k] = v
        t.action = (fields or {}).get("action", "")
        return t

    def _game_packet_from_tank(self, tank: Tank):
        t = self._class_game_packet()["new"]()
        t.type = tank.type
        t.object_type = tank.object_type
        t.count1 = tank.jump_count
        t.count2 = tank.animation_type
        t.netid = tank.net_id
        t.item = tank.value
        t.flags = tank.flags
        t.float_var = tank.float_variable
        t.vec_x = tank.vector_x
        t.vec_y = tank.vector_y
        t.vec2_x = tank.vector_x2
        t.vec2_y = tank.vector_y2
        t.particle_rotation = tank.particle_rotation
        t.int_x = tank.int_x
        t.int_y = tank.int_y
        # deltaX: `x`/`y` = koordinat PIKSEl, `px`/`py` = koordinat TILE.
        t.x = tank.vector_x
        t.y = tank.vector_y
        t.px = tank.int_x
        t.py = tank.int_y
        return t

    def _listen_events(self, seconds=0) -> None:
        """listenEvents(seconds) — pompa antrean event selama `seconds` detik."""
        try:
            dur = float(seconds)
        except (TypeError, ValueError):
            dur = 0.0
        if dur <= 0:
            dur = 1e9
        self._listening = True
        self._listen_until = time.time() + dur
        try:
            while time.time() < self._listen_until:
                if self._stop.is_set() or self._script_stop.is_set():
                    break
                try:
                    kind, payload = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._route_event(kind, payload)
        finally:
            self._listening = False

    def _unlisten_events(self) -> None:
        self._listening = False
        self._listen_until = 0.0

    # ------------------------------------------------------------------ #
    # Thread
    # ------------------------------------------------------------------ #
    def _run_thread(self, fn, *args) -> None:
        """runThread(fn, ...) — jalankan fungsi Lua di thread terpisah."""
        name = ""
        try:
            name = self.lua.eval(
                'function(f) local i = debug.getinfo(f, "n"); return i and i.name or "" end'
            )(fn)
        except Exception:  # noqa: BLE001
            name = ""

        def target():
            if name:
                try:
                    self.run_function(name, *args)
                    return
                except Exception as e:  # noqa: BLE001
                    self.log_line(f"runThread({name}) gagal: {e}")
            # fallback: jalankan di runtime utama (kurang ideal tapi tetap jalan)
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                self.log_line(f"runThread gagal: {e}")

        th = threading.Thread(target=target, name=f"lua-thread-{name or 'anon'}", daemon=True)
        self.threads.append(th)
        th.start()

    # ------------------------------------------------------------------ #
    # Menjalankan skrip
    # ------------------------------------------------------------------ #
    def run_script_source(self, source: str, label: str = "inline") -> bool:
        # Skrip yang mulai jalan selalu menghapus permintaan stop lama,
        # supaya "Stop" sekali tidak membunuh skrip berikutnya.
        self._script_stop.clear()
        with self._lua_lock:
            try:
                chunk = self.lua.execute(f"--[[{label}]]\n{source}")
                if chunk is not None:
                    try:
                        chunk()
                    except TypeError:
                        pass
                return True
            except LuaStop:
                return True
            except Exception as e:  # noqa: BLE001
                self.log_line(f"skrip '{label}' error: {type(e).__name__}: {e}")
                return False

    def run_script_file(self, path: str | Path) -> bool:
        p = Path(path)
        if not p.exists():
            self.log_line(f"skrip tidak ditemukan: {p}")
            return False
        src = p.read_text(encoding="utf-8", errors="replace")
        ok = self.run_script_source(src, label=p.name)
        if ok:
            self._loaded_files.append(p)
        return ok

    def load_scripts(self, folder: Optional[str | Path] = None, run: bool = False) -> list[str]:
        """Muat semua .lua di folder (kecuali diawali '_').

        Penting: secara bawaan skrip hanya DIMUAT (dikompilasi), tidak
        dijalankan. Alasannya: skrip contoh memanggil listenEvents() yang
        memblokir selama menit-menit, sehingga men-jalankannya saat start akan
        membekukan dashboard/CLI. Skrip dijalankan saat pengguna memintanya
        (tombol "Jalankan" di dashboard, `lucifer run`, atau addEvent+listenEvents).
        """
        d = Path(folder or self.scripts_dir)
        loaded: list[str] = []
        if not d.exists():
            return loaded
        for f in sorted(d.glob("*.lua")):
            if f.name.startswith("_"):
                continue
            if run:
                if self.run_script_file(f):
                    loaded.append(f.name)
            else:
                if self.load_script_file(f):
                    loaded.append(f.name)
        return loaded

    def load_script_file(self, path: str | Path) -> bool:
        """Kompilasi skrip tanpa menjalankannya (untuk validasi/muat awal)."""
        p = Path(path)
        try:
            src = p.read_text(encoding="utf-8")
        except OSError as e:
            self.log_line(f"skrip '{p.name}' tidak terbaca: {e}")
            return False
        try:
            self.lua.execute(f"__lucifer_compiled = assert(load([==[\n{src}\n]==], '{p.name}'))")
            self._scripts[p.name] = str(p)
            return True
        except Exception as e:  # noqa: BLE001
            self.log_line(f"skrip '{p.name}' error saat dimuat: {e}")
            return False

    def run_function(self, name: str, *args) -> bool:
        """Panggil fungsi global Lua di runtime BARU (thread terpisah)."""
        # jalankan di runtime sendiri supaya tidak bentrok dengan runtime utama
        engine = _ThreadEngine(self)
        return engine.call(name, *args)

    def stop(self) -> None:
        self._stop.set()
        self._unlisten_events()
        for bot in list(self.bots.values()):
            try:
                bot.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def stop_scripts(self) -> None:
        """Hentikan skrip Lua yang sedang jalan tanpa memutus bot.

        `stop()` sengaja TIDAK dipakai di sini: itu juga memutus koneksi semua
        bot, padahal pengguna cuma ingin menghentikan loop skrip.
        """
        self._script_stop.set()
        self._unlisten_events()
        self.log_line("skrip dihentikan")


class LuaStop(Exception):
    """Sinyal internal: hentikan sleep()/listenEvents()."""


def _sync_props(tbl, bot: Bot) -> None:
    """Salin properti yang diubah skrip Lua kembali ke objek Bot Python."""
    try:
        for attr in ("move_interval", "move_range", "rest_time", "rest_interval",
                     "auto_reconnect", "auto_accept", "auto_collect", "auto_leave_on_admin",
                     "auto_leave_on_mod", "auto_tutorial", "legit_mode", "collect_interval",
                     "collect_range", "collect_all", "object_collect_delay"):
            val = tbl[attr]
            if val is not None:
                setattr(bot, attr, val)
    except Exception:  # noqa: BLE001
        pass


class _ThreadEngine:
    """Runtime Lua terpisah untuk runThread/runScript per-bot.

    Setiap runtime baru memuat ulang file skrip utama lalu memanggil fungsi
    yang diminta — cara ini menjaga agar tiap thread punya state Lua sendiri
    (LuaRuntime lupa tidak aman dipakai bersama antar-thread).
    """

    def __init__(self, parent: LuaEngine) -> None:
        self.parent = parent
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self._register()

    def _register(self) -> None:
        p = self.parent
        g = self.lua.globals()
        g.print = p.log_line
        g.sleep = lambda ms: time.sleep(max(0.0, float(ms) / 1000.0))
        g.read = p._read_file
        g.write = p._write_file
        g.removeColor = lambda t: remove_color(t)
        g.getUsername = lambda: p.username
        g.getInfo = p._get_info
        g.getInfos = p._get_infos
        g.addBot = p._add_bot
        g.addUbiBot = p._add_ubi_bot
        g.removeBot = p._remove_bot
        g.getBot = p._get_bot
        g.addEvent = p._add_event
        g.removeEvent = p._remove_event
        g.removeEvents = p._remove_events
        g.listenEvents = p._listen_events
        g.unlistenEvents = p._unlisten_events
        g.runThread = p._run_thread
        g.getProxyManager = p._get_proxy_manager
        g.getWorldManager = p._get_world_manager
        g.addProxy = p._add_proxy
        g.removeProxy = p._remove_proxy
        g.getWorld = lambda bot=None: p._world_of(bot)
        g.getInventory = lambda bot=None: p._inventory_of(bot)
        g.getLocal = lambda bot=None: p._local_of(bot)
        g.getTile = lambda x, y, bot=None: p._tile_of(x, y, bot)
        g.getTiles = lambda bot=None: p._tiles_of(bot)
        g.getTilesSafe = lambda bot=None: p._tiles_of(bot)
        g.getObject = lambda oid, bot=None: p._object_of(oid, bot)
        g.getObjects = lambda bot=None: p._objects_of(bot)
        g.getPlayer = lambda key, bot=None: p._player_of(key, bot)
        g.getPlayers = lambda bot=None: p._players_of(bot)
        g.getNPC = lambda npcid, bot=None: None
        g.getNPCs = lambda bot=None: self.lua.table()
        g.hasAccess = lambda x, y, bot=None: p._has_access(x, y, bot)
        for enum_name, members in ENUMS.items():
            t = self.lua.table()
            for k, v in members.items():
                t[k] = v
            g[enum_name] = t
        for name, value in ACCOUNT_TYPE_CONSTS.items():
            g[name] = value
        g.variant = p._class_variant()
        g.variantlist = p._class_variantlist()
        g.GameUpdatePacket = p._class_game_packet()
        g.HttpClient = p._class_http_client()
        g.Webhook = p._class_webhook()
        g.Embed = p._class_embed()
        g.RTVAR = p._class_rtvar()
        g.Vector2 = p._class_vector("2")
        g.Vector3 = p._class_vector("3")
        p._register_features(g)
        from .compat_deltax import pasang as _pasang_deltax  # noqa: PLC0415

        _pasang_deltax(p)

    def call(self, name: str, *args) -> bool:
        """Muat ulang semua skrip lalu panggil fungsi global `name`."""
        for f in list(self.parent._loaded_files):
            try:
                self.lua.execute(f.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:  # noqa: BLE001
                self.parent.log_line(f"[thread] gagal muat {f.name}: {e}")
        fn = self.lua.globals()[name]
        if fn is None:
            self.parent.log_line(f"[thread] fungsi '{name}' tidak ditemukan")
            return False
        try:
            fn(*args)
            return True
        except Exception as e:  # noqa: BLE001
            self.parent.log_line(f"[thread] '{name}' error: {type(e).__name__}: {e}")
            return False


# Helper supaya shortcut global bisa mengembalikan struct bot-spesifik
def _attach_shortcuts(engine: LuaEngine) -> None:  # pragma: no cover - dokumentasi
    """Placeholder: shortcut sudah didaftarkan di _register_api()."""
    return None


# Monkey-patch: shortcut butuh tabel, bukan objek Python
def _world_of(self: LuaEngine, bot=None):
    return self._world_table(self._resolve_bot(bot))


def _inventory_of(self: LuaEngine, bot=None):
    return self._inventory_table(self._resolve_bot(bot))


LuaEngine._world_of = _world_of  # type: ignore[attr-defined]
LuaEngine._inventory_of = _inventory_of  # type: ignore[attr-defined]
