-- Drives mods/endless/scripts/main.lua with stubbed runtime globals: menu row, run start,
-- boss death opening the gate, the exit zone + script event pair (either order), travel and
-- arrival placement, fire (operative driven + burn) and push hazards, NPC entries ignored,
-- CONTINUE restoring the area ids, return to the menu. Offline only.
--   lua.exe test_main.lua <mod dir> <template.rfc> <template.ini>
local moddir, rfc, ini = ...
package.path = moddir .. "/scripts/?.lua;" .. package.path
local function read(path) local f = assert(io.open(path, "rb")) local s = f:read("a") f:close() return s end
local calls = {serve = {}, new_game = {}, travel = {}, place = {}, damage = {}, push = {}, rows = {}, drive = {}, cleared = 0}
local handlers = {}
local timerList, timerId = {}, 0
local phase, current = 1, ""
local now = 1000.0
local bossDead = false
local playerHealth = nil -- nil: no readable health (the poll must not fire on that)
local playerFocus = nil  -- focus of the player; a drop from its maximum is a casting
local party = {}         -- extra snapshot rows (companions) the test adds
local bossHealth = nil   -- the boss's health (below its maximum = a fight)
local bossPos = {5000, 0, 5000} -- the boss far from the player unless a test moves it
local bossId = 0
title = {add_row = function(label, after, fn, opts) calls.rows[#calls.rows + 1] = {label, after, fn, opts} return true end, remove_row = function(label) return true end,
    set_subtitle = function(label, text) calls.subtitle = text return true end}
levels = {
    serve = function(name, bytes, package) calls.serve[#calls.serve + 1] = {name, #bytes, package} return true end,
    clear_served = function() calls.cleared = calls.cleared + 1 end,
    new_game = function(name) calls.new_game[#calls.new_game + 1] = name; phase = 3; current = name end,
    travel = function(name) calls.travel[#calls.travel + 1] = name; current = "" end,
    current = function() return current end,
    drive = function(id, st) calls.drive[#calls.drive + 1] = {id, st} return true end,
}
game = {phase = function() return phase end}
-- runtime 0.26.0 shape: nil outside play, loaded = true in play (main.lua derives its phase from it)
world = {level = function() if phase == 1 then return nil end return {name = current, loaded = phase == 3} end}
calls.lever = {}
-- world.read rows: the levers the test sets (record id -> lever_position, as world.levers gives it)
world.snapshot = function()
    local objects = {}
    for id, pos in pairs(calls.lever) do
        objects[#objects + 1] = {item_id = 0x80000000 | id, interaction_kind = "lever", lever_position = pos,
            set_position = function(self, v) assert(v == 0 or v == 1, "set_position takes 0 or 1") calls.lever[id] = v + 0.0 end}
    end
    return {objects = objects}
end
player = {
    place = function(x, y, z) calls.place[#calls.place + 1] = {x, y, z} end,
    damage = function(b, h, f) calls.damage[#calls.damage + 1] = {b, h, f} end,
    push = function(dx, dy, dz, a) calls.push[#calls.push + 1] = {dx, dy, dz, a} end,
}
calls.grant = {}
characters = {
    snapshot = function()
        local rows = {{record_id = bossId, dead = bossDead, is_player = false, health = bossHealth, health_max = 100, position = bossPos},
                      {is_player = true, health = playerHealth, health_max = 100, balance_max = 50, focus = playerFocus, focus_max = 100, position = {0, 0, 0}}}
        for _, r in ipairs(party) do rows[#rows + 1] = r end
        return {characters = rows}
    end,
    grant_powers = function(id, ids) calls.grant[#calls.grant + 1] = {id, #ids} return true end,
}
calls.flags = {}
-- tasks (r25): the task runs under a count hook that yields every 200k instructions; a yield inside a
-- C callback (table.sort comparator, gsub function) errors. The stub runs the task to completion at
-- once but checks the same two things at every 200k step: that no C function is on the stack, and
-- how many pulses the task would have taken.
calls.task_pulses = 0
calls.peak_kb = 0
tasks = {}
-- calls.defer_tasks: a task starts a second later (a timer), so a menu can come while it runs
-- r40: an optional {budget = n} (10k..200k); the stub checks it and slices at it
calls.budgets = {}
function tasks.run(fn, opts)
    local budget = 200000
    if opts ~= nil then
        assert(type(opts) == "table" and math.type(opts.budget) == "integer" and opts.budget >= 10000 and opts.budget <= 200000, "tasks.run budget is an integer 10000..200000")
        budget = opts.budget
    end
    calls.budgets[budget] = (calls.budgets[budget] or 0) + 1
    if calls.defer_tasks then
        timers.after(1.0, function() tasks.run_now(fn, budget) end)
        return true
    end
    return tasks.run_now(fn, budget)
end
tasks.count = function() return 0 end
function tasks.run_now(fn, budget)
        local pulses = 0
        debug.sethook(function()
            pulses = pulses + 1
            local kb = collectgarbage("count")
            if kb > 48 * 1024 then
                -- as Lua's allocator does at a hard cap: a full collection first, then the live size decides
                collectgarbage("collect")
                kb = collectgarbage("count")
                calls.emergency_gc = (calls.emergency_gc or 0) + 1
                if kb > 48 * 1024 then error(string.format("task over the addon's 48 MiB (manifest memory_mb): %.1f MiB live", kb / 1024)) end
            end
            if kb > calls.peak_kb then calls.peak_kb = kb end
            if pulses % 8 == 0 then -- the live size now and then (what the cap really bounds)
                collectgarbage("collect")
                local live = collectgarbage("count")
                if live > (calls.peak_live_kb or 0) then calls.peak_live_kb = live end
            end
            -- only frames between the hook and the task function count (pcall is allowed by the runtime)
            local level = 3
            while true do
                local info = debug.getinfo(level, "Snf")
                if not info or info.func == fn then break end
                if info.what == "C" and info.name and info.name ~= "sethook" and info.name ~= "pcall" then
                    error("task budget boundary inside a C callback (" .. info.name .. "): the runtime cannot yield there")
                end
                level = level + 1
            end
        end, "", budget or 200000)
        local ok, err = pcall(fn)
        debug.sethook()
        assert(ok, err)
        calls.task_pulses = calls.task_pulses + pulses + 1
        return true
end
script_flags = {set = function(name, value) calls.flags[name] = value return true end, get = function(name) return calls.flags[name] or 0 end}
-- runtime 0.28.0-r37 addon messages: recorded (the Light School is not loaded here)
calls.sent = {}
addons = {send = function(target, topic, value) calls.sent[#calls.sent + 1] = {target, topic, value} return true end, on = function() return true end}
assets = {read = function(path) if path:match("dress%.bin$") then return read((rfc:gsub("endless%-template%.rfc$", "endless-dress.bin"))) end if path:match("rft$") then return read(rfc:gsub("%.rfc$", ".rft")) end return read(path:match("rfc$") and rfc or ini) end}
timers = {
    now = function() return now end,
    after = function(s, fn) timerId = timerId + 1; timerList[timerId] = {at = now + s, fn = fn} return timerId end,
    every = function(s, fn) timerId = timerId + 1; timerList[timerId] = {at = now + s, fn = fn, every = s} return timerId end,
    cancel = function(id) timerList[id] = nil end,
}
local store = {}
storage = {get = function(k, d) if store[k] == nil then return d end return store[k] end, set = function(k, v) store[k] = v end}
-- the runtime keeps every handler of an event; so does the stub
events = {on = function(name, fn) assert(type(fn) == "function", "events.on(name, fn): the runtime takes two arguments") handlers[name] = handlers[name] or {}; table.insert(handlers[name], fn) end}
local function fire(name, event)
    -- the runtime cancels worker jobs on the way to the menu (their callbacks never run)
    if name == "runtime.phase" and event.phase == "menu" then calls.jobs = {} end
    for _, fn in ipairs(handlers[name] or {}) do fn(event) end
end
local function tick(seconds)
    local stop = now + seconds
    while true do
        local nextId, nextAt
        for id, t in pairs(timerList) do if not nextAt or t.at < nextAt then nextId, nextAt = id, t.at end end
        if not nextAt or nextAt > stop then break end
        now = nextAt
        local t = timerList[nextId]
        if t.every then t.at = now + t.every else timerList[nextId] = nil end
        t.fn()
    end
    now = stop
end
local function drives(id, st) local n = 0 for _, d in ipairs(calls.drive) do if d[1] == id and d[2] == st then n = n + 1 end end return n end
local failed = 0
local function check(cond, what) if not cond then failed = failed + 1 print("FAIL: " .. what) end end

-- the runtime sandbox: base (without load/dofile/metatables), table, string, math, utf8 and the
-- runtime's own globals; a module that reaches for anything else fails here as it would in the game
local SANDBOX_BASE = {"assert", "error", "ipairs", "pairs", "next", "pcall", "select", "tonumber", "tostring", "type",
    "rawget", "rawset", "rawequal", "rawlen", "print", "string", "table", "math", "utf8", "_VERSION"}
local function sandboxed(path, extra)
    local env = {}
    for _, k in ipairs(SANDBOX_BASE) do env[k] = _G[k] end
    for k, v in pairs(extra or {}) do env[k] = v end
    env._G = env
    local chunk, err = loadfile(path, "t", env)
    assert(chunk, err)
    return chunk()
end
local gen = sandboxed(moddir .. "/scripts/gen.lua")
local tpl = assert(gen.load_template(read(rfc), read(ini)))
assert(gen.load_terrain_template(tpl, read(rfc:gsub("%.rfc$", ".rft"))))
gen.load_dress(tpl, read((rfc:gsub("endless%-template%.rfc$", "endless-dress.bin")))) -- the mod builds with the dressings, so the test does too
calls.log = {}
local function logged_print(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[i] = tostring((select(i, ...))) end
    calls.log[#calls.log + 1] = table.concat(parts, " ")
    print(...)
end
local function said(text) for _, line in ipairs(calls.log) do if line:find(text, 1, true) then return true end end return false end
-- tasks.worker (r41): the addon's module in a sandbox of its own (base, table, string, math, utf8, require of
-- its modules), input and result copied as plain data, the callback a moment later; calls.no_worker turns it off
local function copy(v, depth)
    depth = depth or 0
    assert(depth <= 32, "worker data over 32 deep")
    if type(v) ~= "table" then
        assert(v == nil or type(v) == "boolean" or type(v) == "number" or type(v) == "string", "worker data must be plain: " .. type(v))
        return v
    end
    local out = {}
    for k, x in pairs(v) do out[copy(k, depth + 1)] = copy(x, depth + 1) end
    return out
end
calls.jobs, calls.worker_runs = {}, 0
calls.no_worker = true -- the run below is the tasks.run fallback (older runtimes); the worker has its own block at the end
local next_job = 0
function tasks.worker(module, input, fn)
    if calls.no_worker then return nil end
    assert(module == "build_worker", module)
    next_job = next_job + 1
    local id = next_job
    calls.jobs[id] = true
    local job_input = copy(input)
    timers.after(0.5, function()
        if not calls.jobs[id] then return end -- cancelled at the menu
        calls.jobs[id] = nil
        calls.worker_runs = calls.worker_runs + 1
        local wgen = sandboxed(moddir .. "/scripts/gen.lua")
        local body = sandboxed(moddir .. "/scripts/build_worker.lua", {require = function(name) assert(name == "gen", name) return wgen end})
        local ok, result = pcall(body, job_input)
        if ok then fn(copy(result), nil) else fn(nil, result) end
    end)
    return id
end
sandboxed(moddir .. "/scripts/main.lua", {require = function(name) assert(name == "gen", name) return gen end, print = logged_print,
    events = events, timers = timers, storage = storage, title = title, levels = levels, player = player, assets = assets,
    world = world, characters = characters, script_flags = script_flags, game = game, tasks = tasks, addons = addons})
fire("runtime.phase", {phase = "menu"})
check(#calls.rows == 1 and calls.rows[1][1] == "ENDLESS" and calls.rows[1][2] == 3, "ENDLESS row after ARENA")
calls.rows[1][3]() -- click
check(#calls.serve == 2 and calls.serve[1][1] == "arenao1.rfc" and calls.serve[1][2] > 600000 and calls.serve[2][1] == "arenao1.rft" and calls.serve[2][2] > 1000000 and calls.serve[1][3] == "Resource.rpk", "area 1 served as arenao1 .rfc and .rft from Resource.rpk")
check(#calls.new_game == 1 and calls.new_game[1] == "arenao1", "new game started on the served member")
check(store["endless.area"] == 1 and store["endless.seed"] and store["endless.seed"] > 0, "run stored")
local _, _, info1 = gen.build(tpl, store["endless.seed"], 1)
check(info1.boss > 0 and info1.gate > 0, "area 1 has a boss and a gate")
bossId = info1.boss
-- the boss lives: no gate; the boss dies: the gate is driven once
tick(5.0)
check(drives(info1.gate, 1) == 0, "gate closed while the boss lives")
bossDead = true
tick(5.0)
check(drives(info1.gate, 1) == 1, "gate driven open once after the boss died")
-- an NPC entering the exit zone changes nothing
fire("zone.enter", {zone_id = 0, record_id = 1, name = "EndlessNext", is_player = false})
check(#calls.travel == 0, "NPC in the exit zone ignored")
-- player enters: zone event first, then the script event with area_seed
fire("zone.enter", {zone_id = 0, record_id = 1, name = "EndlessNext", is_player = true})
local value = string.format("%010d_%010d", 1, store["endless.seed"])
fire("script.event", {name = "EndlessNext", value = value, number = 1})
check(#calls.travel == 1 and calls.travel[1] == "arenao2" and calls.serve[3][1] == "arenao2.rfc", "travel to area 2 served as arenao2")
check(#calls.place == 0, "no placement before the level is current")
phase, current = 3, "arenao2"
bossDead = false
local _, _, info2 = gen.build(tpl, store["endless.seed"], 2)
bossId = info2.boss
tick(1.0)
check(#calls.place == 1 and calls.place[1][1] == 8200.0 and calls.place[1][3] == 3920.0, "placed at the start room after arrival")
tick(4.0)
check(drives(info2.gate, 1) == 0, "area 2 gate closed while its boss lives")
bossDead = true
tick(4.0)
check(drives(info2.gate, 1) == 1, "area 2 gate opened after its boss died")
-- script event first, then the zone (CONTINUE case: state restored from the script)
fire("script.event", {name = "EndlessNext", value = string.format("%010d_%010d", 2, store["endless.seed"]), number = 2})
check(#calls.travel == 1, "script event alone does not travel")
fire("zone.enter", {zone_id = 0, record_id = 1, name = "EndlessNext", is_player = true})
check(#calls.travel == 2 and calls.travel[2] == "arenao3", "zone after script travels to area 3")
fire("zone.enter", {zone_id = 0, record_id = 1, name = "EndlessNext", is_player = true})
check(#calls.travel == 2, "no double travel while one is pending")
phase, current = 3, "arenao3"
tick(1.0)
check(#calls.place == 2, "placed again on area 3")
-- hazards: fire slot 1 drives that operative on, burns 3 + depth times, drives it off later
local _, _, info3 = gen.build(tpl, store["endless.seed"], 3)
fire("zone.enter", {zone_id = 11, record_id = 9, name = "Endless Fire Z1", is_player = true})
check(drives(info3.fires[1], 1) == 0, "the plate drives the fire, not the mod")
tick(3.0)
check(#calls.damage == 4, "fire burns 3 + depth times")
fire("zone.enter", {zone_id = 3, record_id = 9, name = "Endless Push W", is_player = true})
check(#calls.push == 1 and calls.push[1][1] == -1 and calls.push[1][4] == 10, "push west with depth-scaled force")
fire("zone.enter", {zone_id = 11, record_id = 9, name = "Endless Fire Z1", is_player = false})
tick(3.0)
check(#calls.damage == 4, "an NPC in fire is not the player")
-- CONTINUE: a fresh mod state learns the area from the script event and watches that boss
fire("runtime.phase", {phase = "menu"})
check(calls.cleared >= 1 and #calls.rows == 1, "served levels cleared, the row added once")
phase, current = 3, "arenao2"
bossDead = false
bossId = info2.boss
fire("script.event", {name = "EndlessNext", value = string.format("%010d_%010d", 2, store["endless.seed"]), number = 2})
local before = drives(info2.gate, 1)
bossDead = true
tick(5.0)
check(drives(info2.gate, 1) == before + 1, "after CONTINUE the restored area's boss opens its gate")
check(#calls.grant == 0, "no grant while health is unreadable or healthy")
local ini_text = read(ini)
local companions = {}
for v in ini_text:match("\ncompanions=([^\n]*)"):gmatch("[^,]+") do companions[#companions + 1] = tonumber(v) end
local tobin, mira = companions[1], companions[3] -- found in this order: Tobin, Aldric, Mira
-- the party: Mira and Tobin walk with the player; presence decides which talk zone the next area gets
party = {{record_id = mira, handle = "h" .. mira, name = "Mira", position = {100, 0, 100}, focus = 100, focus_max = 100},
         {record_id = tobin, handle = "h" .. tobin, name = "Tobin", position = {-100, 0, 100}, focus = 100, focus_max = 100}}
playerHealth = 24
tick(2.0)
check(#calls.grant == 1 and calls.grant[1][1] == mira and calls.grant[1][2] == 5, "the player below a quarter forces Mira's reveal: her five powers granted")
check(store["endless.granted"] == tostring(mira), "the grant is remembered for CONTINUE")
fire("script.event", {name = "EndlessReveal", value = "1", number = 1})
tick(2.0)
check(#calls.grant == 1, "Mira's grant happens once per run")
-- Light School casts: a hit on the party makes Mira (granted) Glare; Tobin (not granted yet) does not
playerHealth = 20
tick(1.0)
local function casts(power, who)
    local k = 0
    for _, m in ipairs(calls.sent) do
        if m[1] == "com.necrosis.light-orb" and m[2] == "light.cast" and m[3].power == power
            and (m[3].caster == who or (type(m[3].caster) == "table" and m[3].caster.handle == "h" .. who)) then k = k + 1 end
    end
    return k
end
check(casts("glare", mira) == 1 and casts("glare", tobin) == 0, "a hit on the party: Mira, granted, sends her Glare by handle; Tobin, not yet granted, does not")
playerHealth = 18
tick(1.0)
check(casts("glare", mira) == 1, "no second Glare inside its cooldown")
-- first castings: the player's focus drops; the first present observer (Aldric absent: Mira) gets the flag
playerFocus = 100
tick(1.0)
playerFocus = 60
tick(1.0)
check(calls.flags["endless_saw_you_2"] == 1 and calls.flags["endless_saw_you_1"] == nil, "the player's first casting flags Mira, the first present observer (Aldric absent)")
party[1].focus = 50
tick(1.0)
check(calls.flags["endless_saw_mira_0"] == 1, "Mira's first casting after her reveal flags Tobin, the only other present")
-- Tobin: twenty minutes with Mira, then a boss fight (a living boss, unhurt first)
bossDead = false
bossHealth = 100
tick(1300.0)
check(#calls.grant == 1, "time with Mira alone grants nothing")
bossHealth = 90
tick(2.0)
check(#calls.grant == 2 and calls.grant[2][1] == tobin and calls.grant[2][2] == 3, "the boss hurt after the lessons: Tobin's three powers granted")
check(calls.flags["endless_spark_0"] == nil, "no Spark before Tobin's grant")
party[2].focus = 40
tick(1.0)
check(calls.flags["endless_spark_0"] == 1, "Tobin's first casting sets his Spark flag")
check(calls.flags["endless_depth"] == 1 and calls.flags["endless_stage"] == 1, "the served area's depth and stage are published for the dialogue")
-- Tobin dies; Aldric is absent, so Mira gets the reaction and Tobin's lines are gated off
party[2].dead = true
tick(2.0)
check(calls.flags["endless_dead_0"] == 1 and calls.flags["endless_dead_tobin_2"] == 1 and calls.flags["endless_dead_tobin_1"] == nil, "Tobin's death flags him dead and gives Mira, the first present survivor, the reaction")
-- the next area's talk zones go to the first present speaker: Aldric is absent, so the gate zone is Mira's
local snapNow = characters.snapshot()
do
    local present = {}
    for _, row in ipairs(snapNow.characters) do
        for i, cid in ipairs(companions) do if row.record_id == cid then present[i - 1] = true end end
    end
    local withParty = gen.build(tpl, store["endless.seed"], 2, present)
    local alone = gen.build(tpl, store["endless.seed"], 2, {})
    local everyone = gen.build(tpl, store["endless.seed"], 2, nil)
    check(withParty ~= alone and alone == everyone, "the party's presence picks the talk zones; nobody present falls back to the designed first speaker")
end
check(store["endless.met"] == "0,2", "the companions seen this run are remembered (Tobin and Mira, not Aldric)")
do
    local met = {[0] = true, [2] = true}
    local again = gen.build(tpl, store["endless.seed"], 2, nil, met)      -- area 2: depth 1's companion is Tobin, already met -> Aldric instead
    local first = gen.build(tpl, store["endless.seed"], 2, nil, {})
    local none = gen.build(tpl, store["endless.seed"], 2, nil, {[0] = true, [1] = true, [2] = true})
    check(again ~= first and none ~= first and none ~= again, "a met companion is not found again; after all three nobody is found")
end
-- the backrooms (easter egg 4): the corner of the perfect copy sends you to a plain level of this area,
-- and its way out brings you back to this area, not the next one
do
    local area_now, travels = 2, #calls.travel
    phase, current = 3, "arenao2"
    fire("zone.enter", {zone_id = 40, record_id = 1384, name = "Endless Wall", is_player = true})
    tick(3.0)
    local back = gen.floor_name(area_now + 7)
    check(#calls.travel == travels + 1 and calls.travel[#calls.travel] == back, "the wall corner travels to the backrooms " .. back .. " (got " .. tostring(calls.travel[#calls.travel]) .. ")")
    fire("zone.enter", {zone_id = 40, record_id = 1384, name = "Endless Wall", is_player = true})
    check(#calls.travel == travels + 1, "no second backrooms trip while one is under way")
    phase, current = 3, back
    tick(1.0)
    fire("zone.enter", {zone_id = 0, record_id = 1, name = "EndlessNext", is_player = true})
    check(#calls.travel == travels + 2 and calls.travel[#calls.travel] == "arenao2", "the backrooms' way out returns to area 2, not area 3 (got " .. tostring(calls.travel[#calls.travel]) .. ")")
    phase, current = 3, "arenao2"
    tick(1.0)
end
do
    local aldric = 0
    for _, m in ipairs(calls.sent) do if m[3].caster == companions[2] or (type(m[3].caster) == "table" and m[3].caster.handle == "h" .. companions[2]) then aldric = aldric + 1 end end
    check(aldric == 0 and #calls.sent >= 2, "Aldric never casts (sent " .. #calls.sent .. ")")
end
fire("runtime.phase", {phase = "menu"})
check(store["endless.last"] == "1,2,1,1", "the run summary is stored at the menu: depth 1, area 2, 1 boss, 1 companion lost (got " .. tostring(store["endless.last"]) .. ")")
check(calls.rows[#calls.rows][1] == "ENDLESS", "the title row stays plain ENDLESS (got " .. calls.rows[#calls.rows][1] .. ")")
check(calls.subtitle == "Deepest: depth 1    Last descent: depth 1", "the subtitle carries the records (got " .. tostring(calls.subtitle) .. ")")
playerHealth = 10
tick(3.0)
check(#calls.grant == 2, "the menu stops the party poll")
-- the boss pen: raised on arrival, a lever pull with the boss inside opens the exit gate
do
    local seed_pen, area_pen, info_pen
    for sd = 1, 60 do
        local _, _, inf = gen.build(tpl, sd, 2)
        if inf.pen_gate then seed_pen, area_pen, info_pen = sd, 2, inf break end
    end
    check(info_pen ~= nil, "a pen area exists among the first 60 seeds")
    if info_pen then
        fire("runtime.phase", {phase = "menu"})
        store["endless.seed"] = seed_pen
        phase, current = 3, gen.floor_name(area_pen)
        bossDead, bossId = false, info_pen.boss
        local box = info_pen.pen_box
        bossPos = {(box[1] + box[3]) / 2, 0, (box[2] + box[4]) / 2}
        calls.lever = {[info_pen.pen_lever] = 0.0}
        local gate_before, pen_before = drives(info_pen.gate, 1), drives(info_pen.pen_gate, 1)
        fire("script.event", {name = "EndlessNext", value = string.format("%010d_%010d", area_pen, seed_pen), number = area_pen})
        tick(5.0)
        check(drives(info_pen.pen_gate, 1) > pen_before, "the pen's portcullis is raised on arrival")
        check(drives(info_pen.gate, 1) == gate_before, "the exit gate stays shut while the boss is free")
        calls.lever[info_pen.pen_lever] = 1.0
        tick(3.0)
        check(drives(info_pen.gate, 1) == gate_before + 1 and calls.flags["endless_boss_caged"] == 1, "the lever pulled with the boss in the pen opens the exit gate")
        bossPos = {5000, 0, 5000}
    end
end
-- the boss-lock puzzles (Hunter 2026-10-22): plate/hold, lever order, timed gate with its failsafe
do
    local found = {}
    for area = 2, 40 do
        local kind = gen.puzzle_kind(area)
        if kind ~= "key" and kind ~= "lever" and not found[kind] then
            local _, _, inf = gen.build(tpl, 7, area)
            if inf.puzzle == kind then found[kind] = {area, inf} end
        end
    end
    for _, kind in ipairs({"plate", "hold", "order", "timed"}) do check(found[kind] ~= nil, "a " .. kind .. " area exists among areas 2-40") end
    local function arrive(entry)
        fire("runtime.phase", {phase = "menu"})
        store["endless.seed"] = 7
        phase, current = 3, gen.floor_name(entry[1])
        bossDead, bossId, bossPos = false, entry[2].boss, {5000, 0, 5000}
        fire("script.event", {name = "EndlessNext", value = string.format("%010d_%010d", entry[1], 7), number = entry[1]})
        tick(3.0)
        return entry[2]
    end
    for _, kind in ipairs({"plate", "hold"}) do
        if found[kind] then
            local inf = arrive(found[kind])
            local g = inf.puzzle_gate
            local up = drives(g, 1)
            check(drives(g, 1) == up, kind .. ": the gate stays shut with the plate empty")
            party = {{record_id = 9001, is_player = false, dead = false, health = 50, health_max = 50, position = {inf.puzzle_plate[1] + 20, 0, inf.puzzle_plate[2]}}}
            tick(1.0)
            check(drives(g, 1) == up + 1, kind .. ": a companion on the plate raises the gate")
            local down = drives(g, 0)
            party[1].position = {inf.puzzle_plate[1] + 400, 0, inf.puzzle_plate[2]}
            tick(1.0)
            check(drives(g, 0) == down + 1, kind .. ": the gate falls when the plate is left")
            party = {}
        end
    end
    if found.order then
        local inf = found.order[2]
        local L = inf.puzzle_levers
        calls.lever = {[L[1]] = 0.0, [L[2]] = 0.0, [L[3]] = 0.0}
        arrive(found.order)
        local g, up = inf.puzzle_gate, drives(inf.puzzle_gate, 1)
        calls.lever[L[1]] = 1.0; tick(1.0)
        calls.lever[L[3]] = 1.0; tick(1.0)
        check(calls.lever[L[1]] == 0.0 and calls.lever[L[3]] == 0.0 and drives(g, 1) == up, "order: a wrong pull springs the levers back, gate shut")
        tick(3.0)
        for i = 1, 3 do calls.lever[L[i]] = 1.0; tick(1.0) end
        check(drives(g, 1) == up + 1 and calls.flags["endless_puzzle_solved"] == 1, "order: the three in order raise the gate")
        calls.flags["endless_puzzle_solved"] = nil
    end
    if found.timed then
        local inf = found.timed[2]
        local L = inf.puzzle_levers
        calls.lever = {[L[1]] = 0.0, [L[2]] = 0.0}
        arrive(found.timed)
        local g, up, down = inf.puzzle_gate, drives(inf.puzzle_gate, 1), drives(inf.puzzle_gate, 0)
        calls.lever[L[1]] = 1.0; tick(1.0)
        check(drives(g, 1) == up + 1, "timed: the near lever raises the gate")
        tick(inf.puzzle_seconds + 1.0)
        check(drives(g, 0) == down + 1 and said("(1 missed)"), "timed: the gate falls when the player is not through in time")
        calls.lever[L[1]] = 0.0; tick(1.0)
        check(drives(g, 1) == up + 2 and said(string.format("%.0f s", inf.puzzle_seconds * 1.5)), "timed: the next try is longer")
        calls.lever[L[2]] = 1.0; tick(1.0)
        check(drives(g, 1) == up + 3 and said("the inside lever holds the gate up"), "timed: the failsafe lever inside holds it up")
        tick(inf.puzzle_seconds * 2)
        check(drives(g, 0) == down + 1, "timed: after the failsafe the gate does not fall")
    end
    calls.lever = {}
    fire("runtime.phase", {phase = "menu"})
end
-- the menu while a build runs (a task cannot be stopped): it ends and is dropped, then the CONTINUE
-- restore runs; never two builds at once (the 48 MiB guard in run_task would fail this test)
do
    local value = string.format("%010d_%010d", 2, store["endless.seed"])
    phase, current = 3, "arenao2"
    fire("runtime.phase", {phase = "menu"})
    calls.defer_tasks = true
    fire("script.event", {name = "EndlessNext", value = value, number = 2}) -- a CONTINUE: area 2 builds
    fire("runtime.phase", {phase = "menu"})                                 -- the menu at once
    fire("script.event", {name = "EndlessNext", value = value, number = 2}) -- CONTINUE again while it runs
    tick(60.0)
    check(said("a build from before the menu ended; dropped"), "the build from before the menu is dropped when it ends")
    local restored = 0
    for _, line in ipairs(calls.log) do if line:find("run restored from the level: area 2", 1, true) then restored = restored + 1 end end
    check(restored >= 1, "the CONTINUE restore runs after it")
    calls.defer_tasks = false
end
check((calls.budgets[50000] or 0) >= 2 and (calls.budgets[200000] or 0) >= 1, "builds ahead run at 50k a pulse, builds the player waits on at the default")
-- Hunter's vanilla-lookalike run (2026-10-22): ENDLESS pressed while a build from before the menu still
-- runs; the game goes on to the character screen; the old build stops, then the new run still gets its level
do
    local value = string.format("%010d_%010d", 2, store["endless.seed"])
    fire("runtime.phase", {phase = "menu"})
    calls.defer_tasks = true
    phase, current = 3, "arenao2"
    fire("script.event", {name = "EndlessNext", value = value, number = 2}) -- a build starts (deferred)
    fire("runtime.phase", {phase = "menu"})
    phase = 1
    local before = #calls.new_game
    calls.rows[#calls.rows][3]() -- ENDLESS pressed on the title while that build runs
    phase = 2                    -- the game goes on to the character screen
    tick(10.0)
    check(#calls.new_game == before + 1 and calls.new_game[#calls.new_game] == "arenao1", "the run pressed during an old build still starts in its own level, not the story's first")
    calls.defer_tasks = false
    fire("runtime.phase", {phase = "menu"})
end
-- the worker (r41): a run, its build ahead and its exit all built off the game's frames; the menu cancels
-- a job without a callback, and a run pressed at once still starts in its own level
do
    calls.no_worker = false
    fire("runtime.phase", {phase = "menu"})
    phase = 1
    local before_new, before_runs = #calls.new_game, calls.worker_runs
    calls.rows[#calls.rows][3]()
    check(#calls.new_game == before_new, "on the worker the level is not ready at once")
    phase = 2
    tick(1.0)
    check(#calls.new_game == before_new + 1 and calls.new_game[#calls.new_game] == "arenao1", "the worker's area 1 starts the new game in its level")
    local served = calls.serve[#calls.serve]
    check(served[1] == "arenao1.rft" and served[2] > 1000000, "the worker's terrain is served with its level")
    phase, current = 3, "arenao1"
    tick(8.0) -- arrival, then the build ahead after its delay
    check(said("area 2 built ahead"), "the build ahead runs on the worker")
    local seed = store["endless.seed"]
    fire("zone.enter", {zone_id = 0, record_id = 1, name = "EndlessNext", is_player = true})
    check(calls.travel[#calls.travel] == "arenao2", "the exit uses the area built ahead at once")
    check(calls.worker_runs - before_runs >= 2, "builds ran on the worker (" .. (calls.worker_runs - before_runs) .. " jobs)")
    -- the menu while a worker job runs
    phase, current = 3, "arenao2"
    tick(1.0)
    fire("runtime.phase", {phase = "menu"})
    fire("script.event", {name = "EndlessNext", value = string.format("%010d_%010d", 2, seed), number = 2}) -- CONTINUE: a job starts
    fire("runtime.phase", {phase = "menu"})                                                                -- cancelled on the way
    phase = 1
    local before = #calls.new_game
    calls.rows[#calls.rows][3]()
    phase = 2
    tick(2.0)
    check(#calls.new_game == before + 1, "after the menu cancels a worker build, a run pressed at once starts in its level")
    fire("runtime.phase", {phase = "menu"})
end
print(string.format("build task pulses in this run: %d, peak Lua memory seen at a budget step: %.1f MiB, full collections forced by the cap: %d, peak live (sampled): %.1f MiB (the addon has 48, memory_mb)", calls.task_pulses, calls.peak_kb / 1024, calls.emergency_gc or 0, (calls.peak_live_kb or 0) / 1024))
print(failed == 0 and "PASS" or ("FAIL (" .. failed .. ")"))
os.exit(failed == 0 and 0 or 1)
