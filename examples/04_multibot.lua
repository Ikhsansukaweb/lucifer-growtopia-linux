-- ============================================================
-- 04_multibot.lua — Banyak bot sekaligus (inti Lucifer)
-- ============================================================
-- Tambah bot, connect semua, jalankan perintah, putar pesan bergiliran.

-- Tambah bot: addBot(nama, password) atau addBot(nama) untuk guest
addBot("bot_utama", "PASSWORD_BOT_1")
addBot("bot_kedua", "PASSWORD_BOT_2")
addBot("bot_ketiga")                       -- guest / tanpa password

local nama_bot = { "bot_utama", "bot_kedua", "bot_ketiga" }

-- ---------- connect semua ----------
for _, nama in ipairs(nama_bot) do
  local b = getBot(nama)
  if b then
    print("connect " .. nama .. " ...")
    b:connect()
    sleep(1500)
  end
end

-- tunggu semua online
local tunggu = 0
while tunggu < 200 do
  local online = 0
  for _, nama in ipairs(nama_bot) do
    local b = getBot(nama)
    if b and b.status == BotStatus.online then online = online + 1 end
  end
  print(string.format("online: %d/%d", online, #nama_bot))
  if online == #nama_bot then break end
  sleep(1000)
  tunggu = tunggu + 1
end

-- ---------- setiap bot masuk dunia & menyapa ----------
local DUNIA = "WORLD"
for i, nama in ipairs(nama_bot) do
  local b = getBot(nama)
  if b and b.status == BotStatus.online then
    b:warp(DUNIA)
    sleep(2500)
    b:say(string.format("Bot %d (%s) siap!", i, nama))
    sleep(1200)
  end
end

-- ---------- thread terpisah untuk pesan berkala ----------
function pesan_berkala(nama, teks, jeda)
  local b = getBot(nama)
  while true do
    if b and b.status == BotStatus.online then
      b:say(teks)
    end
    sleep(jeda)
  end
end

runThread(pesan_berkala, "bot_utama", "Bot utama aktif", 12000)
runThread(pesan_berkala, "bot_kedua", "Bot kedua aktif", 15000)

-- ---------- pantau 60 detik ----------
function pantau()
  for putaran = 1, 6 do
    print("--- status ---")
    for _, nama in ipairs(nama_bot) do
      local b = getBot(nama)
      if b then
        print(string.format("  %-12s %-10s ping=%-5s dunia=%s",
              nama, b.status, tostring(b:getPing()), tostring(b:getWorld().name)))
      end
    end
    sleep(10000)
  end
  print("pantau selesai")
end

pantau()
