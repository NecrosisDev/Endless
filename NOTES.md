# Endless: developer notes

How the generator, the mod and the tools work, and why (the player-facing text is README.md). Moved here
from the README on 2026-10-22 when the README was rewritten for players.

- **Terrain template at load time** (2026-10-22): `assets/endless-template.rft` is the head (28 bytes),
  a 1 x 1 grid and the first tile of `exanima01.rft` (rebuilt byte-identical offline). A build without
  the game-derived files makes it in `main.lua` `terrain_template()` from the player's game through
  `levels.read` and keeps it in `cache/endless-template.rft`. `levels.read` refuses members over 8 MiB
  and `exanima01.rft` is 9.1 MB, so on runtimes before r54 `exanima02.rft` (same head, a different first
  tile; terrain 2.3 MB instead of 1.4) serves. From r54 a ranged read of exanima01.rft's first 354,414
  bytes gives the shipped bytes (checked offline against the real file with the builder's own code).
- **Easter egg 1 dropped** (Hunter, 2026-10-22: "last descent makes no sense if each run is randomized"):
  no remains at the last run's area; `last_area` is gone from `build_floor`/`gen.build` opts and the key.


An **ENDLESS** row on the title menu, directly under ARENA, starts a run of procedurally
generated dungeon areas that never end. Each area hides a **key** (deeper, a **lever**) that
opens the area's locked **boss room**; **beating the boss opens the gate** (a portcullis) to
the exit, and the zone past it generates and loads the next area.
Every third area the exit is a **staircase down** and the depth rises: more rooms and halls,
tougher enemies (level 2 and 3 rosters join), the exit becomes a **maze**, and **fire** and
**push traps** appear in corridors. Progress survives CONTINUE: the area number and run seed
live inside the level's exit script.

## Layout

| Path | Role |
|---|---|
| `manifest.toml` | runtime id, entry, modules, capabilities; the names `levels.flow`, `player.place`, `assets.read` and `[script.overrides]` are the 0.26.0 plan, unverified against a shipped runtime |
| `LIVE-RUN.md` | the first live run, step by step, with the `Endless:` log line or capture that proves each step |
| `scripts/gen.lua` | the area generator: pure Lua, byte-identical to the Python reference `generator/endless_gen.py` |
| `scripts/main.lua` | the mod: title row, run start, boss watch, travel between areas, arrival placement, hazards; every milestone logs one `Endless:` line |
| `assets/endless-template.rfc` + `.ini` + `.rft` | the template level (and one flat terrain tile) made by `generator/make_template.py` from the installed `Resource.rpk` (exanima01, Hellmode) |

## How it works (static; nothing has run in the game yet)

- An area is a complete level file (.rfc) built from exanima01's wall/floor sets, one light
  node, prop entries, its level-local item database (chests with the game's loot lists, plus the
  Endless records: 4 key/door/cache/lever quadruples, a fire operative, hazard zones, an arrival
  marker and the exit zone) and a merged character database: six enemy tiers that join one
  per depth (zombies and skeletons of levels 1–3, then ghouls, gobblers and ember knights, then
  fael, living armour and manipulators, then golems and the deep skeletons), the newest two tiers
  weighted. Enemy counts grow without a cap: +3 per depth and +2 per area (106 at area 100).
- The runtime serves the bytes under an existing arena level name (`arenao1`…, cycling through
  14), starts the run as a new story character on the served member, travels by name
  (dropping any stored copy of that name from the save first) and places the player at the
  game's constant start point, where every area builds its start room.
- The exit zone runs `LuaEvent(EndlessNext,<area>_<seed>);`. The mod travels only when the
  *player* enters that zone (`zone.enter`, `is_player`), using the area/seed from the script event.
- The boss room touches the exit at its entry; its only corridor door is the keyed one, the gate
  is its only other doorway. Bosses come in six tiers by depth (level 1 knights, dark knights,
  ghost knights and the Proctor, the Ember boss, the Blademaster, the Golem/Ancient/Shadow bosses);
  a second boss joins from depth 6 and a third from depth 12; minions grow one per depth. The mod polls the boss's `dead` flag and drives the gate open
  (`levels.drive`, the lever path); CONTINUE rebuilds the ids from the exit script's area_seed.
- Hazard zones carry their kind in the ZoneID: 11–15 fire slots (the mod drives that fire
  operative on and applies a short burn through `player.damage`), 2–5 push toward N/W/S/E
  (`player.push`). Fire and arcs do no damage on their own in this engine (byte-level).
- 14 of 300 test areas found no room for a boss room; those fall back to the key opening the
  exit directly.
- **Secret passages** (from depth 2): an extra corridor whose two doorways carry the shipped
  wall-looking secret door, each opened by a brick switch on that room's wall.
- **Rooms grow out of each other** (Hunter, 2026-10-22: the areas were mostly hallways). A new room
  is placed beside one already placed, on a random side, a gap of ground away (`gap` per archetype:
  1-3 cells, the mine 4-8), overlapping it along that side; rooms are bigger (warren 3-6 cells, halls
  4-7). Corridors fell from about half of the built cells to a quarter (25,202 room cells to 8,042
  corridor cells over 120 areas), and the build got cheaper with them.
- **Bigger areas** (Hunter, 2026-10-22): each archetype tries for twice the rooms (warren 16, crypt
  22, cistern 12, mine 8, halls 12, plus two per depth, at most 28) with larger sizes (warren 3-7,
  halls 5-8, their halls up to 9). Over 105 generated areas the built floor is a median 495 cells
  (182 to 1,120; level 1 of the game is 661), 20 rooms, corridors a fifth of it. A build is 2.5 to
  4.1 million instructions, 13 to 21 task pulses.
- **Twice the size, growing with depth** (Hunter, 2026-10-22). The grid is 56 cells a side at depth
  1, 60 at depth 2 and 64 from depth 3 (64 x 64 is the largest grid the game's own levels use, so
  it stops there); each plan tries for twice its rooms plus three per depth, up to 60. Over 150
  areas: depth 1 a median 946 built cells and 37 rooms (was 495 and 20), depth 4 992 and 49,
  depth 10 1,323 and 51. A build is now 9.6 to 12.4 million instructions, 48 to 62 task pulses,
  about a second at 60 frames; a deep build peaks near 13.4 MiB of Lua.
- **Barricaded doors** (Hunter): 1 + depth / 2 doorways a level (at most 4) between an ordinary
  room with two doorways or more and a corridor are blocked from the room side by a barricade with
  crates or a barrel heaped beside it, each only when everything the player can reach (secret
  doors shut) stays reachable without it, so another way in always exists. The solvability check,
  the wing gate's cut test and its lever, and the vault key all treat them as shut. Barricades are
  themed like every prop, so they appear only on stones whose levels place them (the catacombs,
  the lower halls and level 7's brick); about 1.4 a level over 150 areas.
- **Puzzles dividing the area** (Hunter, 2026-10-22). *Main*: a portcullis on the one doorway or
  corridor edge every way to the boss door passes (secret doors counted open, so no passage goes
  round it), chosen walking back from the boss door so the wing holds two ordinary rooms where it
  can, else one; its lever (the template's spare boss-gate/lever pair) is on the near side as far
  from the gate as possible, in a dead end where one is reachable. About half the areas have one;
  in the rest the boss door's key is the only gate. *Hidden*: a 2x2 treasury off an ordinary room
  behind the wall-looking secret door, opened by the brick switch on that room's wall, holding a
  chest from the deepest loot tier and the second healing salve (the first is in the quiet room).
  The vault's own key is always on the near side of the wing gate, which may stand in the vault.
  410 generated areas solvable (`solvable()` counts the wing gate and the treasury door).
- **Dressing** (Hunter, 2026-10-22: props clipped the walls and left the middle of rooms empty).
  `make_template.py` cuts every built cell of each stage's own shipped levels whose sides are plain
  walls, doorways or open into a cell dressing: its 1..8 objects (no stairs, doors, portcullises,
  levers, chests or bridges) with offsets from the cell centre and heights from that level's floor,
  turned into one of five wall patterns (none, one wall, corner, passage, dead end), up to 80 per
  stage and pattern (`assets/endless-dress.bin`, about 0.9 MB, built from the game's data and not
  committed). The generator dresses 70 % of ordinary room cells (95 % under a collapse) and 30 % of
  corridor cells with a dressing of the cell's own wall pattern turned to fit, preferring for a
  room one that holds its purpose's props. So furniture sits where the game itself put it relative
  to the walls, the middle of rooms is used, and every piece comes from a level of that stone. The
  old scattered props, wall props and debris are gone. An area carries about 1,200 to 2,200
  objects (level 1 of the game: 3,400). The mod parses the dressing file inside the build task
  (about 0.3 M instructions, once).
- **Rooms that tell a story** (Hunter, 2026-10-22: "a table should have some chairs at random
  rotations, maybe one knocked over ... a latrine, a kitchen, a barracks; take vanilla rooms as
  prefabs"). The dressing file (now `EDR2`, about 2.2 MB) also keeps every enclosed rectangular
  room of each stage's own levels whole (2..7 cells a side, 3 objects or more; 68 rooms for the
  catacombs) with a tag read from what is in it: store, barracks (beds), kitchen (tables, seats,
  cookpots), latrine (latrines, buckets, washtubs), workshop (logs, planks, saws, dye pots),
  shrine (coffins), gaol (cages, cells), surgery (stretchers, bathtubs), study. Room purposes gained
  latrine and workshop. An Endless room takes one source room for its purpose (any room of the
  stage when that stone has none, and then the purpose follows what the room holds; the quiet
  room keeps its purpose) and fills its cells from that room's cells of the same wall pattern,
  each source cell once per room (same-tag rooms next; a cell with nothing left stays clear).
  Upright chairs and stools are then turned up to 30 degrees either way, and in about a third of
  the rooms one is knocked over in a pose the game's own levels use for that seat (263 such poses
  in the catacombs). Seats the game itself left knocked over come along with their rooms, so a
  wrecked mess hall stays wrecked. Corridors keep the per-cell pools.
- **Rooms and their neighbours** (Hunter, 2026-10-22: big and small rooms, rooms that need certain
  neighbours, rooms that cannot sit by others). After purposes and source rooms are chosen, a
  deterministic pass swaps purposes (with their source rooms) between ordinary rooms where that
  lowers the broken rules around both: a kitchen wants a store or another kitchen (a mess) within
  4 cells when the area has a store; the gaol and the latrine keep away from the kitchen; the
  shrine keeps away from kitchens, barracks, latrines, workshops and stores; latrines, gaols and
  stores are rooms of 16 cells or fewer, kitchens, barracks and shrines of 6 or more. Over 40
  areas the kitchen and shrine clashes fell from 63 to 7. The quiet room never moves.
- **Rooms by scale**: a room's source room is picked among those of its purpose within a factor of
  two of its own size (else the closest), so a small room takes a private kitchen and a big one a
  mess hall where the stone has both. Purposes are arranged by size and neighbours first, then
  the source rooms are chosen, then arranged once more where a stone's rooms moved a purpose.
- **Loose items**: the dressing file (`EDR3`) carries each source cell's loose clutter items (cups,
  bowls, jugs, bottles, candles, an inkpot...) with their record imported into the template, placed
  as they lay and capped at 200 an area. Books, parchments and scrolls are excluded (nothing
  readable down here, and some teach skills). The game's own rooms hold almost none of these as
  items: the bottles, trays and baskets on its tables are scenery objects, already copied with the
  room, so the shipped stones yield four placements in all (an inkpot among them).
- **Frame budget**: the room dressing chance falls from 70 % as an area passes 900 room cells (not
  below 35 %), and no cell is dressed once the area holds 3,000 objects (the game's level 1 has
  about 3,400): over 60 areas a median of 2,355 objects, at most 3,048.
- **Easter eggs** (Hunter, 2026-10-22; their lines wait for his approval in
  `companions/DRAFT-easter-eggs.md`, the places are built and silent):
  1. *Your last descent*: in the area where the previous run ended (the run summary's area), remains
     lie in the room farthest from the start. Remains are the game's skeleton prop, which only the
     catacombs and lower halls place, so on other stones this one does not appear.
  2. *The twelfth name*: from depth 2, 15 % of areas with a gaol hold remains by the bars of the
     first one (same stones).
  3. *Bram's shrine*: the carving from level 7 (`carving stla a1`, pulled into the template from that
     level) stands in the treasury once a run, from depth 6, on level 7's stone; remembered in storage
     `endless.shrine` across CONTINUE.
  4. *A perfect copy*: 4 % of catacomb areas turn one ordinary room of a source room's exact size into
     that room exactly, every cell in its original turn (the dressing file, now `EDR4`, keeps each
     room's size and each cell's turn).
     *The backrooms* (Hunter, 2026-10-22): a chair in the copy's corner faces the wall; the template's
     `Endless Wall` zone (ini `wall_zone`) sits in the corner behind it. Walking in builds
     `gen.build_backrooms` for this area (a 64-cell plain plan of the same stone, one dull yellow light,
     no one), served as `floor_name(area + 7)`. Its furniture is sparse and wrong (`backrooms_props`, its own rng): two rows of chairs facing a north or south wall, beds stood on end, one prop square at a room's exact middle, the same chair and bucket in the same spot room after room, and a table set for one in the biggest room; only `chair a`, `table_m_re a`, `bed b01`, `coffin01`, `bucket wod a01`, `stool a` as the stone's own dressing has them, never in a doorway cell or the key's cell. Sir, the Archives' demon (ini `sir_demon`, record `Sir36`, full strength), waits in the ordinary room nearest half the farthest room's distance from the start (`backrooms_lair`, never the key's room); that room stays bare. Its locked way out has its key in the room
     farthest from the door; the exit raises `EndlessBack` and the mod travels back to the area and
     places you in the copy room (`info.copy_x/z`). Untested live: whether the area keeps its state
     (killed boss, opened gate, loot taken) when you come back.
  5. *Depth 13*: every lamp cold blue, whatever the stone.
  6. *The quiet chair*: at depth 50 and every 50 after, the quiet room holds one chair by its north
     wall and nothing else of the dressing.
  The mod publishes `LuaFlag(endless_egg_memorial / _elara / _shrine / _copy)` for the lines to come.
