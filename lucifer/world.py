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

Tabel extra mengikuti world_manager Growtopia-PythonBot (tipe 1..81).
Tile dengan item "CBOR" (Party Projector, Auction Block, dst.) menyimpan
`u32 panjang` + blob walau tanpa flag extra.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("lucifer.world")

__all__ = ["Tile", "World", "TILE_FLAGS", "parse_tile_updates"]

# Bit flag tile Growtopia
TILE_FLAGS = {
    "EXTRA_DATA": 0x0001,
    "HAS_PARENT": 0x0002,
    "LOCKED": 0x0002,
    "SPLICED": 0x0004,
    "SEED": 0x0008,
    "SEEDLING": 0x0010,
    "FLIPPED": 0x0020,
    "ROTATED_LEFT": 0x0020,
    "OPEN": 0x0040,
    "PUBLIC": 0x0080,
    "BG_ON": 0x0100,
    "FG_ALT": 0x0200,
    "WATER": 0x0400,
    "GLUE": 0x0800,
    "FIRE": 0x1000,
    "PAINT_RED": 0x2000,
    "PAINT_GREEN": 0x4000,
    "PAINT_BLUE": 0x8000,
    "PAINT_YELLOW": 0x0004,
}

for _name, _val in list(TILE_FLAGS.items()):
    TILE_FLAGS.setdefault(_name.lower(), _val)

# Item yang selalu membawa blok CBOR (u32 panjang + data) setelah extra.
CBOR_IDS = {
    15376,  # Party Projector
    15546,  # Auction Block
    3548,   # Battle Pet Cage
    12598,  # Offering Table
    14662,  # Operating Table
    14666,  # Auto Surgeon Station
    8624, 8630, 8636, 8642, 8648, 8654, 8660, 8666,
    8672, 8678, 8684, 8690, 8696, 8702, 8708, 8714,
}


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

    def i32(self) -> int:
        (v,) = struct.unpack_from("<i", self.buf, self.pos)
        self.pos += 4
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
    seed_age: int = 0
    fruit_count: int = 0
    ready: bool = False
    grow_time: int = 0
    owner_uid: int = 0
    label: str = ""
    raw_extra: bytes = b""

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
    # uid tertinggi yang sudah dipakai server (dari SendMapData). Objek baru
    # dari `ItemChangeObject` tidak membawa uid; klien asli menomori sendiri
    # dengan menaikkan nilai ini.
    last_uid: int = 0
    error: str = ""

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
    """Ubah payload SendMapData menjadi objek World."""
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
        # last_uid = uid tertinggi yang sudah dipakai. Server TIDAK
        # mengirim uid objek baru pada ItemChangeObject; klien asli
        # memakai penghitung ini untuk menomori objek berikutnya.
        # Tanpa nilai ini, autocollect mengirim type 11 dengan uid salah
        # sehingga hanya berhasil untuk objek yang uid-nya diketahui dari
        # SendMapData (yaitu saat baru masuk world) — persis gejalanya.
        w.last_uid = r.u32()
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


def parse_tile_updates(data: bytes, item_db=None) -> list[Tile]:
    """Baca `SendTileUpdateDataMultiple` (Tank type 6).

    Format (diverifikasi dari GrowServer `world/tiles/index.ts:tileUpdateMultiple`):

        diulang:  u32 x, u32 y, <blok tile seperti di SendMapData>
        penutup:  u32 0xFFFFFFFF

    Tiap blok tile panjangnya tidak tetap (tergantung flag extra), jadi
    pembacaan memakai `_read_tile` yang sudah tahu cara melewati extra data.
    Tanpa parser ini, dunia tidak pernah berubah setelah blok pecah/ditaruh —
    autofarm memukul tile yang sama terus dan tidak pernah menaruh blok.
    """
    out: list[Tile] = []
    r = _Reader(data)
    while r.pos + 8 <= len(data):
        x = r.u32()
        y = r.u32()
        if x == 0xFFFFFFFF or y == 0xFFFFFFFF:
            break
        t = _read_tile(r, x, y, item_db)
        out.append(t)
    return out


def _read_tile(r: _Reader, x: int, y: int, item_db) -> Tile:
    t = Tile(x=x, y=y)
    t.fg = r.u16()
    t.bg = r.u16()
    t.parent = r.u16()
    t.flags = r.u16()

    if t.flags & TILE_FLAGS["HAS_PARENT"]:
        r.u16()

    if t.flags & TILE_FLAGS["EXTRA_DATA"]:
        t.extra_type = r.u8()
        _read_extra(r, t, item_db)

    if t.fg in CBOR_IDS:
        n = r.u32()
        t.raw_extra = r.buf[r.pos : r.pos + n]
        r.skip(n)
    return t


