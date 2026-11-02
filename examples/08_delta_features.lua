-- 08_delta_features.lua — fitur gaya deltaX dari Lua.
-- Semua nama fungsi = alias menu deltaX (lihat lucifer/features.py).
-- Tambahkan bot="label" di akhir argumen untuk multi-akun.

-- ------------------------------------------------------------------ --
-- Chat commands (/warp, /back, /finditem, /gscan, /alias, ...).
-- Bot yang mengetik "/..." di dunia akan menanganinya lokal, tidak dikirim.
-- ------------------------------------------------------------------ --
addEvent("onConsoleMessage", function(msg)
    if msg:find("^/") then
        command(msg)
    end
end)

-- ------------------------------------------------------------------ --
-- AutoFarm: panen -> ambil -> tanam. seed_id = id bibit yang ditanam.
-- Tanpa autofarm_set_tiles, sasaran = semua tile berlatar tanah.
-- Dinyalakan setelah dunia termuat (start() menolak kalau bot offline).
-- ------------------------------------------------------------------ --
autofarm_set_seed(964)                  -- 964 = Dirt Seed (contoh)
autofarm_set_tiles({{10, 12}, {11, 12}, {12, 12}})
autocollect_set_radius(3)

addEvent("onWorldLoaded", function(world)
    autofarm_start()
    autocollect_start()
    print("autofarm:", autofarm_status())
end)

-- ------------------------------------------------------------------ --
-- Spammer
-- ------------------------------------------------------------------ --
spammer_add("halo")
spammer_add("siap farm")
spammer_set_delay(1500)                 -- ms antar pesan
-- spammer_start()

-- ------------------------------------------------------------------ --
-- FindPath: jalan ke tile, atau cari tile berisi item tertentu.
-- ------------------------------------------------------------------ --
findpath_set_blockjump(true)            -- anggap tile terpasang = penghalang
findpath_set_teleport(false)            -- true = pindah langsung
-- findpath_to(30, 40)
-- local pos = findpath_item(964)
-- if pos then print("bibit di "..pos[1]..","..pos[2]) end

-- ------------------------------------------------------------------ --
-- Growscan: pindai isi dunia
-- ------------------------------------------------------------------ --
-- local hasil = growscan()
-- print(hasil.world.." "..hasil.ukuran..": "..#hasil.blok.." jenis blok")

-- ------------------------------------------------------------------ --
-- Replay: rekam 10 detik aksi lalu ulangi
-- ------------------------------------------------------------------ --
-- replay_record_start()
-- sleep(10000)
-- replay_record_stop()
-- replay_save("pola_farm")
-- replay_play_start()                  -- tambahkan true untuk loop

-- ------------------------------------------------------------------ --
-- AutoDrop / AutoTrash di atas batas jumlah
-- ------------------------------------------------------------------ --
-- autodrop_set_mode("trash")
-- autodrop_set_minimum(200)
-- autodrop_start()

-- Matikan semuanya saat skrip berhenti
addEvent("onStop", function()
    features_stop_all()
end)
