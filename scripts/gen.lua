-- Endless mode: area generator (Lua port of generator/endless_gen.py,
-- the reference; see its header for the grid, door and key evidence). Pure Lua 5.4:
-- no game access. gen.build(template, seed, area) returns the level bytes the runtime
-- serves under gen.floor_name(area). Keep in step with the reference: the golden test
-- (tests/test_gen.lua) compares bytes for fixed (seed, area) pairs.
local gen = {}

local spack, sunpack = string.pack, string.unpack
local floor = math.floor

local CELL = 600.0
local SIDE_DX = {[0] = 0, -1, 0, 1} -- q: N, W, S, E
local SIDE_DZ = {[0] = -1, 0, 1, 0}
local SIDE_YAW = {[0] = 0.0, -90.0, -180.0, 90.0}
local WALL, DOOR, BUILT, ROCK = 7, 0xB, 0x80000, 0xFFFF
local ROUTE_MARGIN = 8 -- cells beyond the two ends a corridor search may use
-- cell dressings: whole cells of the game's own levels by wall pattern (bit q = wall on side q)
local DRESS_CLASSES = {0, 1, 3, 5, 7}
local DRESS_ROOM_CHANCE, DRESS_COLLAPSED_CHANCE, DRESS_CORRIDOR_CHANCE = 100, 100, 90 -- endless_gen (2026-10-22 density)
local DRESS_FULL_CELLS, DRESS_MIN_CHANCE, OBJECT_CAP = 1400, 50, 5200 -- frame budget (the Python reference's)
-- rooms that tell a story: whole rooms of the stage's own levels by tag (the Python reference's DRESS_TAGS)
local PURPOSE_TAG = {store = 1, barracks = 2, kitchen = 3, latrine = 4, workshop = 5, shrine = 6, gaol = 7, surgery = 8}
local TAG_PURPOSE = {}
for purpose, tag in pairs(PURPOSE_TAG) do TAG_PURPOSE[tag] = purpose end
local SEAT_JITTER = 15.0
-- rooms and their neighbours (the Python reference's arrange_neighbours)
local NEIGHBOUR_GAP, SMALL_MAX, BIG_MIN, NEIGHBOUR_PASSES = 4, 16, 6, 2
local ITEM_CAP, SIZE_FACTOR = 200, 2 -- loose table items per area; source rooms within this size factor
-- easter eggs (the Python reference's list): remains, the carving, a perfect copy, blue lamps, the chair
local REMAINS, CARVING = "skelbase_physics", "carving stla a1"
local ELARA_CHANCE, COPY_CHANCE, BLUE_DEPTH, CHAIR_DEPTHS = 15, 4, 13, 50
local BLUE_LIGHT = {0.18, 0.32, 0.7}
-- the backrooms (the Python reference's build_backrooms)
local BACK_LIGHT, BACK_STRENGTH, BACK_GRID = {0.62, 0.56, 0.3}, 0.6, 64
-- its furniture (endless_gen.BACK_ROWS and backrooms_props)
local BACK_ROWS, BACK_BEDS, BACK_CENTRE, BACK_TWIN = 12, 20, 32, 50
local BACK_PROPS = {"chair a", "table_m_re a", "bed b01", "coffin01", "bucket wod a01", "stool a"}
local BACK_CENTRE_PROPS = {"chair a", "coffin01", "bucket wod a01", "stool a"}
local BED_ON_END = {0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0}
local BED_HALF = 111.0
local SHRINE_APART = {kitchen = true, barracks = true, latrine = true, workshop = true, store = true}
local SMALL_PURPOSES = {latrine = true, gaol = true, store = true}
local BIG_PURPOSES = {kitchen = true, barracks = true, shrine = true}
local function rot_mask(m, k) if k == 0 then return m end return ((m << k) | (m >> (4 - k))) & 15 end
local MAX_ROOMS = 60 -- ordinary rooms an area may try for
local GRID_BY_DEPTH, GRID_MAX = {[1] = 56, [2] = 60}, 64 -- bigger areas growing with depth (64: the game's largest grid)
local BLOCKERS = {["barricade d"] = true, ["barricade b"] = true, ["barricade c"] = true}
local BLOCK_FILL = {["cratel4"] = true, ["barrel wdo1 a02"] = true, ["cratesmall a"] = true, ["sack a"] = true}
local MAX_BLOCKED = 4
local BORDER_TOP, BORDER_LEFT, BORDER_RIGHT, BORDER_BOTTOM = 0x20010007, 0x120070, 0x12007000, 0x1200700 -- the shipped grids' border ring
local MAGIC = 0x3D23AFCF
local TAG_GRID, TAG_NODES, TAG_OBJECTS, TAG_ITEMS, TAG_PEOPLE, TAG_ENV = 0x3DED, 0x3D000000, 0x3DE10000, 0xDBC0, 0xCAC00001, 0xEC00DC00
local TAG_SPAWN, TAG_ITEM_DB, TAG_ITEM_STRINGS, TAG_ITEM_PLACES, TAG_PEOPLE_DB, TAG_LIGHT = 0xCAC0CA00, 0xDBDB, 0xDBCD, 0xDBCE, 0xCECDDB00, 0x3D06
local START_X, START_Z = 8200.0, 3920.0 -- the game's new-game spawn (2B7684, static)
local LIGHT_Y = 300.0
-- (the grid size is per depth: GRID_BY_DEPTH / GRID_MAX below)
local AREAS_PER_DEPTH, MAX_DEPTH_MAZE = 3, 5
local CORRIDOR = 10000
-- only the arena names that have their own .rft: the game loads <name>.rft with the level and the
-- mod serves both members, so the arena's real terrain never shows under a generated area
local POOL = {"arenao1", "arenao2", "arenao3", "arenao4", "arenao5", "arena7"}

gen.AREAS_PER_DEPTH = AREAS_PER_DEPTH
gen.START_X, gen.START_Z = START_X, START_Z

function gen.floor_name(area) return POOL[(area - 1) % #POOL + 1] end
function gen.depth_of(area) return (area - 1) // AREAS_PER_DEPTH + 1 end
function gen.is_staircase(area) return area % AREAS_PER_DEPTH == 0 end
-- the boss lock (endless_gen.puzzle_kind, PUZZLES)
local PUZZLES = {"key", "lever", "plate", "order", "timed", "hold"}
local PLATE_DIST, HOLD_DIST, TIMED_DIST = {3, 5}, {1, 2}, {4, 7}
local TIMED_BASE, TIMED_PER_CELL = 5.0, 1.6
local HEAVY = {"barrel wdo1 a02", "cratel4", "barrel wdo1 a01", "cratesmall a"}
local CLUE = {["bottle_wkr b"] = true, ["pot"] = true}
function gen.puzzle_kind(area)
    local depth = gen.depth_of(area)
    if depth <= 1 then return "key" end
    if depth == 2 then return ({"key", "plate", "hold"})[(area - 1) % AREAS_PER_DEPTH + 1] end
    return PUZZLES[(area * 5 + depth) % #PUZZLES + 1]
end
function gen.is_lever_area(area) return gen.puzzle_kind(area) == "lever" end
-- two-key areas: from depth 4, on key (not lever) areas, the boss key sits in a locked room whose own key lies elsewhere
function gen.is_vault_area(area) return gen.depth_of(area) >= 4 and gen.puzzle_kind(area) == "key" end
function gen.fire_trap_count(area) local n = gen.depth_of(area) - 1 if n < 0 then n = 0 end return n < 5 and n or 5 end
function gen.push_trap_count(area) local n = gen.depth_of(area) - 2 if n < 0 then n = 0 end return n < 4 and n or 4 end
local LEVER_Y = 145.0
local BANDS = 3 -- strength bands beyond the shipped records (make_template.py writes them)
-- wall-mounted props: distance from the wall (cell fraction), height, yaw relative to the wall's side
local WALL_PROPS = {["hook mtl a01"] = {0.13, 191.0, 0.0}, ["chain_wall"] = {0.12, 210.0, 0.0}, ["uw1_shelf a"] = {0.08, 122.0, -89.0},
    ["shelf_wm b"] = {0.16, 160.0, 0.0}, ["lightglobebr a"] = {0.13, 216.0, 0.0}, ["torch holder a1"] = {0.31, 175.0, 0.0},
    ["support wall a1"] = {0.12, 203.0, 0.0}, ["hooks"] = {0.13, 177.0, 0.0}, ["hook2"] = {0.13, 177.0, 0.0}}
local DEBRIS = {["skelbase_physics"] = 14.0, ["planksn"] = 7.0, ["stoneloose a12"] = 9.0, ["bottle_wkr b"] = 34.0, ["pot"] = 22.0, ["decal9"] = 0.0, ["decal12"] = 0.0}
local ENEMY_CAP, BOSS_CAP, MINION_CAP = 40, 3, 6
function gen.enemy_count(area) -- +3 per depth, +2 per area inside a depth, capped (depth 11 on)
    local d = gen.depth_of(area)
    local n = 4 + 3 * d + 2 * ((area - 1) % AREAS_PER_DEPTH)
    return n < ENEMY_CAP and n or ENEMY_CAP
end
function gen.boss_minion_count(area) local n = gen.depth_of(area) - 1 if n < 0 then n = 0 end return n < MINION_CAP and n or MINION_CAP end
function gen.boss_count(area) local n = 1 + gen.depth_of(area) // 6 return n < BOSS_CAP and n or BOSS_CAP end

-- room purposes: props, enemies, chests and salves by what an ordinary room is for
local PURPOSE_PROPS = {
    store = {["barrel wdo1 a02"] = true, ["cratesmall a"] = true, ["cratesmall b"] = true, ["sack a"] = true, ["cratel4"] = true, ["basket_wkr e"] = true},
    barracks = {["stool a"] = true, ["chair a"] = true, ["bucket wod a01"] = true, ["pot9"] = true},
    shrine = {["coffin01"] = true, ["pot9"] = true},
    quiet = {["stool a"] = true, ["chair a"] = true, ["bucket wod a01"] = true},
    gaol = {["cage_human a"] = true, ["bucket wod a01"] = true, ["stool a"] = true},
    surgery = {["bathtub mtod a01"] = true, ["stretcher"] = true, ["sawtwohand"] = true, ["table_m_re a"] = true},
    kitchen = {["cookpot a"] = true, ["table_m_re a"] = true, ["bench b01"] = true, ["barrel wdo1 a02"] = true},
    plain = {["barrel wdo1 a02"] = true, ["cratesmall a"] = true, ["cratesmall b"] = true, ["sack a"] = true, ["stool a"] = true, ["chair a"] = true,
             ["bucket wod a01"] = true, ["cratel4"] = true, ["coffin01"] = true, ["pot9"] = true, ["basket_wkr e"] = true},
}
local PROP_COUNT_SCALE = {store = 2, gaol = 2}
local HOME_WEIGHT = {barracks = 3, gaol = 2}
local CHEST_CHANCE = {store = 90, quiet = 100, shrine = 60, gaol = 30, surgery = 50, kitchen = 60}
-- area archetypes and mutators (the same tables as the Python reference)
local ARCHETYPES = {
    warren = {rooms = 16, size = {3, 7}, hall = 25, hall_size = {5, 8}, loops = 5, style = 30, big = false, spurs = 2, gap = {1, 3}},
    crypt = {rooms = 22, size = {2, 4}, hall = 0, hall_size = {5, 7}, loops = 2, style = 20, big = false, spurs = 3, gap = {1, 2}},
    cistern = {rooms = 12, size = {3, 6}, hall = 10, hall_size = {5, 8}, loops = 5, style = 40, big = true, spurs = 2, gap = {1, 3}},
    mine = {rooms = 8, size = {2, 4}, hall = 0, hall_size = {5, 7}, loops = 1, style = 10, big = false, spurs = 5, gap = {4, 8}},
    halls = {rooms = 12, size = {5, 8}, hall = 60, hall_size = {6, 9}, loops = 4, style = 50, big = false, spurs = 2, gap = {1, 3}},
    -- the backrooms: many same-sized rooms, a cell apart, looped every way (not in ARCH_ORDER)
    backrooms = {rooms = 28, size = {3, 4}, hall = 0, hall_size = {3, 4}, loops = 20, style = 0, big = false, spurs = 4, gap = {1, 1}},
}
local ARCH_ORDER = {"warren", "crypt", "cistern", "mine", "halls"}
local MUTATORS = {"dark", "ambush", "silent", "collapsed"}
local STAGE_LIGHT = {[1] = {0.55, 0.38, 0.2}, [2] = {0.5, 0.42, 0.3}, [3] = {0.25, 0.4, 0.45}, [4] = {0.5, 0.3, 0.15}, [5] = {0.6, 0.25, 0.1}, [6] = {0.35, 0.3, 0.45}, [7] = {0.45, 0.2, 0.2}}
local QUIET_LIGHT = {0.6, 0.5, 0.35}
-- light by use (endless_gen.USE_LIGHT)
local USE_LIGHT = {kitchen = 1.15, workshop = 1.15, surgery = 1.1, shrine = 1.05, barracks = 0.9, store = 0.65, latrine = 0.55, gaol = 0.5}

local function assign_purposes(rng, lay, depth)
    local quiet_done = false
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" then
            local roll = rng:between(0, 99)
            if depth >= 2 and not quiet_done and roll < 25 then room.purpose = "quiet"; quiet_done = true
            elseif roll < 34 then room.purpose = "store"
            elseif roll < 48 then room.purpose = "barracks"
            elseif roll < 60 then room.purpose = "kitchen"
            elseif roll < 68 then room.purpose = "latrine"
            elseif roll < 77 then room.purpose = "workshop"
            elseif depth >= 3 and roll < 85 then room.purpose = "shrine"
            elseif depth >= 2 and roll < 90 then room.purpose = "gaol"
            elseif depth >= 4 and roll < 94 then room.purpose = "surgery"
            else room.purpose = "plain" end
        end
    end
end

-- assets/endless-dress.bin (EDR2): per stage {classes = {objs...} per class, rooms = {{tag, {{class0, objs}}}},
-- by_tag = {tag = {room index}}, tipped = {model = {{m1..m9, dy}}}}; parsed in the build task
local function dress_objs(blob, p)
    local no
    no, p = sunpack("<I4", blob, p)
    local objs = {}
    for o = 1, no do
        local dx, dy, dz, n
        dx, dy, dz, n, p = sunpack("<fffI4", blob, p)
        objs[o] = {dx, dy, dz, blob:sub(p, p + n - 1)}
        p = p + n
    end
    return objs, p
end
local function dress_name(raw)
    local nm = raw:sub(13, 28)
    local zi = nm:find("\0", 1, true)
    if zi then nm = nm:sub(1, zi - 1) end
    return nm
end
function gen.load_dress(t, blob)
    t.dress = {}
    local magic = blob and blob:sub(1, 4)
    if not blob or #blob < 8 or (magic ~= "EDR4" and magic ~= "EDR5") then return end
    local with_shapes = magic == "EDR5"
    local p = 5
    local nst
    nst, p = sunpack("<I4", blob, p)
    for stage = 1, nst do
        local ncls
        ncls, p = sunpack("<I4", blob, p)
        local classes = {}
        for ci = 1, ncls do
            local nd
            nd, p = sunpack("<I4", blob, p)
            local list = {}
            for d = 1, nd do list[d], p = dress_objs(blob, p) end
            classes[ci] = list
        end
        local nrooms
        nrooms, p = sunpack("<I4", blob, p)
        local rooms, by_tag = {}, {}
        for ri = 1, nrooms do
            local tag, rw, rh, ncells
            tag, rw, rh, ncells, p = sunpack("<I4I4I4I4", blob, p)
            local cells = {}
            for k = 1, ncells do
                local cls, ck
                cls, ck, p = sunpack("<I4I4", blob, p)
                local objs
                objs, p = dress_objs(blob, p)
                local nit
                nit, p = sunpack("<I4", blob, p)
                local items = {}
                for it = 1, nit do
                    local iid, dx, dy, dz, yaw
                    iid, dx, dy, dz, yaw, p = sunpack("<I4ffff", blob, p)
                    items[it] = {iid, dx, dy, dz, yaw}
                end
                cells[k] = {cls, objs, items, ck}
            end
            rooms[ri] = {tag, cells, rw, rh}
            by_tag[tag] = by_tag[tag] or {}
            by_tag[tag][#by_tag[tag] + 1] = ri
        end
        local ntip
        ntip, p = sunpack("<I4", blob, p)
        local tipped = {}
        for _ = 1, ntip do
            local nm = blob:sub(p, p + 15)
            local zi = nm:find("\0", 1, true)
            if zi then nm = nm:sub(1, zi - 1) end
            p = p + 16
            local m1, m2, m3, m4, m5, m6, m7, m8, m9, dy
            m1, m2, m3, m4, m5, m6, m7, m8, m9, dy, p = sunpack("<ffffffffff", blob, p)
            tipped[nm] = tipped[nm] or {}
            tipped[nm][#tipped[nm] + 1] = {m1, m2, m3, m4, m5, m6, m7, m8, m9, dy}
        end
        local shapes = {}
        if with_shapes then -- room outlines (endless_gen.load_dress, STAMP_CHANCE)
            local nsh
            nsh, p = sunpack("<I4", blob, p)
            for k = 1, nsh do
                local sw, sh, n = blob:byte(p, p + 2)
                p = p + 3
                local cells = {}
                for j = 1, n do cells[j] = {blob:byte(p + 2 * (j - 1)), blob:byte(p + 2 * (j - 1) + 1)} end
                p = p + 2 * n
                shapes[k] = {sw, sh, cells}
            end
        end
        t.dress[stage] = {classes = classes, rooms = rooms, by_tag = by_tag, tipped = tipped, shapes = shapes}
    end
end

-- a matrix turned about the world's vertical axis (rows times the yaw matrix), keeping any tilt
local function turn_rows(m, degrees)
    local a = math.rad(degrees)
    local c, s_ = math.cos(a), math.sin(a)
    return {m[1] * c - m[3] * s_, m[2], m[1] * s_ + m[3] * c,
            m[4] * c - m[6] * s_, m[5], m[4] * s_ + m[6] * c,
            m[7] * c - m[9] * s_, m[8], m[7] * s_ + m[9] * c}
end

-- whether vanilla places this prop on a level that wears this stage's stone
local function themed(t, name, stage)
    if stage == 0 or t.prop_stages[name] == nil then return true end
    return t.prop_stages[name][stage] == true
end

-- each ordinary room's source room for its purpose; the purpose then follows what the source holds
local function choose_sources(rng, lay, dress)
    if not dress or #dress.rooms == 0 then return end
    local d_rooms, d_by_tag = dress.rooms, dress.by_tag
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" then
            local tag = PURPOSE_TAG[room.purpose]
            local pool = (tag ~= nil and d_by_tag[tag]) or {}
            if #pool == 0 then
                pool = {}
                for ri = 1, #d_rooms do pool[ri] = ri end
            end
            -- by scale: a small room takes a small source room, a big one a big one
            local size = (room.c1 - room.c0 + 1) * (room.r1 - room.r0 + 1)
            if room.cut then for _ in pairs(room.cut) do size = size - 1 end end
            local near = {}
            for _, ri in ipairs(pool) do
                local n = #d_rooms[ri][2]
                if n * SIZE_FACTOR >= size and n <= size * SIZE_FACTOR then near[#near + 1] = ri end
            end
            if #near == 0 then
                local best
                for _, ri in ipairs(pool) do
                    local dd = math.abs(#d_rooms[ri][2] - size)
                    if best == nil or dd < best then best = dd end
                end
                for _, ri in ipairs(pool) do if math.abs(#d_rooms[ri][2] - size) == best then near[#near + 1] = ri end end
            end
            room.src = rng:pick(near)
            local st = d_rooms[room.src][1]
            if room.purpose ~= "quiet" and TAG_PURPOSE[st] then room.purpose = TAG_PURPOSE[st] end
        end
    end
end

-- easter egg 4: now and then, on the catacombs' stone, one room of a source room's exact size becomes it
-- one showpiece per area (endless_gen.pick_showpiece, SHOW_TAGS: shrine, surgery, workshop, kitchen)
local SHOW_TAGS = {6, 8, 5, 3, 2, 1, 7, 4}
local function pick_showpiece(rng, lay, dress)
    if not dress then return end
    local d_rooms = dress.rooms
    for _, tag in ipairs(SHOW_TAGS) do
        local purpose = TAG_PURPOSE[tag]
        local pairs_ = {}
        for i = 0, lay.nrooms - 1 do
            local room = lay.rooms[i]
            if room.kind == "room" and not room.copy and room.cut == nil and room.purpose == purpose then
                local rw, rh = room.c1 - room.c0 + 1, room.r1 - room.r0 + 1
                for ri, dr in ipairs(d_rooms) do
                    if dr[1] == tag and dr[3] == rw and dr[4] == rh and #dr[2] == rw * rh then pairs_[#pairs_ + 1] = {i, ri} end
                end
            end
        end
        if #pairs_ > 0 then
            local pick = rng:pick(pairs_)
            lay.rooms[pick[1]].src, lay.rooms[pick[1]].show = pick[2], true
            return
        end
    end
end

local function pick_copy(rng, lay, dress, stage_no)
    if not dress or stage_no ~= 1 or not rng:chance(COPY_CHANCE) then return end
    local d_rooms = dress.rooms
    local pairs_ = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" and room.purpose ~= "quiet" and room.cut == nil then
            local rw, rh = room.c1 - room.c0 + 1, room.r1 - room.r0 + 1
            for ri, dr in ipairs(d_rooms) do
                if dr[3] == rw and dr[4] == rh and #dr[2] == rw * rh then pairs_[#pairs_ + 1] = {i, ri} end
            end
        end
    end
    if #pairs_ == 0 then return end
    local pick = rng:pick(pairs_)
    local room = lay.rooms[pick[1]]
    room.src, room.copy = pick[2], true
    lay.copy_egg = true
    if TAG_PURPOSE[d_rooms[pick[2]][1]] then room.purpose = TAG_PURPOSE[d_rooms[pick[2]][1]] end
end

-- swaps purposes (with their source rooms) until the neighbour and size rules hold where they can
local function arrange_neighbours(lay)
    local rooms = {}
    for i = 0, lay.nrooms - 1 do if lay.rooms[i].kind == "room" then rooms[#rooms + 1] = lay.rooms[i] end end
    local n = #rooms
    if n < 2 then return end
    local nb, sizes = {}, {}
    for i = 1, n do
        local rm = rooms[i]
        local size = (rm.c1 - rm.c0 + 1) * (rm.r1 - rm.r0 + 1)
        if rm.cut then for _ in pairs(rm.cut) do size = size - 1 end end -- the cells helper is defined further down
        nb[i] = {}; sizes[i] = size
    end
    for i = 1, n do
        local a = rooms[i]
        for j = i + 1, n do
            local b = rooms[j]
            local gap = math.max(b.c0 - a.c1 - 1, a.c0 - b.c1 - 1, b.r0 - a.r1 - 1, a.r0 - b.r1 - 1)
            if gap <= NEIGHBOUR_GAP then
                nb[i][#nb[i] + 1] = j
                nb[j][#nb[j] + 1] = i
            end
        end
    end
    local function broken(i)
        local p = rooms[i].purpose
        local bad = 0
        local any_store = false
        for k = 1, n do if rooms[k].purpose == "store" then any_store = true break end end
        local near_sk, near_kitchen, near_gl, near_apart, near_shrine = false, false, false, false, false
        for _, j in ipairs(nb[i]) do
            local q = rooms[j].purpose
            if q == "store" or q == "kitchen" then near_sk = true end
            if q == "kitchen" then near_kitchen = true end
            if q == "gaol" or q == "latrine" then near_gl = true end
            if SHRINE_APART[q] then near_apart = true end
            if q == "shrine" then near_shrine = true end
        end
        if p == "kitchen" and any_store and not near_sk then bad = bad + 1 end
        if (p == "gaol" or p == "latrine") and near_kitchen then bad = bad + 1 end
        if p == "kitchen" and near_gl then bad = bad + 1 end
        if p == "shrine" and near_apart then bad = bad + 1 end
        if SHRINE_APART[p] and near_shrine then bad = bad + 1 end
        if SMALL_PURPOSES[p] and sizes[i] > SMALL_MAX then bad = bad + 1 end
        if BIG_PURPOSES[p] and sizes[i] < BIG_MIN then bad = bad + 1 end
        return bad
    end
    local function around(i, j)
        local set, list = {}, {}
        local function add(k) if not set[k] then set[k] = true; list[#list + 1] = k end end
        add(i); add(j)
        for _, k in ipairs(nb[i]) do add(k) end
        for _, k in ipairs(nb[j]) do add(k) end
        return list
    end
    local function swap(i, j)
        rooms[i].purpose, rooms[j].purpose = rooms[j].purpose, rooms[i].purpose
        rooms[i].src, rooms[j].src = rooms[j].src, rooms[i].src
    end
    for _ = 1, NEIGHBOUR_PASSES do
        local changed = false
        for i = 1, n do
            if rooms[i].purpose ~= "quiet" and broken(i) > 0 then
                for j = 1, n do
                    if j ~= i and rooms[j].purpose ~= "quiet" and rooms[j].purpose ~= rooms[i].purpose then
                        local zone = around(i, j)
                        local before = 0
                        for _, k in ipairs(zone) do before = before + broken(k) end
                        swap(i, j)
                        local after = 0
                        for _, k in ipairs(zone) do after = after + broken(k) end
                        if after < before then changed = true break end
                        swap(i, j)
                    end
                end
            end
        end
        if not changed then break end
    end
end

local function props_for(t, purpose, stage)
    local wanted = PURPOSE_PROPS[purpose] or PURPOSE_PROPS.plain
    local out = {}
    for i, raw in ipairs(t.props) do
        local nm = t.prop_names[i]
        if (wanted[nm] or (PURPOSE_PROPS[purpose] == nil)) and themed(t, nm, stage) then out[#out + 1] = raw end
    end
    return out
end

local function rare_chests(t)
    for k = #t.chest_tiers, 1, -1 do if #t.chest_tiers[k] > 0 then return t.chest_tiers[k] end end
    return t.chest_ids
end

-- the companion record found on this area, or 0 (met: set of 0-based indices already met, nil = nobody)
local function companion_for(t, area, met)
    if #t.companion_ids == 0 or (area - 1) % AREAS_PER_DEPTH ~= 1 then return 0 end
    local depth = gen.depth_of(area)
    local which = (depth - 1) % #t.companion_ids
    if met ~= nil and met[which] then
        which = -1
        for i = 0, #t.companion_ids - 1 do if not met[i] then which = i break end end
    end
    if which < 0 then return 0 end
    if met == nil and depth > #t.companion_ids then return 0 end
    return t.companion_ids[which + 1]
end

-- ---------------------------------------------------------------- random (splitmix64 seed, xorshift64*)
local Rng = {}
-- no metatables in the runtime sandbox: each instance carries its methods
local function with_methods(o, class)
    for k, v in pairs(class) do if type(v) == "function" and k ~= "new" then o[k] = v end end
    return o
end
function Rng.new(seed, area)
    local x = seed * 0x9E3779B97F4A7C15 + area * 0xBF58476D1CE4E5B9 + 0x94D049BB133111EB -- hex literals wrap to 64-bit
    for _ = 1, 3 do
        x = x + 0x9E3779B97F4A7C15
        local z = x
        z = (z ~ (z >> 30)) * 0xBF58476D1CE4E5B9
        z = (z ~ (z >> 27)) * 0x94D049BB133111EB
        x = z ~ (z >> 31)
    end
    return with_methods({state = x ~= 0 and x or 1}, Rng)
end
function Rng:next()
    local x = self.state
    x = x ~ (x >> 12)
    x = x ~ (x << 25)
    x = x ~ (x >> 27)
    self.state = x
    return x * 0x2545F4914F6CDD1D
end
function Rng:below(n) if n <= 0 then return 0 end return (self:next() >> 32) % n end
function Rng:between(lo, hi) return lo + self:below(hi - lo + 1) end
function Rng:unit() return (self:next() >> 40) / 16777216.0 end
function Rng:chance(percent) return self:below(100) < percent end
function Rng:pick(list) return list[self:below(#list) + 1] end

-- ---------------------------------------------------------------- layout
local function room_new(c0, r0, c1, r1, kind)
    return {c0 = c0, r0 = r0, c1 = c1, r1 = r1, kind = kind or "room", style = 0, entry = {0, 0}, goal = {0, 0}, purpose = "plain", cut = nil, pillars = false, src = 0, copy = false}
end
local function centre(room)
    if room.kind == "maze" then return room.entry[1], room.entry[2] end
    return (room.c0 + room.c1) // 2, (room.r0 + room.r1) // 2
end
local function is_cut(room, c, r) return room.cut ~= nil and room.cut[c * 1000 + r] == true end
local function contains(room, c, r) return c >= room.c0 and c <= room.c1 and r >= room.r0 and r <= room.r1 and not is_cut(room, c, r) end
local function touches(a, b, gap)
    gap = gap or 1
    return not (a.c1 + gap < b.c0 or b.c1 + gap < a.c0 or a.r1 + gap < b.r0 or b.r1 + gap < a.r0)
end
local function cells_of(room)
    local out = {}
    for r = room.r0, room.r1 do for c = room.c0, room.c1 do if not is_cut(room, c, r) then out[#out + 1] = {c, r} end end end
    return out
end
-- an L room (one corner quadrant unbuilt, never the centre) or an octagon (the four corner cells)
local function room_cut(rng, room)
    local rw, rh = room.c1 - room.c0 + 1, room.r1 - room.r0 + 1
    local cut = {}
    if rng:below(2) == 0 then
        local q = rng:below(4)
        local cw, ch = (rw - 1) // 2, (rh - 1) // 2
        local cs, ce, rs, re
        if q == 0 or q == 2 then cs, ce = room.c0, room.c0 + cw - 1 else cs, ce = room.c1 - cw + 1, room.c1 end
        if q == 0 or q == 1 then rs, re = room.r0, room.r0 + ch - 1 else rs, re = room.r1 - ch + 1, room.r1 end
        for r = rs, re do for c = cs, ce do cut[c * 1000 + r] = true end end
    else
        cut[room.c0 * 1000 + room.r0] = true; cut[room.c1 * 1000 + room.r0] = true
        cut[room.c0 * 1000 + room.r1] = true; cut[room.c1 * 1000 + room.r1] = true
    end
    return cut
end
local function dist(ac, ar, bc, br) return math.abs(ac - bc) + math.abs(ar - br) end
-- stable sort by key (insertion), as Python's sorted keeps order for equal keys;
-- also the only sort the build uses: a table.sort comparator is a C callback the runtime's task hook cannot yield in
local function stable_sort(list, keyfn)
    local out = {}
    for _, v in ipairs(list) do
        local k = keyfn(v)
        local i = #out
        while i >= 1 and keyfn(out[i]) > k do out[i + 1] = out[i]; i = i - 1 end
        out[i + 1] = v
    end
    return out
end

-- walkways (endless_gen.walkway, WALK_CLEAR)
local WALK_CLEAR = 0.3 * CELL
local GROUP_CHANCE = 50 -- endless_gen GROUP_CHANCE
local WALL_DRESS_CHANCE, HUNG_Y = 45, 80.0 -- endless_gen: wall dressing by purpose
local HUNG_NEAR = 0.3 * CELL -- endless_gen: a wall piece pressed against a doorway or open side is left out
local WALK_DECAL_CHANCE, DECAL_FIGHT, DECAL_KITCHEN = 35, 2, 1 -- endless_gen: floor decals by use
local CORRIDOR_CLUTTER, DOORWAY_DRESS = 50, 50 -- endless_gen: corridor clutter
local TRAIL_LEN, TRAIL_CHANCE = 4, 75 -- endless_gen: stories across rooms
local EVENT_FIGHT, EVENT_LOOTED, EVENT_HURRY = 15, 30, 50 -- endless_gen: one event per room
local TIDY_JITTER, HURRY_JITTER = 8.0, 60.0
local FIGHT_DEBRIS = 3
local function walkway(lay, room)
    local cells = {}
    for _, cell in ipairs(cells_of(room)) do cells[cell[1] * 1000 + cell[2]] = true end
    local doors, seen = {}, {}
    for _, d in ipairs(lay.doors) do
        for e = 0, 1 do
            local x, z = d[1 + 2 * e], d[2 + 2 * e]
            local key = x * 1000 + z
            if cells[key] and not seen[key] then seen[key] = true; doors[#doors + 1] = {x, z} end
        end
    end
    local out = {}
    if #doors == 0 then return out end
    local targets = {}
    if #doors > 1 then
        for i = 2, #doors do targets[#targets + 1] = doors[i] end
    else
        local cc, cr = centre(room)
        targets[1] = cells[cc * 1000 + cr] and {cc, cr} or doors[1]
    end
    local start = doors[1][1] * 1000 + doors[1][2]
    local parent = {[start] = false}
    local queue = {doors[1]}
    local i = 1
    while i <= #queue do
        local c, r = queue[i][1], queue[i][2]
        i = i + 1
        for q = 0, 3 do
            local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
            local nk = nc * 1000 + nr
            if cells[nk] and parent[nk] == nil then
                parent[nk] = c * 1000 + r
                queue[#queue + 1] = {nc, nr}
            end
        end
    end
    for _, tcell in ipairs(targets) do
        local x = tcell[1] * 1000 + tcell[2]
        if parent[x] ~= nil then
            while x do
                out[x] = true
                x = parent[x]
            end
        end
    end
    return out
end

local Layout = {}
function Layout.new(w, h, rooms, nrooms)
    local owner = {}
    for i = 0, w * h - 1 do owner[i] = -1 end
    return with_methods({w = w, h = h, owner = owner, rooms = rooms, nrooms = nrooms, doors = {}, corridor = {}, exit_door = nil, spur_ends = {}}, Layout)
end
function Layout:at(c, r)
    if c >= 0 and c < self.w and r >= 0 and r < self.h then return self.owner[r * self.w + c] end
    return -1
end
function Layout:built(c, r) return self:at(c, r) >= 0 end
-- doorway edges are looked up in a set kept beside the list: the list is only ever appended to or replaced
-- whole, so the set follows it by length and identity (a scan of the list was a third of an area's build)
local function door_key(ac, ar, bc, br)
    local ka, kb = ac * 1000 + ar, bc * 1000 + br
    if ka > kb then ka, kb = kb, ka end
    return ka * 1000000 + kb
end
function Layout:is_door(ac, ar, bc, br)
    local doors = self.doors
    if self.door_list ~= doors then self.door_list, self.door_n, self.door_set = doors, 0, {} end
    local set = self.door_set
    for i = self.door_n + 1, #doors do
        local d = doors[i]
        set[door_key(d[1], d[2], d[3], d[4])] = true
    end
    self.door_n = #doors
    return set[door_key(ac, ar, bc, br)] == true
end
function Layout:boss_room()
    for i = 0, self.nrooms - 1 do if self.rooms[i].kind == "boss" then return self.rooms[i], i end end
end
function Layout:exit_room()
    for i = 0, self.nrooms - 1 do
        local k = self.rooms[i].kind
        if k == "exit" or k == "maze" then return self.rooms[i], i end
    end
end

local function rect_free(rooms, nrooms, skip, c0, r0, c1, r1)
    local probe = room_new(c0, r0, c1, r1)
    for i = 0, nrooms - 1 do if i ~= skip and touches(probe, rooms[i]) then return false end end
    return true
end

local function carve_maze(lay, rng, m, index)
    local nodes_c = (m.c1 - m.c0) // 2 + 1
    local nodes_r = (m.r1 - m.r0) // 2 + 1
    local visited = {}
    local function carve(c, r) lay.owner[r * lay.w + c] = index end
    local stack = {{0, 0}}
    visited[0] = true
    carve(m.c0, m.r0)
    local di = {1, 0, -1, 0}
    local dj = {0, 1, 0, -1}
    while #stack > 0 do
        local top = stack[#stack]
        local i, j = top[1], top[2]
        local choices = {}
        for k = 1, 4 do
            local ni, nj = i + di[k], j + dj[k]
            if ni >= 0 and ni < nodes_c and nj >= 0 and nj < nodes_r and not visited[ni * nodes_r + nj] then choices[#choices + 1] = {ni, nj} end
        end
        if #choices == 0 then
            stack[#stack] = nil
        else
            local pick = rng:pick(choices)
            local ni, nj = pick[1], pick[2]
            visited[ni * nodes_r + nj] = true
            local c, r = m.c0 + 2 * i, m.r0 + 2 * j
            local nc, nr = m.c0 + 2 * ni, m.r0 + 2 * nj
            carve((c + nc) // 2, (r + nr) // 2)
            carve(nc, nr)
            stack[#stack + 1] = pick
        end
    end
end

-- Deterministic cheapest path (step 1, turn 3), bucketed Dijkstra over (cell, heading) with
-- insertion-order ties; the outer ring and blocked cells (except b) cannot be entered.
-- corridors wander and widen (endless_gen TURN_COST, _wander, WIDE_MIN, WIDE_CHANCE)
local function wander(lay, c, r)
    local v = ((c * 73856093) ~ (r * 19349663) ~ (lay.wander or 0)) & 0xFFFF
    if v % 10 < 2 then return 2 elseif v % 10 < 4 then return 1 end
    return 0
end

local function route(lay, ac, ar, bc, br, blocked)
    local w, h = lay.w, lay.h
    local wg = lay.wander_grid
    if not wg or lay.wander_grid_salt ~= lay.wander then
        wg = {}
        for r = 0, h - 1 do for c = 0, w - 1 do wg[r * w + c] = wander(lay, c, r) end end
        lay.wander_grid, lay.wander_grid_salt = wg, lay.wander
    end
    local INF = 1 << 30
    -- the search stays inside a box round the two ends (ROUTE_MARGIN cells beyond them)
    local minc, maxc = math.max(1, math.min(ac, bc) - ROUTE_MARGIN), math.min(w - 2, math.max(ac, bc) + ROUTE_MARGIN)
    local minr, maxr = math.max(1, math.min(ar, br) - ROUTE_MARGIN), math.min(h - 2, math.max(ar, br) + ROUTE_MARGIN)
    local best = {}
    local parent = {} -- state key -> the state key it was reached from (a state is expanded once, at its final cost)
    local buckets = {[0] = {(ar * w + ac) * 5}} -- states as integers: (r * w + c) * 5 + heading + 1
    local pending = 1
    local cost = 0
    while cost < 8 * (w + h) and pending > 0 do
        local bucket = buckets[cost]
        if bucket then
            buckets[cost] = nil
            pending = pending - 1
            for _, key in ipairs(bucket) do
                local idx = key // 5
                local heading = key % 5 - 1
                local cc, cr = idx % w, idx // w
                if not ((best[key] or INF) < cost) then
                    if cc == bc and cr == br then
                        local rev = {}
                        local k = key
                        while k do
                            local i2 = k // 5
                            rev[#rev + 1] = {i2 % w, i2 // w}
                            k = parent[k]
                        end
                        local path = {}
                        for i = #rev, 1, -1 do path[#path + 1] = rev[i] end
                        return path
                    end
                    for q = 0, 3 do
                        local nc, nr = cc + SIDE_DX[q], cr + SIDE_DZ[q]
                        if nc >= minc and nc <= maxc and nr >= minr and nr <= maxr and not ((nc ~= bc or nr ~= br) and blocked[nr * w + nc]) then
                            local c2 = cost + 1 + wg[nr * w + nc] + ((heading ~= -1 and heading ~= q) and 2 or 0)
                            local nkey = (nr * w + nc) * 5 + q + 1
                            if not ((best[nkey] or INF) <= c2) then
                                best[nkey] = c2
                                parent[nkey] = key
                                if not buckets[c2] then buckets[c2] = {}; pending = pending + 1 end
                                local b = buckets[c2]
                                b[#b + 1] = nkey
                            end
                        end
                    end
                end
            end
        end
        cost = cost + 1
    end
    return {}
end

local function carve_corridor(lay, a, b)
    local protected = {}
    for i = 0, lay.nrooms - 1 do
        local r = lay.rooms[i]
        if r.kind == "exit" or r.kind == "maze" or r.kind == "boss" then protected[#protected + 1] = r end
    end
    local blocked = {}
    for _, p in ipairs(protected) do
        if p ~= b or p.kind == "maze" then
            -- its cells, not its rectangle: an L or octagon's cut corner is open ground (as endless_gen's p.cells)
            for r = p.r0, p.r1 do for c = p.c0, p.c1 do if not is_cut(p, c, r) then blocked[r * lay.w + c] = true end end end
        end
    end
    local ac, ar = centre(a)
    local bc, br = centre(b)
    local path = route(lay, ac, ar, bc, br, blocked)
    for _, p in ipairs(path) do
        local cc, rr = p[1], p[2]
        local inside = false
        for _, pr in ipairs(protected) do if contains(pr, cc, rr) then inside = true break end end
        if lay.owner[rr * lay.w + cc] == -1 and not inside then
            lay.owner[rr * lay.w + cc] = CORRIDOR
            lay.corridor[#lay.corridor + 1] = {cc, rr}
        end
    end
    -- a second lane along the middle third, on the left of the way, now and then
    local pick = ((ac * 73856093) ~ (ar * 19349663) ~ (bc * 83492791) ~ (br * 2654435) ~ (lay.wander or 0)) & 0xFFFF
    if #path >= 8 and pick % 100 < 25 then
        local third = #path // 3
        for k = third, 2 * third - 1 do
            local cc, rr = path[k + 1][1], path[k + 1][2]
            local nc, nr = path[k + 2][1], path[k + 2][2]
            local sc, sr = cc - (nr - rr), rr + (nc - cc)
            if lay.owner[rr * lay.w + cc] == CORRIDOR and sc >= 2 and sc <= lay.w - 3 and sr >= 2 and sr <= lay.h - 3
                and lay.owner[sr * lay.w + sc] == -1 then
                local inside = false
                for _, pr in ipairs(protected) do
                    if sc >= pr.c0 and sc <= pr.c1 and sr >= pr.r0 and sr <= pr.r1 then inside = true break end
                end
                if not inside then
                    lay.owner[sr * lay.w + sc] = CORRIDOR
                    lay.corridor[#lay.corridor + 1] = {sc, sr}
                end
            end
        end
    end
    for i = 1, #path - 1 do
        local x1, z1, x2, z2 = path[i][1], path[i][2], path[i + 1][1], path[i + 1][2]
        local o1, o2 = lay:at(x1, z1), lay:at(x2, z2)
        if o1 >= 0 and o2 >= 0 and o1 ~= o2 and not lay:is_door(x1, z1, x2, z2) then lay.doors[#lay.doors + 1] = {x1, z1, x2, z2} end
    end
end

local side_kind -- forward

local function reachable(lay, sc, sr)
    local seen = {[sr * lay.w + sc] = true}
    local queue = {{sc, sr}}
    local head = 1
    while head <= #queue do
        local c, r = queue[head][1], queue[head][2]
        head = head + 1
        for q = 0, 3 do
            local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
            if lay:built(nc, nr) and not seen[nr * lay.w + nc] and side_kind(lay, c, r, q) ~= WALL then
                seen[nr * lay.w + nc] = true
                queue[#queue + 1] = {nc, nr}
            end
        end
    end
    return seen
end

local function touches_exit(ex, d) return contains(ex, d[1], d[2]) or contains(ex, d[3], d[4]) end

-- the hidden puzzle: a 2x2 room off an ordinary room behind a secret door (switch on the host's wall)
local function treasury(lay, rng)
    local hosts = {}
    for i = 0, lay.nrooms - 1 do if lay.rooms[i].kind == "room" then hosts[#hosts + 1] = lay.rooms[i] end end
    if #hosts == 0 then return end
    for _ = 1, 80 do
        local host = rng:pick(hosts)
        local cell = rng:pick(cells_of(host))
        local c, r = cell[1], cell[2]
        local q = rng:below(4)
        local dx, dz = SIDE_DX[q], SIDE_DZ[q]
        local oc, orr = c + dx, r + dz
        if not contains(host, oc, orr) then
            local c0 = dx >= 0 and oc or oc - 1
            local r0 = dz >= 0 and orr or orr - 1
            if dx ~= 0 then r0 = orr - rng:below(2) else c0 = oc - rng:below(2) end
            local room = room_new(c0, r0, c0 + 1, r0 + 1, "treasury")
            local bad = not (c0 >= 2 and c0 + 1 <= lay.w - 3 and r0 >= 2 and r0 + 1 <= lay.h - 3)
            if not bad then for _, rc in ipairs(cells_of(room)) do if lay:built(rc[1], rc[2]) then bad = true end end end
            if not bad then
                for i = 0, lay.nrooms - 1 do
                    local o = lay.rooms[i]
                    if o ~= host and touches(room, o) then bad = true end
                end
            end
            if not bad then
                for _, rc in ipairs(cells_of(room)) do
                    for k = 0, 3 do
                        local nc, nr = rc[1] + SIDE_DX[k], rc[2] + SIDE_DZ[k]
                        if not contains(room, nc, nr) and lay:built(nc, nr) and not contains(host, nc, nr) then bad = true end
                    end
                end
            end
            if not bad then
                local index = lay.nrooms
                lay.rooms[index] = room
                lay.nrooms = index + 1
                for _, rc in ipairs(cells_of(room)) do lay.owner[rc[2] * lay.w + rc[1]] = index end
                lay.doors[#lay.doors + 1] = {c, r, oc, orr}
                table.insert(lay.secrets, 1, {c, r, oc, orr, host})
                lay.treasury = room
                return
            end
        end
    end
end

local function same_edge(d, ac, ar, bc, br)
    return (d[1] == ac and d[2] == ar and d[3] == bc and d[4] == br) or (d[1] == bc and d[2] == br and d[3] == ac and d[4] == ar)
end

-- cells reachable from (sc, sr) with one edge shut (keys r * w + c)
-- a doorway barricaded shut (lay.blocked keyed like edge_key: the smaller cell key * 65536 + the larger)
local function is_blocked(lay, c, r, nc, nr)
    if not lay.blocked then return false end
    local ka, kb = r * lay.w + c, nr * lay.w + nc
    if ka > kb then ka, kb = kb, ka end
    return lay.blocked[ka * 65536 + kb] == true
end

-- `stop` (a cell key): return as soon as it is reached; the caller then only needs to know that
local function reach_without(lay, sc, sr, ac, ar, bc, br, stop)
    local w, h, owner = lay.w, lay.h, lay.owner
    local seen = {[sr * w + sc] = true}
    local queue = {{sc, sr}}
    local head = 1
    while head <= #queue do
        local c, r = queue[head][1], queue[head][2]
        head = head + 1
        for q = 0, 3 do
            local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
            local nk = nr * w + nc
            if nc >= 0 and nc < w and nr >= 0 and nr < h and owner[nk] >= 0 and not seen[nk] and side_kind(lay, c, r, q) ~= WALL and not is_blocked(lay, c, r, nc, nr)
                and not ((c == ac and r == ar and nc == bc and nr == br) or (c == bc and r == br and nc == ac and nr == ar)) then
                seen[nk] = true
                if nk == stop then return seen end
                queue[#queue + 1] = {nc, nr}
            end
        end
    end
    return seen
end

-- cells reachable with a set of edges shut: shut[min(ka, kb) * 65536 + max(ka, kb)] with k = r * w + c
local function edge_key(w, ac, ar, bc, br)
    local ka, kb = ar * w + ac, br * w + bc
    if ka > kb then ka, kb = kb, ka end
    return ka * 65536 + kb
end
local function reach_shut(lay, sc, sr, shut)
    local w = lay.w
    local seen = {[sr * w + sc] = true}
    local queue = {{sc, sr}}
    local head = 1
    while head <= #queue do
        local c, r = queue[head][1], queue[head][2]
        head = head + 1
        for q = 0, 3 do
            local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
            if lay:built(nc, nr) and not seen[nr * w + nc] and side_kind(lay, c, r, q) ~= WALL and not shut[edge_key(w, c, r, nc, nr)] and not is_blocked(lay, c, r, nc, nr) then
                seen[nr * w + nc] = true
                queue[#queue + 1] = {nc, nr}
            end
        end
    end
    return seen
end
local function secret_shut(lay)
    local shut = {}
    for _, sd in ipairs(lay.secrets) do shut[edge_key(lay.w, sd[1], sd[2], sd[3], sd[4])] = true end
    return shut
end

local function wing_lever(lay, reach, gc, gr)
    local function far(c, r) return math.abs(c - gc) + math.abs(r - gr) end
    local function walled(c, r)
        for q = 0, 3 do if side_kind(lay, c, r, q) == WALL then return true end end
        return false
    end
    local best
    for _, cell in ipairs(lay.spur_ends) do
        if reach[cell[2] * lay.w + cell[1]] and walled(cell[1], cell[2]) and (best == nil or far(cell[1], cell[2]) > far(best[1], best[2])) then best = cell end
    end
    if not best then
        for i = 0, lay.nrooms - 1 do
            local rm = lay.rooms[i]
            local cc, cr = centre(rm)
            if rm.kind == "room" and reach[cr * lay.w + cc] then
                for _, cell in ipairs(cells_of(rm)) do
                    local wall = false
                    for q = 0, 3 do if side_kind(lay, cell[1], cell[2], q) == WALL then wall = true break end end
                    if wall and (best == nil or far(cell[1], cell[2]) > far(best[1], best[2])) then best = cell end
                end
            end
        end
    end
    if not best then return nil end
    for q = 0, 3 do if side_kind(lay, best[1], best[2], q) == WALL then return best, q end end
    return nil
end

-- the main puzzle: a portcullis on a doorway every way to the boss door passes, its lever on the near side
local function wing_gate(lay)
    if not lay.exit_door then return end
    local w = lay.w
    local sc0, sr0 = centre(lay.rooms[0])
    local tc, tr = lay.exit_door[3], lay.exit_door[4]
    local function skipped(c, r)
        for i = 0, lay.nrooms - 1 do
            local rm = lay.rooms[i]
            local k = rm.kind
            if (k == "start" or k == "exit" or k == "maze" or k == "boss" or k == "closet" or k == "treasury" or k == "pen") and contains(rm, c, r) then return true end
        end
        return false
    end
    local function excluded(ac, ar, bc, br)
        for _, sd in ipairs(lay.secrets) do if same_edge(sd, ac, ar, bc, br) then return true end end
        if same_edge(lay.exit_door, ac, ar, bc, br) then return true end
        if lay.gate and same_edge(lay.gate, ac, ar, bc, br) then return true end
        return false
    end
    local start, target = sr0 * w + sc0, tr * w + tc
    local parent = {[start] = -1}
    local queue = {start}
    local head = 1
    while head <= #queue do
        local k = queue[head]
        head = head + 1
        if k == target then break end
        local c, r = k % w, k // w
        for q = 0, 3 do
            local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
            if lay:built(nc, nr) and parent[nr * w + nc] == nil and side_kind(lay, c, r, q) ~= WALL and not is_blocked(lay, c, r, nc, nr) then
                parent[nr * w + nc] = k
                queue[#queue + 1] = nr * w + nc
            end
        end
    end
    if parent[target] == nil then return end
    local rev = {}
    local k = target
    while k ~= -1 do rev[#rev + 1] = k; k = parent[k] end
    -- candidates walked back from the boss door: a doorway, or the edge between two corridor cells
    for _, need in ipairs({2, 1}) do
        for i = 2, #rev do
            local a, b = rev[i], rev[i - 1]
            local ac, ar, bc, br = a % w, a // w, b % w, b // w
            local ok = not excluded(ac, ar, bc, br) and not skipped(ac, ar) and not skipped(bc, br)
                and (lay:is_door(ac, ar, bc, br) or (lay:at(ac, ar) == CORRIDOR and lay:at(bc, br) == CORRIDOR))
            if ok then
                local reach = reach_without(lay, sc0, sr0, ac, ar, bc, br, target)
                if not reach[target] then
                    local wing = 0
                    for j = 0, lay.nrooms - 1 do
                        local rm = lay.rooms[j]
                        local cc, cr = centre(rm)
                        if rm.kind == "room" and not reach[cr * w + cc] then wing = wing + 1 end
                    end
                    if wing >= need then
                        local shut = secret_shut(lay)
                        shut[edge_key(w, ac, ar, bc, br)] = true
                        local near = reach_shut(lay, sc0, sr0, shut)
                        local cell, lq = wing_lever(lay, near, bc, br)
                        if cell then
                            lay.wing = {ac, ar, bc, br, cell[1], cell[2], lq}
                            return
                        end
                    end
                end
            end
        end
    end
end
-- doorways between an ordinary room (two doorways or more) and a corridor, barricaded from the room
-- side, each only when everything reachable (secret doors shut) stays reachable without it
local function block_doors(lay, rng, depth)
    local count = 1 + depth // 2
    if count > MAX_BLOCKED then count = MAX_BLOCKED end
    local sc0, sr0 = centre(lay.rooms[0])
    local shut = secret_shut(lay)
    local function size(set) local n = 0 for _ in pairs(set) do n = n + 1 end return n end
    local full = size(reach_shut(lay, sc0, sr0, shut))
    local function protected(d)
        for _, sd in ipairs(lay.secrets) do if same_edge(sd, d[1], d[2], d[3], d[4]) then return true end end
        if lay.exit_door and same_edge(lay.exit_door, d[1], d[2], d[3], d[4]) then return true end
        if lay.gate and same_edge(lay.gate, d[1], d[2], d[3], d[4]) then return true end
        for _, cl in ipairs(lay.closets) do if same_edge(cl, d[1], d[2], d[3], d[4]) then return true end end
        return false
    end
    local cand = {}
    for _, d in ipairs(lay.doors) do
        if not protected(d) then
            local ac, ar, bc, br = d[1], d[2], d[3], d[4]
            local oa, ob = lay:at(ac, ar), lay:at(bc, br)
            if oa == CORRIDOR and ob >= 0 and ob < lay.nrooms then ac, ar, bc, br, oa, ob = bc, br, ac, ar, ob, oa end
            if oa >= 0 and oa < lay.nrooms and ob == CORRIDOR and lay.rooms[oa].kind == "room" then
                local room = lay.rooms[oa]
                local n = 0
                for _, dd in ipairs(lay.doors) do if contains(room, dd[1], dd[2]) or contains(room, dd[3], dd[4]) then n = n + 1 end end
                if n >= 2 then cand[#cand + 1] = {ac, ar, bc, br} end
            end
        end
    end
    lay.blocked = lay.blocked or {}
    lay.blocked_doors = {}
    while #cand > 0 and #lay.blocked_doors < count do
        local d = table.remove(cand, rng:below(#cand) + 1)
        local key = edge_key(lay.w, d[1], d[2], d[3], d[4])
        lay.blocked[key] = true
        if size(reach_shut(lay, sc0, sr0, shut)) ~= full then
            lay.blocked[key] = nil
        else
            lay.blocked_doors[#lay.blocked_doors + 1] = d
        end
    end
end

-- a build the mod no longer wants (the menu came) stops at the next checkpoint: gen.cancelled is set by
-- the mod around a build; the error is caught by the mod's pcall (no effect on what a build makes)
gen.cancelled = nil
local function checkpoint()
    if gen.cancelled and gen.cancelled() then error("endless build cancelled", 0) end
end

-- corridor sectors (endless_gen._segment_corridors, SEG_MAX): pieces of at most 8 cells joined by doorway sides
local function segment_corridors(lay)
    local w = lay.w
    local seg = {}
    local count = 0
    for _, cell in ipairs(lay.corridor) do
        local sk = cell[2] * w + cell[1]
        if seg[sk] == nil and lay:at(cell[1], cell[2]) == CORRIDOR then
            seg[sk] = count
            local queue, i, n = {cell}, 1, 1
            while i <= #queue and n < 8 do
                local c, r = queue[i][1], queue[i][2]
                i = i + 1
                for q = 0, 3 do
                    local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
                    if n < 8 and seg[nr * w + nc] == nil and lay:at(nc, nr) == CORRIDOR then
                        seg[nr * w + nc] = count
                        queue[#queue + 1] = {nc, nr}
                        n = n + 1
                    end
                end
            end
            count = count + 1
        end
    end
    for _, cell in ipairs(lay.corridor) do
        local c, r = cell[1], cell[2]
        local mine = seg[r * w + c]
        if mine ~= nil then
            for _, q in ipairs({2, 3}) do
                local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
                local other = seg[nr * w + nc]
                if other ~= nil and other ~= mine and not lay:is_door(c, r, nc, nr) then
                    lay.doors[#lay.doors + 1] = {c, r, nc, nr}
                end
            end
        end
    end
end

local function generate_layout(rng, w, h, area, sc, sr, arch_name, block_ok, plain, shapes)
    local depth = gen.depth_of(area)
    local arch = ARCHETYPES[arch_name or "warren"]
    local rooms = {[0] = room_new(sc - 1, sr - 1, sc + 1, sr + 1, "start")}
    local n = 1
    local wanted = 2 * arch.rooms + 3 * depth
    if wanted > MAX_ROOMS then wanted = MAX_ROOMS end
    local attempts = 0
    local big_done = not arch.big
    -- the spine, then wings (endless_gen SPINE_SHARE and the rest)
    local spine_n = math.max(3, wanted // 3)
    local heading = rng:below(4)
    local stall = 0
    while n < wanted and attempts < 2000 do
        attempts = attempts + 1
        if n < spine_n and stall >= 40 then spine_n = n end
        local rw, rh
        local stamp
        if not big_done then
            rw, rh = rng:between(8, 9), rng:between(8, 9)
        else
            local hall = depth >= 2 and rng:chance(arch.hall)
            local lo, hi
            if hall then lo, hi = arch.hall_size[1], arch.hall_size[2] else lo, hi = arch.size[1], arch.size[2] end
            rw = rng:between(lo, hi)
            rh = rng:between(lo, hi)
            if shapes and #shapes > 0 and rng:chance(30) then -- a room shaped like one of the stone's own
                stamp = rng:pick(shapes)
                local k = math.max(stamp[1], stamp[2]) <= 4 and 2 or 1
                rw, rh = stamp[1] * k, stamp[2] * k
            end
        end
        -- beside a room already placed: a side, a gap of ground, and an offset along that side
        local anchor, q
        if n < spine_n then
            anchor = rooms[n - 1]
            if rng:chance(60) then q = heading else q = rng:below(4) end
        else
            if rng:chance(50) then anchor = rooms[n - 1] else anchor = rooms[rng:below(spine_n)] end
            q = rng:below(4)
        end
        stall = stall + 1
        local gap = rng:between(arch.gap[1], arch.gap[2])
        local c0, r0
        if q == 0 or q == 2 then
            c0 = anchor.c0 + rng:between(-(rw - 1), anchor.c1 - anchor.c0)
            if q == 0 then r0 = anchor.r0 - gap - rh else r0 = anchor.r1 + gap + 1 end
        else
            r0 = anchor.r0 + rng:between(-(rh - 1), anchor.r1 - anchor.r0)
            if q == 1 then c0 = anchor.c0 - gap - rw else c0 = anchor.c1 + gap + 1 end
        end
        local clash = not (c0 >= 2 and c0 + rw - 1 <= w - 3 and r0 >= 2 and r0 + rh - 1 <= h - 3)
        local room = room_new(c0, r0, c0 + rw - 1, r0 + rh - 1)
        if not clash then for i = 0, n - 1 do if touches(room, rooms[i]) then clash = true break end end end
        if not clash then
            big_done = true
            stall = 0
            room.style = rng:chance(arch.style) and 0x11 or 0
            if stamp then
                local k = rw // stamp[1]
                local mask = {}
                for _, cell in ipairs(stamp[3]) do
                    for i = 0, k - 1 do for j = 0, k - 1 do mask[(c0 + cell[1] * k + i) * 1000 + (r0 + cell[2] * k + j)] = true end end
                end
                local cc, cr = centre(room)
                if mask[cc * 1000 + cr] then
                    local cut = {}
                    for r = room.r0, room.r1 do for c = room.c0, room.c1 do if not mask[c * 1000 + r] then cut[c * 1000 + r] = true end end end
                    room.cut = cut
                end
            elseif rw >= 4 and rh >= 4 and rng:chance(35) then room.cut = room_cut(rng, room) end
            rooms[n] = room
            n = n + 1
        end
    end
    local start = rooms[0]
    local stc, str_ = centre(start)
    -- the exit: farthest first, the next farthest when no boss room fits (endless_gen EXIT_TRIES)
    local keys = {}
    for i = 1, n - 1 do
        local cc, cr = centre(rooms[i])
        keys[#keys + 1] = (100000 - dist(cc, cr, stc, str_)) * 1000 + i
    end
    local order = stable_sort(keys, function(v) return v end)
    local tries = math.min(#order, 6)
    local boss, gate, far
    for k = 1, tries do
        far = order[k] % 1000
        local plain_exit = rooms[far]
        rooms[far].kind = "exit"
        if depth >= 2 then
            local extra = depth - 2
            if extra > MAX_DEPTH_MAZE - 2 then extra = MAX_DEPTH_MAZE - 2 end
            local m = 7 + 2 * extra
            local pc, pr
            for _ = 1, 200 do
                local c0 = rng:between(2, w - 3 - m)
                local r0 = rng:between(2, h - 3 - m)
                if rect_free(rooms, n, far, c0, r0, c0 + m - 1, r0 + m - 1) then pc, pr = c0, r0 break end
            end
            if pc then
                local corners = {{pc, pr}, {pc + m - 1, pr}, {pc, pr + m - 1}, {pc + m - 1, pr + m - 1}}
                local entry, best_d = corners[1], dist(corners[1][1], corners[1][2], stc, str_)
                for k = 2, 4 do
                    local d = dist(corners[k][1], corners[k][2], stc, str_)
                    if d < best_d then best_d = d; entry = corners[k] end
                end
                local maze = room_new(pc, pr, pc + m - 1, pr + m - 1, "maze")
                maze.entry = {entry[1], entry[2]}
                maze.goal = {pc + m - 1 - (entry[1] - pc), pr + m - 1 - (entry[2] - pr)}
                rooms[far] = maze
            end
        end
        -- the boss room: touching the exit at its entry cell; the exit is then reachable only through it
        local exit_rect = rooms[far]
        local entry_cells = {}
        if exit_rect.kind == "maze" then entry_cells[1] = {exit_rect.entry[1], exit_rect.entry[2]}
        else
            for _, cell in ipairs(cells_of(exit_rect)) do
                if cell[1] == exit_rect.c0 or cell[1] == exit_rect.c1 or cell[2] == exit_rect.r0 or cell[2] == exit_rect.r1 then entry_cells[#entry_cells + 1] = cell end
            end
        end
        for attempt = 0, 239 do
            local e = rng:pick(entry_cells)
            local ec, er = e[1], e[2]
            local q = rng:below(4)
            local bc, br = ec + SIDE_DX[q], er + SIDE_DZ[q]
            local bw, bh
            if attempt < 120 then bw, bh = rng:between(4, 5), rng:between(4, 5) else bw, bh = rng:between(3, 4), rng:between(3, 4) end
            local c0, r0
            if SIDE_DZ[q] ~= 0 then c0 = bc - rng:below(bw) else c0 = (SIDE_DX[q] > 0) and bc or (bc - bw + 1) end
            if SIDE_DX[q] ~= 0 then r0 = br - rng:below(bh) else r0 = (SIDE_DZ[q] > 0) and br or (br - bh + 1) end
            local c1, r1 = c0 + bw - 1, r0 + bh - 1
            if c0 >= 2 and c1 <= w - 3 and r0 >= 2 and r1 <= h - 3 then
                local probe = room_new(c0, r0, c1, r1, "boss")
                local clash = touches(probe, exit_rect, 0)
                if not clash then
                    for i = 0, n - 1 do if i ~= far and touches(probe, rooms[i]) then clash = true break end end
                end
                if not clash then
                    boss = probe
                    gate = {bc, br, ec, er} -- boss side, exit side
                    break
                end
            end
        end
        if boss then break end
        if k < tries then
            plain_exit.kind = "room"
            rooms[far] = plain_exit
        end
    end
    local boss_index = -1
    if boss then rooms[n] = boss; boss_index = n; n = n + 1 end
    -- close quarters (endless_gen FILL_SHARE, FILL_SIZE, FILL_TRIES, FILL_MAX_ROOMS)
    local fill = math.min(n * 35 // 100, 75 - n)
    local placed, tries = 0, 0
    while placed < fill and tries < 400 do
        tries = tries + 1
        local rw, rh = rng:between(2, 3), rng:between(2, 3)
        local anchor = rooms[rng:below(n)]
        local q = rng:below(4)
        local c0, r0
        if q == 0 or q == 2 then
            c0 = anchor.c0 + rng:between(-(rw - 1), anchor.c1 - anchor.c0)
            if q == 0 then r0 = anchor.r0 - 1 - rh else r0 = anchor.r1 + 2 end
        else
            r0 = anchor.r0 + rng:between(-(rh - 1), anchor.r1 - anchor.r0)
            if q == 1 then c0 = anchor.c0 - 1 - rw else c0 = anchor.c1 + 2 end
        end
        if c0 >= 2 and c0 + rw - 1 <= w - 3 and r0 >= 2 and r0 + rh - 1 <= h - 3 then
            local room = room_new(c0, r0, c0 + rw - 1, r0 + rh - 1)
            local clash = false
            for i = 0, n - 1 do if touches(room, rooms[i]) then clash = true break end end
            if not clash then
                rooms[n] = room
                n = n + 1
                placed = placed + 1
            end
        end
    end
    local lay = Layout.new(w, h, rooms, n)
    lay.wander = (area * 40503 + 7) & 0xFFFF -- the corridor hash salt (endless_gen)
    for i = 0, n - 1 do
        local room = rooms[i]
        if room.kind ~= "maze" then
            for _, cell in ipairs(cells_of(room)) do lay.owner[cell[2] * w + cell[1]] = i end
        end
    end
    if rooms[far].kind == "maze" then carve_maze(lay, rng, rooms[far], far) end
    if boss then
        lay.doors[#lay.doors + 1] = {gate[1], gate[2], gate[3], gate[4]}
        lay.gate = gate
    end
    local leaf = boss and boss_index or far
    local linked = {0}
    local in_linked = {[0] = true}
    local edges = {}
    local tree_nodes = boss and (n - 1) or n
    while #linked < tree_nodes do
        local best_d, best_a, best_b = -1, 0, 0
        for _, a in ipairs(linked) do
            if a ~= leaf then
                local acc, acr = centre(rooms[a])
                for b = 0, n - 1 do
                    if not in_linked[b] and not (boss and b == far) then
                        local bcc, bcr = centre(rooms[b])
                        local d = dist(acc, acr, bcc, bcr)
                        if best_d < 0 or d < best_d then best_d, best_a, best_b = d, a, b end
                    end
                end
            end
        end
        edges[#edges + 1] = {best_a, best_b}
        linked[#linked + 1] = best_b
        in_linked[best_b] = true
    end
    -- loops between near rooms (endless_gen LOOP_BASE, LOOP_PER, LOOP_NEAREST)
    for _ = 1, n * (40 + 4 * arch.loops) // 100 do
        local a, k = rng:below(n), rng:below(3)
        if a ~= far and a ~= boss_index then
            local ac, ar = centre(rooms[a])
            local keys = {}
            for j = 0, n - 1 do
                local joined = false
                for _, e in ipairs(edges) do if (e[1] == a and e[2] == j) or (e[1] == j and e[2] == a) then joined = true break end end
                if j ~= a and j ~= far and j ~= boss_index and not joined then -- rooms it is not yet joined to
                    local jc, jr = centre(rooms[j])
                    keys[#keys + 1] = (math.abs(jc - ac) + math.abs(jr - ar)) * 1000 + j
                end
            end
            local near = stable_sort(keys, function(v) return v end)
            if k < #near then edges[#edges + 1] = {a, near[k + 1] % 1000} end
        end
    end
    for _, e in ipairs(edges) do checkpoint(); carve_corridor(lay, rooms[e[1]], rooms[e[2]]) end
    local keyed = rooms[leaf]
    local ex = rooms[far]
    local function is_gate(d)
        return boss and ((d[1] == gate[1] and d[2] == gate[2] and d[3] == gate[3] and d[4] == gate[4]) or (d[1] == gate[3] and d[2] == gate[4] and d[3] == gate[1] and d[4] == gate[2]))
    end
    local kept
    for _, d in ipairs(lay.doors) do
        if touches_exit(keyed, d) and not is_gate(d) and not kept then
            kept = contains(keyed, d[1], d[2]) and {d[1], d[2], d[3], d[4]} or {d[3], d[4], d[1], d[2]}
        end
    end
    local function same_as_kept(d)
        return kept and ((d[1] == kept[1] and d[2] == kept[2] and d[3] == kept[3] and d[4] == kept[4]) or (d[1] == kept[3] and d[2] == kept[4] and d[3] == kept[1] and d[4] == kept[2]))
    end
    local function prune()
        local out = {}
        for _, d in ipairs(lay.doors) do
            if is_gate(d) or same_as_kept(d) then out[#out + 1] = d
            elseif not touches_exit(ex, d) and not touches_exit(keyed, d) then out[#out + 1] = d end
        end
        lay.doors = out
    end
    prune()
    for _ = 1, 6 do
        local reach = reachable(lay, stc, str_)
        local missing = -1
        for i = 0, n - 1 do
            local cc, cr = centre(rooms[i])
            if not reach[cr * w + cc] and not (boss and i == far) then missing = i break end
        end
        if missing < 0 then break end
        local mc, mr = centre(rooms[missing])
        local near, near_d = -1, 0
        for j = 0, n - 1 do
            local cc, cr = centre(rooms[j])
            if reach[cr * w + cc] then
                local d = dist(cc, cr, mc, mr)
                if near < 0 or d < near_d then near, near_d = j, d end
            end
        end
        local before = #lay.doors
        carve_corridor(lay, rooms[near], rooms[missing])
        if not kept then
            for k = before + 1, #lay.doors do
                local d = lay.doors[k]
                if touches_exit(keyed, d) and not is_gate(d) then
                    kept = contains(keyed, d[1], d[2]) and {d[1], d[2], d[3], d[4]} or {d[3], d[4], d[1], d[2]}
                    break
                end
            end
        end
        prune()
    end
    lay.exit_door = kept
    -- secret passages: extra corridors between two ordinary rooms, both doorways get a secret door
    lay.secrets = {}
    local count = depth - 1
    if count < 0 then count = 0 end
    if count > 2 then count = 2 end
    local ordinary = {}
    for i = 0, n - 1 do if rooms[i].kind == "room" then ordinary[#ordinary + 1] = rooms[i] end end
    local used = {}
    local made = 0
    for _ = 1, count * 3 do
        if made >= count then break end
        local pairs_ = {}
        for _, a in ipairs(ordinary) do
            for _, b in ipairs(ordinary) do
                if a ~= b and not used[a] and not used[b] then
                    local ac, ar = centre(a)
                    local bc, br = centre(b)
                    if dist(ac, ar, bc, br) >= 6 then pairs_[#pairs_ + 1] = {a, b} end
                end
            end
        end
        if #pairs_ == 0 then break end
        local pick = rng:pick(pairs_)
        local a, b = pick[1], pick[2]
        local before = #lay.doors
        carve_corridor(lay, a, b)
        local ends = {}
        for k = before + 1, #lay.doors do
            local d = lay.doors[k]
            if touches_exit(a, d) or touches_exit(b, d) then ends[#ends + 1] = d end
        end
        if #ends >= 2 then
            used[a] = true; used[b] = true
            made = made + 1
            for k = 1, 2 do
                local d = ends[k]
                local room = touches_exit(a, d) and a or b
                local ic, ir, oc, orr
                if contains(room, d[1], d[2]) then ic, ir, oc, orr = d[1], d[2], d[3], d[4] else ic, ir, oc, orr = d[3], d[4], d[1], d[2] end
                lay.secrets[#lay.secrets + 1] = {ic, ir, oc, orr, room}
            end
        end
    end
    -- monster closets: a 2x2 room off a corridor cell, shut by a plate-opened portcullis
    lay.closets = {}
    local closets = depth - 1
    if closets < 0 then closets = 0 end
    if closets > 3 then closets = 3 end
    for _ = 1, closets do
        for _attempt = 1, 60 do
            if #lay.corridor == 0 then break end
            local cell = rng:pick(lay.corridor)
            local cc, cr = cell[1], cell[2]
            local q = rng:below(4)
            local dx, dz = SIDE_DX[q], SIDE_DZ[q]
            local oc, orr = cc + dx, cr + dz
            local c0 = dx >= 0 and oc or oc - 1
            local r0 = dz >= 0 and orr or orr - 1
            if dx ~= 0 then r0 = orr - rng:below(2) else c0 = oc - rng:below(2) end
            local room = room_new(c0, r0, c0 + 1, r0 + 1, "closet")
            if c0 >= 2 and c0 + 1 <= lay.w - 3 and r0 >= 2 and r0 + 1 <= lay.h - 3 then
                local bad = false
                for _, rc in ipairs(cells_of(room)) do if lay:built(rc[1], rc[2]) then bad = true end end
                if not bad then
                    for i = 0, lay.nrooms - 1 do
                        local o = lay.rooms[i]
                        if touches(room, o, 0) then bad = true end
                        if o.kind ~= "room" and o.kind ~= "closet" and touches(room, o) then bad = true end
                    end
                end
                if not bad then
                    local index = lay.nrooms
                    lay.rooms[index] = room
                    lay.nrooms = index + 1
                    for _, rc in ipairs(cells_of(room)) do lay.owner[rc[2] * lay.w + rc[1]] = index end
                    lay.doors[#lay.doors + 1] = {oc, orr, cc, cr}
                    lay.closets[#lay.closets + 1] = {oc, orr, cc, cr, room}
                    break
                end
            end
        end
    end
    -- the boss pen (endless_gen._boss_pen, PEN_CHANCE)
    local boss_rm = lay:boss_room()
    if boss_rm and rng:chance(40) then
        local edge = {}
        for _, cell in ipairs(cells_of(boss_rm)) do
            for q = 0, 3 do
                if not contains(boss_rm, cell[1] + SIDE_DX[q], cell[2] + SIDE_DZ[q]) then edge[#edge + 1] = {cell[1], cell[2], q} end
            end
        end
        for _attempt = 1, 30 do
            local e = rng:pick(edge)
            local c, r, q = e[1], e[2], e[3]
            local dx, dz = SIDE_DX[q], SIDE_DZ[q]
            local oc, orr = c + dx, r + dz
            local c0 = dx >= 0 and oc or oc - 1
            local r0 = dz >= 0 and orr or orr - 1
            if dx ~= 0 then r0 = orr - rng:below(2) else c0 = oc - rng:below(2) end
            local room = room_new(c0, r0, c0 + 1, r0 + 1, "pen")
            if c0 >= 2 and c0 + 1 <= lay.w - 3 and r0 >= 2 and r0 + 1 <= lay.h - 3 then
                local bad = false
                for _, rc in ipairs(cells_of(room)) do if lay:built(rc[1], rc[2]) then bad = true end end
                if not bad then
                    for i = 0, lay.nrooms - 1 do
                        local o = lay.rooms[i]
                        if o ~= boss_rm then
                            if touches(room, o, 0) then bad = true end
                            if o.kind ~= "room" and o.kind ~= "closet" and touches(room, o) then bad = true end
                        end
                    end
                end
                if not bad then
                    local index = lay.nrooms
                    lay.rooms[index] = room
                    lay.nrooms = index + 1
                    for _, rc in ipairs(cells_of(room)) do lay.owner[rc[2] * lay.w + rc[1]] = index end
                    lay.doors[#lay.doors + 1] = {oc, orr, c, r}
                    lay.pen = {oc, orr, c, r, room}
                    break
                end
            end
        end
    end
    -- maze gates: portcullises across the entry-to-goal path, each opened by a lever in a dead end
    -- reachable from the entry with that gate and the later ones shut
    lay.maze_gates = {}
    local gcount = depth - 2
    if gcount < 0 then gcount = 0 end
    if gcount > 3 then gcount = 3 end
    local mz = lay:exit_room()
    if gcount > 0 and mz.kind == "maze" then
        local parent = {}
        local key0 = mz.entry[2] * w + mz.entry[1]
        parent[key0] = false
        local queue = {{mz.entry[1], mz.entry[2]}}
        local head = 1
        while head <= #queue do
            local c, r = queue[head][1], queue[head][2]
            head = head + 1
            for q = 0, 3 do
                local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
                local nk = nr * w + nc
                if parent[nk] == nil and contains(mz, nc, nr) and lay:built(nc, nr) then
                    parent[nk] = {c, r}
                    queue[#queue + 1] = {nc, nr}
                end
            end
        end
        local gk = mz.goal[2] * w + mz.goal[1]
        if parent[gk] ~= nil then
            local path = {}
            local cell = {mz.goal[1], mz.goal[2]}
            while cell do
                path[#path + 1] = cell
                cell = parent[cell[2] * w + cell[1]] or nil
                if cell == false then cell = nil end
            end
            -- gates are placed from the entry outward, so the path must run entry .. goal
            local rev = {}
            for i = #path, 1, -1 do rev[#rev + 1] = path[i] end
            path = rev
            local on_path = {}
            for _, pc in ipairs(path) do on_path[pc[2] * w + pc[1]] = true end
            local passages = {}
            for i = 2, #path - 2 do -- python indices 2..len-2 (0-based) -> lua 3..#path-1; the cell at python index i is path[i+1]
                local pc = path[i + 1]
                if (pc[1] - mz.c0) % 2 == 1 or (pc[2] - mz.r0) % 2 == 1 then passages[#passages + 1] = i end
            end
            if #passages < gcount then gcount = #passages end
            local picked = {}
            for _ = 1, gcount do picked[#picked + 1] = rng:pick(passages) end
            picked = stable_sort(picked, function(v) return v end)
            local chosen = {}
            for _, v in ipairs(picked) do if chosen[#chosen] ~= v then chosen[#chosen + 1] = v end end
            local gates = {}
            for gi, i in ipairs(chosen) do
                local gate_cell = path[i + 1]
                local nxt = path[i + 2]
                local q = 0
                for kk = 0, 3 do if nxt[1] - gate_cell[1] == SIDE_DX[kk] and nxt[2] - gate_cell[2] == SIDE_DZ[kk] then q = kk end end
                local blocked = {}
                for j = gi, #chosen do local bc = path[chosen[j] + 1] blocked[bc[2] * w + bc[1]] = true end
                local seen = {[key0] = true}
                local order = {{mz.entry[1], mz.entry[2]}}
                local h2 = 1
                while h2 <= #order do
                    local c, r = order[h2][1], order[h2][2]
                    h2 = h2 + 1
                    for qq = 0, 3 do
                        local nc, nr = c + SIDE_DX[qq], r + SIDE_DZ[qq]
                        local nk = nr * w + nc
                        if not seen[nk] and not blocked[nk] and contains(mz, nc, nr) and lay:built(nc, nr) then
                            seen[nk] = true
                            order[#order + 1] = {nc, nr}
                        end
                    end
                end
                -- candidates sorted as python's sorted(tuples): by column, then row
                local candidates = {}
                for k2, _ in pairs(seen) do
                    local cc, cr = k2 % w, k2 // w
                    if not on_path[k2] and (cc - mz.c0) % 2 == 0 and (cr - mz.r0) % 2 == 0 then candidates[#candidates + 1] = {cc, cr} end
                end
                candidates = stable_sort(candidates, function(cell) return cell[1] * 10000 + cell[2] end)
                if #candidates > 0 then
                    local lever_cell = rng:pick(candidates)
                    local walls = {}
                    for wq = 0, 3 do if side_kind(lay, lever_cell[1], lever_cell[2], wq) == WALL then walls[#walls + 1] = wq end end
                    if #walls > 0 then gates[#gates + 1] = {gate_cell, q, lever_cell, rng:pick(walls)} end
                end
            end
            lay.maze_gates = gates
        end
    end
    -- the companion bypass: a corridor round the maze from the entry corner to the goal corner, a doorway
    -- at the entry and a portcullis at the goal end opened by a lever in the goal cell; only with a boss
    -- room (the keyed room must keep one doorway), routed clear of every existing corridor
    lay.bypass = nil
    lay.bypass_cells = {}
    if mz.kind == "maze" and lay:boss_room() then
        local blocked = {}
        for r = 0, h - 1 do for c = 0, w - 1 do if lay.owner[r * w + c] ~= -1 then blocked[r * w + c] = true end end end
        for r = mz.r0, mz.r1 do for c = mz.c0, mz.c1 do blocked[r * w + c] = true end end
        for _, cell in ipairs(lay.corridor) do
            for q = 0, 3 do blocked[(cell[2] + SIDE_DZ[q]) * w + cell[1] + SIDE_DX[q]] = true end
        end
        local function outside(cell)
            local out = {}
            local dirs = {{(cell[1] == mz.c0) and -1 or 1, 0}, {0, (cell[2] == mz.r0) and -1 or 1}}
            for _, d in ipairs(dirs) do
                local nc, nr = cell[1] + d[1], cell[2] + d[2]
                if nc >= 1 and nc < w - 1 and nr >= 1 and nr < h - 1 and not blocked[nr * w + nc] then out[#out + 1] = {nc, nr} end
            end
            return out
        end
        local e, g = mz.entry, mz.goal
        local done = false
        for _, s in ipairs(outside(e)) do
            if done then break end
            for _, tt in ipairs(outside(g)) do
                if done then break end
                blocked[s[2] * w + s[1]] = nil
                local path = route(lay, s[1], s[2], tt[1], tt[2], blocked)
                blocked[s[2] * w + s[1]] = true
                if #path > 0 then
                    for _, cell in ipairs(path) do lay.owner[cell[2] * w + cell[1]] = CORRIDOR end
                    lay.bypass_cells = path
                    lay.doors[#lay.doors + 1] = {e[1], e[2], s[1], s[2]}
                    lay.doors[#lay.doors + 1] = {g[1], g[2], tt[1], tt[2]}
                    local lq = 0
                    for q = 0, 3 do if tt[1] - g[1] == SIDE_DX[q] and tt[2] - g[2] == SIDE_DZ[q] then lq = q end end
                    local other = {{(g[1] == mz.c0) and -1 or 1, 0}, {0, (g[2] == mz.r0) and -1 or 1}}
                    local lever_q = 0
                    for _, d in ipairs(other) do
                        for q = 0, 3 do if d[1] == SIDE_DX[q] and d[2] == SIDE_DZ[q] and q ~= lq then lever_q = q end end
                    end
                    lay.bypass = {g[1], g[2], tt[1], tt[2], lever_q}
                    done = true
                end
            end
        end
    end
    -- dead-end corridors: 2..4 cells straight into unbuilt ground, clear of every room by a cell
    if #lay.corridor > 0 then
        for _ = 1, arch.spurs * 6 do
            if #lay.spur_ends >= arch.spurs then break end
            local from = rng:pick(lay.corridor)
            local q = rng:below(4)
            local length = rng:between(2, 4)
            local dx, dz = SIDE_DX[q], SIDE_DZ[q]
            local cells = {}
            for k = 1, length do
                local cc, rr = from[1] + dx * k, from[2] + dz * k
                if cc < 1 or cc >= w - 1 or rr < 1 or rr >= h - 1 or lay:at(cc, rr) ~= -1 then break end
                local near = false
                for ri = 0, lay.nrooms - 1 do
                    local rm = lay.rooms[ri]
                    if cc >= rm.c0 - 1 and cc <= rm.c1 + 1 and rr >= rm.r0 - 1 and rr <= rm.r1 + 1 then near = true break end
                end
                if near then break end
                cells[#cells + 1] = {cc, rr}
            end
            if #cells >= 2 then
                for _, cell in ipairs(cells) do
                    lay.owner[cell[2] * lay.w + cell[1]] = CORRIDOR
                    lay.corridor[#lay.corridor + 1] = cell
                end
                lay.spur_ends[#lay.spur_ends + 1] = cells[#cells]
            end
        end
    end
    if plain then segment_corridors(lay) return lay end -- the backrooms: no treasury, no wing gate
    treasury(lay, rng)
    if block_ok then block_doors(lay, rng, depth) end
    wing_gate(lay)
    segment_corridors(lay)
    return lay
end

-- ---------------------------------------------------------------- grid encoding
side_kind = function(lay, c, r, q)
    local w, h, owner = lay.w, lay.h, lay.owner
    local oc, orr = c + SIDE_DX[q], r + SIDE_DZ[q]
    local me = (c >= 0 and c < w and r >= 0 and r < h) and owner[r * w + c] or -1
    local other = (oc >= 0 and oc < w and orr >= 0 and orr < h) and owner[orr * w + oc] or -1
    if other < 0 then return WALL end
    if me == other then -- open, except where a corridor is cut into sectors (segment_corridors)
        if me == CORRIDOR and lay:is_door(c, r, oc, orr) then return DOOR end
        return 0
    end
    return lay:is_door(c, r, oc, orr) and DOOR or WALL
end
local function corner_kind(lay, c, r, q, sides)
    local q2 = (q + 1) % 4
    local e1, e2 = sides[q] ~= 0, sides[q2] ~= 0
    if e1 and e2 then return 3 end
    if e1 then return 1 end
    if e2 then return 2 end
    local n1c, n1r = c + SIDE_DX[q], r + SIDE_DZ[q]
    local n2c, n2r = c + SIDE_DX[q2], r + SIDE_DZ[q2]
    local dc, dr = c + SIDE_DX[q] + SIDE_DX[q2], r + SIDE_DZ[q] + SIDE_DZ[q2]
    local w1 = lay:built(n1c, n1r) and side_kind(lay, n1c, n1r, q2) ~= 0
    local w2 = lay:built(n2c, n2r) and side_kind(lay, n2c, n2r, q) ~= 0
    local wd = lay:built(dc, dr) and (side_kind(lay, dc, dr, (q + 2) % 4) ~= 0 or side_kind(lay, dc, dr, (q + 3) % 4) ~= 0)
    return (w1 or w2 or wd) and 4 or 0
end
local function encode_cell(lay, c, r)
    if r == 0 or r == lay.h - 1 or c == 0 or c == lay.w - 1 then
        local word = 0
        if r == 0 then word = word | BORDER_TOP end
        if r == lay.h - 1 then word = word | BORDER_BOTTOM end
        if c == 0 then word = word | BORDER_LEFT end
        if c == lay.w - 1 then word = word | BORDER_RIGHT end
        return word, 0
    end
    if not lay:built(c, r) then
        -- rock only beside built cells, as the shipped levels do; the rest of the grid stays empty
        for dx = -1, 1 do for dz = -1, 1 do
            if (dx ~= 0 or dz ~= 0) and lay:built(c + dx, r + dz) then return ROCK, 0 end
        end end
        return 0, 0
    end
    local sides = {}
    for q = 0, 3 do sides[q] = side_kind(lay, c, r, q) end
    local word = BUILT
    for q = 0, 3 do word = word | (sides[q] << (4 * q)) | (corner_kind(lay, c, r, q, sides) << (16 + 4 * q)) end
    local o = lay:at(c, r)
    local style = (o >= 0 and o < lay.nrooms) and lay.rooms[o].style or 0
    return word, style
end

-- ---------------------------------------------------------------- template
local function chunks(s, from, to)
    local out, p = {}, from
    while p + 8 <= to + 1 do
        local t, n = sunpack("<I4I4", s, p)
        out[#out + 1] = {tag = t, data = s:sub(p + 8, p + 7 + n)}
        p = p + 8 + n
    end
    return out
end
local function chunk(t, payload) return spack("<I4I4", t, #payload) .. payload end
-- the talk spots in template order (zone ids 20..28); the key and vault spots are placed later
local SPOT_INDEX = {["Boss Door"] = 0, Gate = 1, Stairs = 2, Depth = 3, Key = 4, Vault = 5, Closet = 6, Arrive = 7, Boss = 8}

-- the talk zone placed at a spot: the first companion in the spot's order who is present
-- (present: set of companion indices, nil = all), else the first in the order; without an
-- order all of the spot's zones (as the Python reference does)
local function talk_zone_ids(t, spot_index, per_spot, present)
    local order = t.spot_order[spot_index]
    if not order or #order == 0 then
        local out = {}
        for k = 1, per_spot do out[#out + 1] = t.talk_zone_ids[spot_index * per_spot + k] end
        return out
    end
    local pick = order[1]
    for _, i in ipairs(order) do
        if present == nil or present[i] then pick = i break end
    end
    return {t.talk_zone_ids[spot_index * per_spot + pick + 1]}
end

local function ints(text)
    local out = {}
    for v in (text or ""):gmatch("[^,]+") do out[#out + 1] = tonumber(v) end
    return out
end

-- template bytes + ini text -> template table (nil, reason on a shape mismatch)
function gen.load_template(data, ini)
    if #data < 4 or sunpack("<I4", data, 1) ~= MAGIC then return nil, "not a level" end
    local keys = {}
    for line in ini:gmatch("[^\r\n]+") do
        local k, v = line:match("^([^=%[]+)=(.*)$")
        if k then keys[k:gsub("%s+$", "")] = v:gsub("^%s+", ""):gsub("%s+$", "") end
    end
    local top = {}
    for _, c in ipairs(chunks(data, 5, #data)) do top[c.tag] = c.data end
    local g = top[TAG_GRID]
    if not (g and top[TAG_NODES] and top[TAG_OBJECTS] and top[TAG_ITEMS] and top[TAG_PEOPLE] and top[TAG_ENV]) then return nil, "a level chunk is missing" end
    local nw = sunpack("<I4", g, 1)
    local p = 4 + 16 * nw
    local nf = sunpack("<I4", g, p + 1)
    p = p + 4 + 16 * nf
    local t = {grid_names = g:sub(1, p)}
    for _, c in ipairs(chunks(top[TAG_NODES], 5, #top[TAG_NODES])) do
        if c.tag == TAG_LIGHT and #c.data == 160 then t.light = chunk(c.tag, c.data) break end
    end
    if not t.light then return nil, "no light node" end
    local prop_names = {}
    for nm in (keys.props or ""):gmatch("[^;]+") do prop_names[#prop_names + 1] = nm end
    local objects = chunks(top[TAG_OBJECTS], 5, #top[TAG_OBJECTS])
    if #prop_names == 0 or #objects < #prop_names + 1 then return nil, "object list does not match the ini props" end
    t.props = {}
    for i = 1, #prop_names do t.props[i] = chunk(objects[i].tag, objects[i].data) end
    t.prop_names = prop_names
    t.stairs = chunk(objects[#prop_names + 1].tag, objects[#prop_names + 1].data) -- then an unused plate decoration
    t.wall_props, t.debris = {}, {}
    local base = #prop_names + 2
    local i = 0
    for nm in (keys.wall_props or ""):gmatch("[^;]+") do
        i = i + 1
        t.wall_props[i] = {nm, chunk(objects[base + i].tag, objects[base + i].data)}
    end
    local nwall = i
    i = 0
    for nm in (keys.debris or ""):gmatch("[^;]+") do
        i = i + 1
        t.debris[i] = {nm, chunk(objects[base + nwall + i].tag, objects[base + nwall + i].data)}
    end
    t.pillar_name = keys.pillar
    if keys.pillar and keys.pillar ~= "" then
        local o = objects[base + nwall + i + 1]
        t.pillar = chunk(o.tag, o.data)
    end
    local parts = {}
    for _, c in ipairs(chunks(top[TAG_ITEMS], 1, #top[TAG_ITEMS])) do parts[c.tag] = c.data end
    if not (parts[TAG_ITEM_DB] and parts[TAG_ITEM_STRINGS] and parts[TAG_ITEM_PLACES]) then return nil, "items parts missing" end
    local places = chunks(parts[TAG_ITEM_PLACES], 5, #parts[TAG_ITEM_PLACES])
    if #places < 10 then return nil, "need ten placements" end
    t.marker_place = chunk(places[1].tag, places[1].data)
    t.chest_place = chunk(places[2].tag, places[2].data)
    t.door_place = chunk(places[3].tag, places[3].data)
    t.key_place = chunk(places[4].tag, places[4].data)
    t.fire_place = chunk(places[5].tag, places[5].data)
    t.lever_place = chunk(places[6].tag, places[6].data)
    t.gate_place = chunk(places[7].tag, places[7].data)
    t.secret_door_place = chunk(places[8].tag, places[8].data)
    t.switch_place = chunk(places[9].tag, places[9].data)
    t.plate_place = chunk(places[10].tag, places[10].data)
    t.item_db = chunk(TAG_ITEM_DB, parts[TAG_ITEM_DB])
    t.item_strings = chunk(TAG_ITEM_STRINGS, parts[TAG_ITEM_STRINGS])
    for _, c in ipairs(chunks(top[TAG_PEOPLE], 5, #top[TAG_PEOPLE])) do
        if c.tag == TAG_PEOPLE_DB then t.people_db = chunk(c.tag, c.data) break end
    end
    if not t.people_db then return nil, "no character list" end
    t.env = top[TAG_ENV]
    t.arrival_id = tonumber(keys.arrival)
    t.zone_id = tonumber(keys.zone)
    t.chest_ids, t.key_ids, t.door_ids, t.key_chest_ids = ints(keys.chests), ints(keys.keys), ints(keys.doors), ints(keys.key_chests)
    t.fire_ids, t.lever_ids, t.hazard_ids, t.fire_zone_ids = ints(keys.fires), ints(keys.levers), ints(keys.hazards), ints(keys.fire_zones)
    t.talk_zone_ids = ints(keys.talk_zones)
    t.pair_zone_ids = ints(keys.pair_zones)
    t.gate_ids, t.gate_lever_ids = ints(keys.gates), ints(keys.gate_levers)
    t.secret_door_ids, t.switch_ids = ints(keys.secret_doors), ints(keys.switches)
    t.plate_fire_ids, t.plate_closet_ids, t.closet_gate_ids = ints(keys.plate_fires), ints(keys.plate_closets), ints(keys.closet_gates)
    t.maze_gate_ids, t.maze_lever_ids = ints(keys.maze_gates), ints(keys.maze_levers)
    t.bypass_gate_id, t.bypass_lever_id = tonumber(keys.bypass_gate) or 0, tonumber(keys.bypass_lever) or 0
    t.puzzle_gate_id, t.puzzle_plate_id = tonumber(keys.puzzle_gate) or 0, tonumber(keys.puzzle_plate) or 0
    t.puzzle_lever_ids = {}
    for v in (keys.puzzle_levers or ""):gmatch("[^,]+") do t.puzzle_lever_ids[#t.puzzle_lever_ids + 1] = tonumber(v) end
    t.wall_zone_id = tonumber(keys.wall_zone) or 0 -- the backrooms trigger
    t.enemy_ids = ints(keys.enemies)
    t.enemy_tiers = {}
    for i = 2, 6 do if keys["enemies_t" .. i] then t.enemy_tiers[#t.enemy_tiers + 1] = ints(keys["enemies_t" .. i]) end end
    t.boss_tiers = {}
    for i = 1, 6 do if keys["bosses_t" .. i] then t.boss_tiers[#t.boss_tiers + 1] = ints(keys["bosses_t" .. i]) end end
    t.floor_y = tonumber(keys.floor_y)
    t.companion_ids = ints(keys.companions)
    t.companion_roles = ints(keys.companion_roles) -- each companion's main role id
    t.salve_id = tonumber(keys.salve) or 0 -- the Healing Salve item record
    t.prop_stages = {} -- prop name -> set of stages (1-based) whose vanilla levels place it
    for entry in (keys.prop_stages or ""):gmatch("[^;]+") do
        local nm, list = entry:match("^([^:]+):(.*)$")
        if nm then
            local set = {}
            for v in list:gmatch("[^,]+") do set[tonumber(v)] = true end
            t.prop_stages[nm] = set
        end
    end
    t.spot_order = {} -- talk spot index (0-based) -> companion indices (0-based) in speaking order
    for entry in (keys.spot_order or ""):gmatch("[^;]+") do
        local spot, list = entry:match("^([^:]+):(.*)$")
        if spot then
            local idx = SPOT_INDEX[spot]
            if idx then t.spot_order[idx] = ints(list) end
        end
    end
    t.proctor_boss_id = tonumber(keys.proctor_boss) or 0
    t.sir_demon_id = tonumber(keys.sir_demon) or 0 -- the Archives' demon that roams the backrooms
    t.reveal = {} -- {{companion record id, {power ids}}} granted at that companion's trust reveal
    for entry in (keys.reveal_powers or ""):gmatch("[^;]+") do
        local cid, list = entry:match("^(%d+):(.*)$")
        if cid then
            local ids = {}
            for v in list:gmatch("[^,]+") do ids[#ids + 1] = tonumber(v) end
            t.reveal[#t.reveal + 1] = {tonumber(cid), ids}
        end
    end
    t.chest_tiers = {}
    for k = 2, 7 do if keys["chests_t" .. k] then t.chest_tiers[#t.chest_tiers + 1] = ints(keys["chests_t" .. k]) end end
    t.boss_bands, t.enemy_bands = {}, {}
    for k = 1, 6 do
        if keys["bosses_t" .. k .. "_b1"] then
            local bands = {}
            for b = 1, BANDS do bands[b] = ints(keys["bosses_t" .. k .. "_b" .. b]) end
            t.boss_bands[#t.boss_bands + 1] = bands
        end
        if keys["enemies_t" .. k .. "_b1"] then
            local bands = {}
            for b = 1, BANDS do bands[b] = ints(keys["enemies_t" .. k .. "_b" .. b]) end
            t.enemy_bands[#t.enemy_bands + 1] = bands
        end
    end
    t.stages = {} -- tile-set stages by depth: {walls = {...}, floors = {...}}
    for i = 1, 19 do
        local v = keys["stage" .. i]
        if not v then break end
        local walls, floors = v:match("^([^|]*)|(.*)$")
        local stage = {walls = {}, floors = {}}
        for nm in walls:gmatch("[^,]+") do stage.walls[#stage.walls + 1] = nm end
        for nm in floors:gmatch("[^,]+") do stage.floors[#stage.floors + 1] = nm end
        t.stages[#t.stages + 1] = stage
    end
    if not (t.arrival_id and t.zone_id and #t.chest_ids > 0 and #t.enemy_ids > 0 and #t.key_ids > 0 and #t.key_ids == #t.door_ids and #t.key_ids == #t.key_chest_ids and t.floor_y
            and #t.fire_ids > 0 and #t.fire_zone_ids == #t.fire_ids and #t.lever_ids == #t.key_ids and #t.hazard_ids == 4
            and #t.gate_ids == #t.key_ids and #t.gate_lever_ids == #t.key_ids and #t.boss_tiers > 0 and #t.boss_tiers[1] > 0
            and #t.secret_door_ids > 0 and #t.switch_ids == #t.secret_door_ids and #t.plate_fire_ids == #t.fire_ids
            and #t.closet_gate_ids > 0 and #t.plate_closet_ids == #t.closet_gate_ids
            and #t.maze_gate_ids > 0 and #t.maze_lever_ids == #t.maze_gate_ids) then return nil, "ini values missing" end
    local at = t.item_db:find("LuaEvent(EndlessNext,", 1, true)
    if not at or t.item_db:sub(at + 43, at + 43) ~= ";" then return nil, "template script missing" end
    t.script_at = at
    return t
end

-- ---------------------------------------------------------------- terrain
local TERRAIN_MAGIC, TERRAIN_TAG, TN, TSAMPLE, TTILE = 0x3EEFAD01, 0xBDAD, 244, 20.0, 4800.0

-- the 1 x 1 flat terrain (assets/endless-template.rft): its header and one tile's layers
function gen.load_terrain_template(t, data)
    if #data < 48 or sunpack("<I4", data, 1) ~= TERRAIN_MAGIC then return nil, "not a terrain" end
    local tag, size = sunpack("<I4I4", data, 41)
    if tag ~= TERRAIN_TAG then return nil, "terrain tile missing" end
    t.terrain_head = data:sub(1, 28)
    t.terrain_tile = data:sub(49, 48 + size)
    return true
end

-- 2 x 2 tiles of flat ground at floor level, as level 1's own terrain lies under its floors
-- the terrain (1.4 MB) is built apart from the level, after the level bytes are served and dropped:
-- the addon's Lua state has 8 MiB, and one table.concat over the parts makes the only big copy
function gen.build_terrain(t)
    checkpoint()
    if not t.terrain_tile then return "" end
    local flags = sunpack("<I4", t.terrain_tile, 1)
    local tag = sunpack("<I4", t.terrain_tile, 13)
    local heights = string.rep(spack("<f", 0.0), TN * TN)
    local layers = t.terrain_tile:sub(16 + 4 * TN * TN + 1)
    local body_size = 16 + #heights + #layers
    local parts = {t.terrain_head, spack("<i4i4I4", 2, 2, 4)}
    for iy = 0, 1 do for ix = 0, 1 do
        parts[#parts + 1] = spack("<I4I4", TERRAIN_TAG, body_size)
        parts[#parts + 1] = spack("<I4i4i4I4", flags, ix, iy, tag)
        parts[#parts + 1] = heights
        parts[#parts + 1] = layers
    end end
    return table.concat(parts)
end

-- ---------------------------------------------------------------- assembly
local function world(c, r, w, h, fx, fz)
    return (c - w / 2 + (fx or 0.5)) * CELL, (r - h / 2 + (fz or 0.5)) * CELL
end
local function yaw_matrix(degrees)
    local a = math.rad(degrees)
    local cs, sn = math.cos(a), math.sin(a)
    return spack("<fffffffff", cs, 0.0, sn, 0.0, 1.0, 0.0, -sn, 0.0, cs)
end
local function light(t, x, y, z, cr, cg, cb, strength, falloff, range)
    local v = t.light
    return v:sub(1, 8 + 68) .. spack("<fff", x, y, z) .. v:sub(8 + 80 + 1, 8 + 116) .. spack("<fff", cr, cg, cb) .. spack("<ffff", 1.0, strength, falloff, range) .. v:sub(8 + 144 + 1)
end
local function object(raw, x, y, z, yaw)
    return raw:sub(1, 8 + 20) .. yaw_matrix(yaw) .. spack("<fff", x, y, z) .. raw:sub(8 + 68 + 1)
end
local function placement(raw, item, x, y, z, yaw, state)
    return raw:sub(1, 8) .. spack("<I4I4", item, state or 0) .. raw:sub(8 + 8 + 1, 8 + 12) .. yaw_matrix(yaw) .. spack("<fff", x, y, z) .. raw:sub(8 + 60 + 1)
end
local function spawn(who, x, y, z, yaw) return chunk(TAG_SPAWN, spack("<I4ffffI4I4", who, x, y, z, yaw, 0, 0)) end
-- strength band of a depth: band k from depth 6k+1, so depth keeps biting after the last tier joined
local function band_of(depth)
    local band = (depth - 1) // 6
    if band > BANDS then band = BANDS end
    return band
end
local function enemy_roster(t, depth)
    local tiers = {t.enemy_ids}
    for _, tier in ipairs(t.enemy_tiers) do tiers[#tiers + 1] = tier end
    local top = depth < #tiers and depth or #tiers
    local band = band_of(depth)
    local out = {}
    for k = 1, top do
        local weight = (k == top) and 3 or (k == top - 1) and 2 or 1
        local ids = tiers[k]
        if band > 0 and k <= #t.enemy_bands and #t.enemy_bands[k][band] > 0 then ids = t.enemy_bands[k][band] end
        for _ = 1, weight do for _, id in ipairs(ids) do out[#out + 1] = id end end
    end
    return out
end
local function boss_roster(t, depth)
    local tiers = {}
    for _, tier in ipairs(t.boss_tiers) do if #tier > 0 then tiers[#tiers + 1] = tier end end
    if #tiers == 0 then return {} end
    local k = depth < #tiers and depth or #tiers
    local band = band_of(depth)
    if band > 0 and k <= #t.boss_bands and #t.boss_bands[k][band] > 0 then return t.boss_bands[k][band] end
    return tiers[k]
end
local function chest_roster(t, depth)
    local tiers = {t.chest_ids}
    for _, tier in ipairs(t.chest_tiers) do tiers[#tiers + 1] = tier end
    local top = depth < #tiers and depth or #tiers
    local out = {}
    for k = 1, top do
        if #tiers[k] > 0 then
            local weight = (k == top) and 3 or (k == top - 1) and 2 or 1
            for _ = 1, weight do for _, id in ipairs(tiers[k]) do out[#out + 1] = id end end
        end
    end
    if #out == 0 then return t.chest_ids end
    return out
end

-- the tile sets of an area: the first stage for depths 1-2, then one per depth, cycling past the last
-- the stage index (1-based) an area wears; the mod publishes it as LuaFlag endless_stage
function gen.stage_index(t, area)
    if #t.stages == 0 then return 0 end
    local depth = gen.depth_of(area)
    local i = depth <= 2 and 0 or depth - 2
    if i >= #t.stages then
        if #t.stages > 1 then i = 1 + (i - 1) % (#t.stages - 1) else i = 0 end
    end
    return i + 1
end

function gen.stage_of(t, area)
    local i = gen.stage_index(t, area)
    if i == 0 then return nil end
    return t.stages[i]
end
local function names_block(names)
    local out = {spack("<I4", #names)}
    for _, nm in ipairs(names) do
        local b = nm:sub(1, 16)
        out[#out + 1] = b .. string.rep("\0", 16 - #b)
    end
    return table.concat(out)
end

-- The area bytes for (seed, area). Mirrors endless_gen.build_floor step for step.
local function puzzle_parts(t, lay, rng, kind, start, ic, ir, oc, orr, w, h, d_rooms, stage_no)
    local shut = {[edge_key(w, ic, ir, oc, orr)] = true}
    for _, sd in ipairs(lay.secrets) do shut[edge_key(w, sd[1], sd[2], sd[3], sd[4])] = true end
    local sc0, sr0 = centre(start)
    local near = reach_shut(lay, sc0, sr0, shut)
    local dist = {[orr * w + oc] = 0}
    local order = {{oc, orr}}
    local i = 1
    while i <= #order do
        local c, r = order[i][1], order[i][2]
        i = i + 1
        for q = 0, 3 do
            local nc, nr = c + SIDE_DX[q], r + SIDE_DZ[q]
            local nk = nr * w + nc
            if near[nk] and dist[nk] == nil and side_kind(lay, c, r, q) ~= WALL and not is_blocked(lay, c, r, nc, nr) then
                dist[nk] = dist[r * w + c] + 1
                order[#order + 1] = {nc, nr}
            end
        end
    end
    local places, objects, info = {}, {}, {puzzle = kind, puzzle_gate = t.puzzle_gate_id}
    local function lever_at(c, r, q, lever_id)
        local x, z = world(c, r, w, h, 0.5 + 0.42 * SIDE_DX[q], 0.5 + 0.42 * SIDE_DZ[q])
        places[#places + 1] = placement(t.lever_place, 0x80000000 | lever_id, x, LEVER_Y, z, SIDE_YAW[(q + 2) % 4])
    end
    local function walls_of(c, r)
        local out = {}
        for q = 0, 3 do if side_kind(lay, c, r, q) == WALL then out[#out + 1] = q end end
        return out
    end
    local function d_of(cell) return dist[cell[2] * w + cell[1]] end
    if kind == "plate" or kind == "hold" then
        local lim = kind == "hold" and HOLD_DIST or PLATE_DIST
        local spots = {}
        for _, cell in ipairs(order) do local d = d_of(cell) if d >= lim[1] and d <= lim[2] then spots[#spots + 1] = cell end end
        if #spots == 0 then spots[1] = {oc, orr} end
        local pc = rng:pick(spots)
        local x, z = world(pc[1], pc[2], w, h)
        places[#places + 1] = placement(t.plate_place, 0x80000000 | t.puzzle_plate_id, x, t.floor_y, z, 0.0)
        info.puzzle_plate = {x, z}
        if kind == "plate" and d_rooms then
            local heavy = {}
            for _, name in ipairs(HEAVY) do
                local found
                for _, rm in ipairs(d_rooms) do
                    for _, rc in ipairs(rm[2]) do
                        for _, ob in ipairs(rc[2]) do
                            if not found and dress_name(ob[4]) == name and math.abs((sunpack("<f", ob[4], 8 + 20 + 16 + 1))) >= 0.7 then found = ob end
                        end
                    end
                end
                if found then heavy[#heavy + 1] = found end
            end
            local around = {}
            local dp = d_of(pc)
            for _, cell in ipairs(order) do
                if math.abs(d_of(cell) - dp) <= 1 and not (cell[1] == pc[1] and cell[2] == pc[2]) then around[#around + 1] = cell end
            end
            if #around == 0 then around[1] = pc end
            for _ = 1, (#heavy > 0 and 2 or 0) do
                local ob = rng:pick(heavy)
                local hc = rng:pick(around)
                local fx, fz = rng:unit() * 0.5 + 0.25, rng:unit() * 0.5 + 0.25
                local hx, hz = world(hc[1], hc[2], w, h, fx, fz)
                objects[#objects + 1] = ob[4]:sub(1, 8 + 20) .. yaw_matrix(rng:unit() * 360.0) .. spack("<fff", hx, t.floor_y + ob[2], hz) .. ob[4]:sub(8 + 68 + 1)
            end
        end
        return places, objects, info, pc
    end
    if kind == "order" then
        local rooms = {}
        for j = 0, lay.nrooms - 1 do
            local room = lay.rooms[j]
            if room.kind == "room" then
                local cc, cr = centre(room)
                if near[cr * w + cc] then rooms[#rooms + 1] = room end
            end
        end
        local clue
        for _, pr in ipairs(t.debris) do
            if not clue and CLUE[pr[1]] and themed(t, pr[1], stage_no) then clue = pr end
        end
        local chosen = {}
        local first = {oc, orr}
        for k = 0, 2 do
            local pool = {}
            for _, room in ipairs(rooms) do
                local taken = false
                for _, ch in ipairs(chosen) do if ch == room then taken = true end end
                if not taken then pool[#pool + 1] = room end
            end
            if #pool == 0 then pool = rooms end
            if #pool == 0 then break end
            local room = rng:pick(pool)
            chosen[#chosen + 1] = room
            local edge = {}
            for _, cell in ipairs(cells_of(room)) do
                for _, q in ipairs(walls_of(cell[1], cell[2])) do edge[#edge + 1] = {cell[1], cell[2], q} end
            end
            if #edge > 0 then
                local e = rng:pick(edge)
                local c, r, q = e[1], e[2], e[3]
                if k == 0 then first = {c, r} end
                lever_at(c, r, q, t.puzzle_lever_ids[k + 1])
                if clue then
                    local q1 = (q + 1) % 4
                    for j = 0, k do
                        local bx, bz = world(c, r, w, h, 0.5 + 0.3 * SIDE_DX[q] + 0.12 * (j - k / 2) * SIDE_DX[q1], 0.5 + 0.3 * SIDE_DZ[q] + 0.12 * (j - k / 2) * SIDE_DZ[q1])
                        objects[#objects + 1] = object(clue[2], bx, t.floor_y + DEBRIS[clue[1]], bz, rng:unit() * 360.0)
                    end
                end
            end
        end
        info.puzzle_levers = {t.puzzle_lever_ids[1], t.puzzle_lever_ids[2], t.puzzle_lever_ids[3]}
        return places, objects, info, first
    end
    -- timed: a lever some way back on the near side, and a second inside the boss room (the failsafe)
    local spots = {}
    for _, cell in ipairs(order) do
        local d = d_of(cell)
        if d >= TIMED_DIST[1] and d <= TIMED_DIST[2] and #walls_of(cell[1], cell[2]) > 0 then spots[#spots + 1] = cell end
    end
    if #spots == 0 then for _, cell in ipairs(order) do if #walls_of(cell[1], cell[2]) > 0 then spots[#spots + 1] = cell end end end
    if #spots == 0 then spots[1] = {oc, orr} end
    local lc = rng:pick(spots)
    local lq = walls_of(lc[1], lc[2])
    lever_at(lc[1], lc[2], #lq > 0 and rng:pick(lq) or 0, t.puzzle_lever_ids[1])
    local inner = walls_of(ic, ir)
    lever_at(ic, ir, inner[1] or 0, t.puzzle_lever_ids[2])
    info.puzzle_levers = {t.puzzle_lever_ids[1], t.puzzle_lever_ids[2]}
    info.puzzle_seconds = TIMED_BASE + TIMED_PER_CELL * (d_of(lc) or TIMED_DIST[1])
    local boss = lay:boss_room()
    if boss then
        local x0, z0 = world(boss.c0, boss.r0, w, h, 0.0, 0.0)
        local x1, z1 = world(boss.c1, boss.r1, w, h, 1.0, 1.0)
        info.puzzle_inside = {x0, z0, x1, z1}
    end
    return places, objects, info, lc
end

function gen.build(t, seed, area, present, met, opts)
    checkpoint()
    opts = opts or {}
    local w = GRID_BY_DEPTH[gen.depth_of(area)] or GRID_MAX
    local h = w
    local rng = Rng.new(seed, area)
    local stage = gen.stage_of(t, area)
    local two_sets = stage and #stage.walls >= 2 and #stage.floors >= 2
    local sc, sr = floor(START_X / CELL) + w // 2, floor(START_Z / CELL) + h // 2
    local depth0 = gen.depth_of(area)
    local arch_name = depth0 < 2 and "warren" or ARCH_ORDER[rng:below(#ARCH_ORDER) + 1]
    local mutator = "none"
    if depth0 >= 3 and rng:chance(30) then mutator = MUTATORS[rng:below(#MUTATORS) + 1] end
    local stage_no = gen.stage_index(t, area)
    local blockers, block_fill = {}, {}
    for i, raw in ipairs(t.props) do
        local nm = t.prop_names[i]
        if BLOCKERS[nm] and themed(t, nm, stage_no) then blockers[#blockers + 1] = raw end
        if BLOCK_FILL[nm] and themed(t, nm, stage_no) then block_fill[#block_fill + 1] = raw end
    end
    local lay = generate_layout(rng, w, h, area, sc, sr, arch_name, #blockers > 0, false, t.dress and t.dress[stage_no] and t.dress[stage_no].shapes or nil)
    checkpoint()
    assign_purposes(rng, lay, depth0)
    arrange_neighbours(lay) -- purposes to rooms by size and neighbours
    choose_sources(rng, lay, t.dress and t.dress[stage_no])
    arrange_neighbours(lay) -- again, where a stone's rooms moved a purpose
    pick_copy(rng, lay, t.dress and t.dress[stage_no], stage_no)
    pick_showpiece(rng, lay, t.dress and t.dress[stage_no])
    lay.archetype, lay.mutator = arch_name, mutator
    local pillars_ok = t.pillar ~= nil and themed(t, t.pillar_name, stage_no)
    -- pillared halls: an uncut ordinary room at least 4 cells a side, half the time
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" and room.cut == nil and room.purpose ~= "quiet" and room.c1 - room.c0 >= 3 and room.r1 - room.r0 >= 3 and pillars_ok then
            room.pillars = rng:chance(50)
        end
    end
    if not two_sets then for i = 0, lay.nrooms - 1 do lay.rooms[i].style = 0 end end
    local ex = lay:exit_room()
    local staircase = gen.is_staircase(area)
    local pair = (area - 1) % #t.key_ids + 1
    local depth = gen.depth_of(area)
    local exit_r, exit_g, exit_b = 0.5, 0.05, 0.05
    if staircase then exit_r, exit_g, exit_b = 0.3, 0.4, 0.6 end
    -- grid
    local cells, styles = {}, {}
    for r = 0, h - 1 do for c = 0, w - 1 do
        local word, style = encode_cell(lay, c, r)
        cells[#cells + 1] = word
        styles[#styles + 1] = style
    end end
    local layer0 = spack("<" .. string.rep("I4", #cells), table.unpack(cells))
    local layer2 = spack("<" .. string.rep("I4", #styles), table.unpack(styles))
    local names = stage and (names_block(stage.walls) .. names_block(stage.floors)) or t.grid_names
    local grid = names .. spack("<I4I4I4I4", w, h, 0, 600) .. layer0 .. string.rep("\0", 4 * w * h) .. layer2
    -- lights
    local nodes = {}
    local rc = STAGE_LIGHT[gen.stage_index(t, area)] or {0.55, 0.38, 0.2}
    local hc = {rc[1] * 0.65, rc[2] * 0.65, rc[3] * 0.65}
    local dark = mutator == "dark"
    local room_strength = dark and 0.45 or 1.0
    local every = dark and 12 or 6
    local room_lamp = {} -- ordinary room index -> its lamp's index in nodes (moved toward its furniture later)
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind ~= "maze" then
            local cc, cr = centre(room)
            local x, z = world(cc, cr, w, h)
            local span = math.max(room.c1 - room.c0, room.r1 - room.r0)
            local range = 600 + 150 * span
            if room.kind == "exit" then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, exit_r, exit_g, exit_b, 1.0, 2.0, range)
            elseif room.kind == "boss" then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.45, 0.15, 0.5, 1.0, 2.0, range)
            elseif room.purpose == "quiet" then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, QUIET_LIGHT[1], QUIET_LIGHT[2], QUIET_LIGHT[3], 1.3, 2.0, range)
            else
                local strength = room_strength
                if room.kind == "room" then
                    strength = strength * (USE_LIGHT[room.purpose] or 1.0)
                    room_lamp[i] = #nodes + 1
                end
                nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, rc[1], rc[2], rc[3], strength, 2.0, range)
            end
        end
    end
    for k = 1, #lay.corridor do
        if (k - 1) % every == 1 then
            local x, z = world(lay.corridor[k][1], lay.corridor[k][2], w, h)
            nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, hc[1], hc[2], hc[3], 0.7, 2.0, 600.0)
        end
    end
    for k = 1, #lay.bypass_cells do
        if (k - 1) % every == 1 then
            local x, z = world(lay.bypass_cells[k][1], lay.bypass_cells[k][2], w, h)
            nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, hc[1], hc[2], hc[3], 0.7, 2.0, 600.0)
        end
    end
    if ex.kind == "maze" then
        local k = 0
        for r = ex.r0, ex.r1, 2 do for c = ex.c0, ex.c1, 2 do
            if k % 3 == 0 then
                local x, z = world(c, r, w, h)
                if c == ex.goal[1] and r == ex.goal[2] then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, exit_r, exit_g, exit_b, 0.8, 2.0, 700.0)
                else nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.3, 0.2, 0.1, 0.8, 2.0, 700.0) end
            end
            k = k + 1
        end end
    end
    if gen.depth_of(area) == BLUE_DEPTH then -- easter egg 5: every lamp cold blue, whatever the stone
        for i = 1, #nodes do
            nodes[i] = nodes[i]:sub(1, 8 + 116) .. spack("<fff", BLUE_LIGHT[1], BLUE_LIGHT[2], BLUE_LIGHT[3]) .. nodes[i]:sub(8 + 128 + 1)
        end
    end
    local node_chunk = spack("<I4", #nodes) .. table.concat(nodes)
    -- dressing: whole cells of the game's own levels for this stone, turned to fit each cell's walls
    local objects = {}
    local dress_items = {} -- loose items of the dressed cells, placed with the other items below
    local info_eggs = {} -- the easter eggs this area carries
    local hall_pillar = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.pillars then
            for _, cell in ipairs({{room.c0 + 1, room.r0 + 1}, {room.c1 - 1, room.r0 + 1}, {room.c0 + 1, room.r1 - 1}, {room.c1 - 1, room.r1 - 1}}) do
                hall_pillar[cell[1] * 1000 + cell[2]] = true
            end
        end
    end
    local dress = t.dress and t.dress[stage_no]
    if dress then
        local d_classes, d_rooms, d_by_tag, d_tipped = dress.classes, dress.rooms, dress.by_tag, dress.tipped
        local function class_of(c, r)
            local m = 0
            for q = 0, 3 do if side_kind(lay, c, r, q) == WALL then m = m | (1 << q) end end
            for ci, cm in ipairs(DRESS_CLASSES) do
                for k = 0, 3 do if rot_mask(cm, k) == m then return ci, k end end
            end
            return nil
        end
        -- places a cell's objects turned k steps; returns the upright seats {object index, model}
        local function place(objs, c, r, k, clear)
            local seats = {}
            local cx, cz = world(c, r, w, h)
            local on_walk = clear and clear[c * 1000 + r]
            for _, ob in ipairs(objs) do
                local dx, dy, dz, raw = ob[1], ob[2], ob[3], ob[4]
                local m1, m2, m3, m4, m5, m6, m7, m8, m9 = sunpack("<fffffffff", raw, 8 + 20 + 1)
                for _ = 1, k do
                    dx, dz = dz, -dx
                    m1, m2, m3, m4, m5, m6, m7, m8, m9 = m3, m2, -m1, m6, m5, -m4, m9, m8, -m7
                end
                if on_walk and math.abs(dx) < WALK_CLEAR and math.abs(dz) < WALK_CLEAR then goto next_obj end
                if dy > HUNG_Y then
                    local d = {[0] = CELL / 2 + dz, CELL / 2 + dx, CELL / 2 - dz, CELL / 2 - dx}
                    local doorway, walled = false, false
                    for q = 0, 3 do
                        if d[q] < HUNG_NEAR then
                            local kind = side_kind(lay, c, r, q)
                            if kind == DOOR then doorway = true elseif kind == WALL then walled = true end
                        end
                    end
                    if doorway and not walled then goto next_obj end
                end
                local name = dress_name(raw)
                local low = name:lower()
                if (low:find("chair", 1, true) or low:find("stool", 1, true)) and not low:find("brok", 1, true) and math.abs(m5) >= 0.7 then
                    seats[#seats + 1] = {#objects + 1, name}
                end
                objects[#objects + 1] = raw:sub(1, 8 + 20) .. spack("<fffffffff", m1, m2, m3, m4, m5, m6, m7, m8, m9)
                    .. spack("<fff", cx + dx, t.floor_y + dy, cz + dz) .. raw:sub(8 + 68 + 1)
                ::next_obj::
            end
            return seats
        end
        local room_cells = 0
        for i = 0, lay.nrooms - 1 do if lay.rooms[i].kind == "room" then room_cells = room_cells + #cells_of(lay.rooms[i]) end end
        -- what a fight leaves: the stone's own debris (not remains, not decals)
        -- the stone's own floor decals, in dressing order (endless_gen d_decals)
        local d_decals = {}
        for _, rm in ipairs(d_rooms) do
            for _, rc in ipairs(rm[2]) do
                for _, ob in ipairs(rc[2]) do
                    if dress_name(ob[4]):sub(1, 5) == "decal" then d_decals[#d_decals + 1] = ob end
                end
            end
        end
        local function put_decal(c, r)
            local ob = rng:pick(d_decals)
            local fx, fz = rng:unit() * 0.4 + 0.3, rng:unit() * 0.4 + 0.3
            local x, z = world(c, r, w, h, fx, fz)
            local m = turn_rows({sunpack("<fffffffff", ob[4], 8 + 20 + 1)}, rng:unit() * 360.0)
            objects[#objects + 1] = ob[4]:sub(1, 8 + 20) .. spack("<fffffffff", m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9])
                .. spack("<fff", x, t.floor_y + ob[2], z) .. ob[4]:sub(8 + 68 + 1)
        end
        -- wall-hung pieces by (purpose tag, wall class), from the stone's own rooms (endless_gen d_hung)
        local d_hung, d_hung_any = {}, {}
        for _, rm in ipairs(d_rooms) do
            for _, rc in ipairs(rm[2]) do
                if rc[1] ~= 0 then
                    for _, ob in ipairs(rc[2]) do
                        if ob[2] > HUNG_Y then
                            local key = rm[1] * 16 + rc[1]
                            d_hung[key] = d_hung[key] or {}
                            d_hung[key][#d_hung[key] + 1] = ob
                            d_hung_any[rc[1]] = d_hung_any[rc[1]] or {}
                            d_hung_any[rc[1]][#d_hung_any[rc[1]] + 1] = ob
                        end
                    end
                end
            end
        end
        local fight_debris = {}
        for _, pr in ipairs(t.debris) do
            if pr[1] ~= REMAINS and DEBRIS[pr[1]] and pr[1]:sub(1, 5) ~= "decal" and themed(t, pr[1], stage_no) then fight_debris[#fight_debris + 1] = pr end
        end
        if room_cells == 0 then room_cells = 1 end
        local room_chance = math.max(DRESS_MIN_CHANCE, math.min(DRESS_ROOM_CHANCE, DRESS_ROOM_CHANCE * DRESS_FULL_CELLS // room_cells))
        if mutator == "collapsed" then room_chance = math.min(DRESS_COLLAPSED_CHANCE, room_chance + 25) end
        for i = 0, lay.nrooms - 1 do
            checkpoint()
            local room = lay.rooms[i]
            if room.kind == "room" then
                local src_index = room.src -- chosen with the purpose (choose_sources, arrange_neighbours)
                local src = (src_index and src_index > 0) and d_rooms[src_index] or nil
                local special = false
                if room.purpose == "quiet" and gen.depth_of(area) % CHAIR_DEPTHS == 0 then
                    -- easter egg 6: the quiet room holds one chair, by its north wall
                    special = true
                    local seat
                    for _, rm in ipairs(d_rooms) do
                        for _, rc in ipairs(rm[2]) do
                            for _, ob in ipairs(rc[2]) do
                                if not seat and dress_name(ob[4]):lower():find("chair", 1, true) and math.abs((sunpack("<f", ob[4], 8 + 20 + 16 + 1))) >= 0.7 then seat = ob end
                            end
                        end
                    end
                    if seat then
                        local cc = (room.c0 + room.c1) // 2
                        local x, z = world(cc, room.r0, w, h, 0.5, 0.3)
                        objects[#objects + 1] = seat[4]:sub(1, 8 + 56) .. spack("<fff", x, t.floor_y + seat[2], z) .. seat[4]:sub(8 + 68 + 1)
                    end
                elseif (room.copy or room.show) and src then
                    -- easter egg 4 and the showpiece: the source room exactly, cell for cell, each in its own
                    -- original turn; in the copy's corner a chair facing the wall (the backrooms' door)
                    special = true
                    local seat
                    for _, rm in ipairs(room.copy and d_rooms or {}) do
                        for _, rc in ipairs(rm[2]) do
                            for _, ob in ipairs(rc[2]) do
                                if not seat and dress_name(ob[4]):lower():find("chair", 1, true) and math.abs((sunpack("<f", ob[4], 8 + 20 + 16 + 1))) >= 0.7 then seat = ob end
                            end
                        end
                    end
                    if seat then
                        local m = turn_rows({sunpack("<fffffffff", seat[4], 8 + 20 + 1)}, 45.0)
                        local x, z = world(room.c0, room.r0, w, h, 0.38, 0.38)
                        objects[#objects + 1] = seat[4]:sub(1, 8 + 20) .. spack("<fffffffff", m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9])
                            .. spack("<fff", x, t.floor_y + seat[2], z) .. seat[4]:sub(8 + 68 + 1)
                    end
                    for j, cell in ipairs(cells_of(room)) do
                        local rc = src[2][j]
                        local c, r, ck = cell[1], cell[2], rc[4]
                        place(rc[2], c, r, ck)
                        local icx, icz = world(c, r, w, h)
                        for _, it in ipairs(rc[3]) do
                            local idx, idy, idz, iyaw = it[2], it[3], it[4], it[5]
                            for _ = 1, ck do
                                idx, idz = idz, -idx
                                iyaw = iyaw - 90.0
                            end
                            dress_items[#dress_items + 1] = placement(t.key_place, 0x80000000 | it[1], icx + idx, t.floor_y + idy, icz + idz, iyaw)
                        end
                    end
                end
              if not special then
                local seats = {}
                local used = {} -- each source cell once per room
                local clear = walkway(lay, room)
                local roll = rng:below(100)
                local event = roll < EVENT_FIGHT and "fight" or roll < EVENT_LOOTED and "looted" or roll < EVENT_HURRY and "hurry" or "tidy"
                for _, bd in ipairs(lay.blocked_doors or {}) do
                    if contains(room, bd[1], bd[2]) or contains(room, bd[3], bd[4]) then event = "fight" end -- the barricade was held
                end
                local chance = event == "looted" and room_chance // 2 or room_chance
                if room.purpose == "store" then
                    for j = 0, lay.nrooms - 1 do
                        local o = lay.rooms[j]
                        if o.kind == "room" and o.purpose == "kitchen" then
                            local gap = math.max(o.c0 - room.c1 - 1, room.c0 - o.c1 - 1, o.r0 - room.r1 - 1, room.r0 - o.r1 - 1)
                            if gap <= NEIGHBOUR_GAP then chance = 100 end -- the kitchen's stores, stacked high
                        end
                    end
                end
                local done = {} -- cells dressed by a group (endless_gen GROUP_CHANCE)
                local dressed = {} -- cells the cell-by-cell dressing filled
                if event ~= "looted" and src and src[3] >= 2 and src[4] >= 2 and #src[2] == src[3] * src[4] then
                    local inside = {}
                    for _, cell in ipairs(cells_of(room)) do inside[cell[1] * 1000 + cell[2]] = true end
                    local srw = src[3]
                    for _, cell in ipairs(cells_of(room)) do
                        local c, r = cell[1], cell[2]
                        local quad = {{c, r}, {c + 1, r}, {c, r + 1}, {c + 1, r + 1}}
                        local ok = #objects < OBJECT_CAP
                        for _, q in ipairs(quad) do
                            local key = q[1] * 1000 + q[2]
                            if done[key] or not inside[key] or hall_pillar[key] then ok = false end
                        end
                        if ok and rng:chance(GROUP_CHANCE) then
                            local want = {}
                            for n, q in ipairs(quad) do
                                local ci, k = class_of(q[1], q[2])
                                if not ci then ok = false break end
                                want[n] = {ci - 1, k}
                            end
                            if ok then
                                local blocks = {}
                                for j = 0, src[4] - 2 do
                                    for i = 0, srw - 2 do
                                        local idx = {j * srw + i, j * srw + i + 1, (j + 1) * srw + i, (j + 1) * srw + i + 1}
                                        local fits, nobj = true, 0
                                        for n, x in ipairs(idx) do
                                            local rc = src[2][x + 1]
                                            if rc[1] ~= want[n][1] or rc[4] ~= want[n][2] or used[src_index * 100000 + x + 1] then fits = false break end
                                            nobj = nobj + #rc[2]
                                        end
                                        if fits and nobj >= 2 then blocks[#blocks + 1] = idx end
                                    end
                                end
                                if #blocks > 0 then
                                    local idx = rng:pick(blocks)
                                    for n, q in ipairs(quad) do
                                        local rc = src[2][idx[n] + 1]
                                        local ck = rc[4]
                                        used[src_index * 100000 + idx[n] + 1] = true
                                        done[q[1] * 1000 + q[2]] = true
                                        for _, st in ipairs(place(rc[2], q[1], q[2], ck, clear)) do seats[#seats + 1] = st end
                                        local icx, icz = world(q[1], q[2], w, h)
                                        for _, it in ipairs(rc[3]) do
                                            if #dress_items >= ITEM_CAP then break end
                                            local ix, iy, iz, iyaw = it[2], it[3], it[4], it[5]
                                            for _ = 1, ck do
                                                ix, iz = iz, -ix
                                                iyaw = iyaw - 90.0
                                            end
                                            dress_items[#dress_items + 1] = placement(t.key_place, 0x80000000 | it[1], icx + ix, t.floor_y + iy, icz + iz, iyaw)
                                        end
                                    end
                                end
                            end
                        end
                    end
                end
                for _, cell in ipairs(cells_of(room)) do
                    local c, r = cell[1], cell[2]
                    if not done[c * 1000 + r] and not hall_pillar[c * 1000 + r] and rng:chance(chance) and #objects < OBJECT_CAP then
                        local ci, k = class_of(c, r)
                        if ci then
                            local objs
                            local skip = false
                            if src then
                                local cand = {}
                                for j, rc in ipairs(src[2]) do
                                    local key = src_index * 100000 + j
                                    if rc[1] == ci - 1 and not used[key] then cand[#cand + 1] = {key, rc[2], rc[3]} end
                                end
                                if #cand == 0 then
                                    for _, ri in ipairs(d_by_tag[src[1]] or {}) do
                                        for j, rc in ipairs(d_rooms[ri][2]) do
                                            local key = ri * 100000 + j
                                            if rc[1] == ci - 1 and not used[key] then cand[#cand + 1] = {key, rc[2], rc[3]} end
                                        end
                                    end
                                end
                                if #cand == 0 then -- every fitting cell of its purpose used once: they repeat (endless_gen)
                                    local from = {src_index}
                                    for _, ri in ipairs(d_by_tag[src[1]] or {}) do from[#from + 1] = ri end
                                    for _, ri in ipairs(from) do
                                        for j, rc in ipairs(d_rooms[ri][2]) do
                                            if rc[1] == ci - 1 then cand[#cand + 1] = {ri * 100000 + j, rc[2], rc[3]} end
                                        end
                                    end
                                end
                                if #cand == 0 then
                                    skip = true
                                else
                                    local pick = rng:pick(cand)
                                    used[pick[1]] = true
                                    objs = pick[2]
                                    -- the cell's loose items (cups, books...) as they lay, turned with the cell
                                    local icx, icz = world(c, r, w, h)
                                    for _, it in ipairs(pick[3]) do
                                        if #dress_items >= ITEM_CAP then break end
                                        local idx, idy, idz, iyaw = it[2], it[3], it[4], it[5]
                                        for _ = 1, k do
                                            idx, idz = idz, -idx
                                            iyaw = iyaw - 90.0
                                        end
                                        dress_items[#dress_items + 1] = placement(t.key_place, 0x80000000 | it[1], icx + idx, t.floor_y + idy, icz + idz, iyaw)
                                    end
                                end
                            end
                            if not objs and not skip then
                                local pool = d_classes[ci]
                                if pool and #pool > 0 then objs = rng:pick(pool) end
                            end
                            if objs then
                                for _, st in ipairs(place(objs, c, r, k, clear)) do seats[#seats + 1] = st end
                                dressed[c * 1000 + r] = true
                            end
                        end
                    end
                end
                -- wall dressing by purpose on the walled cells left bare (endless_gen WALL_DRESS_CHANCE)
                if src then
                    for _, cell in ipairs(cells_of(room)) do
                        local c, r = cell[1], cell[2]
                        local key = c * 1000 + r
                        if not done[key] and not dressed[key] and not hall_pillar[key] and #objects < OBJECT_CAP then
                            local ci, k = class_of(c, r)
                            if ci and ci - 1 ~= 0 then
                                local pool = d_hung[src[1] * 16 + (ci - 1)]
                                if pool and #pool > 0 and rng:chance(WALL_DRESS_CHANCE) then
                                    place({rng:pick(pool)}, c, r, k)
                                end
                            end
                        end
                    end
                end
                -- floor decals by use: worn walkways, a fight's marks, a kitchen's spills
                if #d_decals > 0 then
                    local rcells = cells_of(room)
                    for _, cell in ipairs(rcells) do
                        if #objects >= OBJECT_CAP then break end
                        if clear[cell[1] * 1000 + cell[2]] and rng:chance(WALK_DECAL_CHANCE) then put_decal(cell[1], cell[2]) end
                    end
                    local extra = event == "fight" and DECAL_FIGHT or (room.purpose == "kitchen" and DECAL_KITCHEN or 0)
                    for _ = 1, extra do
                        if #objects >= OBJECT_CAP then break end
                        local cell = rng:pick(rcells)
                        put_decal(cell[1], cell[2])
                    end
                    -- a fight's trail down the corridor from its first doorway
                    if event == "fight" then
                        local door
                        for _, d in ipairs(lay.doors) do
                            if contains(room, d[1], d[2]) and lay:at(d[3], d[4]) == CORRIDOR then door = {d[1], d[2], d[3], d[4]}
                            elseif contains(room, d[3], d[4]) and lay:at(d[1], d[2]) == CORRIDOR then door = {d[3], d[4], d[1], d[2]} end
                            if door then break end
                        end
                        if door then
                            local pc, pr, cc, cr = door[1], door[2], door[3], door[4]
                            for _ = 1, TRAIL_LEN do
                                if #objects >= OBJECT_CAP then break end
                                if rng:chance(TRAIL_CHANCE) then put_decal(cc, cr) end
                                local nc, nr
                                for q = 0, 3 do
                                    local xc, xr = cc + SIDE_DX[q], cr + SIDE_DZ[q]
                                    if not nc and not (xc == pc and xr == pr) and lay:at(xc, xr) == CORRIDOR and side_kind(lay, cc, cr, q) ~= WALL then nc, nr = xc, xr end
                                end
                                if not nc then break end
                                pc, pr, cc, cr = cc, cr, nc, nr
                            end
                        end
                    end
                end
                -- the story: seats pushed back at loose angles; now and then one knocked over
                -- the story the room's event tells with the seats
                local jitter = event == "tidy" and TIDY_JITTER or event == "hurry" and HURRY_JITTER or SEAT_JITTER
                local to_knock = event == "tidy" and 0 or event == "fight" and #seats or 1
                local knocked = 0
                for _, st in ipairs(seats) do
                    local raw = objects[st[1]]
                    local tips = d_tipped[st[2]]
                    local m
                    local px, py, pz = sunpack("<fff", raw, 8 + 56 + 1)
                    if knocked < to_knock and tips then
                        local tp_ = rng:pick(tips)
                        m = turn_rows(tp_, rng:unit() * 360.0)
                        py = t.floor_y + tp_[10]
                        knocked = knocked + 1
                    else
                        m = turn_rows({sunpack("<fffffffff", raw, 8 + 20 + 1)}, rng:unit() * 2 * jitter - jitter)
                    end
                    objects[st[1]] = raw:sub(1, 8 + 20) .. spack("<fffffffff", m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9])
                        .. spack("<fff", px, py, pz) .. raw:sub(8 + 68 + 1)
                end
                if event == "fight" and #fight_debris > 0 then
                    local rcells = cells_of(room)
                    for _ = 1, FIGHT_DEBRIS do
                        if #objects >= OBJECT_CAP then break end
                        local fcell = rng:pick(rcells)
                        local fd = rng:pick(fight_debris)
                        local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
                        local x, z = world(fcell[1], fcell[2], w, h, fx, fz)
                        objects[#objects + 1] = object(fd[2], x, t.floor_y + DEBRIS[fd[1]], z, rng:unit() * 360.0)
                    end
                end
              end -- not special
            end
        end
        for k = 1, #lay.corridor do
            if rng:chance(DRESS_CORRIDOR_CHANCE) and #objects < OBJECT_CAP then
                local c, r = lay.corridor[k][1], lay.corridor[k][2]
                local ci, kk = class_of(c, r)
                if ci and d_classes[ci] and #d_classes[ci] > 0 then place(rng:pick(d_classes[ci]), c, r, kk) end
            end
        end
        -- corridor clutter: debris where corridors bend or meet, a wall piece by their doorways
        for k = 1, #lay.corridor do
            if #objects >= OBJECT_CAP then break end
            local c, r = lay.corridor[k][1], lay.corridor[k][2]
            local sides, exits, has_door = {}, {}, false
            for q = 0, 3 do
                sides[q] = side_kind(lay, c, r, q)
                if sides[q] ~= WALL then exits[#exits + 1] = q end
                if sides[q] == DOOR then has_door = true end
            end
            local turn = #exits >= 3 or (#exits == 2 and (exits[2] - exits[1]) % 2 == 1)
            if turn and #fight_debris > 0 and rng:chance(CORRIDOR_CLUTTER) then
                for _ = 1, 1 + rng:below(2) do
                    local fd = rng:pick(fight_debris)
                    local fx, fz = rng:unit() * 0.5 + 0.25, rng:unit() * 0.5 + 0.25
                    local x, z = world(c, r, w, h, fx, fz)
                    objects[#objects + 1] = object(fd[2], x, t.floor_y + DEBRIS[fd[1]], z, rng:unit() * 360.0)
                end
            end
            if has_door then
                local ci, kk = class_of(c, r)
                if ci and ci - 1 ~= 0 and d_hung_any[ci - 1] and rng:chance(DOORWAY_DRESS) then
                    place({rng:pick(d_hung_any[ci - 1])}, c, r, kk)
                end
            end
        end
    end
    -- the barricades: on the room side of each blocked doorway, a barricade across it and something heaped beside
    for _, d in ipairs(lay.blocked_doors or {}) do
        local ac, ar, bc, br = d[1], d[2], d[3], d[4]
        local q = 0
        for k = 0, 3 do if bc - ac == SIDE_DX[k] and br - ar == SIDE_DZ[k] then q = k end end
        local x, z = world(ac, ar, w, h, 0.5 + 0.32 * SIDE_DX[q], 0.5 + 0.32 * SIDE_DZ[q])
        objects[#objects + 1] = object(rng:pick(blockers), x, t.floor_y, z, SIDE_YAW[q])
        if #block_fill > 0 then
            local side = (q + 1) % 4
            local x2, z2 = world(ac, ar, w, h, 0.5 + 0.22 * SIDE_DX[q] + 0.25 * SIDE_DX[side], 0.5 + 0.22 * SIDE_DZ[q] + 0.25 * SIDE_DZ[side])
            objects[#objects + 1] = object(rng:pick(block_fill), x2, t.floor_y, z2, rng:unit() * 360.0)
        end
    end
    -- easter eggs 1-3 (the Python reference's): remains where the last descent ended, the twelfth name, the carving
    local remains
    if themed(t, REMAINS, stage_no) then
        for _, pr in ipairs(t.debris) do if pr[1] == REMAINS then remains = pr[2] break end end
    end
    -- (easter egg 1, the last descent's remains, was dropped 2026-10-22: runs are randomized)
    local gaol
    for i = 0, lay.nrooms - 1 do if not gaol and lay.rooms[i].kind == "room" and lay.rooms[i].purpose == "gaol" then gaol = lay.rooms[i] end end
    if remains and gaol and gen.depth_of(area) >= 2 and rng:chance(ELARA_CHANCE) then
        local x, z = world(gaol.c0, gaol.r0, w, h, 0.35, 0.35)
        objects[#objects + 1] = object(remains, x, DEBRIS[REMAINS], z, 205.0)
        info_eggs.elara = 1
    end
    local carving
    if themed(t, CARVING, stage_no) then
        for i, raw in ipairs(t.props) do if t.prop_names[i] == CARVING then carving = raw break end end
    end
    if carving and lay.treasury and gen.depth_of(area) >= 6 and not opts.shrine_done then
        local x, z = world(lay.treasury.c0, lay.treasury.r0, w, h, 0.9, 0.9)
        objects[#objects + 1] = object(carving, x, t.floor_y, z, 0.0)
        info_eggs.shrine = 1
    end
    -- four pillars in the inner corners of the boss room (rooms are 4..5 cells a side); spawns avoid them
    local pillar_cells = {}
    local boss_room = lay:boss_room()
    if pillars_ok and boss_room and boss_room.c1 - boss_room.c0 >= 3 and boss_room.r1 - boss_room.r0 >= 3 then
        pillar_cells = {{boss_room.c0 + 1, boss_room.r0 + 1}, {boss_room.c1 - 1, boss_room.r0 + 1}, {boss_room.c0 + 1, boss_room.r1 - 1}, {boss_room.c1 - 1, boss_room.r1 - 1}}
        for _, cell in ipairs(pillar_cells) do
            local x, z = world(cell[1], cell[2], w, h)
            objects[#objects + 1] = object(t.pillar, x, t.floor_y, z, 0.0)
        end
    end
    local blocked_cells = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.pillars then
            for _, cell in ipairs({{room.c0 + 1, room.r0 + 1}, {room.c1 - 1, room.r0 + 1}, {room.c0 + 1, room.r1 - 1}, {room.c1 - 1, room.r1 - 1}}) do
                local x, z = world(cell[1], cell[2], w, h)
                objects[#objects + 1] = object(t.pillar, x, t.floor_y, z, 0.0)
                blocked_cells[cell[1] * 1000 + cell[2]] = true
            end
        end
    end
    local gc, gr
    if ex.kind == "maze" then gc, gr = ex.goal[1], ex.goal[2] else gc, gr = centre(ex) end
    local gx, gz = world(gc, gr, w, h)
    if staircase then objects[#objects + 1] = object(t.stairs, gx, t.floor_y, gz, rng:unit() * 360.0) end
    -- light by use: each ordinary room's lamp halfway toward the middle of the things standing in it
    local sums, order = {}, {}
    for _, raw in ipairs(objects) do
        local ox, _, oz = sunpack("<fff", raw, 8 + 56 + 1)
        local o = lay:at(math.floor(ox / CELL + w / 2), math.floor(oz / CELL + h / 2))
        if room_lamp[o] then
            local a = sums[o]
            if not a then a = {0.0, 0.0, 0}; sums[o] = a; order[#order + 1] = o end
            a[1] = a[1] + ox
            a[2] = a[2] + oz
            a[3] = a[3] + 1
        end
    end
    for _, o in ipairs(order) do
        local a = sums[o]
        local node = nodes[room_lamp[o]]
        local lx, ly, lz = sunpack("<fff", node, 8 + 68 + 1)
        nodes[room_lamp[o]] = node:sub(1, 8 + 68) .. spack("<fff", (lx + a[1] / a[3]) / 2, ly, (lz + a[2] / a[3]) / 2) .. node:sub(8 + 80 + 1)
    end
    node_chunk = spack("<I4", #nodes) .. table.concat(nodes)
    local object_chunk = spack("<I4", #objects) .. table.concat(objects)
    -- items
    local start = lay.rooms[0]
    local stc, str_ = centre(start)
    local sx, sz = world(stc, str_, w, h)
    local copy_room
    for i = 0, lay.nrooms - 1 do if not copy_room and lay.rooms[i].copy then copy_room = lay.rooms[i] end end
    local places = {
        placement(t.marker_place, 0x80000000 | t.arrival_id, sx, 100.0, sz, 0.0),
        placement(t.marker_place, 0x80000000 | t.zone_id, gx, 100.0, gz, 0.0),
    }
    if copy_room and t.wall_zone_id ~= 0 then -- the backrooms trigger in the copy's corner
        local x, z = world(copy_room.c0, copy_room.r0, w, h, 0.16, 0.16)
        places[#places + 1] = placement(t.marker_place, 0x80000000 | t.wall_zone_id, x, 100.0, z, 0.0)
    end
    local ic, ir, oc, orr = lay.exit_door[1], lay.exit_door[2], lay.exit_door[3], lay.exit_door[4]
    local q = 0
    for k = 0, 3 do if oc - ic == SIDE_DX[k] and orr - ir == SIDE_DZ[k] then q = k end end
    local dx, dz = world(ic, ir, w, h)
    local kind = gen.puzzle_kind(area)
    local puzzled = (kind == "plate" or kind == "order" or kind == "timed" or kind == "hold") and t.puzzle_gate_id ~= 0 and #t.puzzle_lever_ids >= 3
    if puzzled then -- the boss doorway is the puzzle's portcullis, down until the puzzle raises it
        places[#places + 1] = placement(t.gate_place, 0x80000000 | t.puzzle_gate_id, dx, t.floor_y, dz, SIDE_YAW[q], 1)
    else
        places[#places + 1] = placement(t.door_place, 0x80000000 | t.door_ids[pair], dx, t.floor_y, dz, SIDE_YAW[q], 1)
    end
    local info = {boss = 0, gate = 0, gate_lever = 0, fires = t.fire_ids}
    if lay.gate then
        local gbc, gbr, gec, ger = lay.gate[1], lay.gate[2], lay.gate[3], lay.gate[4]
        local gq = 0
        for k = 0, 3 do if gbc - gec == SIDE_DX[k] and gbr - ger == SIDE_DZ[k] then gq = k end end
        local gx2, gz2 = world(gec, ger, w, h)
        places[#places + 1] = placement(t.gate_place, 0x80000000 | t.gate_ids[pair], gx2, t.floor_y, gz2, SIDE_YAW[gq], 1)
        local walls = {}
        for wq = 0, 3 do if side_kind(lay, gec, ger, wq) == WALL then walls[#walls + 1] = wq end end
        if #walls == 0 then walls[1] = (gq + 2) % 4 end
        local lq = walls[rng:below(#walls) + 1]
        local lx, lz = world(gec, ger, w, h, 0.5 + 0.42 * SIDE_DX[lq], 0.5 + 0.42 * SIDE_DZ[lq])
        places[#places + 1] = placement(t.lever_place, 0x80000000 | t.gate_lever_ids[pair], lx, LEVER_Y, lz, SIDE_YAW[(lq + 2) % 4])
        info.gate, info.gate_lever = t.gate_ids[pair], t.gate_lever_ids[pair]
    end
    -- the wing gate (another of the template's portcullis/lever pairs): in the far cell facing back,
    -- its lever on the near side for the player to find
    if lay.wing and #t.gate_ids > 1 then
        local wg = lay.wing
        local wk = (pair + 1) % #t.gate_ids + 1 -- pair is 1-based here: the Python reference's (pair + 2) % n
        local wq = 0
        for k = 0, 3 do if wg[1] - wg[3] == SIDE_DX[k] and wg[2] - wg[4] == SIDE_DZ[k] then wq = k end end
        local wx, wz = world(wg[3], wg[4], w, h)
        places[#places + 1] = placement(t.gate_place, 0x80000000 | t.gate_ids[wk], wx, t.floor_y, wz, SIDE_YAW[wq], 1)
        local lq = wg[7]
        local lx, lz = world(wg[5], wg[6], w, h, 0.5 + 0.42 * SIDE_DX[lq], 0.5 + 0.42 * SIDE_DZ[lq])
        places[#places + 1] = placement(t.lever_place, 0x80000000 | t.gate_lever_ids[wk], lx, LEVER_Y, lz, SIDE_YAW[(lq + 2) % 4])
        info.wing_gate = t.gate_ids[wk]
    end
    -- the boss pen (endless_gen: portcullis in the pen cell, lever on a wall of the boss cell beside it)
    if lay.pen and #t.gate_ids > 2 then
        local pen = lay.pen
        local pc, pr, bc, br, pen_room = pen[1], pen[2], pen[3], pen[4], pen[5]
        local pk = pair % #t.gate_ids + 1 -- pair is 1-based here: the Python reference's (pair + 1) % n
        local pq = 0
        for k = 0, 3 do if bc - pc == SIDE_DX[k] and br - pr == SIDE_DZ[k] then pq = k end end
        local lq
        for _, q in ipairs({(pq + 1) % 4, (pq + 3) % 4, (pq + 2) % 4}) do
            if not lq and side_kind(lay, bc, br, q) == WALL then lq = q end
        end
        if lq then
            local px, pz = world(pc, pr, w, h)
            places[#places + 1] = placement(t.gate_place, 0x80000000 | t.gate_ids[pk], px, t.floor_y, pz, SIDE_YAW[pq], 1)
            local lx, lz = world(bc, br, w, h, 0.5 + 0.42 * SIDE_DX[lq], 0.5 + 0.42 * SIDE_DZ[lq])
            places[#places + 1] = placement(t.lever_place, 0x80000000 | t.gate_lever_ids[pk], lx, LEVER_Y, lz, SIDE_YAW[(lq + 2) % 4])
            local x0, z0 = world(pen_room.c0, pen_room.r0, w, h, 0.0, 0.0)
            local x1, z1 = world(pen_room.c1, pen_room.r1, w, h, 1.0, 1.0)
            info.pen_gate, info.pen_lever, info.pen_box = t.gate_ids[pk], t.gate_lever_ids[pk], {x0, z0, x1, z1}
        end
    end
    -- talk zones: the companions react at the boss door (its corridor side), past the gate, at the
    -- stairs and in the start room of a new depth; all of a spot's zones sit on one cell
    local per_spot = #t.talk_zone_ids // 9
    local new_depth = depth >= 2 and (area - 1) % AREAS_PER_DEPTH == 0
    local gate_cell = lay.gate and {lay.gate[1], lay.gate[2]} or nil
    local depth_cell = new_depth and {stc, str_} or nil
    -- spots: boss door, gate, stairs, depth, key (placed after the key below), vault (after the vault door), closet, arrive, boss room
    local boss_cell = nil
    do local br = lay:boss_room() if br then local bcc, bcr = centre(br) boss_cell = {bcc, bcr} end end
    local spots = {{oc, orr}, gate_cell, staircase and {gc, gr} or nil, depth_cell,
        false, false,
        (#lay.closets > 0) and {lay.closets[1][3], lay.closets[1][4]} or nil, {stc, str_}, boss_cell}
    for spot_index = 0, 8 do
        local cell = spots[spot_index + 1]
        if cell and per_spot > 0 then
            local tx, tz = world(cell[1], cell[2], w, h)
            for _, zid in ipairs(talk_zone_ids(t, spot_index, per_spot, present)) do
                places[#places + 1] = placement(t.marker_place, 0x80000000 | zid, tx, 100.0, tz, 0.0)
            end
        end
    end
    local per_pair = #t.pair_zone_ids // 3
    local pair_spots = {gate_cell, depth_cell, boss_cell}
    for spot_index = 0, 2 do
        local cell = pair_spots[spot_index + 1]
        if cell and per_pair > 0 then
            local tx, tz = world(cell[1], cell[2], w, h)
            for k = 1, per_pair do
                places[#places + 1] = placement(t.marker_place, 0x80000000 | t.pair_zone_ids[spot_index * per_pair + k], tx, 100.0, tz, 0.0)
            end
        end
    end
    local candidates = {}
    for i = 0, lay.nrooms - 1 do if lay.rooms[i].kind == "room" then candidates[#candidates + 1] = lay.rooms[i] end end
    if #candidates == 0 then candidates[1] = start end
    if puzzled then
        local p_places, p_objects, p_info, opener = puzzle_parts(t, lay, rng, kind, start, ic, ir, oc, orr, w, h, t.dress and t.dress[stage_no] and t.dress[stage_no].rooms or nil, stage_no)
        for _, pl in ipairs(p_places) do places[#places + 1] = pl end
        -- after the lamps and the object chunk were made: added at the end and the chunk made again
        for _, ob in ipairs(p_objects) do objects[#objects + 1] = ob end
        object_chunk = spack("<I4", #objects) .. table.concat(objects)
        for k, v in pairs(p_info) do info[k] = v end
        lay.key_cell = {opener[1], opener[2]}
    end
    local by_distance = stable_sort(candidates, function(room) local cc, cr = centre(room) return dist(cc, cr, ic, ir) end)
    local far_half = {}
    for i = #by_distance // 2 + 1, #by_distance do far_half[#far_half + 1] = by_distance[i] end
    local vaults = {}
    if gen.is_vault_area(area) and not puzzled then
        for _, room in ipairs(far_half) do
            local n = 0
            for _, d in ipairs(lay.doors) do if contains(room, d[1], d[2]) or contains(room, d[3], d[4]) then n = n + 1 end end
            if n == 1 then vaults[#vaults + 1] = room end
        end
    end
    local key_room = #vaults > 0 and rng:pick(vaults) or rng:pick(far_half)
    local kx, kz
    if not puzzled then
        local kcell = rng:pick(cells_of(key_room))
        lay.key_cell = {kcell[1], kcell[2]}
        local kfx, kfz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
        kx, kz = world(kcell[1], kcell[2], w, h, kfx, kfz)
    end
    if puzzled then
        -- the puzzle's parts are placed above; no key, no lever
    elseif gen.is_lever_area(area) then
        local edge = {}
        for _, cell in ipairs(cells_of(key_room)) do
            for q = 0, 3 do if side_kind(lay, cell[1], cell[2], q) == WALL then edge[#edge + 1] = {cell[1], cell[2], q} end end
        end
        local pick = rng:pick(edge)
        local c, r, q = pick[1], pick[2], pick[3]
        lay.key_cell = {c, r}
        local lx, lz = world(c, r, w, h, 0.5 + 0.42 * SIDE_DX[q], 0.5 + 0.42 * SIDE_DZ[q])
        places[#places + 1] = placement(t.lever_place, 0x80000000 | t.lever_ids[pair], lx, LEVER_Y, lz, SIDE_YAW[(q + 2) % 4])
    elseif rng:chance(50) then places[#places + 1] = placement(t.key_place, 0x80000000 | t.key_ids[pair], kx, t.floor_y, kz, rng:unit() * 360.0)
    else places[#places + 1] = placement(t.chest_place, 0x80000000 | t.key_chest_ids[pair], kx, t.floor_y, kz, rng:unit() * 360.0) end
    if per_spot > 0 and not gen.is_lever_area(area) and not puzzled then
        local kx2, kz2 = world(lay.key_cell[1], lay.key_cell[2], w, h)
        for _, zid in ipairs(talk_zone_ids(t, 4, per_spot, present)) do
            places[#places + 1] = placement(t.marker_place, 0x80000000 | zid, kx2, 100.0, kz2, 0.0)
        end
    end
    if #vaults > 0 then
        -- the vault: its one doorway gets the next pair's locked door, that pair's key goes to another room
        local pair2 = pair % #t.key_ids + 1 -- pairs are 1-based here
        local d
        for _, dd in ipairs(lay.doors) do if contains(key_room, dd[1], dd[2]) or contains(key_room, dd[3], dd[4]) then d = dd break end end
        local vic, vir, voc, vor
        if contains(key_room, d[1], d[2]) then vic, vir, voc, vor = d[1], d[2], d[3], d[4] else vic, vir, voc, vor = d[3], d[4], d[1], d[2] end
        local vq = 0
        for k = 0, 3 do if voc - vic == SIDE_DX[k] and vor - vir == SIDE_DZ[k] then vq = k end end
        local vx, vz = world(vic, vir, w, h)
        places[#places + 1] = placement(t.door_place, 0x80000000 | t.door_ids[pair2], vx, t.floor_y, vz, SIDE_YAW[vq], 1)
        if per_spot > 0 then
            local vx2, vz2 = world(voc, vor, w, h)
            for _, zid in ipairs(talk_zone_ids(t, 5, per_spot, present)) do
                places[#places + 1] = placement(t.marker_place, 0x80000000 | zid, vx2, 100.0, vz2, 0.0)
            end
        end
        local others = {}
        for _, room in ipairs(candidates) do if room ~= key_room then others[#others + 1] = room end end
        if #others == 0 then others[1] = start end
        if lay.wing then -- the vault's own key on the near side of the wing gate, which may stand in the vault
            local wg = lay.wing
            local scx, scy = centre(start)
            local shut = secret_shut(lay)
            shut[edge_key(lay.w, wg[1], wg[2], wg[3], wg[4])] = true
            local near = reach_shut(lay, scx, scy, shut)
            local kept = {}
            for _, room in ipairs(others) do
                local cc, cr = centre(room)
                if near[cr * lay.w + cc] then kept[#kept + 1] = room end
            end
            if #kept == 0 then kept[1] = start end
            others = kept
        end
        local k2_room = rng:pick(others)
        local k2 = rng:pick(cells_of(k2_room))
        local k2fx, k2fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
        local k2x, k2z = world(k2[1], k2[2], w, h, k2fx, k2fz)
        if rng:chance(50) then places[#places + 1] = placement(t.key_place, 0x80000000 | t.key_ids[pair2], k2x, t.floor_y, k2z, rng:unit() * 360.0)
        else places[#places + 1] = placement(t.chest_place, 0x80000000 | t.key_chest_ids[pair2], k2x, t.floor_y, k2z, rng:unit() * 360.0) end
    end
    local objects_extra = {}
    local trap_cells = {}
    for k = 1, #lay.corridor do
        local cell = lay.corridor[k]
        if (k - 1) % 3 == 2 and dist(cell[1], cell[2], stc, str_) >= 5 then trap_cells[#trap_cells + 1] = cell end
    end
    local fire_slots = gen.fire_trap_count(area)
    if fire_slots > #t.fire_ids then fire_slots = #t.fire_ids end
    for slot = 1, fire_slots do
        if #trap_cells == 0 then break end
        local cell = table.remove(trap_cells, rng:below(#trap_cells) + 1)
        local x, z = world(cell[1], cell[2], w, h)
        objects_extra[#objects_extra + 1] = placement(t.fire_place, 0x80000000 | t.fire_ids[slot], x, t.floor_y, z, 0.0)
        places[#places + 1] = placement(t.marker_place, 0x80000000 | t.fire_zone_ids[slot], x, 100.0, z, 0.0)
        local opens = {}
        for q = 0, 3 do if side_kind(lay, cell[1], cell[2], q) ~= WALL then opens[#opens + 1] = q end end
        local q = #opens > 0 and rng:pick(opens) or 0
        local px, pz = world(cell[1], cell[2], w, h, 0.5 + 0.35 * SIDE_DX[q], 0.5 + 0.35 * SIDE_DZ[q])
        places[#places + 1] = placement(t.plate_place, 0x80000000 | t.plate_fire_ids[slot], px, t.floor_y, pz, 0.0)
    end
    local nsecret = #lay.secrets
    if nsecret > 2 * #t.switch_ids then nsecret = 2 * #t.switch_ids end
    for k = 1, nsecret do
        local sc_ = lay.secrets[k]
        local ic, ir, oc, orr, room = sc_[1], sc_[2], sc_[3], sc_[4], sc_[5]
        local q = 0
        for kk = 0, 3 do if oc - ic == SIDE_DX[kk] and orr - ir == SIDE_DZ[kk] then q = kk end end
        local sx2, sz2 = world(ic, ir, w, h)
        places[#places + 1] = placement(t.secret_door_place, 0x80000000 | t.secret_door_ids[(k - 1) % #t.secret_door_ids + 1], sx2, t.floor_y, sz2, SIDE_YAW[q], 1)
        local edge = {}
        for _, rc in ipairs(cells_of(room)) do
            for wq = 0, 3 do if side_kind(lay, rc[1], rc[2], wq) == WALL then edge[#edge + 1] = {rc[1], rc[2], wq} end end
        end
        local e = rng:pick(edge)
        local wx, wz = world(e[1], e[2], w, h, 0.5 + 0.46 * SIDE_DX[e[3]], 0.5 + 0.46 * SIDE_DZ[e[3]])
        places[#places + 1] = placement(t.switch_place, 0x80000000 | t.switch_ids[(k - 1) % #t.switch_ids + 1], wx, LEVER_Y + 45.0, wz, SIDE_YAW[(e[3] + 2) % 4])
    end
    local nmg = #lay.maze_gates
    if nmg > #t.maze_gate_ids then nmg = #t.maze_gate_ids end
    for k = 1, nmg do
        local mg = lay.maze_gates[k]
        local gate_cell, gq, lever_cell, lq = mg[1], mg[2], mg[3], mg[4]
        local mx, mz2 = world(gate_cell[1], gate_cell[2], w, h)
        places[#places + 1] = placement(t.gate_place, 0x80000000 | t.maze_gate_ids[k], mx, t.floor_y, mz2, SIDE_YAW[gq], 1)
        local lx, lz = world(lever_cell[1], lever_cell[2], w, h, 0.5 + 0.42 * SIDE_DX[lq], 0.5 + 0.42 * SIDE_DZ[lq])
        places[#places + 1] = placement(t.lever_place, 0x80000000 | t.maze_lever_ids[k], lx, LEVER_Y, lz, SIDE_YAW[(lq + 2) % 4])
    end
    -- the companion bypass: its portcullis in the outside cell facing the goal, its lever on the goal cell's other outer wall
    if lay.bypass and t.bypass_gate_id ~= 0 then
        local bg_c, bg_r, bt_c, bt_r, blq = lay.bypass[1], lay.bypass[2], lay.bypass[3], lay.bypass[4], lay.bypass[5]
        local bq = 0
        for q = 0, 3 do if bg_c - bt_c == SIDE_DX[q] and bg_r - bt_r == SIDE_DZ[q] then bq = q end end
        local bx, bz = world(bt_c, bt_r, w, h)
        places[#places + 1] = placement(t.gate_place, 0x80000000 | t.bypass_gate_id, bx, t.floor_y, bz, SIDE_YAW[bq], 1)
        local lx2, lz2 = world(bg_c, bg_r, w, h, 0.5 + 0.42 * SIDE_DX[blq], 0.5 + 0.42 * SIDE_DZ[blq])
        places[#places + 1] = placement(t.lever_place, 0x80000000 | t.bypass_lever_id, lx2, LEVER_Y, lz2, SIDE_YAW[(blq + 2) % 4])
    end
    local ncl = #lay.closets
    if ncl > #t.closet_gate_ids then ncl = #t.closet_gate_ids end
    for k = 1, ncl do
        local cl = lay.closets[k]
        local oc, orr, cc, cr = cl[1], cl[2], cl[3], cl[4]
        local q = 0
        for kk = 0, 3 do if cc - oc == SIDE_DX[kk] and cr - orr == SIDE_DZ[kk] then q = kk end end
        local cx2, cz2 = world(oc, orr, w, h)
        places[#places + 1] = placement(t.gate_place, 0x80000000 | t.closet_gate_ids[k], cx2, t.floor_y, cz2, SIDE_YAW[q], 1)
        local px, pz = world(cc, cr, w, h)
        places[#places + 1] = placement(t.plate_place, 0x80000000 | t.plate_closet_ids[k], px, t.floor_y, pz, 0.0)
    end
    for _ = 1, gen.push_trap_count(area) do
        if #trap_cells == 0 then break end
        local cell = table.remove(trap_cells, rng:below(#trap_cells) + 1)
        local walls = {}
        for q = 0, 3 do if side_kind(lay, cell[1], cell[2], q) == WALL then walls[#walls + 1] = q end end
        if #walls > 0 then
            local q = rng:pick(walls)
            local x, z = world(cell[1], cell[2], w, h)
            places[#places + 1] = placement(t.marker_place, 0x80000000 | t.hazard_ids[1 + q], x, 100.0, z, 0.0)
        end
    end
    for _, o in ipairs(objects_extra) do places[#places + 1] = o end
    local chests = chest_roster(t, depth)
    for _, cell in ipairs(lay.spur_ends) do -- a reason to walk a dead end, three times in five
        if rng:chance(60) then
            local x, z = world(cell[1], cell[2], w, h)
            places[#places + 1] = placement(t.chest_place, 0x80000000 | rng:pick(chests), x, t.floor_y, z, rng:unit() * 360.0)
        end
    end
    local rare = rare_chests(t)
    local rare_chance = 10 + 5 * depth
    if rare_chance > 60 then rare_chance = 60 end
    local salves = 0
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" then
            if rng:chance(CHEST_CHANCE[room.purpose] or 45) then
                local cell = rng:pick(cells_of(room))
                local x, z = world(cell[1], cell[2], w, h)
                local id
                if room.purpose == "shrine" and rng:chance(rare_chance) then id = rng:pick(rare) else id = rng:pick(chests) end
                places[#places + 1] = placement(t.chest_place, 0x80000000 | id, x, t.floor_y, z, rng:unit() * 360.0)
            end
            -- the first healing salve: in the quiet room (the second is in the hidden treasury)
            if t.salve_id ~= 0 and salves < 1 and room.purpose == "quiet" then
                local cell = rng:pick(cells_of(room))
                local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
                local x, z = world(cell[1], cell[2], w, h, fx, fz)
                places[#places + 1] = placement(t.key_place, 0x80000000 | t.salve_id, x, t.floor_y, z, rng:unit() * 360.0)
                salves = salves + 1
            end
        end
    end
    if lay.treasury then -- the hidden room: a rare find and the second salve, always
        local tcells = cells_of(lay.treasury)
        local x, z = world(tcells[1][1], tcells[1][2], w, h)
        places[#places + 1] = placement(t.chest_place, 0x80000000 | rng:pick(rare), x, t.floor_y, z, rng:unit() * 360.0)
        if t.salve_id ~= 0 then
            x, z = world(tcells[4][1], tcells[4][2], w, h)
            places[#places + 1] = placement(t.key_place, 0x80000000 | t.salve_id, x, t.floor_y, z, 0.0)
        end
    end
    for _, it in ipairs(dress_items) do places[#places + 1] = it end
    local script = string.format("LuaEvent(EndlessNext,%010d_%010d);", area, seed & 0xFFFFFFFF)
    -- the items chunk as parts (the level db is the biggest piece; it is copied once, into the final concat)
    local places_chunk = chunk(TAG_ITEM_PLACES, spack("<I4", #places) .. table.concat(places))
    local item_parts = {t.item_db:sub(1, t.script_at - 1), script, t.item_db:sub(t.script_at + 44), t.item_strings, places_chunk}
    local item_size = 0
    for _, part in ipairs(item_parts) do item_size = item_size + #part end
    -- people
    local enemies = gen.enemy_count(area)
    local roster = enemy_roster(t, depth)
    local keep_out = depth == 1 and 6 or depth == 2 and 4 or 2
    if mutator == "silent" then
        enemies = enemies // 4
        if enemies < 4 then enemies = 4 end
    elseif mutator == "ambush" then
        enemies = enemies * 3 // 2
        if enemies > ENEMY_CAP then enemies = ENEMY_CAP end
        keep_out = 1
    end
    local spawns = {}
    local homes = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        local k = room.kind
        if k ~= "start" and k ~= "exit" and k ~= "boss" and k ~= "closet" and k ~= "treasury" and k ~= "pen" and room.purpose ~= "quiet" then
            for _ = 1, (HOME_WEIGHT[room.purpose] or 1) do homes[#homes + 1] = room end
        end
    end
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "closet" then
            local cells_ = cells_of(room)
            local take = 2 + (depth >= 4 and 1 or 0)
            for k = 1, take do
                local cell = cells_[k]
                local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
                local x, z = world(cell[1], cell[2], w, h, fx, fz)
                spawns[#spawns + 1] = spawn(0x80000000 | rng:pick(roster), x, t.floor_y, z, rng:unit() * 2 * math.pi)
            end
        end
    end
    local tries = 0
    local boss_room = lay:boss_room()
    if boss_room then
        local bosses = boss_roster(t, depth)
        local boss_id = rng:pick(bosses)
        if t.proctor_boss_id ~= 0 and area == 1 + 2 * AREAS_PER_DEPTH then boss_id = t.proctor_boss_id end -- the first area of depth 3: the proctor
        local bcc, bcr = centre(boss_room)
        local bx, bz = world(bcc, bcr, w, h)
        spawns[#spawns + 1] = spawn(0x80000000 | boss_id, bx, t.floor_y, bz, rng:unit() * 2 * math.pi)
        info.boss = boss_id
        info.bosses = {boss_id}
        local boss_cells = {}
        for _, cell in ipairs(cells_of(boss_room)) do
            local blocked = false
            for _, pc in ipairs(pillar_cells) do if pc[1] == cell[1] and pc[2] == cell[2] then blocked = true end end
            if not blocked then boss_cells[#boss_cells + 1] = cell end
        end
        local nb = gen.boss_count(area) + (mutator == "silent" and 1 or 0)
        if nb > BOSS_CAP then nb = BOSS_CAP end
        for _ = 1, nb - 1 do
            local cell = rng:pick(boss_cells)
            local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
            local x, z = world(cell[1], cell[2], w, h, fx, fz)
            local extra = rng:pick(bosses)
            spawns[#spawns + 1] = spawn(0x80000000 | extra, x, t.floor_y, z, rng:unit() * 2 * math.pi)
            info.bosses[#info.bosses + 1] = extra
        end
        local nm = gen.boss_minion_count(area) * (mutator == "silent" and 2 or 1)
        if nm > MINION_CAP then nm = MINION_CAP end
        for _ = 1, nm do
            local cell = rng:pick(boss_cells)
            local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
            local x, z = world(cell[1], cell[2], w, h, fx, fz)
            spawns[#spawns + 1] = spawn(0x80000000 | rng:pick(roster), x, t.floor_y, z, rng:unit() * 2 * math.pi)
        end
    end
    while #spawns < enemies and tries < enemies * 8 do
        tries = tries + 1
        local room = rng:pick(homes)
        local c, r
        local ok = true
        if room.kind == "maze" then
            local nodes_ = {}
            for rr = room.r0, room.r1, 2 do for cc = room.c0, room.c1, 2 do nodes_[#nodes_ + 1] = {cc, rr} end end
            local cell = rng:pick(nodes_)
            c, r = cell[1], cell[2]
            if dist(c, r, room.goal[1], room.goal[2]) < 3 then ok = false end
        else
            local cell = rng:pick(cells_of(room))
            c, r = cell[1], cell[2]
        end
        if ok and (dist(c, r, stc, str_) < keep_out or blocked_cells[c * 1000 + r]) then ok = false end
        if ok then
            local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
            local x, z = world(c, r, w, h, fx, fz)
            local who = 0x80000000 | rng:pick(roster)
            spawns[#spawns + 1] = spawn(who, x, t.floor_y, z, rng:unit() * 2 * math.pi)
        end
    end
    local cid = companion_for(t, area, met)
    if cid ~= 0 then
        local rooms_for = {}
        for i = 0, lay.nrooms - 1 do
            local room = lay.rooms[i]
            if room.kind == "room" then
                local cc, cr = centre(room)
                if dist(cc, cr, stc, str_) >= 6 then rooms_for[#rooms_for + 1] = room end
            end
        end
        if #rooms_for > 0 then
            -- the room that fits who they are: the soldier nearest the locked door, the apprentice nearest
            -- the maze entry, the bandit farthest from the start; ties go to the first room in order
            local which = 0 -- 0 Tobin, 1 Aldric, 2 Mira: the room that fits them
            for i, id in ipairs(t.companion_ids) do if id == cid then which = i - 1 end end
            local room = rooms_for[1]
            if which == 0 then
                local best = -1
                for _, rm in ipairs(rooms_for) do
                    local cc, cr = centre(rm)
                    local d = dist(cc, cr, stc, str_)
                    if d > best then best = d; room = rm end
                end
            else
                local tc, tr
                if which == 1 then tc, tr = oc, orr
                elseif ex.kind == "maze" then tc, tr = ex.entry[1], ex.entry[2]
                else tc, tr = centre(ex) end
                local best = 1 << 30
                for _, rm in ipairs(rooms_for) do
                    local cc, cr = centre(rm)
                    local d = dist(cc, cr, tc, tr)
                    if d < best then best = d; room = rm end
                end
            end
            local cell = rng:pick(cells_of(room))
            local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
            local x, z = world(cell[1], cell[2], w, h, fx, fz)
            spawns[#spawns + 1] = spawn(0x80000000 | cid, x, t.floor_y, z, rng:unit() * 2 * math.pi)
            info.companion = cid
        end
    end
    local people_chunk = spack("<I4", 1 + #spawns) .. t.people_db .. table.concat(spawns)
    for k, v in pairs(info_eggs) do info[k] = v end
    if lay.copy_egg then info.copy = 1 end
    if copy_room then -- where the backrooms send you back to
        local cc, cr = centre(copy_room)
        info.copy_x, info.copy_z = world(cc, cr, w, h)
    end
    info.archetype = 0
    for i, nm in ipairs(ARCH_ORDER) do if nm == arch_name then info.archetype = i - 1 end end
    info.mutator = 0
    for i, nm in ipairs(MUTATORS) do if nm == mutator then info.mutator = i end end
    local scale = 1.0 - 0.15 * (depth - 1)
    if scale < 0.4 then scale = 0.4 end
    if mutator == "dark" then scale = scale * 0.5 end
    local a0, a1, a2 = sunpack("<fff", t.env, 0x30 + 1)
    local env = t.env:sub(1, 0x30) .. spack("<fff", a0 * scale, a1 * scale, a2 * scale) .. t.env:sub(0x30 + 12 + 1)
    local parts = {spack("<I4", MAGIC), chunk(TAG_GRID, grid), chunk(TAG_NODES, node_chunk), chunk(TAG_OBJECTS, object_chunk),
                   spack("<I4I4", TAG_ITEMS, item_size)}
    for _, part in ipairs(item_parts) do parts[#parts + 1] = part end
    parts[#parts + 1] = chunk(TAG_PEOPLE, people_chunk)
    parts[#parts + 1] = chunk(TAG_ENV, env)
    return table.concat(parts), lay, info
end

-- Where Sir waits in the backrooms (endless_gen.backrooms_lair): the ordinary room nearest half the farthest
-- one's distance from the start, first on ties, never the key's room
local function backrooms_lair(lay)
    local sc, sr = centre(lay.rooms[0])
    local rooms = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        local kc, kr = lay.key_cell[1], lay.key_cell[2]
        local has_key = kc >= room.c0 and kc <= room.c1 and kr >= room.r0 and kr <= room.r1 and not is_cut(room, kc, kr)
        if room.kind == "room" and not has_key then rooms[#rooms + 1] = room end
    end
    if #rooms == 0 then return nil end
    local far = 0
    for _, room in ipairs(rooms) do
        local cc, cr = centre(room)
        local d = math.abs(cc - sc) + math.abs(cr - sr)
        if d > far then far = d end
    end
    local best_d, best
    for _, room in ipairs(rooms) do
        local cc, cr = centre(room)
        local d = math.abs(math.abs(cc - sc) + math.abs(cr - sr) - far / 2)
        if best_d == nil or d < best_d then best_d, best = d, room end
    end
    return best
end

-- The backrooms' furniture: its own rng, never in a cell with a doorway or the key's cell
local function backrooms_props(t, lay, w, h, seed, area, stage_no, lair)
    local dress = t.dress and t.dress[stage_no]
    if not dress then return {} end
    local proto = {}
    for _, name in ipairs(BACK_PROPS) do
        local found
        for _, rm in ipairs(dress.rooms) do
            for _, rc in ipairs(rm[2]) do
                for _, ob in ipairs(rc[2]) do
                    if not found and dress_name(ob[4]) == name and math.abs((sunpack("<f", ob[4], 8 + 20 + 16 + 1))) >= 0.7 then found = ob end
                end
            end
        end
        if found then proto[name] = found end
    end
    local rng = Rng.new(seed ~ 0xBAC5, area)
    local out = {}
    local fy = t.floor_y
    local yaw0, yaw180 = yaw_matrix(0.0), yaw_matrix(180.0)
    local bed = spack("<fffffffff", table.unpack(BED_ON_END))
    local function quiet(c, r)
        if c == lay.key_cell[1] and r == lay.key_cell[2] then return false end
        for q = 0, 3 do if side_kind(lay, c, r, q) == DOOR then return false end end
        return true
    end
    local function add(name, c, r, fx, fz, mtx, lift)
        local ob = proto[name]
        if ob then
            local x, z = world(c, r, w, h, fx, fz)
            out[#out + 1] = ob[4]:sub(1, 8 + 20) .. mtx .. spack("<fff", x, fy + ob[2] + (lift or 0.0), z) .. ob[4]:sub(8 + 68 + 1)
        end
    end
    local function contains(room, c, r)
        if c < room.c0 or c > room.c1 or r < room.r0 or r > room.r1 then return false end
        return not is_cut(room, c, r)
    end
    local rooms, biggest, bigsize = {}, nil, -1
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" then
            rooms[#rooms + 1] = room
            local n = #cells_of(room)
            if n > bigsize then biggest, bigsize = room, n end
        end
    end
    for _, room in ipairs(rooms) do
        local cc, cr = centre(room)
        if room == lair then
            -- Sir's room stays bare
        elseif room == biggest then
            if quiet(cc, cr) then
                add("table_m_re a", cc, cr, 0.5, 0.5, yaw0)
                add("chair a", cc, cr, 0.5, 0.5 + 125.0 / CELL, yaw180)
            end
        else
            local roll = rng:below(100)
            local north = rng:below(2) == 0
            local q = north and 0 or 2
            local row = north and room.r0 or room.r1
            if roll < BACK_ROWS then
                for c = room.c0, room.c1 do
                    if contains(room, c, row) and quiet(c, row) and side_kind(lay, c, row, q) == WALL then
                        for _, fz in ipairs(north and {0.22, 0.48} or {0.78, 0.52}) do
                            for _, fx in ipairs({0.25, 0.5, 0.75}) do add("chair a", c, row, fx, fz, north and yaw180 or yaw0) end
                        end
                    end
                end
            elseif roll < BACK_BEDS then
                for c = room.c0, room.c1 do
                    if contains(room, c, row) and quiet(c, row) and side_kind(lay, c, row, q) == WALL then
                        add("bed b01", c, row, 0.5, north and 0.2 or 0.8, bed, BED_HALF)
                    end
                end
            elseif roll < BACK_CENTRE then
                local name = rng:pick(BACK_CENTRE_PROPS)
                add(name, room.c0, room.r0, (room.c1 - room.c0 + 1) / 2, (room.r1 - room.r0 + 1) / 2, yaw0)
            elseif roll < BACK_TWIN then
                local c, r = room.c0 + 1, room.r0 + 1
                if contains(room, c, r) and quiet(c, r) then
                    add("chair a", c, r, 0.3, 0.3, yaw0)
                    add("bucket wod a01", c, r, 0.7, 0.3, yaw0)
                end
            end
        end
    end
    return out
end

-- The backrooms for (seed, area): a vast plain level of the area's own stone, every lamp alike and dull,
-- no props, no one; the key to the way back in the room farthest from it, the exit raising EndlessBack.
-- Mirrors endless_gen.build_backrooms step for step.
function gen.build_backrooms(t, seed, area)
    checkpoint()
    local w, h = BACK_GRID, BACK_GRID
    local rng = Rng.new(seed ~ 0xBAC4, area)
    local stage = gen.stage_of(t, area)
    local sc, sr = floor(START_X / CELL) + w // 2, floor(START_Z / CELL) + h // 2
    local lay = generate_layout(rng, w, h, 1, sc, sr, "backrooms", false, true)
    for i = 0, lay.nrooms - 1 do lay.rooms[i].style = 0 end
    local cells, styles = {}, {}
    for r = 0, h - 1 do for c = 0, w - 1 do
        local word, style = encode_cell(lay, c, r)
        cells[#cells + 1] = word
        styles[#styles + 1] = style
    end end
    local layer0 = spack("<" .. string.rep("I4", #cells), table.unpack(cells))
    local layer2 = spack("<" .. string.rep("I4", #styles), table.unpack(styles))
    local names = stage and (names_block(stage.walls) .. names_block(stage.floors)) or t.grid_names
    local grid = names .. spack("<I4I4I4I4", w, h, 0, 600) .. layer0 .. string.rep("\0", 4 * w * h) .. layer2
    local nodes = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind ~= "maze" then
            local cc, cr = centre(room)
            local x, z = world(cc, cr, w, h)
            local span = math.max(room.c1 - room.c0, room.r1 - room.r0)
            nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, BACK_LIGHT[1], BACK_LIGHT[2], BACK_LIGHT[3], BACK_STRENGTH, 2.0, 600 + 150 * span)
        end
    end
    for k = 1, #lay.corridor do
        if (k - 1) % 6 == 1 then
            local x, z = world(lay.corridor[k][1], lay.corridor[k][2], w, h)
            nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, BACK_LIGHT[1], BACK_LIGHT[2], BACK_LIGHT[3], BACK_STRENGTH, 2.0, 600.0)
        end
    end
    local node_chunk = spack("<I4", #nodes) .. table.concat(nodes)
    local ex = lay:exit_room()
    local gcc, gcr = centre(ex)
    local gx, gz = world(gcc, gcr, w, h)
    local stc, str_ = centre(lay.rooms[0])
    local sx, sz = world(stc, str_, w, h)
    local places = {
        placement(t.marker_place, 0x80000000 | t.arrival_id, sx, 100.0, sz, 0.0),
        placement(t.marker_place, 0x80000000 | t.zone_id, gx, 100.0, gz, 0.0),
    }
    local pair = (area - 1) % #t.key_ids + 1
    local ic, ir, oc, orr = lay.exit_door[1], lay.exit_door[2], lay.exit_door[3], lay.exit_door[4]
    local q = 0
    for k = 0, 3 do if oc - ic == SIDE_DX[k] and orr - ir == SIDE_DZ[k] then q = k end end
    local dx, dz = world(ic, ir, w, h)
    places[#places + 1] = placement(t.door_place, 0x80000000 | t.door_ids[pair], dx, t.floor_y, dz, SIDE_YAW[q], 1)
    local key_room, key_d
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" then
            local cc, cr = centre(room)
            local d = dist(cc, cr, ic, ir)
            if key_d == nil or d > key_d then key_room, key_d = room, d end
        end
    end
    key_room = key_room or lay.rooms[0]
    local kcell = rng:pick(cells_of(key_room))
    local kfx, kfz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
    local kx, kz = world(kcell[1], kcell[2], w, h, kfx, kfz)
    places[#places + 1] = placement(t.key_place, 0x80000000 | t.key_ids[pair], kx, t.floor_y, kz, rng:unit() * 360.0)
    lay.key_cell = {kcell[1], kcell[2]}
    local script = string.format("LuaEvent(EndlessBack,%010d_%010d);", area, seed & 0xFFFFFFFF)
    local places_chunk = chunk(TAG_ITEM_PLACES, spack("<I4", #places) .. table.concat(places))
    local item_parts = {t.item_db:sub(1, t.script_at - 1), script, t.item_db:sub(t.script_at + 44), t.item_strings, places_chunk}
    local item_size = 0
    for _, part in ipairs(item_parts) do item_size = item_size + #part end
    local lair = t.sir_demon_id ~= 0 and backrooms_lair(lay) or nil
    local objects = backrooms_props(t, lay, w, h, seed, area, gen.stage_index(t, area), lair)
    local spawns = {}
    if lair then -- Sir, facing the way you come in
        local lc, lr = centre(lair)
        local x, z = world(lc, lr, w, h)
        spawns[1] = spawn(0x80000000 | t.sir_demon_id, x, t.floor_y, z, 0.0)
    end
    local people_chunk = spack("<I4", 1 + #spawns) .. t.people_db .. table.concat(spawns)
    local a0, a1, a2 = sunpack("<fff", t.env, 0x30 + 1)
    local env = t.env:sub(1, 0x30) .. spack("<fff", a0 * 0.5, a1 * 0.5, a2 * 0.5) .. t.env:sub(0x30 + 12 + 1)
    local parts = {spack("<I4", MAGIC), chunk(TAG_GRID, grid), chunk(TAG_NODES, node_chunk), chunk(TAG_OBJECTS, spack("<I4", #objects) .. table.concat(objects)),
                   spack("<I4I4", TAG_ITEMS, item_size)}
    for _, part in ipairs(item_parts) do parts[#parts + 1] = part end
    parts[#parts + 1] = chunk(TAG_PEOPLE, people_chunk)
    parts[#parts + 1] = chunk(TAG_ENV, env)
    return table.concat(parts), lay, {backrooms = 1, boss = 0, gate = 0, props = #objects, sir = lair and t.sir_demon_id or 0}
end

return gen
