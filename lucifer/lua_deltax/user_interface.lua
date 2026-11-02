UserInterface = {}
UserInterface.__index = UserInterface

function UserInterface.new(sub_name, icon)
    local self = setmetatable({}, UserInterface)
    self.sub_name = sub_name or "Untitled"
    self.menu = {}
    if icon then
        self.icon = icon
    end
    return self
end

function UserInterface:addLabel(text)
    table.insert(self.menu, {
        type = "label",
        text = text
    })
    return self
end

function UserInterface:addLabelApp(text, icon)
    local labelapp = {
        type = "labelapp",
        text = text
    }

    if icon then
        labelapp.icon = icon
    end

    table.insert(self.menu, labelapp)
    return self
end

function UserInterface:addToggle(text, default, alias, autosave)
    local toggle = {
        text = text,
        type = "toggle",
        default = default or false
    }

    if alias then
        toggle.alias = alias
    end

    if autosave then
        toggle.autosave = autosave
    end

    table.insert(self.menu, toggle)
    return self
end

function UserInterface:addToggleButton(text, default, alias)
    local toggle_button = {
        text = text,
        type = "toggle_button",
        default = default or false
    }

    if alias then
        toggle_button.alias = alias
    end

    table.insert(self.menu, toggle_button)
    return self
end

function UserInterface:addButton(text, alias)
    local button = {
        text = text,
        type = "button"
    }

    if alias then
        button.alias = alias
    end

    table.insert(self.menu, button)
    return self
end

function UserInterface:addChildButton(parent, text, alias)
    local button = {
        text = text,
        type = "button"
    }

    if alias then
        button.alias = alias
    end

    table.insert(parent, button)
    return self
end

function UserInterface:addExpandableToggle(text, default, alias, always_expand, background)
    local toggle = {
        text = text,
        type = "toggle",
        default = default or false,
        expandable = true,
        list_child = {}
    }

    if alias then
        toggle.alias = alias
    end

    if always_expand then
        toggle.always_expand = always_expand
    end

    if background ~= nil then
        toggle.background = background
    end

    table.insert(self.menu, toggle)
    return toggle
end

function UserInterface:addChildToggle(parent, text, default, alias, autosave, background)
    local child = {
        text = text,
        type = "toggle",
        default = default or false
    }

    if alias then
        child.alias = alias
    end

    if autosave then
        child.autosave = autosave
    end

    if background ~= nil then
        child.background = background
    end

    table.insert(parent, child)
    return self
end

function UserInterface:addSlider(text, min_val, max_val, default_val, step, use_dot, alias)
    local slider = {
        text = text,
        type = "slider",
        min = min_val or 0,
        max = max_val or 10,
        default = default_val or 5
    }

    if step then
        slider.step = step
    end

    if use_dot then
        slider.use_dot = use_dot
    end

    if alias then
        slider.alias = alias
    end

    table.insert(self.menu, slider)
    return self
end

function UserInterface:addChildSlider(parent, text, min_val, max_val, default_val, step, use_dot, alias)
    local slider = {
        text = text,
        type = "slider",
        min = min_val or 0,
        max = max_val or 10,
        default = default_val or 5
    }

    if step then
        slider.step = step
    end

    if use_dot then
        slider.use_dot = use_dot
    end

    if alias then
        slider.alias = alias
    end

    table.insert(parent, slider)
    return self
end

function UserInterface:addTooltip(text, support_text, icon, background)
    local tooltip = {
        type = "tooltip",
        text = text,
        support_text = support_text or ""
    }

    if icon then
        tooltip.icon = icon
    end

    if background ~= nil then
        tooltip.background = background
    end

    table.insert(self.menu, tooltip)
    return self
end

function UserInterface:addChildTooltip(parent, text, support_text, icon, background)
    local tooltip = {
        type = "tooltip",
        text = text,
        support_text = support_text or ""
    }

    if icon then
        tooltip.icon = icon
    end

    if background ~= nil then
        tooltip.background = background
    end

    table.insert(parent, tooltip)
    return self
end

function UserInterface:addItemPicker(text, item, default, alias)
    local item_picker = {
        type = "item_picker",
        text = text,
        item = item or "Blank",
        default = default or "Blank"
    }

    if alias then
        item_picker.alias = alias
    end

    table.insert(self.menu, item_picker)
    return self
end

function UserInterface:addChildItemPicker(parent, text, item, default, alias)
    local item_picker = {
        type = "item_picker",
        text = text,
        item = item or "Blank",
        default = default or "Blank"
    }

    if alias then
        item_picker.alias = alias
    end

    table.insert(parent, item_picker)
    return self
