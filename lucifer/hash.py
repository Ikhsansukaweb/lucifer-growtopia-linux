"""
lucifer.hash — Fungsi hash Growtopia (mirror dari implementasi C++ klien).

Dua fungsi penting:
  * hash_gt()  -> hash "rotasi" 32-bit yang dipakai untuk `hash`, `hash2`,
                  dan untuk verifikasi checksum items.dat.
  * sha256/md5 -> dipakai untuk membangun `klv` (key-length-value salt).

Semua sudah diuji dan hasilnya deterministik (lihat tests/test_hash.py).
"""

from __future__ import annotations

import ctypes
import hashlib
from enum import IntEnum

__all__ = ["HashMode", "hash_gt", "sha256", "md5", "generate_klv", "random_hex", "random_mac"]


class HashMode(IntEnum):
    FixedLength = 0
    NullTerminated = 1


def hash_gt(data: bytes | bytearray, mode: HashMode = HashMode.NullTerminated, length: int = 0) -> int:
    """Hash 32-bit khas Growtopia (dipakai untuk `hash`, `hash2`, items.dat).

    Algoritma asli (C++):
        uint32 h = 0x55555555;
        for (i = 0; i < n; i++) h = data[i] + (h >> 27) + (h << 5);
    """
    h = ctypes.c_uint32(0x55555555)

    if mode == HashMode.FixedLength:
        n = min(length or len(data), len(data))
        seq = data[:n]
    else:  # NullTerminated — berhenti di byte 0
        seq = []
        for b in data:
            if b == 0:
                break
            seq.append(b)

    for b in seq:
        h.value = (b + (h.value >> 27) + (h.value << 5)) & 0xFFFFFFFF
    return h.value


def sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def md5(text: str) -> str:
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()


# Empat konstanta dari implementasi resmi `generateKlv` klien Growtopia
# (lihat proxy Growtopia/GTProxy: utils.c -> generateKlv).
KLV_SECRETS = (
    "198c4213effdbeb93ca64ea73c1f505f",
    "82a2e2940dd1b100f0d41d23b0bb6e4d",
    "c64f7f09cdd0c682e730d2f936f36ac2",
    "27d8da6190880ce95591215f2c9976a6",
)

SECRET_KLV = KLV_SECRETS  # nama lama, dipertahankan untuk kompatibilitas


def generate_klv(
    game_version: str = "5.58",
    hash_: str = "",
    rid: str = "",
    protocol: str | int = 225,
) -> str:
    """Bangun nilai `klv` yang diminta server saat login.

    Rumus persis dari implementasi resmi klien Growtopia:

        klv = sha256(
                  sha256(gameVersion) + SECRET[0]
                + sha256(hash)        + SECRET[1]
                + sha256(protocol)    + SECRET[2]
                + sha256(rid)         + SECRET[3]
              )

    Urutan argumen mengikuti fungsi aslinya
    `generateKlv(gameVersion, hash, rid, protocol)`.
    """
    combined = (
        sha256(str(game_version)) + KLV_SECRETS[0]
        + sha256(str(hash_)) + KLV_SECRETS[1]
        + sha256(str(protocol)) + KLV_SECRETS[2]
        + sha256(str(rid)) + KLV_SECRETS[3]
    )
    return sha256(combined)


import random as _random


def random_hex(length: int, uppercase: bool = False) -> str:
    s = "".join(_random.choice("0123456789abcdef") for _ in range(length))
    return s.upper() if uppercase else s


def random_mac() -> str:
    return ":".join(random_hex(2) for _ in range(6))
