#!/usr/bin/env python3
"""
lucifer/ltoken.py — Ambil `ltoken` Growtopia dari HP Android (tanpa root).

TIGA JALUR (dari yang paling pasti):

  A. LOG APP (paling praktis)
     APK Growtopia sendiri menulis id_token Google ke logcat:
         Log.d("GoogleSignInHelper", "Token = " + idToken)
     (terbukti di smali_classes2/com/rtsoft/growtopia/GoogleSignInHelper.smali)
     Jadi cukup tangkap logcat saat pemain login Google.

  B. PROXY MITM (paling umum)
     Klien mengirim paket login berisi `ltoken|<nilai>` ke login.growtopiagame.com.
     Bila CA kita dipercaya (APK di-patch), isinya bisa dibaca.

  C. TURUNAN (khusus akun GrowID lama)
     ltoken = base64("_token=<clientdata>&growId=<USER>&password=<PASS>&reg=0")
     Jadi kalau punya nama + sandi, ltoken bisa DIHITUNG tanpa HP.

Modul ini mengurus jalur A dan C; jalur B ada di lucifer.mitm.
"""

from __future__ import annotations

import base64
import re
import subprocess
import time
import urllib.parse
from dataclasses import dataclass

__all__ = [
    "TangkapToken",
    "tangkap_id_token",
    "pindai_buffer",
    "ltoken_dari_kredensial",
    "tukar_id_token",
    "token_dari_savedat",
    "token_dari_hp",
    "ID_TOKEN_RE",
]

# id_token Google adalah JWT: tiga segmen base64url dipisah titik.
ID_TOKEN_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")

PKG = "com.rtsoft.growtopia"
TAG = "GoogleSignInHelper"


@dataclass
class TangkapToken:
    ok: bool
    id_token: str = ""
    ltoken: str = ""
    pesan: str = ""
    mentah: str = ""


