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


def aksi(t: int, value: int = 0) -> str:
    """Arti satu paket dalam bahasa manusia."""
    t = int(t)
    if t == 3:
        return "PLACE" if int(value) not in (18, 32, 0) else (
            "PUKUL" if int(value) == 18 else "WRENCH" if int(value) == 32 else "?")
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
    # `target_net_id` = UID objek untuk ItemChangeObject. Tanpa ini log
    # membingungkan: uid tidak kelihatan, `value` disangka item id.
    uid_obj = g("target_net_id")
    if uid_obj and uid_obj > 0 and uid_obj < 0x7FFFFFFF:
        bagian.append(f"uid={uid_obj}")
    if g("int_x") or g("int_y"):
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
    arti = aksi(tt, g("value"))
    if arti:
        bagian.append(f"-> {arti}")
    return " ".join(bagian)
