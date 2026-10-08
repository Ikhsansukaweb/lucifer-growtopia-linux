# Apa yang diambil dari `login.growtopiagame.com`?

Jawaban singkat: **ltoken**. Itu satu-satunya hal penting yang diambil dari sana.

Dokumen ini menjelaskan dua hal yang sering tertukar:

1. **Lapisan TLS** (`16 03 01 ...`) — cuma bungkus, tidak berisi data login.
2. **Isi sebenarnya** — dua request HTTP yang membawa nama akun, sandi, dan
   mengembalikan token.

Semua di bawah ini **diverifikasi langsung ke server asli** (`tools/bukti_login.py`),
bukan dari dokumentasi atau tebakan.

---

## 1. Dump `16 03 01 ...` itu apa?

Itu **TLS handshake**, bukan data login. Kalau dump itu dibaca record per record:

| Record | Isi | Artinya |
|---|---|---|
| `16 03 01 06 c8` | Handshake, panjang 1736 | Klien bilang "saya mau HTTPS" |
| `01 00 06 c4` | **ClientHello** | Daftar cipher + ALPN (`h2`, `http/1.1`) |
| `16 03 03 00 6c` | Handshake, panjang 108 | Server menjawab |
| `02 00 00 68` | **ServerHello** | Server memilih cipher (`c0 2f` = ECDHE-RSA-AES128-GCM) |
| `16 03 03 1a 16` | Handshake, panjang 6678 | Server kirim sertifikat |
| `0b 00 1a 12` | **Certificate** | Sertifikat `*.growtopiagame.com` — penerbit **Sectigo**, pemilik **Ubisoft Divertissements Inc.** |

**Yang penting: `ApplicationData` (`17 03 03 ...`) TIDAK ADA sama sekali.**

Artinya dump itu **tidak memuat** nama akun, sandi, maupun ltoken. Semuanya
dikirim *setelah* handshake selesai, dalam bentuk terenkripsi. Yang terlihat di
dump cuma "bungkus" dan perkenalan sertifikat — makanya sniffing paket mentah
tidak akan pernah memunculkan data login.

> Untuk melihat isinya, jangan sniff paket mentah. Pakai **proxy debug**
> (HTTP Toolkit / mitmproxy) yang membuka TLS. Hasilnya seperti di bawah.

---

## 2. Isi sebenarnya — dua langkah

### Langkah 1 — yang DIKIRIM

```
POST https://login.growtopiagame.com/player/login/dashboard
User-Agent: UbiServices_SDK_2022.Release.9_PC64_ansi_static
Content-Type: application/x-www-form-urlencoded

data=<base64 dari blok "key|value" di bawah>
```

Blok `key|value` (inilah yang di-base64 jadi field `data`):

```
tankIDName|ikhsan_contoh        <- NAMA AKUN
tankIDPass|<sandi>              <- SANDI (terbuka di sini!)
requestedName|
f|1
protocol|225                    <- versi protokol game
game_version|5.4                <- versi klien
fz|21905432
cbits|0
player_age|20
GDPR|2
FCMToken|
category|_-5100
totalPlaytime|0
klv|615d435e8d88...             <- checksum dari secret GT
hash2|-716928004
meta|2DWc//PLmjPidHam/...       <- dari server_data.php (anti-replay)
fhash|-716928004
rid|FA69C0A813168F387A48D24FC59A3E93   <- request id acak
platformID|0,1,1
deviceVersion|0
country|us
hash|123456789
mac|a5:44:28:6b:d9:11           <- MAC address (di-spoof)
wk|6D35103013A164B1303E434B919A9699
zf|-1623530258
lmode|1
```

Field yang benar-benar menentukan: **`tankIDName`**, **`tankIDPass`**, `protocol`,
`game_version`, `klv`, `meta`, `rid`, `mac`, `platformID`, `lmode`.

### Langkah 2 — yang DIAMBIL

```
POST /player/login/dashboard
   -> HTTP 302
   -> Location: /player/link/dashboard/validate/eyJpdi...VZRR

GET  https://login.growtopiagame.com/player/link/dashboard/validate/eyJpdi...VZRR
   -> HTTP 200
   -> body JSON:
```

