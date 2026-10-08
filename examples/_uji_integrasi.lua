-- ============================================================
-- _uji_integrasi.lua — Uji nyata: Lua -> Bot -> ENet -> server GT
-- ============================================================
-- Dijalankan oleh tests/test_integration.py.
-- Membuktikan seluruh rantai bekerja:
--   runtime Lua -> API Bot -> paket ENet -> server Growtopia -> balasan
--   -> event kembali ke handler Lua (addEvent + listenEvents/sleep)

local hasil = {}
local function catat(k, v) hasil[#hasil+1] = string.format("%-32s %s", k, tostring(v)) end

bot = getBot()
catat("bot.name", bot.name)
catat("bot.status (awal)", bot.status)

-- ---------- daftarkan handler event ----------
local pesan_server = {}
local jumlah_event = 0

function OnTextPacket(msg)
  jumlah_event = jumlah_event + 1
  if msg.msg then
    pesan_server[#pesan_server + 1] = removeColor(tostring(msg.msg))
    catat("EVENT dari server", removeColor(tostring(msg.msg)))
  end
end

function OnVariantList(variant, netid)
  jumlah_event = jumlah_event + 1
  catat("EVENT variantlist", variant:get(0):getString())
end

addEvent(Event.game_message, OnTextPacket)
addEvent(Event.variantlist, OnVariantList)

-- ---------- connect lewat API Lua (jaringan nyata) ----------
catat("bot:connect()", bot:connect())
catat("bot.server", table.concat({tostring(bot.server and bot.server[1]), tostring(bot.server and bot.server[2])}, ":"))

-- ---------- tunggu jawaban server ----------
-- sleep() di Lucifer tetap memompa event, jadi handler di atas ikut jalan.
local n = 0
while n < 100 do
  sleep(250)
  n = n + 1
  if #pesan_server > 0 then break end
  if bot.status == BotStatus.online then break end
end

catat("bot.status (akhir)", bot.status)
catat("ping", bot:getPing())
catat("jumlah event diterima", jumlah_event)
catat("jumlah pesan server", #pesan_server)

print("")
print("========== HASIL UJI INTEGRASI ==========")
for _, h in ipairs(hasil) do print(h) end
print("=========================================")

-- Kriteria lulus: server benar-benar membalas lewat jalur ENet.
-- (Kredensial uji sengaja tidak valid, jadi "Fail to login" dari server
--  justru BUKTI bahwa paket kita diterima dan dijawab server asli.)
local lulus = (#pesan_server > 0) or (bot.status == BotStatus.online)

print(lulus and "KESIMPULAN: LULUS — rantai Lua -> ENet -> server GT bekerja"
             or "KESIMPULAN: GAGAL — tidak ada balasan dari server")

bot:disconnect()
unlistenEvents()
return lulus
