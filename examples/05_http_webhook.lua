-- ============================================================
-- 05_http_webhook.lua — HTTP client, webhook Discord, JSON
-- ============================================================
-- Menunjukkan HttpClient / Webhook / RTVAR seperti di docs Lucifer.

-- ---------- 1. HttpClient: ambil data dari internet ----------
local client = HttpClient.new()
client.method = Method.get
client.url = "https://api.github.com/repos/NuronLucifer/Nurons-Lucifer"
client.headers = client.headers or {}
client.headers["User-Agent"] = "LuciferLinux"

local res = client:request()
print(string.format("HTTP %s (%s byte)", tostring(res.status), #tostring(res.body)))

if res.status == 200 then
  local judul = res.body:match('"full_name"%s*:%s*"([^"]+)"')
  local bintang = res.body:match('"stargazers_count"%s*:%s*(%d+)')
  print(string.format("repo: %s | bintang: %s", tostring(judul), tostring(bintang)))
else
  print("error: " .. res:getError())
end

-- ---------- 2. RTVAR: bangun paket dialog ----------
local var = RTVAR.new()
var:append("action", "dialog_return", false)
var:append("dialog_name", "lucifer_linux", false)
var:append("x", 36, true)
print("RTVAR dump:\n" .. var:dump())
print("punya 'action': " .. tostring(var:contains("action")))
print("nilai x: " .. var:get("x"))

-- ---------- 3. Webhook Discord (diisi kalau punya URL) ----------
local WEBHOOK_URL = ""   -- isi: "https://discord.com/api/webhooks/xxx/yyy"

if WEBHOOK_URL ~= "" then
  local wh = Webhook.new(WEBHOOK_URL)
  wh.username = "Lucifer Linux"
  wh.content = "Laporan bot"

  wh.embed1.use = true
  wh.embed1.title = "Status Bot"
  wh.embed1.description = "Bot berjalan normal di Linux"
  wh.embed1.color = 0x5196fe
  wh.embed1:addField("Bot", getBot().name, true)
  wh.embed1:addField("Status", getBot().status, true)

  if wh:send() then
    print("webhook terkirim")
  else
    print("webhook gagal")
  end
else
  print("WEBHOOK_URL kosong — lewati pengiriman")
end

-- ---------- 4. Tulis/baca file (read/write) ----------
local laporan = string.format("bot=%s\nstatus=%s\nwaktu=%s\n",
    getBot().name, getBot().status, os.date("%Y-%m-%d %H:%M:%S"))
write("laporan.txt", laporan)
print("isi laporan.txt:\n" .. read("laporan.txt"))