end

function UserInterface:addInputInt(text, default, label, placeholder, icon, alias)
    local input_int = {
        type = "input_int",
        text = text,
        default = default or "0",
        label = label or "Value",
        placeholder = placeholder or "0"
    }

    if icon then
        input_int.icon = icon
    end

    if alias then
        input_int.alias = alias
    end

    table.insert(self.menu, input_int)
    return self
end

function UserInterface:addChildInputInt(parent, text, default, label, placeholder, icon, alias)
    local input_int = {
        type = "input_int",
        text = text,
        default = default or "0",
        label = label or "Value",
        placeholder = placeholder or "0"
    }

    if icon then
        input_int.icon = icon
    end

    if alias then
        input_int.alias = alias
    end

    table.insert(parent, input_int)
    return self
end

function UserInterface:addInputString(text, default, label, placeholder, icon, alias)
    local input_string = {
        type = "input_string",
        text = text,
        default = default or "",
        label = label or "Text",
        placeholder = placeholder or ""
    }

    if icon then
        input_string.icon = icon
    end

    if alias then
        input_string.alias = alias
    end

    table.insert(self.menu, input_string)
    return self
end

function UserInterface:addChildInputString(parent, text, default, label, placeholder, icon, alias)
    local input_string = {
        type = "input_string",
        text = text,
        default = default or "",
        label = label or "Text",
        placeholder = placeholder or ""
    }

    if icon then
        input_string.icon = icon
    end

    if alias then
        input_string.alias = alias
    end

    table.insert(parent, input_string)
    return self
end

function UserInterface:addDialog(text, support_text, menu_items)
    local dialog = {
        type = "dialog",
        text = text,
        support_text = support_text or "Click to open",
        menu = menu_items or {}
    }

    table.insert(self.menu, dialog)
    return dialog
end

function UserInterface:addDivider()
    table.insert(self.menu, {
        type = "divider"
    })
    return self
end

function UserInterface:addDisplayList(text, default, alias)
    local display_list = {
        type = "display_list",
        text = text,
        default = default or ""
    }

    if alias then
        display_list.alias = alias
    end

    table.insert(self.menu, display_list)
    return self
end

function UserInterface:addTileSelect(text, default, alias, count)
    local tile_select = {
        type = "tile_select",
        text = text,
        default = default or "{}"
    }

    if alias then
        tile_select.alias = alias
    end

    if count then
        tile_select.count = count
    end

    table.insert(self.menu, tile_select)
    return self
end

function UserInterface:generateJSON()
    local json_table = {
        sub_name = self.sub_name,
        menu = self.menu
    }

    if self.icon then
        json_table.icon = self.icon
    end

    return self:tableToJSON(json_table)
end

function UserInterface:tableToJSON(t, indent)
    indent = indent or ""
    local result = "{\n"
    local first = true

    for k, v in pairs(t) do
        if not first then
            result = result .. ",\n"
        end
        first = false

        result = result .. indent .. "  \"" .. tostring(k) .. "\": "

        if type(v) == "table" then
            if #v > 0 then -- array
                result = result .. "[\n"
                for i, item in ipairs(v) do
                    if i > 1 then result = result .. ",\n" end
                    result = result .. indent .. "    " .. self:tableToJSON(item, indent .. "    ")
                end
                result = result .. "\n" .. indent .. "  ]"
            else -- object
                result = result .. self:tableToJSON(v, indent .. "  ")
            end
        elseif type(v) == "string" then
            result = result .. "\"" .. v .. "\""
        elseif type(v) == "boolean" then
            result = result .. (v and "true" or "false")
        else
            result = result .. tostring(v)
        end
    end

    result = result .. "\n" .. indent .. "}"
    return result
end

function UserInterface:printJSON()
    print(self:generateJSON())
end

-- UIManager class
UIManager = {}
UIManager.__index = UIManager

function UIManager.new()
    local self = setmetatable({}, UIManager)
    self.sub_categories = {}
    return self
end

function UIManager:addSubCategory(ui_instance)
    table.insert(self.sub_categories, ui_instance)
    return self
end

function UIManager:generateJSON()
    local result = "[\n"

    for i, sub_cat in ipairs(self.sub_categories) do
        if i > 1 then
            result = result .. ",\n"
        end

        local sub_json = sub_cat:generateJSON()
        local lines = {}
        for line in sub_json:gmatch("[^\r\n]+") do
            table.insert(lines, "  " .. line)
        end
        result = result .. table.concat(lines, "\n")
    end

    result = result .. "\n]"
    return result
end

function UIManager:printJSON()
    print(self:generateJSON())
end