- **Plan shape** (2026-10-22, tuned with `tests/measure_vanilla.py` against the 14 shipped levels): the
  first third of the rooms is a spine, each beside the last and mostly heading one way; the rest are wings,
  half beside the newest room (a district grows) and half off a spine room. Extra corridors join each room
  to one of its three nearest rooms it is not yet joined to (`LOOP_BASE`, `LOOP_PER`). Doorways per room
  3.33 (vanilla 3.30), dead-end rooms 18 % (17 %), loops 22 (27.5); rooms stay about twice vanilla's size.
  The exit is the farthest room that a boss room fits beside (`EXIT_TRIES`): before, about 1 area in 15
  had no boss.
  Room outlines: the dressing file (now `EDR5`) also keeps every vanilla room on the stage's levels that is
  not a full rectangle (3..7 cells a side; 12 to 43 per stage); 30 % of ordinary rooms take one of their
  stone's outlines, doubled when it is 4 cells a side or less, as the cut of their rectangle.
  Corridors wander: a turn costs 2 and each cell 0..2 more from a hash of its place and the area
  (`TURN_COST`, `_wander`); a quarter of corridors 8 cells or longer get a second lane along their middle
  third (`WIDE_MIN`, `WIDE_CHANCE`). Corridor share of the floor 17 % (vanilla 15 %).
  Walkways: in an ordinary room the cells on the shortest ways from its first doorway to each other
  doorway (to its middle when it has one) keep only dressing that sits toward the cell's edge
  (`walkway`, `WALK_CLEAR` 0.3 of a cell); about 7 % of the dressing is left out for them.
  Furniture groups: before the cell-by-cell dressing, half of the free 2x2 patches of an ordinary room take a
  whole 2x2 block of the room's source room whose cells have the same walls in the same turns
  (`GROUP_CHANCE`), so a table, its chairs and what is on it land together.
  One event per room (`EVENT_FIGHT` 15, `EVENT_LOOTED` 30, `EVENT_HURRY` 50 out of 100, else tidy): a fight
  knocks every seat that can fall and scatters 3 of the stone's own debris (never remains: those stay the
  easter eggs'); looted halves the dressing and takes no groups; a hurry shoves seats up to 60 degrees and
  knocks one; tidy leaves them within 8 degrees. This replaces the old one-in-three knocked seat.
  Light by use: an ordinary room's lamp hangs halfway between its middle and the middle of the objects
  standing in it, and its strength follows the room's use (`USE_LIGHT`: work rooms brighter, stores,
  latrines and cells dimmer); the number of lamps is unchanged.
  Close quarters (Hunter, 10:07): after the exit and the boss room, small rooms of 2 to 3 cells a side
  are tucked one cell from any room where ground is left (`FILL_SHARE` 35 % more rooms, 75 at most).
