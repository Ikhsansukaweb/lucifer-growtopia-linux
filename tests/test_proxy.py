#!/usr/bin/env python3
"""tests/test_proxy.py — SOCKS5 parsing + jalur API proxy (tanpa jaringan luar).

Bagian handshake diuji terhadap server SOCKS5 palsu di localhost, jadi uji ini
tidak butuh proxy sungguhan maupun internet.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lucifer import proxy as px  # noqa: E402

LULUS = GAGAL = 0
GAGAL_NAMA: list[str] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> bool:
    global LULUS, GAGAL
    if kondisi:
        LULUS += 1
        print(f"  ✓ {nama}" + (f"  {detail}" if detail else ""))
    else:
        GAGAL += 1
        GAGAL_NAMA.append(nama)
        print(f"  ✗ {nama}  {detail}")
    return kondisi


def uji_parse() -> None:
    print("== parsing ==")
    cek("host:port", px.parse("127.0.0.1:1080") == px.Proxy("127.0.0.1", 1080))
    cek("skema socks5", px.parse("socks5://1.2.3.4:9050") == px.Proxy("1.2.3.4", 9050))
    cek("user:pass", px.parse("a:b@1.2.3.4:1080") == px.Proxy("1.2.3.4", 1080, "a", "b"))
    cek("socks5h + userinfo",
        px.parse("socks5h://u:p%40ss@host.tld:1080") == px.Proxy("host.tld", 1080, "u", "p@ss"),
        str(px.parse("socks5h://u:p%40ss@host.tld:1080")))
    cek("kosong -> None", px.parse("") is None and px.parse(None) is None)

    for buruk, sebab in [("hostsaja", "tanpa port"), ("h:abc", "port bukan angka"),
                         ("h:99999", "port di luar rentang"),
                         ("http://h:80", "skema salah")]:
        gagal = False
        try:
            px.parse(buruk)
        except ValueError:
            gagal = True
        cek(f"tolak {sebab}", gagal, buruk)

    cek("url menyembunyikan sandi", px.parse("u:rahasia@h:1080").url(sandi=False) ==
        "socks5://u:***@h:1080")
    cek("url asli utuh", px.parse("u:rahasia@h:1080").url() ==
        "socks5://u:rahasia@h:1080")
    cek("tuple4 untuk ENet", px.parse("u:p@h:1").tuple4() == ("h", 1, "u", "p"))


class SocksPalsu:
    """Server SOCKS5 minimal: no-auth atau user/pass, lalu CONNECT sukses."""

    def __init__(self, wajib_auth: bool = False, tolak: bool = False) -> None:
        self.wajib_auth = wajib_auth
        self.tolak = tolak
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._layan, daemon=True)
        self.thread.start()

    def _layan(self) -> None:
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            kepala = conn.recv(2)
            if len(kepala) < 2:
                return
            conn.recv(kepala[1])
            if self.wajib_auth:
                conn.sendall(b"\x05\x02")
                v = conn.recv(2)
                if len(v) < 2:
                    return
                conn.recv(v[1])
                w = conn.recv(1)
                if w:
                    conn.recv(w[0])
                conn.sendall(b"\x01\x00")
            else:
                conn.sendall(b"\x05\x00")
            req = conn.recv(4)
            if len(req) < 4:
                return
            if req[3] == 3:
                n = conn.recv(1)[0]
                conn.recv(n)
            elif req[3] == 1:
                conn.recv(4)
            else:
                conn.recv(16)
            conn.recv(2)
            kode = 0x05 if self.tolak else 0x00
            conn.sendall(b"\x05" + bytes([kode]) + b"\x00\x01" + b"\x00" * 6)


def uji_handshake() -> None:
    print("== handshake SOCKS5 ==")
    s = SocksPalsu()
    ok, pesan = px.uji(px.Proxy("127.0.0.1", s.port), timeout=4)
    cek("no-auth lolos", ok, pesan)

    s2 = SocksPalsu(wajib_auth=True)
    ok2, pesan2 = px.uji(px.Proxy("127.0.0.1", s2.port, "u", "p"), timeout=4)
    cek("user/pass lolos", ok2, pesan2)

    s3 = SocksPalsu(wajib_auth=True)
    ok3, pesan3 = px.uji(px.Proxy("127.0.0.1", s3.port), timeout=4)
    cek("menolak saat kredensial kosong", not ok3, pesan3)

    s4 = SocksPalsu(tolak=True)
    ok4, pesan4 = px.uji(px.Proxy("127.0.0.1", s4.port), timeout=4)
    cek("CONNECT ditolak terdeteksi", not ok4 and "CONNECT" in pesan4, pesan4)

    ok5, pesan5 = px.uji(px.Proxy("127.0.0.1", 1), timeout=2)
    cek("port mati -> gagal jelas", not ok5 and pesan5, pesan5)


def main() -> int:
    uji_parse()
    uji_handshake()
    print(f"\n lulus: {LULUS}   gagal: {GAGAL}")
    if GAGAL_NAMA:
        print(" gagal:", ", ".join(GAGAL_NAMA))
    return 1 if GAGAL else 0


if __name__ == "__main__":
    raise SystemExit(main())
