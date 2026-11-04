# Rencana Fitur (paritas deltaX)

Sumber daftar menu: `docs/deltax-fitur.json` (256 entri hasil bedah UI deltaX).
Kolom **status**: `ada` = sudah ada di `lucifer/features.py`, `baru` = belum,
`skip` = visual/memory-patch klien, mustahil untuk bot headless.

Aturan tetap:

- Tiap fitur punya pilihan **tile** (`tile_select`) dan **block id** (`item_picker`)
  dengan mode `auto` (pakai block yang benar-benar ada di tile terpilih) atau
  id manual.
- Autofarm = **break + place**. Plant/harvest masuk **Automation**.
- Tidak reconnect berulang (risiko IP diblokir). Tak ada perintah yang
  mengubah state bot tanpa izin.

## 0. Prasyarat (dikerjakan dulu, berurutan)

| # | Item | Status | Catatan |
|---|------|--------|---------|
| 0.1 | Gerak (`State`, netid 0, 1 tile/paket) | **selesai (kode)** | `_send_move`, `moveTo`; uji `test_unit.py` |
| 0.2 | Posisi sendiri dari `OnSetPos` + netid dari `OnSpawn` | **selesai (kode)** | parser `OnSpawn` lama salah field |
| 0.3 | Echo posisi server | tidak ada | server tak mengecho; pakai prediksi lokal (pola deltaX) |
| 0.4 | Update tile realtime saat break/place | **ditunda** | server cuma kirim `type 3` (animasi) & `type 8` (damage); tak ada `type 5/6`. Butuh bukti baru |

## 1. Spammer — 12 menu

| Menu | Alias deltaX | Status |
|------|--------------|--------|
| Delay spam (ms) | `spammer_config_delay` | baru |
| Auto delay | `spammer_config_autodelay` | baru |
| Delay detected spam (ms) | `spammer_config_delay_long` | baru |
| Random Color | `spammer_config_autocolor` | baru |
| Random Order | `spammer_config_shuffle` | baru |
| Send to Client | `spammer_config_sendclient` | skip (butuh render lokal) |
| Text to spam | `spammer_config_texttospam` | ada |
| Add to list | `spammer_config_addtolist` | ada |
| Clear list | `spammer_config_clearlist` | ada |
| Auto Re-enter | `cheat_config_autoenter` | baru |
| Auto replay after enter | `spammer_replay_active` | baru |
| Get all actions | `spammer_replay_actions` | baru (dari `type 3` yang kita kirim) |

## 2. Autofarm (break + place) — 30 menu

Inti: pilih tile + block id, punch sampai pecah, lalu place block baru.

| Menu | Alias | Status |
|------|-------|--------|
| Block to break | `autofarm_item_picker` | baru (mode auto/manual) |
| Select tile to break | `autofarm_target_tile` | baru |
| Verify before punch | `autofarm_verify` | baru |
| Break | `autofarm_do_break` | ada |
| Place | `autofarm_do_place` | ada |
| Hit Count | `autofarm_punch_count` | ada |
| Delay Break | `autofarm_autopunch_delay` | ada |
| Delay place | `autofarm_autoplace_delay` | ada |
| Autofarm Debug | `autofarm_debug` | baru |
| Verify pos before continue | `autofarm_verify_pos` | baru |
| Verify pos debug | `autofarm_verify_debug` | baru |
| Delay after teleport | `autofarm_verify_delay` | baru |
| Faster break | `autofarm_config_overclock` | baru |
| Show punch | `autofarm_config_showpunch` | skip (visual) |
| Auto collect | `autofarm_autocollect_start` | ada (pakai Collect) |
| Delay | `autofarm_autocollect_delay` | ada |
| Collect block | `autofarm_autocollect_block` | baru |
| Collect seed | `autofarm_autocollect_seed` | baru |
| Debug | `autofarm_autocollect_debug` | baru |
| Auto drop | `autofarm_autodrop_start` | ada (`AutoDrop`) |
| Minimum to drop | `autofarm_autodrop_minimum` | ada |
| Position x/y block | `autofarm_autodrop_x/y` | ada |
| Current position | `autofarm_autodrop_current_pos` | baru |
| World to drop | `autofarm_autodrop_worldname` | ada |
| Current world | `autofarm_autodrop_worldname_current` | baru |
| Auto pick | `autofarm_autopick_enable` | baru |
| World to pick | `autofarm_autopick_world` | baru |
| Current world | `autofarm_autopick_world_current` | baru |
| Auto pick mode | `autofarm_autopick_mode` | baru |

## 3. Automation (plant & harvest) — 21 menu

| Menu | Alias | Status |
|------|-------|--------|
| Item to farm | `automation_item` | baru |
| Enable Auto Collect | `automation_autocollect` | baru |
| Mode | `automation_mode` | baru |
| Safe delay | `automation_safe_delay` | baru |
| Delay plant (ms) | `automation_delay_plant` | baru |
| Delay harvest (ms) | `automation_delay_harvest` | baru |
| Anti Miss | `automation_antimiss` | baru |
| Start from bottom | `automation_start_from_bottom` | baru |
| Enable Auto Drop | `automation_autodrop` | baru |
| Minimum to drop | `automation_autodrop_minimum` | baru |
| Drop position X/Y | `automation_autodrop_x/y` | baru |
| Current position | `automation_autodrop_current_pos` | baru |
| Facing when drop | `automation_autodrop_facing` | baru |
| Enable Auto Take | `automation_autotake` | baru |
| Minimum to take | `automation_autotake_minimum` | baru |
| Enable Auto Splice | `automation_autosplice` | baru |
| Item to splice | `automation_splice_item` | baru |
| Minimum planted before splice | `automation_autosplice_minimum_planted` | baru |
| Automation Debug | `automation_debug` | baru |
| Smart Delay | `automation_smart_delay` | baru |

