-- ============================================================
-- 02_events.lua — Mendengarkan event dari server
-- ============================================================
-- Menunjukkan addEvent / listenEvents, sama seperti contoh di docs Lucifer.

bot = getBot()

-- Guard: skrip contoh butuh minimal satu bot (akun). Kalau belum ada akun,
-- hentikan dengan pesan yang jelas alih-alih error "nil value".
if getBot() == nil then
  print("[contoh] Belum ada bot/akun. Isi data/accounts.json atau jalankan:")
  print("[contoh]   lucifer login --ltoken \"<TOKEN>\"      (lihat README: Login Google)")
  print("[contoh] lalu jalankan skrip ini lagi dari dashboard/CLI.")
  return
end

-- Event variant list: di sini OnConsoleMessage datang
function OnVariantList(variant, netid)
  local head = variant:get(0):getString()

  if head == "OnConsoleMessage" then
    local message = variant:get(1):getString()
    print("[console] " .. removeColor(message))

    if message:match("!stop") then
      print("Perintah stop diterima — berhenti mendengarkan.")
      unlistenEvents()
    end
  elseif head == "OnTalkBubble" then
    print("[bubble] " .. variant:get(1):getString())
  end
end

-- Event teks (GameMessage / GenericText)
function OnTextPacket(msg)
  if msg.action == "log" or msg.msg then
    print("[log] " .. (msg.msg or ""))
  end
  if msg.action == "logon_fail" then
    print("[!] logon gagal: " .. tostring(msg.msg or "?"))
    bot:disconnect()
    unlistenEvents()
  end
end

addEvent(Event.variantlist, OnVariantList)
addEvent(Event.game_message, OnTextPacket)

print("Mendengarkan event selama 120 detik...")
listenEvents(120)

removeEvents()
print("Selesai mendengarkan.")
