# Endless

Endless is a mod for Exanima. It adds an **ENDLESS** row to the title menu, just under ARENA.
Choosing it starts a new character on a run of dungeon floors that the mod builds as you go,
one area after another, with no last floor. Three companions with their own written dialogue can be
found and recruited on the way down.

Author: NecrosisDev

## Features

### Floors

- Every area is built from a run seed and the area number. A new run gets a new seed.
- Three areas make one **depth**. The exit of every third area is a staircase down, and each new
  depth brings bigger plans, more enemies, more traps and harder puzzles.
- Areas use the game's own wall and floor sets. The stone changes with depth (the catacombs first,
  then the lower halls, the sewers, the brick levels and the mines) and cycles after the deepest.
  Only sets that your installed game actually contains are used.
- From depth 2, each area follows one of five plans: warren, crypt, cistern, mine or halls. They
  differ in room count, room size, loops and dead ends.
- From depth 3, about three areas in ten carry a twist: **dark** (dim lamps), **ambush** (more
  enemies, some near the start), **silent** (empty halls but a stronger boss room) or **collapsed**
  (more rubble).
- Rooms have purposes (store, barracks, kitchen, latrine, workshop, shrine, gaol, surgery) and are
  furnished from rooms of the game's own levels with the same purpose, so furniture sits the way
  the game itself places it. Some rooms show signs of a fight or a looting.
- From depth 2 one **quiet room** per area holds no enemies, a chest and a healing salve.

### Keys, bosses and the way on

- Each area has a locked **boss room**. Find the area's **key** to open it. From depth 3, every
  other area uses a hidden **lever** instead of a key.
- From depth 4, the boss key can lie in a locked vault whose own key is somewhere else in the area.
- Beating the boss raises the **gate** to the exit. Walking into the exit takes you to the next area.
- Some boss rooms have a small pen with a portcullis. Trap the boss in it and pull the lever, and
  that also counts as beating it.
- An area has one boss at first, two from depth 6 and three from depth 12, with more minions as you
  go deeper. Boss rooms have pillars for cover.
- From depth 2 the exit can sit at the far side of a **maze**. Deeper mazes are larger and have
  portcullises across the path, each opened by a lever in one of the maze's dead ends. A corridor
  runs round the outside of the maze so that companions told to wait can rejoin you at the far end.

### Danger and reward

- Enemy counts grow with depth and with each area inside a depth, up to 40 per area. New enemy
  types join as you descend: zombies and skeletons first, then ghouls and other creatures of the
  deeper levels, then living armour, golems and more.
- From depth 7, and again at depths 13 and 19, enemies and bosses come in stronger versions.
- **Fire traps** appear from depth 2 and **push traps** from depth 3. Both affect only the player.
- **Monster closets** (from depth 2): a small room shut by a portcullis that a floor plate in the
  corridor opens.
- **Secret passages** (from depth 2), opened by a brick switch on a room wall, and hidden
  treasuries with deeper loot.
- Some doorways are barricaded. There is always another way round.
- Chest loot follows depth: chests from deeper levels of the game join as you go down.
- The dungeon also hides a few secrets of its own.

### Companions

- **Tobin** is found on depth 1, **Aldric** on depth 2 and **Mira** on depth 3, each in the second
  area of that depth. Each one is met once per run.
- They are recruited and led the way the game's own Derrin is, and follow you down the stairs.
- Each has a full set of written lines: a first meeting, a talk list about their past, the place
  and each other, and reactions to the keys, gates, stairs, boss rooms and new depths the generator
  places. Only one companion speaks at a time; another may answer.
- Their talk lists include "All of you, wait here" and "All of you, with me" orders.
- Companions remember those who fall and mourn them later.
- Two of them carry a hidden talent that wakes during the run.
- If the Light School mod is installed, companions who have woken their talent can cast Glare and
  Guiding Light in a fight.

All of their dialogue is in `companions/DIALOGUE.md` (it contains story spoilers).

## Requirements

- **Exanima** (Steam).
- **EMTK** with the script-runtime startup patch. The Exanima Lua Runtime's README explains how to
  get it.
- **Exanima Lua Runtime 0.28.0 or later**.
- To build the template files (see below): Python 3.9 or later, the Endless source repository and
  the `exanimate` Python format library.

## Template files

The mod needs five files that are built from the game's own data, so the release ZIP does not
include them:

