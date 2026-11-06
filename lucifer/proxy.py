"""lucifer.proxy — parsing + uji SOCKS5 untuk koneksi bot.

Format yang diterima:
    host:port
    user:pass@host:port
    host:port:user:pass              <- ekspor webshare
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

__all__ = ["Proxy", "parse", "uji", "uji_udp", "uji_enet"]


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
        if u.scheme in ("http", "https"):
            raise ValueError(
                "proxy HTTP tidak didukung — Growtopia/ENet butuh UDP, "
                "proxy HTTP tidak meneruskan UDP. Pakai SOCKS5 yang "
                "mendukung UDP ASSOCIATE."
            )
        if u.scheme not in ("socks5", "socks5h"):
            raise ValueError(f"skema '{u.scheme}' tidak didukung — pakai socks5://")
        host, port = u.hostname or "", u.port or 1080
        user = unquote(u.username or "")
        passwd = unquote(u.password or "")
    else:
        user = passwd = ""
        sisa = s
        # Format ekspor webshare: host:port:user:pass (4 bagian). Dikenali
        # dari jumlah titik dua; tanpa ini port terbaca sebagai sandi.
        if s.count(":") == 3 and "@" not in s:
            host, port_s, user, passwd = s.split(":", 3)
            try:
                port = int(port_s)
            except ValueError as e:
                raise ValueError(f"port proxy bukan angka: {port_s!r}") from e
            if not host.strip():
                raise ValueError("host proxy kosong")
            if not (0 < port < 65536):
                raise ValueError(f"port proxy di luar rentang: {port}")
            return Proxy(host.strip(), port, user, passwd)
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


def _tangan(p: Proxy, timeout: float) -> socket.socket:
    """Buka koneksi SOCKS5 + auth. Return soket siap perintah. Raise OSError."""
    sock = socket.create_connection((p.host, p.port), timeout=timeout)
    sock.settimeout(timeout)
    metode = b"\x00\x02" if p.user else b"\x00"
    sock.sendall(b"\x05" + bytes([len(metode)]) + metode)
    balas = _baca(sock, 2)
    if balas[0] != 5:
        raise OSError(f"bukan SOCKS5 (versi {balas[0]})")
    if balas[1] == 0xFF:
        raise OSError("proxy menolak semua metode auth")
    if balas[1] == 0x02:
        if not p.user:
            raise OSError("proxy menuntut user/pass, tapi kredensial kosong")
        u, w = p.user.encode(), p.passwd.encode()
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(w)]) + w)
        if _baca(sock, 2)[1] != 0:
            raise OSError("user/pass ditolak proxy")
    return sock


_KODE_UDP = {
    1: "general failure", 3: "jaringan tak tercapai", 4: "host tak tercapai",
    5: "koneksi ditolak", 6: "TTL habis", 7: "UDP ASSOCIATE tak didukung",
    8: "tipe alamat tak didukung",
}

# Kueri DNS untuk example.com. Dipakai sebagai bukti relay BENAR-BENAR
# meneruskan datagram: server DNS selalu membalas kalau jalurnya hidup.
_DNS_UJI = (
    b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    b"\x07example\x03com\x00\x00\x01\x00\x01"
)


def _relay_probe(udp: socket.socket, relay: tuple[str, int],
                 target: tuple[str, int], payload: bytes,
                 timeout: float) -> bool:
    """Kirim satu datagram lewat relay, True kalau ada balasan."""
    host_b = target[0].encode()
    paket = (b"\x00\x00\x00\x03" + bytes([len(host_b)]) + host_b
             + struct.pack(">H", target[1]) + payload)
    udp.sendto(paket, relay)
    try:
        udp.recvfrom(2048)
        return True
    except socket.timeout:
        return False


def uji_udp(p: Proxy, timeout: float = 8.0,
            target: Optional[tuple[str, int]] = None) -> tuple[bool, str]:
    """Buktikan proxy bisa meneruskan UDP (syarat mutlak Growtopia/ENet).

    Dua tahap, karena banyak proxy "menipu":

    1. **Validasi relay** — kirim kueri DNS sungguhan ke 1.1.1.1:53 lewat
       relay. Server DNS selalu membalas, jadi diam = relay bohong. Ini
       kasus proxy residential yang menjawab UDP ASSOCIATE "OK" lalu
       membuang semua datagram.
    2. **Uji tujuan** (`target`) — datagram ke port game. Server game boleh
       diam (maintenance/port diblok), jadi tahap 2 tidak menentukan hidup
       mati proxy, hanya dilaporkan.
    """
    sock = None
    udp = None
    try:
        sock = _tangan(p, timeout)
        sock.sendall(b"\x05\x03\x00\x01" + b"\x00" * 4 + b"\x00\x00")
        rep = _baca(sock, 10)
        if rep[1] != 0:
            kode = _KODE_UDP.get(rep[1], "?")
            return False, f"UDP ASSOCIATE ditolak (kode {rep[1]}: {kode})"

        relay_ip = socket.inet_ntoa(rep[4:8])
        relay_port = struct.unpack(">H", rep[8:10])[0]
        if relay_ip in ("0.0.0.0", ""):
            relay_ip = p.host
        relay = (relay_ip, relay_port)

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(timeout)

        if not _relay_probe(udp, relay, ("1.1.1.1", 53), _DNS_UJI, timeout):
            return False, ("relay UDP tidak meneruskan apa pun "
                           f"({relay_ip}:{relay_port}) — proxy menerima "
                           "UDP ASSOCIATE tapi membuang datagram")

        if target is None:
            return True, f"UDP relay berfungsi (balasan DNS lewat {relay_ip})"

        hidup = _relay_probe(udp, relay, target, b"\x00" * 32, timeout)
        if hidup:
            return True, f"UDP ok — {target[0]}:{target[1]} menjawab lewat relay"
        return True, (f"UDP relay berfungsi, tetapi {target[0]}:{target[1]} "
                      "tidak menjawab (server diam/maintenance)")
    except socket.timeout:
        return False, f"timeout {timeout:.0f}s"
    except OSError as e:
        return False, str(e)
    finally:
        for s in (udp, sock):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def uji_enet(p: Proxy, server: tuple[str, int], timeout_ms: int = 6000) -> tuple[bool, str]:
    """Uji sesungguhnya: ENet handshake ke server Growtopia lewat proxy.

    Hanya ini yang membuktikan proxy bisa dipakai bot. Tanpa argumen
    `server`, uji berhenti di UDP ASSOCIATE (`uji_udp`).
    """
    try:
        from .enet import ENetHost  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return False, f"modul enet tak bisa dimuat: {e}"
    h = None
    try:
        h = ENetHost(proxy=p.tuple4())
        ok = h.connect(server[0], server[1], timeout_ms=timeout_ms)
        return (ok, "ok — ENet tersambung ke server"
                if ok else "ENet connect gagal (paket UDP tak sampai)")
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    finally:
        if h is not None:
            try:
                h.disconnect(graceful=True, wait_ms=800)
            except Exception:  # noqa: BLE001
                pass
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass


def _baca(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        potong = sock.recv(n - len(buf))
        if not potong:
            raise OSError("proxy menutup koneksi")
        buf += potong
    return buf
