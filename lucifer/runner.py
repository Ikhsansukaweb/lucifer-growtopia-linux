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

# Folder repo (…/lucifer/runner.py -> …). Dasar path bawaan supaya `data/` dan
# `scripts/` tetap ketemu walau backend dijalankan dari folder lain (GUI
# native menjalankan `lucifer web`, terminal bisa dari folder mana pun).
# Tanpa ini backend membuat `data/` kosong di cwd dan akun/skrip pengguna
# seolah "hilang".
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class RunnerConfig:
    """Konfigurasi satu sesi Lucifer."""

    accounts: list[Account] = field(default_factory=list)
    scripts_dir: str = str(ROOT / "scripts")
    examples_dir: str = str(ROOT / "examples")
    data_dir: str = str(ROOT / "data")
    items_path: str = str(ROOT / "data" / "items.dat")
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
        # Skrip yang sedang berjalan. HANYA SATU boleh jalan: dua skrip
        # berebut `bot.local.posx`, posisi maju-mundur, dan server melihat
        # gerakan mustahil -> shadowban. Bukti jurnal: 8 paket State dalam
        # 1 detik dengan posisi 544->576->608->544 (lompat balik).
        self._script_thread: Optional[threading.Thread] = None
        self._script_nama = ""
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
                self._simpan_token(bot)
            else:
                self._log(f"[{bot.label}] gagal connect (status={bot.status})")
                self._selamatkan_token(bot)
        except Exception as e:  # noqa: BLE001
            self._log(f"[{bot.label}] error connect: {type(e).__name__}: {e}")

    def _simpan_token(self, bot: Bot) -> None:
        """Simpan ltoken hasil penyegaran supaya tidak hilang saat backend mati.

        Token ini sudah terpakai untuk login, jadi login berikutnya WAJIB
        memanggil `check_token` lagi (lihat `Bot._segarkan_token`).
        """
        baru = getattr(bot.account, "ltoken", "")
        if not baru:
            return
        try:
            upsert_account(self.accounts_path, bot.account)
        except Exception as e:  # noqa: BLE001
            self._log(f"[{bot.label}] gagal simpan ltoken: {e}")

    def _selamatkan_token(self, bot: Bot) -> None:
        """Bedakan `token mati` dari `cooldown` setelah login ditolak.

        Pesan server `Fail to login. Please try again in 30 seconds.` adalah
        balasan GENERIK untuk kredensial yang ditolak — pesan yang sama muncul
        untuk kredensial palsu (lihat tests/test_integration.py). Jadi pesan itu
        TIDAK bisa dipakai membedakan token mati dari cooldown IP.

        Satu-satunya cara membedakan: tanya /player/growid/checktoken.
          * "Token is invalid."          -> token MATI, harus ambil ltoken baru
          * "Account Validated." + token -> token hidup (dan server merotasi)
        Karena checktoken MEROTASI token, hasilnya langsung disimpan supaya
        token lama yang sudah tidak berlaku tidak dipakai connect berikutnya.
        """
        if bot.status not in (BotStatus.logon_fail, BotStatus.too_many_login,
                              BotStatus.invalid_account):
            return
        token = getattr(bot.account, "_token", "") or bot.account.ltoken
        if not token:
            return

        from .account import check_token  # noqa: PLC0415

        try:
            res = check_token(token, timeout=15)
        except Exception as e:  # noqa: BLE001
            self._log(f"[{bot.label}] tidak bisa cek token: {type(e).__name__}")
            return

        if not res.ok:
            bot.status = BotStatus.invalid_account
            self._log(
                f"[{bot.label}] TOKEN MATI — server bilang '{res.message}'. "
                "Ambil ltoken baru (panel Login: tab HP/Android, atau login "
                "Google di klien resmi). Bukan masalah cooldown."
            )
            return

        baru = res.token or token
        if baru != token:
            bot.account._token = baru
            bot.account.ltoken = baru
            try:
                upsert_account(self.accounts_path, bot.account)
            except Exception as e:  # noqa: BLE001
                self._log(f"[{bot.label}] gagal simpan token baru: {e}")
            self._log(
                f"[{bot.label}] token disegarkan server ({len(baru)} char); "
                "token lama sudah tidak berlaku. Connect sekali lagi."
            )
            return

        self._log(
            f"[{bot.label}] token masih HIDUP — server hanya menahan login "
            f"(cooldown IP). Jangan connect berulang; tunggu sesuai pesan."
        )

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
        proxy: str = "",
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

        # Validasi + SEGARKAN ltoken. checktoken mengembalikan token BARU
        # (berbeda dari yang dikirim), dan hanya token hasil penyegaran itu
        # yang dianggap server masih hidup. Menyimpan token lama lalu
        # memakainya untuk connect menghasilkan penolakan kredensial.
        pesan_validasi = ""
        if ltoken:
            try:
                res = check_token(ltoken, timeout=15)
                if res.ok:
                    if res.token and res.token != ltoken:
                        ltoken = res.token
                        pesan_validasi = "ltoken disegarkan (token baru dari server)"
                    else:
                        pesan_validasi = "ltoken valid"
                else:
                    pesan_validasi = f"peringatan: server bilang '{res.message}'"
            except Exception as e:  # noqa: BLE001
                pesan_validasi = f"peringatan: tidak bisa cek token ({type(e).__name__})"

        # Proxy SOCKS5 opsional; format dinormalkan sekali di sini supaya
        # bot tinggal memakai hasil parse-nya.
        proxy_bersih = ""
        if proxy:
            from .proxy import parse as _parse_proxy  # noqa: PLC0415
            try:
                _p = _parse_proxy(proxy)
                proxy_bersih = _p.url() if _p else ""
            except ValueError as e:
                return {"ok": False, "error": f"proxy tidak valid: {e}"}

        acc = Account(
            label=label,
            username=username or label,
            # Sandi tidak disimpan kalau sudah berhasil ditukar jadi ltoken —
            # ltoken tidak bisa dipakai untuk membalikkan sandi, jadi ini lebih aman.
            password="" if ltoken else password,
            ltoken=ltoken,
            method=method,
            proxy=proxy_bersih or None,
        )
        path, baru = upsert_account(self.accounts_path, acc)
        self._log(f"[akun] {'ditambah' if baru else 'diperbarui'}: {label} ({method})")
        if pesan_validasi:
            self._log(f"[akun] {label}: {pesan_validasi}")

        # Buat bot kalau engine sudah siap
        dibuat = False
        if self.engine is not None:
            if label in self.engine.bots:
                bot_lama = self.engine.bots[label]
                bot_lama.account = acc
                bot_lama.proxy = acc.proxy
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

    def atur_proxy(self, label: str, proxy: str) -> dict[str, Any]:
        """Set/ganti/hapus proxy SOCKS5 satu akun. `proxy` kosong = hapus."""
        label = (label or "").strip()
        if not label:
            return {"ok": False, "error": "label akun wajib diisi"}

        bersih = ""
        if proxy:
            from .proxy import parse as _parse_proxy  # noqa: PLC0415
            try:
                _p = _parse_proxy(proxy)
                bersih = _p.url() if _p else ""
            except ValueError as e:
                return {"ok": False, "error": f"proxy tidak valid: {e}"}

        akun = next((a for a in load_accounts(self.accounts_path) if a.label == label), None)
        if akun is None and not (self.engine and label in self.engine.bots):
            return {"ok": False, "error": f"akun '{label}' tidak ditemukan"}
        if akun is not None:
            akun.proxy = bersih or None
            upsert_account(self.accounts_path, akun)
        if self.engine and label in self.engine.bots:
            self.engine.bots[label].proxy = bersih or None

        self._log(f"[akun] {label}: proxy {'diset' if bersih else 'dihapus'}")
        return {"ok": True, "label": label, "proxy": bersih}

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
            # Skrip bisa jalan menit-menitan (loop tile, Sleep, listenEvents).
            # Menjalankannya sinkron membuat HTTP request menggantung sampai
            # klien menyerah -> BrokenPipeError. Jalankan di thread sendiri.
            nama = parts[1]
            # Tolak skrip kedua yang masih hidup. Tanpa ini tiap klik
            # "Jalankan" menambah thread dan semuanya menembak paket gerak
            # ke bot yang sama.
            if self._script_thread is not None and self._script_thread.is_alive():
                return {"ok": False,
                        "error": f"skrip '{self._script_nama}' masih berjalan — "
                                 f"hentikan dulu (stopscript)"}

            def jalan() -> None:
                try:
                    self.run_script(nama)
                finally:
                    self._script_nama = ""

            th = threading.Thread(target=jalan, name=f"skrip-{nama}",
                                  daemon=True)
            self._script_thread = th
            self._script_nama = nama
            th.start()
            return {"ok": True, "script": nama, "pesan": "skrip dijalankan"}
        if cmd == "stop":
            threading.Thread(target=self.stop, daemon=True).start()
            return {"ok": True, "message": "berhenti"}
        if cmd in ("stopscript", "stop_script", "stoplua"):
            if self.engine:
                self.engine.stop_scripts()
                return {"ok": True, "message": "skrip dihentikan"}
            return {"ok": False, "error": "engine belum siap"}
        # respawn/collect tidak butuh argumen: boleh diketik telanjang dari
        # konsol Executor ("collect") maupun lewat label dari GUI.
        if cmd in ("say", "warp", "connect", "disconnect", "move", "enter",
                   "respawn", "collect", "profil"):
            if not self.engine:
                return {"ok": False, "error": "engine belum siap"}
            # GUI mengirim "say <teks>" tanpa nama bot; CLI memakai
            # "say <bot> <teks>". Kalau kata pertama bukan label bot yang
            # terdaftar, seluruh sisa baris dianggap argumen bot utama.
            bots = self.engine.bots or {}
            kepala = parts[1].split(maxsplit=1)[0] if len(parts) > 1 else ""
            if kepala and kepala in bots:
                bot = bots[kepala]
                arg = parts[2] if len(parts) > 2 else ""
            else:
                # Tak ada nama bot di depan: pakai bot utama, atau satu-satunya
                # bot yang ada. Untuk "say", seluruh sisa baris = teks chat.
                bot = self.engine.parent or (list(bots.values())[0] if len(bots) == 1 else None)
                arg = " ".join(parts[1:])
            if not bot:
                return {
                    "ok": False,
                    "error": (
                        f"bot '{kepala}' tidak ada. Belum ada akun terdaftar — "
                        "isi data/accounts.json atau jalankan "
                        "`lucifer login --ltoken \"<TOKEN>\"` dulu."
                    ),
                }
            if cmd == "say":
                return {"ok": bot.say(arg)}
            if cmd == "warp":
                ke = arg.strip()
                dari = bot.world.name if bot.world else ""
                hasil = bot.warp(ke)
                if hasil:
                    return {"ok": True, "dari": dari, "ke": bot.world.name or ke,
                            "pesan": f"masuk {bot.world.name or ke}"}
                return {"ok": False, "dari": dari, "ke": ke,
                        "error": (f"gagal warp ke '{ke}' — server tidak mengirim data dunia "
                                  f"dalam 10 detik (bot masih di '{dari or '?'}'; "
                                  "cek nama dunia, akses, atau status login bot)")}
            if cmd == "connect":
                return {"ok": bot.connect()}
            if cmd == "disconnect":
                bot.disconnect()
                return {"ok": True}
            if cmd == "move":
                bit = arg.split()
                direction = bit[0].lower() if bit else ""
                step = int(bit[1]) if len(bit) > 1 and bit[1].isdigit() else 1
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
            if cmd == "profil":
                # Minta dialog profil diri sendiri: satu-satunya sumber level.
                return {"ok": bot.minta_profil()}
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
