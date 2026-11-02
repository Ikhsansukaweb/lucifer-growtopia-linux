local json = require("json")
local Preferences = {}
Preferences.__index = Preferences

function Preferences:new(name)
    local instance = setmetatable({}, self)
    self.name = name
    self.values = {}
    self:load()
    return instance
end

function Preferences:load()
    local path = getAppLibrary()
    local file = io.open(path .. "/" .. self.name)
    if file then
        local content = file:read("*a")
        file:close()
        self.values = json:decode(content) or {}
    else
        self.values = {}
    end
end

function Preferences:save()
    local path = getAppLibrary()
    local file = io.open(path .. "/" .. self.name, "w")
    if file then
        local content = json:encode(self.values, { indent = true })
        file:write(content)
        file:close()
    else
        error("Could not open preferences file for writing: " .. path .. "/" .. self.name)
    end
end

function Preferences:get(name, default)
    local value = self.values[name]
    if type(value) == "nil" then
        return default
    end
    return value
end

function Preferences:set(name, value)
    self.values[name] = value
end

return Preferences