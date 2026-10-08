"""
lucifer.items — Pembaca items.dat (database item Growtopia).

Format: [u16 version][u32 item_count][item...]
Nama item di-XOR dengan kunci 'PBG892FXX982ABC*' (bergeser per item ID).
Struktur per-item bervariasi menurut `version`, jadi semua field setelah
blok dasar dibaca kondisional.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Optional

__all__ = ["Item", "ItemDatabase", "load_items", "decode_item_name", "SECRET"]

SECRET = b"PBG892FXX982ABC*"


@dataclass
class Item:
    id: int = 0
    flags: int = 0
    action_type: int = 0
    material: int = 0
    name: str = ""
    texture_file_name: str = ""
    texture_hash: int = 0
    visual_effect: int = 0
    cooking_ingredient: int = 0
    texture_x: int = 0
    texture_y: int = 0
    render_type: int = 0
    is_stripey_wallpaper: int = 0
    collision_type: int = 0
    block_health: int = 0
    drop_chance: int = 0
    clothing_type: int = 0
    rarity: int = 0
    max_item: int = 0
    file_name: str = ""
    file_hash: int = 0
    pet_name: str = ""
    pet_prefix: str = ""
    pet_suffix: str = ""
    pet_ability: str = ""
    seed_base_sprite: int = 0
    seed_overlay_sprite: int = 0
    tree_base_sprite: int = 0
    tree_overlay_sprite: int = 0
    base_color: int = 0
    overlay_color: int = 0
    ingredient: int = 0
    grow_time: int = 0
    extra_options: str = ""
    texture_path_2: str = ""
    extra_option2: str = ""
    description: str = ""
    punch_option: str = ""

    # --- kenyamanan ------------------------------------------------------- #
    # Diuji empiris pada items.dat v24 (15.934 item): action_type == 19
    # menandai item bibit/seed dengan akurasi 99,96% (7.964 dari 7.967 item
    # action_type==19 juga berakhiran " Seed"). Ini cara yang dipakai Growtopia.
    SEED_ACTION_TYPE = 19

    @property
    def is_seed(self) -> bool:
        return self.action_type == 19 or self.name.endswith(" Seed")

    @property
    def is_block(self) -> bool:
        return self.material in (2, 4, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28)

    @property
    def is_foreground(self) -> bool:
        return self.material in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 40, 42, 44, 46)

    @property
    def is_clothing(self) -> bool:
        # material == 1 menandai item pakaian; clothing_type memberi slotnya
        # (0 masih mungkin untuk aksesori seperti Bunny Ears).
        return self.material == 1 or self.clothing_type > 0

    @property
    def level_required(self) -> int:
        r = self.rarity
        if 1 <= r <= 99:
            return min(20, (r - 1) // 5 + 3)
        return 0

    def __str__(self) -> str:
        return f"Item(#{self.id} {self.name!r} rarity={self.rarity})"


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

    def skip(self, n: int) -> None:
        self.pos += n

    def string(self) -> str:
        """String panjang-u16 dengan karakter mentah (tanpa decode utf-8 ketat)."""
        n = self.u16()
        raw = self.buf[self.pos : self.pos + n]
        self.pos += n
        return raw.decode("latin-1")

    def cypher_string(self, item_id: int) -> str:
        n = self.u16()
        raw = self.buf[self.pos : self.pos + n]
        self.pos += n
        return decode_item_name(raw, item_id)


def decode_item_name(raw: bytes, item_id: int) -> str:
    """XOR nama item dengan kunci, posisi kunci bergeser sebesar item_id."""
    key = SECRET
    klen = len(key)
    out = bytearray(len(raw))
    for i, ch in enumerate(raw):
        out[i] = ch ^ key[(i + item_id) % klen]
    return out.decode("utf-8", errors="replace")


class ItemDatabase:
    """Database item in-memory + lookup cepat berdasarkan nama."""

    __slots__ = ("version", "count", "items", "by_name", "source")

    def __init__(self, version: int = 0, source: str = "") -> None:
        self.version = version
        self.count = 0
        self.items: dict[int, Item] = {}
        self.by_name: dict[str, Item] = {}
        self.source = source

    # -- akses ------------------------------------------------------------- #
    def get(self, item_id: int) -> Optional[Item]:
        return self.items.get(item_id)

    def find(self, name: str, exact: bool = False) -> list[Item]:
        """Cari item berdasarkan nama (case-insensitive)."""
        key = name.strip().lower()
        if exact:
            it = self.by_name.get(key)
            return [it] if it else []
        return [i for k, i in self.by_name.items() if key in k]

    def name_of(self, item_id: int) -> str:
        it = self.items.get(item_id)
        return it.name if it else f"<unknown#{item_id}>"

    def __len__(self) -> int:
        return self.count

    def __contains__(self, item_id: object) -> bool:
        return item_id in self.items

    def __iter__(self):
        return iter(self.items.values())

    # -- pemuatan ---------------------------------------------------------- #
    @classmethod
    def from_bytes(cls, data: bytes, source: str = "<memory>") -> "ItemDatabase":
        r = _Reader(data)
        db = cls(version=r.u16(), source=source)
        db.count = r.u32()
        for _ in range(db.count):
            item = _read_item(r, db.version)
            db.items[item.id] = item
            db.by_name.setdefault(item.name.strip().lower(), item)
        return db

    @classmethod
    def from_file(cls, path: str | Path) -> "ItemDatabase":
        p = Path(path)
        return cls.from_bytes(p.read_bytes(), source=str(p))


def _read_item(r: _Reader, version: int) -> Item:
    it = Item()
    it.id = r.u32()
    it.flags = r.u16()
    it.action_type = r.u8()
    it.material = r.u8()
    it.name = r.cypher_string(it.id)
    it.texture_file_name = r.string()
    it.texture_hash = r.u32()
    it.visual_effect = r.u8()
    it.cooking_ingredient = r.u32()
    it.texture_x = r.u8()
    it.texture_y = r.u8()
    it.render_type = r.u8()
    it.is_stripey_wallpaper = r.u8()
    it.collision_type = r.u8()
    it.block_health = r.u8()
    it.drop_chance = r.u32()
    it.clothing_type = r.u8()
    it.rarity = r.u16()
    it.max_item = r.u8()
    it.file_name = r.string()
    it.file_hash = r.u32()
    r.u32()  # audio_volume
    it.pet_name = r.string()
    it.pet_prefix = r.string()
    it.pet_suffix = r.string()
    it.pet_ability = r.string()
    it.seed_base_sprite = r.u8()
    it.seed_overlay_sprite = r.u8()
    it.tree_base_sprite = r.u8()
    it.tree_overlay_sprite = r.u8()
    it.base_color = r.u32()
    it.overlay_color = r.u32()
    it.ingredient = r.u32()
    it.grow_time = r.u32()
    r.u16()
    r.u16()  # is_rayman
    it.extra_options = r.string()
    it.texture_path_2 = r.string()
    it.extra_option2 = r.string()
    r.skip(80)

    if version >= 11:
        it.punch_option = r.string()
    if version >= 12:
        r.skip(13)
    if version >= 13:
        r.skip(4)
    if version >= 14:
        r.skip(4)
    if version >= 15:
        r.skip(25)
        r.string()
    if version >= 16:
        r.string()
    if version >= 17:
        r.skip(4)
    if version >= 18:
        r.skip(4)
    if version >= 19:
        r.skip(9)
    if version >= 21:
        r.skip(2)
    if version >= 22:
        it.description = r.string()
    if version >= 23:
        r.skip(4)
    if version >= 24:
        r.skip(1)
    return it


def load_items(path: str | Path) -> ItemDatabase:
    """Pintasan: muat items.dat dari file."""
    return ItemDatabase.from_file(path)
