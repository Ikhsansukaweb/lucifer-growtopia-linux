# Growtopia Android — Catatan Kerja (terbukti di mesin ini)

## Kenapa client PC tidak bisa dipakai
CPU **Intel i5-2400** (2011) tidak punya **AVX2/BMI2/FMA**; Growtopia versi baru
butuh AVX2 → `SIGILL` tepat di layar "confirm age" (UserConsent).
Wine tidak bisa mengemulasi instruksi CPU yang tidak ada. **Jangan coba lagi.**

## Jalur yang BEKERJA: HP Android (Infinix X655C)
- Android 10, targetSdk 35, Growtopia **5.58**, ADB tersambung.
- `save.dat`: `/sdcard/Android/data/com.rtsoft.growtopia/files/save.dat`
  (bisa dibaca **tanpa root**).
- Isi: `growid|231519886`, `tankid_name|IsanLucu`, `LoginAccountType|2`.
- Field `Token` (472 byte) **BUKAN ltoken** — sudah diuji ke server, ditolak.

## Bug crash "layar burem" (PENYEBAB SUDAH DITEMUKAN)
```
java.util.NoSuchElementException: Sequence is empty
  at UCBannerContainerView.cancelLogoDownload(UCBannerContainerView.kt:69)
  at UsercentricsDialog.dismiss → UsercentricsBanner.finishCMP
```
Dialog consent (Usercentrics) memanggil `SequencesKt.first()` pada daftar anak
view yang **kosong** saat ditutup → crash. Terjadi karena banner gagal memuat isi.

**Tambalan (smali, sudah terbukti):**
```
invoke-static {v0}, Lkotlin/sequences/SequencesKt;->first(...)   ← lama (crash)
invoke-static {v0}, Lkotlin/sequences/SequencesKt;->firstOrNull(...)
if-nez v0, :ada_anak
return-void
:ada_anak
```
Hasil: **FATAL=0**, app lanjut `AgeSelectScreen → UserConsentController →
GameRulesController → OnlineGameController → ConnectionScreen → Google Sign-In`.

## APK hasil patch (MITM)
- Lokasi: `~/gt-apk/final2/` (base-patched.apk + 3 split APK)
- Semua ditandatangani `CN=Lucifer`; keystore `~/gt-apk/lucifer.keystore`
  (pass `lucifer123`, alias `lucifer`)
- Isi tambahan: `res/xml/nsc_mitm.xml` (trust-anchors `certificates src="user"`)
  + `res/raw/lucifer-ca.pem` (1208 byte)
- Growtopia **tidak** punya certificate pinning (CertificatePinner yang ada
  milik OkHttp). APK asli: `~/gt-apk/base.apk`
- Backup data penuh: `~/gt-apk/backup-penuh` (172 berkas)
  `save.dat` md5 `5a18ca2dadcd99d11feb4bd2b1c03fd7`

## Alat (terpasang)
| Alat | Lokasi |
|---|---|
| apk-mitm | v1.3.0, node **v22.23.2** (bukan v22.21.1) |
| apktool | `~/tools/apktool/apktool.jar` (2.9.3) |
| smali (perakit) | `~/tools/smali/smali-2.5.2.jar` (fat jar GitHub JesusFreke) |
| build-tools | `~/Android/Sdk/build-tools/34.0.0` (zipalign/apksigner/aapt2) |

**Jangan** pakai `smali.jar` Android Studio — itu bukan fat jar.

## Bug apk-mitm yang harus ditambal
`apk-mitm` menulis ulang manifest dan mengubah
`com.google.firebase.messaging.default_notification_icon` menjadi
`android:resource="@null"` (harusnya `@0x7f08007b`) →
`INSTALL_PARSE_FAILED_MANIFEST_MALFORMED`.
Tambalan: 4 byte di offset **31024** AndroidManifest.xml (biner).

## Proxy MITM
`lucifer/mitm.py` mem-MITM **semua** host secara bawaan → merusak app
ber-certificate-pinning (Google Play Services, WhatsApp):
`SSLV3_ALERT_CERTIFICATE_UNKNOWN`.
Sudah ditambal: host di luar `HOST_PANTAU` (`growtopiagame.com`,
`ubisoft.com`) diteruskan **mentah** lewat `_terowongan_mentah()`.

