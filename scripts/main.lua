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
    add_row = function(label, after, fn) return title.add_row(label, after, fn, {acts_as = 1}) end,
    remove_row = function(label) return title.remove_row and title.remove_row(label) end,
    serve = function(member, bytes) return levels.serve(member, bytes, PACKAGE) end,
    clear_served = function() return levels.clear_served() end,
    new_game = function(member) return levels.new_game(member) end,
    travel = function(member) return levels.travel(member) end,
    current_level = function() local l = world.level and world.level() return l and l.name end,
    drive = function(record_id, on) if levels.drive then return levels.drive(record_id, on and 1 or 0) end end,
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
    snapshot = function() if characters and characters.snapshot then return characters.snapshot() end end,
    -- 0.28.0: a live NPC learns 1..10 Force/Energy/Displacement powers (the companions' hidden talents)
    grant_powers = function(record_id, ids) if characters and characters.grant_powers then return characters.grant_powers(record_id, ids) end end,
    -- LuaFlag(name) in a dialogue condition reads this; a reaction node opens on its companion's flag
    set_flag = function(name, value) if script_flags and script_flags.set then return script_flags.set(name, value) end end,
    log = function(text) if log and log.info then log.info(text) else print(text) end end,
}

local state = {
    template = nil,        -- gen template, loaded once
    seed = 0,              -- run seed (u32)
    area = 0,              -- area being played (0 = no run)
    info = nil,            -- {boss, gate, gate_lever, fires, companion} record ids of the current area
    travelling = false,    -- a travel was requested and the arrival placement is pending
    want_travel = false,   -- the player entered the exit zone
    gate_open = false,     -- the boss died and the gate was driven
    row_label = nil,       -- the title row's label while it is on the menu (it carries the deepest depth)
    granted = {},          -- companion record id -> true once its powers were granted this run
    present = nil,         -- set of companion indices (0-based, as the generator counts) in the party
    lesson_seconds = 0,    -- time Tobin has spent with Mira after her reveal
    focus_seen = {},       -- row key -> true once a readable focus was seen (the first casting is a drop from it)
    cast_seen = {},        -- row key -> true once that character's first casting was reacted to
    party_timer = nil,     -- the party poll
    place_timer = nil,
    burn_timer = nil,
    boss_timer = nil,
}

local function say(text) api.log("Endless: " .. text) end

-- the title row shows the deepest depth any run reached, so the menu itself is the scoreboard
local function row_label()
    local best = tonumber(storage.get("endless.best_depth", 0)) or 0
    return best > 0 and string.format("ENDLESS  (DEPTH %d)", best) or "ENDLESS"
end
local function template()
    if state.template then return state.template end
    local rfc, ini, rft = api.read_asset("assets/endless-template.rfc"), api.read_asset("assets/endless-template.ini"), api.read_asset("assets/endless-template.rft")
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
local function area_info(area)
    local t = template()
    if not t then return nil end
    local _, _, info = gen.build(t, state.seed, area, state.present)
    return info
end

