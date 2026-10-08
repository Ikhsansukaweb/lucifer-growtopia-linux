"""
lucifer.google — Login Growtopia lewat Google (OAuth web flow).

CARA KERJA (sama seperti Growlauncher)
--------------------------------------
Growtopia punya **OAuth client bertipe "Web"** yang client_id-nya tertanam di
`base.apk` resmi:

    389994132396-4s6ol46f60831v5blfpci7lnmsdnh8br.apps.googleusercontent.com

Karena bertipe Web, Google MENGIZINKAN flow redirect (tidak seperti client
Android yang menolak `redirect_uri`). Jadi alurnya:

    1. buka  accounts.google.com/o/oauth2/v2/auth
             ?client_id=<client_id GT>
             &redirect_uri=https://login.growtopiagame.com/google/callback
             &response_type=code
             &scope=openid profile email
             &prompt=select_account
             &state=<dibuat server>
    2. pengguna pilih akun Google & setujui (di browser, MANUAL)
    3. Google redirect ke  login.growtopiagame.com/google/callback?code=...
    4. server GT menukar `code` -> 302 ke /player/link/dashboard/validate/<payload>
    5. GET payload itu -> JSON berisi `token` (= ltoken)

KOREKSI PENTING (diuji ulang 2026-09-30)
-----------------------------------------
Versi awal modul ini mengklaim `state` **tidak diperiksa** server, sehingga
nilai acak apa pun cukup. **Itu SALAH.** Buktinya:

    GET /player/login/dashboard            -> 302 ke
        /player/link/dashboard/validate/<enc>/<enc>
        -> JSON {"status":"failed","message":"Please try login again."}
    POST /player/login/dashboard (_token=...)  -> sama, "Please try login again."

Artinya `state` (dan sesi `growtopia_game_session`/`XSRF-TOKEN`) HARUS berasal
dari server GT. `state` karangan kita memang membuat callback tidak lagi 500,
tapi server tetap menolak di tahap akhir dengan:

    {"status":"failed","message":"Token is invalid.", ...}   # code tak sah/terpakai
    {"status":"failed","message":"Please try login again."}  # state/sesi tak dikenal

Jadi login Google web flow lewat jalur mandiri ini **belum tentu sah** — server
GT memvalidasi `state` terhadap sesi yang ia terbitkan sendiri. Yang benar-benar
dibutuhkan adalah memulai alur dari halaman resmi (tombol "Login with Google")
supaya server menerbitkan `state` + sesi yang cocok. Jalur `--code` (tempel URL
callback hasil browser) tetap berguna, tapi hanya bila URL itu berasal dari
alur resmi yang dibuka di browser yang sama.

Yang TIDAK dilakukan modul ini: meminta email/sandi Google. Pengguna memilih
akunnya sendiri di browser. Jadi tidak ada sandi Google yang disimpan, dan
tidak ada login otomatis yang dilawan Google (anti-bot).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_REDIRECT_URI",
    "URL_CALLBACK",
    "HasilGoogle",
    "url_login_google",
    "tukar_code_jadi_ltoken",
    "tangkap_code_dari_browser",
    "login_google",
]

# client_id OAuth tipe "Web" milik Growtopia (ditemukan di base.apk resmi,
# dipakai sebagai `default_web_client_id`). Ini BUKAN rahasia: client_id OAuth
# memang publik dan ikut terkirim di setiap URL login.
GOOGLE_CLIENT_ID = (
    "389994132396-4s6ol46f60831v5blfpci7lnmsdnh8br.apps.googleusercontent.com"
)
GOOGLE_REDIRECT_URI = "https://login.growtopiagame.com/google/callback"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
URL_CALLBACK = GOOGLE_REDIRECT_URI

LOGIN_HOST = "https://login.growtopiagame.com"


@dataclass
class HasilGoogle:
    """Hasil login Google."""

    ok: bool = False
    token: str = ""
    message: str = ""
    code: str = ""
    url: str = ""
    raw: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return self.message or ("berhasil" if self.ok else "gagal")


def buat_state(panjang: int = 24) -> str:
    """Buat nilai `state` acak untuk OAuth.

    Server Growtopia **mewajibkan** callback membawa parameter `state`:
    tanpa itu balasannya HTTP 500 (halaman 404). Nilainya sendiri **tidak
    diperiksa** server (sudah diuji dengan nilai asal-asalan → tetap 302),
    jadi nilai acak sudah cukup.
    """
    import secrets  # noqa: PLC0415

    return secrets.token_urlsafe(panjang)


def url_login_google(state: str = "", prompt: str = "select_account",
                     login_hint: str = "") -> str:
    """Bangun URL login Google yang dipakai Growtopia/Growlauncher.

    Buka URL ini di browser, pilih akun Google, dan setelah disetujui browser
    akan mendarat di `login.growtopiagame.com/google/callback?code=...`.

    `state` selalu ikut dikirim (walau kosong → dibuat acak), karena Google
    hanya mengembalikan `state` yang kita kirim, dan server GT menolak
    callback yang tidak membawa `state`.
    """
    q = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid profile email",
        "prompt": prompt,
        "state": state or buat_state(),
    }
    if login_hint:
        q["login_hint"] = login_hint
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(q)


# --------------------------------------------------------------------------- #
# Tukar `code` -> ltoken
# --------------------------------------------------------------------------- #
def tukar_code_jadi_ltoken(code: str, state: str = "", timeout: int = 30,
                           user_agent: str = "") -> HasilGoogle:
    """Tukar authorization `code` Google menjadi `ltoken` Growtopia.

    Alurnya: GET /google/callback?code=.. -> 302 -> GET /player/link/
    dashboard/validate/<payload> -> JSON {"token": "<ltoken>"}.

    Redirect WAJIB diikuti dengan GET (kalau di-POST, server balas 405).
    """
    try:
        import requests  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        return HasilGoogle(False, message=f"butuh paket requests: {e}")

    if not code:
        return HasilGoogle(False, message="code kosong")

    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    )
    s = requests.Session()
    s.headers.update({
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })

    params = {"code": code}
    if state:
        params["state"] = state

    try:
        r = s.get(URL_CALLBACK, params=params, timeout=timeout,
                  allow_redirects=False)
    except Exception as e:  # noqa: BLE001
        return HasilGoogle(False, message=f"gagal hubungi server: {e}",
                           code=code)

    loc = r.headers.get("Location", "")
    if r.status_code in (301, 302, 303, 307, 308) and loc:
        if not loc.startswith("http"):
            loc = LOGIN_HOST + loc
        try:
            g = s.get(loc, timeout=timeout)
            r = g
        except Exception as e:  # noqa: BLE001
            return HasilGoogle(False, message=f"gagal ikuti redirect: {e}",
                               code=code, url=loc)
    elif r.status_code == 500 and not loc:
        # Terjadi kalau `state` tidak ikut dikirim. Server GT membalas 500
        # (halaman 404) untuk callback tanpa `state` — sudah diuji:
        #   ?code=X          -> 500
        #   ?code=X&state=Y  -> 302 (benar)
        return HasilGoogle(
            False, code=code, url=URL_CALLBACK,
            message=("server menolak (HTTP 500). Biasanya karena parameter "
                     "`state` tidak ikut dikirim — server Growtopia "
                     "mewajibkannya. Coba lagi dengan `--google-browser` "
                     "(state dibuat otomatis)."),
            raw=r.text[:300],
        )
    elif r.status_code >= 400:
        return HasilGoogle(
            False, code=code, url=loc,
            message=(f"server menolak (HTTP {r.status_code}). `code` mungkin "
                     f"sudah kedaluwarsa, sudah dipakai, atau berasal dari "
                     f"akun/client lain — coba login ulang."),
            raw=r.text[:300],
        )

    teks = r.text.strip()
    try:
        j = json.loads(teks)
    except ValueError:
        return HasilGoogle(False, code=code,
                           message=f"balasan bukan JSON: {teks[:120]!r}",
                           raw=teks[:300], url=loc)

    token = j.get("token") or ""
    if j.get("status") == "success" and token:
        return HasilGoogle(
            True, token=token, code=code, url=loc,
            message=j.get("message") or "login Google berhasil",
            raw=teks[:300],
            details={"accountType": j.get("accountType", ""),
                     "accountAge": j.get("accountAge", "")},
        )
    return HasilGoogle(
        False, code=code, url=loc,
        message=j.get("message") or "server tidak memberi token",
        raw=teks[:300], details=dict(j),
    )


# --------------------------------------------------------------------------- #
# Tangkap `code` dari browser (CDP / Chrome DevTools Protocol)
# --------------------------------------------------------------------------- #
def _bersihkan_lock_basi(udd: str) -> bool:
    """Hapus `SingletonLock` Chrome yang BASI (pemiliknya sudah mati).

    Chrome menolak start kalau di `user-data-dir` ada `SingletonLock` milik
    proses yang sudah tidak ada — gejalanya "DevTools tidak menjawab" walau
    Chrome sama sekali tidak jalan. Terjadi setelah Chrome di-kill/crash.

    Lock ini symlink bernama `<hostname>-<pid>`; kita hanya menghapus kalau
    PID-nya benar-benar sudah mati, jadi Chrome yang sedang jalan AMAN.
    """
    lock = os.path.join(udd, "SingletonLock")
    if not os.path.islink(lock):
        return False
    try:
        target = os.readlink(lock)
        pid = int(str(target).rsplit("-", 1)[-1])
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)          # ada -> tidak apa-apa, lock sah
        return False
    except ProcessLookupError:
        pass                      # pemilik sudah mati -> lock basi
    except PermissionError:
        return False              # proses milik user lain -> jangan sentuh
    hapus = False
    for nama in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = os.path.join(udd, nama)
        try:
            if os.path.islink(p) or os.path.exists(p):
                os.remove(p)
                hapus = True
        except OSError:
            pass
    return hapus


def _cari_chrome() -> str:
    for nama in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "brave-browser", "microsoft-edge"):
        p = shutil.which(nama)
        if p:
            return p
    for p in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(p):
            return p
    return ""


def _port_bebas() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tunggu_devtools(port: int, batas: float = 25.0) -> bool:
    akhir = time.time() + batas
    while time.time() < akhir:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


def _target_halaman(port: int) -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/list", timeout=5
        ) as r:
            return [t for t in json.loads(r.read().decode())
                    if t.get("type") == "page"]
    except Exception:  # noqa: BLE001
        return []


def _pilih_tab(pages: list[dict[str, Any]],
               ingin: str = "") -> Optional[dict[str, Any]]:
    """Pilih tab yang paling mungkin berisi alur login.

    Chrome kadang membuka beberapa tab (tab lama yang di-restore, `about:blank`,
    `chrome://`, `background_page` ekstensi). Kalau `ingin` diberi (URL yang kita
    buka / host login), tab yang URL-nya cocok diutamakan — supaya CDP tidak
    menempel ke tab lama dan melewatkan `code`.
    """
    if not pages:
        return None
    if ingin:
        inti = ingin.split("?")[0].lower()
        for t in pages:
            u = (t.get("url") or "").lower()
            if u and u.split("?")[0] == inti:
                return t
    # utamakan tab alur login (Google / Growtopia) — walau bukan tab pertama
    for t in pages:
        u = (t.get("url") or "").lower()
        if "accounts.google.com" in u or "growtopiagame.com" in u:
            return t
    for t in pages:
        u = (t.get("url") or "").lower()
        if u and not u.startswith(("about:", "chrome:", "devtools:")):
            return t
    return pages[0]


def _profil_chrome() -> str:
    """Folder profil Chrome khusus Lucifer (persisten antar-run).

    Dipakai supaya sesi Google tersimpan: login berikutnya tinggal klik satu
    akun, tidak perlu mengetik ulang. Profil ini terpisah dari Chrome biasa
    milikmu, jadi tidak mengganggu bookmark/riwayatmu.
    """
    dasar = os.environ.get("LUCIFER_HOME") or os.path.join(
        os.path.expanduser("~"), ".lucifer")
    p = os.path.join(dasar, "chrome-profil")
    os.makedirs(p, exist_ok=True)
    return p


POLA_VALIDATE = "/player/link/dashboard/validate/"


def _token_dari_isi(teks: str) -> tuple[str, str]:
    """Ambil `token` dari isi halaman `/player/link/dashboard/validate/`.

    Halaman itu mengembalikan JSON polos, mis:
        {"status":"success","message":"Account Validated.","token":"<ltoken>"}
    atau saat gagal:
        {"status":"failed","message":"Token is invalid.","token":""}

    Kembalikan `(token, pesan)`. Token kosong bila gagal.
    """
    if not teks:
        return "", ""
    t = teks.strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return "", ""
    try:
        d = json.loads(t[i:j + 1])
    except ValueError:
        return "", ""
    if not isinstance(d, dict):
        return "", ""
    pesan = str(d.get("message") or "")
    token = d.get("token") or ""
    if token and str(d.get("status") or "").lower() == "success":
        return str(token), pesan
    return "", pesan


def _eval_cdp(ws, expr: str, id_pesan: int, timeout: float = 6.0) -> str:
    """Jalankan JS di halaman lewat CDP dan kembalikan nilainya."""
    try:
        ws.send(json.dumps({
            "id": id_pesan, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True},
        }))
    except Exception:  # noqa: BLE001
        return ""
    akhir = time.time() + timeout
    while time.time() < akhir:
        try:
            ws.settimeout(1.0)
            d = json.loads(ws.recv())
        except Exception:  # noqa: BLE001
            continue
        if d.get("id") == id_pesan:
            r = (d.get("result") or {}).get("result") or {}
            return str(r.get("value") or "")
    return ""


def tangkap_code_dari_browser(url: str, batas: int = 300,
                              tampilkan: bool = True,
                              profil: str = "") -> HasilGoogle:
    """Buka `url` di Chrome, lalu tunggu sampai muncul `?code=` di callback.

    Pakai Chrome DevTools Protocol (tanpa Selenium/Playwright): Chrome
    dijalankan dengan `--remote-debugging-port`, lalu kita sambung ke WebSocket
    halaman dan memantau navigasi. Begitu browser mendarat di
    `login.growtopiagame.com/google/callback?code=...`, code-nya diambil.

    Pengguna tetap memilih akun Google & menyetujui sendiri di jendela browser
    — modul ini tidak menyentuh sandi Google.
    """
    try:
        import websocket  # noqa: PLC0415  (websocket-client)
    except ImportError:
        return HasilGoogle(
            False,
            message=("butuh paket `websocket-client`. Install:\n"
                     "    .venv/bin/pip install websocket-client"),
        )

    chrome = _cari_chrome()
    if not chrome:
        return HasilGoogle(
            False,
            message=("Chrome/Chromium tidak ditemukan. Buka URL berikut "
                     "manual di browser apa pun, lalu tempel hasilnya:\n  " + url),
        )

    port = _port_bebas()
    udd = profil or _profil_chrome()
    # PENTING: Chrome dibuka di `about:blank` DULU, bukan langsung ke `url`.
    #
    # URL callback `?code=...` hanya SEKILAS — server GT langsung 302 ke
    # `/player/link/dashboard/validate/...`. Kalau Chrome dibuka langsung ke
    # URL login, CDP baru tersambung ~1-2 detik kemudian dan peristiwa
    # navigasi `code` sudah lewat (gejala: kadang berhasil, kadang "waktu
    # habis"). Jadi: buka tab kosong -> pasang pemantau -> baru `Page.navigate`.
    arg = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={udd}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,OptimizationHints",
        "about:blank",
    ]
    if not tampilkan:
        arg.insert(1, "--headless=new")

    proc = None
    try:
        # Lock basi dari run sebelumnya membuat Chrome menolak start
        # ("DevTools tidak menjawab"). Bersihkan dulu, lalu coba lagi.
        _bersihkan_lock_basi(udd)
        proc = subprocess.Popen(arg, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if not _tunggu_devtools(port):
            # sekali lagi: bersihkan lock, matikan sisa, ulangi
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            bersih = _bersihkan_lock_basi(udd)
            if bersih:
                proc = subprocess.Popen(arg, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        if not _tunggu_devtools(port):
            ada_layar = bool(os.environ.get("DISPLAY")
                             or os.environ.get("WAYLAND_DISPLAY"))
            if not ada_layar and tampilkan:
                return HasilGoogle(
                    False,
                    message=("Chrome tidak bisa dibuka karena tidak ada layar "
                             "(DISPLAY/WAYLAND_DISPLAY kosong — mis. lewat "
                             "SSH tanpa -X). Jalankan perintah ini di terminal "
                             "desktop, ATAU buka URL di atas manual lalu pakai "
                             "`--code`."),
                    url=url)
            return HasilGoogle(
                False,
                message=("Chrome gagal start (DevTools tidak menjawab). "
                         "Coba tutup Chrome lain, atau pakai jalur manual: "
                         "buka URL di atas lalu `--code`."),
                url=url)

        # tunggu tab halaman muncul
        target = None
        for _ in range(40):
            target = _pilih_tab(_target_halaman(port), ingin=url)
            if target:
                break
            time.sleep(0.4)
        if not target:
            return HasilGoogle(False, message="tidak ada tab browser terbuka.")

        ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=batas + 10,
            suppress_origin=True)
        try:
            for i, cmd in enumerate(("Page.enable", "Network.enable")):
                ws.send(json.dumps({"id": i + 1, "method": cmd}))
            # Baru SEKARANG navigasi ke halaman login — pemantau sudah aktif,
            # jadi peristiwa `code` (yang hanya sekilas) pasti tertangkap.
            ws.send(json.dumps({"id": 3, "method": "Page.navigate",
                                "params": {"url": url}}))
            # pantau peristiwa navigasi & request
            #
            # URUTAN PRIORITAS (penting):
            #   1. halaman `/player/link/dashboard/validate/...` -> JSON `token`
            #      Ini hasil AKHIR yang pasti. `code` OAuth hanya sekali pakai
            #      dan Chrome-lah yang memakainya saat memuat callback, jadi
            #      token dari halaman inilah yang benar.
            #   2. `?code=` di URL callback -> hanya CADANGAN (dipakai kalau
            #      halaman token tidak pernah muncul).
            akhir = time.time() + batas
            ws.settimeout(2.0)
            id_eval = 900
            kode_cadangan = ""
            cek_isi_terakhir = 0.0

            def baca_token(u: str) -> Optional[HasilGoogle]:
                """Baca token dari halaman validate; None bila belum siap."""
                isi = _eval_cdp(
                    ws, "document.body?document.body.innerText:''", id_eval)
                tok, pesan = _token_dari_isi(isi)
                if tok:
                    return HasilGoogle(True, token=tok, url=u,
                                       message=pesan or "token didapat",
                                       details={"cara": "baca_halaman"})
                if pesan:
                    # halaman sudah final tapi server menolak
                    return HasilGoogle(False, url=u,
                                       message=f"server menolak: {pesan}")
                return None

            while time.time() < akhir:
                halaman = [pg.get("url", "") for pg in _target_halaman(port)]
                for u in halaman:
                    if POLA_VALIDATE in u:
                        r = baca_token(u)
                        id_eval += 1
                        if r is not None:
                            return r
                    elif "code=" in u and "google/callback" in u:
                        cand = _dari_url(u)
                        if cand.ok and not kode_cadangan:
                            kode_cadangan = cand.code
                # peristiwa CDP
                try:
                    pesan = ws.recv()
                except Exception:  # noqa: BLE001  (timeout -> ulangi)
                    continue
                try:
                    d = json.loads(pesan)
                except ValueError:
                    continue
                u = ""
                m = d.get("method", "")
                if m == "Network.requestWillBeSent":
                    u = (d.get("params", {}).get("request", {}) or {}).get("url", "")
                elif m == "Page.frameNavigated":
                    u = (d.get("params", {}).get("frame", {}) or {}).get("url", "")
                elif m == "Page.navigatedWithinDocument":
                    u = d.get("params", {}).get("url", "")
                if u and POLA_VALIDATE in u:
                    time.sleep(0.7)  # beri waktu server menulis JSON
                    r = baca_token(u)
                    id_eval += 1
                    if r is not None:
                        return r
                elif u and "code=" in u and "growtopiagame.com" in u:
                    cand = _dari_url(u)
                    if cand.ok and not kode_cadangan:
                        kode_cadangan = cand.code
                # pengaman: sesekali cek isi halaman walau tak ada peristiwa
                if time.time() - cek_isi_terakhir > 2.0:
                    cek_isi_terakhir = time.time()
                    for u in _target_halaman(port):
                        if POLA_VALIDATE in (u.get("url") or ""):
                            r = baca_token(u["url"])
                            id_eval += 1
                            if r is not None:
                                return r
                            break

            if kode_cadangan:
                return HasilGoogle(True, code=kode_cadangan,
                                   message="code tertangkap (cadangan)")
            return HasilGoogle(
                False, message=f"waktu habis ({batas}s) — hasil login "
                               "tidak muncul (belum menyetujui di browser?)")
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        return HasilGoogle(False, message=f"gagal jalankan browser: {e}")
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        # Rapikan lock supaya run berikutnya tidak tersandung "lock basi".
        # Profilnya sendiri TETAP disimpan (biar tidak perlu pilih akun ulang).
        _bersihkan_lock_basi(udd)


def _dari_url(u: str) -> HasilGoogle:
    """Ambil `code` (dan `state`) dari URL callback."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    code = (q.get("code") or [""])[0]
    state = (q.get("state") or [""])[0]
    if not code:
        err = (q.get("error") or [""])[0]
        return HasilGoogle(False, url=u,
                           message=f"tidak ada `code` di URL (error={err!r})")
    return HasilGoogle(True, code=code, url=u, details={"state": state},
                       message="code tertangkap")


