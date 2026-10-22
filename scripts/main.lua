-- Endless: procedurally generated dungeon areas from an ENDLESS row on the title menu.
-- Each area hides a key (deeper, a lever) that opens the area's locked boss room; beating
-- the boss opens the gate to the exit (the stairs down every third area); the zone past the
-- gate loads the next area. gen.lua builds the areas; this file is the flow.
--
-- Everything the game does goes through the `api` table, so a renamed runtime call is a
-- one-line change here and the stubbed test (tests/test_main.lua) still covers
-- the flow. Every milestone writes one log line starting with "Endless:" so a live run can be
-- judged from ScriptRuntime.log alone (LIVE-RUN.md). Nothing here has run in the game yet
-- (2026-10-22).
local gen = require("gen")

local PACKAGE = "Resource.rpk"          -- the archive whose level members the areas replace
local PLACE_Y = 25.0                     -- the game's own new-game start height (8200, 25, 3920)
local PLACE_POLL_SECONDS = 0.25          -- how often to look for the loaded area after a travel
local PLACE_GIVE_UP_SECONDS = 60         -- a travel that never lands stops being waited for
local BOSS_POLL_SECONDS = 2.0            -- how often the boss's death is checked
local PARTY_POLL_SECONDS = 1.0           -- how often the party is looked at (health, presence, castings)
local REVEAL_HEALTH_RATIO = 0.25         -- below this fraction of health anyone in the party counts as near death
local PRESENT_RANGE_CM = 2500            -- a living companion this close to the player is in the party
local LESSON_SECONDS = 1200              -- time with Mira (both present, after her reveal) before Tobin's talent can wake
local BOSS_FIGHT_RANGE_CM = 1500         -- the boss this close to the player, alive, is a boss fight
local CAST_FOCUS_RATIO = 0.97            -- focus below this fraction of its maximum means a power was cast
local GLARE_COOLDOWN_SECONDS = 12        -- a companion's Glare (Light School), at most this often each
local GUIDE_COOLDOWN_SECONDS = 60        -- a companion's Guiding Light, at most this often each
local LIGHT_ADDON = "com.necrosis.light-orb" -- Light School: takes "light.cast" {caster, power} (0.17.0)
local TOBIN, ALDRIC, MIRA = 1, 2, 3      -- companion indices (1-based, the order they are found: depths 1, 2, 3)
local BURN_TICK_SECONDS = 0.5            -- fire trap: one damage tick per this interval
local BURN_BASE_TICKS = 3                -- plus one tick per depth
local BURN_HEALTH_FRACTION = 0.04        -- of max health per tick, plus BURN_HEALTH_PER_DEPTH per depth
local BURN_HEALTH_PER_DEPTH = 0.01
local BURN_BALANCE_FRACTION = 0.1        -- of max balance per tick
local BURN_FALLBACK_HEALTH, BURN_FALLBACK_BALANCE = 5.0, 8.0 -- when the snapshot gives no maxima
local PUSH_BASE, PUSH_PER_DEPTH = 8, 2   -- push trap force (native units of 158870)
local FIRE_ZONE_FIRST, FIRE_ZONE_LAST = 11, 15 -- zone ids of the five fire trap slots
local PUSH_DIR = {[2] = {0, 0, -1}, [3] = {-1, 0, 0}, [4] = {0, 0, 1}, [5] = {1, 0, 0}} -- zone ids 2..5: N, W, S, E
local SEED_SALT = 0x5A17                 -- mixes the wall-clock seed so two quick starts differ
local SEED_MODULUS = 4294967296          -- seeds are 32-bit (the exit script carries 10 digits)
local ROW_AFTER_ARENA = 3                -- base title rows: BEGIN 1, CONTINUE 2, ARENA 3
local PHASE_TITLE, PHASE_PLAY = 1, 3     -- game.phase(): 1 title, 2 character screen, 3 play

