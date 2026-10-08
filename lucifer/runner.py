"""
lucifer.runner — Penjalankan skrip: muat, jalankan, pantau, hot-reload.

Kelas Runner adalah lapisan yang dipakai CLI dan Web UI:
  * menyiapkan engine Lua + bot dari daftar akun
  * memuat skrip dari folder scripts/
  * memantau perubahan file dan memuat ulang otomatis (hot reload)
  * menyediakan snapshot status untuk dashboard
"""

from __future__ import annotations

import json
import logging
import signal as signal_mod
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .account import (
    Account,
    check_token,
    growid_login,
    load_accounts,
    remove_account,
    upsert_account,
)
from .lua_api import _hint_login as _saran_login
from .bot import Bot, BotStatus
from .items import ItemDatabase

log = logging.getLogger("lucifer.runner")


@dataclass
class RunnerConfig:
    """Konfigurasi satu sesi Lucifer."""

    accounts: list[Account] = field(default_factory=list)
    scripts_dir: str = "scripts"
    examples_dir: str = "examples"
    data_dir: str = "data"
    items_path: str = "data/items.dat"
    username: str = "linux"
    hot_reload: bool = True
    auto_connect: bool = True
    listen_seconds: float = 0.0  # 0 = tanpa batas
    log_file: Optional[str] = None