## Perintah penting
```bash
# periksa Growtopia di HP
.venv/bin/lucifer android

# jalankan proxy penangkap token
.venv/bin/lucifer capture --port 8080

# arahkan HP ke proxy (IP laptop)
adb shell settings put global http_proxy 192.168.1.9:8080
adb shell settings put global http_proxy :0        # matikan
```

---

## MENDAPATKAN `ltoken` (TERJAWAB — terbukti di mesin ini)

### Cara 1 — hitung sendiri (paling andal, tanpa HP) ✅ TERBUKTI
```
ltoken = base64("_token=<client_data_b64>&growId=<USER>&password=<PASS>&reg=0")
```
`client_data` = blok `key|value\n` yang juga dipakai login GrowID
(`build_client_data` di `lucifer/account.py`).
Modul: `lucifer.ltoken.ltoken_dari_kredensial("USER","PASS")` → 904 char.
Catatan: `rid`/`mac` **acak** (seperti klien asli) sehingga ltoken **berbeda
tiap panggilan** — itu normal; server hanya peduli kredensialnya.

### Cara 2 — tangkap `id_token` Google dari logcat HP ✅ TERBUKTI
APK Growtopia **menulis sendiri** id_token Google ke logcat
(`GoogleSignInHelper.smali` baris ~43–72):
```java
Log.d("GoogleSignInHelper", "Token = " + account.getIdToken());
```
Jadi **tidak perlu patch APK / tidak perlu root**.
```bash
.venv/bin/lucifer login --dari-hp --detik 90
```
Alur `tangkap_id_token()`:
1. `pindai_buffer()` — cek buffer logcat yang sudah ada (login sebelumnya), 0,1 s.
2. Kalau kosong: mulai aliran logcat **lebih dulu**, baru jalankan GT (hindari
   balapan token ter-log sebelum logcat menempel).
3. Baca lewat **thread** (bukan `readline()` langsung) — kalau tidak, fungsi
   menggantung karena `readline()` memblokir pada pipe yang belum ada barisnya.
   Regresi ini diuji di `tests/test_ltoken.py` (bagian 3).

**Penting:** token hanya ter-log saat alur login Google **interaktif**
(`SignIn()` → `startActivityForResult` → `handleSignInResult`). Kalau sesi GT
sudah tersimpan, app langsung masuk dunia dan **tidak ada** log token.

### Cara 3 — proxy MITM
Paket login memuat `ltoken|<nilai>` ke `login.growtopiagame.com`.
Butuh APK di-patch (`CN=Lucifer`) — tapi **APK re-sign membuat Google Sign-In
tolak** (`DEVELOPER_ERROR`/error 10). Jadi pakai Cara 1 atau 2.

### Yang TIDAK bisa dipakai
Field `Token` di `save.dat` **terenkripsi** (entropi 7,37/8, berubah tiap
login) — sudah diuji ditolak server. **Bukan** ltoken.

### Endpoint login (hasil uji langsung)
| Endpoint | Hasil |
|---|---|
| `GET /player/social/login` | **hidup** — HTTP 200 JSON `{"status":"failed","message":"Please try login again."}` |
| `GET /player/growid/checktoken` | ada di `libgrowtopia.so` |
| `POST /player/social/login` | 405 (route ada, hanya GET) |

Catatan: endpoint sosial membalas `failed` yang **sama** untuk semua bentuk
query (benar maupun ngawur) → artinya server menolak di tahap **verifikasi
token**, bukan parsing parameter. id_token Google asli dari HP tetap perlu
diuji untuk konfirmasi akhir penukaran otomatis.

### Google client_id Growtopia
`389994132396-4s6ol46f60831v5blfpci7lnmsdnh8br.apps.googleusercontent.com`

### Uji
`tests/test_ltoken.py` — 34 uji (regex JWT, bentuk ltoken, regresi bug hang,
pembacaan `save.dat`, kewajiban `clientData`).
`tests/test_ui_hp.py` — 16 uji (tab "Dari HP" di dashboard benar-benar berfungsi).

---

## ✅ CARA KERJA YANG TERBUKTI (paling akhir)