def _adb(*args: str, timeout: int = 30) -> str:
    """Jalankan adb dan kembalikan stdout (teks)."""
    try:
        r = subprocess.run(
            ["adb", *args], capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return ""
    except subprocess.TimeoutExpired:
        return ""


def hp_tersambung() -> bool:
    out = _adb("devices")
    for baris in out.splitlines()[1:]:
        if "\tdevice" in baris:
            return True
    return False


def pindai_buffer() -> str:
    """Cari id_token di buffer logcat yang SUDAH ADA (tanpa menghapusnya).

    Berguna kalau pemain sudah login Google sebelum alat dijalankan —
    token masih tersimpan di buffer dan bisa langsung diambil.
    """
    out = _adb("logcat", "-d", "-s", f"{TAG}:D", "*:S", timeout=20)
    m = ID_TOKEN_RE.search(out)
    return m.group(0) if m else ""


def tangkap_id_token(durasi: int = 90, jalankan: bool = True) -> TangkapToken:
    """Tangkap id_token Google dari logcat Growtopia (jalur A).

    Pemain cukup menekan 'Login with Google' di HP saat penangkapan berjalan.
    """
    if not hp_tersambung():
        return TangkapToken(False, pesan="HP tidak tersambung (cek `adb devices`)")

    # 1) Pindai buffer dulu — kalau sudah ada (login sebelumnya), langsung pakai.
    tok = pindai_buffer()
    if tok:
        return TangkapToken(True, id_token=tok,
                            pesan="id_token ditemukan di buffer log (login sebelumnya)",
                            mentah="(dari buffer logcat)")

    # 2) PENTING: mulai aliran logcat SEBELUM app dijalankan, supaya tidak
    #    ada balapan (token ter-log sebelum logcat menempel).
    #    -s TAG:D = hanya tag itu; *:S membisukan sisanya.
    try:
        p = subprocess.Popen(
            ["adb", "logcat", "-v", "time", "-s", f"{TAG}:D", "*:S"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except FileNotFoundError:
        return TangkapToken(False, pesan="adb tidak ditemukan")

    # 3) Baru jalankan Growtopia (opsional).
    if jalankan:
        _adb("shell", "am", "force-stop", PKG)
        time.sleep(1)
        _adb("shell", "monkey", "-p", PKG, "-c",
             "android.intent.category.LAUNCHER", "1")

    # PENTING: readline() pada pipe logcat MEMBLOKIR kalau belum ada baris,
    # sehingga batas waktu tak pernah dicek -> fungsi menggantung.
    # Solusi: baca di thread terpisah, hasil masuk queue.
    import queue as _queue
    import threading as _threading

    q: "_queue.Queue[str | None]" = _queue.Queue()

    def _pembaca() -> None:
        try:
            for ln in p.stdout:  # type: ignore[union-attr]
                q.put(ln)
        except Exception:  # noqa: BLE001
            pass
        finally:
            q.put(None)

    th = _threading.Thread(target=_pembaca, daemon=True)
    th.start()

    akhir = time.time() + durasi
    buf: list[str] = []
    id_token = ""
    try:
        while time.time() < akhir:
            try:
                baris = q.get(timeout=0.5)
            except _queue.Empty:
                continue
            if baris is None:
                break
            buf.append(baris)
            m = ID_TOKEN_RE.search(baris)
            if m:
                id_token = m.group(0)
                break
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            p.kill()
        try:
            p.stdout.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass

    mentah = "".join(buf)[-4000:]
    if id_token:
        return TangkapToken(True, id_token=id_token,
                            pesan="id_token Google tertangkap dari log",
                            mentah=mentah)
    return TangkapToken(
        False, mentah=mentah,
        pesan=("Belum ada id_token. Pastikan: (1) Growtopia di layar login, "
               "(2) tekan 'Login with Google', (3) pilih akun Google-mu."),
    )


def ltoken_dari_kredensial(growid: str, password: str, client_data: str = "",
                           reg: int = 0) -> str:
    """Hitung `ltoken` dari nama + sandi (jalur C, akun GrowID lama).

    Bentuk ltoken (dari GrowtopiaLogin-Backend):
        base64("_token=<client_data>&growId=<growid>&password=<password>&reg=<0|1>")
    """
    from .account import build_client_data  # noqa: PLC0415

    cd = client_data or build_client_data(username=growid, password=password)
    cd_b64 = base64.b64encode(cd.encode()).decode()
    isi = (
        f"_token={urllib.parse.quote(cd_b64, safe='')}"
        f"&growId={urllib.parse.quote(growid, safe='')}"
        f"&password={urllib.parse.quote(password, safe='')}"
        f"&reg={reg}"
    )
    return base64.b64encode(isi.encode()).decode()


def token_dari_savedat(path: str) -> str:
    """Ambil **refreshToken** dari berkas `save.dat`.

    Struktur `save.dat` (biner): setiap field disimpan sebagai
        <nama field> \\x00 \\x01 \\x00\\x00\\x00 <panjang uint32 LE> <nilai>

    Field `Token` (472 byte) BUKAN terenkripsi — ia adalah refreshToken yang
    diterima `POST /player/growid/checktoken` sebagai `refreshToken`.
    (Dibuktikan: server membalas `{"status":"success"}`.)
    """
    import struct  # noqa: PLC0415

    with open(path, "rb") as f:
        data = f.read()

    for m in re.finditer(rb"Token", data):
        i = m.start()
        if data[max(0, i - 3):i] == b"FCM":      # lewati FCMToken
            continue
        for off in range(5, 10):
            if i + off + 4 > len(data):
                continue
            (n,) = struct.unpack_from("<I", data, i + off)
            if 50 < n < 4000:                    # panjang token wajar
                return data[i + off + 4:i + off + 4 + n].decode("latin-1")
    return ""


def token_dari_hp(pkg: str = PKG) -> TangkapToken:
    """Tarik `save.dat` dari HP lalu ambil refreshToken-nya (jalur D).

    Ini jalur paling langsung: token di `save.dat` **tidak terenkripsi**
    dan langsung diterima server (terbukti). Tidak perlu root.
    """
    import os as _os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    if not hp_tersambung():
        return TangkapToken(False, pesan="HP tidak tersambung (cek `adb devices`)")

    remote = f"/sdcard/Android/data/{pkg}/files/save.dat"
    tmp = _os.path.join(tempfile.gettempdir(), "lucifer-save.dat")
    _adb("pull", remote, tmp, timeout=60)
    if not _os.path.exists(tmp):
        return TangkapToken(False, pesan=f"gagal menarik {remote}")

    tok = token_dari_savedat(tmp)
    if tok:
        # PENTING: token dari save.dat adalah refreshToken (472 char).
        # Wajib ditukar ke ltoken game asli (428 char) via checktoken sebelum dipakai connect.
        try:
            import requests as _req  # noqa: PLC0415
            res = _req.post(
                "https://login.growtopiagame.com/player/growid/checktoken",
                data={"refreshToken": tok, "clientData": "platformID|3,1,1\n"},
                headers={"User-Agent": "Ubi/Growtopia (Android)", "X-Requested-With": "XMLHttpRequest"},
                timeout=20,
            )
            j = res.json()
            if j.get("status") == "success" and j.get("token"):
                tok = j["token"]
        except Exception:  # noqa: BLE001
            pass
        return TangkapToken(True, ltoken=tok,
                            pesan=f"ltoken diperoleh & divalidasi ({len(tok)} char)")
    return TangkapToken(False, pesan="field Token tidak ditemukan di save.dat")


def tukar_id_token(id_token: str, timeout: int = 25) -> TangkapToken:
    """Tukar id_token Google -> ltoken lewat server Growtopia (jalur A lanjutan).

    Endpoint resmi (terverifikasi hidup):
        GET /player/social/login  (POST -> 405, jadi GET + query)
    """
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    UA = "UbiServices_SDK_2022.Release.9_PC64_ansi_static"
    basis = "https://login.growtopiagame.com/player/social/login"
    dicoba: list[str] = []

    kandidat = [
        {"social_login": "google", "token": id_token},
        {"social_login": "google", "id_token": id_token},
        {"provider": "google", "token": id_token},
        {"social": "google", "token": id_token},
    ]
    for i, q in enumerate(kandidat, 1):
        url = basis + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                teks = r.read().decode("utf-8", "replace")
            dicoba.append(f"#{i}: HTTP {r.status} len={len(teks)}")
            try:
                j = json.loads(teks)
            except ValueError:
                dicoba.append(f"#{i}: bukan JSON {teks[:120]!r}")
                continue
            tok = j.get("token") or j.get("ltoken") or ""
            if j.get("status") == "success" and tok:
                return TangkapToken(True, id_token=id_token, ltoken=tok,
                                    pesan=j.get("message", "berhasil"),
                                    mentah=teks[:400])
            dicoba.append(f"#{i}: {j.get('status')} / {j.get('message')}")
        except Exception as e:  # noqa: BLE001
            dicoba.append(f"#{i}: {type(e).__name__}: {e}")

    return TangkapToken(False, id_token=id_token,
                        pesan="Penukaran id_token -> ltoken belum berhasil",
                        mentah="\n".join(dicoba))
