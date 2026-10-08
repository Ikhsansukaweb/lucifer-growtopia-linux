# Alur Login Growtopia — Kenyataan & Jalur yang Terbukti

Dokumen ini mencatat **apa yang benar-benar terbukti** di mesin ini
(Ubuntu, HP Infinix X655C, Android 10), bukan asumsi. Setiap klaim punya
bukti perintah yang bisa diulang.

Tanggal: 29 September 2026 · mesin: `ikhsan` · CPU: Intel i5-2400

---

## 1. Ringkasan satu menit

| Pertanyaan | Jawaban singkat |
|---|---|
| Di mana halaman login Growtopia? | **Tidak ada di web.** Tombol "Login with Google" ada **di dalam client** (PC/Android). |
| Kenapa `login.growtopiagame.com` cuma balas JSON? | Itu **endpoint API**, bukan halaman. Selalu balas JSON 110–155 byte. |
| Kenapa client PC crash di Wine? | CPU i5-2400 **tidak punya AVX2**; Growtopia baru butuh AVX2 → `SIGILL` di layar "confirm age". |
| Jalur mana yang bisa jalan? | **HP Android** (Growtopia 5.58 terpasang, CPU mendukung) + **proxy MITM Lucifer**. |
| Perlu root? | **Tidak.** Cukup patch APK dengan `apk-mitm` (CA Lucifer disisipkan). |
| Kalau akun GrowID? | `lucifer login --user N --pass S` — jalan penuh. |

---

## 2. Bukti: halaman login tidak ada di web

```
GET  /player/growid/login        -> 110 byte JSON  {"status":"failed",...}
POST /player/login/dashboard     -> 302, body 2214 byte (stub redirect)
Chrome headless buka URL itu     -> JSON mentah, BUKAN form
9 User-Agent berbeda             -> respons IDENTIK semua
```

Kesimpulan: tidak ada HTML form. `_token` CSRF pun tidak bisa diambil
(`grep` = 0 hasil), sehingga POST ke `/player/growid/login/validate`
selalu balas **419 CSRF token mismatch**.

---

## 3. Bukti: client PC crash karena AVX2

```
CPU: Intel i5-2400  → flags: avx sse4_2 ...  TIDAK ADA: avx2 bmi2 fma
GT_CrashReport.txt  → SIGILL di UserConsentController
log.txt             → "HTTPSOperation is successful" lalu mati
```

Wine tidak bisa mengemulasi instruksi yang tidak ada di CPU. **Jalur PC buntu** —
bukan karena salah konfigurasi.

---

## 4. Jalur yang jalan: HP Android + MITM

### 4.1 Fakta HP (terbukti lewat ADB)

```
model     : Infinix X655C (Android 10)
GT        : com.rtsoft.growtopia v5.58 (targetSdk 35)
APK       : base + 3 split (arm64_v8a, in, xhdpi) = 258 MB
save.dat  : bisa dibaca TANPA ROOT
            growid|231519886 · tankid_name|IsanLucu · LoginAccountType|2
```

### 4.2 Kenapa patch APK perlu

- Android 10+ **tidak** mempercayai CA pengguna (targetSdk ≥ 24).
- `apk-mitm` menyisipkan CA Lucifer **ke dalam APK** → dipercaya tanpa root.
- Growtopia **tidak punya** certificate pinning sendiri (`network_security_config.xml`
  tidak ada di APK asli) → jadi patch ini cukup.

### 4.3 Perintah

```bash
# 1. tarik semua APK dari HP (sekali saja)
lucifer android --pull-apk ~/gt-apk

# 2. patch base.apk + sisipkan CA Lucifer
apk-mitm ~/gt-apk/base.apk --certificate data/ca/lucifer-ca.pem

# 3. tanda-tangani base + semua split dengan kunci yang SAMA
#    (lihat scripts/pasang-apk.sh)

# 4. uninstall GT lama -> install-multiple yang baru
#    save.dat dikembalikan supaya tidak perlu login ulang

# 5. jalankan penangkap
lucifer capture --port 8080

# 6. di HP: set proxy Wi-Fi ke IP-mu:8080, lalu buka GT dan login Google
#    -> ltoken otomatis tertangkap dan tersimpan
```

---

## 5. Catatan penting

- **Uninstall GT menghapus data.** `save.dat` **wajib** dibackup dulu
  (otomatis oleh `scripts/pasang-apk.sh`).
- Token di `save.dat` (field `Token`, 472 byte) **bukan** ltoken langsung —
  sudah diuji ke server, jawabannya `"Please try login again."`. Jadi
  tidak bisa dipakai tanpa dekripsi kunci internal client.
- `file.db` di HP adalah **database filter kata kasar**, bukan penyimpan token.
- Akun GrowID tetap jalur termudah kalau punya.

---

## 6. Perintah Lucifer terkait

| Perintah | Guna |
|---|---|
| `lucifer login --user N --pass S` | login GrowID → ltoken (otomatis) |
| `lucifer ltoken --file save.dat` | pakai ltoken yang sudah ada |
| `lucifer capture --port 8080` | proxy MITM: tangkap ltoken dari HP |
| `lucifer android` | periksa GT + save.dat di HP lewat ADB |
| `lucifer android --pull-apk DIR` | tarik semua APK (base + split) |
