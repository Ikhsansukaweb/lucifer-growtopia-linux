# Lucifer Linux

**API Lua Lucifer V1.8 untuk Growtopia — berjalan native di Linux.**

Klien Growtopia asli (ENet yang dipatch Ubisoft + codec Tank/Variant + CRC32 +
range coder), mesin skrip Lua lengkap, dashboard web, **GUI native GTK3**, dan
dukungan proxy SOCKS5 untuk UDP. Skrip ditulis dengan gaya Lucifer, jadi skrip
Lucifer yang sudah ada bisa langsung dipakai.

```
   _                       _  _
  | |   _   _  ___(_) __ _ | |(_)_ __
  | |  | | | |/ __| |/ _` || || | '__|     Lucifer Linux  v1.0.0
  | |__| |_| | (__| | (_| || || | |        API Lua Lucifer V1.8 untuk Growtopia
  |_____\__,_|\___|_|\__,_|_|/ |_|
                           |__/
```

---

## Bukti bekerja (bukan klaim)

Diuji langsung ke server Growtopia **asli** (bukan server lokal):

```
$ make && .venv/bin/python tests/test_integration.py

== 1. Endpoint server_data.php resmi ==
  ✓ respons diterima  528 ms
  ✓ ada 'server'  213.179.209.175
  ✓ ada 'port'  17043

== 2. Handshake ENet ke server game (patch Ubisoft) ==
  ✓ library ENet dimuat  /home/ikhsan/Documents/lucifer-linux/enet/enet.so
  ✓ ENet connect  252 ms -> 213.179.209.175:17043
  ✓ ServerHello diterima  tipe=[1]

== 3. Codec paket (kirim login -> terima balasan server) ==
  ✓ server membalas paket terurai  Fail to login. Please try again in 30 seconds.

== 4. Rantai LENGKAP: skrip Lua -> Bot -> ENet -> server GT ==
  ✓ items.dat dimuat  16480 item v27
  ✓ skrip Lua dieksekusi
  ✓ event server sampai ke handler Lua  Fail to login. Please try again in 30 seconds.
  ✓ bot membuat koneksi ENet nyata  213.179.209.175:17047

 lulus: 13   gagal: 0
SEMUA UJI NYATA LULUS — rantai Lua -> ENet -> Growtopia bekerja
```

Balasan *"Fail to login"* justru **bukti** bahwa paket kita diterima dan dijawab
server asli — kredensial di tes sengaja tidak valid.

### Kalau kena `logon_fail` (login pakai kuota / hotspot HP)

`Fail to login. Please try again in 30 seconds.` = **cooldown IP dari server**,
bukan token mati. Token bisa tetap valid (`Account Validated` di
`/player/growid/checktoken`) sementara game server masih menahan login.

Yang **jangan** dilakukan: klik Connect berulang. Tiap percobaan memperpanjang
cooldown, lalu IP diblokir lebih lama.

Sejak commit ini bot:
- memetakan pesan itu ke status `too_many_login` (bukan `logon_fail` generik),
- **mematikan auto-reconnect** saat cooldown terdeteksi,
- menyarankan *"tunggu sesuai detik di pesan"*, bukan *"sandi salah"*
  (login ltoken tidak memakai sandi),
- memisahkan `Login token is invalid.` → status `invalid_account` dengan saran
  ambil ltoken baru.

Kalau ENet connect sendiri gagal (`timeout` UDP ke `213.179.209.175:170xx`)
sementara UDP ke `8.8.8.8:53`/STUN jalan, itu **jalur jaringan memblokir port
game** — bukan bug bot. Buktinya: TCP/443 ke IP game juga timeout, tapi
`login.growtopiagame.com:443` terbuka. Ganti jaringan (Wi-Fi lain) atau pakai
VPN/proxy lewat field `proxy` akun.

`items.dat` v27 terbaca sempurna: **16.480 item**, dengan ID asli
(World Lock = 242, Dirt = 2, Grass Seed = 17, Fist = 18, Wrench = 32).

---

## Anti-ercon: aturan yang dipakai bot

Bagian ini ada karena kesalahan yang sama berulang: bot menembak server
lebih cepat daripada server memprosesnya, lalu IP diblokir.

**Aturan satu-satunya:** kirim **satu** aksi → tunggu server membalas →
baru boleh kirim lagi. Kalau tidak dibalas, berhenti.

Yang ditegakkan di kode (semua berlaku untuk fitur **dan** skrip Lua):

| Penjaga | Nilai | Kenapa |
|---|---|---|
| `Bot._tunggu_balasan_aksi()` | `AKSI_TUNGGU_BALAS_S = 2.0` | satu aksi menunggu balasan; lewat batas → tile ditandai gagal & dilewati |
| `Bot.auto_reconnect` | `False` | connect **hanya** dari tombol/permintaan user |
| `Bot._send_move` | `MOVE_JEDA_MIN_S = 0.26` | laju klien asli 123 px/detik = 1 tile / 260 ms |
| `Bot._send_move` | maks 64 px per paket | menolak lompatan/teleport |
| `Bot._send_move` | `POS_KOREKSI_DIAM_S = 2.0` | `OnSetPos` = server menolak posisi → gerak berhenti |
| `Bot._tile_change` | `JANGKAU_TILE = 4` | server menolak tile di luar 4 tanpa kabar |
| `Bot._tile_change` | `PAKET_MAKS_PER_DETIK = 10` | batas laju paket total |
| `Bot._tile_terkunci` | `TILE_TERKUNCI_INGAT_S = 300` | `punch_locked` / `cant_place_tile` = tile dilewati, bukan diulang |
| `Runner` | satu skrip | klik "Jalankan" kedua ditolak selama skrip pertama hidup |

### Paket balasan yang membuka gerbang aksi

Hanya balasan **milik bot sendiri**:

- `TileApplyDamage` (type 8) dengan `net_id` sendiri
- echo `TileChangeRequest` (type 3) dengan `net_id` sendiri
- `audio/punch_locked.wav` — penolakan, tapi tetap **balasan**
- `audio/cant_place_tile.wav` — penolakan place

Echo pemain lain **tidak** membuka gerbang. `punch_locked` dan
`cant_place_tile` **wajib** membukanya — kalau tidak, satu tile terkunci
membuat bot diam selamanya ("cuma sebagian di-break terus diem").

### API Lua terkait

```lua
TileBalas()        -- berapa aksi terakhir yang belum dibalas
TileDitolak(x, y)  -- true bila server menyatakan tile ini terkunci
ServerAlive()      -- false bila tidak ada paket masuk (koneksi mati)
TotalHit()         -- jumlah TileApplyDamage yang sudah diterima
```

### Yang **jangan** dilakukan

- Klik Connect berulang saat `logon_fail` / `too_many_login` — tiap
  percobaan memperpanjang cooldown.
- Membuka beberapa GUI sekaligus — dulu tiap GUI menyalakan backend yang
  langsung auto-connect. Sekarang GUI memakai `--no-connect`.
- Menjalankan backend dari folder lain — path `data/` & `scripts/`
  di-resolve dari folder repo (`ROOT` di `runner.py`), bukan cwd, tapi
  tetap: jalankan dari repo supaya tidak bingung.

---

## Pasang

```bash
git clone <repo> lucifer-linux && cd lucifer-linux
make                  # kompilasi ENet patch Growtopia + siapkan venv
make doctor           # cek lingkungan
make probe            # uji handshake ke server Growtopia asli
```

Butuh: Python ≥ 3.10, `g++`/`clang++`, `python3-venv`.

Untuk GUI native, tambahan: `gtk3`, `json-glib`, `cmake`.

```bash
bash deploy/pasang-desktop.sh   # build GUI + pasang ikon + entri menu
```

---

## Login

> **✅ CARA PALING MUDAH (terbukti 2026-09-30): login Google lewat browser.**
> Cara yang sama dengan **Growlauncher** — tidak butuh root, tidak butuh patch
> APK, dan **sandi Google tidak pernah diminta** (kamu pilih akun sendiri).
> ```bash
> .venv/bin/lucifer login --google-browser --verify
> ```
> Growtopia punya OAuth client bertipe **Web** (`client_id` ada di `base.apk`
> resmi), jadi Google mengizinkan redirect ke
> `login.growtopiagame.com/google/callback`. Server GT menukar `code` Google
> jadi `ltoken`. Terperinci: [`docs/login-flow.md`](docs/login-flow.md) bagian 6.

Growtopia modern (v4.6+) **tidak** mengirim email+sandi ke server game. Klien
menukar kredensial menjadi **`ltoken`**, lalu server game hanya menerima
`ltoken`. Lucifer Linux mendukung semua jalur:

| Metode | Cara kerja | Butuh | Status |
|---|---|---|---|
| `--google-browser` | buka Chrome → pilih akun Google → tukar `code` jadi ltoken | Chrome | ✅ **cara Growlauncher** |
| `--code` | tempel `code` dari URL callback Google | `code` | ✅ tanpa browser |
| `legacy` | `tankIDName` + `tankIDPass` langsung ke server game | akun lama (pra-4.61) | ✅ jalur paling sederhana |
| `growid` | tukar GrowID+sandi jadi `ltoken` lewat `login.growtopiagame.com` | nama + sandi | ⚠️ belum terverifikasi |
| `token` | pakai `ltoken` yang sudah ada | `ltoken` | ✅ kalau tokennya benar |
| `hp` | ambil `Token` dari `save.dat` HP, tukar jadi token | HP Android + ADB | ⚠️ ambil ✅ / tukar ❌ |

### Rantai token Google (cara Growlauncher — sudah diuji)

```
1. accounts.google.com/o/oauth2/v2/auth
     client_id    = <client_id GT tipe Web, dari base.apk>
     redirect_uri = https://login.growtopiagame.com/google/callback
     response_type= code, scope=openid profile email
     state        = <acak>   ⚠️ WAJIB — tanpa ini server GT balas HTTP 500
2. pilih akun Google + setujui              (MANUAL, di browser)
3. Google redirect -> /google/callback?code=<CODE>&state=<STATE>
4. server GT tukar code -> 302 -> /player/link/dashboard/validate/<payload>
5. GET payload -> {"status":"success","token":"<LTOKEN>"}
6. kirim ke server game sebagai  ltoken|<token>
```

> **⚠️ Jebakan `state` (ditemukan 2026-09-30 dari error nyata):**
> callback **tanpa** `state` → HTTP 500 berisi halaman *"Page not found [404]"*.
> Pesan itu menyesatkan: kelihatan seperti `code` salah/kedaluwarsa, padahal
> `code`-nya **valid** dan yang kurang cuma `state`. `state` kosong juga 500,
> jadi harus ada isinya — **nilainya tidak diperiksa** server (acak pun diterima).
>
> **⚠️ Kalau "waktu habis" padahal kamu sudah menyetujui:** URL `?code=` hanya
> sekilas (server langsung 302). Chrome harus dibuka di `about:blank` dulu, lalu
> CDP dipasang, baru dinavigasi — sudah otomatis di kode. Kalau tetap gagal,
> pakai jalur manual `--code` (lihat di bawah).


Langkah 1 sudah diuji: Chrome diarahkan ke URL itu dan **benar-benar mendarat di
halaman login Google**. Langkah 4–5 sudah diuji: callback menghasilkan redirect
ke `/player/link/dashboard/validate/...` (pola yang sama dengan alur GrowID).

### Rantai token dari HP (belum terbukti)

```
save.dat → Token (472 char)
   → POST login.growtopiagame.com/player/growid/checktoken
        refreshToken=<Token>   clientData=<blok base64>   ← clientData WAJIB
   → yang DIHARAPKAN: {"status":"success","message":"Account Validated.",
                       "token":"<428 char>"}
```

**Yang benar-benar terjadi:** balasannya `{"status":"redirect","message":"Token
is invalid."}` — identik untuk token ngawur maupun kosong. Jadi `clientData`
wajib, tapi bentuknya belum cocok. Kalau kamu punya akun Google, **pakai
`--google-browser`** dan lewati jalur ini.

### Login Google — sudah otomatis (cara Growlauncher)

**✅ Terbukti 2026-09-30.** Klaim lama "Growtopia tidak menyediakan client_id
publik" ternyata **salah**: Growtopia **punya** OAuth client bertipe **Web**
yang `client_id`-nya tertanam di `base.apk` resmi (namanya
`default_web_client_id`):

```
389994132396-4s6ol46f60831v5blfpci7lnmsdnh8br.apps.googleusercontent.com
```

Karena bertipe **Web** (bukan Android), Google **mengizinkan** `redirect_uri`
ke `https://login.growtopiagame.com/google/callback` — dan server Growtopia
memang punya route itu (balas `500` saat kosong, bukan `404`).

Jadi **tidak perlu** SDK native dan **tidak perlu** sandi Google:

```
   [1] Lucifer buka browser            [2] Kamu pilih akun       [3] ltoken didapat
   ┌────────────────────────┐         ┌────────────────┐       ┌──────────────────┐
   │ accounts.google.com    │ ──────> │ pilih akun +   │ ────> │ login.growtopia  │
   │ ?client_id=<GT>        │         │ setujui        │       │ /google/callback │
   │ &redirect_uri=...      │         │ (MANUAL)       │       │ → token          │
   └────────────────────────┘         └────────────────┘       └──────────────────┘
```

```bash
.venv/bin/lucifer login --google-browser --verify
```

Catatan jujur: langkah **[2] tetap butuh kamu** — memilih akun Google tidak bisa
diotomasi tanpa menyimpan sandi Google (yang sengaja **tidak** dilakukan Lucifer,
karena itu yang bikin akun berisiko). Tapi **sekali saja**; setelah `ltoken`
tersimpan, bot jalan mandiri dan bisa refresh sendiri.

```
   [1] Lucifer buka browser          [2] Kamu pilih akun      [3] ltoken didapat
   ┌───────────────────────┐        ┌─────────────────┐     ┌────────────────────┐
   │ accounts.google.com   │        │ pilih akun +    │     │ login.growtopia    │
   │ ?client_id=<GT>       │ ─────► │ setujui (MANUAL)│ ──► │ /google/callback   │
   │ &redirect_uri=...     │        │                 │     │ → {token: ltoken}  │
   └───────────────────────┘        └─────────────────┘     └────────────────────┘
```

#### Cara A — ambil `ltoken` dari clientData

Klien Growtopia menyimpan `clientData` yang berisi `ltoken` di file konfigurasi
lokal. Ambil dari salah satu lokasi berikut:

| Platform | Lokasi |
|---|---|
| Windows | `%LOCALAPPDATA%\Growtopia\` — file `clientData` / `save.dat` |
| Android | `/data/data/com.rtsoft.growtopia/files/` (butuh root) |
| Linux (Wine) | `~/.wine/drive_c/users/*/AppData/Local/Growtopia/` |

`clientData` berbentuk baris `kunci|nilai`, cari baris `ltoken|...`.
Bisa juga terlihat di URL dashboard: `login.growtopiagame.com/player/login/dashboard?...`
lalu lihat parameter `ltoken` / `tokenUrl` di respons JSON.

> **Penjelasan rinci "apa yang dikirim/diambil dari login.growtopiagame.com"**
> ada di [`docs/login-flow.md`](docs/login-flow.md) — termasuk pembacaan dump
> TLS (`16 03 01 ...`) dan bukti setiap field. Jalankan sendiri dengan:
> `.venv/bin/python tools/bukti_login.py`

Setelah dapat, simpan:

```bash
.venv/bin/lucifer login --ltoken "<LTOKEN>" --name "NamaGrowID" --verify
```

`--verify` mengecek token ke server dulu (`/player/growid/checktoken`) sehingga
kamu tahu token masih hidup sebelum dipakai. Hasilnya tersimpan di
`data/accounts.json` dengan izin `600`.

#### Cara B — tukar `id_token` Google jadi `ltoken`

Kalau kamu punya `id_token` (OpenID Connect) dari login Google:

```bash
.venv/bin/lucifer login --google "<ID_TOKEN>" --name "NamaGrowID"
```

Token ditukar ke `login.growtopiagame.com/player/social/login?social_login=google`
dan hasilnya (`ltoken`) disimpan. Ambil `id_token` dengan salah satu cara:

- **Playground OAuth Google** — https://developers.google.com/oauthplayground
  (scope `openid email`), lalu salin `id_token`.
- **Login manual di browser** — buka DevTools → Network, login Growtopia dengan
  Google, cari request ke `oauth2.googleapis.com` atau `accounts.google.com`,
  salin `id_token` dari respons.
- **Dari aplikasi Android** — `GoogleSignIn.getLastSignedInAccount()`
  → `getIdToken()` (butuh kode native).

#### Cara C — GrowID / legacy (paling sederhana)

```bash
.venv/bin/lucifer login --growid "NamaKamu"          # sandi ditanya diam-diam
.venv/bin/lucifer login --growid "NamaKamu" -p "sandi"
```

#### Cara D — di dalam skrip Lua (gaya Lucifer)

```lua
-- ltoken siap pakai (paling andal)
local akun = { type = TOKEN, token = "ISI_LTOKEN", growid = "NamaKamu" }
addBot(akun)

-- Google: butuh social_token (id_token)
addBot({ type = GOOGLE, mail = "email@gmail.com", password = "sandi", secretKey = "" })

-- Legacy
addBot({ type = LEGACY, growid = "NamaLama", password = "sandiLama" })

-- atau bentuk lama
addBot("NamaGrowID", "sandi")
```

Konstanta `LEGACY`, `GROWID`, `GOOGLE`, `UBICONNECT`, `TOKEN`, `APPLE`, `STEAM`
tersedia langsung di Lua (lihat `examples/07_login_google.lua`).

#### Menyegarkan `ltoken`

`ltoken` bisa kedaluwarsa. Simpan `tokenUrl` (ada di clientData) lalu segarkan:

```bash
.venv/bin/lucifer login --ltoken "<LTOKEN>" --verify   # cetak token baru bila perlu
```

Di Lua: `bot:setToken("ltoken_baru")`.

> **Catatan jujur:** karena butuh langkah manusia sekali di awal, login Google
> **tidak** bisa dibuat "tinggal jalan" tanpa interaksi. Setelah `ltoken`
> tersimpan, bot bisa jalan mandiri. Tapi ingat: **cara mendapatkan `ltoken`
> dari HP belum terbukti berhasil** (lihat status di atas) — jalur yang paling
> mungkin berhasil saat ini adalah akun GrowID/legacy, atau `lucifer capture`
> dengan CA terpasang di HP.

---

## Pakai

```bash
lucifer doctor                     # cek lingkungan
lucifer probe                      # uji handshake ke server GT
lucifer items data/items.dat -s Dirt   # cari item
lucifer scripts                    # daftar skrip
lucifer check examples/*.lua        # cek sintaks Lua
lucifer lua examples/01_hello.lua --connect
lucifer run                        # bot + skrip + hot reload
lucifer web --host 0.0.0.0 --port 8787   # dashboard (buka di browser)
lucifer desktop                    # GUI native GTK3 (jendela sendiri)
lucifer ltoken --file client_data.txt --save   # ambil ltoken dari proxy debug
```

### Dashboard: login langsung dari UI

Dashboard web (`lucifer web`) juga punya panel **Login Akun** — tidak perlu
menyentuh terminal lagi:

1. Jalankan `lucifer web` lalu buka `http://127.0.0.1:8787` (atau pakai GUI
   native lewat `lucifer desktop`).
2. Pilih tabnya:

   | Tab | Isi | Kapan dipakai |
   |---|---|---|
   | **Pakai ltoken** | tempel ltoken **atau** seluruh blok `client_data` | kalau kamu sudah punya ltoken |
   | **GrowID** | nama GrowID + sandi | akun GrowID biasa |

3. Centang **langsung connect** kalau mau bot langsung nyambung ke Growtopia.
4. Klik **Simpan & Login**.

Panel **Akun Tersimpan** di bawahnya menampilkan semua akun dengan tombol
**Connect / Putus / Hapus**, plus **Connect semua**. Akun disimpan ke
`data/accounts.json` dengan izin `600`; sandi dan token **tidak pernah**
ditampilkan kembali di UI (hanya penanda "punya ltoken / punya sandi").

Kalau kamu menempel blok `client_data` mentah, ltoken diambil otomatis —
pengurainya ada di sisi browser (JS) **dan** di `tools/ltoken.py`, keduanya
mendukung tiga bentuk: per baris, satu baris dipisah `|`, dan base64.

### Store / Auto Buy

Toko Growtopia **bukan** daftar `item|`. Server mengirim seluruh isi toko
sebagai markdown UI lewat `OnStoreRequest` (variant CallFunction):

```
enable_tabs|<n>
add_tab|<nama>
add_banner|...
embed_data|item_id|<id>|price|...|count|...     <- SATU entri item
add_button|...                                    <- tombol entri (25 field)
add_image|... / add_custom_button|...
```

Satu **pack** berisi beberapa `embed_data`, jadi daftar item harus dibaca
dari situ, bukan dari satu id.

Permintaan beli memakai literal di `libgrowtopia.so` @`0x6fe5f1`:

```
action|buy
item|<kode atau id>
```

Satu field saja. (`itemID` dipakai `trash` / `mod_trade` / `itemfavourite`,
**bukan** `buy`.)

Konfirmasi pembelian:

| Paket | Arti |
|---|---|
| `OnSetBux(val, ...)` | gem berubah → biaya terpotong |
| `ModifyItemInventory` | barang masuk inventaris |
| `OnStorePurchaseResult` / `OnStoreBuyConfirm` | pembelian IAP (gem asli) |

Bot menyimpan `store_raw` (payload mentah) dan `store_items` (hasil parse
`_baca_store`). Auto Buy menunggu gem berubah setelah mengirim `buy`; kalau
gem tidak berubah dalam `TIMEOUT_BALAS_MS`, dihitung gagal.

> **Belum selesai:** pemetaan 25 field `add_button` dan tombol yang dipakai
> `dialog_return` saat membeli **pack**. Butuh satu payload `OnStoreRequest`
> nyata (`LUCIFER_DUMP=1` → `/tmp/opencode/dump_store.bin`) sebelum
> Auto Buy diarahkan ke entri pack.

### Fitur otomasi (padanan deltaX)

`lucifer/features.py` mengisi menu yang **bisa** dibawa ke klien protokol —
semuanya mengirim paket asli ke server, tidak ada satu pun yang memalsukan
tampilan. Nama alias mengikuti `assets/menu.json` deltaX supaya mudah
dicocokkan.

| Fitur | Alias deltaX | Isi |
|---|---|---|
| AutoFarm | `autofarm_start`, `autofarm_item_picker`, `autofarm_target_tile` | **pecah blok → ambil → taruh blok lagi** di tile yang sama, pakai `hit()`/`collect()`/`place()` |
| Automation | `automation_start`, `automation_item`, `automation_mode` | **panen tanaman → ambil → tanam bibit** (terpisah dari AutoFarm) |
| AutoCollect | `autocollectstart`, `auto_collect_radius`, `auto_collect_tile` | ambil objek jatuh di radius, atau hanya di tile terpilih |
| Spammer | `spammer_config_start`, `spammer_config_texttospam` | chat berkala, urut atau acak |
| AutoDrop | `cheat_config_fastdrop_active`, `cheat_config_fasttrash_active` | drop/trash item di atas batas jumlah |
| AutoWrench | `autowrench_start` | wrench tile yang ditandai untuk melihat isinya |
| FindPath | `findpath_config_blockjump`, `findpath_config_teleport_path` | BFS yang menghitung tile terpasang sebagai penghalang |
| Replay | `replay_record_active`, `replay_play_active`, `replay_loop` | rekam aksi keluar lalu putar ulang (JSON di `data/replay/`) |
| Growscan | `cheat_growscan_open` | pindai blok/tanaman/objek jatuh di dunia |
| **Auto Buy** | `autobuy_start`, `autobuy_set_item`, `autobuy_set_harga` | beli di Store saat gem cukup (`action\|buy\nitem\|<kode>`), berhenti bila gem kurang |
| ModExit | `modexit_*` | keluar dunia otomatis saat moderator terdeteksi |
| Chat commands | `cmd_warp`, `cmd_back`, `cmd_finditem`, `cmd_gscan`, `cmd_pullall`, `cmd_alias`, `cmd_bind` | perintah `/...` yang ditangani lokal, tidak dikirim ke server |

AutoFarm dan Automation sengaja dipisah: yang pertama bekerja pada **blok**
(pecah & taruh balik), yang kedua pada **tanaman** (panen & tanam bibit).
Mencampurnya membuat bot memecah tanaman yang belum siap panen.

Catatan AutoFarm:

- Sasaran = `target_tile` kalau diisi; kalau kosong, hanya tile dalam
  **jangkauan 4 tile** (server menolak `tileChange` yang lebih jauh).
- Blok dipukul **sampai benar-benar pecah** — jumlah pukulan mengikuti
  `block_health` di items.dat (tiap blok beda), dan konfirmasi diambil dari
  `SendTileUpdateData` / `SendTileUpdateDataMultiple` (tank type 5/6).
- Blok baru ditaruh setelah server mengonfirmasi tile kosong, jadi tidak
  pernah menaruh di atas blok yang masih utuh.
- Sign, pintu, lock, mailbox, bulletin, dan donation box dilewati — bukan
  sasaran pecah.

Dipanggil dari Lua dengan nama yang sama (`autofarm_start()`,
`spammer_add("halo")`, `growscan()`, `command("/warp FARM")`, …), semuanya
menerima `bot=` opsional untuk multi-akun.

**Yang tidak dipindah** karena butuh render/memori klien (bukan paket):
`cheat_esp_player`, `cheat_esp_item`, `cheat_esp_ghost`, `noclip_and_ghost`,
`features_invis_v2`, `visual_inventory_*`, `Antibounce`, `Gravity`, `Antipunch`,
`cheat_config_moonwalk`, `cheat_config_fastfall`, `ModFly`, `Night Vision`.
Klien bot tidak punya layar atau memori game untuk diubah — fitur itu tidak
punya arti di sini.

### Dashboard: peta dunia, fitur, dan skrip

Selain panel login, dashboard punya:

- **Peta Dunia** — `<canvas>` yang menggambar tile dunia (warna dari hash item
  id), bibit siap panen, objek, dan posisi pemain.
- **Fitur Otomasi** — tombol Start/Stop untuk AutoFarm, AutoCollect, Spammer,
  AutoDrop, plus Rekam/Putar/Simpan replay dan Growscan.
- **Skrip Lua** — kotak editor + tombol **Simpan** dan **Jalankan**
  (`POST /api/script/save`, lalu `run <nama>.lua`).

Endpoint: `GET /api/features`, `GET /api/map`, `POST /api/feature`,
`POST /api/script/save`, `GET /api/dialog`.

### Proxy SOCKS5

Growtopia butuh **UDP**, jadi proxy TCP-only tidak berguna walaupun lolos tes
TCP. Dua hal penting:

- `enet_host_use_proxy()` di `enet/enet.so` **rusak** (kirim greeting SOCKS5
  lalu menutup soket). Karena itu `lucifer/udprelay.py` dipakai: ENet bicara
  UDP biasa ke `127.0.0.1:<port>`, relay yang membungkus tiap datagram dengan
  header SOCKS5.
- `ProxyPool` menyimpan kunci `(host, port, user, passwd)`. Proxy model
  *rotating gateway* memakai host:port sama untuk ribuan kredensial, dan tiap
  kredensial keluar lewat IP berbeda — dedupe `host:port` saja membuang hampir
  semua proxy yang sah.

Uji proxy bertahap: `uji()` (TCP) → `uji_udp()` (DNS lewat UDP ASSOCIATE,
membuktikan relay benar-benar meneruskan) → `uji_enet()` (handshake ENet ke
server Growtopia lewat relay yang sama dengan yang dipakai bot).

```bash
curl -X POST localhost:8787/api/proxy \
  -d '{"label":"main","proxy":"socks5://user:pass@host:port"}'
```

### Status bot: level, gems, malady

| Data | Sumber | Catatan |
|---|---|---|
| gems | variant `OnSetBux` arg1 | dikirim server tiap gem berubah |
| level | `add_player_info\|nama\|level\|xp\|xp_next\|` di dialog profil | retail **tidak** mengirim level lewat paket status |
| malady | `MALADY_*` / `ILLNESS_*` di dialog profil | status sakit kategori Surgeon; kosong = tidak kena |

Level dan malady hanya muncul di dialog hasil **wrench diri sendiri**, jadi
bot memintanya sekali per world (`action|wrench` netid sendiri). Ada juga
tombol **Profil** di GUI dan perintah `profil` untuk meminta ulang.

> Jangan tertukar `OnDialogRequest`: markup dialog ada di **argumen index 1**,
> bukan index 2. Membaca index 2 membuat dialog selalu kosong.

### Aplikasi desktop

`lucifer desktop` menjalankan server dashboard di latar lalu membuka **GUI native
GTK3** (`desktop/src/*.cpp`) — jendela sendiri, bukan browser. Backend Python
tetap yang memegang protokol; GUI hanya mengirim JSON lewat loopback HTTP.

Perintah lain:

```bash
lucifer desktop --status   # cek server
lucifer desktop --stop     # matikan server
lucifer-desktop            # perintah yang sama (launcher .desktop)
bash deploy/pasang-desktop.sh   # build GUI + pasang ikon + entri menu
```

Launcher dipasang oleh `deploy/pasang-desktop.sh` dengan `--repo DIR`, jadi
**Lucifer Linux** muncul di daftar aplikasi (Activities → cari "Lucifer") dan
backend selalu jalan dari direktori repo (supaya `data/items.dat` kebaca).

### GUI native (GTK3)

Lima tab: **Bots · Executor · Proxy · Database · Settings**.

| Bagian | Isi |
|---|---|
| Daftar bot | kolom PILIH (centang) · BOT · NAMA · **LEVEL** · **MALADY** · PING · STATUS · PROXY · DUNIA · POSISI · GEMS |
| Panel kiri | Connect/Disconnect (+Semua), panah gerak, Warp, Respawn, Collect, **Profil**, kelola akun |
| Detail bot | Fitur (14 kategori: 13 deltaX + Auto Buy) · Peta · Console · Chat · Inventaris · Paket · Info |
| Proxy | pool SOCKS5, uji UDP relay + ENet handshake sungguhan |
| Database | cari item + sprite 24×24 |

Window memakai `gdk_monitor_get_workarea` + `gtk_window_maximize`, tanpa
headerbar server-side (ramah Hyprland); minimize/close ada di toolbar.

**Pilih banyak bot**: klik baris = pilih, klik 2× = buka detail. Centang di
kolom PILIH adalah sumber kebenaran (`std::set<std::string> dipilih_`), jadi
Connect/Warp/Respawn bisa menyasar banyak bot sekaligus.


---

## API Lua Lucifer V1.8

Seluruh permukaan API Lucifer diimplementasikan di `lucifer/lua_api.py`.

**Global** — `sleep`, `print`, `read`, `write`, `getInfo`, `getInfos`, `addBot`,
`addUbiBot`, `removeBot`, `getBot`, `addEvent`, `removeEvent`, `removeEvents`,
`listenEvents`, `unlistenEvents`, `runThread`, `removeColor`, `getUsername`,
`getProxyManager`, `getWorldManager`, `addProxy`, `removeProxy`.

**Shortcut** — `getWorld`, `getInventory`, `getLocal`, `getTile`, `getTiles`,
`getTilesSafe`, `getObject`, `getObjects`, `getPlayer`, `getPlayers`, `hasAccess`.

**Struct** — `Bot`, `World`, `Tile`, `Player`, `Inventory`, `InventoryItem`,
`ItemInfo`, `NetObject`, `NPC`, `Signal`, `Console`, `Log`, `Login`, `PathNode`,
`Growscan`, `GameUpdatePacket`, `Vector2`, `Vector3`, `variant`, `variantlist`,
`RTParam`, `RTVAR`, `Embed`, `Webhook`, `HttpResult`, `HttpClient`,
`ProxyManager`, `WorldManager`.

**Enum** — `BotStatus`, `CaptchaStatus`, `Method`, `Event`, `VariantType`,
`GeigerArea`, `Role`, `Bubble`, `StorageType`, `Proxy`, `PlayerState`,
`TileType`, `TileFlag`, `NpcType`, `PacketType`, `LoginMethod`.

### Contoh

```lua
bot = getBot()

-- tunggu online
local n = 0
while bot.status ~= BotStatus.online and n < 150 do sleep(200); n = n + 1 end

-- dunia & inventaris
local world = bot:getWorld()
print(string.format("%s %dx%d, %d tile", world.name, world.x, world.y, world.tile_count))

local tile = getTile(10, 10)
if tile:canHarvest() then bot:hit(10, 10) end

-- aksi
bot:say("halo dunia")
bot:warp("FARM")
bot:place(10, 11, getInfo("Dirt").id)
bot:collect(4, 120)

-- event
function OnTextPacket(msg)
  if msg.msg then print("[log] " .. removeColor(msg.msg)) end
end
addEvent(Event.game_message, OnTextPacket)
listenEvents(60)

-- thread terpisah
function pesan_berkala(teks, jeda)
  while true do getBot():say(teks); sleep(jeda) end
end
runThread(pesan_berkala, "Bot aktif", 10000)
```

> **Catatan penting:** di Lucifer Linux, `sleep()` **tetap memompa event** —
> event dari server terus dikirim ke handler Lua selama skrip menunggu. Ini
> sama seperti perilaku Lucifer dan bikin skrip gaya lama jalan apa adanya.

---

## Skrip contoh

| File | Isi |
|---|---|
| `01_hello.lua` | connect, tunggu online, kirim pesan |
| `02_events.lua` | `addEvent` / `listenEvents`, tangani console & logon_fail |
| `03_auto_farm.lua` | auto farm lengkap: panen, tanam, ambil objek, laporan |
| `04_multibot.lua` | banyak bot, connect bersamaan, `runThread` per bot |
| `05_http_webhook.lua` | `HttpClient`, `Webhook` Discord, `RTVAR`, file IO |
| `06_pathfinding.lua` | `getPath`/`moveTile`, `collect`, hitung blok di dunia |
| `07_login_google.lua` | semua jenis login: LEGACY/GROWID/GOOGLE/TOKEN/APPLE |
| `08_delta_features.lua` | autofarm/autocollect/spammer/findpath/replay lewat alias deltaX |
| `baru.lua` | clear world (TornAi): pukul sampai kosong, lewati tile terkunci |
| `isan.lua` | clear world + penjaga anti-ercon (`TileBalas`/`TileDitolak`) |

---

## Uji

Tanpa jaringan (cepat, dipakai tiap perubahan):

```bash
.venv/bin/python tests/test_unit.py      # 408 lulus
.venv/bin/python tests/test_features.py  # 118 lulus
.venv/bin/python tests/test_modmenu.py   # 358 lulus
.venv/bin/python tests/test_web.py       # 33 lulus
```

Semua memakai `unittest` bawaan Python — tidak perlu pytest. Skrip mencetak
`lulus: N gagal: 0` dan keluar dengan kode ≠ 0 kalau ada yang gagal.

Uji nyata ke server Growtopia asli (butuh jaringan):

```bash
.venv/bin/python tests/test_integration.py
```

Isi yang diuji tanpa jaringan: codec Tank/Variant, parser items.dat dan
dunia, semua aksi bot beserta isi paket yang dikirim (`hit` = type 3 value 18,
`place` = type 3 value item, `collectObject` = type 11 dengan posisi piksel),
parser `SendTileUpdateDataMultiple`, `ModifyItemInventory`, filter malady,
pool proxy, dan siklus autofarm (pecah → taruh) dengan server yang diam
maupun yang mengonfirmasi.

---

## Struktur

```
lucifer-linux/
├── enet/                 # ENet single-header, dipatch Growtopia
├── lucifer/
│   ├── enet.py           # binding ctypes ENet (patch new-packet/CRC32/range coder)
│   ├── protocol.py       # codec Tank, Variant, VariantList, teks + tabel 75 action
│   ├── hash.py           # Growtopia hash (TLSH) untuk login
│   ├── items.py          # pembaca items.dat (16.480 item v27)
│   ├── world.py          # parser dunia, tile update (type 5/6), flag tile
│   ├── bot.py            # bot: koneksi, state, aksi (say/warp/place/hit/...)
│   ├── features.py       # otomasi gaya deltaX + SKEMA_FITUR (14 kategori)
│   ├── lua_api.py        # API Lua Lucifer V1.8 lengkap
│   ├── compat_deltax.py  # jembatan nama fungsi Lua gaya deltaX
│   ├── proxy.py          # SOCKS5: uji TCP/UDP/ENet
│   ├── proxypool.py      # pool proxy (kunci host+port+user+passwd)
│   ├── udprelay.py       # jembatan UDP lokal <-> SOCKS5 UDP ASSOCIATE
│   ├── runner.py         # runner + hot reload
│   ├── cli.py            # perintah `lucifer`
│   └── web.py            # dashboard web
├── desktop/              # GUI native GTK3 (C++)
│   └── src/              # ui.cpp (tampilan), data.cpp (handler), http.cpp (klien)
├── deploy/               # pasang-desktop.sh, install.sh, ikon, .desktop, service
├── android/push/         # APK kecil pengirim ltoken dari HP (Java)
├── examples/             # skrip contoh .lua (siap pakai)
├── scripts/              # skrip kamu sendiri
├── tests/                # uji unit + uji nyata ke server Growtopia asli
├── Makefile
└── requirements.txt
```

---

## Temuan protokol yang mengubah kode

Semua di bawah dibuktikan dari paket nyata (jurnal `in`/`out`) atau literal
di `libgrowtopia.so` 5.58 — bukan asumsi.

| Temuan | Bukti | Akibat kalau salah |
|---|---|---|
| `tileChange` = Tank **type 3**; `value` 18 = Fist, 32 = Wrench, selain itu id item | paket klien asli | pukul mengirim Wrench, blok tak pernah pecah |
| `vector_x/vector_y` = posisi **PEMAIN**, `int_x/int_y` = tile | `place tile=(52,26) pos=(1606,834)` | server balas `cant_place_tile` |
| `OnSetPos` saat bergerak = **koreksi posisi**, bukan info spawn | `18:00:19 in OnSetPos (2080,736)` ×5 | bot teleport → shadowban |
| Nama dari server berakhiran dua backtick (`OnSpawn` mengirim `Isanlucuuu` + dua backtick) | `name\|` di `OnSpawn` | bot salah kenal diri sendiri → echo-nya dibuang → peta tidak update |
| Pola kode warna harus menerima backtick sebagai karakter kode | pola lama `[a-zA-Z0-9#]` tidak cocok dengan dua backtick | nama tidak pernah cocok dengan nama akun |
| `audio/punch_locked.wav` = tile terkunci | 8 pukulan ditolak tile yang sama | bot mukul selamanya → ercon |
| Echo `TileChangeRequest` pemain lain tetap **mengubah peta** | `in type=3 netid=2` | peta bot buta terhadap perubahan orang lain |
| Growtopia **tidak** meng-echo `State` milik sendiri | 111 `out State` → 0 `in State` | menunggu echo = bot diam selamanya |
| `int_x` pada tank type 11 = jumlah item (count) | `out type=11 tile=(30,0) value=11 int_x=30` | `collectObject` mengirim 0 → selalu ditolak |
| uid objek = counter `last_uid + 1` | drop 10, 11, 12 | uid karangan → server tolak |
| `OnStoreRequest` = markdown UI, bukan `item\|` | parser `0x17483f8` | isi toko hilang total |

---

## Catatan hukum & etika

Proyek ini untuk **pembelajaran protokol jaringan** dan otomasi akun sendiri.
Bot otomatis melanggar Terms of Service Growtopia dan bisa berujung ban.
Gunakan hanya di akun milikmu sendiri dan dengan risiko yang kamu sadari.

---

## Lisensi

MIT.
