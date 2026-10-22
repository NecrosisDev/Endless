-- Golden test: mods/endless/scripts/gen.lua must produce the same bytes as the Python
-- reference for every (seed, area) pair in the golden folder.
--   lua.exe test_gen.lua <template.rfc> <template.ini> <golden dir> <gen.lua path>
local rfc, ini, golden, genpath = ...
package.path = genpath:gsub("gen%.lua$", "?.lua") .. ";" .. package.path
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
local gen = sandboxed(genpath)
local function read(path)
    local f = assert(io.open(path, "rb"))
    local s = f:read("a")
    f:close()
    return s
end
local t, why = gen.load_template(read(rfc), read(ini))
if not t then print("FAIL: template: " .. why) os.exit(1) end
assert(gen.load_terrain_template(t, read(rfc:gsub("%.rfc$", ".rft"))))
gen.load_dress(t, read((rfc:gsub("endless%-template%.rfc$", "endless-dress.bin"))))
local seeds = {1, 3, 7, 42, 123456789, 4294967295}
local areas = {1, 2, 5, 12, 30, 99}
local compared, failed = 0, 0
local clock = os.clock()
for _, seed in ipairs(seeds) do
    for _, area in ipairs(areas) do
        local mine = gen.build(t, seed, area)
        local rft = gen.build_terrain(t)
        for _, pair in ipairs({{".rfc", mine}, {".rft", rft}}) do
            local f = io.open(golden .. "/golden_s" .. seed .. "_a" .. area .. pair[1], "rb")
            if f then
                local ref = f:read("a")
                f:close()
                compared = compared + 1
                if ref ~= pair[2] then
                    failed = failed + 1
                    local i = 1
                    while i <= #ref and i <= #pair[2] and ref:byte(i) == pair[2]:byte(i) do i = i + 1 end
                    print(string.format("MISMATCH seed %d area %d %s: sizes %d vs %d, first difference at byte %d", seed, area, pair[1], #ref, #pair[2], i - 1))
                end
            end
        end
    end
end
local seconds = (os.clock() - clock) / (#seeds * #areas)
local a = gen.build(t, 9, 4)
local b = gen.build(t, 9, 4)
print(string.format("compared %d with Python (%d mismatches), deterministic %s, %.3f s per area, name(15)=%s", compared, failed, tostring(a == b), seconds, gen.floor_name(15)))
local ok = compared >= 72 and failed == 0 and a == b
print(ok and "PASS" or "FAIL")
os.exit(ok and 0 or 1)