def _read_extra(r: _Reader, t: Tile, item_db) -> None:
    """Baca extra data per tipe (1..81)."""
    et = t.extra_type
    if et == 1 or et == 2:  # Sign / Door
        t.label = r.string_u16()
        if et == 1:
            r.u8()
        else:
            r.u32()
    elif et == 3:  # Lock
        r.u8()
        t.owner_uid = r.u32()
        n = r.u32()
        for _ in range(min(n, 4096)):
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
    elif et in (6, 7, 12):  # Mailbox / Bulletin / DonationBox
        t.label = r.string_u16()
        r.string_u16()
        r.string_u16()
        r.u8()
    elif et == 8:  # Dice
        r.u8()
    elif et == 9:  # Chemical source
        t.seed_age = r.u32()
        if item_db is not None:
            item = item_db.get(t.fg)
            t.grow_time = getattr(item, "grow_time", 0) if item else 0
        t.ready = bool(t.grow_time and t.seed_age >= t.grow_time)
        if t.fg == 10656:
            r.skip(4)
    elif et == 10:
        r.u32(); r.u8()
    elif et == 11:
        r.u32(); r.string_u16()
    elif et == 14:  # Mannequin
        t.label = r.string_u16(); r.u8(); r.u32()
        for _ in range(9):
            r.u16()
    elif et == 15:
        r.u32()
    elif et == 16:
        r.u8()
    elif et == 17:
        pass
    elif et == 18:
        r.u8(); r.u32()
    elif et == 19:
        for _ in range(9):
            r.u16()
    elif et == 20:  # Crystal
        t.label = r.string_u16()
    elif et == 21:
        r.string_u16(); r.u32(); r.u8()
    elif et == 22:
        pass
    elif et == 23:
        r.u32()
    elif et == 24:
        r.u32(); r.i32()
    elif et == 25:  # Fish tank port
        r.u8()
        n = r.u32()
        r.skip((n // 2) * 8)
    elif et == 26:
        r.skip(5)
    elif et == 27:
        r.u32()
    elif et == 28:
        r.u16(); r.u32()
    elif et == 30:
        r.u8(); r.u32()
    elif et == 31:  # Silkworm
        r.u8(); r.string_u16()
        for _ in range(4):
            r.u32()
        r.u8()
        for _ in range(4):
            r.u32()
    elif et == 32:
        n = r.u16()
        r.skip(n * 4)
    elif et == 33:
        t.label = r.string_u16()
    elif et == 34:
        pass
    elif et == 35:
        r.u32(); r.string_u16()
    elif et == 36:
        r.string_u16(); r.skip(12)
    elif et == 37:
        r.string_u16()
        n = r.u32()
        r.u32()
        r.skip(n * 4)
    elif et in (38, 39, 40, 41):
        r.u32()
    elif et == 42:
        r.skip(21)
    elif et == 43:
        r.skip(16)
    elif et == 44:
        r.u8(); r.u32()
        n = r.u32()
        r.skip(n * 4)
    elif et == 45:
        pass
    elif et == 47:
        r.string_u16(); r.u32(); r.u8()
    elif et == 48:  # Portrait
        # ksy: u4,u4,5,u1,u2,face,hat,hair,u4 = 26 byte setelah label.
        t.label = r.string_u16()
        r.skip(26)
    elif et == 49:
        r.u32(); r.u32(); r.u8()
    elif et == 50:
        r.u32()
    elif et in (51, 52):
        pass
    elif et == 53:
        r.u32(); r.u32()
    elif et == 54:
        n = r.u16()
        r.skip(n)
    elif et == 55:
        r.u32()
        n = r.u32()
        r.skip(n * 8)
        r.skip(12)
    elif et == 56:
        r.string_u16(); r.u32()
    elif et == 57:
        r.u32()
    elif et in (58, 59):
        pass
    elif et == 60:
        r.u32(); r.u8()
    elif et == 61:
        r.u32(); r.u16()
        for _ in range(4):
            r.u32()
    elif et == 62:  # Item sucker
        r.u32(); r.u32(); r.u16(); r.u32()
    elif et == 63:  # CyBot
        r.u32(); r.u32()
        n = r.u32()
        for _ in range(n):
            r.u32(); r.u32(); r.skip(7)
    elif et == 65:  # Guild item
        r.skip(17)
    elif et == 66:
        r.u8()
    elif et == 67:
        r.u32()
        n = r.u32()
        r.skip(n * 4)
    elif et in (68, 69):
        r.u32(); r.u32(); r.u32()
        if et == 69:
            r.u32()
    elif et == 72:
        for _ in range(3):
            r.u32()
    elif et == 73:
        r.u32()
    elif et == 74:
        pass
    elif et == 75:
        r.u32(); r.u16(); r.u8()
    elif et == 77:
        r.u32()
        n = r.u32()
        r.skip(n * 4)
    elif et == 79:
        pass
    elif et == 80:
        r.u8(); r.u32(); r.u8(); r.u8(); r.u8()
    elif et == 81:
        r.u32(); r.u16(); r.u16()
    else:
        log.debug("extra tile tipe %s belum didukung (fg=%s)", et, t.fg)
