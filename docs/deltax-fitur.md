# Fitur deltaX / XISEN — hasil bedah `libPowerKuy.so`

Dokumen ini mencatat **di mana** fitur deltaX sebenarnya berada dan **bagaimana**
Lucifer memakainya. Ditulis setelah analisis penuh Ghidra 12.2 atas
`lib/arm64-v8a/libPowerKuy.so` (11.978.224 B, `.text` 6.121.140 B, 22.843 fungsi (5.115.488 B)).

## Kesimpulan utama

**Fitur mod deltaX TIDAK ada di kode native.** `libPowerKuy.so` hanya menyediakan:

1. UI ImGui (`nativeDrawFrame`, EGL/GLESv2) — 626 fungsi yang menyentuh string UI.
2. Jembatan Lua (`LuaManager_Execute` @ `0x445c68`, `StopExecute` @ `0x445e88`).
3. Hook paket lewat JNI (`nativeGetMessagePowerKuy`, vtable game).

Logika fitur sesungguhnya ada di **skrip Lua** `assets/misc/*.lua.enc`, yang
didekripsi dengan rumus aditif (lihat `RE_libPowerKuy.md`):

```
plain[i] = (cipher[i] - KEY[i % 44]) & 0xFF
KEY = "AHJKSHSALMCYEUOECTYYIUADIOPDYTBRTWCERTDFGUQK"
```

Hasil dekripsi ada di `decrypted_lua/` (2.381 baris, 14 berkas berisi).
Jadi "membaca fitur deltaX" = membaca Lua itu, bukan disassembly.

## Bukti dari Ghidra

Analisis penuh berhasil (`ghidra-analyze.log`, 439 detik, heap 1300 MB):

- 256.390 data terdefinisi, 112 cocok dengan kata kunci fitur.
- Hanya **2** callback game yang dirujuk native: `OnSetClothing`, `OnDialogRequest`
  — sisanya ditangani Lua lewat hook.
- **9** template paket `action|` di `.text`/`.rodata` native, semuanya primitif:

```
action|dialog_return  (vending, trash_item, drop_item, give_item)
action|input
action|join_request   name|{} invitedWorld|1
action|drop |itemID|{}
action|trash |itemID|{}
```

Tidak ada satu pun `action|` untuk autofarm, autocollect, spammer, growscan.
Artinya fitur-fitur itu disusun dari primitif di atas **di dalam Lua**.

- Nama API Lua (`sendPacketRaw`, `bindValue`, `getObjectList`, …) **tidak ada**
  di `.rodata`: string di-obfuscate XOR seperti `getSupportedGameVersion`
  (lihat `RE_libPowerKuy.md` § String obfuscation). Ini yang membuat grep string
  tidak menemukan apa pun — bukan berarti fiturnya tidak ada.
- Sumber jalur build ikut terbaca: `/Users/powerkuy/Documents/Project/
  GrowLauncher-Kotlin-Android/app/src/main/cpp_rebuild/...` (fmt, imgui).

## Struktur fitur (dari `assets/menu.json`, 256 item)

| Kategori | Item |
|---|---|
| Menu (Basic, Visual, FindPath, Fast, ESP, Info, Debug, Login Spoof, Google) | 98 |
| Automation (Spammer, Autofarm, Automation, Collect, Fishing, AutoCrime, Copy Song, Ghost, Replay, Wrench, Moderator Exit) | 143 |
| World (Growscan, Random) | 6 |
| Module (Lua Manager) | 1 |
| Setting (Misc) | 8 |

Daftar lengkap dengan tipe widget + alias: `docs/deltax-fitur.json`.

## Yang bisa dan tidak bisa dipindah ke Lucifer

Bisa (murni paket server, tidak butuh hook memori):

- Autofarm, autocollect, auto drop/plant/splice (`automation.lua`)
- Spammer, replay, pathfinder, growscan
- World saver / navigator (`world_saver.lua`)
- Semua aksi `action|` di `protocol.ACTIONS` (75 aksi, lihat `docs/login-flow.md`)

Tidak bisa (butuh hook ke `libGrowtopia.so` ARM64 di dalam proses Android):

- ESP, noclip, ghost, moonwalk, fastfall, ModFly, Night Vision, See Inside Chest,
  visual inventory, visual name/clothes — semua menggambar atau memalsukan state
  klien, bukan mengirim paket.

## Jembatan yang dipakai Lucifer

`lucifer/compat_deltax.py` memasang nama API deltaX ke global Lua Lucifer,
sehingga **skrip deltaX asli jalan tanpa ditulis ulang**:

```lua
-- automation.lua deltaX, apa adanya
if not FindPath(tile.x, tile.y) then
    sleep(Delays.Harvest())
    growtopia.tileChange(tile.x, tile.y, 18)
end
```

Catatan semantik yang wajib diikuti (bukan bug):

| Nama deltaX | Padanan Lucifer | Catatan |
|---|---|---|
| `FindPath(x, y)` | `Bot.getPath` + `moveTile` | **True = GAGAL**, False = berhasil |
| `sendPacketRaw(false, {type=3, px, py, value})` | `Bot.place` | `px/py` = tile, `x/y` = piksel |
| `sendPacketRaw(false, {type=7, px, py})` | `Bot.hit` | `TileActivateRequest` |
| `sendVariant({v1=..., v2=...}, packet, netid)` | `Bot.send_raw` + `VariantList` | |
| `getValue/editValue/setValue/bindValue` | `data/deltax_values.json` | persisten |
| `getTiles()` | `Bot.world.tiles` | + `extra`, `readyharvest`, `itemid` |
| `getObjectList()` | `Bot.world.dropped` | + `invbit`, `pos.x/pos.y` |
| `addHook(fn, "onvariant")` | `LuaEngine._add_event` | |

`library.lua` dan `user_interface.lua` deltaX disalin apa adanya ke
`lucifer/lua_deltax/` — di sanalah `applyHook`, `await`, `growtopia.tileChange`,
`UserInterface` didefinisikan. Satu baris diubah: `dumpTable` memakai variabel
baru `nama` karena Lua 5.5 menjadikan variabel loop `const`.

## Cara menjalankan skrip deltaX

```python
from lucifer.lua_api import LuaEngine
eng = LuaEngine(accounts=[akun])
eng.parent = bot
eng.run_script_file("automation.lua")   # berkas deltaX, tanpa diubah
```

Pustaka deltaX dimuat otomatis saat `LuaEngine` dibuat.

## Verifikasi

`tests/test_deltax.py` — 43 pemeriksaan, termasuk menjalankan `automation.lua`
asli (dipotong di `while true`) dan memastikan ia mengirim
`TileChangeRequest value=18`, yaitu `growtopia.tileChange(x, y, 18)`.