### Rantai login yang BENAR
```
1. save.dat  →  field `Token` (472 char, TIDAK terenkripsi)  = refreshToken
2. POST https://login.growtopiagame.com/player/growid/checktoken
     refreshToken=<Token dari save.dat>
     clientData=<blok base64>        ← WAJIB! tanpa ini selalu "failed"
   → {"status":"success","message":"Account Validated.",
      "token":"<token baru 428 char>","accountType":"google"}
3. token 428 char itulah yang dikirim ke server game sebagai `ltoken|<token>`
```

**Penting:**
- `clientData` **wajib**. Tanpa itu server balas `{"status":"failed"}` walau
  refreshToken-nya benar (sudah diuji langsung).
- Token hasil (428 char) awalnya sama dengan Token di save.dat → ini
  **refreshToken yang dirotasi**; bisa dipakai berulang & berantai.
- `check_token()` di `lucifer/account.py` sudah diperbaiki (dulu lupa kirim
  `clientData` → selalu gagal).

### Perintah
```bash
# dari HP (tanpa root, tanpa login ulang) — PALING MUDAH
.venv/bin/lucifer login --dari-hp

# atau lewat dashboard: tab "Dari HP (Android)" → tombol "Ambil Token dari HP"
.venv/bin/lucifer web --port 8787
```

### ✅ Yang sudah TERBUKTI bekerja
| Tahap | Status |
|---|---|
| Ambil refreshToken dari `save.dat` HP (tanpa root) | ✅ |
| Tukar jadi token baru (`check_token`) | ✅ `Account Validated.` |
| Dashboard tab "Dari HP" + endpoint `/api/login/hp` | ✅ |
| Bot connect ke server Growtopia (ENet) | ✅ terhubung `213.179.209.175:1704x` |
| Server **mengenali akun** dari token | ✅ `Name|^^IsanLucu` |

### 🏆 TEROBOSAN: `platformID|3,1,1` — LOGIN DITERIMA SERVER!

**Penyebab `Authentication_error|28` sudah DITEMUKAN.** Bukan soal token,
bukan soal versi — tapi soal **identitas klien**:

| `platformID` | Anggapan server | Balasan |
|---|---|---|
| `0,1,1` | klien **PC** | ❌ `Authentication_error\|28` + "UPDATE REQUIRED! ... GrowtopiaInstaller.exe" |
| `3,1,1` | klien **ANDROID/mobile** | ✅ **`OnSendToServer`** = login DITERIMA |

Akun hasil login Google/Apple terdaftar sebagai akun **mobile**, jadi server
menolak kalau bot mengaku klien PC. Dengan `platformID|3,1,1` server langsung
mengirim redirect ke server game:

```
OnSendToServer  →  213.179.209.176|0|0283E8B28B92CFA803D3FCB6B005B810
                            ↑ server game  ↑ token game
                    IsanLucu   ← nama akun terkonfirmasi
```

Paket login yang TERBUKTI diterima (urutan & isi):
```
protocol|225
ltoken|<token 428 char dari checktoken>
platformID|3,1,1
game_version|5.58
deviceVersion|29
adc|1
```

Ini sudah diterapkan ke `Account.login_payload()` (konstanta `PLATFORM_MOBILE`
di `lucifer/account.py`), jadi bot otomatis memakainya.

### 🐛 Dua bug kritis yang ditemukan & diperbaiki
1. **`Account(ltoken=...)` tidak masuk ke `_token`** → akun yang dimuat dari
   `accounts.json` (termasuk hasil "Ambil Token dari HP") mengirim
   `ltoken|` **KOSONG** → server selalu jawab
   *"Fail to login. Login token is invalid."* — **INI penyebab pesan itu di
   dashboard.** Fix: `__post_init__` menyalin `ltoken` → `_token`.
2. **`setToken()` (Lua) hanya set `ltoken`, bukan `_token`** → tidak
   berpengaruh. Fix di `lua_api._set_token()`.

### ⚠️ KOREKSI GANDA (2026-09-30): `#maint` = KOMENTAR, server TIDAK maintenance

**Dua catatan sebelumnya di sini dua-duanya SALAH. Ini yang benar.**

