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
local MAGIC = 0x3D23AFCF
local TAG_GRID, TAG_NODES, TAG_OBJECTS, TAG_ITEMS, TAG_PEOPLE, TAG_ENV = 0x3DED, 0x3D000000, 0x3DE10000, 0xDBC0, 0xCAC00001, 0xEC00DC00
local TAG_SPAWN, TAG_ITEM_DB, TAG_ITEM_STRINGS, TAG_ITEM_PLACES, TAG_PEOPLE_DB, TAG_LIGHT = 0xCAC0CA00, 0xDBDB, 0xDBCD, 0xDBCE, 0xCECDDB00, 0x3D06
local START_X, START_Z = 8200.0, 3920.0 -- the game's new-game spawn (2B7684, static)
local LIGHT_Y = 300.0
local GRID_W, GRID_H = 48, 48
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
function gen.is_lever_area(area) return gen.depth_of(area) >= 3 and area % 2 == 1 end
-- two-key areas: from depth 4, on key (not lever) areas, the boss key sits in a locked room whose own key lies elsewhere
function gen.is_vault_area(area) return gen.depth_of(area) >= 4 and not gen.is_lever_area(area) end
function gen.fire_trap_count(area) local n = gen.depth_of(area) - 1 if n < 0 then n = 0 end return n < 5 and n or 5 end
function gen.push_trap_count(area) local n = gen.depth_of(area) - 2 if n < 0 then n = 0 end return n < 4 and n or 4 end
local LEVER_Y = 145.0
local BANDS = 3 -- strength bands beyond the shipped records (make_template.py writes them)
-- wall-mounted props: distance from the wall (cell fraction), height, yaw relative to the wall's side
local WALL_PROPS = {["hook mtl a01"] = {0.13, 191.0, 0.0}, ["chain_wall"] = {0.12, 210.0, 0.0}, ["uw1_shelf a"] = {0.08, 122.0, -89.0},
    ["shelf_wm b"] = {0.16, 160.0, 0.0}, ["lightglobebr a"] = {0.13, 216.0, 0.0}, ["torch holder a1"] = {0.31, 175.0, 0.0},
    ["support wall a1"] = {0.12, 203.0, 0.0}, ["hooks"] = {0.13, 177.0, 0.0}, ["hook2"] = {0.13, 177.0, 0.0}}
local DEBRIS = {["skelbase_physics"] = 14.0, ["planksn"] = 7.0, ["stoneloose a12"] = 9.0, ["bottle_wkr b"] = 34.0, ["pot"] = 22.0, ["decal9"] = 0.0, ["decal12"] = 0.0}
function gen.enemy_count(area) -- endless and steady: +3 per depth, +2 per area inside a depth, no cap
    local d = gen.depth_of(area)
    return 4 + 3 * d + 2 * ((area - 1) % AREAS_PER_DEPTH)
end
function gen.boss_minion_count(area) local n = gen.depth_of(area) - 1 return n > 0 and n or 0 end
function gen.boss_count(area) return 1 + gen.depth_of(area) // 6 end

-- ---------------------------------------------------------------- random (splitmix64 seed, xorshift64*)
local Rng = {}
Rng.__index = Rng
function Rng.new(seed, area)
    local x = seed * 0x9E3779B97F4A7C15 + area * 0xBF58476D1CE4E5B9 + 0x94D049BB133111EB -- hex literals wrap to 64-bit
    for _ = 1, 3 do
        x = x + 0x9E3779B97F4A7C15
        local z = x
        z = (z ~ (z >> 30)) * 0xBF58476D1CE4E5B9
        z = (z ~ (z >> 27)) * 0x94D049BB133111EB
        x = z ~ (z >> 31)
    end
    return setmetatable({state = x ~= 0 and x or 1}, Rng)
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
    return {c0 = c0, r0 = r0, c1 = c1, r1 = r1, kind = kind or "room", style = 0, entry = {0, 0}, goal = {0, 0}}
end
local function centre(room)
    if room.kind == "maze" then return room.entry[1], room.entry[2] end
    return (room.c0 + room.c1) // 2, (room.r0 + room.r1) // 2