- **Density and orientation, second pass** (2026-10-22): every ordinary-room cell is dressed (`DRESS_ROOM_CHANCE`
  100, corridors 90 %), a purpose's source cells repeat once all are used, `OBJECT_CAP` 5200 (vanilla level
  5's objects per cell; areas carry 3,700-4,700). Ordinary rooms 4.5 objects per cell, corridors 3.5 (the
  census below counts special rooms and wide corridors too). `tests/check_orientation.py` compares with
  vanilla levels 1-3: no wall piece turned unlike vanilla's own for that model, nothing tipped that vanilla
  never tips, wall pieces off any wall 34 % (vanilla 33 %), seats facing their table 41 % (56 %). A wall
  piece pressed against a doorway side with no wall beside it is left out (`HUNG_NEAR`); `SEAT_JITTER` 15.
- **Decoration density** (2026-10-22, `tests/measure_dressing.py`, vanilla levels 1-3 against depth 1):
  room objects per cell 3.3 (vanilla 5.1, was 2.4), corridor 2.1 (4.1, was 0.8), wall-hung pieces per room
  wall side 1.07 (1.15, was 0.73), floor decals per cell 0.18 (0.18, was 0.05). Dressing chances 90/60 %,
  `OBJECT_CAP` 4200 (areas reach it rarely). Wall dressing by purpose (`WALL_DRESS_CHANCE`): bare walled
  cells take a wall-hung piece from the stone's rooms of the same purpose and wall class (the wall-prop
  table `WALL_PROPS` stays loaded by the template but nothing places it). Floor decals by use
  (`WALK_DECAL_CHANCE`, `DECAL_FIGHT`, `DECAL_KITCHEN`) from the stone's own decal models. Corridor clutter
  (`CORRIDOR_CLUTTER`, `DOORWAY_DRESS`): the stone's debris at bends and junctions, a wall piece by doorways.
  Stories across rooms: a room behind a barricade is a fight; a fight leaves a trail of floor marks down
  the corridor from its first doorway (`TRAIL_LEN`, `TRAIL_CHANCE`); a store beside a kitchen is dressed in
  every cell. One showpiece per area (`pick_showpiece`, `SHOW_TAGS`): a room whose size matches a whole
  vanilla room of its purpose on this stone (shrine, surgery, workshop, kitchen first, then barracks,
  store, gaol, latrine) is dressed as that room exactly, as the perfect copy is but without its chair.