```json
{
  "status":      "success",
  "message":     "",
  "token":       "<--- INI ltoken-nya",
  "url":         "172.65.0.0",
  "accountType": "growtopia",
  "accountAge":  "2"
}
```

**`token` itulah `ltoken`** yang dipakai bot untuk login ke server game lewat
ENet. Kalau gagal, bentuknya:

```json
{"status":"failed","message":"Please try login again.","token":"","url":"","accountType":"growtopia","accountAge":"2"}
```

> ⚠️ **Redirect wajib diikuti dengan GET.** Kalau `POST` dikirim ke URL
> `validate`, server menjawab **405**. Ini kesalahan umum saat meniru alurnya.

---

## 3. Jadi urutan lengkapnya

```
 1. GET  https://www.growtopia1.com/growtopia/server_data.php
         -> server=213.179.209.175, port=17043, meta=<base64>

 2. POST https://login.growtopiagame.com/player/login/dashboard
         data=<base64 tankIDName|... tankIDPass|... klv|... meta|...>
         -> 302

 3. GET  /player/link/dashboard/validate/<payload>
         -> 200 {"status":"success","token":"<LTOKEN>"}

 4. ENet ke 213.179.209.175:17043
         paket login berisi: tankIDName, ltoken (bukan sandi lagi!), rid, mac, ...

 5. Server balas ServerHello + OnSuperMainStartAcceptLogon
         -> bot masuk game
```

**Poin penting:** sandi **hanya** dipakai di langkah 2. Setelah dapat ltoken,
langkah 4 memakai ltoken — sandi tidak dikirim lagi. Karena itu ltoken bisa
disimpan dan dipakai berulang tanpa login ulang.

---

## 4. Cara melihat sendiri (membuktikan)

Jalankan skrip bukti yang ikut di repo:

```bash
.venv/bin/python tools/bukti_login.py
```

Skrip itu menjalankan alur di atas dengan sandi contoh, mencetak setiap request
dan respons, dengan sandi/token **disamarkan otomatis**.

Atau pakai `lucifer login --user Nama --pass Sandi --verbose` untuk alur nyata.

---

## 5. Kalau tujuannya mengambil ltoken dari klien sendiri

Karena TLS tidak bisa dibaca dari packet capture biasa:

1. Pasang **HTTP Toolkit** (atau `mitmproxy`) — ini MITM proxy yang membuka TLS
   dengan sertifikat yang dipasang di perangkat.
2. Set proxy perangkat ke HTTP Toolkit.
3. Buka Growtopia, login seperti biasa (Google/Apple/GrowID).
4. Cari request ke `login.growtopiagame.com` → copy isi field **`data`**.
5. Jalankan:

```bash
lucifer ltoken --file client_data.txt --save
```

Perintah itu mengambil `ltoken`, `tankIDName`, `rid`, `mac` dari blok tersebut
lalu menyimpannya ke `data/accounts.json` (izin `600`).

Bisa juga langsung tempel blok `data` itu ke **panel Login Akun** di dashboard —
pengurainya sudah ada di sisi browser.

---

## 6. Login Google lewat OAuth web — **BISA** (koreksi 2026-09-30)

> ### ⚠️ WAJIB: parameter `state` harus ikut dikirim
> Ditemukan dari error nyata (2026-09-30):
> ```
> GET /google/callback?code=<VALID>              → HTTP 500 "Page not found [404]"
> GET /google/callback?code=<VALID>&state=<apa>  → HTTP 302 → JSON {token: ...}
> ```
> Server Growtopia **menolak** callback tanpa `state`, dan balasannya menyesatkan
> (halaman 404, seolah `code`-nya salah padahal valid). `state` kosong juga 500 —
> jadi harus ada isinya. **Nilainya tidak diperiksa** server (acak pun diterima).
> Karena itu `url_login_google()` sekarang **selalu** menyertakan `state`, dan
> `--code` menerima URL callback utuh sekaligus mengambil `state`-nya.

