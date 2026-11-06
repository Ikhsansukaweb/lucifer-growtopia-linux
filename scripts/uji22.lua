removeEvents()
local b = getBot()
local p = getLocal()
log(string.format("U22 pos=%.0f,%.0f tile=%d,%d", p.pos.x, p.pos.y, math.floor(p.pos.x/32), math.floor(p.pos.y/32)))
local function dirt() local n=0 for _,it in pairs(b:getInventory().items) do if tonumber(it.id)==2 then n=it.count end end return n end
log("U22 dirt sebelum="..dirt())
-- buang 1 dirt tepat di badan bot -> server kirim type 14 netid -1
b:drop(2, 1)
log("U22 drop terkirim")
for i = 1, 8 do
  sleep(700)
  log(string.format("U22 t=%dms dirt=%d objek=%d", i*700, dirt(),
    (function() local n=0 for _ in pairs(getObjects()) do n=n+1 end return n end)()))
end