local function serve_area(area)
    local t = template()
    if not t then return nil end
    local bytes, _, info, terrain = gen.build(t, state.seed, area, state.present)
    local name = gen.floor_name(area)
    -- the terrain too: these level names carry an arena terrain that would show under the dungeon
    if not api.serve(name .. ".rfc", bytes) or not api.serve(name .. ".rft", terrain) then say("serve refused for " .. name) return nil end
    state.info = info
    state.gate_open = false
    note_depth(area)
    say(string.format("area %d (depth %d) served as %s: level %d bytes, terrain %d bytes, boss %d, gate %d, companion %d",
        area, gen.depth_of(area), name, #bytes, #terrain, info.boss, info.gate, info.companion or 0))
    return name
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

-- Tobin's talent wakes in a boss fight after enough time with Mira (both present, after her reveal)
local function watch_tobin(snap)
    if state.granted[companion_record(TOBIN)] or not state.granted[companion_record(MIRA)] then return end
    if not (state.present and state.present[MIRA - 1] and state.present[TOBIN - 1]) then return end
    state.lesson_seconds = state.lesson_seconds + PARTY_POLL_SECONDS
    if state.lesson_seconds < LESSON_SECONDS then return end
    local info = state.info
    if not info or info.boss == 0 then return end
    local player, boss
    for _, row in ipairs(snap.characters) do
        if row.is_player then player = row elseif row.record_id == info.boss and not row.dead then boss = row end
    end
    if not boss then return end
    local fighting = boss.health and boss.health_max and boss.health < boss.health_max
    if not fighting and player and player.position and boss.position then
        local dx, dz = boss.position[1] - player.position[1], boss.position[3] - player.position[3]
        fighting = dx * dx + dz * dz <= BOSS_FIGHT_RANGE_CM * BOSS_FIGHT_RANGE_CM
    end
    if fighting then reveal(TOBIN, "boss fight, after " .. math.floor(state.lesson_seconds) .. " s with Mira") end
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
    end)
end

-- the gate opens once the boss is dead; the check repeats until the drive is accepted
local function watch_boss()
    if state.boss_timer then timers.cancel(state.boss_timer) end
    state.boss_timer = timers.every(BOSS_POLL_SECONDS, function()
        local info = state.info
        if not info or info.boss == 0 or state.gate_open or api.phase() ~= PHASE_PLAY then return end
        local snap = api.snapshot()
        if not snap then return end
        for _, row in ipairs(snap.characters) do
            if row.record_id == info.boss and row.dead then
                if api.drive(info.gate, true) then
                    state.gate_open = true
                    say(string.format("boss %d dead, gate %d driven open", info.boss, info.gate))
                    timers.cancel(state.boss_timer)
                    state.boss_timer = nil
                end
                return
            end
        end
    end)
end

-- ENDLESS on the title menu: a new story character on area 1
local function start_run()
    if api.phase() ~= PHASE_TITLE then return end
    state.seed = (math.floor(timers.now() * 1000) % SEED_MODULUS) ~ SEED_SALT
    if state.seed == 0 then state.seed = 1 end
    state.area = 1
    state.travelling = false
    state.want_travel = false
    local name = serve_area(1)
    if not name then return end
    storage.set("endless.seed", state.seed)
    storage.set("endless.area", 1)
    storage.set("endless.granted", "")
    api.new_game(name)
    watch_boss()
    watch_party()
    say("run started, seed " .. state.seed)
end

-- after a travel the game puts the player on the default transform; move them to the start room
local function arm_placement(name)
    if state.place_timer then timers.cancel(state.place_timer) end
    local waited = 0
    state.place_timer = timers.every(PLACE_POLL_SECONDS, function()
        waited = waited + PLACE_POLL_SECONDS
        if api.phase() == PHASE_PLAY and api.current_level() == name then
            api.place(gen.START_X, PLACE_Y, gen.START_Z)
            state.travelling = false
            timers.cancel(state.place_timer)
            state.place_timer = nil
            say("arrived in " .. name .. ", placed at the start room")
            watch_boss()
        elseif waited > PLACE_GIVE_UP_SECONDS then
            state.travelling = false
            timers.cancel(state.place_timer)
            state.place_timer = nil
            say("travel to " .. name .. " never landed")
        end
    end)
end

local function next_area()
    if state.travelling or state.area == 0 then return end
    local area = state.area + 1
    local name = serve_area(area)
    if not name then return end
    state.area = area
    state.travelling = true
    state.want_travel = false
    storage.set("endless.area", area)
    api.travel(name)
    arm_placement(name)
    say("travelling to area " .. area)
end

-- a companion's trust reveal (a dialogue action raises it): grant the powers the record was built without
events.on("script.event", "endless_reveal", function(event)
    if event.name ~= "EndlessReveal" then return end
    reveal(MIRA, event.value) -- she tells you (1), is betrayed (2) or sees death near (3); the grant happens once
end)

-- the exit zone script carries "area_seed" so CONTINUE from a save restores the run
events.on("script.event", "endless_next", function(event)
    if event.name ~= "EndlessNext" then return end
    local area, seed = tostring(event.value):match("^(%d+)_(%d+)$")
    if not area then return end
    state.area, state.seed = tonumber(area), tonumber(seed)
    if not state.info then
        state.info = area_info(state.area)
        say(string.format("run restored from the level: area %d, seed %d", state.area, state.seed))
        watch_boss()
        watch_party()
        regrant()
    end
    if state.want_travel then next_area() end
end)

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

events.on("zone.enter", "endless_zones", function(event)
    if not event.is_player then return end -- an NPC in a zone must not end the area or burn the player
    if event.name == "EndlessNext" then
        say("player entered the exit zone")
        state.want_travel = true
        if state.area > 0 then next_area() end
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

events.on("runtime.phase", "endless_phase", function(event)
    if event.phase ~= "menu" then return end
    local label = row_label()
    if state.row_label and state.row_label ~= label and api.remove_row(state.row_label) then state.row_label = nil end
    if not state.row_label then
        if api.add_row(label, ROW_AFTER_ARENA, start_run) then
            state.row_label = label
            say(label .. " row added")
        else
            say("ENDLESS row refused")
        end
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
    if state.boss_timer then timers.cancel(state.boss_timer); state.boss_timer = nil end
    if state.party_timer then timers.cancel(state.party_timer); state.party_timer = nil end
    api.clear_served()
end)