> ### ⚠️ Jebakan penangkapan `code` (intermiten)
> URL callback `?code=...` hanya **SEKILAS** — server GT langsung 302 ke
> `/player/link/dashboard/validate/<payload>`. Kalau Chrome dibuka langsung ke
> URL login dan CDP baru tersambung ~1-2 detik kemudian, peristiwa `code` sudah
> lewat. Gejalanya: **kadang berhasil, kadang "waktu habis"** (dibuktikan: 2 dari
> 5 percobaan gagal).
> Solusinya: Chrome dibuka di `about:blank` dulu → pasang pemantau CDP →
> **baru** `Page.navigate`. Setelah perbaikan: **5 dari 5 berhasil**.

> ### ⚠️ `SingletonLock` basi
> Kalau Chrome di-kill/crash, `SingletonLock -> <host>-<pid>` milik proses mati
> tertinggal di profil. Chrome lalu menolak start dan gejalanya menyesatkan:
> *"DevTools tidak menjawab"* (padahal Chrome tidak jalan sama sekali).
> Sekarang lock basi dibersihkan otomatis (hanya kalau PID-nya benar-benar mati,
> jadi Chrome yang sedang jalan aman).

> ### ⚠️ KOREKSI PENTING
> Bagian ini dulu menyimpulkan **"tidak ada endpoint web untuk Google, harus
> pakai SDK native"**. **Kesimpulan itu SALAH** dan sudah dibuktikan keliru.
> Growlauncher bisa login Google langsung dari URL — dan sekarang Lucifer juga.

### Buktinya

URL yang dipakai Growlauncher:

```
https://accounts.google.com/v3/signin/accountchooser
  ?client_id=389994132396-4s6ol46f60831v5blfpci7lnmsdnh8br.apps.googleusercontent.com
  &redirect_uri=https%3A%2F%2Flogin.growtopiagame.com%2Fgoogle%2Fcallback
  &response_type=code&scope=openid+profile+email&state=...
```

Dua hal yang membuktikan ini jalur resmi:

| Bukti | Hasil |
|---|---|
| `client_id` itu siapa? | **Ada di `base.apk` resmi Growtopia** — namanya `default_web_client_id` |
| Tipe client-nya? | **Web** (bukan Android) → Google **mengizinkan** `redirect_uri` |
| `/google/callback` ada? | **Ada** — balas `500` saat tanpa parameter (route terdaftar), bukan `404` |
| `/google/callback?code=X&state=Y` | **302** → `/player/link/dashboard/validate/<payload>` |
| `state` divalidasi? | **Tidak ketat** — `state` sembarang/kosong tetap diproses |

Kenapa dulu gagal: yang diuji waktu itu cuma `GET /player/growid/login` dan
mencari **halaman HTML berisi tombol Google**. Halaman itu memang tidak ada —
karena alurnya **bukan** halaman GT, melainkan **redirect OAuth ke Google**
yang URL-nya dibangun di sisi klien. Tidak perlu halaman apa pun dari GT.

### Alur lengkapnya

```
1. buka accounts.google.com/o/oauth2/v2/auth
      client_id   = <client_id GT, tipe Web>
      redirect_uri= https://login.growtopiagame.com/google/callback
      response_type=code, scope=openid profile email
2. pilih akun Google + setujui            (MANUAL, di browser)
3. Google redirect ke /google/callback?code=<CODE>
4. server GT tukar code -> 302 ke /player/link/dashboard/validate/<payload>
5. GET payload itu -> JSON {"status":"success","token":"<LTOKEN>"}
6. pakai ltoken di paket login ENet
```

Langkah 1 sudah diuji otomatis: Chrome diarahkan ke URL itu dan **benar-benar
mendarat di halaman login Google** (`accounts.google.com/v3/signin/...`).

### Cara pakai di Lucifer

```bash
# A. otomatis: Lucifer buka Chrome, kamu pilih akun, token langsung didapat
.venv/bin/lucifer login --google-browser --verify

# B. manual: buka URL-nya sendiri, salin `code` dari URL callback, lalu:
.venv/bin/lucifer login --code "4/0AX4XfWg..." --verify

# lihat URL loginnya saja (tanpa membuka browser)
.venv/bin/python -c "from lucifer.google import url_login_google; print(url_login_google())"
```

