"""
lucifer.enet — Binding ENet (ctypes) khusus untuk protokol Growtopia.

Growtopia memakai ENet yang sudah DIPATCH Ubisoft. Tanpa patch ini klien
tidak akan bisa konek (dan server tidak memberi error apa pun — diam saja).
Patch wajib:
  1. enet_host_use_crc32()      -> checksum CRC32
  2. enet_host_use_new_packet() -> format header "new packet" ala Growtopia
  3. enet_host_compress_with_range_coder() -> kompresi range coder
  4. opsional enet_host_use_proxy() untuk SOCKS5

Library .so dibangun dari enet/enet.cpp (single-header enet.h patch).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import struct
import threading
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Optional

__all__ = [
    "ENetAddress",
    "ENetEvent",
    "ENetPacket",
    "ENetEventType",
    "TankPacket",
    "ENetError",
    "ENetHost",
    "TANK_SIZE",
    "load_library",
]

TANK_SIZE = 56  # sizeof(TankPacket) — 3*1 + 4 + 4 + 4 + 4 + 4 + 4*5 + 4 + 4 + 4


class ENetError(RuntimeError):
    """Kegagalan di lapisan ENet."""


# --------------------------------------------------------------------------- #
# Struktur C
# --------------------------------------------------------------------------- #
class TankPacket(ctypes.Structure):
    """Tank packet Growtopia (56 byte, little-endian, tanpa padding)."""

    _pack_ = 1
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("object_type", ctypes.c_uint8),
        ("jump_count", ctypes.c_uint8),
        ("animation_type", ctypes.c_uint8),
        ("net_id", ctypes.c_uint32),
        ("target_net_id", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("float_variable", ctypes.c_float),
        ("value", ctypes.c_uint32),
        ("vector_x", ctypes.c_float),
        ("vector_y", ctypes.c_float),
        ("vector_x2", ctypes.c_float),
        ("vector_y2", ctypes.c_float),
        ("particle_rotation", ctypes.c_float),
        ("int_x", ctypes.c_int32),
        ("int_y", ctypes.c_int32),
        ("extended_data_length", ctypes.c_uint32),
    ]


class _In6Addr(ctypes.Structure):
    _fields_ = [("s6_addr", ctypes.c_ubyte * 16)]


class ENetAddress(ctypes.Structure):
    _fields_ = [
        ("host", _In6Addr),
        ("port", ctypes.c_uint16),
        ("sin6_scope_id", ctypes.c_uint16),
    ]


class ENetPacket(ctypes.Structure):
    _fields_ = [
        ("referenceCount", ctypes.c_size_t),
        ("flags", ctypes.c_uint32),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
        ("dataLength", ctypes.c_size_t),
        ("freeCallback", ctypes.c_void_p),
        ("userData", ctypes.c_void_p),
    ]


class ENetEventType(IntEnum):
    NONE = 0
    CONNECT = 1
    DISCONNECT = 2
    RECEIVE = 3
    DISCONNECT_TIMEOUT = 4


class ENetEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("peer", ctypes.c_void_p),
        ("channelID", ctypes.c_uint8),
        ("data", ctypes.c_uint32),
        ("packet", ctypes.POINTER(ENetPacket)),
    ]


# --------------------------------------------------------------------------- #
# Pemuatan library
# --------------------------------------------------------------------------- #
_LIB_LOCK = threading.Lock()
_LIB: Optional[ctypes.CDLL] = None
_LIB_PATH: Optional[str] = None

_EXT = {"Windows": ".dll", "Darwin": ".dylib"}.get(platform.system(), ".so")


def _candidate_paths() -> list[str]:
    here = Path(__file__).resolve().parent
    root = here.parent
    cands = [
        os.environ.get("LUCIFER_ENET_LIB", ""),
        str(root / "enet" / f"enet{_EXT}"),
        str(root / "enet" / f"libenet{_EXT}"),
        str(here / f"enet{_EXT}"),
        ctypes.util.find_library("enet") or "",
    ]
    return [c for c in cands if c]


def _bind(lib: ctypes.CDLL) -> None:
    def sig(name, argtypes, restype):
        fn = getattr(lib, name, None)
        if fn is None:
            raise ENetError(
                f"Simbol '{name}' tidak ada di library ENet. "
                "Library-nya bukan versi patch Growtopia — build ulang dengan "
                "`make` (lihat README)."
            )
        fn.argtypes = argtypes
        fn.restype = restype
        return fn

    g = globals()
    vp = ctypes.c_void_p

    g["enet_initialize"] = sig("enet_initialize", [], ctypes.c_int)
    g["enet_deinitialize"] = sig("enet_deinitialize", [], None)
    g["enet_host_create"] = sig(
        "enet_host_create", [vp, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32], vp
    )
    g["enet_host_destroy"] = sig("enet_host_destroy", [vp], None)
    g["enet_host_service"] = sig("enet_host_service", [vp, ctypes.POINTER(ENetEvent), ctypes.c_uint32], ctypes.c_int)
    g["enet_host_flush"] = sig("enet_host_flush", [vp], None)
    g["enet_host_use_crc32"] = sig("enet_host_use_crc32", [vp], None)
    g["enet_host_use_new_packet"] = sig("enet_host_use_new_packet", [vp], None)
    g["enet_host_compress_with_range_coder"] = sig("enet_host_compress_with_range_coder", [vp], ctypes.c_int)
    g["enet_address_set_host"] = sig("enet_address_set_host", [ctypes.POINTER(ENetAddress), ctypes.c_char_p], ctypes.c_int)
    g["enet_host_connect"] = sig("enet_host_connect", [vp, ctypes.POINTER(ENetAddress), ctypes.c_size_t, ctypes.c_uint32], vp)
    g["enet_peer_disconnect"] = sig("enet_peer_disconnect", [vp, ctypes.c_uint32], None)
    g["enet_peer_disconnect_now"] = sig("enet_peer_disconnect_now", [vp, ctypes.c_uint32], None)
    g["enet_peer_reset"] = sig("enet_peer_reset", [vp], None)
    g["enet_peer_send"] = sig("enet_peer_send", [vp, ctypes.c_uint8, ctypes.POINTER(ENetPacket)], ctypes.c_int)
    g["enet_packet_create"] = sig("enet_packet_create", [vp, ctypes.c_size_t, ctypes.c_uint32], ctypes.POINTER(ENetPacket))
    g["enet_packet_destroy"] = sig("enet_packet_destroy", [ctypes.POINTER(ENetPacket)], None)
    g["enet_peer_get_ping"] = sig("enet_peer_get_ping", [vp], ctypes.c_uint32)

    # opsional
    if hasattr(lib, "enet_host_use_proxy"):
        fn = lib.enet_host_use_proxy
        fn.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint16, ctypes.c_char_p, ctypes.c_char_p]
        fn.restype = None
        g["enet_host_use_proxy"] = fn

    # konstanta
    g["ENET_PACKET_FLAG_RELIABLE"] = 1
    g["ENET_PACKET_FLAG_UNSEQUENCED"] = 2
    g["ENET_PACKET_FLAG_UNRELIABLE_FRAGMENT"] = 8


def load_library(path: Optional[str] = None) -> ctypes.CDLL:
    """Muat (sekali) library ENet patch Growtopia. Sekaligus enet_initialize()."""
    global _LIB, _LIB_PATH
    with _LIB_LOCK:
        if _LIB is not None and path is None:
            return _LIB

        tried: list[str] = []
        for cand in ([path] if path else _candidate_paths()):
            if not cand:
                continue
            tried.append(cand)
            if not os.path.exists(cand) and not cand.startswith("lib"):
                continue
            try:
                lib = ctypes.CDLL(cand)
            except OSError:
                continue
            _bind(lib)
            if lib.enet_initialize() != 0:
                raise ENetError("enet_initialize() gagal")
            _LIB, _LIB_PATH = lib, cand
            return lib

        raise ENetError(
            "Library ENet patch Growtopia tidak ditemukan.\n"
            f"Sudah dicoba: {tried}\n"
            "Perbaiki dengan:  make -C <folder lucifer-linux>  "
            "(atau set LUCIFER_ENET_LIB=/path/ke/enet.so)"
        )


def library_path() -> Optional[str]:
    """Path library ENet yang sedang dipakai (memuat lebih dulu bila perlu)."""
    if _LIB is None:
        try:
            load_library()
        except ENetError:
            return None
    return _LIB_PATH


# --------------------------------------------------------------------------- #
# Pembungkus tingkat tinggi
# --------------------------------------------------------------------------- #
@dataclass
class Received:
    """Hasil terjemahan ENetEvent menjadi objek Python biasa."""

    kind: str  # "connect" | "disconnect" | "receive" | "timeout" | "none"
    data: bytes = b""
    channel: int = 0


class ENetHost:
    """Klien ENet 1-peer, sudah dipatch untuk Growtopia.

    Pemakaian:
        host = ENetHost()
        host.connect("213.179.209.175", 17047)
        ev = host.service(timeout_ms=1000)
        if ev.kind == "receive": ...
    """

    def __init__(
        self,
        channels: int = 2,
        proxy: Optional[tuple[str, int, str, str]] = None,
        use_crc32: bool = True,
        use_new_packet: bool = True,
        use_range_coder: bool = True,
    ) -> None:
        self.lib = load_library()
        self._lock = threading.RLock()
        self._event = ENetEvent()
        self.connected = False
        self.peer = None
        self.address: Optional[tuple[str, int]] = None

        self.host = self.lib.enet_host_create(None, 1, channels, 0, 0)
        if not self.host:
            raise ENetError("enet_host_create() gagal (host NULL)")

        if use_new_packet:
            self.lib.enet_host_use_new_packet(self.host)
        if use_crc32:
            self.lib.enet_host_use_crc32(self.host)
        if use_range_coder:
            rc = self.lib.enet_host_compress_with_range_coder(self.host)
            if rc != 0:
                raise ENetError(f"compress_with_range_coder gagal (rc={rc})")
        if proxy and "enet_host_use_proxy" in dir(self.lib):
            ip, port, user, pwd = proxy
            self.lib.enet_host_use_proxy(
                self.host, ip.encode(), port, user.encode(), pwd.encode()
            )

    # -- koneksi ----------------------------------------------------------- #
    def connect(self, host: str, port: int, timeout_ms: int = 5000) -> bool:
        """Connect + tunggu event CONNECT. Return True kalau tersambung."""
        with self._lock:
            addr = ENetAddress()
            if self.lib.enet_address_set_host(ctypes.byref(addr), host.encode()) != 0:
                raise ENetError(f"Tidak bisa resolve/assign host {host!r}")
            addr.port = int(port)
            self.peer = self.lib.enet_host_connect(self.host, ctypes.byref(addr), 2, 0)
            if not self.peer:
                raise ENetError("enet_host_connect() mengembalikan NULL")
            self.address = (host, int(port))

            ev = self.service(timeout_ms)
            if ev.kind == "connect":
                self.connected = True
                return True
            return False

    # -- I/O --------------------------------------------------------------- #
    def service(self, timeout_ms: int = 1000) -> Received:
        """Tunggu satu event ENet dan terjemahkan ke objek Python."""
        with self._lock:
            rc = self.lib.enet_host_service(self.host, ctypes.byref(self._event), int(timeout_ms))
            if rc <= 0:
                return Received("none")
            ev = self._event
            if ev.type == ENetEventType.CONNECT:
                return Received("connect", channel=ev.channelID)
            if ev.type == ENetEventType.DISCONNECT:
                self.connected = False
                return Received("disconnect", channel=ev.channelID)
            if ev.type == ENetEventType.DISCONNECT_TIMEOUT:
                self.connected = False
                return Received("timeout", channel=ev.channelID)
            if ev.type == ENetEventType.RECEIVE:
                pkt = ev.packet.contents
                data = ctypes.string_at(pkt.data, pkt.dataLength)
                self.lib.enet_packet_destroy(ev.packet)
                return Received("receive", data=data, channel=ev.channelID)
            return Received("none")

    def send(self, data: bytes, reliable: bool = True) -> bool:
        """Kirim data mentah ke peer (channel 0)."""
        with self._lock:
            if not self.peer:
                raise ENetError("Belum connect — peer NULL")
            buf = ctypes.create_string_buffer(data, len(data))
            flags = ENET_PACKET_FLAG_RELIABLE if reliable else 0
            pkt = self.lib.enet_packet_create(buf, len(data), flags)
            if not pkt:
                raise ENetError("enet_packet_create() gagal")
            rc = self.lib.enet_peer_send(self.peer, 0, pkt)
            self.lib.enet_host_flush(self.host)
            if rc < 0:
                self.lib.enet_packet_destroy(pkt)
                return False
            return True

    # -- util -------------------------------------------------------------- #
    @property
    def ping(self) -> int:
        if not self.peer:
            return 0
        return int(self.lib.enet_peer_get_ping(self.peer))

    def disconnect(self, graceful: bool = True, wait_ms: int = 3000) -> None:
        with self._lock:
            if not self.peer:
                return
            if graceful:
                self.lib.enet_peer_disconnect(self.peer, 0)
                deadline = wait_ms
                while deadline > 0:
                    ev = self.service(200)
                    deadline -= 200
                    if ev.kind in ("disconnect", "timeout"):
                        break
            else:
                self.lib.enet_peer_disconnect_now(self.peer, 0)
            self.peer = None
            self.connected = False

    def close(self) -> None:
        with self._lock:
            try:
                if self.peer:
                    self.lib.enet_peer_disconnect_now(self.peer, 0)
            except Exception:
                pass
            if self.host:
                self.lib.enet_host_destroy(self.host)
                self.host = None
            self.peer = None
            self.connected = False

    def __enter__(self) -> "ENetHost":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def probe(host: str, port: int, timeout_ms: int = 5000) -> dict:
    """Cek cepat: bisakah connect ke host:port pakai ENet patch Growtopia?"""
    h = ENetHost()
    try:
        ok = h.connect(host, port, timeout_ms)
        return {"host": host, "port": port, "connected": ok, "ping": h.ping}
    finally:
        h.close()
