"""
lucifer/mitm.py — Penangkap `ltoken` lewat proxy MITM.

KENAPA INI ADA
--------------
`login.growtopiagame.com` tidak pernah menyajikan halaman login (sudah
dibuktikan: selalu JSON). Jadi satu-satunya cara mengambil `ltoken` milik akun
Google/Apple adalah menangkapnya **saat client asli login** — dan itu butuh
membuka TLS. Modul ini melakukannya:

    client Growtopia  --(proxy ini)-->  login.growtopiagame.com
                            |
                            +-- membuka TLS, membaca isi, menyimpan `token`

CARA PAKAI (ringkas)
--------------------
1. Jalankan `lucifer capture` di PC ini.
2. Di perangkat tempat Growtopia login (HP Android / PC), arahkan proxy ke
   `IP-PC:8080`.
3. Pasang sertifikat CA yang dicetak oleh perintah itu di perangkat tersebut.
4. Login Growtopia seperti biasa (pilih akun Google).
5. Lucifer otomatis menangkap `ltoken` dan menyimpannya sebagai akun.

Hanya pustaka standar + `openssl` (untuk membuat sertifikat).
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("lucifer.mitm")

# Host yang isinya kita periksa (tempat ltoken lewat).
HOST_PANTAU = (
    "growtopiagame.com",
    "ubisoft.com",
)

# Nama berkas di dalam folder CA.
_CA_KEY = "lucifer-ca.key"
_CA_PEM = "lucifer-ca.pem"


class MitmError(RuntimeError):
    """Gagal menyiapkan/menjalankan proxy."""


# --------------------------------------------------------------------------- #
# Sertifikat
# --------------------------------------------------------------------------- #

def _openssl(*args: str) -> None:
    """Jalankan openssl; lempar MitmError kalau gagal."""
    exe = _cari_openssl()
    hasil = subprocess.run(
        [exe, *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if hasil.returncode != 0:
        pesan = hasil.stdout.decode("utf-8", "replace").strip()
        raise MitmError(f"openssl gagal: {pesan[:300]}")


def _cari_openssl() -> str:
    for nama in ("openssl", "/usr/bin/openssl", "/usr/local/bin/openssl"):
        if os.path.sep in nama:
            if os.path.exists(nama):
                return nama
        else:
            from shutil import which
            p = which(nama)
            if p:
                return p
    raise MitmError("openssl tidak ditemukan — pasang dulu: sudo apt install openssl")


def siapkan_ca(folder: str | Path) -> dict[str, str]:
    """Buat CA (kalau belum ada) dan kembalikan path-nya.

    CA inilah yang harus dipasang di perangkat agar proxy ini bisa membuka
    TLS-nya.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = folder / _CA_KEY
    pem = folder / _CA_PEM

    if not (key.exists() and pem.exists()):
        _openssl(
            "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key), "-out", str(pem),
            "-days", "3650", "-nodes",
            "-subj", "/CN=Lucifer Capture CA/O=Lucifer",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        )
        try:
            os.chmod(key, 0o600)
        except OSError:
            pass

    return {"key": str(key), "pem": str(pem)}