- **Corridor sectors** (2026-10-22, from a static decompile of the game's culling at 141840, 143C20,
  5B170, 58CD0): the game makes one sector of every run of cells joined by open sides (a doorway side
  ends it), draws the camera's sector whole, the sectors one doorway away only through their openings,
  and nothing further. Endless corridors were one open network, one sector the size of the area, so from
  any corridor the game drew all of it and nearly every room. `_segment_corridors` cuts corridors into
  pieces of at most `SEG_MAX` 8 cells joined by doorway sides (corridor pieces per area 75, vanilla 67,
  before 54); `side_kind` gives those corridor-to-corridor doorways. Not measured live.
- **Builds on a worker thread** (runtime r41 `tasks.worker`): every area and backrooms build runs in
  `scripts/build_worker.lua` (a [script.modules] entry) on a runtime worker thread, in a Lua state of its
  own, so none of it runs in the game's frames; it is sent the four template files and the build inputs
  and returns the level, its info and the terrain together. The runtime cancels a job on the way to the
  menu without calling back, so the mod's menu handler clears its build flag itself. Runtimes without
  workers build with `tasks.run` as before (the 50k background budget, the checkpoints).
- **Boss pen** (Hunter, 2026-10-22): 40 % of boss rooms get a 2x2 pen off one side (about 30 % of areas
  once space allows), its portcullis (gate pair `pair + 1`) placed down and raised by the mod on arrival,
  its lever on a wall of the boss cell beside the doorway. When the lever's position (`world.levers`)
  moves by half its travel while the living boss stands in the pen's box, the boss counts as beaten: the
  mod drops the pen gate, sets `endless_boss_caged` and opens the exit gate. The game has no pits or
  trapdoors (KNOWLEDGEBASE), so the pen is a cage, not a drop. Not seen live: whether bosses follow
  into a 2x2 pen, and the lever's travel values.
- **Build cost** (2026-10-22): an area build is about 20 M Lua instructions (was 33 M after the overhaul),
  so about 100 frames of the runtime's fixed 200k-instruction task budget, typically 2 to 3 ms of a frame
  offline. Lua-side only, output unchanged: doorway lookups through a set (`Layout:is_door`), the wing-gate
  search stops at its target, `side_kind` and the hot searches read the grid directly, and the router's
  wander costs come from a grid made once. The runtime's profiler logs the live cost as `task`. Since
  runtime r40 the build ahead runs at `tasks.run(fn, {budget = 50000})` (`BACKGROUND_BUDGET`: about 400
  frames, a quarter of the default's share of each); builds the player waits on (the exit with no build
  ahead, the backrooms, the terrain) keep the default 200k. Older runtimes ignore the option.