local api = {
    -- the row then does what BEGIN does (character creation); levels.new_game makes that game start in our level
    add_row = function(label, after, fn, subtitle) return title.add_row(label, after, fn, {acts_as = 1, subtitle = subtitle}) end,
    -- a smaller second line under a row (planned after r28); runtimes without it ignore the option
    set_subtitle = function(label, text) if title.set_subtitle then return title.set_subtitle(label, text) end end,
    remove_row = function(label) return title.remove_row and title.remove_row(label) end,
    serve = function(member, bytes) return levels.serve(member, bytes, PACKAGE) end,
    clear_served = function() return levels.clear_served() end,
    new_game = function(member) return levels.new_game(member) end,
    travel = function(member) return levels.travel(member) end,
    current_level = function() local l = world.level and world.level() return l and l.name end,
    drive = function(record_id, on) if levels.drive then return levels.drive(record_id, on and 1 or 0) end end,
    -- world.read rows for several levers at once, by their record ids: {[index] = row}; a row has
    -- lever_position and, in a timer callback with world.levers, set_position(0 or 1)
    lever_rows = function(ids)
        if not (world and world.snapshot) then return nil end
        local scene = world.snapshot()
        if not scene or not scene.objects then return nil end
        local want, rows = {}, {}
        for i, id in ipairs(ids) do want[id] = i; want[0x80000000 | id] = i end
        for _, o in ipairs(scene.objects) do
            local i = want[o.item_id]
            if i and o.lever_position then rows[i] = o end
        end
        return rows
    end,
    -- world.read rows; a lever's lever_position needs world.levers (0.17.0)
    lever_position = function(record_id)
        if not (world and world.snapshot) then return nil end
        local scene = world.snapshot()
        if not scene or not scene.objects then return nil end
        for _, o in ipairs(scene.objects) do
            if (o.item_id == record_id or o.item_id == (0x80000000 | record_id)) and o.lever_position then return o.lever_position end
        end
        return nil
    end,
    -- runtime 0.26.0: world.level() is nil outside play (title, character screen) and has loaded = true in play
    phase = function()
        local l = world.level and world.level()
        if l and l.loaded then return PHASE_PLAY end
        return l and 2 or PHASE_TITLE
    end,
    place = function(x, y, z) return player.place(x, y, z) end,
    damage = function(balance, health, can_fall) if player.damage then return player.damage(balance, health, can_fall) end end,
    push = function(dx, dy, dz, amount) if player.push then return player.push(dx, dy, dz, amount) end end,
    read_asset = function(path) return assets.read(path) end,
    -- r41: a module run on a runtime worker thread (no game API there); nil on older runtimes
    worker = function(module, input, fn) if tasks and tasks.worker then return tasks.worker(module, input, fn) end end,
    snapshot = function() if characters and characters.snapshot then return characters.snapshot() end end,
    -- 0.28.0: a live NPC learns 1..10 Force/Energy/Displacement powers (the companions' hidden talents)
    grant_powers = function(record_id, ids) if characters and characters.grant_powers then return characters.grant_powers(record_id, ids) end end,
    -- 0.28.0-r37: another addon's message; the Light School casts Glare / Guiding Light for an NPC
    light_cast = function(row, power)
        if not (addons and addons.send) then return false end
        local caster = row.handle and {handle = row.handle} or row.record_id
        return addons.send(LIGHT_ADDON, "light.cast", {caster = caster, power = power})
    end,
    -- LuaFlag(name) in a dialogue condition reads this; a reaction node opens on its companion's flag
    set_flag = function(name, value) if script_flags and script_flags.set then return script_flags.set(name, value) end end,
    log = function(text) if log and log.info then log.info(text) else print(text) end end,
    -- 0.26.0: a short message at the bottom of the screen
    notify = function(text) if ui and ui.notify and text ~= "" then ui.notify(text) end end,
    -- 0.28.0 r25: a long job as a task (200k instructions a pulse, resumed each presented frame);
    -- without tasks it runs at once, which the runtime's budget refuses for an area build
    -- r40: `budget` instructions per pulse (10k..200k; older runtimes ignore it and give 200k)
    run_task = function(fn, done, budget)
        if tasks and tasks.run then return tasks.run(function() done(fn()) end, budget and {budget = budget} or nil) end
        done(fn())
        return true
    end,
}

local state = {
    template = nil,        -- gen template, loaded once
    seed = 0,              -- run seed (u32)
    area = 0,              -- area being played (0 = no run)
    info = nil,            -- {boss, gate, gate_lever, fires, companion} record ids of the current area
    travelling = false,    -- a travel was requested and the arrival placement is pending
    want_travel = false,   -- the player entered the exit zone
    gate_open = false,     -- the boss died and the gate was driven
    pen_open = false,      -- the boss pen's portcullis was raised on arrival
    pz = nil,              -- the boss-lock puzzle's progress in this area (watch_puzzle)
    puzzle_timer = nil,
    worker = nil,          -- the running worker job's handle (the runtime cancels it on the way to the menu)
    pen_lever = nil,       -- its lever's position when last seen settled (a change is a pull)
    row_label = nil,       -- the title row's label while it is on the menu (it carries the deepest depth)
    granted = {},          -- companion record id -> true once its powers were granted this run
    present = nil,         -- set of companion indices (0-based, as the generator counts) in the party
    lesson_seconds = 0,    -- time Tobin has spent with Mira after her reveal
    focus_seen = {},       -- row key -> true once a readable focus was seen (the first casting is a drop from it)
    cast_seen = {},        -- row key -> true once that character's first casting was reacted to
    cast_cool = {},        -- "<power>_<index>" -> seconds before that companion casts that power again
    last_health = {},      -- party row key -> health at the last poll (a drop is a hit)
    dead_seen = {},        -- companion index -> true once its death was reacted to
    met = {},              -- 0-based companion indices ever seen this run (a met one is not found again)
    building = nil,        -- the area whose build task is running (one at a time)
    in_backrooms = false,  -- the player is in the backrooms of the current area (easter egg 4)
    prebuilt = nil,        -- the next area built during play: {area, key, bytes, info} (used if key still matches)
    run = 0,               -- counts menus: a build task started before the latest menu is dropped when it ends
    after_build = nil,     -- what waits for such a build (a CONTINUE restore): it runs when the old build is done
    want_backrooms = false, -- the backrooms corner was entered while a build ran; it opens when that ends
    bosses = 0,            -- gates opened this run (bosses killed), for the run summary
    party_timer = nil,     -- the party poll
    place_timer = nil,
    burn_timer = nil,
    boss_timer = nil,
}

local function say(text) api.log("Endless: " .. text) end

-- the title row shows the deepest depth any run reached, so the menu itself is the scoreboard
-- the title row is just ENDLESS, like the game's own rows (Hunter: the title font dropped the
-- parentheses and the number); the deepest depth and the last run are told on screen instead
local function row_label() return "ENDLESS" end

-- the second, smaller line under the row: the deepest depth and the last descent (Hunter)
local function row_subtitle()
    local best = tonumber(storage.get("endless.best_depth", 0)) or 0
    if best <= 0 then return nil end
    local text = string.format("Deepest: depth %d", best)
    local depth = (storage.get("endless.last", "") or ""):match("^(%d+),")
    if depth then text = text .. string.format("    Last descent: depth %s", depth) end
    return text
end

