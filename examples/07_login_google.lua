-- ============================================================
-- 07_login_google.lua — Login Google / Apple / Ubisoft / ltoken
-- ============================================================
-- Growtopia modern (4.6+) TIDAK mengirim email+password ke server game.
-- Klien menukar kredensial sosial menjadi `ltoken`, lalu server game hanya
-- menerima `ltoken`. Lucifer Linux mendukung semuanya.
--
-- Baca README bagian "Login Google" untuk cara mengambil token.

-- ---------------------------------------------------------------
-- CARA 1 (PALING ANDAL): pakai ltoken yang sudah ada
-- ---------------------------------------------------------------
-- ltoken bisa diambil dari clientData Growtopia (lihat README), lalu dipakai
-- berulang kali tanpa perlu login Google lagi.
local akun_token = {
  type = TOKEN,
  token = "ISI_LTOKEN_DI_SINI",
  growid = "NamaKamu",
  mac = "02:00:00:00:00:00",
}
-- local b1 = addBot(akun_token)

-- ---------------------------------------------------------------
-- CARA 2: login Google (butuh id_token dari login Google yang sah)
-- ---------------------------------------------------------------
local akun_google = {
  type = GOOGLE,
  mail = "email@gmail.com",
  password = "password_google",   -- hanya untuk auto-refresh token
  recovery = "",
  secretKey = "",                 -- kunci 2FA kalau aktif
}
-- local b2 = addBot(akun_google)

-- ---------------------------------------------------------------
-- CARA 3: Ubisoft Connect / Apple
-- ---------------------------------------------------------------
local akun_ubi = { type = UBICONNECT, mail = "email@contoh.com", password = "sandi" }
local akun_apple = { type = APPLE, mail = "email@icloud.com", password = "sandi", cookies = "" }
-- local b3 = addBot(akun_ubi)
-- local b4 = addBot(akun_apple)

-- ---------------------------------------------------------------
-- CARA 4: Legacy (kalau akunmu masih akun lama)
-- ---------------------------------------------------------------
local akun_legacy = { type = LEGACY, growid = "NamaLama", password = "sandiLama" }
-- local b5 = addBot(akun_legacy)

-- ---------------------------------------------------------------
-- DEMO: pakai bot yang sudah dikonfigurasi di data/accounts.json
-- ---------------------------------------------------------------
bot = getBot()
-- Guard: skrip contoh butuh minimal satu bot (akun). Kalau belum ada akun,
-- hentikan dengan pesan yang jelas alih-alih error "nil value".
if getBot() == nil then
  print("[contoh] Belum ada bot/akun. Isi data/accounts.json atau jalankan:")
  print("[contoh]   lucifer login --ltoken \"<TOKEN>\"      (lihat README: Login Google)")
  print("[contoh] lalu jalankan skrip ini lagi dari dashboard/CLI.")
  return
end

print("Jenis login yang didukung: LEGACY, GROWID, GOOGLE, UBICONNECT, TOKEN, APPLE, STEAM")
print(string.format("bot aktif: %s | metode: %s", bot.name, bot:getLogin().method))
print(string.format("mac: %s", bot:getLogin().mac))

-- Kalau punya ltoken, bisa dipasang saat berjalan:
-- bot:setToken("ltoken_dari_clientData")

-- Cek status koneksi (tanpa login paksa)
print(string.format("status: %s | ping: %s", bot.status, tostring(bot:getPing())))

-- Tampilkan token yang sedang dipakai (dipotong, jangan cetak penuh)
local tok = bot:getToken()
if tok and #tok > 0 then
  print(string.format("ltoken aktif: %s...", tok:sub(1, 12)))
else
  print("ltoken: (belum ada — akun legacy tidak butuh)")
end