- **Built ahead** (2026-10-22): five seconds after arriving, the next area builds in the background from
  the party as it is then; at the exit it is served at once when the party present, the companions met,
  the last descent and the shrine are unchanged (`build_inputs`), else built again. One build at a time:
  the exit and the backrooms corner wait for a running build. A menu cannot stop a running task, so its
  result is dropped (`state.run`): the build stops at its next checkpoint (`gen.cancelled`, a pcall'd
  error, no effect on output) and a CONTINUE or new run starts after it, even once the game has gone on
  to the character screen (fixed 2026-10-22: such a run used to be dropped, and the game started the
  story's first level instead). The exit script's area only
  restores a run the mod knows nothing of. The backrooms task now loads the dressings (its furniture
  was missing in the game).
- **Light School casts** (Hunter, 2026-10-22: companions use Guiding Light and Glare): Mira and Tobin,
  each only after their talent is granted; Aldric never. When anyone in the party was just hit (each caster
  at most every 12 s) the mod sends Glare, in a boss fight (every 60 s) Guiding Light: one caster per power
  per poll, Mira first, as `addons.send("com.necrosis.light-orb", "light.cast", {caster = {handle}, power})`
  (runtime 0.28.0-r37, Light School 0.17.0; the record id when a row has no handle).
- **Companion record order** (fixed 2026-10-22): the template now numbers the companion records in the
  order they are found (Tobin 2731, Aldric 2732, Mira 2733), which everything reads; it used to number
  them alphabetically, so depth 1 found Aldric and Mira's reveal granted her powers to Tobin's record.
- **Title row**: plain ENDLESS like the game's own rows; the deepest depth and last descent go on a
  smaller second line where the runtime offers row subtitles, and on screen when a descent starts.
- **Area archetypes** (Hunter's review, 2026-10-22): from depth 2 every area is one of five plans
  that change the layout rules: a warren (the original: 2..5-cell rooms, a few halls, loops), a
  crypt (many small rooms, one loop, two dead ends), a cistern (one 8..9-cell hall first, loops),
  a mine (few small rooms, no loops, long corridors, four dead ends) or halls (big rooms, most of
  them halls). The mod publishes it as `LuaFlag(endless_archetype)` (0 warren, 1 crypt, 2 cistern,
  3 mine, 4 halls). **Room shapes**: a room at least 4 cells a side is, a third of the time, an L
  (one corner quadrant unbuilt, never its centre) or an octagon (the four corner cells unbuilt);
  uncut 4+ rooms get the four pillars half the time where the stone allows a pillar. **Dead ends**:
  2..4-cell corridors into unbuilt ground clear of every room, a chest at the end three times in
  five. **Mutators** (from depth 3, three areas in ten; `LuaFlag(endless_mutator)` 1 dark, 2 ambush,
  3 silent, 4 collapsed): dark halves the ambient light, dims the room lamps to 0.45 and lights
  every eighth corridor cell (the exit and the boss room stay lit); ambush adds half again to the
  enemies and lets them stand near the start; silent cuts the halls to a quarter of their enemies
  and gives the boss room one more boss and twice the minions; collapsed triples the debris.
  **Light**: the room lamps take the stone's colour by stage (warm in the catacombs, whiter in the
  lower halls, cold green-blue in the sewers, amber in brick, red-orange in the mines, grey-violet
  in the old brick, red deeper), corridors the same at 0.65, the quiet room warm and bright.
- **Theme rule** (Hunter): a prop is placed on a stage only where a vanilla level wearing that
  stage's stone places it (`prop_stages=` in the ini, from the stage's source levels: 1 levels
  1-3, 2 level 4, 3 the sewers, 4 level 5, 5 level 6, 6 level 7, 7 level 8). So the catacombs get
  everything, the lower halls barrels, crates, chairs and tables, the sewers nothing, the mines sacks
  and hooks; the pillar stands only in the catacombs. "Mixed stone in one area" was dropped for
  the same reason: no vanilla level wears another depth's stone.
- **Room purposes** (Hunter's review, 2026-10-22): every ordinary room is a store (crates, barrels
  and sacks, a chest nine times in ten, sometimes a healing salve), a barracks (stools, chairs,
  buckets; three times the enemies), a shrine (coffins; from depth 3; its chest is a rare find from
  the deepest chest tier with a chance of 10 % + 5 % per depth, up to 60 %), the quiet room (one
  per area from depth 2: nothing spawns there, a chest and a healing salve always), or plain.
  The salve is exanima03's `Healing Salve` record imported into the template (`salve=`); two per
  area at most. Enemy counts are capped at 40 (reached at depth 11), bosses at 3, minions at 6.
- **Run summary**: when a run ends (the menu comes back with an area in progress) the mod stores
  depth, areas, bosses and companions lost, and the title row reads
  `ENDLESS  (DEPTH 7)  LAST RUN: DEPTH 4, 11 AREAS, 3 BOSSES`.
- **Companions are found once**: the mod remembers every companion seen this run (`endless.met`)
  and passes it to the generator, which skips a met one for the first not yet met and places
  nobody once all three are met (before this, a companion already following could be found again
  one depth later). Companions found: Tobin on depth 1, Aldric on 2, Mira on 3.
- **Monster closets** (from depth 2): a 2x2 room off a corridor, shut by a portcullis that a floor
  plate in the corridor opens (the button class, pressed by contact); two or three enemies inside.
- **Maze gate puzzles** (from depth 3): portcullises across the maze's entry-to-goal path, each
  opened by a lever hidden in a dead end that is reachable before that gate. Fire traps also
  get a floor plate that drives the operative natively.
- **Companion bypass** (Hunter, 2026-10-22: companions should not be lost in mazes): on areas
  with a boss room and a maze, a corridor runs round the outside of the maze from its entry
  corner to its goal corner, with a plain doorway at the entry and a portcullis at the goal end
  whose lever is in the goal cell. The player parks the party with the game's own "Wait for me
  here", solves the maze, pulls the lever, and "Follow me" brings them round instead of through.
  It is routed only through unbuilt cells that touch no other corridor, so it joins nothing else;
  the solvability check counts its gate (opener: the goal cell). Fire and push traps already hurt
  only the player.