end
local function contains(room, c, r) return c >= room.c0 and c <= room.c1 and r >= room.r0 and r <= room.r1 end
local function touches(a, b, gap)
    gap = gap or 1
    return not (a.c1 + gap < b.c0 or b.c1 + gap < a.c0 or a.r1 + gap < b.r0 or b.r1 + gap < a.r0)
end
local function cells_of(room)
    local out = {}
    for r = room.r0, room.r1 do for c = room.c0, room.c1 do out[#out + 1] = {c, r} end end
    return out
end
local function dist(ac, ar, bc, br) return math.abs(ac - bc) + math.abs(ar - br) end

local Layout = {}
Layout.__index = Layout
function Layout.new(w, h, rooms, nrooms)
    local owner = {}
    for i = 0, w * h - 1 do owner[i] = -1 end
    return setmetatable({w = w, h = h, owner = owner, rooms = rooms, nrooms = nrooms, doors = {}, corridor = {}, exit_door = nil}, Layout)
end
function Layout:at(c, r)
    if c >= 0 and c < self.w and r >= 0 and r < self.h then return self.owner[r * self.w + c] end
    return -1
end
function Layout:built(c, r) return self:at(c, r) >= 0 end
function Layout:is_door(ac, ar, bc, br)
    for _, d in ipairs(self.doors) do
        if (d[1] == ac and d[2] == ar and d[3] == bc and d[4] == br) or (d[1] == bc and d[2] == br and d[3] == ac and d[4] == ar) then return true end
    end
    return false
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
local function route(lay, ac, ar, bc, br, blocked)
    local w, h = lay.w, lay.h
    local INF = 1 << 30
    local best = {}
    local buckets = {[0] = {{ac, ar, -1, {{ac, ar}}}}}
    local pending = 1
    local cost = 0
    while cost < 4 * (w + h) and pending > 0 do
        local bucket = buckets[cost]
        if bucket then
            buckets[cost] = nil
            pending = pending - 1
            for _, s in ipairs(bucket) do
                local cc, cr, heading, path = s[1], s[2], s[3], s[4]
                local key = (cr * w + cc) * 5 + heading + 1
                if not ((best[key] or INF) < cost) then
                    if cc == bc and cr == br then return path end
                    for q = 0, 3 do
                        local nc, nr = cc + SIDE_DX[q], cr + SIDE_DZ[q]
                        if nc >= 1 and nc < w - 1 and nr >= 1 and nr < h - 1 and not ((nc ~= bc or nr ~= br) and blocked[nr * w + nc]) then
                            local c2 = cost + 1 + ((heading ~= -1 and heading ~= q) and 3 or 0)
                            local nkey = (nr * w + nc) * 5 + q + 1
                            if not ((best[nkey] or INF) <= c2) then
                                best[nkey] = c2
                                local np = {}
                                for i = 1, #path do np[i] = path[i] end
                                np[#np + 1] = {nc, nr}
                                if not buckets[c2] then buckets[c2] = {}; pending = pending + 1 end
                                local b = buckets[c2]
                                b[#b + 1] = {nc, nr, q, np}
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
            for r = p.r0, p.r1 do for c = p.c0, p.c1 do blocked[r * lay.w + c] = true end end
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
local function generate_layout(rng, w, h, area, sc, sr)
    local depth = gen.depth_of(area)
    local rooms = {[0] = room_new(sc - 1, sr - 1, sc + 1, sr + 1, "start")}
    local n = 1
    local wanted = 8 + 2 * depth
    if wanted > 18 then wanted = 18 end
    local attempts = 0
    while n < wanted and attempts < 600 do
        attempts = attempts + 1
        local hall = depth >= 2 and rng:chance(25)
        local rw = hall and rng:between(5, 7) or rng:between(2, 5)
        local rh = hall and rng:between(5, 7) or rng:between(2, 5)
        local c0 = rng:between(2, w - 3 - rw)
        local r0 = rng:between(2, h - 3 - rh)
        local room = room_new(c0, r0, c0 + rw - 1, r0 + rh - 1)
        local clash = false
        for i = 0, n - 1 do if touches(room, rooms[i]) then clash = true break end end
        if not clash then
            room.style = rng:chance(30) and 0x11 or 0
            rooms[n] = room
            n = n + 1
        end
    end
    local start = rooms[0]
    local stc, str_ = centre(start)
    local far, far_d = 1, -1
    for i = 1, n - 1 do
        local cc, cr = centre(rooms[i])
        local d = dist(cc, cr, stc, str_)
        if d > far_d then far_d = d; far = i end
    end
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
    local boss, gate
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
    local boss_index = -1
    if boss then rooms[n] = boss; boss_index = n; n = n + 1 end
    local lay = Layout.new(w, h, rooms, n)
    for i = 0, n - 1 do
        local room = rooms[i]
        if room.kind ~= "maze" then
            for r = room.r0, room.r1 do for c = room.c0, room.c1 do lay.owner[r * w + c] = i end end
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
    local extra = n // 3
    if extra > 4 then extra = 4 end
    for _ = 1, extra do
        local a, b = rng:below(n), rng:below(n)
        local have = false
        for _, e in ipairs(edges) do if (e[1] == a and e[2] == b) or (e[1] == b and e[2] == a) then have = true break end end
        if a ~= b and a ~= far and b ~= far and a ~= boss_index and b ~= boss_index and not have then edges[#edges + 1] = {a, b} end
    end
    for _, e in ipairs(edges) do carve_corridor(lay, rooms[e[1]], rooms[e[2]]) end
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
            table.sort(picked)
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
                table.sort(candidates, function(a, b) if a[1] ~= b[1] then return a[1] < b[1] end return a[2] < b[2] end)
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
    return lay
end

-- ---------------------------------------------------------------- grid encoding
side_kind = function(lay, c, r, q)
    local me, other = lay:at(c, r), lay:at(c + SIDE_DX[q], r + SIDE_DZ[q])
    if other < 0 then return WALL end
    if me == other then return 0 end
    return lay:is_door(c, r, c + SIDE_DX[q], r + SIDE_DZ[q]) and DOOR or WALL
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
    if not lay:built(c, r) then return ROCK, 0 end
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
    t.enemy_ids = ints(keys.enemies)
    t.enemy_tiers = {}
    for i = 2, 6 do if keys["enemies_t" .. i] then t.enemy_tiers[#t.enemy_tiers + 1] = ints(keys["enemies_t" .. i]) end end
    t.boss_tiers = {}
    for i = 1, 6 do if keys["bosses_t" .. i] then t.boss_tiers[#t.boss_tiers + 1] = ints(keys["bosses_t" .. i]) end end
    t.floor_y = tonumber(keys.floor_y)
    t.companion_ids = ints(keys.companions)
    t.companion_roles = ints(keys.companion_roles) -- each companion's main role id
    t.spot_order = {} -- talk spot index (0-based) -> companion indices (0-based) in speaking order
    for entry in (keys.spot_order or ""):gmatch("[^;]+") do
        local spot, list = entry:match("^([^:]+):(.*)$")
        if spot then
            local idx = SPOT_INDEX[spot]
            if idx then t.spot_order[idx] = ints(list) end
        end
    end
    t.proctor_boss_id = tonumber(keys.proctor_boss) or 0
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
local function build_terrain(t)
    if not t.terrain_tile then return "" end
    local flags = sunpack("<I4", t.terrain_tile, 1)
    local tag = sunpack("<I4", t.terrain_tile, 13)
    local row = spack("<" .. string.rep("f", TN), table.unpack((function() local z = {} for i = 1, TN do z[i] = 0.0 end return z end)()))
    local heights = string.rep(row, TN)
    local layers = t.terrain_tile:sub(16 + 4 * TN * TN + 1)
    local tiles = {}
    for iy = 0, 1 do for ix = 0, 1 do
        local body = spack("<I4i4i4I4", flags, ix, iy, tag) .. heights .. layers
        tiles[#tiles + 1] = spack("<I4I4", TERRAIN_TAG, #body) .. body
    end end
    return t.terrain_head .. spack("<i4i4I4", 2, 2, #tiles) .. table.concat(tiles)
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
-- stable sort by key (insertion), as Python's sorted keeps order for equal keys
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
function gen.build(t, seed, area, present)
    local w, h = GRID_W, GRID_H
    local rng = Rng.new(seed, area)
    local stage = gen.stage_of(t, area)
    local two_sets = stage and #stage.walls >= 2 and #stage.floors >= 2
    local sc, sr = floor(START_X / CELL) + w // 2, floor(START_Z / CELL) + h // 2
    local lay = generate_layout(rng, w, h, area, sc, sr)
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
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind ~= "maze" then
            local cc, cr = centre(room)
            local x, z = world(cc, cr, w, h)
            local span = math.max(room.c1 - room.c0, room.r1 - room.r0)
            if room.kind == "exit" then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, exit_r, exit_g, exit_b, 1.0, 2.0, 900 + 250 * span)
            elseif room.kind == "boss" then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.45, 0.15, 0.5, 1.0, 2.0, 900 + 250 * span)
            else nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.55, 0.38, 0.2, 1.0, 2.0, 900 + 250 * span) end
        end
    end
    for k = 1, #lay.corridor do
        if (k - 1) % 4 == 1 then
            local x, z = world(lay.corridor[k][1], lay.corridor[k][2], w, h)
            nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.35, 0.25, 0.14, 0.7, 2.0, 800.0)
        end
    end
    for k = 1, #lay.bypass_cells do
        if (k - 1) % 4 == 1 then
            local x, z = world(lay.bypass_cells[k][1], lay.bypass_cells[k][2], w, h)
            nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.35, 0.25, 0.14, 0.7, 2.0, 800.0)
        end
    end
    if ex.kind == "maze" then
        local k = 0
        for r = ex.r0, ex.r1, 2 do for c = ex.c0, ex.c1, 2 do
            if k % 2 == 0 then
                local x, z = world(c, r, w, h)
                if c == ex.goal[1] and r == ex.goal[2] then nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, exit_r, exit_g, exit_b, 0.8, 2.0, 700.0)
                else nodes[#nodes + 1] = light(t, x, LIGHT_Y, z, 0.3, 0.2, 0.1, 0.8, 2.0, 700.0) end
            end
            k = k + 1
        end end
    end
    local node_chunk = spack("<I4", #nodes) .. table.concat(nodes)
    -- props and the staircase
    local objects = {}
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind ~= "start" and room.kind ~= "maze" and room.kind ~= "boss" and room.kind ~= "closet" then
            local cells_ = cells_of(room)
            local edge = {}
            for _, cell in ipairs(cells_) do
                if cell[1] == room.c0 or cell[1] == room.c1 or cell[2] == room.r0 or cell[2] == room.r1 then edge[#edge + 1] = cell end
            end
            local count = rng:between(1, 2 + #cells_ // 2)
            for _ = 1, count do
                local cell = rng:pick(edge)
                local raw = rng:pick(t.props)
                local fx = cell[1] == room.c0 and 0.2 or cell[1] == room.c1 and 0.8 or rng:unit() * 0.6 + 0.2
                local fz = cell[2] == room.r0 and 0.2 or cell[2] == room.r1 and 0.8 or rng:unit() * 0.6 + 0.2
                local x, z = world(cell[1], cell[2], w, h, fx, fz)
                objects[#objects + 1] = object(raw, x, t.floor_y, z, rng:unit() * 360.0)
            end
        end
    end
    local function wall_prop(c, r, q)
        local pick = rng:pick(t.wall_props)
        local rule = WALL_PROPS[pick[1]]
        local dist_, height, rel = rule[1], rule[2], rule[3]
        local along = rng:unit() * 0.6 + 0.2
        local fx = (SIDE_DX[q] ~= 0) and (0.5 + (0.5 - dist_) * SIDE_DX[q]) or along
        local fz = (SIDE_DZ[q] ~= 0) and (0.5 + (0.5 - dist_) * SIDE_DZ[q]) or along
        local x, z = world(c, r, w, h, fx, fz)
        objects[#objects + 1] = object(pick[2], x, height, z, SIDE_YAW[q] + rel)
    end
    if #t.wall_props > 0 then
        for i = 0, lay.nrooms - 1 do
            local room = lay.rooms[i]
            if room.kind ~= "start" and room.kind ~= "maze" and room.kind ~= "boss" and room.kind ~= "closet" then
                local walls = {}
                for _, cell in ipairs(cells_of(room)) do
                    for q = 0, 3 do if side_kind(lay, cell[1], cell[2], q) == WALL then walls[#walls + 1] = {cell[1], cell[2], q} end end
                end
                for _ = 1, rng:between(1, 1 + #walls // 4) do
                    local pk = rng:pick(walls)
                    wall_prop(pk[1], pk[2], pk[3])
                end
            end
        end
        for k = 1, #lay.corridor do
            if (k - 1) % 5 == 3 then
                local cell = lay.corridor[k]
                local walls = {}
                for q = 0, 3 do if side_kind(lay, cell[1], cell[2], q) == WALL then walls[#walls + 1] = q end end
                if #walls > 0 then wall_prop(cell[1], cell[2], rng:pick(walls)) end
            end
        end
    end
    if #t.debris > 0 then
        for i = 0, lay.nrooms - 1 do
            local room = lay.rooms[i]
            if room.kind ~= "start" and room.kind ~= "maze" and room.kind ~= "closet" then
                local cells_ = cells_of(room)
                for _ = 1, rng:between(0, 1 + #cells_ // 3) do
                    local cell = rng:pick(cells_)
                    local pick = rng:pick(t.debris)
                    local fx, fz = rng:unit() * 0.8 + 0.1, rng:unit() * 0.8 + 0.1
                    local x, z = world(cell[1], cell[2], w, h, fx, fz)
                    objects[#objects + 1] = object(pick[2], x, DEBRIS[pick[1]], z, rng:unit() * 360.0)
                end
            end
        end
    end
    -- four pillars in the inner corners of the boss room (rooms are 4..5 cells a side); spawns avoid them
    local pillar_cells = {}
    local boss_room = lay:boss_room()
    if t.pillar and boss_room and boss_room.c1 - boss_room.c0 >= 3 and boss_room.r1 - boss_room.r0 >= 3 then
        pillar_cells = {{boss_room.c0 + 1, boss_room.r0 + 1}, {boss_room.c1 - 1, boss_room.r0 + 1}, {boss_room.c0 + 1, boss_room.r1 - 1}, {boss_room.c1 - 1, boss_room.r1 - 1}}
        for _, cell in ipairs(pillar_cells) do
            local x, z = world(cell[1], cell[2], w, h)
            objects[#objects + 1] = object(t.pillar, x, t.floor_y, z, 0.0)
        end
    end
    local gc, gr
    if ex.kind == "maze" then gc, gr = ex.goal[1], ex.goal[2] else gc, gr = centre(ex) end
    local gx, gz = world(gc, gr, w, h)
    if staircase then objects[#objects + 1] = object(t.stairs, gx, t.floor_y, gz, rng:unit() * 360.0) end
    local object_chunk = spack("<I4", #objects) .. table.concat(objects)
    -- items
    local start = lay.rooms[0]
    local stc, str_ = centre(start)
    local sx, sz = world(stc, str_, w, h)
    local places = {
        placement(t.marker_place, 0x80000000 | t.arrival_id, sx, 100.0, sz, 0.0),
        placement(t.marker_place, 0x80000000 | t.zone_id, gx, 100.0, gz, 0.0),
    }
    local ic, ir, oc, orr = lay.exit_door[1], lay.exit_door[2], lay.exit_door[3], lay.exit_door[4]
    local q = 0
    for k = 0, 3 do if oc - ic == SIDE_DX[k] and orr - ir == SIDE_DZ[k] then q = k end end
    local dx, dz = world(ic, ir, w, h)
    places[#places + 1] = placement(t.door_place, 0x80000000 | t.door_ids[pair], dx, t.floor_y, dz, SIDE_YAW[q], 1)
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
    local by_distance = stable_sort(candidates, function(room) local cc, cr = centre(room) return dist(cc, cr, ic, ir) end)
    local far_half = {}
    for i = #by_distance // 2 + 1, #by_distance do far_half[#far_half + 1] = by_distance[i] end
    local vaults = {}
    if gen.is_vault_area(area) then
        for _, room in ipairs(far_half) do
            local n = 0
            for _, d in ipairs(lay.doors) do if contains(room, d[1], d[2]) or contains(room, d[3], d[4]) then n = n + 1 end end
            if n == 1 then vaults[#vaults + 1] = room end
        end
    end
    local key_room = #vaults > 0 and rng:pick(vaults) or rng:pick(far_half)
    local kcell = rng:pick(cells_of(key_room))
    lay.key_cell = {kcell[1], kcell[2]}
    local kfx, kfz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
    local kx, kz = world(kcell[1], kcell[2], w, h, kfx, kfz)
    if gen.is_lever_area(area) then
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
    if per_spot > 0 and not gen.is_lever_area(area) then
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
    for i = 0, lay.nrooms - 1 do
        local room = lay.rooms[i]
        if room.kind == "room" and rng:chance(45) then
            local cell = rng:pick(cells_of(room))
            local x, z = world(cell[1], cell[2], w, h)
            local id = rng:pick(chests)
            places[#places + 1] = placement(t.chest_place, 0x80000000 | id, x, t.floor_y, z, rng:unit() * 360.0)
        end
    end
    local script = string.format("LuaEvent(EndlessNext,%010d_%010d);", area, seed & 0xFFFFFFFF)
    local item_db = t.item_db:sub(1, t.script_at - 1) .. script .. t.item_db:sub(t.script_at + 44)
    local item_chunk = item_db .. t.item_strings .. chunk(TAG_ITEM_PLACES, spack("<I4", #places) .. table.concat(places))
    -- people
    local enemies = gen.enemy_count(area)
    local roster = enemy_roster(t, depth)
    local keep_out = depth == 1 and 6 or depth == 2 and 4 or 2
    local spawns = {}
    local homes = {}
    for i = 0, lay.nrooms - 1 do
        local k = lay.rooms[i].kind
        if k ~= "start" and k ~= "exit" and k ~= "boss" and k ~= "closet" then homes[#homes + 1] = lay.rooms[i] end
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
        for _ = 1, gen.boss_count(area) - 1 do
            local cell = rng:pick(boss_cells)
            local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
            local x, z = world(cell[1], cell[2], w, h, fx, fz)
            local extra = rng:pick(bosses)
            spawns[#spawns + 1] = spawn(0x80000000 | extra, x, t.floor_y, z, rng:unit() * 2 * math.pi)
            info.bosses[#info.bosses + 1] = extra
        end
        for _ = 1, gen.boss_minion_count(area) do
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
        if ok and dist(c, r, stc, str_) < keep_out then ok = false end
        if ok then
            local fx, fz = rng:unit() * 0.6 + 0.2, rng:unit() * 0.6 + 0.2
            local x, z = world(c, r, w, h, fx, fz)
            local who = 0x80000000 | rng:pick(roster)
            spawns[#spawns + 1] = spawn(who, x, t.floor_y, z, rng:unit() * 2 * math.pi)
        end
    end
    if #t.companion_ids > 0 and (area - 1) % AREAS_PER_DEPTH == 1 then
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
            local which = (depth - 1) % #t.companion_ids -- 0 Tobin (depth 1), 1 Aldric, 2 Mira
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
            local cid = t.companion_ids[(depth - 1) % #t.companion_ids + 1]
            spawns[#spawns + 1] = spawn(0x80000000 | cid, x, t.floor_y, z, rng:unit() * 2 * math.pi)
            info.companion = cid
        end
    end
    local people_chunk = spack("<I4", 1 + #spawns) .. t.people_db .. table.concat(spawns)
    local scale = 1.0 - 0.15 * (depth - 1)
    if scale < 0.4 then scale = 0.4 end
    local a0, a1, a2 = sunpack("<fff", t.env, 0x30 + 1)
    local env = t.env:sub(1, 0x30) .. spack("<fff", a0 * scale, a1 * scale, a2 * scale) .. t.env:sub(0x30 + 12 + 1)
    return spack("<I4", MAGIC) .. chunk(TAG_GRID, grid) .. chunk(TAG_NODES, node_chunk) .. chunk(TAG_OBJECTS, object_chunk)
        .. chunk(TAG_ITEMS, item_chunk) .. chunk(TAG_PEOPLE, people_chunk) .. chunk(TAG_ENV, env), lay, info, build_terrain(t)
end

return gen