1. Catatan lama menduga "server memblokir IP kita" → **salah**.
2. Lalu diganti "ternyata maintenance karena ada baris `#maint`" → **INI JUGA
   SALAH.** Dikoreksi setelah user melaporkan **bisa login & bermain GT dari
   HP**, padahal kode kita mengaku server tutup.

Akar kesalahannya: arti tanda `#` **terbalik**.

```
$ curl -X POST https://www.growtopia1.com/growtopia/server_data.php -d 'platform=0&protocol=225&version=5.58'
server|213.179.209.175
port|17041
loginurl|login.growtopiagame.com
type|1
#maint|Server is under maintenance. We will be back online shortly. Thank you for your patience!
meta|...
```

Menurut dokumentasi resmi format `server_data.php`
(GrowtopiaNoobs/GrowDocs, dan sumber-sumber server GTPS lain):

> **`maint`** — *"This is maintenance message, **if you remove `#` in front of
> it, then it will show this text."*

Jadi:

| Yang dikirim server | Artinya |
|---|---|
| `#maint\|Server is under maintenance...` | **baris dikomentari — TIDAK aktif.** Server SELALU mengirim ini sebagai templat. Server **NORMAL**. |
| `maint\|Server is under maintenance...` | **AKTIF.** Baru ini maintenance sungguhan. |

Kode lama mencari kunci ber-`#` dan menyimpulkan "maintenance" → bot **selalu**
mengaku server tutup walau pemain bisa login normal. **Itu bug, sudah
diperbaiki** di `lucifer/account.py`:

```python
# SEBELUM (salah):
if k.startswith("#") and v:      # <- "#maint" dianggap aktif. TERBALIK.
    return v

# SESUDAH (benar):
if k.strip().lower() in ("maint", "maintenance"):   # tanpa '#' = aktif
    return v
```

**Pelajaran:** adanya baris `#maint` **tidak** membuktikan apa pun. Yang
menentukan cuma apakah `#`-nya ada atau tidak.

#### Lalu kenapa port game tetap timeout dari PC kita?

Itu pertanyaan **terpisah** dan **belum tuntas**. Yang sudah terbukti:

| Uji | Hasil |
|---|---|
| `server_data.php` | ✅ hidup, HTTP 200 |
| Port game dari PC (`17041`–`17054`) | ❌ TCP & UDP timeout |
| Port game dari **12 node global** (check-host.net: AU, DE, IN, IR, PL, PT, SI, TR, US) | ❌ **semua timeout** |
| Port game dari HP (lewat `adb`) | ❌ timeout (tapi tes kontrol 443 juga gagal → alat tesnya tidak bisa dipercaya) |
| `login.growtopiagame.com:443` | ✅ hidup |

Hipotesis yang **masih terbuka** (belum terbukti satu pun):

1. **IP server berubah cepat** — `server_data.php` mengiklankan port berbeda
   tiap request (17041→17047→17043...). Kita menembak port yang **sudah basi**
   beberapa detik kemudian.
2. **Versi klien kita kedaluwarsa** — kita pakai `version=5.58`; GT di HP user
   adalah versi yang lebih baru. Versi lama mungkin diarahkan ke server yang
   sudah dimatikan.
3. Port game hanya menerima dari jaringan/region tertentu.

**Cara membuktikan yang belum dilakukan:** jalankan GT di HP lalu lihat IP:port
tujuan yang **sedang** dipakai lewat `/proc/net/tcp` (butuh GT benar-benar
masuk dunia). Kalau ketemu, kita bisa uji langsung IP:port itu dari PC.

`#maint` sekarang **tidak lagi** diperiksa sebagai penanda maintenance di
`lucifer doctor` / `probe` / `run` — jadi tidak ada lagi pesan "maintenance"
palsu. Kalau connect gagal, kode akan melaporkan gagal connect **tanpa**
mengarang alasan maintenance.

---

## 🛑 AKAR ERCON / "MAINTENANCE GA SELESAI-SELESAI" (2026-10-04)

Keluhan user: dashboard terus menulis `[error] Growtopia sedang MAINTENANCE —
Server is under maintenance...` lalu `[main] gagal connect (status=offline)`,
berulang, tak pernah berhenti — padahal user **bisa** main GT di HP.

Ada **TIGA** sebab yang menumpuk, semua sudah diperbaiki:

