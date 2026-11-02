"""lucifer.proxy — parsing + uji SOCKS5 untuk koneksi bot.

Format yang diterima:
    host:port
    user:pass@host:port
    socks5://host:port
    socks5h://user:pass@host:port

Hanya SOCKS5 (tanpa auth / user-pass). ENet yang mengurus tunnel-nya;
modul ini menormalkan string dan menyediakan uji tangan (handshake) supaya
pengguna tahu proxy hidup atau mati SEBELUM bot connect.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlsplit

__all__ = ["Proxy", "parse", "uji"]


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    user: str = ""
    passwd: str = ""

    def tuple4(self) -> tuple[str, int, str, str]:
        """Bentuk yang diminta `enet_host_use_proxy`."""
        return (self.host, self.port, self.user, self.passwd)

    def url(self, sandi: bool = True) -> str:
        auth = ""
        if self.user:
            auth = f"{self.user}:{self.passwd}@" if sandi else f"{self.user}:***@"
        return f"socks5://{auth}{self.host}:{self.port}"

    def __str__(self) -> str:
        return self.url(sandi=False)


def parse(teks: Optional[str]) -> Optional[Proxy]:
    """Urai string proxy. `None`/kosong → None. Format salah → ValueError."""
    if not teks:
        return None
    s = str(teks).strip()
    if not s:
        return None

    if "://" in s:
        u = urlsplit(s)
        if u.scheme not in ("socks5", "socks5h"):
            raise ValueError(f"skema '{u.scheme}' tidak didukung — pakai socks5://")
        host, port = u.hostname or "", u.port or 1080
        user = unquote(u.username or "")
        passwd = unquote(u.password or "")
    else:
        user = passwd = ""
        sisa = s
        if "@" in s:
            kredensial, sisa = s.rsplit("@", 1)
            if ":" in kredensial:
                user, passwd = kredensial.split(":", 1)
            else:
                user = kredensial
        if ":" not in sisa:
            raise ValueError("proxy harus berformat host:port")
        host, _, port_s = sisa.rpartition(":")
        try:
            port = int(port_s)
        except ValueError as e:
            raise ValueError(f"port proxy bukan angka: {port_s!r}") from e

    host = (host or "").strip()
    if not host:
        raise ValueError("host proxy kosong")
    if not (0 < port < 65536):
        raise ValueError(f"port proxy di luar rentang: {port}")
    if len(user) > 255 or len(passwd) > 255:
        raise ValueError("user/pass SOCKS5 maksimal 255 byte")
    return Proxy(host, port, user, passwd)


def uji(p: Proxy, target: tuple[str, int] = ("1.1.1.1", 80), timeout: float = 8.0) -> tuple[bool, str]:
    """Handshake SOCKS5 sungguhan sampai CONNECT ke `target`.

    Return (ok, pesan). Tidak mengirim data aplikasi — hanya membuktikan
    proxy menerima kredensial dan bisa membuka jalur keluar.
    """
    try:
        with socket.create_connection((p.host, p.port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            metode = b"\x00\x02" if p.user else b"\x00"
            sock.sendall(b"\x05" + bytes([len(metode)]) + metode)
            balas = _baca(sock, 2)
            if balas[0] != 5:
                return False, f"bukan SOCKS5 (versi {balas[0]})"
            if balas[1] == 0xFF:
                return False, "proxy menolak semua metode auth"
            if balas[1] == 0x02:
                if not p.user:
                    return False, "proxy menuntut user/pass, tapi kredensial kosong"
                u, w = p.user.encode(), p.passwd.encode()
                sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(w)]) + w)
                st = _baca(sock, 2)
                if st[1] != 0:
                    return False, "user/pass ditolak proxy"

            host_b = target[0].encode()
            sock.sendall(
                b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b
                + struct.pack(">H", target[1])
            )
            kepala = _baca(sock, 4)
            if kepala[1] != 0:
                return False, f"CONNECT ditolak (kode {kepala[1]})"
            if kepala[3] == 1:
                _baca(sock, 4)
            elif kepala[3] == 4:
                _baca(sock, 16)
            else:
                panjang = _baca(sock, 1)[0]
                _baca(sock, panjang)
            _baca(sock, 2)
            return True, f"ok — {p.host}:{p.port} meneruskan ke {target[0]}:{target[1]}"
    except socket.timeout:
        return False, f"timeout {timeout:.0f}s menyambung ke {p.host}:{p.port}"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


def _baca(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        potong = sock.recv(n - len(buf))
        if not potong:
            raise OSError("proxy menutup koneksi")
        buf += potong
    return buf
