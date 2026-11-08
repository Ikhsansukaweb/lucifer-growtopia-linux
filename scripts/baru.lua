--------------------------------------------------
-- AUTO CLEAR WORLD
-- TornAi | GrowLauncher
--------------------------------------------------

-------------------------
-- CONFIG
-------------------------
local DELAY_BREAK = 140
-- Jumlah pukulan berturut-turut TANPA balasan server sebelum tile dilewati.
-- Bukan batas jumlah pukulan per blok: tiap blok beda (Rock ~10, Dirt ~2).
local MAX_DIAM = 6

local WORLD_LIST = {
    "jjjhhhdjjdw", -- ganti nama world lo
}

-------------------------
-- FUNGSI
-------------------------
local function pos()
    return {
        x = GetLocal().posX // 32,
        y = GetLocal().posY // 32
    }
end

local function log(...)
    LogToConsole("`c[`9TornAi``]`9>> `0" .. table.concat({...}, " : "))
end

local function punch(x, y)
    SendPacketRaw(false, {
        type = 3,
        value = 18,
        px = x,
        py = y,
        x = GetLocal().posX,
        y = GetLocal().posY
    })
end

local function randomSleep(base)
    Sleep(math.random(base, base + 50))
end

local function safePath(x, y)
    local dx = math.abs(pos().x - x)
    local dy = math.abs(pos().y - y)
    if dx <= 2 and dy <= 2 then return true end
    -- FindPath mengembalikan TRUE bila GAGAL (perilaku deltaX). Versi lama
    -- mengabaikannya, lalu memukul dari tempat jauh: server menolak tanpa
    -- kabar, tile tidak pernah pecah, dan skrip menganggapnya selesai.
    if FindPath(x, y) then
        return false
    end
    Sleep(math.random(55, 70))
    return math.abs(pos().x - x) <= 3 and math.abs(pos().y - y) <= 3
end

-------------------------
-- CLEAR WORLD
-------------------------
local function clearWorld()
    for y = 0, 53 do
        for x = 0, 99 do
            local tile = GetTile(x, y)

            if tile and not tile.extra
            and (tile.bg ~= 0 or tile.fg % 2 == 1)
            and tile.fg ~= 8 then

                if safePath(x, y - 1) then
                    -- Pukul sampai tile kosong. Batasnya BUKAN jumlah pukulan
                    -- tetap: tiap blok butuh jumlah berbeda (Rock ~10, Dirt
                    -- ~2, Lava ~4). Versi lama `MAX_COBA=8` memotong Rock
                    -- sehingga banyak blok dilewati. Yang dipakai: berhenti
                    -- kalau server berhenti membalas (diam / maintenance).
                    local diam = 0
                    while GetTile(x, y).fg ~= 0
                       or GetTile(x, y).bg ~= 0 do
                        if not ServerAlive() then
                            log("Berhenti (server tidak membalas)", x, y)
                            return
                        end
                        if diam >= MAX_DIAM then
                            log("Lewati (server diam)", x, y)
                            break
                        end
                        local sebelum = TotalHit()
                        punch(x, y)
                        randomSleep(DELAY_BREAK)
                        if TotalHit() == sebelum then
                            diam = diam + 1
                        else
                            diam = 0
                        end
                    end
                else
                    -- Tidak bisa mendekat: jangan pukul dari jauh, server
                    -- membuang paketnya diam-diam. Catat lalu lanjut.
                    log("Lewati (tak terjangkau)", x, y)
                end
            end
        end
    end
end

-------------------------
-- MAIN
-------------------------
log("TornAi Started")

for i, world in ipairs(WORLD_LIST) do
    log("Warping to", world)
    SendPacket(3, "action|join_request\nname|" .. world)
    Sleep(4000)

    log("Clearing", world)
    clearWorld()

    log("Done", world)
    Sleep(2000)
end

log("Semua world selesai di clear!")