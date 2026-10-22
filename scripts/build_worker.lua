-- Endless builds on a runtime worker thread (tasks.worker, runtime 0.28.0-r41): a Lua state of its own with
-- no game API, so the build costs the game's frames nothing. The mod (main.lua build_area / enter_backrooms)
-- sends the template files and what the build reads, and gets back the level, its info and the terrain.
-- On older runtimes the mod builds with tasks.run instead; this module is then never loaded.
local gen = require("gen")

return function(input)
    local t, why = gen.load_template(input.rfc, input.ini)
    if not t then error("template rejected: " .. tostring(why)) end
    local ok, why2 = gen.load_terrain_template(t, input.rft)
    if not ok then error("terrain template rejected: " .. tostring(why2)) end
    gen.load_dress(t, input.dress)
    local bytes, info
    if input.kind == "backrooms" then
        local b, _, i = gen.build_backrooms(t, input.seed, input.area)
        bytes, info = b, i
    else
        local b, _, i = gen.build(t, input.seed, input.area, input.present, input.met, input.opts)
        bytes, info = b, i
    end
    t.dress = nil
    return {bytes = bytes, info = info, terrain = gen.build_terrain(t)}
end