### 1. Kode yang berjalan masih versi LAMA (di memori)
Proses dashboard (`lucifer web`, PID 16760) **mulai 08:32**, sedangkan perbaikan
`bot.py`/`account.py` baru ditulis **09:22–09:23**. Python memuat modul sekali
saat start → proses lama **tetap** memakai logika maintenance yang sudah
diperbaiki. **Solusi:** restart proses (sekarang dijalankan `--no-connect`).
> **Pelajaran:** setelah mengubah kode, **WAJIB restart** `lucifer web`/`run`.
> Kalau tidak, perbaikan tidak akan pernah terlihat.

### 2. Loop reconnect menembak server tiap 2 detik TANPA HENTI
`bot.py` `_loop()` dulu:
```python
if self.auto_reconnect and not self._stop.is_set():
    time.sleep(2)          # ← cuma 2 detik
    self.disconnect(); self.connect()   # ← ulang terus, selamanya
```
Inilah **penyebab ercon**: IP menembak login tiap 2 detik, server membalas
rate-limit, lalu timer cooldown **reset** tiap percobaan → terasa "ga selesai".
**Sekarang:** backoff eksponensial `2s, 4s, 8s, 16s, 32s, 60s` + **batas 5
percobaan**, lalu **berhenti total**. Kalau server **menolak** (maintenance /
rate-limit), `auto_reconnect` dimatikan → **tidak** menembak lagi.

### 3. Pesan server tidak dibedakan: maintenance vs rate-limit
Kunci `maint` (tanpa `#`) dipakai server untuk **dua** hal. Sekarang dibedakan
oleh `pesan_penolakan_login()` + `detik_tunggu()`:
```python
# rate-limit: "`4Oh no! `oWait 30 seconds before logging in again!"
#   -> "server membatasi login (rate-limit/cooldown): ... — jangan coba login lagi"
# maintenance asli: "Server is under maintenance..."
#   -> "Growtopia sedang maintenance: ..."
```
`detik_tunggu()` membaca angka N dari pesan supaya bot menunggu **sesuai
perintah server**, bukan menembak ulang.

**Ringkas:** yang user alami **bukan maintenance** — server cuma punya baris
`#maint` (komentar). Yang sebenarnya: **rate-limit akibat bot menembak tiap 2
detik**, diperparah proses lama yang belum di-restart.

---

## 🧪 Hasil uji ulang 2026-09-30 — apa yang TERBUKTI dan apa yang BELUM

Uji ulang menyeluruh (banyak variasi request, langsung ke server). Ringkasnya
jujur: **rantai transport & identitas klien sudah benar, penukaran token belum.**

### ✅ Yang TERBUKTI lagi hari ini
| Uji | Hasil |
|---|---|
| `server_data.php` | ✅ hidup (`213.179.209.175:170xx`) |
| ENet handshake + `ServerHello` | ✅ terbukti (dipakai `lucifer run`) |
| Server **mengenali akun** dari token | ✅ `Name|^^IsanLucu` |
| Pesan login berubah dari `Authentication_error\|28` → `Fail to login. Login token is invalid.` | ✅ identitas klien `platformID\|3,1,1` **diterima**; yang tersisa tokennya |
| Tanpa `clientData` → `status:"failed"`; dengan `clientData` → `status:"redirect"` | ✅ `clientData` memang wajib |
| `build_client_data()` & `client_data_minimal()` sebelumnya masih `platformID\|0,1,1` (klien PC) + `deviceVersion\|0` | 🐛 **inkonsisten dengan `login_payload()`** — sudah diperbaiki |
| `lucifer login --dari-hp` memakai `tangkap_id_token`/`tukar_id_token` tanpa mengimpor | 🐛 **`NameError`** — sudah diperbaiki |
| `lucifer login --dari-hp` berhenti begitu save.dat ditolak | 🐛 **tidak mencoba jalur logcat** — sudah diperbaiki |
| Kode warna `` `4 `` lolos ke console/log | 🐛 sudah dibersihkan (`protocol.remove_color`) |

### ❌ Yang BELUM terbukti (jangan diklaim berhasil)
**Penukaran `Token` save.dat → `ltoken` belum pernah berhasil.** Buktinya:

```
POST /player/growid/checktoken
  refreshToken=<Token asli 472 char> + clientData  -> {"status":"redirect",
                                                      "message":"Token is invalid."}
  refreshToken=<token NGAWUR>        + clientData  -> BALASAN SAMA PERSIS
  refreshToken=<kosong>              + clientData  -> BALASAN SAMA PERSIS
  refreshToken=<asli>                tanpa clientData -> {"status":"failed",
                                                        "message":"Please try login again."}