# --------------------------------------------------------------------------- #
# Alur lengkap
# --------------------------------------------------------------------------- #
def login_google(batas: int = 300, tampilkan: bool = True, state: str = "",
                 code: str = "", verifikasi: bool = False) -> HasilGoogle:
    """Login Google end-to-end: buka browser -> pilih akun -> dapat `ltoken`.

    Kalau `code` sudah ada (mis. ditangkap manual dari URL), langkah browser
    dilewati dan langsung ditukar.
    """
    if not code:
        url = url_login_google(state=state)
        ambil = tangkap_code_dari_browser(url, batas=batas, tampilkan=tampilkan)
        if not ambil.ok:
            return HasilGoogle(False, message=ambil.message, url=url)
        if ambil.token:
            # Browser sudah mendarat di halaman hasil dan server GT sudah
            # menukar `code` -> token. `code` OAuth hanya sekali pakai, jadi
            # JANGAN ditukar lagi (dulu inilah penyebab "Token is invalid").
            tukar = ambil
        else:
            code = ambil.code
            state = (ambil.details or {}).get("state", "") or state
            tukar = tukar_code_jadi_ltoken(code, state=state)
    else:
        tukar = tukar_code_jadi_ltoken(code, state=state)
    if not tukar.ok:
        return tukar

    if verifikasi:
        try:
            from .account import check_token  # noqa: PLC0415

            cek = check_token(tukar.token)
            tukar.details["verify"] = cek.message
            tukar.details["verify_ok"] = cek.ok
        except Exception as e:  # noqa: BLE001
            tukar.details["verify"] = f"gagal cek: {e}"
    return tukar
