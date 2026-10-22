# Endless (Lua mod for the Exanima Lua Runtime)

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