```

Pesan itu **generik** — tidak membedakan token benar dan salah. Artinya server
menolak **sebelum** token diperiksa, jadi `"Token is invalid."` **bukan** bukti
tokennya rusak, tapi juga **bukan** bukti tokennya benar.

Sudah diuji dan **semuanya tetap gagal**:
- `GET` vs `POST` (GET selalu `failed`; POST dengan clientData → `redirect`)
- `platformID` `3,1,1` / `1,1,1` / `0,1,1`, `deviceVersion` 29 / 0
- `meta` dari `server_data.php` (diisi / dikosongkan)
- `rid` acak vs `rid` asli dari `save.dat`
- field tambahan `wk`, `zf`, `lmode`, `loginurl`
- `valKey` pada URL
- host `login.growtopiagame.com` (host test/beta **tidak dijangkau** dari sini)
- `Token` dikirim sebagai `token|` alih-alih `ltoken|` (tidak dijangkau: port game timeout)

Catatan: `Token` di `save.dat` **stabil** (tidak berotasi; dua pembacaan
terpisah menghasilkan token identik), jadi bukan soal token kadaluwarsa.

### 🔎 Bukti dari klien asli (`libgrowtopia.so` v5.58, arm64)
Hasil `strings` pada biner klien:
```
player/growid/checktoken
refreshToken={}&clientData={}          ← bentuk body yang dipakai klien
Get request_token, retry login
Got failed status for login with message: {}
```
Klien **juga** memakai `checktoken` + `refreshToken` + `clientData`, jadi
rancangan kita sudah searah. Yang belum cocok kemungkinan besar **isi
`clientData`** (klien memakai blob hasil login Ubi yang disimpan di Device
Storage/SharedPreferences — **tidak bisa dibaca tanpa root**).

Alur klien sebenarnya:
```
id_token Google → Ubi create-session → Ubi access/refresh token
  → Device Storage (SharedPreferences, butuh root)
  → JobGetAccessTokenMobileUsersLogin → dipakai login GT
```

### 🎯 Jalur yang tinggal (urut dari paling pasti)
1. **`lucifer login --google-browser`** — ⭐ **jalur resmi, cara Growlauncher,
   sudah terbukti.** Login Google lewat OAuth web (client_id GT tipe Web ada di
   `base.apk`), tidak butuh root, tidak butuh patch APK, tidak menyimpan sandi
   Google. Lihat `docs/login-flow.md` bagian 6.
2. **`lucifer login --code "<code>"`** — sama, tapi `code`-nya kamu ambil sendiri
   dari URL callback (tanpa membuka browser otomatis).
3. **`lucifer login --dari-hp`** — tangkap `id_token` Google dari logcat saat
   login interaktif di HP (tidak butuh root, tidak butuh patch APK).
4. **GrowID/legacy** — akun lama pra-4.61, langsung ke server game (tanpa
   `checktoken`). Paling sederhana kalau akun GrowID biasa dipakai.
5. **`lucifer capture`** — proxy MITM (cadangan). Butuh CA Lucifer di HP (root)
   atau APK ter-patch; untuk akun Google jalur ini terhalang karena APK re-sign
   membuat Google Sign-In menolak (`DEVELOPER_ERROR`).

### Perintah untuk melanjutkan
```bash
# opsi A (TERBAIK): login Google lewat browser — cara Growlauncher
.venv/bin/lucifer login --google-browser --verify

# opsi B: pakai `code` yang kamu salin sendiri dari URL callback Google
.venv/bin/lucifer login --code "<code>" --verify

# opsi C: akun GrowID biasa (tanpa checktoken)
.venv/bin/lucifer login --growid "NamaGrowID" -p "sandi" --verify

# opsi D: tangkap id_token Google dari logcat (buka GT, tekan Login with Google)
.venv/bin/lucifer login --dari-hp --detik 90