- **Solvability rule (Hunter):** `decode_check` simulates every gated doorway shut and opens a
  gate only when its opener (key or lever room, boss room, switch room, lever cell, plate cell)
  is reachable; the exit goal must be reached and every gate must open. 300 areas pass.
- **Terrain:** the level names come with their own .rft, so the mod serves a flat 2x2-tile
  terrain at floor level with every area (as level 1's terrain lies under its floors).
- **Tile sets change with depth:** catacombs (levels 1–3) for depths 1–2, then the lower halls
  (level 4), the sewers, the deep brick (level 5), the mines (level 6), Hellmode's own deep brick
  (level 7, when the archive has it) and the deepest brick (level 8), cycling afterwards. The
  template records which sets the installed archive really holds, so a vanilla install gets the
  vanilla list. The grid encoding is the same for every complete set.
- **Loot scales with depth:** chests of deeper levels (2, 3, the Archives and sewers, level 7,
  the mines and level 8) are imported into the template with their own loot lists (ids
  remapped, display strings cleared) and join one tier per depth, the newest two weighted; the
  key caches and level 1's chests stay as the base. Corpse loot follows the enemy tiers.
- **Strength bands:** every boss and every enemy record exists in four strengths (skills
  x1.0/1.2/1.4/1.6 capped at 30000, AI skill +0/+15/+30/+45 capped at 150); band k from depth
  6k+1 (7, 13, 19). All enemy tiers are in play by depth 6, so the bands are what keeps depth
  biting after that, on top of the growing counts.
- **Two-key areas** (from depth 4, on key areas): the boss key lies in a vault, a one-door room
  locked with another pair's door; that pair's key is loose or in a cache elsewhere. The
  solvability check covers the vault door (36 deep areas: 15 vaults, 0 problems).
- **Boss-room pillars:** level 1's freestanding column stands in the four inner corners of every
  boss room, so the fight has cover; boss and minion spawns avoid those cells.
- **Props:** besides the floor props, wall-mounted hooks, chains, shelves, lamps, torch holders
  and wall supports sit on room and corridor walls at the heights and offsets level 1 uses
  (medians of its placements), and bones, planks, loose stones, bottles, pots and floor decals
  litter rooms with random turns.
- Holes you fall through are not possible in this engine's one-storey room grid (a fall would be
  a level change); the "trapdoors" of the shipped maze are dropping portcullises, which is what
  the gates above are.

## Companions

Friendly NPCs that join like Derrin, with their own dialogue written from scratch
(`generator/endless_dialogue.py`, built by `make_companions.py` through the
conversation builder `convo.py`; the built lines are rendered to `companions/DIALOGUE.md`):
- Written on the game's own texts (every note, book, item description and dialogue in Resource.rpk), adjacent to the main story without closing its open
  questions (nobody paid the bandits; Ardent is guilty only of coming late): **Aldric**, a soldier of
  Ardent who could not make himself follow the proctor down the rope, came down days later, and
  now goes first through every door; he does not know the proctor's fate until he finds him dead
  and walking (the generator makes that record the boss of the first area of depth 3) and only
  then admits what he did. **Tobin**, rough and distrustful, the heavy hand of Bram's band, who
  fed people to the hole at the old shrine because Bram believed it wanted feeding, thrown in when
  he asked why; he has a nose for danger and expects to be left behind. **Mira**, an apprentice
  of the Order who says she copies books, down alone on a rope after a master who went below
  years ago and never came back; she hides the talent until she trusts the player (her feel-based
  lines unlock after her first secret). The player is the story's amnesiac: terse, formal, cold.
- **Three roles each** (shapes: Derrin's main 19, meet-outer 35, assail 34; ids 48..56): the
  first meeting with the recruit script on the "Join me" yes (and a "come back later" path);
  the talk list while following (their past, the place, how they are, a question that unlocks
  after a depth, their secret in two stages, wait here / come along); reactions the generator's
  **talk zones** open at the boss door, the key, a vault door, a monster-closet plate, past the
  gate, at the stairs, in the start room of every area, on a new depth (depth lines in order
  from each one's joining depth) and **in the boss room** (a room-sized zone: an entering line, then
  up to three mid-fight call-outs while you are below half health, 30 s apart, and a pair
  coordination line per pair); the huge beast through Derrin's event topic (any holder of the
  Huge Demon role) and **a known dead one** through that topic re-keyed to a plain role of the
  companion's own (`EN_Known_<name>`, the shape of Huge Demon), which the template gives to one
  shipped dead record each (ToxZombieW26, ZombieOfficeSt16, ToxZombieW32): the sight event fires
  on the companion's first focus on any such character (static reading); hurt lines below 40 health, theirs and yours; three idle remarks each, an hour apart;
  and what happens if you attack them first.
- **Addressing them:** the player's lines call them soldier, apprentice, thief as often as by
  name. **Group orders** "All of you, wait here" / "All of you, with me" are nodes in each one's
  talk list whose script fans the game's own Explorer "Wait Here" / "Follow me" out to every
  follower nearby (`Actor[1].ActivateTopicN(31, 29, ...)`, the player holding Explorer). Static:
  the fan-out is a static reading of ActivateTopicN; not seen in play.
- **One voice per occasion** (Hunter, 2026-10-22: nobody talks over anybody): every occasion
  (each talk-zone spot, the boss room and its call-outs, your wounds, the huge beast, each
  first casting) has an order of speakers (`SPOT_ORDER`): Aldric first at the boss door, the
  gate, arrival, the boss room, the call-outs and your wounds; Mira first at the stairs, a new
  depth and the vault; Tobin first at the key and the closet plate, and alone for the beast
  (a sight event each observer raises for itself). Every companion keeps its own line for each
  occasion, in its own voice, but only one is opened: the template carries one talk zone per
  spot per companion and the generator places one of them, the first in the spot's order who is
  in the party (`gen.build(t, seed, area, present)`; the mod reads the party from
  `characters.snapshot` each second: living companions within 25 m of the player, and passes it
  when it serves the next area; nobody present falls back to the designed first speaker). The
  opened line's end runs `ActivateTopicN(me, next, <occasion>, 1)`, one short exchange with the
  next in the order in the speaker's banter topic (it plays only when that one is near). So at
  most two speak at an occasion, in turn, saying different things. Pair zones are retired.
