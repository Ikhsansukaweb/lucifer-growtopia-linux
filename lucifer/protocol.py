"""
lucifer.protocol — Konstanta + codec protokol Growtopia.

Format paket (setelah header ENet):
    [4 byte little-endian: tipe pesan] [payload]

Tipe pesan:
    1  ServerHello   (server -> klien, meminta kredensial)
    2  GenericText   (teks `key|value\\n`) — dua arah
    3  GameMessage   (teks `action|...\\n`) — dua arah
    4  GamePacket    (TankPacket 56 byte + extended data)
    5  Error
    6  Track
    7  ClientLogRequest

Semua string Growtopia memakai pemisah '|' dan baris '\\n'.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

from .enet import TANK_SIZE, TankPacket

__all__ = [
    "NetMessage",
    "NetGamePacket",
    "Tank",
    "Variant",
    "VariantList",
    "TextPacket",
    "decode_text",
    "encode_text",
    "remove_color",
    "build_packet",
    "parse_packet",
    "pack_tank",
    "unpack_tank",
    "VARIANT_FLOAT",
    "VARIANT_STRING",
    "VARIANT_VEC2",
    "VARIANT_VEC3",
    "VARIANT_UNSIGNED",
    "VARIANT_SIGNED",
]


class NetMessage(IntEnum):
    Unknown = 0
    ServerHello = 1
    GenericText = 2
    GameMessage = 3
    GamePacket = 4
    Error = 5
    Track = 6
    ClientLogRequest = 7
    ClientLogResponse = 8


class NetGamePacket(IntEnum):
    State = 0
    CallFunction = 1
    UpdateStatus = 2
    TileChangeRequest = 3
    SendMapData = 4
    SendTileUpdateData = 5
    SendTileUpdateDataMultiple = 6
    TileActivateRequest = 7
    TileApplyDamage = 8
    SendInventoryState = 9
    ItemActivateRequest = 10
    ItemActivateObjectRequest = 11
    SendTileTreeState = 12
    ModifyItemInventory = 13
    ItemChangeObject = 14
    SendLock = 15
    SendItemDatabaseData = 16
    SendParticleEffect = 17
    SetIconState = 18
    ItemEffect = 19
    SetCharacterState = 20
    PingReply = 21
    PingRequest = 22
    GotPunched = 23
    AppCheckResponse = 24
    AppIntegrityFail = 25
    Disconnect = 26
    BattleJoin = 27
    BattleEvent = 28
    UseDoor = 29
    SendParental = 30
    GoneFishin = 31
    Steam = 32
    PetBattle = 33
    Npc = 34
    Special = 35
    SendParticleEffectV2 = 36
    ActivateArrowToItem = 37
    SelectTileIndex = 38
    SendPlayerTributeData = 39
    FTUESetItemToQuickInventory = 40
    PVENpc = 41
    PVPCardBattle = 42
    PVEApplyPlayerDamage = 43
    PVENPCPositionUpdate = 44
    SetExtraMods = 45
    OnStepTileMod = 46


# --------------------------------------------------------------------------- #
# Tank packet
# --------------------------------------------------------------------------- #
@dataclass
class Tank:
    """TankPacket versi Python — mudah dibaca/ditulis dan diserialisasi."""

    type: int = 0
    object_type: int = 0
    jump_count: int = 0
    animation_type: int = 0
    net_id: int = 0
    target_net_id: int = 0
    flags: int = 0
    float_variable: float = 0.0
    value: int = 0
    vector_x: float = 0.0
    vector_y: float = 0.0
    vector_x2: float = 0.0
    vector_y2: float = 0.0
    particle_rotation: float = 0.0
    int_x: int = 0
    int_y: int = 0
    extended_data_length: int = 0

    def to_bytes(self, extended: bytes = b"") -> bytes:
        t = TankPacket(
            type=self.type & 0xFF,
            object_type=self.object_type & 0xFF,
            jump_count=self.jump_count & 0xFF,
            animation_type=self.animation_type & 0xFF,
            net_id=self.net_id & 0xFFFFFFFF,
            target_net_id=self.target_net_id,
            flags=self.flags & 0xFFFFFFFF,
            float_variable=float(self.float_variable),
            value=self.value & 0xFFFFFFFF,
            vector_x=float(self.vector_x),
            vector_y=float(self.vector_y),
            vector_x2=float(self.vector_x2),
            vector_y2=float(self.vector_y2),
            particle_rotation=float(self.particle_rotation),
            int_x=int(self.int_x),
            int_y=int(self.int_y),
            extended_data_length=len(extended),
        )
        return bytes(t) + extended

    @classmethod
    def from_bytes(cls, raw: bytes) -> tuple["Tank", bytes]:
        if len(raw) < TANK_SIZE:
            raise ValueError(f"Tank packet terlalu pendek: {len(raw)} < {TANK_SIZE}")
        t = TankPacket.from_buffer_copy(raw[:TANK_SIZE])
        ext_len = t.extended_data_length
        ext = raw[TANK_SIZE : TANK_SIZE + ext_len]
        obj = cls(
            type=t.type,
            object_type=t.object_type,
            jump_count=t.jump_count,
            animation_type=t.animation_type,
            net_id=t.net_id,
            target_net_id=t.target_net_id,
            flags=t.flags,
            float_variable=t.float_variable,
            value=t.value,
            vector_x=t.vector_x,
            vector_y=t.vector_y,
            vector_x2=t.vector_x2,
            vector_y2=t.vector_y2,
            particle_rotation=t.particle_rotation,
            int_x=t.int_x,
            int_y=t.int_y,
            extended_data_length=ext_len,
        )
        return obj, ext


def pack_tank(tank: Tank, extended: bytes = b"") -> bytes:
    return tank.to_bytes(extended)


def unpack_tank(raw: bytes) -> tuple[Tank, bytes]:
    return Tank.from_bytes(raw)


# --------------------------------------------------------------------------- #
# Teks (GenericText / GameMessage)
# --------------------------------------------------------------------------- #
def decode_text(payload: bytes) -> dict[str, str]:
    """Ubah payload teks `key|value\\n...` menjadi dict.

    Baris tanpa '|' disimpan sebagai key dengan value "".
    Kunci duplikat ditimpa (perilaku sama seperti klien).

    Catatan: server Growtopia kadang mengirim NUL (`\\x00`) di akhir nilai
    (mis. `msg|Fail to login...\\x00`). NUL itu dibuang supaya pesan enak
    dibaca dan bisa dicocokkan pola.
    """
    text = payload.decode("utf-8", errors="replace")
    # Buang NUL dan karakter kontrol lain (server kadang menempelkannya di
    # akhir nilai, mis. "Fail to login...\x00)" sehingga pesan jadi kotor).
    text = "".join(c for c in text if c >= " " or c == "\n")
    out: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip("\r")
        if not line:
            continue
        idx = line.find("|")
        if idx < 0:
            out[line.strip()] = ""
        else:
            out[line[:idx].strip()] = line[idx + 1 :].strip()
    return out


def encode_text(fields: dict[str, Any]) -> bytes:
    """Bangun payload teks dari dict (urutan dipertahankan)."""
    return ("\n".join(f"{k}|{v}" for k, v in fields.items()) + "\n").encode("utf-8")


# Kode warna Growtopia: backtick + satu karakter (`4 merah, `c, `#, `w, `o ...).
_COLOR_RE = re.compile(r"`[a-zA-Z0-9#]")


def remove_color(text: str) -> str:
    """Buang kode warna Growtopia dari teks (`` `4Fail to login... `` -> ``Fail to login... ``).

    Ini versi tanpa-dependensi di `protocol.py` supaya lapisan bot/console bisa
    memakainya tanpa memuat runtime Lua (`lupa`). `lua_api.remove_color`
    tetap ada untuk dipakai dari skrip Lua.
    """
    return _COLOR_RE.sub("", str(text))


class TextPacket(dict):
    """dict teks dengan helper .action dan .raw."""

    @property
    def action(self) -> str:
        return self.get("action", "")

    @property
    def raw(self) -> str:
        return "\n".join(f"{k}|{v}" for k, v in self.items()) + "\n"

    def __repr__(self) -> str:  # pragma: no cover
        return f"TextPacket({dict(self)!r})"


# --------------------------------------------------------------------------- #
# Variant list (CallFunction)
# --------------------------------------------------------------------------- #
VARIANT_UNKNOWN = 0
VARIANT_FLOAT = 1
VARIANT_STRING = 2
VARIANT_VEC2 = 3
VARIANT_VEC3 = 4
VARIANT_UNSIGNED = 5
VARIANT_SIGNED = 9


@dataclass
class Variant:
    kind: int
    value: Any

    # -- pembuat (dipakai juga oleh modul lain & uji) ---------------------- #
    @classmethod
    def from_string(cls, text: str) -> "Variant":
        return cls(VARIANT_STRING, str(text))

    @classmethod
    def from_int(cls, number: int) -> "Variant":
        return cls(VARIANT_SIGNED, int(number))

    @classmethod
    def from_uint(cls, number: int) -> "Variant":
        return cls(VARIANT_UNSIGNED, int(number))

    @classmethod
    def from_float(cls, number: float) -> "Variant":
        return cls(VARIANT_FLOAT, float(number))

    @classmethod
    def from_vec2(cls, x: float, y: float) -> "Variant":
        return cls(VARIANT_VEC2, (float(x), float(y)))

    @classmethod
    def from_vec3(cls, x: float, y: float, z: float) -> "Variant":
        return cls(VARIANT_VEC3, (float(x), float(y), float(z)))

    def as_string(self) -> str:
        return str(self.value) if self.value is not None else ""

    def as_float(self) -> float:
        try:
            return float(self.value)
        except (TypeError, ValueError):
            return 0.0

    def as_int32(self) -> int:
        try:
            return int(self.value)
        except (TypeError, ValueError):
            return 0

    def as_uint32(self) -> int:
        return self.as_int32() & 0xFFFFFFFF

    def as_vec2(self) -> tuple[float, float]:
        if isinstance(self.value, (tuple, list)) and len(self.value) >= 2:
            return float(self.value[0]), float(self.value[1])
        return 0.0, 0.0

    def as_vec3(self) -> tuple[float, float, float]:
        if isinstance(self.value, (tuple, list)) and len(self.value) >= 3:
            return float(self.value[0]), float(self.value[1]), float(self.value[2])
        return 0.0, 0.0, 0.0


@dataclass
class VariantList:
    variants: list[Variant] = field(default_factory=list)

    # -- akses ------------------------------------------------------------- #
    def __len__(self) -> int:
        return len(self.variants)

    def append(self, variant: Variant) -> Variant:
        """Tambah satu Variant ke daftar (dipakai saat membangun paket)."""
        self.variants.append(variant)
        return variant

    def extend(self, variants: list[Variant]) -> None:
        self.variants.extend(variants)

    def __getitem__(self, i: int) -> Variant:
        return self.variants[i]

    def get(self, i: int, default: Optional[Variant] = None) -> Optional[Variant]:
        return self.variants[i] if 0 <= i < len(self.variants) else default

    def func_name(self) -> str:
        return self.variants[0].as_string() if self.variants else ""

    # -- serialisasi ------------------------------------------------------- #
    @classmethod
    def deserialize(cls, data: bytes) -> "VariantList":
        if not data:
            raise ValueError("VariantList: data kosong")
        vl = cls()
        off = 1  # byte pertama = jumlah variant (dipakai server, tidak wajib cocok)
        n_declared = data[0]
        while off + 2 <= len(data) and len(vl.variants) < n_declared:
            off += 1  # index variant (diabaikan)
            vtype = data[off]
            off += 1
            if vtype == VARIANT_FLOAT:
                (v,) = struct.unpack_from("<f", data, off)
                off += 4
                vl.variants.append(Variant(vtype, v))
            elif vtype == VARIANT_STRING:
                (slen,) = struct.unpack_from("<I", data, off)
                off += 4
                vl.variants.append(Variant(vtype, data[off : off + slen].decode("utf-8", "replace")))
                off += slen
            elif vtype == VARIANT_VEC2:
                x, y = struct.unpack_from("<ff", data, off)
                off += 8
                vl.variants.append(Variant(vtype, (x, y)))
            elif vtype == VARIANT_VEC3:
                x, y, z = struct.unpack_from("<fff", data, off)
                off += 12
                vl.variants.append(Variant(vtype, (x, y, z)))
            elif vtype == VARIANT_UNSIGNED:
                (v,) = struct.unpack_from("<I", data, off)
                off += 4
                vl.variants.append(Variant(vtype, v))
            elif vtype == VARIANT_SIGNED:
                (v,) = struct.unpack_from("<i", data, off)
                off += 4
                vl.variants.append(Variant(vtype, v))
            else:
                vl.variants.append(Variant(vtype, None))
                break
        return vl

    def serialize(self) -> bytes:
        out = bytearray([len(self.variants)])
        for i, v in enumerate(self.variants):
            out.append(i & 0xFF)
            out.append(v.kind)
            if v.kind == VARIANT_FLOAT:
                out += struct.pack("<f", float(v.value))
            elif v.kind == VARIANT_STRING:
                raw = str(v.value).encode("utf-8")
                out += struct.pack("<I", len(raw)) + raw
            elif v.kind == VARIANT_VEC2:
                x, y = v.value
                out += struct.pack("<ff", float(x), float(y))
            elif v.kind == VARIANT_VEC3:
                x, y, z = v.value
                out += struct.pack("<fff", float(x), float(y), float(z))
            elif v.kind == VARIANT_UNSIGNED:
                out += struct.pack("<I", int(v.value) & 0xFFFFFFFF)
            elif v.kind == VARIANT_SIGNED:
                out += struct.pack("<i", int(v.value))
        return bytes(out)


# --------------------------------------------------------------------------- #
# Bingkai paket
# --------------------------------------------------------------------------- #
def build_packet(msg_type: int, payload: bytes = b"") -> bytes:
    """Bungkus payload dengan 4-byte tipe pesan."""
    return struct.pack("<I", int(msg_type) & 0xFFFFFFFF) + payload


def parse_packet(data: bytes) -> tuple[int, bytes]:
    """Pisahkan bingkai paket menjadi (tipe, payload)."""
    if len(data) < 4:
        raise ValueError(f"Paket terlalu pendek ({len(data)} byte) untuk header tipe")
    (t,) = struct.unpack_from("<I", data, 0)
    return t, data[4:]


# --------------------------------------------------------------------------- #
# Tabel paket `action|...` hasil ekstraksi dari libgrowtopia.so (arm64)
# --------------------------------------------------------------------------- #
# Sumber: literal string di .rodata `libgrowtopia.so` versi 5.58 (43.331.256 B).
# Setiap entri = satu `action|` yang benar-benar dikirim klien, beserta field
# yang menyertainya (urutan sesuai literal di binary). Dipakai
# `Bot.kirim()` supaya aksi baru tidak perlu satu method per fitur.
#
# Alat ekstraksi: tools/extract_so.py (tanpa Ghidra).
ACTIONS: dict[str, tuple[str, ...]] = {
    "AccountSecurity": ("location",),
    "PlasmaGlobeHeartLocalHour": ("localHour",),
    "UbiclubMenu": ("location",),
    "activatedungeonchallenge": (),
    "adClosed": (),
    "auction_getpage": ("pageIndex", "sortType", "searchItem"),
    "auction_place_bid": ("bidAmount",),
    "chaching": (),
    "claimdailyreward": (),
    "claimdungeonchallengerewards": (),
    "claimwinterrallyreward": (),
    "communitytabs": ("type",),
    "complete_seeddiary_tutorial": (),
    "dailyrewardmenu": (),
    "dungeonBackpackClicked": (),
    "dungeonleaderboard_getrange": ("startIndex", "endIndex", "relative"),
    "eventmenu": ("location",),
    "fashion_show_join_to_room": (),
    "fashion_show_vote": ("participantIndex",),
    "friends": ("location",),
    "get_seed_diary_data": (),
    "giveupdungeonchallenge": (),
    "gohomeworld": (),
    "growid": (),
    "houston_validation_done": (),
    "inventoryfavuitrigger": (),
    "itemfavourite": (),
    "killstore": ("item",),
    "mailbox_claimreward": ("messageID",),
    "mailbox_claimrewardsmany": ("listIDs",),
    "mailbox_getpage": ("pageIndex",),
    "mailbox_readmessage": ("messageID",),
    "mod_trade": ("itemID",),
    "on_use_door_tutorial": (),
    "purchase_dungeon_pass": (),
    "purchase_dungeon_scroll": (),
    "pveprofile": (),
    "quit": (),
    "refresh_item_data": (),
    "refresh_player_tribute_data": (),
    "rem_trade": ("itemID",),
    "requestAccountDelete": (),
    "resetclaimdailyreward": (),
    "respawn_spike": ("tileX",),
    "setDeath": ("animDeath",),
    "setFilter": ("filtering",),
    "setGDPR": ("GDPR",),
    "setOnlyFriendsChat": ("show",),
    "setRespawn": ("animRespawn",),
    "setRoleIcon": ("roleType",),
    "setRoleSkin": ("roleType",),
    "setSkin": ("color",),
    "set_auction_tile": ("item",),
    "setchatFilter": ("filtering",),
    "showdungeoninvitefriends": (),
    "startdungeonbtn": (),
    "store": ("location",),
    "storenavigate": ("item", "selection"),
    "survey": (),
    "surveyanswer": (),
    "trade_accept": ("status",),
    "trade_cancel": (),
    "trade_check_price": (),
    "trade_lock": ("status",),
    "trade_started": ("netid",),
    "tutorialTaskPhoneClicked": (),
    "tutorialTaskQuestClicked": (),
    "update_weather_machine": ("jsonStr",),
    "validate_world": ("name",),
    "wardrobe_preset_load": (),
    "wardrobe_purchase_slot": (),
    "wardrobe_unequip_all": (),
    "world_button": ("name",),
    "worldlock_storage_getpage": ("pageIndex",),
    "worldlock_storage_modify_amount": ("amount", "type"),
}


def build_action(name: str, **fields: Any) -> bytes:
    """Bangun payload `action|<name>\\n<field>|<nilai>\\n...`.

    Urutan field mengikuti tabel `ACTIONS`; nilai diberikan lewat keyword.
    Field yang tidak diberi nilai dilewati.
    """
    spec = ACTIONS.get(name)
    if spec is None:
        raise KeyError(f"action tidak dikenal: {name!r}")
    parts = [f"action|{name}"]
    for key in spec:
        if key in fields and fields[key] is not None:
            parts.append(f"{key}|{fields[key]}")
    return ("\n".join(parts) + "\n").encode("utf-8")
