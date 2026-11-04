local n = 0
local t0 = os.time()
addEvent("game_packet", function(p)
  if p.type == 5 or p.type == 6 or p.type == 3 or p.type == 8 then
    n = n + 1
    log("TILE type=" .. tostring(p.type) .. " intx=" .. tostring(p.int_x) .. " inty=" .. tostring(p.int_y) .. " vx=" .. tostring(p.vec_x) .. " vy=" .. tostring(p.vec_y) .. " value=" .. tostring(p.item) .. " netid=" .. tostring(p.netid) .. " target=" .. tostring(p.object_type))
  end
end)
listenEvents(90)
log("REKAM SELESAI total=" .. tostring(n))