- **Hidden talents.** Mira's and Tobin's records ship with the thaumaturgy skills and no caster
  block (`characters.grant_powers`, runtime 0.28.0, capability `characters.powers`). Mira: Blast,
  Barrier, Shock, Shell, Constant Displacement, granted at her reveal (dialogue `LuaEvent(EndlessReveal, 1)`), at betrayal or when
  anyone in the party is near death. Tobin does not know he has it: granted the
  first time a boss is hurt or within 15 m while he and Mira have spent 20 minutes together in
  the party after her reveal (`LESSON_SECONDS`; Blast, Shock, Strikes); her hourly `Lesson 1..3` banter with him is her
  prodding the feeling he has without naming it. Grants are remembered in `endless.granted` and
  made again after CONTINUE. The continuous powers (Shell, Constant Displacement, Strikes, Shock
  Weapons) need a binding, and bindings come from Continuity, a Concentration technique (not a
  power id), so the records carry it from the start: Mira Continuity II, Tobin Continuity; Mira's
  grant is Blast, Barrier, Shock, Shell, Constant Displacement; Tobin's Blast, Shock, Strikes.
- **Found in this order** (Hunter): Tobin on depth 1, Aldric on depth 2, Mira on depth 3. They all
  came in by the same hole at different times and each got as far as they got; the proctor Aldric
  follows is the boss one depth below him. The second area of each depth holds its companion in the
  room that fits them (the bandit farthest from the start, the soldier nearest the locked door, the
  apprentice nearest the maze entry). The template's `companions=` list is in that order and every
  index in the mod (flags, orders) follows it.
- **The procedural seed is what they talk about.** Every zone line opens only where the generator
  put the thing (the key, a second lock, a closet plate, the gate, the stairs, the boss room). The
  new-depth lines are chosen by the tile-set stage the mod publishes as `LuaFlag(endless_stage)`
  (1 catacombs, 2 lower halls, 3 sewers, 4 brick, 5 mines, 6 old brick, 7 deeper brick, then 2..7
  again), so what they say matches the stone, whatever depth they joined at; `endless_depth` is
  published too.
