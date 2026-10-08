# Lucifer Linux

**API Lua Lucifer V1.8 untuk Growtopia — berjalan native di Linux.**

Klien Growtopia asli (ENet yang dipatch Ubisoft + codec Tank/Variant + CRC32 +
range coder), mesin skrip Lua lengkap, dan dashboard web. Skrip ditulis dengan
gaya Lucifer, jadi skrip Lucifer yang sudah ada bisa langsung dipakai.

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
  ✓ items.dat dimuat  15934 item v24
  ✓ skrip Lua dieksekusi
  ✓ event server sampai ke handler Lua  Fail to login. Please try again in 30 seconds.
  ✓ bot membuat koneksi ENet nyata  213.179.209.175:17047

 lulus: 13   gagal: 0
SEMUA UJI NYATA LULUS — rantai Lua -> ENet -> Growtopia bekerja
```

Balasan *"Fail to login"* justru **bukti** bahwa paket kita diterima dan dijawab
server asli — kredensial di tes sengaja tidak valid.

`items.dat` v24 terbaca sempurna: **15.934 item**, dengan ID asli
(World Lock = 242, Dirt = 2, Grass Seed = 17, Wrench = 32).

---

## Pasang

```bash
git clone <repo> lucifer-linux && cd lucifer-linux
make                  # kompilasi ENet patch Growtopia + siapkan venv
make doctor           # cek lingkungan
make probe            # uji handshake ke server Growtopia asli
```

Butuh: Python ≥ 3.10, `g++`/`clang++`, `python3-venv`.

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
lucifer desktop                    # buka sebagai APLIKASI DESKTOP (jendela sendiri)
lucifer ltoken --file client_data.txt --save   # ambil ltoken dari proxy debug
```

### Dashboard: login langsung dari UI

Dashboard punya panel **Login Akun** — tidak perlu menyentuh terminal lagi:

1. Jalankan `lucifer desktop` (atau `lucifer web` lalu buka `http://127.0.0.1:8787`).
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

### Aplikasi desktop

`lucifer desktop` menjalankan server dashboard di latar lalu membukanya di
Chrome mode `--app`: jendela sendiri, tanpa address bar dan tab, dengan ikon
Lucifer di dock. Perintah lain:

```bash
lucifer desktop --status   # cek server
lucifer desktop --stop     # matikan server
lucifer-desktop            # perintah yang sama (launcher .desktop)
```

Launcher GNOME-nya dipasang oleh `deploy/install.sh`, jadi **Lucifer Linux**
juga muncul di daftar aplikasi (Activities → cari "Lucifer").

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

---

## Struktur

```
lucifer-linux/
├── enet/                 # ENet single-header, dipatch Growtopia
├── lucifer/
│   ├── enet.py           # binding ctypes ENet (patch new-packet/CRC32/range coder)
│   ├── protocol.py       # codec Tank, Variant, VariantList, teks
│   ├── hash.py           # Growtopia hash (TLSH) untuk login
│   ├── items.py          # pembaca items.dat (15.934 item v24)
│   ├── world.py          # parser dunia + flag tile
│   ├── account.py        # login: legacy, growid, google, apple, ubi, token
│   ├── bot.py            # bot: koneksi, state, aksi (say/warp/place/hit/...)
│   ├── lua_api.py        # API Lua Lucifer V1.8 lengkap
│   ├── runner.py         # runner + hot reload
│   ├── cli.py            # perintah `lucifer`
│   └── web.py            # dashboard web
├── examples/             # skrip contoh .lua (siap pakai)
├── scripts/              # skrip kamu sendiri
├── tests/                # uji nyata ke server Growtopia asli
├── Makefile
└── requirements.txt
```

---

## Catatan hukum & etika

Proyek ini untuk **pembelajaran protokol jaringan** dan otomasi akun sendiri.
Bot otomatis melanggar Terms of Service Growtopia dan bisa berujung ban.
Gunakan hanya di akun milikmu sendiri dan dengan risiko yang kamu sadari.

---

## Lisensi

MIT.