-- the records, as plain sentences for a short on-screen message
local function records_text()
    local best = tonumber(storage.get("endless.best_depth", 0)) or 0
    local last = storage.get("endless.last", "") or ""
    local depth, areas, bosses = last:match("^(%d+),(%d+),(%d+)")
    local parts = {}
    if best > 0 then parts[#parts + 1] = string.format("Deepest reached: depth %d.", best) end
    if depth then
        parts[#parts + 1] = string.format("Last descent: depth %s, %s area%s, %s boss%s slain.", depth, areas, areas == "1" and "" or "s", bosses, bosses == "1" and "" or "es")
    end
    return table.concat(parts, " ")
end

local function save_met()
    local list = {}
    for index in pairs(state.met) do list[#list + 1] = tostring(index) end
    table.sort(list)
    storage.set("endless.met", table.concat(list, ","))
end

local function load_met()
    state.met = {}
    for v in (storage.get("endless.met", "") or ""):gmatch("[^,]+") do state.met[tonumber(v)] = true end
end
-- the terrain template: a 1 x 1 terrain, the head (28 bytes) and the first tile of a story level's own
-- .rft. Shipped builds carry it (assets/, made from exanima01.rft: byte-identical, checked offline); a
-- build without the game-derived files makes it here once from the player's own game and keeps it in
-- cache/: a ranged levels.read (r54) of exanima01.rft's first 354,414 bytes gives the shipped bytes; an
-- older runtime refuses exanima01.rft (9.1 MB, over its 8 MiB) and exanima02.rft (same head) serves
local TERRAIN_SOURCES = {"exanima01.rft", "exanima02.rft", "exanima03.rft"}
local terrain_raw
local function terrain_template()
    if terrain_raw then return terrain_raw end
    terrain_raw = api.read_asset("assets/endless-template.rft") or api.read_asset("cache/endless-template.rft")
    if terrain_raw then return terrain_raw end
    if not (levels and levels.read) then say("no terrain template, and this runtime cannot read the game's files") return nil end
    for _, src in ipairs(TERRAIN_SOURCES) do
        -- r54: only the slice needed (its head says the first tile's size); older runtimes ignore the range
        -- and return the whole member (refused over 8 MiB, so exanima01.rft fails there and the next serves)
        local ok, data, why = pcall(levels.read, src, "Resource.rpk", {offset = 0, length = 48})
        if ok and data and #data >= 48 then
            local _, size = string.unpack("<I4I4", data, 41)
            if #data < 48 + size then ok, data, why = pcall(levels.read, src, "Resource.rpk", {offset = 0, length = 48 + size}) end
        end
        if ok and data and #data >= 48 then
            local _, size = string.unpack("<I4I4", data, 41)
            local cut = data:sub(1, 28) .. string.pack("<i4i4I4", 1, 1, 1) .. data:sub(41, 48 + size)
            data = nil
            if gen.load_terrain_template({}, cut) then
                terrain_raw = cut
                if assets and assets.write then pcall(assets.write, "cache/endless-template.rft", cut) end
                say("terrain template made from the game's " .. src .. " (" .. #cut .. " bytes)")
                return cut
            end
        else
            say("terrain source " .. src .. " not read: " .. tostring(ok and why or data))
        end
    end
    say("no terrain template could be made")
    return nil
end

local function template()
    if state.template then return state.template end
    local rfc, ini, rft = api.read_asset("assets/endless-template.rfc"), api.read_asset("assets/endless-template.ini"), terrain_template()
    if not rfc or not ini or not rft then say("template files missing") return nil end
    local t, why = gen.load_template(rfc, ini)
    if not t then say("template rejected: " .. tostring(why)) return nil end
    local ok, why2 = gen.load_terrain_template(t, rft)
    if not ok then say("terrain template rejected: " .. tostring(why2)) return nil end
    say(string.format("template loaded: %d bytes, %d companions", #rfc, #t.companion_ids))
    state.template = t
    return t
end

-- the depth and the tile-set stage of the area being served, for the title row and for the
-- dialogue (LuaFlag endless_depth / endless_stage: the companions' new-depth lines match the stone)
local function note_depth(area)
    local depth = gen.depth_of(area)
    local best = tonumber(storage.get("endless.best_depth", 0)) or 0
    if depth > best then storage.set("endless.best_depth", depth) end
    api.set_flag("endless_depth", depth)
    local t = template()
    if t then api.set_flag("endless_stage", gen.stage_index(t, area)) end
end

-- the generator is deterministic, so an area's record ids come back from (seed, area) alone
-- an area's build (2-4 million instructions) runs as a task; `done(bytes, info, terrain)` follows
-- what a build reads besides (seed, area): the party present, the companions met, the last descent's
-- area and the shrine; a prebuilt area is used only while these are unchanged
local function build_inputs()
    -- easter eggs: the shrine's carving once a run
    local parts = {}
    for i = 0, 2 do
        parts[#parts + 1] = (state.present and state.present[i]) and "p" or "-"
        parts[#parts + 1] = state.met[i] and "m" or "-"
    end
    parts[#parts + 1] = state.shrine_done and "s" or "-"
    return state.present, state.met, {shrine_done = state.shrine_done}, table.concat(parts)
end

local BACKGROUND_BUDGET = 50000 -- a build ahead during play: about a quarter of the default, so it stays out of the frame
-- a build on a runtime worker thread (r41): nothing of it runs in the game's frames. `input.kind` is "area"
-- or "backrooms"; `done(bytes, info, terrain)`. False when there is no worker (older runtime) or it refused.
local function build_on_worker(input, done)
    if not (tasks and tasks.worker) then return false end
    input.rfc, input.ini = api.read_asset("assets/endless-template.rfc"), api.read_asset("assets/endless-template.ini")
    input.rft, input.dress = terrain_template(), api.read_asset("assets/endless-dress.bin")
    local run = state.run
    local ok, handle = pcall(api.worker, "build_worker", input, function(r, err)
        state.building, state.worker = nil, nil
        if run ~= state.run then -- from before the menu (a job started at the menu survives into the session)
            local after = state.after_build
            state.after_build = nil
            if after then after() end
            return
        end
        if not r then say(input.kind .. " " .. input.area .. " build failed on the worker: " .. tostring(err)) return end
        done(r.bytes, r.info, r.terrain)
    end)
    if ok and handle then state.worker = handle return true end
    say("worker refused (" .. tostring(handle) .. "); building in the game's frames")
    return false
end

local function build_area(area, done, budget)
    local t = template()
    if not t then return false end
    if state.building then say("area " .. state.building .. " is still building") return false end
    state.building = area
    local present, met, opts = build_inputs()
    local run = state.run
    local seed = state.seed
    if build_on_worker({kind = "area", seed = seed, area = area, present = present, met = met, opts = opts}, done) then return true end
    local started = api.run_task(function()
        -- the dressings are parsed for this build and dropped after it (several MB of tables otherwise);
        -- a menu stops the build at its next checkpoint (gen.cancelled)
        gen.cancelled = function() return run ~= state.run end
        local ok, bytes, info = pcall(function()
            gen.load_dress(t, api.read_asset("assets/endless-dress.bin"))
            local b, _, i = gen.build(t, seed, area, present, met, opts)
            return b, i
        end)
        t.dress, gen.cancelled = nil, nil
        if not ok then return {nil, nil, bytes} end
        return {bytes, info}
    end, function(r)
        state.building = nil
        if run ~= state.run then -- started before the menu: stopped early (or finished) and dropped
            say("a build from before the menu ended; dropped")
            local after = state.after_build
            state.after_build = nil
            if after then after() end
            return
        end
        if not r[1] then say("area " .. area .. " build failed: " .. tostring(r[3])) return end
        done(r[1], r[2])
    end, budget)
    if not started then state.building = nil; say("build task refused") end
    return started
end

-- build, then serve under an arena level name; `done(name)` follows (nothing on refusal)
local function serve_area(area, done)
    local function serve_built(bytes, info, terrain_built)
        local name = gen.floor_name(area)
        local level_size = #bytes
        if not api.serve(name .. ".rfc", bytes) then say("serve refused for " .. name) return end
        bytes = nil -- the level bytes are the runtime's now; the terrain (1.4 MB) is built with them gone
        -- the terrain too: these level names carry an arena terrain that would show under the dungeon
        local run = state.run
        local function finish(terrain)
            if run ~= state.run then return end -- the menu came between: this area is not wanted now
            if not api.serve(name .. ".rft", terrain) then say("terrain serve refused for " .. name) return end
            state.info = info
            state.gate_open = false
            note_depth(area)
            api.set_flag("endless_archetype", info.archetype or 0) -- 0 warren, 1 crypt, 2 cistern, 3 mine, 4 halls
            api.set_flag("endless_mutator", info.mutator or 0)     -- 0 none, 1 dark, 2 ambush, 3 silent, 4 collapsed
            -- easter eggs in this area, for the lines that will answer them (Hunter approves the words first)
            api.set_flag("endless_egg_elara", info.elara or 0)
            api.set_flag("endless_egg_shrine", info.shrine or 0)
            api.set_flag("endless_egg_copy", info.copy or 0)
            say(string.format("area %d (depth %d) served as %s: level %d bytes, terrain %d bytes, boss %d, gate %d, companion %d",
                area, gen.depth_of(area), name, level_size, #terrain, info.boss, info.gate, info.companion or 0))
            if info.shrine then
                state.shrine_done = true
                storage.set("endless.shrine", 1)
            end
            done(name)
        end
        if terrain_built then finish(terrain_built) return end
        local t = template()
        api.run_task(function() return gen.build_terrain(t) end, finish)
    end
    local pre = state.prebuilt
    state.prebuilt = nil
    if pre and pre.area == area then
        local _, _, _, key = build_inputs()
        if pre.key == key then
            say("area " .. area .. " was built during play")
            serve_built(pre.bytes, pre.info, pre.terrain)
            return true
        end
        say("area " .. area .. " was built during play, but the party changed since: building again")
    end
    return build_area(area, serve_built)
end

-- the next area, built in the background once this one is entered, so the exit door does not wait;
-- a travel or the backrooms asked for meanwhile go on when it is done
local PREBUILD_DELAY_SECONDS = 5 -- after arriving, before the next area builds (the last build's memory is freed first)
local prebuild_now
local function prebuild()
    local run = state.run
    timers.after(PREBUILD_DELAY_SECONDS, function() if run == state.run then prebuild_now() end end)
end
prebuild_now = function()
    if state.building or state.in_backrooms or state.area == 0 or not state.seed then return end
    local area = state.area + 1
    if state.prebuilt and state.prebuilt.area == area then return end
    local _, _, _, key = build_inputs()
    build_area(area, function(bytes, info, terrain)
        state.prebuilt = {area = area, key = key, bytes = bytes, info = info, terrain = terrain}
        say("area " .. area .. " built ahead")
        if state.want_backrooms then
            state.want_backrooms = false
            state.enter_backrooms()
        elseif state.want_travel then
            state.next_area()
        end
    end, BACKGROUND_BUDGET)
end

-- the companions' talents: their records ship without a caster block. Mira's is granted at her
-- reveal (dialogue action), at betrayal (Engage) or when anyone in the party is near death;
-- Tobin's wakes in a boss fight after enough time with Mira. Once per run each, remembered in
-- storage so CONTINUE grants again (the runtime does not know whether saves keep the change).
local function companion_record(index)
    local t = template()
    return t and t.companion_ids[index] or 0
end

local function reveal(index, reason)
    local record = companion_record(index)
    if record == 0 or state.granted[record] then return end
    local t = template()
    for _, entry in ipairs(t.reveal) do
        if entry[1] == record then
            local ok = api.grant_powers(record, entry[2])
            say(string.format("reveal (%s): record %d granted %d powers: %s", tostring(reason), record, #entry[2], ok and "accepted" or "refused or unavailable"))
            if ok then
                state.granted[record] = true
                local list = {}
                for id in pairs(state.granted) do list[#list + 1] = tostring(id) end
                table.sort(list)
                storage.set("endless.granted", table.concat(list, ","))
            end
        end
    end
end

local function regrant()
    for id in (storage.get("endless.granted", "") or ""):gmatch("[^,]+") do
        local record = tonumber(id)
        local t = template()
        if record and t then
            for index, cid in ipairs(t.companion_ids) do
                if cid == record then reveal(index, "continue") end
            end
        end
    end
end

-- the party: living companions near the player, as a set of 0-based companion indices (the
-- generator's count), so the next area's talk zones go to the first present speaker
local function party_present(snap)
    local t = template()
    if not t or not snap then return nil end
    local player
    for _, row in ipairs(snap.characters) do if row.is_player then player = row end end
    local present = {}
    for _, row in ipairs(snap.characters) do
        if row.record_id and not row.dead then
            for index, cid in ipairs(t.companion_ids) do
                if cid == row.record_id then
                    local near = true
                    if player and player.position and row.position then
                        local dx, dz = row.position[1] - player.position[1], row.position[3] - player.position[3]
                        near = dx * dx + dz * dz <= PRESENT_RANGE_CM * PRESENT_RANGE_CM
                    end
                    if near then present[index - 1] = true end
                end
            end
        end
    end
    return present
end

local function first_present(order)
    for _, index in ipairs(order) do
        if state.present and state.present[index - 1] then return index end
    end
    return nil
end

-- a first casting: the first present observer's reaction node opens (its LuaFlag); the node's
-- own last line opens the exchange with the next in the order
local SAW_ORDER = {you = {ALDRIC, MIRA, TOBIN}, mira = {ALDRIC, TOBIN}} -- the same orders as the dialogue (SPOT_ORDER)
local function react(which, order)
    local observer = first_present(order)
    if not observer then return end
    local name = string.format("endless_saw_%s_%d", which, observer - 1)
    local ok = api.set_flag(name, 1)
    say(string.format("first casting (%s): flag %s %s", which, name, ok and "set" or "refused or unavailable"))
end

local function watch_castings(snap)
    local t = template()
    for _, row in ipairs(snap.characters) do
        local key, which, order, gate
        if row.is_player then
            key, which, order = "player", "you", SAW_ORDER.you
        elseif row.record_id == companion_record(MIRA) then
            key, which, order, gate = "mira", "mira", SAW_ORDER.mira, state.granted[row.record_id] or false
        elseif row.record_id == companion_record(TOBIN) then
            key, which, gate = "tobin", "spark", state.granted[row.record_id] or false
        end
        if key and not state.cast_seen[key] and row.focus and row.focus_max and row.focus_max > 0 then
            if not state.focus_seen[key] then
                state.focus_seen[key] = true
            elseif (gate == nil or gate) and row.focus < row.focus_max * CAST_FOCUS_RATIO then
                state.cast_seen[key] = true
                if which == "spark" then
                    local ok = api.set_flag("endless_spark_" .. (TOBIN - 1), 1)
                    say("Tobin's first casting: flag " .. (ok and "set" or "refused or unavailable"))
                else
                    react(which, order)
                end
            end
        end
    end
end

-- a companion's death: its flag stops the lines about it; the first present survivor in the
-- occasion's order gets the reaction flag (its node opens on it and hops to the other survivor)
local DEAD_ORDER = {[TOBIN] = {ALDRIC, MIRA}, [ALDRIC] = {MIRA, TOBIN}, [MIRA] = {ALDRIC, TOBIN}}
local DEAD_NAME = {[TOBIN] = "tobin", [ALDRIC] = "aldric", [MIRA] = "mira"}
local function watch_deaths(snap)
    local t = template()
    for _, row in ipairs(snap.characters) do
        if row.dead and row.record_id then
            for index, cid in ipairs(t.companion_ids) do
                if cid == row.record_id and not state.dead_seen[index] then
                    state.dead_seen[index] = true
                    api.set_flag("endless_dead_" .. (index - 1), 1)
                    local observer = first_present(DEAD_ORDER[index])
                    if observer then
                        local name = string.format("endless_dead_%s_%d", DEAD_NAME[index], observer - 1)
                        local ok = api.set_flag(name, 1)
                        say(string.format("%s is dead: flag %s %s", DEAD_NAME[index], name, ok and "set" or "refused or unavailable"))
                    else
                        say(DEAD_NAME[index] .. " is dead, nobody left to say so")
                    end
                end
            end
        end
    end
end

-- a boss fight: the area's boss alive and hurt, or this close to the player
local function boss_fight(snap)
    local info = state.info
    if not info or info.boss == 0 then return false end
    local player, boss
    for _, row in ipairs(snap.characters) do
        if row.is_player then player = row elseif row.record_id == info.boss and not row.dead then boss = row end
    end
    if not boss then return false end
    if boss.health and boss.health_max and boss.health < boss.health_max then return true end
    if player and player.position and boss.position then
        local dx, dz = boss.position[1] - player.position[1], boss.position[3] - player.position[3]
        return dx * dx + dz * dz <= BOSS_FIGHT_RANGE_CM * BOSS_FIGHT_RANGE_CM
    end
    return false
end

-- Light School casts (Hunter: companions use Guiding Light and Glare): Mira and Tobin, each only after
-- their talent is granted, present and alive. Glare when anyone in the party was just hit; Guiding
-- Light in a boss fight. One caster per power per poll, Mira first. Sent straight to the Light School
-- ("light.cast", the caster by its character handle, else its record id).
local CASTERS = {MIRA, TOBIN}
local CAST_POWERS = {"glare", "guide"}
local function watch_light(snap)
    local t = template()
    for name, left in pairs(state.cast_cool) do state.cast_cool[name] = left > PARTY_POLL_SECONDS and left - PARTY_POLL_SECONDS or nil end
    local party = {}
    for _, id in ipairs(t.companion_ids) do party[id] = true end
    local hit, rows = false, {}
    for _, row in ipairs(snap.characters) do
        local key = row.is_player and "player" or (row.record_id and party[row.record_id] and row.record_id)
        if key then
            rows[key] = row
            if row.health then
                local before = state.last_health[key]
                if before and not row.dead and row.health < before then hit = true end
                state.last_health[key] = row.health
            end
        end
    end
    local want = {glare = hit, guide = boss_fight(snap)}
    for _, power in ipairs(CAST_POWERS) do
        if want[power] then
            for _, index in ipairs(CASTERS) do
                local record = companion_record(index)
                local row = rows[record]
                local name = power .. "_" .. index
                if state.granted[record] and row and not row.dead and state.present and state.present[index - 1]
                    and not state.cast_cool[name] then
                    local ok = api.light_cast(row, power)
                    state.cast_cool[name] = power == "glare" and GLARE_COOLDOWN_SECONDS or GUIDE_COOLDOWN_SECONDS
                    say(string.format("%s casts %s: %s", index == MIRA and "Mira" or "Tobin", power, ok and "sent" or "no Light School to take it"))
                    break
                end
            end
        end
    end
end

-- Tobin's talent wakes in a boss fight after enough time with Mira (both present, after her reveal)
local function watch_tobin(snap)
    if state.granted[companion_record(TOBIN)] or not state.granted[companion_record(MIRA)] then return end
    if not (state.present and state.present[MIRA - 1] and state.present[TOBIN - 1]) then return end
    state.lesson_seconds = state.lesson_seconds + PARTY_POLL_SECONDS
    if state.lesson_seconds < LESSON_SECONDS then return end
    if boss_fight(snap) then reveal(TOBIN, "boss fight, after " .. math.floor(state.lesson_seconds) .. " s with Mira") end
end

-- the party poll: presence, near death (Mira's forced reveal), Tobin's lessons, first castings
local function watch_party()
    if state.party_timer then return end -- one poll per run; the menu cancels it
    state.party_timer = timers.every(PARTY_POLL_SECONDS, function()
        if api.phase() ~= PHASE_PLAY then return end
        local t = template()
        local snap = api.snapshot()
        if not t or not snap then return end
        state.present = party_present(snap)
        local changed = false
        for _, row in ipairs(snap.characters) do
            if row.record_id then
                for index, cid in ipairs(t.companion_ids) do
                    if cid == row.record_id and not state.met[index - 1] then state.met[index - 1] = true; changed = true end
                end
            end
        end
        if changed then save_met() end
        if not state.granted[companion_record(MIRA)] then
            local party = {}
            for _, id in ipairs(t.companion_ids) do party[id] = true end
            for _, row in ipairs(snap.characters) do
                local member = row.is_player or (row.record_id and party[row.record_id])
                if member and not row.dead and row.health and row.health_max and row.health_max > 0
                    and row.health / row.health_max < REVEAL_HEALTH_RATIO then
                    reveal(MIRA, "near death: " .. tostring(row.name or (row.is_player and "player") or row.record_id))
                    break
                end
            end
        end
        watch_tobin(snap)
        watch_castings(snap)
        watch_light(snap)
        watch_deaths(snap)
    end)
end

-- the gate opens once the boss is dead; the check repeats until the drive is accepted
-- the boss beaten (dead, or caged in its pen): the gate to the exit opens
local function boss_beaten(info, how)
    if api.drive(info.gate, true) then
        state.gate_open = true
        state.bosses = state.bosses + 1
        say(string.format("boss %d %s, gate %d driven open", info.boss, how, info.gate))
        timers.cancel(state.boss_timer)
        state.boss_timer = nil
    end
end

-- the boss pen (Hunter: lure the boss in, drop the portcullis): raised once on arrival; a pull of its
-- lever while the living boss stands inside the pen's box cages it, which counts as beating it
local PEN_PULL = 0.5 -- the lever's travel (0..1) that counts as a pull
local function boss_in_pen(row, box)
    local p = row.position
    return p and p[1] >= box[1] and p[1] <= box[3] and p[3] >= box[2] and p[3] <= box[4]
end
local function watch_pen(info, boss)
    if not info.pen_gate then return false end
    if not state.pen_open then
        state.pen_open = api.drive(info.pen_gate, true) and true or false
        if state.pen_open then say("boss pen raised") end
        return false
    end
    local pos = api.lever_position(info.pen_lever)
    if not pos then return false end
    if state.pen_lever == nil then state.pen_lever = pos return false end
    if math.abs(pos - state.pen_lever) < PEN_PULL then return false end
    state.pen_lever = pos -- pulled: the next pull is measured from here
    if boss and not boss.dead and boss_in_pen(boss, info.pen_box) then
        api.drive(info.pen_gate, false) -- the lever drops it; this makes sure
        api.set_flag("endless_boss_caged", 1)
        return true
    end
    say("pen lever pulled with the boss outside")
    return false
end

-- the boss-lock puzzles (Hunter, 2026-10-22: weight plate, lever order, timed gate with a failsafe, hold
-- the door); the generator puts the puzzle's portcullis in the boss doorway (info.puzzle, endless_gen)
local PUZZLE_POLL_SECONDS = 0.5
local PLATE_REACH_CM = 90       -- a character this close to the plate's middle stands on it
local TIMED_RETRY_GROWTH = 1.5  -- each missed timed run leaves the gate up this much longer next time
local LEVER_SETTLE_POLLS = 4    -- after the levers spring back, polls before they are read again
local function in_box(p, box) return p and box and p[1] >= box[1] and p[1] <= box[3] and p[3] >= box[2] and p[3] <= box[4] end
local function puzzle_step(info, pz)
    local kind = info.puzzle
    if kind == "plate" or kind == "hold" then
        -- a character on the plate holds the gate up: a companion told to wait, or a body dragged onto it
        -- (so a held door needs no companion); an object's weight is the plate's own business (the game's
        -- plate drives the same gate)
        local snap = api.snapshot()
        if not snap then return end
        local on = false
        for _, row in ipairs(snap.characters) do
            local p = row.position
            if not row.is_player and p then
                local dx, dz = p[1] - info.puzzle_plate[1], p[3] - info.puzzle_plate[2]
                if dx * dx + dz * dz <= PLATE_REACH_CM * PLATE_REACH_CM then on = true end
            end
        end
        if on and not pz.held then
            pz.held = api.drive(info.puzzle_gate, true) and true or false
            if pz.held then say("someone stands on the plate: the gate rises") end
        elseif not on and pz.held then
            api.drive(info.puzzle_gate, false)
            pz.held = false
            say("the plate is empty: the gate falls")
        end
        return
    end
    local rows = api.lever_rows(info.puzzle_levers)
    if not rows then return end
    local pos = {}
    for i = 1, #info.puzzle_levers do
        if not rows[i] then return end
        pos[i] = rows[i].lever_position
    end
    if pz.settle and pz.settle > 0 then pz.settle = pz.settle - 1 return end
    if not pz.base then
        pz.base, pz.start = {}, pz.start or {}
        for i = 1, #pos do pz.base[i] = pos[i]; if pz.start[i] == nil then pz.start[i] = pos[i] end end
        return
    end
    if kind == "order" then
        for i = 1, #pos do
            if math.abs(pos[i] - pz.base[i]) >= PEN_PULL then
                pz.base[i] = pos[i]
                if i == pz.progress + 1 then
                    pz.progress = i
                    if i == #pos then
                        pz.solved = api.drive(info.puzzle_gate, true) and true or false
                        api.set_flag("endless_puzzle_solved", 1)
                        say("the levers in their order: the gate rises")
                    end
                else
                    say("lever " .. i .. " out of order: they spring back")
                    pz.progress = 0
                    for j = 1, #pos do
                        local row = rows[j]
                        if row.set_position and math.abs(pos[j] - pz.start[j]) >= PEN_PULL then pcall(row.set_position, row, pz.start[j] < 0.5 and 0 or 1) end
                    end
                    pz.base, pz.settle = nil, LEVER_SETTLE_POLLS
                end
                return
            end
        end
        return
    end
    -- timed: the near lever raises the gate for a while; the inside lever (the failsafe) raises it for good
    local now = timers.now()
    if math.abs(pos[2] - pz.base[2]) >= PEN_PULL then
        pz.solved = api.drive(info.puzzle_gate, true) and true or false
        say("the inside lever holds the gate up")
        return
    end
    if pz.deadline then
        if now >= pz.deadline then
            local through = false
            local snap = api.snapshot()
            for _, row in ipairs(snap and snap.characters or {}) do
                if row.is_player and in_box(row.position, info.puzzle_inside) then through = true end
            end
            if through then
                pz.solved = true
                api.set_flag("endless_puzzle_solved", 1)
                say("through the gate in time")
                return
            end
            api.drive(info.puzzle_gate, false)
            pz.deadline, pz.fails = nil, pz.fails + 1
            say("the gate falls (" .. pz.fails .. " missed)")
        end
        return
    end
    if math.abs(pos[1] - pz.base[1]) >= PEN_PULL then
        pz.base[1] = pos[1]
        if api.drive(info.puzzle_gate, true) then
            local seconds = info.puzzle_seconds * TIMED_RETRY_GROWTH ^ pz.fails
            pz.deadline = now + seconds
            say(string.format("the gate rises for %.0f s", seconds))
        end
    end
end
local function watch_puzzle()
    if state.puzzle_timer then timers.cancel(state.puzzle_timer); state.puzzle_timer = nil end
    state.pz = {progress = 0, fails = 0}
    local info = state.info
    if not info or not info.puzzle then return end
    state.puzzle_timer = timers.every(PUZZLE_POLL_SECONDS, function()
        local now_info = state.info
        if not now_info or not now_info.puzzle or state.pz.solved or api.phase() ~= PHASE_PLAY then return end
        puzzle_step(now_info, state.pz)
    end)
end

local function watch_boss()
    watch_puzzle()
    if state.boss_timer then timers.cancel(state.boss_timer) end
    state.pen_open, state.pen_lever = false, nil
    state.boss_timer = timers.every(BOSS_POLL_SECONDS, function()
        local info = state.info
        if not info or info.boss == 0 or state.gate_open or api.phase() ~= PHASE_PLAY then return end
        local snap = api.snapshot()
        if not snap then return end
        local boss
        for _, row in ipairs(snap.characters) do
            if row.record_id == info.boss then
                if row.dead then boss_beaten(info, "dead") return end
                boss = boss or row
            end
        end
        if watch_pen(info, boss) then boss_beaten(info, "caged in the pen") end
    end)
end

-- ENDLESS on the title menu: a new story character on area 1
local function start_run(waited)
    -- the row was pressed on the title; after a wait the game has gone on to the character screen,
    -- which is where the level must still be set (once play has begun it is too late)
    if not waited and api.phase() ~= PHASE_TITLE then return end
    if waited and api.phase() == PHASE_PLAY then say("the earlier build ended too late for this run") return end
    if state.building then -- a build from before the menu still runs: it stops at its next checkpoint
        say("waiting for an earlier build to stop")
        state.after_build = function() start_run(true) end
        return
    end
    state.seed = (math.floor(timers.now() * 1000) % SEED_MODULUS) ~ SEED_SALT
    if state.seed == 0 then state.seed = 1 end
    state.area = 1
    state.travelling = false
    state.want_travel = false
    state.met = {}
    state.bosses = 0
    say("descending: building area 1 (seed " .. state.seed .. ")")
    api.notify(records_text())
    serve_area(1, function(name)
        storage.set("endless.seed", state.seed)
        storage.set("endless.area", 1)
        storage.set("endless.granted", "")
        storage.set("endless.met", "")
        storage.set("endless.shrine", 0)
        api.new_game(name)
        watch_boss()
        watch_party()
        say("run started, seed " .. state.seed)
        prebuild()
    end)
end

-- after a travel the game puts the player on the default transform; move them to the start room
local function arm_placement(name, x, z)
    if state.place_timer then timers.cancel(state.place_timer) end
    local waited = 0
    state.place_timer = timers.every(PLACE_POLL_SECONDS, function()
        waited = waited + PLACE_POLL_SECONDS
        if api.phase() == PHASE_PLAY and api.current_level() == name then
            api.place(x or gen.START_X, PLACE_Y, z or gen.START_Z)
            state.travelling = false
            timers.cancel(state.place_timer)
            state.place_timer = nil
            say("arrived in " .. name .. (x and ", placed at the room that sent you" or ", placed at the start room"))
            watch_boss()
            state.want_travel = false -- an exit zone entered again while the travel was pending is not a new wish
            if not state.in_backrooms then prebuild() end
        elseif waited > PLACE_GIVE_UP_SECONDS then
            state.travelling = false
            timers.cancel(state.place_timer)
            state.place_timer = nil
            say("travel to " .. name .. " never landed")
        end
    end)
end

local function next_area()
    if state.travelling or state.building or state.area == 0 then return end -- a running build calls back when done
    local area = state.area + 1
    say("descending: building area " .. area)
    serve_area(area, function(name)
        state.area = area
        state.travelling = true
        state.want_travel = false
        storage.set("endless.area", area)
        api.travel(name)
        arm_placement(name)
        say("travelling to area " .. area)
    end)
end
state.next_area = next_area

-- a companion's trust reveal (a dialogue action raises it): grant the powers the record was built without
events.on("script.event", function(event)
    if event.name ~= "EndlessReveal" then return end
    reveal(MIRA, event.value) -- she tells you (1), is betrayed (2) or sees death near (3); the grant happens once
end)

-- the backrooms (easter egg 4, Hunter): walking into the corner behind the chair in the perfect copy
-- takes you to a vast empty level built for this area; its exit returns you to that room
local function backrooms_name(area) return gen.floor_name(area + 7) end -- never this area's or the next one's
local function enter_backrooms()
    if state.building and not state.in_backrooms then state.want_backrooms = true return end -- after the running build
    if state.travelling or state.building or state.in_backrooms or state.area == 0 then return end
    local t = template()
    if not t then return end
    local area = state.area
    state.building = area
    say("the corner gives way: building the backrooms of area " .. area)
    local function go_in(bytes, terrain)
        local name = backrooms_name(area)
        if not api.serve(name .. ".rfc", bytes) then say("backrooms serve refused") return end
        if not api.serve(name .. ".rft", terrain) then say("backrooms terrain refused") return end
        state.in_backrooms = true
        state.travelling = true
        api.travel(name)
        arm_placement(name)
        say("into the backrooms of area " .. area)
    end
    if build_on_worker({kind = "backrooms", seed = state.seed, area = area}, function(bytes, _, terrain) go_in(bytes, terrain) end) then return end
    local run = state.run
    api.run_task(function()
        -- its furniture comes from the stone's dressings: parsed for this build and dropped after it
        gen.load_dress(t, api.read_asset("assets/endless-dress.bin"))
        local bytes, lay, info = gen.build_backrooms(t, state.seed, area)
        t.dress = nil
        return {bytes, lay, info}
    end, function(r)
        state.building = nil
        if run ~= state.run then
            local after = state.after_build
            state.after_build = nil
            if after then after() end
            return
        end
        local bytes = r[1]
        api.run_task(function() return gen.build_terrain(t) end, function(terrain) go_in(bytes, terrain) end)
    end)
end
local function leave_backrooms()
    if state.travelling or not state.in_backrooms then return end
    local name = gen.floor_name(state.area)
    local info = state.info or {}
    state.in_backrooms = false
    state.travelling = true
    api.travel(name)
    arm_placement(name, info.copy_x, info.copy_z)
    say("out of the backrooms, back to area " .. state.area)
end
state.enter_backrooms = enter_backrooms

-- the exit zone script carries "area_seed" so CONTINUE from a save restores the run
local function on_area_script(event)
    if event.name ~= "EndlessNext" and event.name ~= "EndlessBack" then return end
    local area, seed = tostring(event.value):match("^(%d+)_(%d+)$")
    if not area then return end
    -- the script restores a run the mod knows nothing of (CONTINUE); in play it names the area being
    -- left, which the mod may already have moved past (the next area was built ahead)
    if not state.info then
        state.area, state.seed = tonumber(area), tonumber(seed)
        if event.name == "EndlessBack" then state.in_backrooms = true end -- CONTINUE inside the backrooms
    end
    if not state.info and state.building then -- a build from before the menu still runs: restore after it
        state.after_build = function() on_area_script(event) end
        return
    end
    if not state.info and not state.building then
        watch_party()
        load_met()
        state.shrine_done = (tonumber(storage.get("endless.shrine", 0)) or 0) == 1
        regrant()
        build_area(state.area, function(_, info)
            state.info = info
            say(string.format("run restored from the level: area %d, seed %d", state.area, state.seed))
            watch_boss()
            if state.want_travel then next_area() else prebuild() end
        end)
        return
    end
    if state.want_travel then next_area() end
end
events.on("script.event", on_area_script)

-- fire trap damage: the engine's fire is only light and force, so the mod applies the burn
local function burn(depth)
    if state.burn_timer then timers.cancel(state.burn_timer) end
    local ticks = BURN_BASE_TICKS + depth
    state.burn_timer = timers.every(BURN_TICK_SECONDS, function()
        ticks = ticks - 1
        local health, balance = BURN_FALLBACK_HEALTH, BURN_FALLBACK_BALANCE
        local snap = api.snapshot()
        if snap then
            for _, row in ipairs(snap.characters) do
                if row.is_player then
                    if row.health_max and row.health_max > 0 then health = row.health_max * (BURN_HEALTH_FRACTION + BURN_HEALTH_PER_DEPTH * depth) end
                    if row.balance_max and row.balance_max > 0 then balance = row.balance_max * BURN_BALANCE_FRACTION end
                end
            end
        end
        api.damage(balance, health, ticks == 0)
        if ticks <= 0 then timers.cancel(state.burn_timer); state.burn_timer = nil end
    end)
end

events.on("zone.enter", function(event)
    if not event.is_player then return end -- an NPC in a zone must not end the area or burn the player
    if event.name == "EndlessNext" then
        if state.in_backrooms then -- the backrooms' way out leads back to the room that sent you
            say("player found the way out of the backrooms")
            leave_backrooms()
            return
        end
        say("player entered the exit zone")
        state.want_travel = true
        if state.area > 0 then next_area() end
        return
    end
    if event.name == "Endless Wall" then
        enter_backrooms()
        return
    end
    local depth = gen.depth_of(math.max(state.area, 1))
    if event.zone_id >= FIRE_ZONE_FIRST and event.zone_id <= FIRE_ZONE_LAST then
        say("fire trap " .. (event.zone_id - FIRE_ZONE_FIRST + 1))
        burn(depth)
    elseif PUSH_DIR[event.zone_id] then
        local d = PUSH_DIR[event.zone_id]
        say("push trap " .. event.zone_id)
        api.push(d[1], d[2], d[3], PUSH_BASE + PUSH_PER_DEPTH * depth)
    end
end)

events.on("runtime.phase", function(event)
    if event.phase ~= "menu" then return end
    if state.area > 0 then -- a run ended (death, or the player left): its summary for the title row
        local lost = 0
        for _ in pairs(state.dead_seen) do lost = lost + 1 end
        storage.set("endless.last", string.format("%d,%d,%d,%d", gen.depth_of(state.area), state.area, state.bosses, lost))
        say(string.format("run ended at area %d (depth %d): %d bosses, %d companions lost", state.area, gen.depth_of(state.area), state.bosses, lost))
    end
    local label = row_label()
    if state.row_label and state.row_label ~= label and api.remove_row(state.row_label) then state.row_label = nil end
    if not state.row_label then
        if api.add_row(label, ROW_AFTER_ARENA, start_run, row_subtitle()) then
            state.row_label = label
            say(label .. " row added")
        else
            say("ENDLESS row refused")
        end
    else
        api.set_subtitle(state.row_label, row_subtitle() or "") -- the row stays; its second line follows the records
    end
    state.area = 0
    state.info = nil
    state.travelling = false
    state.want_travel = false
    state.gate_open = false
    state.granted = {}
    state.present = nil
    state.lesson_seconds = 0
    state.focus_seen = {}
    state.cast_seen = {}
    state.cast_cool, state.last_health = {}, {}
    state.dead_seen = {}
    state.in_backrooms = false
    state.prebuilt, state.want_backrooms = nil, false
    if state.worker then state.worker, state.building = nil, nil end -- cancelled by the runtime, no callback comes
    state.run, state.after_build = state.run + 1, nil
    state.met = {}
    state.bosses = 0
    if state.boss_timer then timers.cancel(state.boss_timer); state.boss_timer = nil end
    if state.puzzle_timer then timers.cancel(state.puzzle_timer); state.puzzle_timer = nil end
    if state.party_timer then timers.cancel(state.party_timer); state.party_timer = nil end
    api.clear_served()
end)