| File | What it is |
|---|---|
| `assets/endless-template.rfc` | the template level every area is built from |
| `assets/endless-template.ini` | the record ids and settings that go with that template |
| `assets/endless-template.rft` | a flat terrain tile served with each area |
| `assets/charroles.rdb` | the game's roles database with the companions' roles added |
| `assets/endless-dress.bin` | room furnishings cut from the game's own levels |

Build them from your own install with the scripts in the source repository's `generator` folder.
Run these from the root of the repository:

```powershell
$env:EXANIMATE_TOOLS = '<folder that contains the exanimate package>'
python -X utf8 -B generator\make_companions.py --game "<Exanima folder>"
python -X utf8 -B generator\make_template.py --game "<Exanima folder>"
```

- `--game` is the folder that holds `Resource.rpk`. Always pass it; the scripts only read from it.
- Run `make_companions.py` first. `make_template.py` reads its output from the repository's `out`
  folder, so leave `--out` at its default.
- `make_companions.py` writes `out\charroles-endless.rdb` and `out\companions\`.
  `make_template.py` writes `out\endless-template.rfc`, `out\endless-template.ini` and
  `out\endless-dress.bin`.

Then copy them into the installed mod:

| From | To `<Exanima folder>\mods\com.necrosis.endless\` |
|---|---|
| `out\endless-template.rfc` | `assets\endless-template.rfc` |
| `out\endless-template.ini` | `assets\endless-template.ini` |
| `out\endless-dress.bin` | `assets\endless-dress.bin` |
| `out\charroles-endless.rdb` | `assets\charroles.rdb` |

The `.rfc`, `.ini` and `.rdb` must come from the same build, because the template's companion
records refer to the roles in that database. Rebuild all of them after a game update.

`assets\endless-template.rft` is not written by these two scripts. It is a one-tile flat terrain
file in the game's `.rft` format; the mod will not start a run without it.

## Install

1. Download `Endless-<version>.zip` from the releases page. A `.sha256` file beside it lets you
   check the download.
2. Close Exanima.
3. Copy the `mods` folder from the ZIP into your Exanima game folder, so that
   `<Exanima folder>\mods\com.necrosis.endless\manifest.toml` exists.
4. Build the template files and place them in `mods\com.necrosis.endless\assets\` as described
   above.
5. Enable Endless in your EMTK profile, together with the Exanima Lua Runtime.
6. Launch the game through EMTK.

The mod does not change the game's own files. The areas and the companions' roles database are
handed to the game by the runtime while it runs.

## Playing

- On the title menu, choose **ENDLESS**. The first area is built and a new character starts in it.
  Building an area takes a moment.
- Find the key or lever, open the boss room, beat the boss and go through the gate to the exit.
  The next area is usually built ahead while you play, so the move is quick.
- When a run has ended, the ENDLESS row shows your deepest depth and your last descent on a second
  line (where the runtime supports it), and starting a run shows the same records on screen.
- There are no settings to change.

## Saves and uninstalling

- A run is saved by the game like any story character. **CONTINUE** resumes it in the area where
  you saved: the area and the run seed are stored in the level itself.
- Your deepest depth, last descent and the run's companion progress are kept in the runtime's
  per-user storage.
- An Endless character can only be continued while the mod is installed and enabled.
- Back up your saves before trying any new mod.
- To uninstall, disable Endless in your EMTK profile and delete
  `<Exanima folder>\mods\com.necrosis.endless`.

## Building from source

The mod is three Lua scripts (`scripts/main.lua`, `scripts/gen.lua`, `scripts/build_worker.lua`)
and `manifest.toml`. The Python files in `generator/` are the template builders and a reference
version of the area generator.

```powershell
python -X utf8 -B release.py
```

This writes the mod folder to `dist/mods/com.necrosis.endless/` and the public
`dist/Endless-<version>.zip` with its `.sha256`. The version comes from `manifest.toml`. The ZIP
never includes the five game-derived files. The full build expects them in `assets/` first, so
the mod folder in `dist/` is ready to copy into the game.

- `--without-private` builds the public part only, from a clean checkout with no game data.
- `--zip-only` packages the mod folder already in `dist/` without rebuilding it.
- `--tag v<version>` stops unless the tag matches the manifest version.

A previous mod folder in `dist/` is moved to `dist/previous/` before a build. ZIP entries carry a
fixed timestamp, so the same files always give the same SHA256.
