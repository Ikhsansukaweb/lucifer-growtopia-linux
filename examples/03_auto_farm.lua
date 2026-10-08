-- ============================================================
-- 03_auto_farm.lua — Auto farm: tanam, tunggu, panen, ambil
-- ============================================================
-- Contoh lengkap memakai world/tile/inventory API seperti Lucifer.

bot = getBot()

-- Guard: skrip contoh butuh minimal satu bot (akun). Kalau belum ada akun,
-- hentikan dengan pesan yang jelas alih-alih error "nil value".
if getBot() == nil then
  print("[contoh] Belum ada bot/akun. Isi data/accounts.json atau jalankan:")
  print("[contoh]   lucifer login --ltoken \"<TOKEN>\"      (lihat README: Login Google)")
  print("[contoh] lalu jalankan skrip ini lagi dari dashboard/CLI.")
  return
end

FARM_WORLD = "FARMTEST"     -- ganti dengan dunia kamu
SEED_NAME  = "Grass Seed"   -- item yang ditanam
SEED_ID    = nil            -- diisi otomatis dari database item
PLANT_X, PLANT_Y = 10, 10   -- area tanam

-- ---------- util ----------
local function item_id(name)
  local info = getInfo(name)
  if info and info.id then return info.id end
  return 0
end

local function info_name(id)
  local info = getInfo(id)
  return (info and info.name) or ("#" .. tostring(id))
end

local function log(msg)
  print(string.format("[farm] %s", msg))
  bot:getLog():append(msg)
end

-- ---------- tunggu siap ----------
local function wait_online(limit)
  local n = 0
  while bot.status ~= BotStatus.online and n < limit do
    sleep(200); n = n + 1
  end
  return bot.status == BotStatus.online
end

-- ---------- masuk dunia ----------
local function goto_world(name)
  if bot:isInWorld(name) then return true end
  log("warp ke " .. name)
  bot:warp(name)
  -- tunggu sampai dunia benar-benar termuat (maks 15 detik)
  local n = 0
  while not bot:isInWorld(name) and n < 75 do
    sleep(200)
    n = n + 1
  end
  return bot:isInWorld(name)
end

-- ---------- cari tanaman siap panen ----------
local function find_ready()
  local world = bot:getWorld()
  local out = {}
  for i, tile in pairs(world:getTiles()) do
    if tile and tile:canHarvest() then
      out[#out + 1] = tile
    end
  end
  return out
end

-- ---------- cari lahan kosong ----------
local function find_empty()
  local world = bot:getWorld()
  local out = {}
  for i, tile in pairs(world:getTiles()) do
    if tile and tile.fg == 0 and tile.bg ~= 0 then
      out[#out + 1] = tile
      if #out >= 60 then break end
    end
  end
  return out
end

-- ---------- aksi ----------
local function harvest(tiles)
  local n = 0
  for _, tile in ipairs(tiles) do
    if bot.status ~= BotStatus.online then break end
    bot:hit(tile.x, tile.y)
    n = n + 1
    sleep(180)
  end
  log("panen " .. n .. " tanaman")
  return n
end

local function collect_all(range)
  local total = 0
  for round = 1, 6 do
    local n = 0
    local local_player = bot:getLocal()
    local lx = local_player and local_player.tile_x or 0
    local ly = local_player and local_player.tile_y or 0
    local objects = bot:getWorld():getObjects()
    for i, obj in pairs(objects) do
      if obj and math.abs(obj.tile_x - lx) <= range and math.abs(obj.tile_y - ly) <= range then
        bot:collectObject(obj.oid, range)
        n = n + 1
        total = total + 1
        sleep(120)
      end
    end
    if n == 0 then break end
    sleep(400)
  end
  log("mengambil " .. total .. " objek")
  return total
end

local function plant(tiles, seed_id)
  local inv = bot:getInventory()
  local have = inv:getItemCount(seed_id)
  if have <= 0 then
    log("bibit habis (" .. info_name(seed_id) .. ")")
    return 0
  end
  local n = 0
  for _, tile in ipairs(tiles) do
    if n >= have then break end
    if bot.status ~= BotStatus.online then break end
    bot:place(tile.x, tile.y, seed_id)
    n = n + 1
    sleep(220)
  end
  log("tanam " .. n .. " bibit " .. info_name(seed_id))
  return n
end

-- ============================================================
-- PROGRAM UTAMA
-- ============================================================
SEED_ID = item_id(SEED_NAME)
log(string.format("bibit: %s (id=%s)", SEED_NAME, tostring(SEED_ID)))

if not wait_online(150) then
  log("bot tidak online, keluar")
  return
end

goto_world(FARM_WORLD)
sleep(3000)

for siklus = 1, 5 do
  log("=== siklus " .. siklus .. " ===")

  -- 1. panen yang siap
  harvest(find_ready())
  sleep(800)
  collect_all(4)

  -- 2. tanam ulang
  if SEED_ID and SEED_ID > 0 then
    plant(find_empty(), SEED_ID)
  end

  -- 3. laporan
  local inv = bot:getInventory()
  log(string.format("inventaris: %d jenis item", inv.itemcount))

  sleep(5000)
end

log("selesai 5 siklus.")
