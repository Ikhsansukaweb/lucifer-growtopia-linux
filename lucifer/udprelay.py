"""lucifer.udprelay — jembatan UDP lokal <-> SOCKS5 UDP ASSOCIATE.

Kenapa ada modul ini: `enet_host_use_proxy()` di `enet/enet.so` RUSAK — ia
mengirim greeting SOCKS5 (`05 01 02`) lalu langsung menutup soket tanpa
membaca balasan, jadi semua proxy gagal walau proxy-nya sehat. (Dibuktikan
dengan proxy palsu lokal: satu-satunya yang diterima server adalah greeting,
lalu FIN.)

Solusinya tidak menyentuh .so: ENet bicara UDP biasa ke `127.0.0.1:<port>`,
lalu modul ini yang membungkus tiap datagram dengan header SOCKS5 dan
mengirimnya ke relay proxy. Balasan dilepas headernya dan diteruskan balik
ke ENet. Dari sisi ENet tidak ada yang berubah.
"""

from __future__ import annotations

import select
import socket
import struct
import threading
from typing import Optional

from .proxy import Proxy, _tangan

__all__ = ["RelayUdp", "RelayError"]


class RelayError(RuntimeError):
    pass


def _baca_alamat(rep: bytes) -> tuple[str, int]:
    """Ambil (host, port) dari balasan SOCKS5. `rep` = 10 byte pertama."""
    if rep[3] == 1:
        return socket.inet_ntoa(rep[4:8]), struct.unpack(">H", rep[8:10])[0]
    if rep[3] == 4:
        raise RelayError("relay IPv6 belum didukung")
    panjang = rep[4]
    raise RelayError(f"ATYP {rep[3]} tak dikenal (domain {panjang}B)")


class RelayUdp:
    """Tunnel UDP lokal untuk satu tujuan tetap lewat proxy SOCKS5.

    Pemakaian:
        relay = RelayUdp(proxy, (server_ip, server_port)); relay.start()
        ENetHost().connect("127.0.0.1", relay.port)
        ...
        relay.close()
    """

    def __init__(self, proxy: Proxy, target: tuple[str, int],
                 timeout: float = 8.0) -> None:
        self.proxy = proxy
        self.target = (target[0], int(target[1]))
        self.timeout = timeout
        self.port = 0
        self.error = ""

        self._ctl: Optional[socket.socket] = None
        self._udp: Optional[socket.socket] = None
        self._relay: Optional[tuple[str, int]] = None
        self._client: Optional[tuple[str, int]] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._kirim = 0
        self._terima = 0

        # Header SOCKS5 tetap untuk tujuan ini: RSV RSV FRAG ATYP ADDR PORT.
        th = self.target[0].encode()
        self._header_target = (
            b"\x00\x00\x00\x03" + bytes([len(th)]) + th
            + struct.pack(">H", self.target[1])
        )

    # -- hidup/mati -------------------------------------------------------- #
    def start(self) -> "RelayUdp":
        """Buka UDP ASSOCIATE + soket lokal. Raise RelayError kalau gagal."""
        try:
            self._ctl = _tangan(self.proxy, self.timeout)
        except OSError as e:
            raise RelayError(f"tak bisa hubungi proxy: {e}") from e

        try:
            self._ctl.sendall(b"\x05\x03\x00\x01" + b"\x00" * 4 + b"\x00\x00")
            rep = _baca_tepat(self._ctl, 10)
        except OSError as e:
            self.close()
            raise RelayError(f"UDP ASSOCIATE gagal: {e}") from e

        if rep[1] != 0:
            self.close()
            raise RelayError(
                f"proxy menolak UDP ASSOCIATE (kode {rep[1]}) — proxy ini "
                f"tidak bisa dipakai, Growtopia/ENet butuh UDP"
            )

        host, port = _baca_alamat(rep)
        if host in ("0.0.0.0", ""):
            host = self.proxy.host
        self._relay = (host, port)

        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # WAJIB 0.0.0.0, bukan 127.0.0.1: soket yang di-bind ke loopback tak
        # bisa mengirim ke relay di internet ("Invalid argument"). ENet tetap
        # menyambung ke 127.0.0.1:<port> karena kita mendengarkan di semua
        # antarmuka.
        self._udp.bind(("0.0.0.0", 0))
        self._udp.setblocking(False)
        self.port = self._udp.getsockname()[1]

        self._thread = threading.Thread(
            target=self._loop, name="lucifer-udprelay", daemon=True
        )
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        for s in (self._udp, self._ctl):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._udp = self._ctl = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def __enter__(self) -> "RelayUdp":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def statistik(self) -> dict[str, int]:
        return {"kirim": self._kirim, "terima": self._terima, "lokal": self.port}

    # -- inti -------------------------------------------------------------- #
    def _bingkus(self, data: bytes) -> bytes:
        return self._header_target + data

    def _buka(self, data: bytes) -> Optional[bytes]:
        """Lepas header SOCKS5 dari datagram relay. None kalau tak valid."""
        if len(data) < 10 or data[0] != 0 or data[1] != 0:
            return None
        if data[2] != 0:            # FRAG: tidak mendukung fragmentasi
            return None
        atyp = data[3]
        if atyp == 1:
            return data[10:]
        if atyp == 4:
            return data[22:]
        if atyp == 3:
            if len(data) < 5:
                return None
            return data[5 + data[4] + 2:]
        return None

    def _loop(self) -> None:
        udp = self._udp
        if udp is None:
            return
        while not self._stop.is_set():
            try:
                siap, _, _ = select.select([udp], [], [], 0.5)
            except (OSError, ValueError):
                return
            if not siap:
                continue
            try:
                data, asal = udp.recvfrom(65535)
            except OSError:
                return

            # Datagram pertama selalu dari ENet (klien lokal). Setelah itu,
            # apa pun yang bukan dari alamat klien dianggap balasan relay.
            # Port sumber relay TIDAK selalu sama dengan yang dijanjikan di
            # balasan ASSOCIATE (Oxylabs pakai soket keluar berbeda), jadi
            # alamat klien yang dipakai sebagai pembeda.
            if self._client is None:
                self._client = asal
            elif asal != self._client:
                bersih = self._buka(data)
                if bersih:
                    self._terima += 1
                    try:
                        udp.sendto(bersih, self._client)
                    except OSError:
                        pass
                continue

            # Datagram dari ENet: bungkus dan teruskan ke relay.
            self._kirim += 1
            try:
                udp.sendto(self._bingkus(data), self._relay)
            except OSError as e:
                self.error = str(e)
                return


def _baca_tepat(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        potong = sock.recv(n - len(buf))
        if not potong:
            raise OSError("proxy menutup koneksi")
        buf += potong
    return buf
