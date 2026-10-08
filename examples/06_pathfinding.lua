-- ============================================================
-- 06_pathfinding.lua — Jalan ke tile tujuan & kumpulkan item
-- ============================================================
-- Memakai getPath / findPath / moveTile / collect.

bot = getBot()

-- Guard: skrip contoh butuh minimal satu bot (akun). Kalau belum ada akun,
-- hentikan dengan pesan yang jelas alih-alih error "nil value".
if getBot() == nil then
  print("[contoh] Belum ada bot/akun. Isi data/accounts.json atau jalankan:")
  print("[contoh]   lucifer login --ltoken \"<TOKEN>\"      (lihat README: Login Google)")
  print("[contoh] lalu jalankan skrip ini lagi dari dashboard/CLI.")
  return
end

local TUJUAN_X, TUJUAN_Y = 25, 15

local function tunggu_online()
  local n = 0
  while bot.status ~= BotStatus.online and n < 150 do
    sleep(200); n = n + 1
  end
  return bot.status == BotStatus.online
end

if not tunggu_online() then
  print("bot tidak online")
  return
end

local local_player = bot:getLocal()
if not local_player then
  print("posisi pemain belum diketahui, tunggu dunia termuat...")
  sleep(4000)
  local_player = bot:getLocal()
end

if local_player then
  print(string.format("posisi awal: tile (%d,%d)", local_player.tile_x, local_player.tile_y))
else
  print("peringatan: posisi masih belum terbaca")
end

-- ---------- 1. hitung jalur ----------
local jalur = bot:getPath(TUJUAN_X, TUJUAN_Y)
print(string.format("jalur ditemukan: %d langkah", #jalur))

if #jalur == 0 then
  print("tidak ada jalur (tile mungkin terhalang)")
else
  -- ---------- 2. tempuh jalur ----------
  for i, node in ipairs(jalur) do
    bot:moveTile(node.x, node.y)
    sleep(140)
    if i % 10 == 0 then
      print(string.format("  langkah %d/%d -> (%d,%d)", i, #jalur, node.x, node.y))
    end
  end
  print("sampai tujuan")
end

-- ---------- 3. ambil semua objek di sekitar ----------
local diambil = bot:collect(4, 120)
print(string.format("objek diambil: %d", diambil))

-- ---------- 4. laporan sekitar ----------
local world = bot:getWorld()
print(string.format("dunia %s: %dx%d, %d tile", world.name, world.x, world.y, world.tile_count))

local hitung = {}
for i, tile in pairs(world:getTiles()) do
  if tile and tile.fg > 0 then
    hitung[tile.fg] = (hitung[tile.fg] or 0) + 1
  end
end

print("blok terbanyak di dunia:")
local n = 0
for id, jumlah in pairs(hitung) do
  local info = getInfo(id)
  print(string.format("  %-30s x%d", (info and info.name) or ("#" .. id), jumlah))
  n = n + 1
  if n >= 10 then break end
end