**Keamanan:** Lucifer **tidak** meminta email/sandi Google. Kamu memilih akun
sendiri di jendela browser. Jadi tidak ada sandi Google yang disimpan, dan tidak
ada otomasi yang dilawan Google (anti-bot). `client_id` bukan rahasia — ia
memang publik dan ikut di setiap URL login.

Catatan: Chrome dijalankan dengan profil terpisah (`--user-data-dir` sementara),
jadi tidak menyentuh profil Chrome-mu yang biasa.

---

## 6b. Yang sudah DICOBA dan GAGAL (jangan diulang)

Beberapa pendekatan sudah diuji langsung ke server asli. **Semuanya gagal**,
karena satu sebab yang sama: **server tidak pernah menyajikan halaman login.**

| Pendekatan | Hasil |
|---|---|
| Buka Chrome ke `login.growtopiagame.com` | halaman menampilkan **JSON mentah** (155 byte) |
| `POST /player/login/dashboard` dari dalam browser + cookie sesi Laravel | tetap **JSON 116 byte** |
| 9 variasi User-Agent (PC / Android / app Growtopia) | **identik** |
| 8 matriks header (`X-Requested-With`, `Referer`, `Origin`, `Sec-Fetch-*`, `X-XSRF-TOKEN`, dll) | **identik** |
| `GET /player/growid/login` | **110 byte JSON**, tidak ada `_token` sama sekali |
| `POST /player/growid/login/validate` dengan `_token` halaman | `419 CSRF token mismatch` |
| `POST` dengan header `X-XSRF-TOKEN` (cookie di-url-decode) | tetap `419` |

**Kesimpulan:** tidak ada halaman login web untuk diotomasi. Tombol
Google/Apple di Growtopia memakai SDK native (Play Services / Sign in with
Apple) di perangkat, bukan halaman web. Karena itu fitur "login lewat browser"
**dihapus** dari Lucifer — lebih baik tidak ada daripada ada tapi rusak.

### Kenapa `POST /player/login/dashboard` selalu balas JSON

Titik masuk itu memang bukan halaman login. Yang terjadi:

```
POST /player/login/dashboard   -> 302
   Location: /player/link/dashboard/validate/<payload>
GET  <url itu>                 -> 200 JSON {status, message, token, ...}
```

Klien Growtopia mengirim `client_data` (termasuk `tankIDName` + `tankIDPass`)
ke titik itu, lalu membaca **JSON** hasilnya. Server tidak merender HTML apa pun
untuk klien luar.

### Batas jujurnya: tombol Google

Percobaan yang sudah dilakukan (semua menghasilkan **JSON 116 byte**, bukan
halaman login):

| Percobaan | Hasil |
|---|---|
| `POST /player/login/dashboard` (blob lengkap, klv+meta sah) | `302` → `GET validate` → JSON |
| Sama, tapi dibuka di **Chrome sungguhan** | halaman menampilkan **JSON mentah** |
| Dari dalam browser + cookie sesi Laravel sah | tetap JSON |
| 9 variasi User-Agent (PC/Android/app Growtopia) | **identik** |
| 8 matriks header (X-Requested-With, Referer, Origin, Sec-Fetch-*, dll) | **identik** |
| `GET /player/growid/login` | `{"status":"failed","message":"Token is invalid."}` |
| `GET /player/login` | `404` |

Artinya: **server tidak menyajikan halaman login berisi tombol Google ke klien
luar.** Tombol Google/Apple di Growtopia memakai SDK native (Play Services /
Sign in with Apple) di perangkat, bukan halaman web.

Karena itu, satu-satunya jalur yang tersisa untuk akun **Google** adalah menyerahkan
email + sandi Google ke program (cara yang dipakai tool publik seperti
`CLOEI/growtopia-token`). Lucifer sengaja **tidak** menempuh jalur itu: sandi
Google harus dipercayakan ke program, dan Google akan sering memblokirnya dengan
captcha/2FA.