- **First castings.** The mod watches each party member's `focus` in the snapshot: the first drop
  below 97 % of its maximum (after the grant, for the two of them) is that character's first
  casting. It then sets a `LuaFlag` for the first present observer in the occasion's order
  (`endless_saw_you_<i>`, `endless_saw_mira_<i>`, `endless_spark_2`), and that companion's
  reaction node (`Saw you`, `Saw Mira`, Tobin's `Spark`) opens on its own on that flag, once, and
  hops to the next in the order. Mira's `Saw you` differs before and after she has told you.
- **Aldric is strong**: Close Combat, Armour and Shields at 25000 (five techniques) in his record.
- **Deaths.** The mod sees a dead companion in the snapshot and sets `endless_dead_<index>` (the
  talk-list lines about that one stop being offered, and exchanges with it no longer play: their
  conditions also check the partner's Health), then gives the first present survivor in the
  occasion's order the reaction flag (`endless_dead_<name>_<observer>`): that survivor's
  `Dead <name>` line to you opens on its own, once, and hops to the other survivor (`DEATHS`,
  `HOPS`). Nobody left means nobody says it. Afterwards each survivor mourns every so often:
  three lines per dead companion (`MOURNING`), in order, once each, an hour of world time apart.
- **Banter:** a topic in each main role keyed by each other companion's main role: three hourly
  exchanges per direction while both follow (six for Mira with Tobin), plus the hops above.
  The engine only ever pairs two actors; the group orders above are how "all of you" works.
- **Talks that pass between three of you:** each companion's talk list has one once-only line
  about each other companion ("About <B>"). The answer closes the dialogue and the script opens
  the owner's banter topic with the other at "Asked <B>"; the end of that exchange opens the other
  one's "<A> asked" line to you. Three two-person conversations chained by `ActivateTopicN`
  (the same call the group orders and pair zones use). Static: whether a conversation opens as
  the previous one closes has not been seen in play.
- **Travelling with you** ("Arrival placement", static): followers with the follow activity
  travel on the stairs and land round the arrival marker at fixed offsets up to 200 cm, rotated by
  the marker; the fifth to eighth stack on the player and later ones are lost. Endless has three
  companions, the arrival marker sits at the start room's centre (3x3 cells, no props, no debris,
  no spawns), and the mod places the player on that same point, so the party lands together.
- **Mira's talent is granted at her reveal.** Her record ships with the thaumaturgy skills but no
  caster block, so she cannot cast before she admits the talent. The reveal reply's action is
  `LuaEvent(EndlessReveal, 1);`; the mod answers the event with `characters.grant_powers(record,
  {Blast, Barrier, Shock, Shell, Constant Displacement})`. Both are runtime 0.26.0 requests
  (LuaEvent from a dialogue action; grant_powers appending the CDEC01 block to a live character),
  written behind capability checks; the ini carries `reveal_powers=<record>:<ids>`.
  The talent also comes out without her choosing (Hunter): a `Dire` node opens on its own when she
  or the player is below a quarter of health while she follows ("No. Not like this. Get behind
  me."), and an `Engage` node in her main role fires when the player turns on her; both raise the
  same event. The mod grants once per run. Other party members' health is not readable from a
  role script, so `main.lua` polls the party itself every second (`watch_party`): any living
  companion or the player below a quarter of a readable maximum in `characters.snapshot()`
  takes the same grant path (`reveal("near death: <name>")`). The poll starts with the run
  (new game or CONTINUE) and stops at the menu.
- `assets/charroles.rdb` is the whole roles database with the nine roles appended (118066
  bytes); the companion records (a level-1 civilian look, roles Human + Activity Wait + their
  meet role) are appended to the template. Every conversation reads back with the builder's
  reader and every script passes the dialogue checker; nothing has run in game.

The generator places one companion in an ordinary room, away from the start, on the second area
of every depth (Aldric, Mira, Tobin in turn). The manifest declares the runtime's startup override (`[script.overrides]`, 0.26.0-dev) that puts
our roles database in place before the game reads it (unverified in game: it relies on EMTK
submitting before session setup). The live run has to show them greet, join and follow (the
Explorer activity → brain mode mapping is inferred).

The title row reads `ENDLESS  (DEPTH n)` once a run has reached depth n (the deepest of any run,
kept in the runtime's per-user storage); the label is refreshed at the title menu by removing and
re-adding the row, so it lags one return to the menu.

## Checks

```
lua.exe tests\test_gen.lua assets\endless-template.rfc assets\endless-template.ini out\golden-lua scripts\gen.lua
lua.exe tests\test_main.lua . assets\endless-template.rfc assets\endless-template.ini
```
The first compares 36 (seed, area) pairs byte for byte with the Python reference; the second
drives `main.lua` with stubbed runtime globals (row, start, boss death opening the gate, exit zone
in either event order, travel, placement, fire, push, NPC entries ignored, CONTINUE, menu reset)
and prints the same `Endless:` lines a live run would write. Last run 2026-10-22: both PASS
(72 files compared, 0 mismatches). Both re-run after the 2026-10-22 02:40 UTC round (bands, vaults,
pillars, dialogue, depth label): PASS. These are offline checks of the code, not of the game.
The runtime must accept member names with extensions in `levels.serve` (`arenao1.rfc`, `arenao1.rft`).

## Owed

- Runtime 0.25.0-r2 (built, offline suites only) provides `title.rows` and `levels.serve(member, bytes, package)`
  and the `dead` flag from the character's life stage; 0.26.0 is to bring `levels.flow` (new_game/travel/current),
  `levels.drive`, `player.place`, `player.damage`/`player.push` and `assets.read`. The `api` table in
  `main.lua` is the one place to rename when they land.
- Boss and monster hostility is their shipped roles (knights carry "Human Hater"; the monsters
  are hostile by nature); per-record stat scaling is not applied, counts scale instead. Frame
  rate at 100+ enemies is the player's own limit; there is no cap.
- First live run with saves backed up, per `LIVE-RUN.md`. Nothing in this folder has been seen in
  the game. There is no test hook that kills the boss: step 5 of the live run is real combat
  unless the runtime adds one.
- Wall and floor set pairings beyond the shipped ones are untested; imported chest models and
  loot lists from other tilesets may look out of place until seen.
- Plate semantics (press opens the target, release closes it with flag 2) and the secret-door
  look are static readings; the first live run decides whether closets and plates feel right.

## Building and checking

The runtime sandbox has `base` (without `load`, `dofile` or metatables), `table`, `string`, `math`
and `utf8` only: `gen.lua` builds its objects as plain tables carrying their methods, and both
tests load the modules through the same restricted environment so a stray global fails offline.

**The build is a task.** The runtime allows about 100k instructions per callback and an area build
takes 2 to 3.6 million (measured with a count hook: 2.0 M at area 1, 3.6 M at depth 4), so
`main.lua` runs `gen.build` through `tasks.run` (runtime 0.28.0 r25: 200k instructions a pulse,
resumed every presented frame, 10 to 18 pulses an area) and serves the level in the completion
callback; the title row click says "descending", and `next_area` and CONTINUE's restore go the
same way. A task cannot yield inside a C callback, so the generator uses its own insertion sort
instead of `table.sort` with a comparator. The stub test models the budget: it counts the pulses a
build would take and fails if a 200k boundary falls inside a C function. The corridor router no
longer copies its path per step and searches only a box 8 cells round the two ends (it was 87 %
of the cost); the remaining cost is the search itself.

**Memory.** The addon's Lua state is 8 MiB by default and an area build holds the template (1.8 MB),
the level (1.5 MB) and the terrain (1.4 MB) with their intermediates, so the manifest asks for
`memory_mb = 48` (runtime r26; the parsed dressings are dropped after each build) and the build keeps its peak down: the level and the terrain are
assembled by one `table.concat` over parts each (no chained `..` copies of megabyte strings), the
terrain is built in a second task after the level bytes are served and dropped, and the stub fails
a task whose live memory passes 32 MiB (it reports the peak it saw).

**Frame rate** (Hunter: 7 then 22 FPS against the arena's 60): rock cells only beside built
cells and vanilla's border ring (above), and lamps cut: room lamps reach 600 + 150 per cell of
span (was 900 + 250), corridor lamps every sixth cell at 600 (was every fourth at 800), maze lamps
every third node. The counts are now far under a vanilla floor's (about 25 lamps against level
1's 122, 130 objects against 3,400).

The generators and checks need the exanimate format library
(`EXANIMATE_TOOLS`, see `tests/README.md`). `out/` and the four game-data-derived files under
`assets/` are not committed; each machine builds them from its own installed game.
`tools/make_dist.py` copies the ready-to-ship mod to `dist/mods/com.necrosis.endless/` (not
committed); the installer and the packager copy Endless only from there.
