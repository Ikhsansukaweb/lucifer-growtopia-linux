"""
lucifer.world — Pembaca data dunia (world) Growtopia.

Paket `SendMapData` (Tank type 4) berisi serialisasi dunia:

    u16  version          (harus >= 0x19 / 25)
    u32  flags
    u16  nama dunia
    u32  width, height, tile_count
    skip 5
    tile_count x tile     (lihat _read_tile)
    skip 12
    u32  dropped_count
    u32  last_uid
    dropped_count x item
    u16  base_weather, u16 (padding), u16 current_weather

Pembacaan tile mengikuti bit flag Growtopia; tipe extra yang tidak dikenal
TIDAK membuat parsing gagal (dilewati) — ini penting supaya bot tetap jalan
di dunia dengan konten baru.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("lucifer.world")

__all__ = ["Tile", "World", "TILE_FLAGS"]

# Bit flag tile Growtopia
TILE_FLAGS = {
    "EXTRA_DATA": 0x0001,
    "LOCKED": 0x0002,
    "SEED": 0x0008,  # "tree" / tanam
    "FLIPPED": 0x0010,
    "ROTATED_LEFT": 0x0020,
    "OPEN": 0x0040,
    "PUBLIC": 0x0080,
    "SILENCED": 0x0100,
    "WATER": 0x0400,
    "GLUE": 0x0800,
    "FIRE": 0x1000,
    "PAINT_RED": 0x2000,
    "PAINT_GREEN": 0x4000,
    "PAINT_BLUE": 0x8000,
    "PAINT_YELLOW": 0x0004,  # di Growtopia, 0x04 = paint kuning (bit 2)
}

# Alias huruf kecil sesuai gaya API Lucifer: tile:hasFlag(TileFlag.locked)
for _name, _val in list(TILE_FLAGS.items()):
    TILE_FLAGS.setdefault(_name.lower(), _val)


class _Reader:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    def u8(self) -> int:
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        (v,) = struct.unpack_from("<H", self.buf, self.pos)
        self.pos += 2
        return v

    def u32(self) -> int:
        (v,) = struct.unpack_from("<I", self.buf, self.pos)
        self.pos += 4
        return v

    def f32(self) -> float:
        (v,) = struct.unpack_from("<f", self.buf, self.pos)
        self.pos += 4
        return v

    def skip(self, n: int) -> None:
        self.pos += n

    def string_u16(self) -> str:
        n = self.u16()
        s = self.buf[self.pos : self.pos + n]
        self.pos += n
        return s.decode("utf-8", errors="replace")

    @property
    def remaining(self) -> int:
        return len(self.buf) - self.pos


@dataclass
class Tile:
    x: int = 0
    y: int = 0
    fg: int = 0
    bg: int = 0
    parent: int = 0
    flags: int = 0
    extra_type: int = 0
    # data khusus per extra type
    seed_age: int = 0
    fruit_count: int = 0
    ready: bool = False
    grow_time: int = 0
    owner_uid: int = 0
    label: str = ""
    raw_extra: bytes = b""

    # -- flag helpers ------------------------------------------------------ #
    def has(self, name: str) -> bool:
        return bool(self.flags & TILE_FLAGS[name])

    @property
    def has_extra(self) -> bool:
        return bool(self.flags & TILE_FLAGS["EXTRA_DATA"])

    @property
    def is_locked(self) -> bool:
        return bool(self.flags & TILE_FLAGS["LOCKED"])

    @property
    def is_seed(self) -> bool:
        return self.extra_type == 4

    @property
    def empty(self) -> bool:
        return self.fg == 0 and self.bg == 0

    def name(self, item_db=None) -> str:
        if item_db is None:
            return f"#{self.fg}"
        return item_db.name_of(self.fg)

    def __str__(self) -> str:
        return f"Tile({self.x},{self.y} fg={self.fg} bg={self.bg} flags=0x{self.flags:04x} extra={self.extra_type})"


@dataclass
class DroppedItem:
    item_id: int = 0
    x: float = 0.0
    y: float = 0.0
    count: int = 0
    flags: int = 0
    uid: int = 0


@dataclass
class World:
    name: str = ""
    width: int = 0
    height: int = 0
    tiles: list[Tile] = field(default_factory=list)
    dropped: list[DroppedItem] = field(default_factory=list)
    base_weather: int = 0
    current_weather: int = 0
    version: int = 0
    flags: int = 0
    error: str = ""

    # -- akses ------------------------------------------------------------- #
    @property
    def tile_count(self) -> int:
        return self.width * self.height

    def tile(self, x: int, y: int) -> Optional[Tile]:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return None
        idx = y * self.width + x
        return self.tiles[idx] if 0 <= idx < len(self.tiles) else None

    def tile_at_index(self, index: int) -> Optional[Tile]:
        return self.tiles[index] if 0 <= index < len(self.tiles) else None

    def index_of(self, x: int, y: int) -> int:
        return y * self.width + x

    def coords_of(self, index: int) -> tuple[int, int]:
        return index % self.width, index // self.width

    def update_tile(self, index: int, tile: Tile) -> None:
        if 0 <= index < len(self.tiles):
            self.tiles[index] = tile

    # -- pencarian --------------------------------------------------------- #
    def find_items(self, item_id: int) -> list[Tile]:
        return [t for t in self.tiles if t.fg == item_id]

    def find_seeds(self, ready_only: bool = False) -> list[Tile]:
        return [t for t in self.tiles if t.is_seed and (t.ready if ready_only else True)]

    def dropped_of(self, item_id: int) -> list[DroppedItem]:
        return [d for d in self.dropped if d.item_id == item_id]

    def __len__(self) -> int:
        return len(self.tiles)

    def __str__(self) -> str:
        return f"World({self.name!r} {self.width}x{self.height} tiles={len(self.tiles)} dropped={len(self.dropped)})"


def parse_world(data: bytes, item_db=None) -> World:
    """Ubah payload SendMapData menjadi objek World.

    Tidak pernah melempar exception karena tile aneh — kesalahan dicatat di
    `world.error` supaya bot tetap bisa jalan.
    """
    w = World()
    r = _Reader(data)
    try:
        w.version = r.u16()
        if w.version < 25:
            w.error = f"versi dunia terlalu lama: {w.version}"
            return w
        w.flags = r.u32()
        w.name = r.string_u16()
        w.width = r.u32()
        w.height = r.u32()
        declared = r.u32()
        r.skip(5)

        if declared > 0xFE01:
            w.error = f"tile_count tidak wajar: {declared}"
            return w

        w.tiles = []
        for i in range(declared):
            x, y = (i % w.width, i // w.width) if w.width else (0, 0)
            w.tiles.append(_read_tile(r, x, y, item_db))

        r.skip(12)
        n_dropped = r.u32()
        r.u32()  # last uid
        for _ in range(n_dropped):
            w.dropped.append(
                DroppedItem(item_id=r.u16(), x=r.f32(), y=r.f32(), count=r.u8(), flags=r.u8(), uid=r.u32())
            )
        w.base_weather = r.u16()
        r.u16()
        w.current_weather = r.u16()
    except Exception as e:  # noqa: BLE001
        w.error = f"{type(e).__name__}: {e} (offset={r.pos}/{len(data)})"
        log.warning("parse_world gagal: %s", w.error)
    return w


def _read_tile(r: _Reader, x: int, y: int, item_db) -> Tile:
    t = Tile(x=x, y=y)
    t.fg = r.u16()
    t.bg = r.u16()
    t.parent = r.u16()
    t.flags = r.u16()

    if t.flags & TILE_FLAGS["EXTRA_DATA"]:
        t.extra_type = r.u8()
        _read_extra(r, t, item_db)
    return t


def _read_extra(r: _Reader, t: Tile, item_db) -> None:
    """Baca extra data per tipe.

    Tipe yang tidak dikenal dilewati tanpa menghentikan parsing: kita tandai
    saja dan berhenti membaca extra untuk tile ini (sisa byte akan terbaca
    sebagai tile berikutnya — konsekuensi yang diterima, dan tercatat di log).
    """
    et = t.extra_type
    if et == 1:  # Sign
        t.label = r.string_u16()
        r.u8()
    elif et == 2:  # Door
        t.label = r.string_u16()
        r.u32()
    elif et == 3:  # Lock
        r.u8()
        t.owner_uid = r.u32()
        n = r.u32()
        for _ in range(min(n, 512)):
            r.u32()
        r.u8()
        r.skip(7)
        if t.fg == 5814:
            r.skip(16)
    elif et == 4:  # Seed / tanaman
        t.seed_age = r.u32()
        t.fruit_count = r.u8()
        if item_db is not None:
            item = item_db.get(t.fg)
            t.grow_time = getattr(item, "grow_time", 0) if item else 0
        t.ready = bool(t.grow_time and t.seed_age >= t.grow_time)
    elif et == 9:  # Chemical source
        t.seed_age = r.u32()
        if item_db is not None:
            item = item_db.get(t.fg)
            t.grow_time = getattr(item, "grow_time", 0) if item else 0
        t.ready = bool(t.grow_time and t.seed_age >= t.grow_time)
        if t.fg == 10656:
            r.skip(4)
    elif et in (6, 7, 12):  # Mailbox / Bulletin / DonationBox
        t.label = r.string_u16()
        r.string_u16()
        r.string_u16()
        r.u8()
    elif et == 8:  # Dice
        r.u8()
    elif et == 20:  # Crystal
        t.label = r.string_u16()
    elif et == 33:  # CountryFlag
        t.label = r.string_u16()
    else:
        # Tidak dikenal: catat, jangan tebak-tebakan panjang fieldnya.
        log.debug("extra tile tipe %s belum didukung (fg=%s)", et, t.fg)
        t.raw_extra = b""