**Rekomendasi:**
* Akun **GrowID** → pakai tab **GrowID** di dashboard (sandi ditukar jadi ltoken
  otomatis, lihat bagian 8).
* Akun **Google** → ambil ltoken **sekali** lewat proxy (bagian 7), lalu pakai
  berulang. ltoken bisa disegarkan lewat `tokenUrl` tanpa login Google lagi.

---

## 7. Proxy MITM: kalau tetap mau menangkap sendiri

1. Pasang **HTTP Toolkit** (paling mudah) atau `mitmproxy`
2. Aktifkan proxy di perangkat, pasang sertifikat CA-nya
3. Buka Growtopia, login seperti biasa
4. Cari request ke `login.growtopiagame.com/player/login/dashboard`
5. Copy isi field `data` (blok base64) **atau** ambil langsung nilai `token`
6. Simpan ke file, lalu:
   ```bash
   lucifer ltoken --file client_data.txt --save
   ```
   atau tempel blok itu ke tab **Pakai ltoken** di dashboard.

⚠️ Android Growtopia kemungkinan memakai certificate pinning. Kalau traffic
tidak terlihat, perlu patching (Frida/objection) atau pakai jalur browser di atas.

**Jawaban jujur: tidak, dan ini sudah diuji habis-habisan ke server asli.**

### Kenapa tidak ada token di packet capture Android

Karena token **tidak pernah lewat jaringan dalam bentuk terbaca**. Alurnya:

```
  HP (klien Growtopia)
    └─ SDK Google NATIVE (Play Services) -> dapat id_token
    └─ id_token ditukar ke server Growtopia lewat endpoint internal
    └─ server balas ltoken (lewat HTTPS)
    └─ ENet (UDP) pakai ltoken
```

- Token asli (Google `id_token`) **tidak pernah menyentuh jaringan yang bisa di-sniff** —
  ia dibuat di dalam Play Services dan diserahkan langsung ke aplikasi lewat IPC lokal.
- Pertukaran ke server Growtopia lewat **HTTPS (TLS)** → di pcap cuma terlihat
  bungkusan `16 03 03 ...`, isinya terenkripsi.
- Karena itu pcap Android kamu **wajar kosong dari token**.

> Untuk melihatnya, WAJIB pakai proxy MITM (HTTP Toolkit / mitmproxy) yang
> membuka TLS — packet capture biasa tidak akan pernah cukup.

### Hasil pengujian jalur HTTP (semua diverifikasi)

| Yang diuji | Hasil | Artinya |
|---|---|---|
| POST `/player/login/dashboard` (blob lengkap, seperti bot) | `302` → `GET validate` → **JSON** | Server balas JSON, **bukan halaman login** |
| GET `/player/login/dashboard` di **Chrome headless** | **JSON 116 byte** | Bahkan browser sungguhan tidak dapat halaman login |
| Ganti User-Agent (PC / Android / Chrome / app GT) | **identik** | UA **tidak** mengubah apa pun |
| `/player/social/login` | `302` → dashboard | Bukan endpoint login |
| `/player/social/login/google` | `500`, body = halaman **404** | Route-nya **tidak ada** |
| Field `social_login`/`id_token`/`provider` **di dalam** blob `data` | `302` → JSON biasa | Tidak memicu redirect Google |
| `server_data.php` | ada `loginurl\|login.growtopiagame.com` | Hanya alamat host, bukan endpoint sosial |

**Kesimpulan:** `login.growtopiagame.com` **tidak pernah** menyajikan halaman login
HTML ke request HTTP biasa. **Tapi** itu bukan halangan: jalur Google **tidak**
butuh halaman dari GT sama sekali — cukup redirect ke Google, lalu GT menukar
`code` di `/google/callback` (lihat bagian 6). Server yang diuji di sini memang
tidak menyajikan HTML, tapi jalur OAuth-nya tetap terbuka.

> ⚠️ Tabel di atas tetap berguna sebagai catatan "yang jangan diulang", tapi
> **kesimpulan lamanya sudah dikoreksi di bagian 6** — login Google BISA
> dilakukan tanpa SDK native, lewat redirect OAuth biasa.

