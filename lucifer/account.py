"""
lucifer.account — Login ke Growtopia.

Dua jalur login yang didukung:

1. LEGACY  (tankIDName / tankIDPass)
   Dikirim apa adanya ke server game. Cocok untuk akun lama.
   Pakai: Account(username="Nama", password="rahasia", method="legacy")

2. GROWID  (ltoken)
   Ambil token dari login.growtopiagame.com lalu pakai sebagai `ltoken`.
   Pakai: Account(username="Nama", password="rahasia", method="growid")

CATATAN PENTING
--------------
Login web Growtopia milik Ubisoft dan alurnya BERUBAH tanpa pemberitahuan
(mis. dashboard kini menjawab JSON, bukan HTML form). Modul ini karena itu
memakai beberapa strategi berurutan dan selalu melaporkan APA yang terjadi.
Kalau semua gagal, pesan errornya berisi respons mentah server supaya bisa
didiagnosis — bukan gagal diam-diam.

Untuk memakai tanpa menyimpan sandi di skrip: set env LUCIFER_USER /
LUCIFER_PASS, atau simpan di data/accounts.json.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("lucifer.account")

# --------------------------------------------------------------------------- #
# Identitas klien saat login ke server game
# --------------------------------------------------------------------------- #
# Hasil uji langsung ke server Growtopia (2026-09-29):
#
#   platformID|0,1,1  -> server menganggap klien PC
#                        -> Authentication_error|28 + "UPDATE REQUIRED! ...
#                           GrowtopiaInstaller.exe"  (akun mobile DITOLAK)
#   platformID|3,1,1  -> server menganggap klien ANDROID/mobile
#                        -> server membalas `OnSendToServer` = LOGIN DITERIMA
#
# Akun hasil login Google/Apple terdaftar sebagai akun **mobile**, jadi bot
# WAJIB mengaku klien Android supaya bisa masuk.
PLATFORM_MOBILE = "platformID|3,1,1"

# Nilai mentah `platformID` (tanpa nama kunci) untuk dipakai di client_data.
PLATFORM_ID_MOBILE = "3,1,1"
PLATFORM_ID_PC = "0,1,1"

# Versi Android yang dilaporkan klien (Android 10 = 29).
DEVICE_VERSION_MOBILE = "29"

__all__ = ["Account", "LoginResult", "fetch_server_data", "growid_login", "load_accounts"]

SERVER_DATA_URLS = (
    "https://www.growtopia1.com/growtopia/server_data.php",
    "https://www.growtopia2.com/growtopia/server_data.php",
)
GAME_UA = "UbiServices_SDK_2022.Release.9_PC64_ansi_static"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
LOGIN_HOST = "https://login.growtopiagame.com"
DASHBOARD_VALKEY = "40db4045f2d8c572efe8c4a060605726"


@dataclass
class LoginResult:
    ok: bool
    method: str = ""
    token: str = ""
    message: str = ""
    raw: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return f"LoginResult(ok={self.ok}, method={self.method!r}, msg={self.message!r})"


def _requests():
    try:
        import requests  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Butuh paket 'requests'. Jalankan: pip install requests") from e
    return requests


# --------------------------------------------------------------------------- #
# Server data (endpoint resmi)
# --------------------------------------------------------------------------- #
def ambil_pesan_maintenance(data: dict[str, str]) -> str:
    """Ambil pesan maintenance yang **AKTIF** dari `server_data.php` (atau '').

    ⚠️ KOREKSI PENTING (2026-09-30) — logika lama TERBALIK.

    Format resmi `server_data.php` (dokumentasi GrowtopiaNoobs/GrowDocs):

        server|1.2.3.4
        port|17091
        type|1
        #maint|Server is under maintenance. We will be back online shortly!
        meta|...

    Kunci `#maint` (dengan `#`) berarti baris itu **DIKOMENTARI / TIDAK AKTIF**
    — server SELALU mengirimnya sebagai templat, jadi keberadaannya **BUKAN**
    tanda maintenance. Maintenance baru benar-benar aktif kalau server mengirim
    `maint|...` **TANPA** `#`.

    Kode lama mencari kunci ber-`#` dan menyimpulkan "maintenance" — akibatnya
    bot selalu mengaku server tutup padahal pemain bisa login normal. Itu bug.

    ⚠️ TEMUAN TAMBAHAN (dari kode server Growtopia/GTOS): kunci `maint` TANPA
    `#` dipakai server untuk **DUA** hal, bukan cuma maintenance:

        maint|`4Oh no! `oWait 30 seconds before logging in again!

    Pesan "wait N seconds before logging in again" itu **rate-limit / cooldown**
    (terlalu sering minta login), bukan maintenance. Jadi kalau kunci ini
    muncul, artinya salah satu dari: (a) server benar-benar maintenance, atau
    (b) IP kita sedang dibatasi karena terlalu banyak percobaan login.
    Keduanya sama-sama berarti "jangan login dulu".
    """
    for k, v in data.items():
        if not v:
            continue
        kk = k.strip().lower()
        # hanya `maint` / `maintenance` TANPA `#` yang berarti aktif.
        # `beta_maint`/`beta2_maint`/`beta3_maint` khusus server beta — abaikan.
        if kk in ("maint", "maintenance"):
            return v
    return ""


def pesan_penolakan_login(data: dict[str, str]) -> str:
    """Terjemahkan kunci `maint` aktif menjadi penjelasan yang JUJUR.

    Kunci `maint` tanpa `#` bisa berarti maintenance ATAU rate-limit/cooldown
    ("wait N seconds before logging in again"). Fungsi ini membedakannya
    berdasarkan isi pesannya, supaya bot/CLI tidak salah bilang "maintenance".
    """
    pesan = ambil_pesan_maintenance(data)
    if not pesan:
        return ""
    low = pesan.lower()
    if "wait" in low and "second" in low:
        return (f"server membatasi login (rate-limit/cooldown): {pesan} — "
                "jangan coba login lagi sebelum waktunya habis.")
    return f"Growtopia sedang maintenance: {pesan}"


def sedang_maintenance(data: dict[str, str]) -> bool:
    """True bila Growtopia **benar-benar** sedang maintenance.

    Hanya true kalau `server_data.php` mengirim kunci `maint` tanpa `#`.
    Kunci `#maint` diabaikan (itu baris komentar, selalu ada).
    """
    return bool(ambil_pesan_maintenance(data))


def detik_tunggu(data: dict[str, str]) -> int:
    """Baca angka dari pesan server "Wait N seconds before logging in again".

    Server Growtopia memakai pesan ini saat membatasi login (rate-limit/
    cooldown) — mis. IP kita terlalu sering minta login. Mengembalikan N
    (detik) bila ditemukan, atau 0 bila tidak ada. Dipakai bot supaya ia
    benar-benar MENUNGGU sesuai perintah server, bukan menembak ulang tiap
    2 detik (yang membuat cooldown makin panjang / "ercon").
    """
    import re  # noqa: PLC0415

    pesan = ambil_pesan_maintenance(data)
    if not pesan:
        return 0
    # Buang kode warna Growtopia (`4, `o, `0, ...) supaya regex bersih.
    bersih = re.sub(r"`.", "", pesan)
    m = re.search(r"wait\s+(\d+)\s*second", bersih, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def fetch_server_data(protocol: int = 225, version: str = "5.58", timeout: int = 20) -> dict[str, str]:
    """Ambil daftar server game dari growtopia1/2.com (endpoint resmi).

    Hasilnya memuat `server`, `port`, `meta`, dan — bila Growtopia sedang
    maintenance — kunci `#maint` berisi pesannya. Pakai
    `sedang_maintenance(...)` untuk memeriksanya.
    """
    requests = _requests()
    last_err = ""
    for url in SERVER_DATA_URLS:
        try:
            r = requests.post(
                url,
                headers={"User-Agent": GAME_UA, "Content-Type": "application/x-www-form-urlencoded"},
                data=f"platform=0&protocol={protocol}&version={version}",
                timeout=timeout,
            )
            if r.status_code != 200:
                last_err = f"{url} -> HTTP {r.status_code}"
                continue
            out: dict[str, str] = {}
            for line in r.text.split("\n"):
                line = line.strip("\r")
                if "|" in line:
                    k, v = line.split("|", 1)
                    out[k.strip()] = v.strip()
            if out.get("server") and out.get("port"):
                out["_source"] = url
                return out
            last_err = f"{url} -> respons tanpa server/port: {r.text[:120]!r}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{url} -> {type(e).__name__}: {e}"
    raise RuntimeError(f"Gagal mengambil server_data. Terakhir: {last_err}")


# --------------------------------------------------------------------------- #
# Login GrowID (ltoken)
# --------------------------------------------------------------------------- #
def build_client_data(
    protocol: int = 225,
    version: str = "5.58",
    meta: str = "",
    rid: Optional[str] = None,
    mac: Optional[str] = None,
    username: str = "",
    password: str = "",
    platform: str = PLATFORM_ID_MOBILE,
    device_version: str = DEVICE_VERSION_MOBILE,
) -> str:
    """Bangun blob client_data `key|value\\n` seperti yang dikirim klien asli.

    PENTING: `platform` bawaan adalah `3,1,1` (klien ANDROID), bukan `0,1,1`
    (klien PC). Alasannya sama dengan `login_payload()`: akun hasil login
    Google/Apple terdaftar sebagai akun **mobile**, dan server menolaknya bila
    klien mengaku PC. Sebelumnya fungsi ini masih memakai `0,1,1` sementara
    `login_payload()` sudah memakai `3,1,1` — identitas yang tidak konsisten.

    `meta` sebaiknya diisi nilai dari `server_data.php` (`fetch_server_data()
    ["meta"]`), sama seperti yang dipakai klien asli.
    """
    from .hash import generate_klv, random_hex, random_mac  # noqa: PLC0415

    rid = rid or random_hex(32, uppercase=True)
    mac = mac or random_mac()
    hash_val = "123456789"
    # Urutan argumen mengikuti klien asli: generateKlv(gameVersion, hash, rid, protocol)
    klv = generate_klv(str(version), hash_val, rid, str(protocol))
    fields = [
        ("tankIDName", username),
        ("tankIDPass", password),
        ("requestedName", ""),
        ("f", "1"),
        ("protocol", str(protocol)),
        ("game_version", str(version)),
        ("fz", "21905432"),
        ("cbits", "0"),
        ("player_age", "20"),
        ("GDPR", "2"),
        ("FCMToken", ""),
        ("category", "_-5100"),
        ("totalPlaytime", "0"),
        ("klv", klv),
        ("hash2", "-716928004"),
        ("meta", meta),
        ("fhash", "-716928004"),
        ("rid", rid),
        ("platformID", platform),
        ("deviceVersion", device_version),
        ("country", "us"),
        ("hash", hash_val),
        ("mac", mac),
        ("wk", random_hex(32, uppercase=True)),
        ("zf", "-1623530258"),
        ("lmode", "1"),
    ]
    return "\n".join(f"{k}|{v}" for k, v in fields)


def growid_login(
    username: str,
    password: str,
    protocol: int = 225,
    version: str = "5.58",
    meta: str = "",
    timeout: int = 25,
) -> LoginResult:
    """Ambil `ltoken` dari login.growtopiagame.com.

    Strategi (berurutan, berhenti saat berhasil):
      1. POST client_data ke /player/login/dashboard?valKey=... -> ikuti redirect
         -> GET URL hasil redirect -> JSON {status, token}
      2. Sama, tapi kredensial dikirim sebagai form field (growId/password)
      3. POST langsung ke /player/growid/login/validate dengan _token + kredensial
    """
    requests = _requests()
    client_data = build_client_data(protocol, version, meta, username=username, password=password)
    tried: list[str] = []
    # Pesan asli dari server Growtopia (mis. "Please try login again.") —
    # disimpan supaya bisa ditampilkan ke pengguna, bukan dibuang.
    pesan_server: list[str] = []

    def _finish(resp_text: str, how: str) -> LoginResult:
        try:
            j = json.loads(resp_text)
        except ValueError:
            return LoginResult(False, "growid", message=f"Respons bukan JSON ({how})", raw=resp_text[:500])
        if j.get("status") == "success" and j.get("token"):
            return LoginResult(True, "growid", token=j["token"], message=j.get("message", ""),
                               raw=resp_text[:300], details={"how": how})
        msg = str(j.get("message") or j.get("status") or "gagal")
        pesan_server.append(msg)
        return LoginResult(False, "growid", message=msg, raw=resp_text[:300],
                           details={"how": how})

    s = requests.Session()
    s.headers.update({"User-Agent": GAME_UA})

    # -- strategi 1 & 2 ----------------------------------------------------- #
    for label, body in (
        ("client_data", client_data),
        ("form-fields", f"growId={username}&password={urllib.parse.quote(password, safe='')}"),
    ):
        try:
            p = s.post(
                f"{LOGIN_HOST}/player/login/dashboard?valKey={DASHBOARD_VALKEY}",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=timeout,
                allow_redirects=False,
            )
            tried.append(f"{label}: dashboard HTTP {p.status_code}")
            loc = p.headers.get("Location", "")
            if not loc:
                tried.append(f"{label}: tanpa Location, body={p.text[:120]!r}")
                continue
            g = s.get(loc, headers={"User-Agent": GAME_UA}, timeout=timeout)
            tried.append(f"{label}: GET link HTTP {g.status_code} len={len(g.text)}")
            res = _finish(g.text, f"dashboard/{label}")
            if res.ok:
                return res
        except Exception as e:  # noqa: BLE001
            tried.append(f"{label}: {type(e).__name__}: {e}")

    # -- strategi 3: _token langsung --------------------------------------- #
    for token_src, token_val in (
        ("base64(client_data)", base64.b64encode(client_data.encode()).decode()),
        ("segment-path", ""),
    ):
        if not token_val:
            continue
        try:
            r = s.post(
                f"{LOGIN_HOST}/player/growid/login/validate",
                data={"_token": token_val, "growId": username, "password": password, "type": "log"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": LOGIN_HOST,
                    "Referer": f"{LOGIN_HOST}/player/growid/login",
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=timeout,
            )
            tried.append(f"{token_src}: HTTP {r.status_code}")
            res = _finish(r.text, token_src)
            if res.ok:
                return res
        except Exception as e:  # noqa: BLE001
            tried.append(f"{token_src}: {type(e).__name__}: {e}")

    # Semua strategi gagal: tampilkan pesan ASLI dari server bila ada, supaya
    # pengguna tahu penyebabnya (sandi salah / perlu tunggu 30 detik / dsb).
    if pesan_server:
        unik: list[str] = []
        for m in pesan_server:
            if m not in unik:
                unik.append(m)
        pesan = "; ".join(unik)
        hint = ""
        low = pesan.lower()
        if "try again" in low or "wait" in low:
            hint = " (biasanya karena sandi salah atau permintaan terlalu sering — coba lagi 30 detik)"
        elif "verify" in low or "email" in low:
            hint = " (akun mungkin perlu verifikasi email di growtopiagame.com)"
        return LoginResult(
            False,
            "growid",
            message=f"Login GrowID ditolak server: {pesan}{hint}",
            details={"dicoba": tried},
        )

    return LoginResult(
        False,
        "growid",
        message=(
            "Login GrowID gagal di semua strategi. Kemungkinan alur login Growtopia "
            "berubah, atau jaringan memblokir. Alternatif yang lebih andal: pakai "
            "ltoken — `lucifer login --ltoken \"<TOKEN>\"` (lihat README: Login Google)."
        ),
        details={"dicoba": tried},
    )


def social_login(
    social_token: str,
    social: str = "google",
    protocol: int = 225,
    version: str = "5.58",
    meta: str = "",
    timeout: int = 25,
) -> LoginResult:
    """Tukar token sosial (Google/Apple/Ubisoft) menjadi `ltoken` Growtopia.

    Alur ini yang dipakai klien Growtopia 4.6+ (dan semua bot modern seperti
    SurferBot) untuk login lewat Google:

      1. Pemain login ke Google di sisi kita (browser/HP) -> dapat
         `id_token` (OpenID Connect) atau `serverAuthCode`.
      2. Token itu dikirim ke endpoint sosial Growtopia:
             POST /player/social/login?social_login=<google|apple|ubisoft>
         Server menukarnya dan membalas JSON berisi `token` (= ltoken).
      3. `ltoken` itulah yang dipakai di paket login ENet (lihat
         Account.login_payload) — bukan email/password.

    Catatan jujur: Growtopia TIDAK menyediakan OAuth client_id publik untuk
    pihak ketiga, dan Google memblokir login otomatis (anti-bot). Jadi langkah
    1 harus dilakukan MANUSIA sekali di browser; setelah itu `ltoken` bisa
    dipakai ulang dan disegarkan lewat tokenUrl (tanpa login Google lagi).
    """
    requests = _requests()
    client_data = build_client_data(protocol, version, meta)
    tried: list[str] = []
    s = requests.Session()
    s.headers.update({"User-Agent": GAME_UA})

    url = f"{LOGIN_HOST}/player/social/login"
    # Beberapa bentuk body dicoba karena format bisa berubah antar versi klien.
    bodies = [
        {"social_login": social, "token": social_token, "id_token": social_token},
        {"social_login": social, "social_token": social_token},
        f"social_login={social}&token={urllib.parse.quote(social_token, safe='')}",
    ]
    for i, body in enumerate(bodies, 1):
        try:
            r = s.post(
                url,
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=timeout,
                allow_redirects=False,
            )
            tried.append(f"body#{i}: HTTP {r.status_code} len={len(r.text)}")
            loc = r.headers.get("Location", "")
            if loc:
                g = s.get(loc, timeout=timeout)
                tried.append(f"body#{i}: GET redirect HTTP {g.status_code}")
                r = g
            try:
                j = json.loads(r.text)
            except ValueError:
                tried.append(f"body#{i}: bukan JSON ({r.text[:100]!r})")
                continue
            if j.get("status") == "success" and j.get("token"):
                return LoginResult(
                    True, social, token=j["token"],
                    message=j.get("message", "login sosial berhasil"),
                    raw=r.text[:300], details={"how": f"social/{social}"},
                )
            tried.append(f"body#{i}: status={j.get('status')} msg={j.get('message')}")
        except Exception as e:  # noqa: BLE001
            tried.append(f"body#{i}: {type(e).__name__}: {e}")

    return LoginResult(
        False, social,
        message=(f"Login {social} gagal — token sosial tidak diterima server. "
                 "Pastikan token belum kedaluwarsa dan berasal dari login Google "
                 "yang sah (lihat README bagian 'Login Google')."),
        details={"dicoba": tried},
    )


def client_data_minimal(protocol: int = 225, version: str = "5.58",
                        meta: str = "") -> str:
    """Blok `client_data` minimal (base64) untuk /player/growid/checktoken.

    Server Growtopia MENOLAK permintaan tanpa `clientData` — dibuktikan
    lewat uji langsung: tanpa clientData -> {"status":"failed"}.

    `meta` diisi nilai dari `server_data.php` bila ada (klien asli
    mengirimkannya). `platformID` memakai identitas **Android** (`3,1,1`)
    supaya konsisten dengan `login_payload()` dan `build_client_data()`.
    """
    from .hash import generate_klv, random_hex, random_mac  # noqa: PLC0415

    rid = random_hex(32, uppercase=True)
    klv = generate_klv(str(version), "123456789", rid, str(protocol))
    blok = (
        f"tankIDName|\ntankIDPass|\nrequestedName|\nf|1\n"
        f"protocol|{protocol}\ngame_version|{version}\nfz|21905432\n"
        f"cbits|0\nplayer_age|20\nGDPR|2\nFCMToken|\n"
        f"category|_-5100\ntotalPlaytime|0\nklv|{klv}\n"
        f"hash2|-716928004\nmeta|{meta}\nfhash|-716928004\nrid|{rid}\n"
        f"platformID|{PLATFORM_ID_MOBILE}\ndeviceVersion|{DEVICE_VERSION_MOBILE}\n"
        f"country|us\n"
        f"hash|123456789\nmac|{random_mac()}\n"
    )
    return base64.b64encode(blok.encode()).decode()


CHECKTOKEN_VALKEY: str = "40db4045f2d8c572efe8c4a060605726"

def check_token(ltoken: str, timeout: int = 20,
                client_data: str = "", meta: str = "") -> LoginResult:
    """Validasi/segar-ulang `ltoken` lewat /player/growid/checktoken (metode Nxrth)."""
    requests = _requests()
    s = requests.Session()
    s.headers.update({"User-Agent": "UbiServices_SDK_2022.Release.9_PC64_ansi_static"})
    cd = client_data or client_data_minimal(meta=meta)
    try:
        r = s.post(
            f"{LOGIN_HOST}/player/growid/checktoken?valKey={CHECKTOKEN_VALKEY}",
            data={"refreshToken": ltoken, "clientData": cd},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
            allow_redirects=True,
        )
        try:
            j = json.loads(r.text)
        except ValueError:
            return LoginResult(False, "ltoken", message=f"bukan JSON (HTTP {r.status_code})",
                               raw=r.text[:200])
        if j.get("status") == "success" and j.get("token"):
            return LoginResult(True, "ltoken", token=j["token"],
                               message=j.get("message", "token valid"),
                               details={"accountType": j.get("accountType", "")})
        return LoginResult(False, "ltoken", message=j.get("message", "token tidak valid"),
                           raw=r.text[:200])
    except Exception as e:  # noqa: BLE001
        return LoginResult(False, "ltoken", message=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Akun
# --------------------------------------------------------------------------- #
@dataclass
class Account:
    """Kredensial + preferensi satu akun Growtopia.

    Sandi TIDAK pernah ditulis ke log. Ambil dari env bila kosong:
        LUCIFER_USER / LUCIFER_PASS
    """

    username: str = ""
    password: str = ""
    method: str = "growid"  # growid | legacy | google | apple | ubiconnect | token
    protocol: int = 225
    version: str = "5.58"
    ltoken: str = ""
    rid: str = ""
    mac: str = ""
    proxy: Optional[str] = None
    label: str = ""
    # -- login sosial (Google / Apple / Ubisoft) ------------------------- #
    mail: str = ""                 # email akun sosial
    social_token: str = ""         # id_token / serverAuthCode dari Google/Apple
    secret_key: str = ""           # kunci 2FA
    token_url: str = ""            # URL penyegar token (dari clientData / dashboard)
    cookies: str = ""              # cookie sesi (khusus Apple)
    _token: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.username:
            self.username = os.environ.get("LUCIFER_USER", "")
        if not self.password:
            self.password = os.environ.get("LUCIFER_PASS", "")
        if not self.social_token:
            self.social_token = os.environ.get("LUCIFER_SOCIAL_TOKEN", "")
        if not self.label:
            self.label = self.username or self.mail or "bot"
        # PENTING: `ltoken` (dari accounts.json / dashboard) harus masuk ke
        # `_token`, kalau tidak `login_payload()` mengirim `ltoken|` KOSONG dan
        # server selalu menjawab "Fail to login. Login token is invalid."
        # Ini jalur yang dipakai akun hasil "Ambil Token dari HP".
        if not self._token and self.ltoken:
            self._token = self.ltoken

    # -- keamanan ---------------------------------------------------------- #
    def __repr__(self) -> str:
        pw = "***" if self.password else ""
        return f"Account(username={self.username!r}, password={pw!r}, method={self.method!r})"

    def redacted(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "username": self.username,
            "method": self.method,
            "protocol": self.protocol,
            "version": self.version,
            "password": "***" if self.password else "",
            "mail": self.mail,
            "social_token": ("***" if self.social_token else ""),
            "ltoken": (self._token[:12] + "...") if self._token else "",
            "proxy": self.proxy or "",
        }

    # -- login ------------------------------------------------------------- #
    def login(self, meta: str = "", timeout: int = 25) -> LoginResult:
        """Siapkan kredensial untuk dikirim ke server game.

        Return LoginResult. `.token` berisi nilai yang harus dikirim sebagai
        `ltoken` di paket GenericText.
        """
        if self.ltoken:
            self._token = self.ltoken
            return LoginResult(True, "ltoken-siap", token=self.ltoken, message="ltoken sudah tersedia")

        if self.method == "legacy":
            # Server game menerima tankIDName/tankIDPass langsung.
            self._token = ""
            return LoginResult(True, "legacy", token="", message="pakai tankIDName/tankIDPass")

        # -- Google / Apple / Ubisoft: tukar token sosial jadi ltoken -------- #
        if self.method in ("google", "apple", "ubiconnect", "social"):
            social = "google" if self.method in ("google", "social") else self.method
            if not self.social_token:
                return LoginResult(
                    False, self.method,
                    message=(f"method='{self.method}' butuh 'social_token' (id_token Google). "
                             "Lihat README bagian 'Login Google' untuk cara mengambilnya."),
                )
            res = social_login(self.social_token, social, self.protocol, self.version, meta, timeout)
            if res.ok:
                self._token = res.token
            return res

        if self.method == "token":
            # ltoken mentah yang ditempel langsung (paling praktis & andal).
            if not self.ltoken:
                return LoginResult(False, "token", message="method='token' butuh field 'ltoken'")
            self._token = self.ltoken
            return LoginResult(True, "token", token=self.ltoken, message="ltoken dari konfigurasi")

        if not self.username or not self.password:
            return LoginResult(False, self.method, message="username/password kosong")

        res = growid_login(self.username, self.password, self.protocol, self.version, meta, timeout)
        if res.ok:
            self._token = res.token
        return res

    # -- paket ------------------------------------------------------------------ #
    def login_payload(self) -> bytes:
        """Payload GenericText untuk ServerHello.

        PENTING (hasil uji langsung ke server GT, 2026-09-29):

        `platformID` menentukan jenis klien:
            platformID|0,1,1  -> dianggap klien PC
            platformID|3,1,1  -> dianggap klien ANDROID/mobile  ← DIPAKAI

        Akun Google/Apple terdaftar sebagai akun **mobile**. Kalau bot mengaku
        klien PC (`0,1,1`), server membalas:
            eventName|102_PLAYER.AUTHENTICATION
            Authentication_error|28
            msg|UPDATE REQUIRED! ... GrowtopiaInstaller.exe
        (yaitu: "akun mobile tidak boleh masuk lewat klien PC").

        Dengan `platformID|3,1,1` server justru membalas `OnSendToServer` —
        artinya login DITERIMA dan bot dipersilakan pindah ke server game.
        """
        if self.method == "legacy" and not self._token:
            body = (
                f"tankIDName|{self.username}\n"
                f"tankIDPass|{self.password}\n"
                f"protocol|{self.protocol}\n"
                f"game_version|{self.version}\n"
                f"{PLATFORM_MOBILE}\n"
                f"deviceVersion|29\n"
                "adc|1\n"
            )
        else:
            body = (
                f"protocol|{self.protocol}\n"
                f"ltoken|{self._token}\n"
                f"{PLATFORM_MOBILE}\n"
                f"game_version|{self.version}\n"
                f"deviceVersion|29\n"
                "adc|1\n"
            )
        return body.encode("utf-8")


def load_accounts(path: str | Path) -> list[Account]:
    """Muat daftar akun dari JSON.

    Format:
        [
          {"label":"main", "username":"Nama", "password":"...", "method":"growid"},
          {"label":"alt",  "username":"Nama2", "ltoken":"...", "method":"token"}
        ]
    Nilai password boleh dikosongkan -> ambil dari env LUCIFER_PASS.
    """
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    if isinstance(raw, dict):
        raw = raw.get("accounts", [])
    accounts: list[Account] = []
    for entry in raw:
        entry = dict(entry)
        entry.setdefault("label", entry.get("username", "bot"))
        accounts.append(Account(**entry))
    return accounts


# Kunci yang boleh disimpan ke disk. Field lain (mis. _token) tidak ditulis.
_SIMPAN_KEYS = (
    "label", "username", "password", "method", "protocol", "version",
    "ltoken", "rid", "mac", "proxy", "mail", "social_token",
    "secret_key", "token_url", "cookies",
)


def account_to_dict(acc: Account) -> dict[str, Any]:
    """Ubah Account jadi dict siap disimpan (hanya field yang relevan)."""
    d: dict[str, Any] = {}
    for k in _SIMPAN_KEYS:
        v = getattr(acc, k, "")
        if v not in ("", None, 0) or k in ("label", "username", "method"):
            d[k] = v
    # Jangan simpan sandi kalau akun memakai token (tidak diperlukan)
    if d.get("method") in ("token",) and not d.get("ltoken"):
        d.pop("password", None)
    return d


def save_accounts(path: str | Path, accounts: list[Account], mode: int = 0o600) -> Path:
    """Tulis daftar akun ke JSON dengan izin ketat (bawaan 600).

    File ini berisi rahasia (sandi/ltoken), jadi izinnya dibatasi ke pemilik.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = [account_to_dict(a) for a in accounts]
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        p.chmod(mode)
    except OSError:  # mis. filesystem tanpa izin POSIX
        log.debug("tidak bisa chmod %s", p)
    return p


def upsert_account(path: str | Path, acc: Account) -> tuple[Path, bool]:
    """Tambah/ganti akun berdasarkan label. Return (path, apakah_baru)."""
    akun = load_accounts(path)
    for i, a in enumerate(akun):
        if a.label == acc.label:
            akun[i] = acc
            save_accounts(path, akun)
            return Path(path), False
    akun.append(acc)
    save_accounts(path, akun)
    return Path(path), True


def remove_account(path: str | Path, label: str) -> bool:
    """Hapus akun berdasarkan label. Return True kalau ada yang dihapus."""
    akun = load_accounts(path)
    sisa = [a for a in akun if a.label != label]
    if len(sisa) == len(akun):
        return False
    save_accounts(path, sisa)
    return True