## 4. Collect — 12 menu

| Menu | Alias | Status |
|------|-------|--------|
| Item (ambil) | `collectfilter_itemtotake` | baru |
| Specified value | `filter_collect_valuetake` | baru |
| Item (jangan ambil) | `collectfilter_itemdisabletake` | baru |
| Delay | `auto_collect_delay` | ada |
| Fast take | `auto_collect_faster` | baru |
| Check before take | `auto_collect_check` | baru |
| Inventory check | `auto_collect_inventory_check` | baru |
| Debug area | `auto_collect_debug_area` | baru |
| Debug take | `auto_collect_debug` | baru |
| Auto collect mode | `auto_collect_mode` | baru |
| Radius auto collect | `auto_collect_radius` | ada |
| Select tile to collect | `auto_collect_tile` | baru |

## 5. Fishing — 10 menu

| Menu | Alias | Status |
|------|-------|--------|
| Bait | `autofish_config_bait` | baru |
| Delay after catch | `autofish_config_delay` | baru |
| Direction | `autofish_config_direct` | baru |
| Delay after trigger mode | `autofish_config_delaymode` | baru |
| Minimum items in front to move | `autofish_config_minimum_to_move` | baru |
| Auto teleport back | `autofish_autoteleport` | baru |
| Auto move | `autofish_automove` | baru |
| Action after catch | `autofish_action_catch` | baru |
| Filter Action | `autofish_action_catch_filter` | baru |
| Enable Action | `autofish_action_enable` | baru |

## 6. AutoCrime (ghost) — 1 menu + Ghost 17

| Menu | Alias | Status |
|------|-------|--------|
| AutoCrime | `autocrime_is_active` | baru |
| Auto Punch Ghost | `cheat_auto_esp_ghost` | skip (patch memori klien) |
| Show Punch | `cheat_auto_esp_ghost_show_punch` | skip |
| Auto put jar | `cheat_auto_esp_ghost_jar` | baru |
| Search Radius | `ghost_config_radius` | baru |
| Minimum ghost stay before put jar | `ghost_config_min_in_radius` | baru |
| Debug | `cheat_auto_esp_ghost_debug` | baru |
| Show Distance/Target/Line/State/Type/Radius | `ghost_debug_*` | skip (visual) |
| Esp Ghost | `cheat_esp_ghost` | skip |
| Auto Teleport | `cheat_esp_ghost_auto_teleport` | baru |
| Normal/Mind/Winter Ghost | `ghost_auto_*` | baru |

## 7. Wrench — 5 menu

| Menu | Alias | Status |
|------|-------|--------|
| Fast wrench mode | `cheat_fastwrench` | baru |
| Enable | `cheat_fastwrench_enable` | baru |
| Enhanced Mode | `cheat_fastwrench_enhanced` | baru |
| Auto Wrench | `cheat_autowrench` | baru |
| Auto wrench mode | `cheat_autowrench_mode` | baru |

## 8. Replay — 11 menu

| Menu | Alias | Status |
|------|-------|--------|
| Record | `replay_record_active` | ada (`Replay`) |
| Play | `replay_play_active` | ada |
| Loop | `replay_loop` | baru |
| Raw Packet | `replay_record_active_raw` | baru |
| Text Packet | `replay_record_active_text` | baru |
| Custom delay (ms) | `replay_custom_delay` | baru |
| Clear Actions | `replay_clear` | baru |
| Filename | `replay_filename` | baru |
| Add / Refresh | `replay_filename_add`, `*_refresh` | baru |

## 9. Moderator Exit — 16 menu

Semua `baru`; butuh deteksi moderator (join world / chat) lalu drop item di
posisi tetap + warp keluar. Menu: `mod_exit_enable`, `modexit_mode`,
`mod_exit_drop_world`, `mod_exit_current_world`, `mod_exit_drop_pos_x/y`,
`mod_exit_current_drop`, `mod_exit_donate_world`, `mod_exit_current_world_donate`,
`mod_exit_donate_player_pos_x/y`, `mod_exit_current_donate`,
`mod_exit_donate_pos_x/y`, `mod_exit_find_donate`, `DEBUG_MOD_JOIN`.

## Urutan pengerjaan

1. Prasyarat 0.1–0.3 (gerak) — kode selesai, uji hijau, **butuh verifikasi live**.
2. Collect (12) + break block: paling kecil, dipakai fitur lain.
3. Autofarm (break + place, tile + block id auto/manual).
4. Automation (plant + harvest).
5. Spammer.
6. Fishing, AutoCrime/ghost, Wrench, Replay, Moderator Exit.
7. Rombak GUI mod menu mengikuti skema di atas (sidebar fitur + form kanan).
8. 0.4 update tile realtime kalau ada bukti paket baru.