### Cara yang benar-benar dipakai tool publik

Tool seperti `CLOEI/growtopia-token` (dipakai bot **Alya**) memakai
**headless browser** (`go-rod`, yaitu Chrome otomatis). Cara Lucifer sekarang
sama, **tanpa menyimpan sandi Google**:

1. Buka URL OAuth (client_id GT + redirect_uri `/google/callback`).
2. **Pengguna memilih akun Google sendiri** di jendela browser.
3. Browser mendarat di `/google/callback?code=...`.
4. Lucifer menukar `code` → `ltoken` dan menyimpannya.

Bedanya dengan tool yang menyimpan sandi: Lucifer tidak pernah menyentuh
kredensial Google, jadi tidak ada sandi yang bocor dan tidak ada otomasi
login yang memicu captcha/2FA Google.

### Alur GrowID (Laravel CSRF) — ditemukan, tapi bukan untuk ltoken

Server memakai **Laravel**. Detail penting yang ditemukan:

- Cookie `XSRF-TOKEN` harus **di-url-decode** lalu dikirim sebagai header
  `X-XSRF-TOKEN`. Kalau dikirim mentah → **419 CSRF token mismatch**.
- `POST /player/growid/login/validate` menolak dengan `419` bila `_token` tidak
  sah. Nilai `_token` yang benar hanya diberikan ke klien Growtopia asli.
- **Tapi** alur itu untuk **login website**, bukan menghasilkan ltoken game.
  Untuk ltoken, jalur yang benar tetap `growid_login` (blob `data`).

---

## 8. Perbaikan penting: tab GrowID kini menukar sandi jadi ltoken

**Bug yang ditemukan (dan diperbaiki):** tab **GrowID** di dashboard dulu hanya
**menyimpan nama + sandi** ke `data/accounts.json`, tanpa menukarnya menjadi
`ltoken`. Akibatnya bot connect dengan `ltoken` kosong → server menolak dengan
`logon_fail`. Sandi saja **tidak cukup**: server game memerlukan `ltoken`.

Sekarang alurnya benar:

```
Tab GrowID
  nama + sandi
      │
      ├─> growid_login()  (POST blob `data` ke /player/login/dashboard)
      │      └─> 302 -> GET validate -> JSON {"token": "<ltoken>"}
      │
      ├─> BERHASIL: ltoken disimpan, method jadi "token", bot siap connect
      └─> GAGAL: akun TIDAK disimpan, pesan server + saran ditampilkan
```

Kalau gagal, dashboard menampilkan pesan **asli** dari server beserta saran,
misalnya:

```
[akun] uji_salah: GAGAL ambil ltoken — Login GrowID ditolak server: Please try login again.
[akun] uji_salah: saran: sandi salah, atau percobaan terlalu sering — tunggu 30 detik lalu coba lagi
```

Akun yang gagal **tidak** disimpan, sehingga tidak ada bot dengan token kosong
yang membuat bingung.

### Kesimpulan praktis

| Akun | Cara dapat ltoken | Otomatis? |
|---|---|---|
| **Google** | `lucifer login --google-browser` (browser, pilih akun sendiri) | ✅ ya — **cara Growlauncher** |
| **Google** | `lucifer login --code "<code dari URL callback>"` | ✅ ya, tanpa browser |
| **GrowID** | tab **GrowID** di dashboard (nama + sandi → ltoken otomatis) | ✅ ya, penuh |
| **GrowID** | `lucifer login --user N --pass S` | ✅ ya, penuh |
| **Google** (cadangan) | proxy MITM **sekali** → `lucifer ltoken --file ...` | ⚠️ sekali manual |

**Rekomendasi:** untuk akun Google, pakai **`--google-browser`** — itu jalur
resmi yang sama dengan Growlauncher, tidak butuh root, tidak butuh patch APK,
dan tidak menyimpan sandi Google. Setelah `ltoken` didapat, ia bisa dipakai
berulang dan disegarkan lewat `tokenUrl` — **tanpa login Google lagi**.
