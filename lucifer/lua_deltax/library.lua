Callback = Callback or {}
Callback.hooks = {}
growtopia = growtopia or {}

function AddHookCallback(func, name)
    name = name:lower()
    if type(func) ~= "function" then error("Callback must be function") end
    if not Callback.hooks[name] then
        Callback.hooks[name] = {}
    end
    Callback.hooks[name] = { func = func, noret = false }
    log("[Callback] Added hook: " .. name)
end

function RemoveHookCallback(name)
    Callback.hooks[name:lower()] = nil
    log("[Callback] Removed hook: " .. name)
end

function applyHook()
    local hook_string = {
        "ondraw",
        "onvalue",
        "ondialog",
        "onsendpacket",
        "onvariant",
        "onsendpacketraw",
        "ondrawimgui",
        "ongamepacket"
    }
    for _, hook in ipairs(hook_string) do
        for global_name, global_value in pairs(_G) do
            if type(global_value) == "function" and global_name:lower() == hook then
                addHook(global_value, hook)
            end
        end
    end
end
ApplyHook = applyHook

function CallHookCallback(name, ...)
    local hooks = Callback.hooks[name]
    if not hooks then return end
    local ok, result = pcall(hooks.func, ...)
    if not ok then
        log("[Callback Error @ " .. name .. "]: " .. tostring(result))
    elseif result ~= nil then
        return result
    end
end

function dumpTable(o)
    if type(o) == 'table' then
        local s = '{ '
        for k, v in pairs(o) do
            local nama = k
            if type(nama) ~= 'number' then nama = '"' .. nama .. '"' end
            s = s .. '[' .. nama .. '] = ' .. dumpTable(v) .. ','
        end
        return s .. '} '
    else
        return tostring(o)
    end
end

function log(text)
    LogToConsole(text)
end

function growtopia.enterGateway(x, y, n)
    sendPacketRaw(false, { type = 7, value = 18, px = x, py = y })
    Sleep(500)
    SendPacket(2, string.format([[action|dialog_return
    dialog_name|adventure_door
    tilex|%s|
    tiley|%s|
    buttonClicked|button%s]], x, y, n))
end

function split(str, regex)
    local p = {}
    for i in str:gmatch("[^" .. regex .. "]+") do table.insert(p, i) end
    return p
end

function string:split(sep)
    local result = {}
    for str in self:gmatch("([^" .. sep .. "]+)") do
        table.insert(result, str)
    end
    return result
end

function growtopia.sendChat(text, toClient)
    SendPacket(2, "action|input\n|text|" .. text, toClient)
end

function writeToLocal(name, s, append)
    local path = getValue(2, "app_lua_library")
    path = path:gsub("%?%.lua$", ""):gsub("([^/])$", "%1/")
    local file = io.open(path .. name, append and "a+" or "w")
    if not file then return end
    file:write(s .. "\n")
    file:close()
end

function await(function_cond, timeout)
    timeout = timeout or 0
    using_timeout = false
    if timeout == 0 then
        using_timeout = true
    end
    while not function_cond() do
        Sleep(30)
        if using_timeout then timeout = timeout - 30 end
        if using_timeout and timeout < 0 then return false end
    end
    return true
end

function isInside(c_x, c_y, radius, x, y)
    return ((x - c_x) * (x - c_x) + (y - c_y) * (y - c_y) <= radius * radius);
end

function growtopia.tileChange(posx, posy, value, animation)
    local player = getLocal()
    local tile = getTile(posx, posy)
    if player ~= nil and tile then
        if not isInside(player.pos.x + 10, player.pos.y + 15, 32 * 4, posx * 32 + 16, posy * 32 + 16) then
            log("TileChange: Player is too far away from the tile (" .. posx .. "," .. posy .. ")")
            return
        end
        local position_x = player.pos.x
        local position_y = player.pos.y
        if tile.fg % 2 == 1 or tile.fg == 0 then
            position_x = posx * 32
            position_y = posy * 32
        end

        if animation ~= nil and animation then
            local isLeft = posx < player.pos.x;
            local state =0;

            if value == 18 then
                if isLeft then
                    state = 2608
                else
                    state = 2592
                end
            else
                if isLeft then
                    state = 3120
                else
                    state = 3104
                end
            end

            local packet = {
                x =  position_x,
                y = position_y,
                px = posx,
                py = posy,
                value = value,
                state = state,
                type = 0
            }
            sendPacketRaw(false, packet)
        end
        
        local packet = {
            x =  position_x,
            y = position_y,
            px = posx,
            py = posy,
            value = value,
            type = 3
        }
        sendPacketRaw(false, packet)
    end