def sertifikat_host(ca: dict[str, str], folder: str | Path,
                    host: str) -> str:
    """Buat (atau ambil dari cache) sertifikat untuk satu host.

    Sertifikat ditandatangani CA kita supaya perangkat yang sudah memasang CA
    mempercayainya.
    """
    folder = Path(folder) / "hosts"
    folder.mkdir(parents=True, exist_ok=True)
    aman = re.sub(r"[^A-Za-z0-9._-]", "_", host)
    cert = folder / f"{aman}.pem"
    key = folder / f"{aman}.key"
    # Berkas gabungan (sertifikat + kunci) — inilah yang dipakai
    # load_cert_chain(). Selalu dikembalikan, termasuk saat cache dipakai.
    gabung = folder / f"{aman}-lengkap.pem"

    if cert.exists() and key.exists() and gabung.exists():
        return str(gabung)

    csr = folder / f"{aman}.csr"
    ext = folder / f"{aman}.ext"
    ext.write_text(
        "subjectAltName=DNS:" + host + "\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    _openssl(
        "req", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(csr),
        "-subj", f"/CN={host}",
    )
    _openssl(
        "x509", "-req", "-in", str(csr),
        "-CA", ca["pem"], "-CAkey", ca["key"],
        "-CAcreateserial", "-out", str(cert),
        "-days", "825", "-extfile", str(ext),
    )
    # Gabungkan cert+key supaya load_cert_chain mudah.
    gabung.write_text(
        cert.read_text(encoding="utf-8") + key.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    try:
        os.chmod(key, 0o600)
        os.chmod(gabung, 0o600)
    except OSError:
        pass
    return str(gabung)


# --------------------------------------------------------------------------- #
# Ekstraksi token
# --------------------------------------------------------------------------- #

def ekstrak_token(isi: bytes) -> dict[str, Any] | None:
    """Cari token login di dalam badan respons.

    Mengembalikan dict berisi `token` (+ info lain) kalau ketemu, else None.
    """
    if not isi:
        return None
    teks = isi.decode("utf-8", "replace")

    # Bentuk utama: JSON {"status":..,"token":"..","accountType":..}
    for kandidat in _calon_json(teks):
        try:
            data = json.loads(kandidat)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            tok = data.get("token") or data.get("ltoken")
            if isinstance(tok, str) and tok.strip():
                return {
                    "token": tok.strip(),
                    "status": data.get("status", ""),
                    "message": data.get("message", ""),
                    "accountType": data.get("accountType", ""),
                    "accountAge": data.get("accountAge", ""),
                    "url": data.get("url", ""),
                }

    # Cadangan: cari pola "token":"..."
    m = re.search(r'"token"\s*:\s*"([^"]{8,})"', teks)
    if m:
        return {"token": m.group(1), "status": "", "message": "",
                "accountType": "", "accountAge": "", "url": ""}
    return None


def _calon_json(teks: str) -> list[str]:
    """Kumpulkan potongan teks yang mungkin JSON (badan bisa tercampur)."""
    keluar: list[str] = []
    mulai = teks.find("{")
    if mulai >= 0:
        dalam = 0
        for i in range(mulai, len(teks)):
            c = teks[i]
            if c == "{":
                dalam += 1
            elif c == "}":
                dalam -= 1
                if dalam == 0:
                    keluar.append(teks[mulai:i + 1])
                    break
    if not keluar:
        keluar.append(teks.strip())
    return keluar


def ekstrak_client_data(isi: bytes) -> dict[str, str]:
    """Ambil field penting dari badan POST (blob `data` / `clientData`)."""
    hasil: dict[str, str] = {}
    if not isi:
        return hasil
    teks = isi.decode("utf-8", "replace")
    for kunci in ("data", "clientData", "client_data"):
        m = re.search(rf"(?:^|&){kunci}=([^&]+)", teks)
        if m:
            hasil[kunci] = m.group(1)[:4000]
    return hasil


# --------------------------------------------------------------------------- #
# Proxy
# --------------------------------------------------------------------------- #

class PenangkapToken:
    """Proxy MITM yang menyimpan `ltoken` begitu terlihat di jaringan.

    Contoh:
        p = PenangkapToken("/path/data/ca", on_token=simpan)
        p.mulai(port=8080)
        ...
        p.tutup()
    """

    def __init__(self,
                 folder_ca: str | Path,
                 on_token: Callable[[dict[str, Any]], None] | None = None,
                 on_request: Callable[[dict[str, Any]], None] | None = None,
                 host_pantau: tuple[str, ...] = HOST_PANTAU,
                 peta_upstream: dict[str, tuple[str, int]] | None = None,
                 log_fn: Callable[[str], None] | None = None) -> None:
        self.folder_ca = Path(folder_ca)
        self.on_token = on_token
        self.on_request = on_request
        self.host_pantau = tuple(h.lower() for h in host_pantau)
        self.peta_upstream = peta_upstream or {}
        self.log_fn = log_fn or (lambda m: log.info("%s", m))

        self.ca = siapkan_ca(self.folder_ca)
        self.port = 0
        self.token: dict[str, Any] | None = None
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sert_cache: dict[str, str] = {}
        self._kunci = threading.Lock()
        self.jumlah_request = 0

    # -- siklus hidup ----------------------------------------------------- #

    def mulai(self, port: int = 8080, host: str = "0.0.0.0") -> int:
        """Buka port proxy. Mengembalikan port yang benar-benar dipakai."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(64)
        s.settimeout(0.5)
        self._sock = s
        self.port = s.getsockname()[1]
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="lucifer-mitm")
        self._thread.start()
        self.log_fn(f"[mitm] proxy mendengarkan di port {self.port}")
        return self.port

    def tutup(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    # -- inti ------------------------------------------------------------- #

    def _loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._tangani, args=(conn, addr),
                             daemon=True).start()

    def _tangani(self, conn: socket.socket, addr: Any) -> None:
        try:
            conn.settimeout(20)
            baris = _baca_baris(conn)
            if not baris:
                return
            if baris.upper().startswith("CONNECT"):
                self._tangani_connect(conn, baris)
            else:
                self._tangani_http(conn, baris)
        except Exception as e:  # noqa: BLE001
            log.debug("koneksi dari %s gagal: %s", addr, e)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _tangani_connect(self, conn: socket.socket, baris: str) -> None:
        bagian = baris.split()
        if len(bagian) < 2:
            return
        host_port = bagian[1]
        if ":" in host_port:
            host, port_s = host_port.rsplit(":", 1)
            port = int(port_s)
        else:
            host, port = host_port, 443

        # Beri tahu klien bahwa terowongan siap.
        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")

        # PENTING: habiskan sisa header request CONNECT sampai baris kosong.
        # Kalau tidak, sisa "\r\n" itu akan masuk ke TLS handshake dan
        # menyebabkan WRONG_VERSION_NUMBER.
        while True:
            sisa = _baca_baris(conn)
            if not sisa:
                break

        # Host yang TIDAK dipantau diteruskan MENTAH (tanpa MITM).
        # Ini wajib: Google Play Services, WhatsApp, dan app lain memakai
        # certificate pinning, jadi TLS kita akan ditolak dan app mereka
        # rusak. Dengan bypass, hanya host Growtopia yang kita bedah.
        if not self._dipantau(host):
            self._terowongan_mentah(conn, host, port)
            return

        cert = self._cert_untuk(host)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert)
        try:
            tls = ctx.wrap_socket(conn, server_side=True)
        except ssl.SSLError as e:
            self.log_fn(f"[mitm] TLS ke {host} gagal: {e} "
                        "(sertifikat CA belum dipasang di perangkat?)")
            return

        # Baca satu request HTTP dari dalam terowongan.
        req = _baca_request(tls)
        if req is None:
            return
        metode, path, headers, body = req
        self.jumlah_request += 1

        if self.on_request is not None:
            try:
                self.on_request({
                    "host": host, "method": metode, "path": path,
                    "client_data": ekstrak_client_data(body),
                    "body_len": len(body),
                })
            except Exception:  # noqa: BLE001
                pass

        # Teruskan ke server asli.
        tujuan_host, tujuan_port = self.peta_upstream.get(
            host, (host, port))
        status, hdr, isi = _forward(tujuan_host, tujuan_port, host,
                                    metode, path, headers, body)

        # Periksa apakah ini respons login berisi token.
        if self._dipantau(host):
            tok = ekstrak_token(isi)
            if tok:
                with self._kunci:
                    self.token = tok
                self.log_fn(f"[mitm] TOKEN DITEMUKAN dari {host}{path}")
                if self.on_token is not None:
                    try:
                        self.on_token(tok)
                    except Exception as e:  # noqa: BLE001
                        log.debug("on_token gagal: %s", e)

        # Kirim balik ke klien.
        try:
            tls.sendall(_susun_respons(status, hdr, isi))
        except OSError:
            pass
        try:
            tls.unwrap()
        except (ssl.SSLError, OSError):
            pass

    def _terowongan_mentah(self, conn: socket.socket, host: str,
                           port: int) -> None:
        """Teruskan koneksi TANPA membedah TLS (bypass).

        Dipakai untuk host di luar pantauan. Penting karena banyak app
        (Google Play Services, WhatsApp, dsb.) memakai certificate pinning
        sehingga TLS kita pasti ditolak — kalau dipaksa, app mereka rusak.
        """
        tujuan_host, tujuan_port = self.peta_upstream.get(host, (host, port))
        try:
            hulu = socket.create_connection((tujuan_host, tujuan_port),
                                            timeout=20)
        except OSError as e:
            self.log_fn(f"[mitm] bypass {host} gagal: {e}")
            return

        # Teruskan dua arah sampai salah satu sisi tutup.
        def _salin(dari: socket.socket, ke: socket.socket) -> None:
            try:
                while True:
                    data = dari.recv(65536)
                    if not data:
                        break
                    ke.sendall(data)
            except OSError:
                pass
            finally:
                for s in (dari, ke):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        t1 = threading.Thread(target=_salin, args=(conn, hulu), daemon=True)
        t2 = threading.Thread(target=_salin, args=(hulu, conn), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=120)
        t2.join(timeout=120)
        for s in (hulu, conn):
            try:
                s.close()
            except OSError:
                pass

    def _tangani_http(self, conn: socket.socket, baris: str) -> None:
        """HTTP polos (bukan CONNECT) — diteruskan apa adanya."""
        req = _baca_request(conn, baris_awal=baris)
        if req is None:
            return
        metode, path, headers, body = req
        if not path.lower().startswith("http://"):
            return
        sisa = path[7:]
        host = sisa.split("/", 1)[0]
        path2 = "/" + (sisa.split("/", 1)[1] if "/" in sisa else "")
        self.jumlah_request += 1
        tujuan_host, tujuan_port = self.peta_upstream.get(host, (host, 80))
        status, hdr, isi = _forward(tujuan_host, tujuan_port, host,
                                    metode, path2, headers, body, tls=False)
        if self._dipantau(host):
            tok = ekstrak_token(isi)
            if tok:
                with self._kunci:
                    self.token = tok
                if self.on_token is not None:
                    try:
                        self.on_token(tok)
                    except Exception:  # noqa: BLE001
                        pass
        try:
            conn.sendall(_susun_respons(status, hdr, isi))
        except OSError:
            pass

    def _dipantau(self, host: str) -> bool:
        h = host.lower()
        return any(h == d or h.endswith("." + d) for d in self.host_pantau)

    def _cert_untuk(self, host: str) -> str:
        with self._kunci:
            if host not in self._sert_cache:
                self._sert_cache[host] = sertifikat_host(
                    self.ca, self.folder_ca, host)
            return self._sert_cache[host]

    # -- info ------------------------------------------------------------- #

    def info_ca(self) -> dict[str, str]:
        return dict(self.ca)


# --------------------------------------------------------------------------- #
# Utilitas HTTP
# --------------------------------------------------------------------------- #

def _baca_baris(sock: socket.socket) -> str:
    buf = b""
    while b"\r\n" not in buf and b"\n" not in buf:
        potong = sock.recv(1)
        if not potong:
            break
        buf += potong
        if len(buf) > 8192:
            break
    return buf.decode("latin-1").strip()


def _baca_request(sock: socket.socket, baris_awal: str = "") -> (
        tuple[str, str, dict[str, str], bytes] | None):
    """Baca satu request HTTP lengkap. None kalau tidak ada."""
    if not baris_awal:
        baris_awal = _baca_baris(sock)
    if not baris_awal:
        return None
    bagian = baris_awal.split()
    if len(bagian) < 3:
        return None
    metode, path, _ = bagian[0], bagian[1], bagian[2]

    headers: dict[str, str] = {}
    while True:
        baris = _baca_baris(sock)
        if not baris:
            break
        if ":" in baris:
            k, v = baris.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    body = b""
    panjang = headers.get("content-length")
    if panjang:
        try:
            n = int(panjang)
        except ValueError:
            n = 0
        while len(body) < n:
            potong = sock.recv(min(65536, n - len(body)))
            if not potong:
                break
            body += potong
    return metode, path, headers, body


def _forward(host: str, port: int, sni: str, metode: str, path: str,
             headers: dict[str, str], body: bytes, tls: bool = True) -> (
        tuple[int, dict[str, str], bytes]):
    """Kirim request ke server asli, kembalikan (status, header, badan)."""
    mentah = socket.create_connection((host, port), timeout=20)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        mentah = ctx.wrap_socket(mentah, server_hostname=sni)

    baris = [f"{metode} {path} HTTP/1.1"]
    sudah_host = False
    for k, v in headers.items():
        lk = k.lower()
        if lk in ("proxy-connection", "connection"):
            continue
        if lk == "host":
            sudah_host = True
        baris.append(f"{k}: {v}")
    if not sudah_host:
        baris.append(f"Host: {sni}")
    baris.append("Connection: close")
    kepala = "\r\n".join(baris).encode("latin-1") + b"\r\n\r\n"
    mentah.sendall(kepala + (body or b""))

    data = b""
    mentah.settimeout(20)
    while True:
        try:
            potong = mentah.recv(65536)
        except (socket.timeout, OSError):
            break
        if not potong:
            break
        data += potong
        if len(data) > 8 * 1024 * 1024:
            break
    try:
        mentah.close()
    except OSError:
        pass

    return _urai_respons(data)


def _urai_respons(data: bytes) -> tuple[int, dict[str, str], bytes]:
    """Pisahkan respons HTTP menjadi status, header, badan."""
    if b"\r\n\r\n" not in data:
        return 502, {}, data
    kepala, badan = data.split(b"\r\n\r\n", 1)
    baris = kepala.decode("latin-1").split("\r\n")
    status = 502
    if baris and baris[0].startswith("HTTP/"):
        try:
            status = int(baris[0].split()[1])
        except (IndexError, ValueError):
            pass
    headers: dict[str, str] = {}
    for b in baris[1:]:
        if ":" in b:
            k, v = b.split(":", 1)
            headers[k.strip()] = v.strip()

    # Buang chunked encoding sederhana supaya badan bisa dibaca.
    te = headers.get("Transfer-Encoding", "").lower()
    if "chunked" in te:
        badan = _buka_chunked(badan)
        headers.pop("Transfer-Encoding", None)
    return status, headers, badan


def _buka_chunked(data: bytes) -> bytes:
    keluar = b""
    sisa = data
    while sisa:
        if b"\r\n" not in sisa:
            break
        baris, sisa = sisa.split(b"\r\n", 1)
        try:
            n = int(baris.split(b";")[0].strip(), 16)
        except ValueError:
            break
        if n == 0:
            break
        keluar += sisa[:n]
        sisa = sisa[n + 2:] if len(sisa) > n + 2 else b""
    return keluar


def _susun_respons(status: int, headers: dict[str, str],
                   body: bytes) -> bytes:
    baris = [f"HTTP/1.1 {status} OK" if status == 200
             else f"HTTP/1.1 {status}"]
    h = dict(headers)
    h.pop("Transfer-Encoding", None)
    h.pop("Content-Encoding", None)
    h["Content-Length"] = str(len(body))
    h["Connection"] = "close"
    for k, v in h.items():
        baris.append(f"{k}: {v}")
    return ("\r\n".join(baris) + "\r\n\r\n").encode("latin-1") + body


def ip_lokal() -> str:
    """Perkirakan IP LAN PC ini (untuk diisi di HP)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def tunggu_token(penangkap: PenangkapToken, batas_detik: float = 300,
                 jeda: float = 0.5) -> dict[str, Any] | None:
    """Tunggu sampai token tertangkap atau waktu habis."""
    mulai = time.time()
    while time.time() - mulai < batas_detik:
        if penangkap.token:
            return penangkap.token
        time.sleep(jeda)
    return None
