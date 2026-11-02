"""
lucifer.compat_deltax — lapisan kompatibilitas API Lua deltaX/PowerKuy.

Skrip asli deltaX (`assets/misc/*.lua.enc`, sudah didekripsi) tidak memakai API
Lucifer. Mereka memakai nama seperti `getLocal`, `getTiles`, `getObjectList`,
`getValue`, `sendPacketRaw`, `FindPath`, `addHook`, `bindValue`.

Modul ini memasang nama-nama itu ke tabel global Lua supaya skrip deltaX bisa
dijalankan apa adanya di Lucifer, tanpa menulis ulang skrip per fitur.

Sumber kebenaran nama & semantik: `decrypted_lua/*.lua` dari APK deltaX
(lihat `RE_libPowerKuy.md`).

Catatan semantik penting:

* `FindPath(x, y)` mengembalikan **True bila GAGAL** (tidak ada jalan), `False`
  bila berhasil. Skrip deltaX menulis `if not FindPath(...) then <aksi> end`,
  jadi urutannya harus dibalik seperti ini. Ini bukan bug — ikuti sumbernya.
* `getLocal()` mengembalikan `pos.x/pos.y` (piksel) DAN `posX/posY`; dua-duanya
  dipakai skrip (`player.pos.x // 32` dan `player.posX`).
* `getTiles()` mengisi `extra` (bool) dan `readyharvest` (bool).
* `getObjectList()` mengisi `itemid`, `pos.x/pos.y`, `invbit`, `id`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import protocol as P

__all__ = ["pasang"]


def _tabel(obj) -> bool:
    """True bila `obj` tabel Lua (lupa memakai `_LuaTable`, bukan `dict`)."""
    return hasattr(obj, "keys") and hasattr(obj, "items") and not isinstance(obj, (str, bytes))


# --------------------------------------------------------------------------- #
# Penyimpan nilai (pengganti getValue/editValue/setValue deltaX)
# --------------------------------------------------------------------------- #
class _Nilai:
    """Penyimpan alias -> nilai, persisten ke `data/deltax_values.json`.

    deltaX memakai tiga jenis nilai (`getValue(type, alias)`): 0 = toggle,
    1 = angka, 2 = string. Tipe hanya memengaruhi nilai bawaan, bukan
    penyimpanan; semuanya disimpan apa adanya.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self._data = {}

    def ambil(self, alias: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(str(alias), default)

    def setel(self, alias: str, value: Any) -> None:
        with self._lock:
            self._data[str(alias)] = value
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(self._data, indent=1, sort_keys=True), encoding="utf-8"
                )
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# Pemasangan
# --------------------------------------------------------------------------- #
def pasang(engine) -> None:
    """Pasang API gaya deltaX ke `engine` (LuaEngine). Idempoten."""
    g = engine.lua.globals()
    if g._deltax_terpasang:
        return
    g._deltax_terpasang = True

    lua = engine.lua
    nilai = _Nilai(Path(engine.data_dir) / "deltax_values.json")

    def bot_dari(label=None):
        return engine._resolve_bot(label)

    # -- nilai ----------------------------------------------------------- #
    def getValue(tipe, alias, *args):
        default = args[0] if args else None
        return nilai.ambil(alias, default)

    def editValue(alias, value=None):
        nilai.setel(alias, value)
        return True

    def setValue(alias, value=None):
        """`setValue` deltaX mengubah toggle; samakan dengan editValue."""
        nilai.setel(alias, value)
        return True

    def bindValue(tipe, alias, default=None):
        """Kembalikan fungsi pembaca nilai (dipakai `automation.lua`)."""
        return lambda: nilai.ambil(alias, default)

    g.getValue = getValue
    g.editValue = editValue
    g.setValue = setValue
    g.bindValue = bindValue

    # -- data dunia ------------------------------------------------------ #
    def getLocal(label=None):
        b = bot_dari(label)
        if not b or not b.local:
            return None
        pl = b.local
        t = engine._player_table(pl)
        pos = lua.table()
        pos.x = pl.posx
        pos.y = pl.posy
        t.pos = pos
        t.posX = pl.posx
        t.posY = pl.posy
        t.netID = pl.netid
        t.userID = pl.userid
        return t

    def tile_deltax(tile, b):
        t = engine._tile_table(tile, b)
        t.extra = bool(tile.has_extra)
        t.readyharvest = bool(tile.ready)
        t.itemid = tile.fg
        return t

    def getTiles(label=None):
        b = bot_dari(label)
        out = lua.table()
        if not b:
            return out
        for i, tile in enumerate(b.world.tiles, start=1):
            out[i] = tile_deltax(tile, b)
        return out

    def getTile(x, y, label=None):
        b = bot_dari(label)
        if not b:
            return None
        tile = b.world.tile(int(x), int(y))
        return tile_deltax(tile, b) if tile else None

    def getObjectList(label=None):
        b = bot_dari(label)
        out = lua.table()
        if not b:
            return out
        for i, d in enumerate(b.world.dropped, start=1):
            o = lua.table()
            o.id = d.uid
            o.oid = d.uid
            o.itemid = d.item_id
            o.count = d.count
            o.invbit = d.count
            o.flags = d.flags
            pos = lua.table()
            pos.x = d.x
            pos.y = d.y
            o.pos = pos
            out[i] = o
        return out

    def getWorldTileMap(label=None):
        b = bot_dari(label)
        out = lua.table()
        if not b:
            return out
        size = lua.table()
        size.x = b.world.width
        size.y = b.world.height
        out.size = size
        out.name = b.world.name
        return out

    def getCurrentWorldName(label=None):
        b = bot_dari(label)
        return b.world.name if b else ""

    g.getLocal = getLocal
    g.getTiles = getTiles
    g.getTile = getTile
    g.getObjectList = getObjectList
    g.getObjects = getObjectList
    g.getWorldTileMap = getWorldTileMap
    g.getCurrentWorldName = getCurrentWorldName

    # -- item & inventaris ----------------------------------------------- #
    def GetInventory(label=None):
        b = bot_dari(label)
        out = lua.table()
        if not b:
            return out
        for i, it in enumerate(b.inventory.items.values(), start=1):
            e = lua.table()
            e.id = it.id
            e.amount = it.count
            e.count = it.count
            e.isActive = it.isActive
            out[i] = e
        return out

    def getItemInfoByID(item_id, label=None):
        b = bot_dari(label)
        db = (b.items_db if b else None) or engine.items_db
        item = db.get(int(item_id)) if db else None
        return engine._item_info_table(item) if item else None

    def getItemInfoByName(name, label=None):
        b = bot_dari(label)
        db = (b.items_db if b else None) or engine.items_db
        if not db:
            return None
        for item in db.items.values():
            if item.name.lower() == str(name).lower():
                return engine._item_info_table(item)
        return None

    g.GetInventory = GetInventory
    g.getItemInfoByID = getItemInfoByID
    g.getItemInfoByName = getItemInfoByName

    # -- kirim paket ----------------------------------------------------- #
    def sendPacket(packet_type, text, label=None):
        b = bot_dari(label)
        if not b:
            return False
        if isinstance(packet_type, str) and not isinstance(text, str):
            packet_type, text = text, packet_type
        return b.send_packet(int(packet_type), str(text))

    def sendPacketRaw(toserver, packet, label=None):
        """`sendPacketRaw(false, {type=..., x=..., y=..., px=..., py=..., value=...})`

        `px`/`py` di deltaX = koordinat TILE, `x`/`y` = piksel. Tank Growtopia
        memakai int_x/int_y untuk tile dan vector_x/vector_y untuk posisi.
        """
        b = bot_dari(label)
        if not b or not _tabel(packet):
            return False
        # CATATAN: `_LuaTable` milik lupa tidak punya `.get()` yang bisa dipakai
        # (akses atribut tertutup field Lua), jadi selalu pakai indeks `[]`.
        def ambil(kunci, bawaan=0):
            v = packet[kunci]
            return bawaan if v is None else v

        ptype = int(ambil("type"))
        # type 3 = TileChangeRequest, type 7 = TileActivateRequest: kirim lewat
        # jalur bot yang sudah mengisi int_x/int_y dengan benar.
        px, py = packet["px"], packet["py"]
        value = int(ambil("value"))
        if px is not None and py is not None:
            if ptype == 3:
                return b.place(int(px), int(py), value)
            if ptype == 7:
                return b.hit(int(px), int(py))
        tank = P.Tank(
            type=ptype,
            net_id=int(ambil("netid")),
            flags=int(ambil("flags")),
            value=value,
            float_variable=float(ambil("state", ambil("float_var", 0.0)) or 0.0),
            vector_x=float(ambil("x", 0.0) or 0.0),
            vector_y=float(ambil("y", 0.0) or 0.0),
            int_x=int(ambil("int_x", px if px is not None else 0) or 0),
            int_y=int(ambil("int_y", py if py is not None else 0) or 0),
        )
        return b.send_raw(tank)

    def sendVariant(var, packet=None, netid=None, label=None):
        """Kirim VariantList dari tabel Lua `{v1=..., v2=...}`."""
        b = bot_dari(label)
        if not b or not _tabel(var):
            return False
        vl = P.VariantList()
        for key in sorted(k for k in var.keys() if str(k).startswith("v")):
            val = var[key]
            if isinstance(val, bool):
                vl.append(P.Variant.from_int(int(val)))
            elif isinstance(val, (int, float)):
                vl.append(P.Variant.from_int(int(val)))
            else:
                vl.append(P.Variant.from_string(str(val)))
        tank = packet if isinstance(packet, P.Tank) else P.Tank(
            type=P.NetGamePacket.CallFunction,
            net_id=int(netid if netid is not None else 0),
        )
        return b.send_raw(tank, vl.serialize())

    g.sendPacket = sendPacket
    g.SendPacket = sendPacket
    g.sendPacketRaw = sendPacketRaw
    g.sendVariant = sendVariant

    # -- hook ------------------------------------------------------------ #
    def addHook(fn, name=None):
        """deltaX: addHook(fungsi, "onvariant"). Dipetakan ke addEvent."""
        if name is None:
            return False
        engine._add_event(str(name).lower(), fn)
        return True

    def removeHook(name=None):
        engine._remove_event(str(name or "").lower())
        return True

    def runCoroutine(fn, *args):
        """deltaX menjalankan fungsi di thread sendiri (coroutine terpisah)."""
        engine._run_thread(fn, *args)
        return True

    g.addHook = addHook
    g.removeHook = removeHook
    g.runCoroutine = runCoroutine

    # -- tidur ----------------------------------------------------------- #
    def Sleep(ms):
        return engine._sleep(ms)

    def CSleep(ms):
        """Tidur tanpa memompa event (dipakai di dalam callback)."""
        try:
            time.sleep(max(0.0, float(ms) / 1000.0))
        except (TypeError, ValueError):
            pass

    g.Sleep = Sleep
    g.CSleep = CSleep

    # -- log & util ------------------------------------------------------ #
    def LogToConsole(text, *args):
        engine.log_line(" ".join(str(a) for a in (text,) + args))

    def isInside(cx, cy, radius, x, y):
        dx = float(x) - float(cx)
        dy = float(y) - float(cy)
        return dx * dx + dy * dy <= float(radius) * float(radius)

    def getTime():
        return int(time.time() * 1000)

    def FindPath(x, y, teleport=None, label=None):
        """deltaX: True = GAGAL cari jalan, False = berhasil.

        Skrip menulis `if not FindPath(...) then <aksi> end`, jadi urutan ini
        wajib. `teleport` diterima dan diabaikan (deltaX memakai packet hack).
        """
        b = bot_dari(label)
        if not b:
            return True
        path = b.getPath(int(x), int(y))
        if not path:
            return True
        for langkah in path:
            px, py = langkah[0], langkah[1]
            b.moveTile(px, py)
            time.sleep((getattr(b, "move_interval", 0) or 120) / 1000.0)
        return False

    g.LogToConsole = LogToConsole
    g.log = LogToConsole
    g.isInside = isInside
    g.getTime = getTime
    g.FindPath = FindPath

    # -- UI (no-op: Lucifer punya dashboard sendiri) ---------------------- #
    for nama in (
        "addCategory", "addIntoModule", "addSubCategory", "executeFromAssets",
    ):
        if g[nama] is None:
            g[nama] = lambda *a, **k: True

    # -- pustaka Lua bawaan deltaX --------------------------------------- #
    # `library.lua` + `user_interface.lua` deltaX dipakai apa adanya (bukan
    # ditulis ulang): di situlah `applyHook`, `await`, `sendDialog`, `UserInterface`,
    # `bindValue`, `isInside` didefinisikan. Tanpa keduanya skrip fitur deltaX
    # langsung gagal karena fungsi-fungsi itu belum ada.
    pustaka = Path(__file__).parent / "lua_deltax"
    folder_skrip = Path(engine.data_dir) / "library"
    folder_skrip.mkdir(parents=True, exist_ok=True)

    def getAppLibrary():
        """deltaX: folder tempat skrip/lua menyimpan berkas bantuannya."""
        return str(folder_skrip) + "/"

    def requireModule(nama):
        """Muat modul .lua dari folder pustaka deltaX (fallback Lua `require`)."""
        p = folder_skrip / f"{nama}.lua"
        if not p.exists():
            p = pustaka / f"{nama}.lua"
        if not p.exists():
            engine.log_line(f"requireModule: '{nama}' tidak ditemukan")
            return None
        return engine.lua.execute(p.read_text(encoding="utf-8"))

    g.getAppLibrary = getAppLibrary
    g.requireModule = requireModule

    for nama in ("library.lua", "user_interface.lua"):
        p = pustaka / nama
        if p.exists():
            try:
                engine.lua.execute(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                engine.log_line(f"pustaka deltaX {nama} gagal dimuat: {e}")
