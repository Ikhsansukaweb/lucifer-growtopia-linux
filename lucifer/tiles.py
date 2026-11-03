"""Atlas tile Growtopia -> sprite PNG per item.

`items.dat` menyimpan `texture_file_name` (`tiles_pageN.rttex`) dan koordinat
`texture_x/texture_y` dalam satuan tile 32x32. Berkas `.rttex` sendiri adalah
`RTPACK` (zlib) yang di dalamnya `RTTXTR` berisi RGBA mentah 1024x1024.

Modul ini membuka atlas itu sekali, memotong ubin 32x32 sesuai item yang
diminta, lalu menyimpannya sebagai PNG. Dipakai GUI untuk menggambar dunia:
tiap koordinat tile mendapat gambar blok yang benar (Dirt, Grass, Pizza, ...).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional

TILE_PX = 32
_CACHE: dict[str, "object"] = {}


def _cari_folder_tile() -> Optional[Path]:
    """Cari folder berisi `tiles_page*.rttex`."""
    kandidat = [
        Path.home() / ".wine/drive_c/users/ikhsan/AppData/Local/Growtopia/game",
        Path.home() / ".var/app/io.mrarm.mcpelauncher/data/mcpelauncher",
    ]
    for folder in kandidat:
        if folder.exists() and next(folder.glob("tiles_page*.rttex"), None):
            return folder
    for p in Path.home().rglob("tiles_page1.rttex"):
        return p.parent
    return None


class Atlas:
    """Atlas satu halaman tile (`tiles_pageN.rttex`)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        data = path.read_bytes()
        if data[:6] != b"RTPACK":
            raise ValueError(f"{path.name}: bukan RTPACK")
        raw = zlib.decompress(data[32:])
        if raw[:6] != b"RTTXTR":
            raise ValueError(f"{path.name}: bukan RTTXTR")
        self.width, self.height = struct.unpack_from("<II", raw, 8)
        self.pixels = raw[124:]
        if len(self.pixels) < self.width * self.height * 4:
            raise ValueError(f"{path.name}: data piksel pendek")

    def ubin(self, tx: int, ty: int) -> bytes:
        """Ambil satu tile 32x32 sebagai RGBA mentah (baris demi baris).

        Koordinat `texture_y` di `items.dat` dihitung dari bawah atlas, jadi
        barisnya dibalik dulu. Tanpa ini Fist tampil sebagai bata merah dan
        Dirt sebagai blok kuning.
        """
        baris = self.height // TILE_PX
        y0 = (baris - 1 - ty) * TILE_PX
        x0 = tx * TILE_PX
        if x0 < 0 or y0 < 0 or x0 + TILE_PX > self.width or y0 + TILE_PX > self.height:
            return b"\x00" * (TILE_PX * TILE_PX * 4)
        out = bytearray()
        for y in range(y0, y0 + TILE_PX):
            awal = (y * self.width + x0) * 4
            out += self.pixels[awal : awal + TILE_PX * 4]
        return bytes(out)


def _atlas(nama: str) -> Optional[Atlas]:
    """Muat atlas per nama berkas, dengan cache."""
    if not nama:
        return None
    if nama in _CACHE:
        return _CACHE[nama]  # type: ignore[return-value]
    folder = _cari_folder_tile()
    if folder is None:
        return None
    path = folder / nama
    if not path.exists():
        return None
    try:
        a = Atlas(path)
    except Exception:  # noqa: BLE001
        return None
    _CACHE[nama] = a
    return a


def sprite_png(item, folder_cache: Path) -> Optional[Path]:
    """Buat (sekali) PNG 32x32 untuk satu item; kembalikan path-nya."""
    from PIL import Image  # noqa: PLC0415

    nama = (getattr(item, "texture_file_name", "") or "").strip()
    if not nama:
        return None
    tx = int(getattr(item, "texture_x", 0) or 0)
    ty = int(getattr(item, "texture_y", 0) or 0)

    out = folder_cache / f"{int(getattr(item, 'id', 0))}.png"
    if out.exists():
        return out

    a = _atlas(nama)
    if a is None:
        return None
    buf = a.ubin(tx, ty)
    if not any(buf):
        return None

    folder_cache.mkdir(parents=True, exist_ok=True)
    im = Image.frombytes("RGBA", (TILE_PX, TILE_PX), buf)
    im.save(out)
    return out


def folder_cache(akar: Path) -> Path:
    d = akar / "tile_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def daftar_halaman() -> list[str]:
    folder = _cari_folder_tile()
    if folder is None:
        return []
    return sorted(p.name for p in folder.glob("tiles_page*.rttex"))
