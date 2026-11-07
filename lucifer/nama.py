"""lucifer.nama — nama manusiawi untuk kode protokol Growtopia.

Semua angka mentah di jurnal paket diterjemahkan di sini supaya log bisa
dibaca tanpa menghafal tabel. Satu sumber kebenaran: dipakai `bot.py` (ringkas
tank) dan `web.py` (jurnal paket).

Contoh hasil:
    type=3(TileChangeRequest) value=2(Dirt)  flags=0x8(EXTENDED)
    netid=-1(ALL)  tile=(48,23)  pos=(1536,736)  -> PLACE Dirt
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "tank_type",
    "netid",
    "flags",
    "tank_value",
    "aksi",
    "ringkas_tank",
    "object_type",
    "item_nama",
]

# --------------------------------------------------------------- tipe tank --
TANK: dict[int, str] = {
    0: "State",
    1: "CallFunction",
    2: "UpdateStatus",
    3: "TileChangeRequest",
    4: "SendMapData",
    5: "SendTileUpdateData",
    6: "SendTileUpdateDataMultiple",
    7: "TileActivateRequest",
    8: "TileApplyDamage",
    9: "SendInventoryState",
    10: "ItemActivateRequest",
    11: "ItemActivateObjectRequest",
    12: "SendTileTreeState",
    13: "ModifyItemInventory",
    14: "ItemChangeObject",
    15: "SendLock",
    16: "SendItemDatabaseData",
    17: "SendParticleEffect",
    18: "SetIconState",
    19: "ItemEffect",
    20: "SetCharacterState",
    21: "PingReply",
    22: "PingRequest",
    23: "GotPunched",
    24: "AppCheckResponse",
    25: "AppIntegrityFail",
    26: "Disconnect",
    27: "BattleJoin",
    28: "BattleEvent",
    29: "UseDoor",
    30: "SendParental",
    31: "GoneFishin",
    32: "Steam",
    33: "PetBattle",
    34: "Npc",
    35: "Special",
    36: "SendParticleEffectV2",
    37: "ActivateArrowToItem",
    38: "SelectTileIndex",
}

# -------------------------------------------------------------- netid kode --
NETID: dict[int, str] = {
    0xFFFFFFFF: "ALL",       # -1  : siaran / objek baru
    0xFFFFFFFE: "SERVER",    # -2  : server sendiri
    0xFFFFFFFD: "MERGE",     # -3  : gabung ke objek yang sudah ada
}

# --------------------------------------------------------------- tank flag --
FLAGS: dict[int, str] = {
    0x01: "ON_GRAVITY",
    0x02: "ON_COLLISION",
    0x04: "ON_FACING_LEFT",
    0x08: "EXTENDED",
    0x10: "ON_PARACHUTE",
    0x20: "ON_JUMP",
    0x40: "ON_WALL_HANG",
    0x80: "ON_DOUBLE_JUMP",
}

# ------------------------------------------------------- object_type (tank) --
OBJECT_TYPE: dict[int, str] = {
    0: "NONE",
    1: "PLAYER",
    2: "DROPPED",
    3: "NPC",
    4: "SEED",       # bibit di pohon / drop bibit
    5: "BLOCK",
}

# ------------------------------------------------------------ aksi tile -----
# `value` pada TileChangeRequest: 18 = pukul (Fist), sisanya item id.
VALUE_KHUSUS: dict[int, str] = {
    0: "Blank",
    18: "Fist(pukul)",
    32: "Wrench",
}

# Nama aksi berdasarkan tipe tank + value.
AKSI_TANK: dict[int, str] = {
    0: "gerak/state",
    1: "variant",
    3: "tileChange",
    8: "pukulan diterima",
    11: "ambil objek",
    13: "stok berubah",
    14: "objek muncul/diambil",
    21: "ping balas",
    22: "ping minta",
}


def _db(item_db: Any) -> Any:
    return item_db


def item_nama(item_id: int, item_db: Any = None) -> str:
    """Nama item kalau database tersedia, kalau tidak `#id`."""
    if item_id in VALUE_KHUSUS:
        return VALUE_KHUSUS[item_id]
    if item_db is not None:
        try:
            return item_db.name_of(int(item_id))
        except Exception:  # noqa: BLE001
            pass
    return f"#{item_id}"


def tank_type(t: int) -> str:
    return TANK.get(int(t), f"?{t}")


def netid(n: int) -> str:
    return NETID.get(int(n), str(int(n)))


def flags(f: int) -> str:
    """Rincian bit flag: `0x8(EXTENDED)` atau `0x28(EXTENDED,ON_JUMP)`."""
    if not f:
        return ""
    bagian = [nama for bit, nama in FLAGS.items() if int(f) & bit]
    if not bagian:
        bagian = ["?"]
    return f"0x{int(f):x}(" + ",".join(bagian) + ")"


def object_type(o: int) -> str:
    return OBJECT_TYPE.get(int(o), f"?{o}")


def tank_value(t: int, value: int, item_db: Any = None, nid: int = 0) -> str:
    """`value` diberi nama sesuai tipe paket DAN netid-nya.

    Untuk `ItemChangeObject` (type 14) artinya berbeda tergantung `netid`:
      netid = ALL / MERGE  -> `value` = item id      (objek muncul / menumpuk)
      netid = pemain       -> `value` = uid objek    (objek diambil)
    Bukti dari jurnal paket: `netid=ALL value=2(Dirt)` vs `netid=3 value=5`
    (uid 5, BUKAN item id 5).
    """
    t, value, nid = int(t), int(value), int(nid)
    if t == 3 or t == 8:
        # TileChangeRequest / TileApplyDamage: 18 = pukul, lain = item id
        return item_nama(value, item_db)
    if t == 13:
        return item_nama(value, item_db)
    if t == 14:
        if nid in (-1, 0xFFFFFFFF, -3, 0xFFFFFFFD):
            return item_nama(value, item_db)      # value = item id
        return f"uid={value}"                     # value = uid objek
    if t == 11:
        return f"uid={value}"
    return str(value)


def aksi(t: int, value: int = 0, nid: int = 0) -> str:
    """Arti satu paket dalam bahasa manusia."""
    t = int(t)
    if t == 3:
        return "PLACE" if int(value) not in (18, 32, 0) else (
            "PUKUL" if int(value) == 18 else "WRENCH" if int(value) == 32 else "?")
    if t == 14:
        art = item_change_arti(nid)
        return "objek DITUMPUK" if art["target_net_id"] == "uid" else (
            "objek BARU" if art["value"] == "item" else "objek DIAMBIL")
    return AKSI_TANK.get(t, "")


def ringkas_tank(t: Any, item_db: Any = None) -> str:
    """Ringkas satu TankPacket jadi satu baris yang bisa dibaca.

    Menerima objek apa pun yang punya atribut `type`, `net_id`, `int_x`,
    `int_y`, `vector_x`, `vector_y`, `value`, `flags`, `object_type`,
    `animation_type`, `jump_count` (Tank Python maupun hasil parse lain).
    """
    g = lambda n, d=0: getattr(t, n, d)  # noqa: E731
    tt = int(g("type"))
    bagian = [f"type={tt}({tank_type(tt)})"]
    if g("net_id"):
        bagian.append(f"netid={netid(g('net_id'))}")
    # `target_net_id` artinya BERBEDA per tipe/netid — lihat `item_change_arti`.
    # Menulis "uid=" untuk semua paket (versi lama) menyesatkan: pada type 14
    # netid ALL field itu netid pemain yang menjatuhkan, BUKAN uid objek.
    tn = g("target_net_id")
    if tn and 0 < tn < 0x7FFFFFFF:
        if tt == 14:
            art = item_change_arti(g("net_id"))
            if art["target_net_id"] == "uid":
                bagian.append(f"uid={tn}")
            else:
                bagian.append(f"dropper_netid={netid(tn)}")
    if tt == 11:
        # `int_x` pada type 11 = jumlah item (invbit), bukan koordinat.
        bagian.append(f"count={int(g('int_x'))}")
    if (g("int_x") or g("int_y")) and tt != 11:
        bagian.append(f"tile=({int(g('int_x'))},{int(g('int_y'))})")
    if g("vector_x") or g("vector_y"):
        bagian.append(f"pos=({g('vector_x'):.0f},{g('vector_y'):.0f})")
    if g("vector_x2") or g("vector_y2"):
        bagian.append(f"vec2=({g('vector_x2'):.0f},{g('vector_y2'):.0f})")
    if g("value"):
        bagian.append(f"value={g('value')}"
                      f"({tank_value(tt, g('value'), item_db, g('net_id'))})")
    if g("object_type"):
        bagian.append(f"obj={g('object_type')}({object_type(g('object_type'))})")
    if g("animation_type"):
        bagian.append(f"anim={g('animation_type')}")
    if g("jump_count"):
        bagian.append(f"jump={g('jump_count')}")
    if g("flags"):
        bagian.append(f"flags={flags(g('flags'))}")
    arti = aksi(tt, g("value"), g("net_id"))
    if arti:
        bagian.append(f"-> {arti}")
    return " ".join(bagian)

# ===========================================================================
# PEMETAAN FIELD TANK -> ARTI, per tipe paket
# ===========================================================================
# Satu sumber kebenaran. Sebelumnya arti `value`/`netid`/`uid` ditafsirkan
# berbeda-beda di beberapa tempat sehingga sering tertukar.
#
# Layout struct (lucifer/protocol.py, 56 byte little-endian):
#   offset  0  type          u8
#   offset  4  net_id        u32   <- Gurotopia `.netid`
#   offset  8  target_net_id i32   <- Gurotopia `.uid`
#   offset 12  flags         u32   <- Gurotopia `.state`
#   offset 16  float_variable f32  <- Gurotopia `.count`
#   offset 20  value         u32   <- Gurotopia `.id`
#   offset 24  vector_x      f32   <- Gurotopia `.pos.x`   (piksel)
#   offset 28  vector_y      f32
#   offset 44  int_x         i32   <- Gurotopia `.punch.x` (tile)
#   offset 48  int_y         i32

# Arti tiap field, per tipe tank.
#   "item"  = id item
#   "uid"   = uid objek
#   "netid" = netid pemain
#   "count" = jumlah item
#   "tile"  = koordinat tile
#   "px"    = koordinat piksel
TANK_ARTI: dict[int, dict[str, str]] = {
    # Server meng-echo aksi kita. value = item id (18 = pukul = blok pecah).
    3: {"value": "item", "net_id": "netid", "int_x": "tile", "int_y": "tile",
        "vector_x": "px", "vector_y": "px"},
    # Pukulan diterima. value = nilai damage mentah, BUKAN item id.
    8: {"value": "damage", "net_id": "netid", "int_x": "tile", "int_y": "tile"},
    # Ambil objek. value = UID OBJEK. int_x = jumlah item (invbit deltaX).
    11: {"value": "uid", "int_x": "count", "vector_x": "px", "vector_y": "px",
         "net_id": "netid"},
    # Objek muncul/hilang.
    #   netid ALL(-1) / MERGE(-3): value = ITEM ID, target_net_id = uid
    #   netid pemain            : value = UID OBJEK, target_net_id = netid
    14: {"net_id": "penanda", "value": "bedakan", "target_net_id": "uid",
         "float_variable": "count", "vector_x": "px", "vector_y": "px"},
    # Stok satu item naik/turun. value = item id.
    13: {"value": "item"},
    # Posisi/gerak. vector = piksel.
    0: {"net_id": "netid", "vector_x": "px", "vector_y": "px"},
    20: {"net_id": "netid", "vector_x": "px", "vector_y": "px"},
}


def arti_field(tipe: int, field: str) -> str:
    """Arti satu field untuk tipe tank tertentu ('item'/'uid'/'netid'/...)."""
    return TANK_ARTI.get(int(tipe), {}).get(field, "?")


MERGE_NETID = (0xFFFFFFFD, -3)
ALL_NETID = (0xFFFFFFFF, -1)


def item_change_arti(net_id: int) -> dict[str, str]:
    """Arti field `ItemChangeObject` (type 14) menurut `net_id`.

    Tiga bentuk dalam satu tipe paket:

        netid ALL(-1)     objek BARU
                          value          = item id
                          target_net_id  = netid pemain yang menjatuhkan
                          float_variable = jumlah item
        netid MERGE(-3)   objek DITUMPUK
                          value          = item id
                          target_net_id  = uid objek yang ditumpuk
                          float_variable = jumlah TOTAL
        netid pemain      objek DIAMBIL
                          value          = uid objek
                          target_net_id  = netid pemain

    Bukti: tiga drop berbeda (Rock Seed, Cave BG, Dirt Seed) semuanya
    mengirim `target_net_id=5` = netid pemain lain. Saat rejoin,
    `SendMapData` memberi uid asli 10, 11, 12.
    """
    n = int(net_id)
    if n in MERGE_NETID:
        return {"value": "item", "target_net_id": "uid",
                "float_variable": "count"}
    if n in ALL_NETID:
        return {"value": "item", "target_net_id": "netid",
                "float_variable": "count"}
    return {"value": "uid", "target_net_id": "netid"}
