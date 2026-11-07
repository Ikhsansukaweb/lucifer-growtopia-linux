--------------------------------------------------
-- AUTO CLEAR WORLD
-- TornAi | GrowLauncher
--------------------------------------------------

-------------------------
-- CONFIG
-------------------------
local DELAY_BREAK = 140
local MAX_COBA = 8

local WORLD_LIST = {
    "jejehj", -- ganti nama world lo
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
    if dx > 2 or dy > 2 then
        FindPath(x, y)
        Sleep(math.random(55, 70))
    end
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

                safePath(x, y - 1)

                -- Batas percobaan: kalau server diam (blok tidak pecah),
                -- berhenti. Tanpa ini `while` berputar selamanya menembak
                -- tile yang sama dan server membalas dengan blokir.
                local coba = 0
                while (GetTile(x, y).fg ~= 0
                   or GetTile(x, y).bg ~= 0) and coba < MAX_COBA do
                    punch(x, y)
                    randomSleep(DELAY_BREAK)
                    coba = coba + 1
                end
                if coba >= MAX_COBA then
                    log("Lewati (server diam)", x, y)
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