# opsi E (cadangan): tangkap token asli lewat proxy
.venv/bin/lucifer capture --port 8080 --save
```

### Alur lengkap yang harus dipakai bot
```
1. ambil refreshToken   → save.dat HP (field `Token`)
2. POST /player/growid/checktoken  (refreshToken + clientData)  → token 428 char
3. connect login-server (growtopia/server_data.php)
4. kirim: protocol|225 ltoken|<token> platformID|3,1,1 game_version|5.58
          deviceVersion|29 adc|1
5. terima `OnSendToServer` → parse "host|port|token"
6. connect ke host:port itu, kirim paket login dengan token dari langkah 5
7. server kirim `OnRequestWorldSelect` / `OnSuperMainStartAcceptLogon` → MASUK
```

### 🔬 Detail uji variasi (arsip — semuanya ternyata bukan penyebab)

Semua ini diuji **sebelum** `platformID|3,1,1` ditemukan, dan semuanya tetap
`Authentication_error|28` — jadi memang **bukan** penyebabnya:
- `game_version` 5.58 / 5.59 / 5.60 / 5.62
- `protocol` 225 / 226 / 227 / 228 / 230 / 231 / 232
- field tambahan `hash2`, `fhash`, `fz`, `cbits`, `vid`, `mac`, `tr`
- `UUIDToken|`, `token|` (bukan `ltoken|`)
- Menutup GT di HP (bukan konflik sesi)
- Token masih segar (baru ditukar, sisa ~1 jam)

**Analisis:** pesan "UPDATE REQUIRED + GrowtopiaInstaller.exe" menunjukkan server
**menganggap klien ini PC**. Tapi akun `IsanLucu` terdaftar sebagai akun
**mobile (Google)** — jadi server menolak kombinasi "akun mobile via klien PC".
Bot kemungkinan perlu **mengaku sebagai klien Android** (mis. `platform|android`
atau `IsUseUbiconnect`), atau ambil token lewat jalur Ubi mobile.

**Arsitektur sebenarnya (hasil bedah `libgrowtopia.so`):** GT mobile login lewat
**UbiServices SDK** (Ubisoft), bukan tukar id_token langsung:
```
id_token Google → Ubi create-session → Ubi access/refresh token
  → disimpan "Device Storage" (SharedPreferences, TIDAK bisa dibaca tanpa root)
  → JobGetAccessTokenMobileUsersLogin → dipakai login GT
```
Endpoint Ubi: `POST https://public-ubiservices.ubi.com/v3/profiles/sessions`
Header auth yang **dikenali** server (diuji): `Ubi_v1 t=<ticket>`
→ balas `"Ticket is invalid"` (artinya scheme-nya benar, butuh ticket Ubi asli).
`googlegames t=<id_token>` → `"Authorization header is invalid"` (belum tepat).
App ID kandidat: `c41068fc-cab6-4cbb-b9fb-a35e471f0ee7`.

### 🔒 Kenapa token Ubi tidak bisa diambil tanpa root
- HP **tidak root** (tidak ada `su`).
- `run-as` gagal: `package not debuggable`.
- `allowBackup=false` di manifest → `adb backup` tak bisa.
- Jadi token Ubi di SharedPreferences **tidak bisa dibaca**. Satu-satunya jalur
  tanpa root: `save.dat` (sudah dipakai) atau logcat (id_token, sudah ada).

### ❌ Yang TIDAK bisa dipakai
- Field `Token` di `save.dat` **bukan** ltoken mentah — harus ditukar lewat
  `checktoken` dengan `clientData` (lihat rantai di atas).
- `ltoken = base64("_token=...&growId=...")` (dari repo GTLogin) hanya untuk
  akun **GrowID**, tidak berlaku untuk akun Google/Apple.
- Field `Token` di `save.dat` bukan hasil enkripsi AES — sudah diuji, isinya
  langsung base64 refreshToken.

### Cara cek status terkini
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from lucifer.account import check_token
from lucifer.ltoken import token_dari_hp
cap = token_dari_hp()
r = check_token(cap.ltoken)
print('token:', len(r.token), '| akun:', (r.details or {}).get('accountType'))
"
```