end

function growtopia.sendDialog(dialog)
    var = {}
    var.v1 = "OnDialogRequest"
    var.v2 = dialog
    sendVariant(var)
end

function growtopia.notifyCenter(msg)
    var = {}
    var.v1 = "OnTextOverlay"
    var.v2 = msg
    sendVariant(var)
end

function growtopia.notify(msg)
    var = {}
    var.v1 = "OnTextOverlay"
    var.v2 = msg
    sendVariant(var)
end

function growtopia.setWeather(weatherid)
    var = {}
    var.v1 = "OnSetCurrentWeather"
    var.v2 = weatherid
    sendVariant(var)
end

function growtopia.getItemName(id)
    local item = getItemInfoByID(id)
    if item then
        return item.name
    else
        return "Blank"
    end
end

function growtopia.getItemID(name)
    local item = getItemInfoByName(name)
    if item then
        return item.id
    else
        return 0
    end
end

function growtopia.checkInventory(itemid)
    for _, i in pairs(GetInventory()) do
        if i.id == itemid then return true end
    end
    return false
end

function growtopia.checkInventoryCount(itemid)
    for _, i in pairs(GetInventory()) do
        if i.id == itemid then return i.amount end
    end
    return 0
end

function growtopia.isOnPos(posx, posy)
    local player = getLocal()
    if player then
        return player.pos.x // 32 == posx and player.pos.y // 32 == posy
    end
    return false
end

function growtopia.warpTo(world_name)
    packet = "action|join_request\nname|" .. world_name .. "\ninvitedWorld|1\n";
    SendPacket(3, packet)
end

function growtopia.enter()
    local player = getLocal()
    if player then
        local x = player.pos.x // 32
        local y = player.pos.y // 32
        pkt = {
            type = 7,
            px = x,
            py = y
        }
        sendPacketRaw(false, pkt)
    else
        log("Player not found!")
    end
end

function growtopia.enterPos()
    local player = getLocal()
    local t_x = (player.posX + 10) // 32;
    local t_y = (player.posY + 15) // 32;
    if player then
        pkt = {
            type = 7,
            px = t_x,
            py = t_y
        }
        sendPacketRaw(false, pkt)
    else
        log("Player not found!")
    end
end

function growtopia.dropItem(itemID)
    packet = string.format("action|drop\n|itemID|%d", itemID)
    sendPacket(2, packet)
end

function growtopia.confirmDropItem(itemID, amount)
    packet = string.format("action|dialog_return\ndialog_name|drop_item\nitemID|%d|\ncount|%d", itemID, amount)
    sendPacket(2, packet)
end

tile = tile or {}
tile.getTile = getTile
tile.setFg = setFg
tile.setBg = setBg

itemInfoManager = itemInfoManager or {}

itemInfoManager.getItemInfoByID = getItemInfoByID
itemInfoManager.getItemInfoByName = getItemInfoByName

function getItemInfoManager()
    return itemInfoManager
end

function bindValue(type, alias, default)
    if type == 0 then
        return function ()
            return getValue(type, alias)
        end
    else
        return function ()
            return getValue(type, alias) or default
        end
    end
end

function isInside(circle_x, circle_y, rad, x, y)
    return ((x - circle_x)^2 + (y - circle_y)^2) <= rad^2
end

local original_require = require
function require(name)
    -- bisa panggil asli kalau mau fallback
    local ok, mod = pcall(original_require, name)
    if ok then
        return mod
    else
        return requireModule(name)
    end
end

function randomSleep(min, max)
    local a = math.random(min, max)
    Sleep(a)
    return a
end

function randomCSleep(min, max)
    local a = math.random(min, max)
    CSleep(a)
    return a
end

function waitUntil(predicate, timeout, useCSleep)
    local maxTries = math.max(1, math.floor(timeout * 1000 / 100))
    for i = 1, maxTries do
        local ok, res = pcall(predicate)
        if ok and res then
            return true
        end
        if useCSleep then
            CSleep(100)
        else
            Sleep(100)
        end
    end
    return false
end