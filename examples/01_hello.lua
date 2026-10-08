-- ============================================================
-- 01_hello.lua — Skrip paling dasar (gaya Lucifer)
-- ============================================================
-- Jalankan: lucifer lua examples/01_hello.lua --connect

bot = getBot()

-- Guard: skrip contoh butuh minimal satu bot (akun). Kalau belum ada akun,
-- hentikan dengan pesan yang jelas alih-alih error "nil value".
if getBot() == nil then
  print("[contoh] Belum ada bot/akun. Isi data/accounts.json atau jalankan:")
  print("[contoh]   lucifer login --ltoken \"<TOKEN>\"      (lihat README: Login Google)")
  print("[contoh] lalu jalankan skrip ini lagi dari dashboard/CLI.")
  return
end

print(string.format("Halo! Bot: %s | status: %s", bot.name, bot.status))

-- Tunggu bot benar-benar online (maks 30 detik)
local t = 0
while bot.status ~= BotStatus.online and t < 300 do
  sleep(100)
  t = t + 1
end

if bot.status ~= BotStatus.online then
  print("Bot belum online — periksa kredensial di data/accounts.json")
  return
end

print("Bot online. Ping: " .. bot:getPing() .. "ms")

-- Kirim 3 pesan ke dunia
for i = 1, 3 do
  bot:say("Lucifer Linux aktif (" .. i .. "/3)")
  sleep(2500)
end

print("Selesai.")