class Runner:
    """Mengelola engine Lua + bot + skrip."""

    def __init__(self, config: Optional[RunnerConfig] = None) -> None:
        self.config = config or RunnerConfig()
        self.engine = None
        self.items_db: Optional[ItemDatabase] = None
        self._stop = threading.Event()
        self._watcher: Optional[threading.Thread] = None
        self._mtimes: dict[str, float] = {}
        self._log_buffer: list[str] = []
        self._log_lock = threading.Lock()
        self._started_at = time.time()

    # ------------------------------------------------------------------ #
    # Persiapan
    # ------------------------------------------------------------------ #
    def setup(self) -> None:
        from .lua_api import LuaEngine  # noqa: PLC0415

        self._load_items()

        if not self.config.accounts:
            # PENTING: pakai self.accounts_path (menghormati config.data_dir),
            # BUKAN path hardcoded — kalau hardcoded, `--data <folder>` akan
            # membaca akun dari folder yang salah dan uji jadi tak hermetik.
            self.config.accounts = load_accounts(self.accounts_path)
        if not self.config.accounts:
            # Tanpa akun, engine tetap dibuat supaya dashboard & skrip bisa
            # diuji (mode pantau). Login baru diperlukan saat connect().
            self._log(
                "belum ada akun: isi data/accounts.json atau set LUCIFER_USER/"
                "LUCIFER_PASS, lalu `lucifer login --ltoken ...` "
                "(lihat README bagian 'Login Google'). Bot tidak akan connect."
            )
            self.config.auto_connect = False

        self.engine = LuaEngine(
            accounts=self.config.accounts,
            items_db=self.items_db,
            scripts_dir=self.config.scripts_dir,
            data_dir=self.config.data_dir,
            username=self.config.username,
            on_log=self._log,
        )

        for acc in self.config.accounts:
            self.engine._new_bot(acc, acc.label)
        if self.engine.bots:
            self._log(f"{len(self.engine.bots)} bot disiapkan: {', '.join(self.engine.bots)}")
        else:
            self._log("mode pantau: 0 bot (dashboard & skrip tetap bisa dipakai)")

        if self.items_db:
            self._log(f"items.dat dimuat: {len(self.items_db)} item (v{self.items_db.version})")
        else:
            self._log("items.dat belum ada — bot akan memintanya dari server saat masuk dunia")

        # Muat skrip (hanya dikompilasi, tidak dijalankan — lihat load_scripts).
        loaded = self.engine.load_scripts(self.config.scripts_dir)
        if Path(self.config.examples_dir).exists():
            loaded += self.engine.load_scripts(self.config.examples_dir)
        self._log(f"skrip dimuat: {len(loaded)} berkas" + (f" ({', '.join(loaded)})" if loaded else ""))

    def _load_items(self) -> None:
        p = Path(self.config.items_path)
        if p.exists():
            try:
                self.items_db = ItemDatabase.from_file(p)
            except Exception as e:  # noqa: BLE001
                self._log(f"gagal membaca {p}: {e}")
                self.items_db = None

    # ------------------------------------------------------------------ #
    # Log
    # ------------------------------------------------------------------ #
    def _log(self, text: str) -> None:
        with self._log_lock:
            self._log_buffer.append(text)
            if len(self._log_buffer) > 2000:
                del self._log_buffer[:500]
        print(text, flush=True)
        if self.config.log_file:
            try:
                with open(self.config.log_file, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except OSError:
                pass

    def logs(self, limit: int = 200) -> list[str]:
        with self._log_lock:
            return self._log_buffer[-limit:]

    # ------------------------------------------------------------------ #
    # Jalan
    # ------------------------------------------------------------------ #
    def start(self, block: bool = True) -> None:
        if self.engine is None:
            self.setup()

        if self.config.auto_connect:
            for bot in self.engine.bots.values():
                threading.Thread(target=self._connect_bot, args=(bot,), daemon=True).start()

        if self.config.hot_reload:
            self._watcher = threading.Thread(target=self._watch_scripts, daemon=True)
            self._watcher.start()

        if block:
            self.wait()

    def _connect_bot(self, bot: Bot) -> None:
        try:
            self._log(f"[{bot.label}] connect ke server Growtopia...")
            if bot.connect():
                self._log(f"[{bot.label}] terhubung ({bot.server[0]}:{bot.server[1]})")
            else:
                self._log(f"[{bot.label}] gagal connect (status={bot.status})")
        except Exception as e:  # noqa: BLE001
            self._log(f"[{bot.label}] error connect: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------ #
    # Akun (dipakai dashboard: login/hapus/connect dari UI)
    # ------------------------------------------------------------------ #
    @property
    def accounts_path(self) -> Path:
        return Path(self.config.data_dir) / "accounts.json"

    def tambah_akun(
        self,
        label: str,
        username: str = "",
        password: str = "",
        ltoken: str = "",
        method: str = "",
        connect: bool = False,
    ) -> dict[str, Any]:
        """Tambah akun dari dashboard: simpan ke accounts.json + buat bot.

        method otomatis:
          * ada ltoken           -> "token"
          * ada username+sandi   -> "growid"
        """
        label = (label or username or "").strip()
        if not label:
            return {"ok": False, "error": "label/nama akun wajib diisi"}

        ltoken = (ltoken or "").strip()
        username = (username or "").strip()
        password = password or ""

        if not ltoken and not (username and password):
            return {
                "ok": False,
                "error": "isi ltoken, atau username + sandi (untuk login GrowID)",
            }

        if not method:
            method = "token" if ltoken else "growid"

        # Kalau pengguna memberi nama + sandi GrowID, TUKAR dulu jadi ltoken.
        # Ini langkah yang wajib: server game butuh ltoken, bukan sandi.
        if not ltoken and username and password:
            self._log(f"[akun] {label}: login GrowID untuk mengambil ltoken…")
            try:
                res = growid_login(username, password)
                if res.ok and res.token:
                    ltoken = res.token
                    method = "token"
                    self._log(f"[akun] {label}: ltoken didapat "
                              f"({len(ltoken)} karakter)")
                else:
                    pesan = res.message or "server tidak memberi token"
                    saran = _saran_login(pesan)
                    self._log(f"[akun] {label}: GAGAL ambil ltoken — {pesan}")
                    if saran:
                        self._log(f"[akun] {label}: saran: {saran}")
                    return {
                        "ok": False,
                        "error": f"login GrowID gagal: {pesan}",
                        "saran": saran,
                        "details": getattr(res, "details", {}),
                    }
            except Exception as e:  # noqa: BLE001
                self._log(f"[akun] {label}: ERROR saat login GrowID: {e}")
                return {
                    "ok": False,
                    "error": f"gagal menghubungi server login: "
                             f"{type(e).__name__}: {e}",
                }

        # Validasi ltoken dulu kalau ada — supaya tidak menyimpan token mati
        pesan_validasi = ""
        if ltoken:
            try:
                res = check_token(ltoken, timeout=15)
                if res.ok:
                    pesan_validasi = "ltoken valid"
                else:
                    pesan_validasi = f"peringatan: server bilang '{res.message}'"
            except Exception as e:  # noqa: BLE001
                pesan_validasi = f"peringatan: tidak bisa cek token ({type(e).__name__})"

        acc = Account(
            label=label,
            username=username or label,
            # Sandi tidak disimpan kalau sudah berhasil ditukar jadi ltoken —
            # ltoken tidak bisa dipakai untuk membalikkan sandi, jadi ini lebih aman.
            password="" if ltoken else password,
            ltoken=ltoken,
            method=method,
        )
        path, baru = upsert_account(self.accounts_path, acc)
        self._log(f"[akun] {'ditambah' if baru else 'diperbarui'}: {label} ({method})")
        if pesan_validasi:
            self._log(f"[akun] {label}: {pesan_validasi}")

        # Buat bot kalau engine sudah siap
        dibuat = False
        if self.engine is not None:
            if label in self.engine.bots:
                self.engine.bots[label].account = acc
            else:
                self.engine._new_bot(acc, label)
                dibuat = True
            self.config.accounts = [b.account for b in self.engine.bots.values()]

        hasil: dict[str, Any] = {
            "ok": True,
            "label": label,
            "method": method,
            "baru": baru,
            "bot_dibuat": dibuat,
            "file": str(path),
        }
        if pesan_validasi:
            hasil["catatan"] = pesan_validasi

        if connect:
            hasil["connect"] = self.connect_bot(label)
        return hasil

    def hapus_akun(self, label: str) -> dict[str, Any]:
        """Hapus akun + bot-nya."""
        label = (label or "").strip()
        if not label:
            return {"ok": False, "error": "label akun wajib diisi"}

        ada_di_file = any(a.label == label for a in load_accounts(self.accounts_path))
        ada_di_engine = bool(self.engine and label in self.engine.bots)
        if not ada_di_file and not ada_di_engine:
            return {"ok": False, "error": f"akun '{label}' tidak ditemukan"}

        if ada_di_file:
            remove_account(self.accounts_path, label)

        if ada_di_engine and self.engine:
            bot = self.engine.bots.pop(label)
            try:
                bot.disconnect()
            except Exception as e:  # noqa: BLE001
                log.debug("disconnect saat hapus: %s", e)
            if self.engine.parent is bot:
                self.engine.parent = next(iter(self.engine.bots.values()), None)
            self.config.accounts = [b.account for b in self.engine.bots.values()]

        self._log(f"[akun] dihapus: {label}")
        return {"ok": True, "label": label}

    def connect_bot(self, label: str = "") -> dict[str, Any]:
        """Connect satu bot (atau semua kalau label kosong) di latar belakang."""
        if self.engine is None:
            return {"ok": False, "error": "engine belum siap"}

        target: list[Bot] = []
        if label:
            bot = self.engine.bots.get(label)
            if bot is None:
                return {"ok": False, "error": f"bot '{label}' tidak ada"}
            target = [bot]
        else:
            target = list(self.engine.bots.values())

        if not target:
            return {"ok": False, "error": "tidak ada bot — tambah akun dulu"}

        for bot in target:
            if bot.status == "online":
                continue
            threading.Thread(target=self._connect_bot, args=(bot,), daemon=True).start()
        return {"ok": True, "mulai_connect": [b.label for b in target]}

    def disconnect_bot(self, label: str = "") -> dict[str, Any]:
        if self.engine is None:
            return {"ok": False, "error": "engine belum siap"}
        target = [self.engine.bots[label]] if label in self.engine.bots else list(self.engine.bots.values())
        for bot in target:
            try:
                bot.disconnect()
            except Exception as e:  # noqa: BLE001
                log.debug("disconnect %s: %s", bot.label, e)
            self._log(f"[{bot.label}] diputus")
        return {"ok": True, "diputus": [b.label for b in target]}

    def daftar_akun(self) -> list[dict[str, Any]]:
        """Akun tersimpan (tanpa membocorkan sandi/token penuh)."""
        keluar = []
        for a in load_accounts(self.accounts_path):
            d = a.redacted()
            d["punya_ltoken"] = bool(a.ltoken)
            d["punya_sandi"] = bool(a.password)
            keluar.append(d)
        return keluar

    def wait(self) -> None:
        """Pompa event sampai dihentikan."""
        self._log("runner aktif. Tekan Ctrl+C untuk berhenti.")
        try:
            while not self._stop.is_set():
                if self.engine:
                    self.engine._listen_events(1.0)
                else:
                    time.sleep(0.2)
        except KeyboardInterrupt:
            self._log("dihentikan oleh pengguna")
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        if self.engine:
            self.engine.stop()
        self._log("runner berhenti")

    # ------------------------------------------------------------------ #
    # Hot reload
    # ------------------------------------------------------------------ #
    def _watch_scripts(self) -> None:
        d = Path(self.config.scripts_dir)
        while not self._stop.is_set():
            try:
                for f in d.glob("*.lua"):
                    if f.name.startswith("_"):
                        continue
                    mtime = f.stat().st_mtime
                    old = self._mtimes.get(f.name)
                    if old is None:
                        self._mtimes[f.name] = mtime
                    elif mtime > old:
                        self._mtimes[f.name] = mtime
                        self._log(f"[hot-reload] {f.name} berubah — memuat ulang")
                        if self.engine:
                            self.engine.run_script_file(f)
            except Exception as e:  # noqa: BLE001
                log.debug("watcher error: %s", e)
            time.sleep(1.5)

    # ------------------------------------------------------------------ #
    # Kontrol manual (dipakai CLI/Web UI)
    # ------------------------------------------------------------------ #
    def run_script(self, name_or_path: str) -> bool:
        if not self.engine:
            self._log("engine belum siap")
            return False
        p = Path(name_or_path)
        if not p.exists():
            # cari di scripts/ lalu examples/
            for d in (self.config.scripts_dir, self.config.examples_dir):
                cand = Path(d) / name_or_path
                if cand.exists():
                    p = cand
                    break
        if p.exists():
            return self.engine.run_script_file(p)
        self._log(f"skrip '{name_or_path}' tidak ditemukan")
        return False

    def command(self, text: str) -> dict[str, Any]:
        """Jalankan perintah teks (dipakai Web UI).

        Perintah: status | bots | logs | reload | run <skrip> | stop |
                  say <bot> <teks> | warp <bot> <dunia> | connect <bot> |
                  disconnect <bot>
        """
        parts = text.strip().split(maxsplit=2)
        if not parts:
            return {"ok": False, "error": "perintah kosong"}
        cmd = parts[0].lower()

        if cmd == "status":
            return {"ok": True, "status": self.snapshot()}
        if cmd == "bots":
            return {"ok": True, "bots": list(self.engine.bots) if self.engine else []}
        if cmd == "logs":
            return {"ok": True, "logs": self.logs()}
        if cmd == "reload":
            if self.engine:
                loaded = self.engine.load_scripts(self.config.scripts_dir)
                return {"ok": True, "loaded": loaded}
            return {"ok": False, "error": "engine belum siap"}
        if cmd == "run" and len(parts) > 1:
            return {"ok": self.run_script(parts[1]), "script": parts[1]}
        if cmd == "stop":
            threading.Thread(target=self.stop, daemon=True).start()
            return {"ok": True, "message": "berhenti"}
        if cmd in ("say", "warp", "connect", "disconnect", "move", "enter", "respawn", "collect") and len(parts) > 1:
            if not self.engine:
                return {"ok": False, "error": "engine belum siap"}
            bot = self.engine.bots.get(parts[1]) or self.engine.parent
            if not bot:
                return {
                    "ok": False,
                    "error": (
                        f"bot '{parts[1]}' tidak ada. Belum ada akun terdaftar — "
                        "isi data/accounts.json atau jalankan "
                        "`lucifer login --ltoken \"<TOKEN>\"` dulu."
                    ),
                }
            arg = parts[2] if len(parts) > 2 else ""
            if cmd == "say":
                return {"ok": bot.say(" ".join(parts[2:]))}
            if cmd == "warp":
                return {"ok": bot.warp(arg)}
            if cmd == "connect":
                return {"ok": bot.connect()}
            if cmd == "disconnect":
                bot.disconnect()
                return {"ok": True}
            if cmd == "move":
                direction = arg.lower()
                step = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
                if direction in ("left", "kiri"): return {"ok": bot.moveLeft(step)}
                if direction in ("right", "kanan"): return {"ok": bot.moveRight(step)}
                if direction in ("up", "atas"): return {"ok": bot.moveUp(step)}
                if direction in ("down", "bawah"): return {"ok": bot.moveDown(step)}
                return {"ok": False, "error": "arah move: left/right/up/down"}
            if cmd == "enter":
                return {"ok": bot.enter(arg)}
            if cmd == "respawn":
                return {"ok": bot.respawn()}
            if cmd == "collect":
                rng = int(arg) if arg.isdigit() else 3
                return {"ok": True, "collected": bot.collect(range_=rng)}
        return {"ok": False, "error": f"perintah tidak dikenal: {cmd}"}

    # ------------------------------------------------------------------ #
    # Snapshot untuk dashboard
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict[str, Any]:
        bots = []
        if self.engine:
            for bot in self.engine.bots.values():
                s = bot.stats()
                s["is_parent"] = bot is self.engine.parent
                bots.append(s)
        scripts: list[str] = []
        for d in (self.config.scripts_dir, self.config.examples_dir):
            p = Path(d)
            if p.exists():
                scripts += [f.name for f in sorted(p.glob("*.lua")) if not f.name.startswith("_")]
        return {
            "uptime": int(time.time() - self._started_at),
            "running": not self._stop.is_set(),
            "accounts": len(self.config.accounts),
            "accounts_list": self.daftar_akun(),
            "scripts": scripts,
            "items_loaded": len(self.items_db) if self.items_db else 0,
            "bots": bots,
            "log_tail": self.logs(40),
        }

    def snapshot_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False, default=str)


def load_config(path: str | Path) -> RunnerConfig:
    """Muat konfigurasi runner dari JSON.

    Contoh data/config.json:
        {
          "scripts_dir": "scripts",
          "data_dir": "data",
          "hot_reload": true,
          "auto_connect": true,
          "username": "ikhsan",
          "accounts": [
            {"label": "main", "username": "Nama", "password": "rahasia", "method": "growid"}
          ]
        }
    """
    p = Path(path)
    if not p.exists():
        return RunnerConfig()
    raw = json.loads(p.read_text())
    accounts = [Account(**a) for a in raw.pop("accounts", [])]
    cfg = RunnerConfig(accounts=accounts)
    for k, v in raw.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
