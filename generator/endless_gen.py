"""Endless mode area generator (offline reference implementation).

Builds one dungeon AREA as an Exanima level (.rfc bytes) from the template made
by make_template.py plus a run seed and the area number. Hunter's spec (2026-10-21):
every area hides a key that unlocks the area's locked door; past the door, a zone
loads the next area; every AREAS_PER_DEPTH areas the exit is a staircase down and the
depth (difficulty and complexity) goes up; deeper areas add mazes.

Grid encoding (static + offline evidence):
- layer 0: one nibble per SIDE of the cell, q0 = north (-z), q1 = west (-x),
  q2 = south (+z), q3 = east (+x): 0 open, 7 plain wall, 0xB doorway wall
  (the same value on both sides of a shared edge);
- bits 16+4q..18+4q: the corner between side q and side q+1: 3 both walls,
  1 side q only, 2 side q+1 only, 0 open, 4 a pillar where a neighbour's wall ends;
- bit 19 (q0) built; layer 1 = 0; layer 2 = 0 (wall set 0, floor set 0); unbuilt 0xFFFF/0/0.
Doors (offline, exanima01): a door is an item placement of a level-local record with
chunk 0x40000 (+4 = opener id); the placement sits at the centre of a cell whose side
nibble is 0xB, facing that side (N yaw 0, E 90, S -180, W -90); placement head +4 is
the state word, bit 0 = locked. Keys are item placements of a device record. A key
carried into the next area gets a new id, so a small pool of key/door records
is reused per area. Stairs are decoration objects; the zone at their foot travels.
Nothing here has been seen in the game yet.

Everything after the layout is byte-level surgery on the template, mirrored by the
native port, so both produce the same
bytes for (seed, area). The random source is a small fixed integer generator.
"""
from __future__ import annotations

import argparse
import math
import struct
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# the exanimate format library: EXANIMATE_TOOLS, else the Exanimate workspace this repo was split from
_TOOLS = os.environ.get('EXANIMATE_TOOLS') or str(Path(__file__).resolve().parents[3] / 'tools' / 'exanimate')
sys.path.insert(0, _TOOLS)
from exanimate import level, rdb  # noqa: E402

CELL = 600.0
SIDE = [(0, -1), (-1, 0), (0, 1), (1, 0)]  # q -> (dx, dz): N, W, S, E
SIDE_YAW = [0.0, -90.0, -180.0, 90.0]  # a door facing side q (from shipped placements)
WALL, DOOR = 7, 0xB
BUILT = 0x80000
ROCK = 0xFFFF
ROUTE_MARGIN = 8  # cells beyond the two ends a corridor search may use
# corridors that wander and widen (2026-10-22, the game's own corridors bend and vary): a turn costs
# TURN_COST, and each cell a fixed 0..2 more from a hash of its place and the area (WANDER), so routes
# drift instead of running ruler-straight; a quarter of corridors WIDE_MIN cells or longer get a second
# lane along their middle third. Hashes, not the rng, so the rest of the plan is unchanged by them.
TURN_COST = 2
# corridor sectors (2026-10-22, from a static decompile of the game's culling, 141840/143C20/5B170): the
# game makes one sector of every run of cells joined by open sides; a doorway side ends it. It draws the
# camera's sector whole, those one doorway away only through their openings, and nothing further. A
# corridor network joined only by open sides is one sector the size of the area, so from any corridor the
# game drew all of it and nearly every room. Corridors are cut into pieces of at most SEG_MAX cells,
# joined by doorway sides, as the shipped levels' corridors are.
SEG_MAX = 8
WIDE_MIN, WIDE_CHANCE = 8, 25


def _wander(lay, c: int, r: int) -> int:
    v = ((c * 73856093) ^ (r * 19349663) ^ lay.wander) & 0xFFFF
    return 2 if v % 10 < 2 else 1 if v % 10 < 4 else 0
# cell dressings (Hunter, 2026-10-22: scattered props clipped walls and left the middle empty): whole
# cells of the game's own levels, kept by their wall pattern. Masks: bit q is a wall on side q (0 N,
# 1 W, 2 S, 3 E); the classes are none, N, N+W (corner), N+S (passage), N+W+S (dead end).
DRESS_CLASSES = [0, 1, 3, 5, 7]
DRESS_ROOM_CHANCE, DRESS_COLLAPSED_CHANCE, DRESS_CORRIDOR_CHANCE = 100, 100, 90  # 2026-10-22: toward the shipped levels' density (tests/measure_dressing.py)
# frame budget: the room dressing chance falls as an area grows past DRESS_FULL_CELLS room cells (not
# below DRESS_MIN_CHANCE), and no cell is dressed once the area holds OBJECT_CAP objects (level 1 of
# the game has about 3,400)
DRESS_FULL_CELLS, DRESS_MIN_CHANCE, OBJECT_CAP = 1400, 50, 5200  # 5200: vanilla level 5's objects per cell over an Endless area (frame cost unmeasured)
# rooms that tell a story (Hunter, 2026-10-22): every enclosed room of the stage's own levels is kept
# whole and tagged by what is in it; an Endless room takes one source room by its purpose and fills
# its cells from that room's cells of the same wall pattern. Seats get loose angles, and now and
# then one lies knocked over in one of the poses the game's own levels use.
DRESS_TAGS = ['misc', 'store', 'barracks', 'kitchen', 'latrine', 'workshop', 'shrine', 'gaol', 'surgery', 'study']
PURPOSE_TAG = {'store': 1, 'barracks': 2, 'kitchen': 3, 'latrine': 4, 'workshop': 5, 'shrine': 6, 'gaol': 7, 'surgery': 8}
TAG_PURPOSE = {tag: purpose for purpose, tag in PURPOSE_TAG.items()}
SEAT_JITTER = 15.0  # degrees either way (30 left seats facing their tables less often than the shipped levels')
# rooms and their neighbours (Hunter, 2026-10-22: big and small rooms, rooms that need certain
# neighbours and rooms that cannot sit by others). Neighbours: ordinary rooms within NEIGHBOUR_GAP
# cells of each other. The kitchen wants a store or another kitchen (a mess) beside it when the area
# has a store; the gaol and the latrine keep away from the kitchen; the shrine keeps apart from the
# living rooms; latrines, gaols and stores are small rooms, kitchens, barracks and shrines big ones.
NEIGHBOUR_GAP = 4
SHRINE_APART = ('kitchen', 'barracks', 'latrine', 'workshop', 'store')
SMALL_PURPOSES, SMALL_MAX = ('latrine', 'gaol', 'store'), 16
BIG_PURPOSES, BIG_MIN = ('kitchen', 'barracks', 'shrine'), 6
NEIGHBOUR_PASSES = 2
ITEM_CAP = 200  # loose table items (cups, books...) an area may carry
# easter eggs (Hunter, 2026-10-22). Dialogue for them waits for his approval; these are the places.
#  1. your last descent: remains in the farthest room of the area where the last run ended;
#  2. the twelfth name: remains in the first gaol, now and then (from depth 2);
#  3. Bram's shrine: the carving in the treasury, once a run, from depth 6, where the stone has it;
#  4. a perfect copy: now and then one room of the catacombs is one of the game's own rooms exactly;
#  5. depth 13: every lamp cold blue; 6. depth 50 and every 50 after: the quiet room holds one chair.
REMAINS = 'skelbase_physics'
CARVING = 'carving stla a1'
ELARA_CHANCE, COPY_CHANCE = 15, 4
BLUE_DEPTH, BLUE_LIGHT = 13, (0.18, 0.32, 0.7)
CHAIR_DEPTHS = 50
# the backrooms (Hunter, 2026-10-22, turning the perfect copy into a reference): a chair in the copy's
# corner faces the wall; walking into the corner behind it takes you to a vast, empty level of the same
# stone, every room alike under the same dull yellow light, no one in it; the way back is behind a
# locked door whose key lies somewhere in it, and it returns you to the room that sent you
BACK_LIGHT, BACK_STRENGTH, BACK_GRID = (0.62, 0.56, 0.3), 0.6, 64
# its furniture (Hunter, 09:30: "uncanny layouts of props, furniture"): sparse and wrong. Chairs in rows
# facing a wall, beds stood on end, one thing dead centre, the same chair and bucket in the same spot
# room after room, and in the biggest room a table set for one. Only the stone's own vanilla props.
# Out of 100 per ordinary room: rows below 12, beds below 20, centre below 32, the twin below 50.
BACK_ROWS, BACK_BEDS, BACK_CENTRE, BACK_TWIN = 12, 20, 32, 50
BACK_PROPS = ('chair a', 'table_m_re a', 'bed b01', 'coffin01', 'bucket wod a01', 'stool a')
BACK_CENTRE_PROPS = ('chair a', 'coffin01', 'bucket wod a01', 'stool a')
BED_ON_END = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0]  # bed b01's long model x axis turned upright
BED_HALF = 111.0  # half of bed b01's length (its model x runs -111..111): the lift that stands it on the floor
# chair a's backrest is on its model -z side (its vertices above 70 sit 22 units toward -z), so with no
# turn it faces south (+z) and half a turn faces north. Rows only go on north and south walls, where
# that holds under either matrix convention.
SIZE_FACTOR = 2  # a source room within this factor of the room's size is preferred (a private kitchen, a mess hall)
MAX_ROOMS = 60     # ordinary rooms an area may try for
EXIT_TRIES = 6     # rooms tried as the exit, farthest first, until a boss room fits beside it
# close quarters (Hunter, 2026-10-22: "mix in some smaller, tighter, close quarters areas with the large
# rooms to fill in gaps"): after the plan, small rooms tucked one cell from any room where ground is left
FILL_SHARE = 35        # percent of the plan's room count added as small rooms
FILL_SIZE = (2, 3)     # their sides, in cells
FILL_TRIES = 400
FILL_MAX_ROOMS = 75    # rooms in all, fill included (the build's memory and time grow with it)
# room outlines from the stage's own levels (dressing file EDR5): this percent of ordinary rooms takes one,
# doubled when it is 4 cells a side or less (Endless rooms run about twice the game's); the room's centre
# cell must be in it (corridors aim there), else the room stays a rectangle
STAMP_CHANCE = 30
# the plan grows along a spine, then wings (2026-10-22, from tests/measure_vanilla.py: the shipped levels
# have ~2.9 doorways a room, ~0.5 loops a room and 17 % dead-end rooms; Endless had 2.3, 0.3 and 25 %).
# The first third of the rooms is a chain, each beside the last, heading one way more often than not;
# the rest are wings: half the time beside the newest room (a district grows), else beside a spine room.
SPINE_SHARE = 3        # one room in this many is on the spine (at least 3)
SPINE_STRAIGHT = 60    # percent of spine rooms that keep the heading
SPINE_STALL = 40       # failed tries in a row that end the spine early
WING_GROW = 50         # percent of wing rooms placed beside the newest room
# extra corridors join a room to one of its nearest rooms: rooms * (LOOP_BASE + LOOP_PER * arch loops) / 100
LOOP_BASE, LOOP_PER, LOOP_NEAREST = 40, 4, 3
# bigger areas, growing with depth (Hunter, 2026-10-22): the grid is 56 cells a side at depth 1, 60 at
# depth 2 and 64 from depth 3 (64 x 64 is the largest grid the game's own levels use); the room
# count keeps growing with depth inside it
GRID_BY_DEPTH = {1: 56, 2: 60}
GRID_MAX = 64
# doors barricaded from the room side (Hunter): the doorway stays built, props block it, and another
# way in must exist; 1 + depth // 2 of them, at most 4
BLOCKERS = ('barricade d', 'barricade b', 'barricade c')
BLOCK_FILL = ('cratel4', 'barrel wdo1 a02', 'cratesmall a', 'sack a')
MAX_BLOCKED = 4
# the shipped grids ring their border with fixed words (top, left, right, bottom; a corner is the
# OR of its two edges): exanima01/02/05_sw all carry exactly these
BORDER_TOP, BORDER_LEFT, BORDER_RIGHT, BORDER_BOTTOM = 0x20010007, 0x120070, 0x12007000, 0x1200700
TAG_MARKER = 0x8000AC07
TAG_NAME = 0x10000000
TAG_DOOR = 0x40000
TAG_CONTAINER = 0x20000
TAG_DEVICE = 0x10000
LEVER_Y = 145.0  # wall levers in exanima01 sit at 135..170 cm
MARKER_ARRIVAL, MARKER_EXIT, MARKER_ZONE = 0x1040, 0x1120, 0x1110
PROP_NAMES = ['barrel wdo1 a02', 'cratesmall a', 'cratesmall b', 'sack a', 'stool a', 'chair a', 'bucket wod a01', 'cratel4', 'coffin01', 'pot9', 'basket_wkr e',
              'cage_human a', 'bathtub mtod a01', 'stretcher', 'cookpot a', 'table_m_re a', 'bench b01', 'sawtwohand',  # set-piece rooms
              'barricade d', 'barricade b', 'barricade c',  # blocked doors
              'carving stla a1']  # an easter egg: the shrine's carving
# area archetypes (Hunter's review, 2026-10-22): what an area is changes the layout rules, not only
# the dressing. rooms: wanted before +2 per depth; size / hall_size: a side in cells; hall: % of
# rooms that are halls (from depth 2); loops: extra corridors beyond the tree; style: % of rooms
# on the second wall/floor set; big: one 8..9 hall first (the cistern); spurs: dead-end corridors.
# gap: cells of ground between a new room and the room it is placed beside (Hunter: the areas were
# mostly hallways; rooms now grow out of each other instead of landing anywhere on the grid)
ARCHETYPES = {
    'warren': dict(rooms=16, size=(3, 7), hall=25, hall_size=(5, 8), loops=5, style=30, big=False, spurs=2, gap=(1, 3)),
    'crypt': dict(rooms=22, size=(2, 4), hall=0, hall_size=(5, 7), loops=2, style=20, big=False, spurs=3, gap=(1, 2)),
    'cistern': dict(rooms=12, size=(3, 6), hall=10, hall_size=(5, 8), loops=5, style=40, big=True, spurs=2, gap=(1, 3)),
    'mine': dict(rooms=8, size=(2, 4), hall=0, hall_size=(5, 7), loops=1, style=10, big=False, spurs=5, gap=(4, 8)),
    'halls': dict(rooms=12, size=(5, 8), hall=60, hall_size=(6, 9), loops=4, style=50, big=False, spurs=2, gap=(1, 3)),
    # the backrooms: many same-sized rooms, a cell apart, looped every way (not in ARCH_ORDER)
    'backrooms': dict(rooms=28, size=(3, 4), hall=0, hall_size=(3, 4), loops=20, style=0, big=False, spurs=4, gap=(1, 1)),
}
ARCH_ORDER = ['warren', 'crypt', 'cistern', 'mine', 'halls']  # depth 1 is always a warren
# mutators: one twist per area from depth 3, three areas in ten; the mod publishes it (endless_mutator)
MUTATORS = ['dark', 'ambush', 'silent', 'collapsed']
# lamp colour by tile-set stage (rooms; corridors are the same at 0.65): the stone sets the light
STAGE_LIGHT = {1: (0.55, 0.38, 0.2), 2: (0.5, 0.42, 0.3), 3: (0.25, 0.4, 0.45), 4: (0.5, 0.3, 0.15), 5: (0.6, 0.25, 0.1), 6: (0.35, 0.3, 0.45), 7: (0.45, 0.2, 0.2)}
QUIET_LIGHT = (0.6, 0.5, 0.35)
# light by use (2026-10-22): an ordinary room's lamp hangs halfway between its middle and the middle of
# what stands in it, as bright as its use asks (work rooms brighter, stores and cells dimmer); no more lamps
USE_LIGHT = {'kitchen': 1.15, 'workshop': 1.15, 'surgery': 1.1, 'shrine': 1.05, 'barracks': 0.9, 'store': 0.65, 'latrine': 0.55, 'gaol': 0.5}
# room purposes (Hunter's review, 2026-10-22): what an ordinary room is for decides its props,
# its enemies, its chest and whether a healing salve lies there. The quiet room (one per area
# from depth 2) spawns nothing and always holds a chest and a salve: a place to breathe.
PURPOSE_PROPS = {'store': ['barrel wdo1 a02', 'cratesmall a', 'cratesmall b', 'sack a', 'cratel4', 'basket_wkr e'],
                 'barracks': ['stool a', 'chair a', 'bucket wod a01', 'pot9'],
                 'shrine': ['coffin01', 'pot9'],
                 'quiet': ['stool a', 'chair a', 'bucket wod a01'],
                 'gaol': ['cage_human a', 'bucket wod a01', 'stool a'],
                 'surgery': ['bathtub mtod a01', 'stretcher', 'sawtwohand', 'table_m_re a'],
                 'kitchen': ['cookpot a', 'table_m_re a', 'bench b01', 'barrel wdo1 a02'],
                 'plain': PROP_NAMES[:11]}
PROP_COUNT_SCALE = {'store': 2, 'gaol': 2}
HOME_WEIGHT = {'barracks': 3, 'gaol': 2}  # quiet rooms are not homes
CHEST_CHANCE = {'store': 90, 'quiet': 100, 'shrine': 60, 'gaol': 30, 'surgery': 50, 'kitchen': 60}
ENEMY_CAP = 40      # ordinary enemies per area (the curve was uncapped: 106 at area 100)
BOSS_CAP = 3        # bosses in one boss room
MINION_CAP = 6
STAIRS_NAME = 'stair_ls a300_6'
# wall-mounted props: (distance from the wall as a cell fraction, height, yaw relative to the wall's side)
# medians of 261/39/52/55/75/94/41/55/78 shipped placements in levels 1-3 (offline, 2026-10-22)
WALL_PROPS = {'hook mtl a01': (0.13, 191.0, 0.0), 'chain_wall': (0.12, 210.0, 0.0), 'uw1_shelf a': (0.08, 122.0, -89.0),
              'shelf_wm b': (0.16, 160.0, 0.0), 'lightglobebr a': (0.13, 216.0, 0.0), 'torch holder a1': (0.31, 175.0, 0.0),
              'support wall a1': (0.12, 203.0, 0.0), 'hooks': (0.13, 177.0, 0.0), 'hook2': (0.13, 177.0, 0.0)}
# floor debris: (height) with a random turn
DEBRIS = {'skelbase_physics': 14.0, 'planksn': 7.0, 'stoneloose a12': 9.0, 'bottle_wkr b': 34.0, 'pot': 22.0, 'decal9': 0.0, 'decal12': 0.0}
TALK_SPOTS = ['Boss Door', 'Gate', 'Stairs', 'Depth', 'Key', 'Vault', 'Closet', 'Arrive', 'Boss']  # companion nodes the talk zones open
TALK_ZONE_FIRST = 20  # zone ids 20..28, one per spot (the mod ignores them)
TALK_ZONE_BOX = {'Boss': (900, 150, 900)}  # the boss-room zone covers the room; the rest are one cell (300)
PAIR_SPOTS = ['Gate', 'Depth', 'Boss']  # exchanges between two companions the pair zones open
PAIR_ZONE_FIRST = 29  # zone ids 29..31
PILLAR_NAME = 'dn0 pillar 01a'  # level 1's freestanding column: four stand in every boss room
PLATE_NAME = 'anchorplate a01'  # a flat metal plate (112 x 120 x 10 cm model, thin along its z), laid flat as a floor plate
AREAS_PER_DEPTH = 3
MAX_DEPTH_MAZE = 5


def depth_of(area: int) -> int:
    return (area - 1) // AREAS_PER_DEPTH + 1


def is_staircase(area: int) -> bool:
    return area % AREAS_PER_DEPTH == 0


# ----------------------------------------------------------------- random
class Rng:
    """splitmix64 seeding, xorshift64* stream. Integers only, so a C++ port
    reproduces every draw."""

    MASK = (1 << 64) - 1

    def __init__(self, seed: int, area: int):
        x = (seed * 0x9E3779B97F4A7C15 + area * 0xBF58476D1CE4E5B9 + 0x94D049BB133111EB) & self.MASK
        for _ in range(3):
            x = (x + 0x9E3779B97F4A7C15) & self.MASK
            z = x
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
            x = z ^ (z >> 31)
        self.state = x or 1

    def next(self) -> int:
        x = self.state
        x ^= x >> 12
        x ^= (x << 25) & self.MASK
        x ^= x >> 27
        self.state = x
        return (x * 0x2545F4914F6CDD1D) & self.MASK

    def below(self, n: int) -> int:
        return (self.next() >> 32) % n if n > 0 else 0

    def between(self, lo: int, hi: int) -> int:
        """Inclusive."""
        return lo + self.below(hi - lo + 1)

    def unit(self) -> float:
        return (self.next() >> 40) / float(1 << 24)

    def chance(self, percent: int) -> bool:
        return self.below(100) < percent

    def pick(self, items):
        return items[self.below(len(items))]


# ----------------------------------------------------------------- layout
@dataclass
class Room:
    c0: int
    r0: int
    c1: int  # inclusive
    r1: int
    kind: str = 'room'  # room | start | exit | maze
    entry: tuple = (0, 0)  # maze: the node cell corridors aim at
    goal: tuple = (0, 0)  # maze: the node cell the exit zone sits in
    style: int = 0  # layer-2 word for the room's cells: 0 plain, 0x11 the pillared wall/floor set pair
    purpose: str = 'plain'  # ordinary rooms: plain | store | barracks | shrine | quiet | gaol | surgery | kitchen | latrine | workshop
    copy: bool = False  # an exact copy of a source room (easter egg 4)
    show: bool = False  # the area's showpiece: a vanilla room of its purpose, exactly (pick_showpiece)
    src: int = -1  # the source room of the dressing (index into the stage's rooms), chosen with the purpose
    cut: frozenset = frozenset()  # cells of the rectangle that are not built (an L room, an octagon)
    pillars: bool = False  # a hall with four pillars in its inner corners

    @property
    def cells(self):
        return [(c, r) for r in range(self.r0, self.r1 + 1) for c in range(self.c0, self.c1 + 1) if (c, r) not in self.cut]

    @property
    def centre(self):
        if self.kind == 'maze':
            return self.entry
        return ((self.c0 + self.c1) // 2, (self.r0 + self.r1) // 2)

    def contains(self, c: int, r: int) -> bool:
        return self.c0 <= c <= self.c1 and self.r0 <= r <= self.r1 and (c, r) not in self.cut

    def touches(self, other: Room, gap: int = 1) -> bool:
        return not (self.c1 + gap < other.c0 or other.c1 + gap < self.c0 or self.r1 + gap < other.r0 or other.r1 + gap < self.r0)


@dataclass
class Layout:
    w: int
    h: int
    owner: list  # per cell: -1 unbuilt, >= 0 room index, CORRIDOR for corridor cells
    rooms: list
    doors: list = field(default_factory=list)  # ((c, r), (c2, r2)) edges that get a doorway, in creation order
    corridor_cells: list = field(default_factory=list)
    exit_door: tuple = ()  # ((inside cell), (outside cell)) of the keyed door (boss room, else exit)
    info: dict = field(default_factory=dict)  # boss / gate / gate_lever record ids the mod needs
    secrets: list = field(default_factory=list)  # (inside cell, outside cell, room) doorways that get a secret door
    vault_door: tuple = ()  # ((inside), (outside)) of the locked room that holds the boss key (two-key areas)
    vault_key_cell: tuple = ()  # where the vault's own key lies
    closets: list = field(default_factory=list)  # (closet cell, corridor cell, room) monster closets shut by a plate-opened portcullis
    maze_gates: list = field(default_factory=list)  # (gate cell, side q toward the goal, lever cell, lever side q) across the maze path
    bypass: tuple = ()  # (goal cell, outside cell with the gate, lever side q in the goal cell) of the companion bypass
    bypass_cells: list = field(default_factory=list)  # the bypass corridor's cells, entry end first
    key_cell: tuple = ()  # where the key (or lever) of the keyed door lies
    spur_ends: list = field(default_factory=list)  # the last cell of each dead-end corridor (a chest may lie there)
    treasury: object = None  # the hidden room behind a secret door (a rare chest and the second salve)
    wing: tuple = ()  # (near cell, far cell, lever cell, lever side): the portcullis that cuts off the boss wing
    blocked: set = field(default_factory=set)  # doorway edges barricaded shut (frozensets)
    blocked_doors: list = field(default_factory=list)  # the same as (room cell, corridor cell), in order
    archetype: str = 'warren'
    mutator: str = 'none'
    terrain: bytes = b''  # the .rft served with the level
    gate: tuple = ()  # ((boss cell), (exit cell)) of the gate the boss death opens, when a boss room exists
    pen: tuple = ()  # ((pen cell), (boss cell), pen room) of the boss pen (PEN_CHANCE)

    CORRIDOR = 10_000
    wander = 0  # the corridor hash salt of this plan (generate_layout)

    def at(self, c: int, r: int) -> int:
        return self.owner[r * self.w + c] if 0 <= c < self.w and 0 <= r < self.h else -1

    def built(self, c: int, r: int) -> bool:
        return self.at(c, r) >= 0

    def is_door(self, a, b) -> bool:
        # a set kept beside the list (appended to or replaced whole, as in gen.lua's Layout:is_door)
        if getattr(self, '_door_list', None) is not self.doors:
            self._door_list, self._door_n, self._door_set = self.doors, 0, set()
        for d in self.doors[self._door_n:]:
            self._door_set.add(frozenset(d))
        self._door_n = len(self.doors)
        return frozenset((a, b)) in self._door_set

    @property
    def exit_room(self) -> Room:
        return next(r for r in self.rooms if r.kind in ('exit', 'maze'))

    @property
    def boss_room(self):
        return next((r for r in self.rooms if r.kind == 'boss'), None)

    def picture(self) -> list[str]:
        out = []
        for r in range(self.h):
            line = ''
            for c in range(self.w):
                o = self.at(c, r)
                if o < 0:
                    line += '#'
                elif o == self.CORRIDOR:
                    line += '+'
                else:
                    k = self.rooms[o].kind
                    line += 'S' if k == 'start' else 'X' if k == 'exit' else 'M' if k == 'maze' else 'B' if k == 'boss' else 'C' if k == 'closet' else '.'
            out.append(line)
        return out


def _rect_free(rooms, c0, r0, c1, r1) -> bool:
    probe = Room(c0, r0, c1, r1)
    return not any(probe.touches(o) for o in rooms)


def _carve_maze(lay: Layout, rng: Rng, m: Room, index: int) -> None:
    """A perfect maze on the odd grid of the rect: nodes every second cell from the
    corner, passages between them (recursive backtracker, deterministic). Uncarved
    cells stay unbuilt, so the game's walls come out of the grid encoding."""
    nodes_c = (m.c1 - m.c0) // 2 + 1
    nodes_r = (m.r1 - m.r0) // 2 + 1
    visited = [[False] * nodes_r for _ in range(nodes_c)]

    def cell_of(i, j):
        return (m.c0 + 2 * i, m.r0 + 2 * j)

    def carve(c, r):
        lay.owner[r * lay.w + c] = index

    stack = [(0, 0)]
    visited[0][0] = True
    carve(*cell_of(0, 0))
    order = 0
    while stack:
        i, j = stack[-1]
        choices = []
        for di, dj in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < nodes_c and 0 <= nj < nodes_r and not visited[ni][nj]:
                choices.append((ni, nj))
        if not choices:
            stack.pop()
            continue
        ni, nj = rng.pick(choices)
        visited[ni][nj] = True
        c, r = cell_of(i, j)
        nc, nr = cell_of(ni, nj)
        carve((c + nc) // 2, (r + nr) // 2)
        carve(nc, nr)
        stack.append((ni, nj))
        order += 1


def _route(lay: Layout, a, b, blocked) -> list:
    """Deterministic cheapest path on the cell grid from a to b: a step costs 1,
    a turn 3 (long straight corridors), the outer ring and `blocked` cells (the
    protected rooms, except b itself) cannot be entered. Bucketed Dijkstra over
    (cell, heading) states with insertion-order ties, so the native port matches."""
    w, h = lay.w, lay.h
    INF = 1 << 30
    # the search stays inside a box round the two ends (ROUTE_MARGIN cells beyond them): a
    # corridor never needs to wander further, and the box keeps the search to a few hundred
    # states instead of the whole grid (the build runs under the runtime's instruction budget)
    minc, maxc = max(1, min(a[0], b[0]) - ROUTE_MARGIN), min(w - 2, max(a[0], b[0]) + ROUTE_MARGIN)
    minr, maxr = max(1, min(a[1], b[1]) - ROUTE_MARGIN), min(h - 2, max(a[1], b[1]) + ROUTE_MARGIN)
    best = {}
    parent = {}  # state -> the state it was reached from (a state is expanded once, at its final cost)
    buckets = {0: [(a, -1)]}
    cost = 0
    while cost < 8 * (w + h) and buckets:
        if cost not in buckets:
            cost += 1
            continue
        for cell, heading in buckets.pop(cost):
            if best.get((cell, heading), INF) < cost:
                continue
            if cell == b:
                path = []
                state = (cell, heading)
                while state is not None:
                    path.append(state[0])
                    state = parent.get(state)
                path.reverse()
                return path
            for q, (dx, dz) in enumerate(SIDE):
                n = (cell[0] + dx, cell[1] + dz)
                if not (minc <= n[0] <= maxc and minr <= n[1] <= maxr):
                    continue
                if n != b and n in blocked:
                    continue
                c2 = cost + 1 + _wander(lay, *n) + (TURN_COST if heading not in (-1, q) else 0)
                if best.get((n, q), INF) <= c2:
                    continue
                best[(n, q)] = c2
                parent[(n, q)] = (cell, heading)
                buckets.setdefault(c2, []).append((n, q))
        cost += 1
    return []


def _carve_corridor(lay: Layout, rng: Rng, a: Room, b: Room) -> None:
    """A one-cell corridor between two room centres routed around the protected
    rooms (the exit, a maze), which it may only enter at the destination cell.
    Crossings into a different owner become doorways."""
    protected = [r for r in lay.rooms if r.kind in ('exit', 'maze', 'boss')]
    # a plain exit room may be entered anywhere (its cells are all its own, so one door results);
    # a maze only at its entry node, since its other cells are walls or passages
    blocked = {(c, r) for p in protected if p is not b or p.kind == 'maze' for (c, r) in p.cells}
    path = _route(lay, a.centre, b.centre, blocked)
    for cc, rr in path:
        if lay.owner[rr * lay.w + cc] == -1 and not any(p.contains(cc, rr) for p in protected):
            lay.owner[rr * lay.w + cc] = Layout.CORRIDOR
            lay.corridor_cells.append((cc, rr))
    # a second lane along the middle third, on the left of the way, now and then
    (ac_, ar_), (bc_, br_) = a.centre, b.centre
    pick = ((ac_ * 73856093) ^ (ar_ * 19349663) ^ (bc_ * 83492791) ^ (br_ * 2654435) ^ lay.wander) & 0xFFFF
    if len(path) >= WIDE_MIN and pick % 100 < WIDE_CHANCE:
        third = len(path) // 3
        for k in range(third, 2 * third):
            (cc, rr), (nc, nr) = path[k], path[k + 1]
            sc, sr = cc - (nr - rr), rr + (nc - cc)
            if (lay.owner[rr * lay.w + cc] == Layout.CORRIDOR and 2 <= sc <= lay.w - 3 and 2 <= sr <= lay.h - 3
                    and lay.owner[sr * lay.w + sc] == -1 and not any(p.c0 <= sc <= p.c1 and p.r0 <= sr <= p.r1 for p in protected)):
                lay.owner[sr * lay.w + sc] = Layout.CORRIDOR
                lay.corridor_cells.append((sc, sr))
    for (x1, z1), (x2, z2) in zip(path, path[1:]):
        o1, o2 = lay.at(x1, z1), lay.at(x2, z2)
        if o1 >= 0 and o2 >= 0 and o1 != o2 and not lay.is_door(((x1, z1)), ((x2, z2))):
            lay.doors.append(((x1, z1), (x2, z2)))


def _reachable(lay: Layout, start) -> set:
    """Cells reachable from `start` through open edges and doorways (BFS)."""
    seen = {start}
    queue = [start]
    while queue:
        c, r = queue.pop(0)
        for dx, dz in SIDE:
            n = (c + dx, r + dz)
            if n in seen or not lay.built(*n):
                continue
            if side_kind(lay, c, r, SIDE.index((dx, dz))) == WALL:
                continue
            seen.add(n)
            queue.append(n)
    return seen


def generate_layout(rng: Rng, w: int, h: int, area: int, start_cell, arch_name: str = 'warren', block_doors: bool = False, plain: bool = False, shapes=None) -> Layout:
    """Rooms that never touch (sizes and counts by archetype), a 3x3 start room around
    `start_cell`, the exit room farthest from it (a maze from depth 2), corridors
    along a nearest-neighbour spanning tree (the exit room only ever a leaf) plus a
    few loops, connectivity repaired by BFS, and exactly one doorway into the exit."""
    depth = depth_of(area)
    arch = ARCHETYPES[arch_name]
    sc, sr = start_cell
    rooms = [Room(sc - 1, sr - 1, sc + 1, sr + 1, 'start')]
    wanted = min(2 * arch['rooms'] + 3 * depth, MAX_ROOMS)  # Hunter (2026-10-22): bigger areas, growing with depth
    attempts = 0
    big_done = not arch['big']
    spine_n = max(3, wanted // SPINE_SHARE)
    heading = rng.below(4)
    stall = 0
    while len(rooms) < wanted and attempts < 2000:
        attempts += 1
        if len(rooms) < spine_n and stall >= SPINE_STALL:
            spine_n = len(rooms)  # the spine is boxed in: wings from here
        stamp = None
        if not big_done:
            rw, rh = rng.between(8, 9), rng.between(8, 9)
        else:
            hall = depth >= 2 and rng.chance(arch['hall'])
            lo, hi = arch['hall_size'] if hall else arch['size']
            rw = rng.between(lo, hi)
            rh = rng.between(lo, hi)
            if shapes and rng.chance(STAMP_CHANCE):  # a room shaped like one of the stone's own
                stamp = rng.pick(shapes)
                k = 2 if max(stamp[0], stamp[1]) <= 4 else 1
                rw, rh = stamp[0] * k, stamp[1] * k
        # beside a room already placed: a side, a gap of ground, and an offset along that side
        if len(rooms) < spine_n:  # the spine: beside the last room, mostly onward
            anchor = rooms[-1]
            q = heading if rng.chance(SPINE_STRAIGHT) else rng.below(4)
        else:  # a wing: the newest district grows, or a new one starts off the spine
            anchor = rooms[-1] if rng.chance(WING_GROW) else rooms[rng.below(spine_n)]
            q = rng.below(4)
        stall += 1
        gap = rng.between(*arch['gap'])
        if q in (0, 2):
            c0 = anchor.c0 + rng.between(-(rw - 1), anchor.c1 - anchor.c0)
            r0 = anchor.r0 - gap - rh if q == 0 else anchor.r1 + gap + 1
        else:
            r0 = anchor.r0 + rng.between(-(rh - 1), anchor.r1 - anchor.r0)
            c0 = anchor.c0 - gap - rw if q == 1 else anchor.c1 + gap + 1
        if not (2 <= c0 and c0 + rw - 1 <= w - 3 and 2 <= r0 and r0 + rh - 1 <= h - 3):
            continue
        room = Room(c0, r0, c0 + rw - 1, r0 + rh - 1)
        if any(room.touches(o) for o in rooms):
            continue
        big_done = True
        stall = 0
        room.style = 0x11 if rng.chance(arch['style']) else 0
        if stamp is not None:
            k = rw // stamp[0]
            mask = {(c0 + dc * k + i, r0 + dr * k + j) for dc, dr in stamp[2] for i in range(k) for j in range(k)}
            if room.centre in mask:
                room.cut = frozenset((c, r) for r in range(room.r0, room.r1 + 1) for c in range(room.c0, room.c1 + 1) if (c, r) not in mask)
        elif rw >= 4 and rh >= 4 and rng.chance(35):
            room.cut = _room_cut(rng, room)
        rooms.append(room)
    start = rooms[0]
    # the exit: the farthest room from the start; when no boss room fits beside it (or beside the maze
    # that replaces it), the next farthest, up to EXIT_TRIES (2026-10-22: some areas had no boss)
    order = sorted(range(1, len(rooms)), key=lambda i: (100000 - abs(rooms[i].centre[0] - start.centre[0]) - abs(rooms[i].centre[1] - start.centre[1])) * 1000 + i)
    tries = order[:EXIT_TRIES]
    boss = None
    gate = None
    for k, far in enumerate(tries):
        plain_exit = rooms[far]
        rooms[far].kind = 'exit'
        # from depth 2 the exit is a maze; it replaces the farthest room when a rect fits
        if depth >= 2:
            m = 7 + 2 * min(depth - 2, MAX_DEPTH_MAZE - 2)
            others = rooms[:far] + rooms[far + 1 :]
            placed = None
            for _ in range(200):
                c0 = rng.between(2, w - 3 - m)
                r0 = rng.between(2, h - 3 - m)
                if _rect_free(others, c0, r0, c0 + m - 1, r0 + m - 1):
                    placed = (c0, r0)
                    break
            if placed is not None:
                c0, r0 = placed
                corners = [(c0, r0), (c0 + m - 1, r0), (c0, r0 + m - 1), (c0 + m - 1, r0 + m - 1)]
                entry = min(corners, key=lambda p: abs(p[0] - start.centre[0]) + abs(p[1] - start.centre[1]))
                goal = (c0 + m - 1 - (entry[0] - c0), r0 + m - 1 - (entry[1] - r0))
                rooms[far] = Room(c0, r0, c0 + m - 1, r0 + m - 1, 'maze', entry, goal)
        # the boss room: 4..5 cells a side, touching the exit at its entry cell (the maze's entry node, or
        # any boundary cell of a plain exit room); the exit is then reachable only through it
        exit_rect = rooms[far]
        entry_cells = [exit_rect.entry] if exit_rect.kind == 'maze' else [(c, r) for (c, r) in exit_rect.cells if c in (exit_rect.c0, exit_rect.c1) or r in (exit_rect.r0, exit_rect.r1)]
        for attempt in range(240):
            ec, er = rng.pick(entry_cells)
            q = rng.below(4)
            bc, br = ec + SIDE[q][0], er + SIDE[q][1]  # the boss cell next to the entry cell
            bw, bh = (rng.between(4, 5), rng.between(4, 5)) if attempt < 120 else (rng.between(3, 4), rng.between(3, 4))
            c0 = bc - rng.below(bw) if SIDE[q][1] != 0 else (bc if SIDE[q][0] > 0 else bc - bw + 1)
            r0 = br - rng.below(bh) if SIDE[q][0] != 0 else (br if SIDE[q][1] > 0 else br - bh + 1)
            c1, r1 = c0 + bw - 1, r0 + bh - 1
            if not (2 <= c0 and c1 <= w - 3 and 2 <= r0 and r1 <= h - 3):
                continue
            probe = Room(c0, r0, c1, r1, 'boss')
            if probe.touches(exit_rect, 0) or any(probe.touches(o) for i, o in enumerate(rooms) if i != far):
                continue
            boss = probe
            gate = ((ec, er), (bc, br))  # (exit side, boss side)
            break
        if boss is not None:
            break
        if k < len(tries) - 1:  # this one stays an ordinary room; the next farthest is tried
            plain_exit.kind = 'room'
            rooms[far] = plain_exit
    if boss is not None:
        rooms.append(boss)
    boss_index = len(rooms) - 1 if boss is not None else -1
    # (after the exit and the boss room, so they never take the ground those need)
    fill = min(len(rooms) * FILL_SHARE // 100, FILL_MAX_ROOMS - len(rooms))
    placed = tries = 0
    while placed < fill and tries < FILL_TRIES:
        tries += 1
        rw, rh = rng.between(*FILL_SIZE), rng.between(*FILL_SIZE)
        anchor = rng.pick(rooms)
        q = rng.below(4)
        if q in (0, 2):
            c0 = anchor.c0 + rng.between(-(rw - 1), anchor.c1 - anchor.c0)
            r0 = anchor.r0 - 1 - rh if q == 0 else anchor.r1 + 2
        else:
            r0 = anchor.r0 + rng.between(-(rh - 1), anchor.r1 - anchor.r0)
            c0 = anchor.c0 - 1 - rw if q == 1 else anchor.c1 + 2
        if not (2 <= c0 and c0 + rw - 1 <= w - 3 and 2 <= r0 and r0 + rh - 1 <= h - 3):
            continue
        room = Room(c0, r0, c0 + rw - 1, r0 + rh - 1)
        if any(room.touches(o) for o in rooms):
            continue
        rooms.append(room)
        placed += 1
    owner = [-1] * (w * h)
    for i, room in enumerate(rooms):
        if room.kind == 'maze':
            continue
        for c, r in room.cells:
            owner[r * w + c] = i
    lay = Layout(w, h, owner, rooms)
    lay.wander = (area * 40503 + 7) & 0xFFFF
    if rooms[far].kind == 'maze':
        _carve_maze(lay, rng, rooms[far], far)
    if boss is not None:
        lay.doors.append((gate[1], gate[0]))  # the gate: boss side first, as a kept door is (inside, outside)
        lay.gate = (gate[1], gate[0])
    # spanning tree; the exit (and the boss room, when present) is never a source so it ends up a leaf;
    # with a boss room the exit is not a tree node at all: it hangs off the boss room through the gate
    leaf = boss_index if boss is not None else far
    linked = [0]
    edges = []
    while len(linked) < len(rooms) - (1 if boss is not None else 0):
        best = None
        for a in linked:
            if a == leaf:
                continue
            for b in range(len(rooms)):
                if b in linked or (boss is not None and b == far):
                    continue
                d = abs(rooms[a].centre[0] - rooms[b].centre[0]) + abs(rooms[a].centre[1] - rooms[b].centre[1])
                if best is None or d < best[0]:
                    best = (d, a, b)
        edges.append((best[1], best[2]))
        linked.append(best[2])
    # loops between near rooms (short corridors and extra doorways, as the shipped levels have)
    for _ in range(len(rooms) * (LOOP_BASE + LOOP_PER * arch['loops']) // 100):
        a, k = rng.below(len(rooms)), rng.below(LOOP_NEAREST)
        if a in (far, boss_index):
            continue
        ac, ar = rooms[a].centre
        near = sorted((abs(rooms[j].centre[0] - ac) + abs(rooms[j].centre[1] - ar)) * 1000 + j for j in range(len(rooms))
                      if j not in (a, far, boss_index) and (a, j) not in edges and (j, a) not in edges)  # rooms it is not yet joined to
        if k >= len(near):
            continue
        edges.append((a, near[k] % 1000))
    for a, b in edges:
        _carve_corridor(lay, rng, rooms[a], rooms[b])
    # the keyed room (the boss room, else the exit) keeps exactly one corridor doorway: the first one made;
    # the exit keeps only the gate
    keyed = rooms[leaf]
    exit_room = rooms[far]

    def touches(room, d):
        return room.contains(*d[0]) or room.contains(*d[1])

    def is_gate(d):
        return boss is not None and (d == lay.gate or d == (lay.gate[1], lay.gate[0]))

    kept = None
    for d in lay.doors:
        if touches(keyed, d) and not is_gate(d) and kept is None:
            kept = d if keyed.contains(*d[0]) else (d[1], d[0])

    def prune():
        out = []
        for d in lay.doors:
            if is_gate(d) or (kept is not None and (d == kept or d == (kept[1], kept[0]))):
                out.append(d)
            elif not touches(exit_room, d) and not touches(keyed, d):
                out.append(d)
        lay.doors = out

    prune()
    # connectivity repair: every room (and the exit) must be reachable from the start
    for _ in range(6):
        reach = _reachable(lay, start.centre)
        missing = [i for i, room in enumerate(rooms) if room.centre not in reach and not (boss is not None and i == far)]
        if not missing:
            break
        i = missing[0]
        near = min((j for j in range(len(rooms)) if rooms[j].centre in reach), key=lambda j: abs(rooms[j].centre[0] - rooms[i].centre[0]) + abs(rooms[j].centre[1] - rooms[i].centre[1]))
        before = len(lay.doors)
        _carve_corridor(lay, rng, rooms[near], rooms[i])
        new = [d for d in lay.doors[before:] if touches(keyed, d) and not is_gate(d)]
        if kept is None and new:
            kept = new[0] if keyed.contains(*new[0][0]) else (new[0][1], new[0][0])
        prune()
    lay.exit_door = kept if kept else ()
    _secret_passages(lay, rng, depth)
    _closets(lay, rng, depth)
    _boss_pen(lay, rng)
    _maze_gates(lay, rng, depth)
    _maze_bypass(lay)
    _spurs(lay, rng, arch['spurs'])
    if plain:  # the backrooms: no treasury, no wing gate
        _segment_corridors(lay)
        return lay
    _treasury(lay, rng)
    if block_doors:
        _block_doors(lay, rng, depth)
    _wing_gate(lay)
    _segment_corridors(lay)
    return lay


def _block_doors(lay: Layout, rng: Rng, depth: int) -> None:
    """Doorways between an ordinary room with two doorways or more and a corridor, barricaded from
    the room side; each only when everything the player could reach (secret doors shut) stays
    reachable without it. Picked at random among the candidates, in door order."""
    count = min(1 + depth // 2, MAX_BLOCKED)
    start = lay.rooms[0].centre
    secret_edges = {frozenset((s_in, s_out)) for s_in, s_out, _ in lay.secrets}
    full = len(_reachable_shut(lay, start, secret_edges))
    protected = set(secret_edges)
    if lay.exit_door:
        protected.add(frozenset(lay.exit_door))
    if lay.gate:
        protected.add(frozenset(lay.gate))
    for a, b, _ in lay.closets:
        protected.add(frozenset((a, b)))
    cand = []
    for a, b in lay.doors:
        if frozenset((a, b)) in protected:
            continue
        oa, ob = lay.at(*a), lay.at(*b)
        if oa == Layout.CORRIDOR and 0 <= ob < len(lay.rooms):
            a, b, oa, ob = b, a, ob, oa
        if not (0 <= oa < len(lay.rooms) and ob == Layout.CORRIDOR):
            continue
        room = lay.rooms[oa]
        if room.kind != 'room':
            continue
        if sum(1 for d in lay.doors if room.contains(*d[0]) or room.contains(*d[1])) < 2:
            continue
        cand.append((a, b))
    while cand and len(lay.blocked_doors) < count:
        a, b = cand.pop(rng.below(len(cand)))
        e = frozenset((a, b))
        lay.blocked.add(e)
        if len(_reachable_shut(lay, start, secret_edges)) != full:
            lay.blocked.discard(e)
        else:
            lay.blocked_doors.append((a, b))


def _treasury(lay: Layout, rng: Rng) -> None:
    """The hidden puzzle (Hunter, 2026-10-22): a 2x2 room off an ordinary room, behind a
    wall-looking secret door whose brick switch is on the host room's own wall. It touches nothing
    but its host. A rare chest and the second healing salve lie inside."""
    hosts = [room for room in lay.rooms if room.kind == 'room']
    if not hosts:
        return
    for _ in range(80):
        host = rng.pick(hosts)
        c, r = rng.pick(host.cells)
        q = rng.below(4)
        dx, dz = SIDE[q]
        oc, orr = c + dx, r + dz
        if host.contains(oc, orr):
            continue
        c0 = oc if dx >= 0 else oc - 1
        r0 = orr if dz >= 0 else orr - 1
        if dx != 0:
            r0 = orr - rng.below(2)
        else:
            c0 = oc - rng.below(2)
        room = Room(c0, r0, c0 + 1, r0 + 1, 'treasury')
        if not (2 <= c0 and c0 + 1 <= lay.w - 3 and 2 <= r0 and r0 + 1 <= lay.h - 3):
            continue
        if any(lay.built(cc, rr) for cc, rr in room.cells):
            continue
        if any(room.touches(o) for o in lay.rooms if o is not host):
            continue
        if any(lay.built(cc + ex, rr + ez) and not host.contains(cc + ex, rr + ez)
               for cc, rr in room.cells for ex, ez in SIDE if not room.contains(cc + ex, rr + ez)):
            continue
        index = len(lay.rooms)
        lay.rooms.append(room)
        for cc, rr in room.cells:
            lay.owner[rr * lay.w + cc] = index
        lay.doors.append(((c, r), (oc, orr)))
        lay.secrets.insert(0, ((c, r), (oc, orr), host))  # first, so it always gets a secret door record
        lay.treasury = room
        return


def _wing_gate(lay: Layout) -> None:
    """The main puzzle (Hunter, 2026-10-22): a portcullis on a doorway that every way to the boss
    door passes through, cutting the area into the near side and the boss wing; its lever is on the
    near side, in a dead end when there is one, else on a room wall, as far from the gate as it can
    be. The wing must hold two ordinary rooms or more; the doorway nearest the boss door that
    allows that is chosen. Secret doors count as open, so no passage goes round the gate."""
    if not lay.exit_door:
        return
    start = lay.rooms[0].centre
    target = lay.exit_door[1]
    skip = [room for room in lay.rooms if room.kind in ('start', 'exit', 'maze', 'boss', 'closet', 'treasury', 'pen')]
    secret_edges = {frozenset((s_in, s_out)) for s_in, s_out, _ in lay.secrets}
    excluded = set(secret_edges)
    excluded.add(frozenset(lay.exit_door))
    if lay.gate:
        excluded.add(frozenset(lay.gate))
    parent = {start: None}
    queue = [start]
    head = 0
    while head < len(queue):
        c, r = queue[head]
        head += 1
        if (c, r) == target:
            break
        for q, (dx, dz) in enumerate(SIDE):
            n = (c + dx, r + dz)
            if n in parent or not lay.built(*n) or side_kind(lay, c, r, q) == WALL or frozenset(((c, r), n)) in lay.blocked:
                continue
            parent[n] = (c, r)
            queue.append(n)
    if target not in parent:
        return
    path = []
    cell = target
    while cell is not None:
        path.append(cell)
        cell = parent[cell]
    path.reverse()
    # candidates: a doorway, or the edge between two corridor cells (a corridor is one cell wide, so
    # a portcullis on that edge closes it), walked back from the boss door; the first that cuts the
    # area with a wing of two ordinary rooms or more wins, else one room or more
    pairs = list(zip(path, path[1:]))
    for need in (2, 1):
        for a, b in reversed(pairs):
            e = frozenset((a, b))
            if e in excluded:
                continue
            if any(room.contains(*a) or room.contains(*b) for room in skip):
                continue
            if not (lay.is_door(a, b) or (lay.at(*a) == Layout.CORRIDOR and lay.at(*b) == Layout.CORRIDOR)):
                continue
            reach = _reachable_shut(lay, start, {e})
            if target in reach:
                continue
            if sum(1 for room in lay.rooms if room.kind == 'room' and room.centre not in reach) < need:
                continue
            near = _reachable_shut(lay, start, {e} | secret_edges)
            lever = _wing_lever(lay, near, b)
            if lever is not None:
                lay.wing = (a, b, lever[0], lever[1])
                return


def _wing_lever(lay: Layout, reach: set, gate):
    def far(cell):
        return abs(cell[0] - gate[0]) + abs(cell[1] - gate[1])
    def walled(cell):
        return any(side_kind(lay, cell[0], cell[1], q) == WALL for q in range(4))
    best = None
    for cell in lay.spur_ends:
        if cell in reach and walled(cell) and (best is None or far(cell) > far(best)):
            best = cell
    if best is None:
        for room in lay.rooms:
            if room.kind != 'room' or room.centre not in reach:
                continue
            for cell in room.cells:
                if any(side_kind(lay, cell[0], cell[1], q) == WALL for q in range(4)) and (best is None or far(cell) > far(best)):
                    best = cell
    if best is None:
        return None
    return best, next(q for q in range(4) if side_kind(lay, best[0], best[1], q) == WALL)


def _room_cut(rng: Rng, room: Room) -> frozenset:
    """An L room (one corner quadrant unbuilt, never the centre) or an octagon (the four corner
    cells unbuilt), for rooms at least 4 cells a side. Two rng calls at most."""
    rw, rh = room.c1 - room.c0 + 1, room.r1 - room.r0 + 1
    if rng.below(2) == 0:
        q = rng.below(4)
        cw, ch = (rw - 1) // 2, (rh - 1) // 2
        cols = range(room.c0, room.c0 + cw) if q in (0, 2) else range(room.c1 - cw + 1, room.c1 + 1)
        rows = range(room.r0, room.r0 + ch) if q in (0, 1) else range(room.r1 - ch + 1, room.r1 + 1)
        return frozenset((c, r) for r in rows for c in cols)
    return frozenset([(room.c0, room.r0), (room.c1, room.r0), (room.c0, room.r1), (room.c1, room.r1)])


def _spurs(lay: Layout, rng: Rng, count: int) -> None:
    """Dead-end corridors: from a corridor cell, 2..4 cells straight into unbuilt ground that
    touches no room (so they open no doorway). The last cell may get a chest."""
    if not lay.corridor_cells:
        return
    for _ in range(count * 6):
        if len(lay.spur_ends) >= count:
            break
        c, r = rng.pick(lay.corridor_cells)
        q = rng.below(4)
        length = rng.between(2, 4)
        dx, dz = SIDE[q]
        cells = []
        for k in range(1, length + 1):
            cc, rr = c + dx * k, r + dz * k
            if not (1 <= cc < lay.w - 1 and 1 <= rr < lay.h - 1) or lay.at(cc, rr) != -1:
                break
            # clear of every room by a cell (a maze's cells are unowned, so the rects decide)
            if any(rm.c0 - 1 <= cc <= rm.c1 + 1 and rm.r0 - 1 <= rr <= rm.r1 + 1 for rm in lay.rooms):
                break
            cells.append((cc, rr))
        if len(cells) < 2:
            continue
        for cc, rr in cells:
            lay.owner[rr * lay.w + cc] = Layout.CORRIDOR
            lay.corridor_cells.append((cc, rr))
        lay.spur_ends.append(cells[-1])


def _maze_bypass(lay: Layout) -> None:
    """A corridor round the outside of the maze from its entry corner to its goal corner, so
    companions told to wait can be called straight to the goal once the player has solved it:
    a doorway at the entry, a portcullis at the goal end opened by a lever in the goal cell.
    Only with a boss room (the maze is then not the keyed room, which must keep one doorway);
    routed through unbuilt cells not touching any existing corridor, so nothing else joins it."""
    m = lay.exit_room
    if m.kind != 'maze' or lay.boss_room is None:
        return
    w, h = lay.w, lay.h
    e, g = m.entry, m.goal
    blocked = {(c, r) for r in range(h) for c in range(w) if lay.owner[r * w + c] != -1}
    blocked |= set(m.cells)
    for c, r in lay.corridor_cells:
        for dx, dz in SIDE:
            blocked.add((c + dx, r + dz))

    def outside(cell):
        c, r = cell
        out = []
        for dx, dz in ((-1 if c == m.c0 else 1, 0), (0, -1 if r == m.r0 else 1)):
            n = (c + dx, r + dz)
            if 1 <= n[0] < w - 1 and 1 <= n[1] < h - 1 and n not in blocked:
                out.append(n)
        return out

    for s in outside(e):
        for t in outside(g):
            path = _route(lay, s, t, blocked - {s})
            if not path:
                continue
            for c, r in path:
                lay.owner[r * w + c] = Layout.CORRIDOR
            lay.bypass_cells = list(path)
            lay.doors.append((e, s))
            lay.doors.append((g, t))
            lq = SIDE.index((t[0] - g[0], t[1] - g[1]))
            other = [(-1 if g[0] == m.c0 else 1, 0), (0, -1 if g[1] == m.r0 else 1)]
            lever_q = next(SIDE.index(d) for d in other if SIDE.index(d) != lq)
            lay.bypass = (g, t, lever_q)
            return


def _secret_passages(lay: Layout, rng: Rng, depth: int) -> None:
    """From depth 2, up to depth-1 (max 2) extra corridors between two ordinary rooms whose
    doorways at both ends get a secret door (a wall-looking door opened by a brick switch
    somewhere on that room's walls). The corridor is routed like any other."""
    count = min(max(depth - 1, 0), 2)
    rooms = [room for room in lay.rooms if room.kind == 'room']
    used = []
    made = 0
    for _ in range(count * 3):
        if made >= count:
            break
        pairs = [(a, b) for a in rooms for b in rooms if a is not b and not any(a is u or b is u for u in used) and abs(a.centre[0] - b.centre[0]) + abs(a.centre[1] - b.centre[1]) >= 6]
        if not pairs:
            break
        a, b = rng.pick(pairs)
        before = len(lay.doors)
        _carve_corridor(lay, rng, a, b)
        new = lay.doors[before:]
        ends = [d for d in new if (a.contains(*d[0]) or a.contains(*d[1]) or b.contains(*d[0]) or b.contains(*d[1]))]
        if len(ends) < 2:
            continue
        used += [a, b]
        made += 1
        for d in ends[:2]:
            room = a if (a.contains(*d[0]) or a.contains(*d[1])) else b
            inside = d[0] if room.contains(*d[0]) else d[1]
            outside = d[1] if inside == d[0] else d[0]
            lay.secrets.append((inside, outside, room))


def _closets(lay: Layout, rng: Rng, depth: int) -> None:
    """From depth 2, up to depth-1 (max 3) monster closets: a 2x2 room grown off a corridor
    cell, shut by a portcullis that a floor plate in the corridor opens."""
    count = min(max(depth - 1, 0), 3)
    for _ in range(count):
        for _attempt in range(60):
            if not lay.corridor_cells:
                return
            cc, cr = rng.pick(lay.corridor_cells)
            q = rng.below(4)
            dx, dz = SIDE[q]
            oc, orr = cc + dx, cr + dz  # the closet cell at the corridor's side
            c0 = oc if dx >= 0 else oc - 1
            r0 = orr if dz >= 0 else orr - 1
            if dx != 0:
                r0 = orr - rng.below(2)
            else:
                c0 = oc - rng.below(2)
            room = Room(c0, r0, c0 + 1, r0 + 1, 'closet')
            if not (2 <= c0 and c0 + 1 <= lay.w - 3 and 2 <= r0 and r0 + 1 <= lay.h - 3):
                continue
            # free cells, not touching any room (corridor cells beside it just get walls)
            if any(lay.built(c, r) for c, r in room.cells) or any(room.touches(o, 0) for o in lay.rooms) or any(room.touches(o) for o in lay.rooms if o.kind not in ('room', 'closet')):
                continue
            index = len(lay.rooms)
            lay.rooms.append(room)
            for c, r in room.cells:
                lay.owner[r * lay.w + c] = index
            lay.doors.append(((oc, orr), (cc, cr)))
            lay.closets.append(((oc, orr), (cc, cr), room))
            break


def _boss_pen(lay: Layout, rng: Rng) -> None:
    """A 2x2 pen grown off a boss-room cell (PEN_CHANCE), touching no other room; one doorway."""
    boss = lay.boss_room
    if boss is None or not rng.chance(PEN_CHANCE):
        return
    edge = [(c, r, q) for (c, r) in boss.cells for q in range(4) if not boss.contains(c + SIDE[q][0], r + SIDE[q][1])]
    for _attempt in range(30):
        c, r, q = rng.pick(edge)
        dx, dz = SIDE[q]
        oc, orr = c + dx, r + dz
        c0 = oc if dx >= 0 else oc - 1
        r0 = orr if dz >= 0 else orr - 1
        if dx != 0:
            r0 = orr - rng.below(2)
        else:
            c0 = oc - rng.below(2)
        room = Room(c0, r0, c0 + 1, r0 + 1, 'pen')
        if not (2 <= c0 and c0 + 1 <= lay.w - 3 and 2 <= r0 and r0 + 1 <= lay.h - 3):
            continue
        if any(lay.built(x, y) for x, y in room.cells):
            continue
        if any(room.touches(o, 0) for o in lay.rooms if o is not boss) or any(room.touches(o) for o in lay.rooms if o is not boss and o.kind not in ('room', 'closet')):
            continue
        index = len(lay.rooms)
        lay.rooms.append(room)
        for x, y in room.cells:
            lay.owner[y * lay.w + x] = index
        lay.doors.append(((oc, orr), (c, r)))
        lay.pen = ((oc, orr), (c, r), room)
        return


def _segment_corridors(lay: Layout) -> None:
    """Corridor cells grouped into pieces of at most SEG_MAX (breadth-first from each unassigned cell, in
    corridor order and side order); a doorway side between every two cells of different pieces."""
    seg = {}
    count = 0
    for start in lay.corridor_cells:
        if start in seg or lay.at(*start) != Layout.CORRIDOR:
            continue
        seg[start] = count
        queue, i, n = [start], 0, 1
        while i < len(queue) and n < SEG_MAX:
            c, r = queue[i]
            i += 1
            for dx, dz in SIDE:
                nb = (c + dx, r + dz)
                if n < SEG_MAX and nb not in seg and lay.at(*nb) == Layout.CORRIDOR:
                    seg[nb] = count
                    queue.append(nb)
                    n += 1
        count += 1
    for c, r in lay.corridor_cells:
        if (c, r) not in seg:
            continue
        for q in (2, 3):  # south and east: each edge once
            nb = (c + SIDE[q][0], r + SIDE[q][1])
            if nb in seg and seg[nb] != seg[(c, r)] and not lay.is_door((c, r), nb):
                lay.doors.append(((c, r), nb))


def _puzzle_parts(tp, lay, rng, kind, start, inside, outside, w, h, d_rooms, stage_no):
    """The boss lock's parts for a puzzle area: placements, objects, info and the opener cell."""
    shut = {frozenset((inside, outside))} | {frozenset((s_in, s_out)) for s_in, s_out, _ in lay.secrets}
    near = _reachable_shut(lay, start.centre, shut)
    dist = {outside: 0}
    order = [outside]
    i = 0
    while i < len(order):
        c, r = order[i]
        i += 1
        for q, (dx, dz) in enumerate(SIDE):
            n = (c + dx, r + dz)
            if n in near and n not in dist and side_kind(lay, c, r, q) != WALL and frozenset(((c, r), n)) not in lay.blocked:
                dist[n] = dist[(c, r)] + 1
                order.append(n)
    places, objects, info = [], [], {'puzzle': kind, 'puzzle_gate': tp.puzzle_gate_id}

    def lever_at(c, r, q, lever_id):
        x, z = world(c, r, w, h, 0.5 + 0.42 * SIDE[q][0], 0.5 + 0.42 * SIDE[q][1])
        places.append(_placement(tp.lever_place, 0x80000000 | lever_id, (x, LEVER_Y, z), SIDE_YAW[(q + 2) % 4]))

    def walls_of(c, r):
        return [q for q in range(4) if side_kind(lay, c, r, q) == WALL]

    if kind in ('plate', 'hold'):
        lo, hi = HOLD_DIST if kind == 'hold' else PLATE_DIST
        spots = [cell for cell in order if lo <= dist[cell] <= hi] or [outside]
        pc = rng.pick(spots)
        x, z = world(*pc, w, h)
        places.append(_placement(tp.plate_place, 0x80000000 | tp.puzzle_plate_id, (x, tp.floor_y, z), 0.0))
        info['puzzle_plate'] = [x, z]
        if kind == 'plate' and d_rooms:
            heavy = [got for got in (_proto(d_rooms, name) for name in HEAVY) if got is not None]
            around = [cell for cell in order if abs(dist[cell] - dist[pc]) <= 1 and cell != pc] or [pc]
            for _ in range(2 if heavy else 0):
                dy, raw = rng.pick(heavy)
                hc = rng.pick(around)
                hx, hz = world(*hc, w, h, rng.unit() * 0.5 + 0.25, rng.unit() * 0.5 + 0.25)
                objects.append(_put(raw, (hx, tp.floor_y + dy, hz), yaw_matrix(rng.unit() * 360.0)))
        return places, objects, info, pc
    if kind == 'order':
        rooms = [room for room in lay.rooms if room.kind == 'room' and room.centre in near]
        clue = next(((name, raw) for name, raw in tp.debris if name in CLUE and themed(tp, name, stage_no)), None)
        chosen = []
        first = outside
        for k in range(3):
            pool = [room for room in rooms if room not in chosen] or rooms
            if not pool:
                break
            room = rng.pick(pool)
            chosen.append(room)
            edge = [(c, r, q) for (c, r) in room.cells for q in walls_of(c, r)]
            if not edge:
                continue
            c, r, q = rng.pick(edge)
            if k == 0:
                first = (c, r)
            lever_at(c, r, q, tp.puzzle_lever_ids[k])
            if clue is not None:
                for j in range(k + 1):  # k + 1 bottles at its foot: the order
                    bx, bz = world(c, r, w, h, 0.5 + 0.3 * SIDE[q][0] + 0.12 * (j - k / 2) * SIDE[(q + 1) % 4][0], 0.5 + 0.3 * SIDE[q][1] + 0.12 * (j - k / 2) * SIDE[(q + 1) % 4][1])
                    objects.append(_object(clue[1], (bx, tp.floor_y + DEBRIS[clue[0]], bz), rng.unit() * 360.0))
        info['puzzle_levers'] = tp.puzzle_lever_ids[:3]
        return places, objects, info, first
    # timed: a lever some way back on the near side, and a second inside the boss room (the failsafe)
    lo, hi = TIMED_DIST
    spots = [cell for cell in order if lo <= dist[cell] <= hi and walls_of(*cell)] or [cell for cell in order if walls_of(*cell)] or [outside]
    lc = rng.pick(spots)
    lq = walls_of(*lc)
    lever_at(lc[0], lc[1], rng.pick(lq) if lq else 0, tp.puzzle_lever_ids[0])
    inner = walls_of(*inside) or [0]
    lever_at(inside[0], inside[1], inner[0], tp.puzzle_lever_ids[1])
    info['puzzle_levers'] = tp.puzzle_lever_ids[:2]
    info['puzzle_seconds'] = TIMED_BASE + TIMED_PER_CELL * dist.get(lc, lo)
    boss = lay.boss_room
    if boss is not None:
        x0, z0 = world(boss.c0, boss.r0, w, h, 0.0, 0.0)
        x1, z1 = world(boss.c1, boss.r1, w, h, 1.0, 1.0)
        info['puzzle_inside'] = [x0, z0, x1, z1]
    return places, objects, info, lc


def _maze_path(lay: Layout, m: Room) -> dict:
    """Parents of every carved maze cell from the entry (BFS over carved cells)."""
    parent = {m.entry: None}
    queue = [m.entry]
    while queue:
        c, r = queue.pop(0)
        for dx, dz in SIDE:
            n = (c + dx, r + dz)
            if n not in parent and m.contains(*n) and lay.built(*n):
                parent[n] = (c, r)
                queue.append(n)
    return parent


def _maze_gates(lay: Layout, rng: Rng, depth: int) -> None:
    """From depth 3, up to depth-2 (max 3) portcullises across the maze's entry-to-goal path,
    each opened by a lever placed in a dead end that is reachable from the entry before the
    gate. Gates go on passage cells (between two nodes), in path order; the lever of gate i is
    chosen among cells reachable with gates i.. closed and earlier gates open, off the path."""
    count = min(max(depth - 2, 0), 3)
    m = lay.exit_room
    if count == 0 or m.kind != 'maze':
        return
    parent = _maze_path(lay, m)
    if m.goal not in parent:
        return
    path = []
    cell = m.goal
    while cell is not None:
        path.append(cell)
        cell = parent[cell]
    path.reverse()  # entry .. goal
    on_path = set(path)
    # passage cells of the path (odd positions between nodes), skipping the first two and the last
    passages = [i for i in range(2, len(path) - 1) if (path[i][0] - m.c0) % 2 == 1 or (path[i][1] - m.r0) % 2 == 1]
    if len(passages) < count:
        count = len(passages)
    chosen = sorted(rng.pick(passages) for _ in range(count))
    chosen = sorted(set(chosen))
    gates = []
    for gi, i in enumerate(chosen):
        gate_cell = path[i]
        q = SIDE.index((path[i + 1][0] - gate_cell[0], path[i + 1][1] - gate_cell[1]))
        blocked = {path[j] for j in chosen[gi:]}
        # cells reachable from the entry with this and later gates shut
        seen = {m.entry}
        queue = [m.entry]
        while queue:
            c, r = queue.pop(0)
            for dx, dz in SIDE:
                n = (c + dx, r + dz)
                if n in seen or n in blocked or not m.contains(*n) or not lay.built(*n):
                    continue
                seen.add(n)
                queue.append(n)
        candidates = [cell for cell in seen if cell not in on_path and (cell[0] - m.c0) % 2 == 0 and (cell[1] - m.r0) % 2 == 0]
        if not candidates:
            continue
        lever_cell = rng.pick(sorted(candidates))
        walls = [wq for wq in range(4) if side_kind(lay, lever_cell[0], lever_cell[1], wq) == WALL]
        if not walls:
            continue
        gates.append((gate_cell, q, lever_cell, rng.pick(walls)))
    lay.maze_gates = gates


def solvable(lay: Layout) -> list[str]:
    """Hunter's rule: every gate's opener must be reachable from the player's side before the
    gate, and the exit goal reachable in the end. Simulates: all gated edges shut, then
    repeatedly opens every gate whose opener cell is reachable (the keyed door: the key/lever
    room; the boss gate: the boss room; secret doors: their switch room; maze gates: their lever
    cell; closets: their corridor cell)."""
    problems = []
    gated = []  # (edge (a, b), opener cell)
    if lay.exit_door:
        gated.append((lay.exit_door, lay.key_cell if lay.key_cell else lay.rooms[0].centre))
    if lay.gate:
        gated.append((lay.gate, lay.boss_room.centre if lay.boss_room else lay.rooms[0].centre))
    if lay.bypass:
        gated.append(((lay.bypass[0], lay.bypass[1]), lay.bypass[0]))
    if lay.vault_door:
        gated.append((lay.vault_door, lay.vault_key_cell))
    for inside, outside, room in lay.secrets:
        gated.append(((inside, outside), room.centre))
    for closet_cell, corridor_cell, room in lay.closets:
        gated.append(((closet_cell, corridor_cell), corridor_cell))
    for gate_cell, q, lever_cell, _ in lay.maze_gates:
        gated.append(((gate_cell, (gate_cell[0] + SIDE[q][0], gate_cell[1] + SIDE[q][1])), lever_cell))
    if lay.wing:
        gated.append(((lay.wing[0], lay.wing[1]), lay.wing[2]))
    shut = {frozenset(e) for e, _ in gated}
    opened = True
    reach = set()
    while opened:
        opened = False
        reach = _reachable_shut(lay, lay.rooms[0].centre, shut)
        for e, opener in gated:
            if frozenset(e) in shut and opener in reach:
                shut.discard(frozenset(e))
                opened = True
    ex = lay.exit_room
    goal = ex.goal if ex.kind == 'maze' else ex.centre
    if goal not in reach:
        problems.append('exit goal unreachable with every gate opened from the player side')
    for e, opener in gated:
        if frozenset(e) in shut:
            problems.append(f'gate {e} never opens: opener {opener} unreachable')
    return problems


def _reachable_shut(lay: Layout, start, shut: set) -> set:
    seen = {start}
    queue = [start]
    while queue:
        c, r = queue.pop(0)
        for q, (dx, dz) in enumerate(SIDE):
            n = (c + dx, r + dz)
            e = frozenset(((c, r), n))
            if n in seen or not lay.built(*n) or side_kind(lay, c, r, q) == WALL or e in shut or e in lay.blocked:
                continue
            seen.add(n)
            queue.append(n)
    return seen


def _l_cells(a, b, horizontal_first: bool) -> list:
    (c, r), (c2, r2) = a, b
    path = [(c, r)]
    cc, rr = c, r
    steps = []
    if horizontal_first:
        steps += [((1 if c2 > cc else -1), 0)] * abs(c2 - cc)
        steps += [(0, (1 if r2 > rr else -1))] * abs(r2 - rr)
    else:
        steps += [(0, (1 if r2 > rr else -1))] * abs(r2 - rr)
        steps += [((1 if c2 > cc else -1), 0)] * abs(c2 - cc)
    for dx, dz in steps:
        cc += dx
        rr += dz
        path.append((cc, rr))
    return path


# ----------------------------------------------------------------- grid encoding
def side_kind(lay: Layout, c: int, r: int, q: int) -> int:
    dx, dz = SIDE[q]
    me, other = lay.at(c, r), lay.at(c + dx, r + dz)
    if other < 0:
        return WALL
    if me == other:  # open, except where a corridor is cut into sectors (_segment_corridors)
        return DOOR if me == Layout.CORRIDOR and lay.is_door((c, r), (c + dx, r + dz)) else 0
    return DOOR if lay.is_door((c, r), (c + dx, r + dz)) else WALL


def corner_kind(lay: Layout, c: int, r: int, q: int, sides: list[int]) -> int:
    q2 = (q + 1) % 4
    e1, e2 = sides[q] != 0, sides[q2] != 0
    if e1 and e2:
        return 3
    if e1:
        return 1
    if e2:
        return 2
    (dx1, dz1), (dx2, dz2) = SIDE[q], SIDE[q2]
    n1 = (c + dx1, r + dz1)
    n2 = (c + dx2, r + dz2)
    d = (c + dx1 + dx2, r + dz1 + dz2)
    w1 = lay.built(*n1) and side_kind(lay, n1[0], n1[1], q2) != 0
    w2 = lay.built(*n2) and side_kind(lay, n2[0], n2[1], q) != 0
    wd = lay.built(*d) and (side_kind(lay, d[0], d[1], (q + 2) % 4) != 0 or side_kind(lay, d[0], d[1], (q + 3) % 4) != 0)
    return 4 if (w1 or w2 or wd) else 0


def encode_cell(lay: Layout, c: int, r: int) -> tuple[int, int, int]:
    if r == 0 or r == lay.h - 1 or c == 0 or c == lay.w - 1:  # the border ring, as the shipped grids
        word = (BORDER_TOP if r == 0 else 0) | (BORDER_BOTTOM if r == lay.h - 1 else 0) | (BORDER_LEFT if c == 0 else 0) | (BORDER_RIGHT if c == lay.w - 1 else 0)
        return word, 0, 0
    if not lay.built(c, r):
        # rock only beside built cells, as the shipped levels do (level 1: 329 rock cells, the
        # rest of the unbuilt grid empty); an area full of rock cost frames (Hunter, 7 FPS)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if (dx or dz) and lay.built(c + dx, r + dz):
                    return ROCK, 0, 0
        return 0, 0, 0
    sides = [side_kind(lay, c, r, q) for q in range(4)]
    word = BUILT
    for q in range(4):
        word |= sides[q] << (4 * q)
        word |= corner_kind(lay, c, r, q, sides) << (16 + 4 * q)
    o = lay.at(c, r)
    style = lay.rooms[o].style if 0 <= o < len(lay.rooms) else 0
    return word, 0, style


def encode_grid(lay: Layout) -> list[list[int]]:
    layers = [[0] * (lay.w * lay.h) for _ in range(3)]
    for r in range(lay.h):
        for c in range(lay.w):
            a, b, d = encode_cell(lay, c, r)
            i = r * lay.w + c
            layers[0][i], layers[1][i], layers[2][i] = a, b, d
    return layers


def decode_check(layers: list[list[int]], lay: Layout) -> list[str]:
    """Independent consistency check of an encoded grid: shared edges agree,
    walls face every unbuilt neighbour, corners match their two sides; plus the
    area rules: one doorway into the exit, everything reachable from the start."""
    problems = []
    w, h = lay.w, lay.h

    def cell(c, r):
        return layers[0][r * w + c] if 0 <= c < w and 0 <= r < h else None

    for r in range(h):
        for c in range(w):
            a = cell(c, r)
            if r == 0 or r == h - 1 or c == 0 or c == w - 1:
                continue  # the border ring
            if not a & BUILT:
                if a not in (ROCK, 0):
                    problems.append(f'unbuilt cell {c},{r} is {a:x}')
                continue
            for q in range(4):
                dx, dz = SIDE[q]
                b = cell(c + dx, r + dz)
                mine = (a >> 4 * q) & 0xF
                if b is None or not b & BUILT:
                    if mine != WALL:
                        problems.append(f'cell {c},{r} side {q} faces rock with {mine:x}')
                elif ((b >> (4 * ((q + 2) % 4))) & 0xF) != mine:
                    problems.append(f'cell {c},{r} side {q} disagrees with its neighbour')
                e1, e2 = mine != 0, ((a >> 4 * ((q + 1) % 4)) & 0xF) != 0
                k = (a >> (16 + 4 * q)) & 7
                want = {(True, True): 3, (True, False): 1, (False, True): 2}.get((e1, e2))
                if want is not None and k != want:
                    problems.append(f'cell {c},{r} corner {q} is {k}, want {want}')
                if want is None and k not in (0, 4):
                    problems.append(f'cell {c},{r} corner {q} is {k} on an open corner')
    exit_room = lay.exit_room
    doors_in = [d for d in lay.doors if exit_room.contains(*d[0]) or exit_room.contains(*d[1])]
    if len(doors_in) != 1 + (2 if lay.bypass else 0) or not lay.exit_door:
        problems.append(f'exit has {len(doors_in)} doorways')
    boss = lay.boss_room
    if boss is not None:
        boss_doors = [d for d in lay.doors if boss.contains(*d[0]) or boss.contains(*d[1])]
        if len(boss_doors) != 2 + (1 if lay.pen else 0) or not lay.gate:
            problems.append(f'boss room has {len(boss_doors)} doorways')
    reach = _reachable(lay, lay.rooms[0].centre)
    for room in lay.rooms:
        if room.centre not in reach and room.kind != 'closet':
            problems.append(f'{room.kind} room at {room.centre} unreachable')
    if exit_room.kind == 'maze' and exit_room.goal not in reach:
        problems.append('maze goal unreachable')
    problems += solvable(lay)
    return problems


# ----------------------------------------------------------------- level assembly
# Byte-level surgery on the template built by make_template.py. The native port
# does exactly the same steps, so both produce identical bytes for (seed, area).
MAGIC = 0x3D23AFCF
TAG_GRID, TAG_NODES, TAG_OBJECTS, TAG_ITEMS, TAG_PEOPLE, TAG_ENV = 0x3DED, 0x3D000000, 0x3DE10000, 0xDBC0, 0xCAC00001, 0xEC00DC00
TAG_OBJECT, TAG_PLACE, TAG_SPAWN, TAG_ITEM_DB, TAG_ITEM_STRINGS, TAG_ITEM_PLACES, TAG_PEOPLE_DB = 0x3DE10100, 0xDB01, 0xCAC0CA00, 0xDBDB, 0xDBCD, 0xDBCE, 0xCECDDB00
SCRIPT_PREFIX = b'LuaEvent(EndlessNext,'
START_X, START_Z = 8200.0, 3920.0  # the game's new-game spawn (constant 2B7684, static)
LIGHT_Y = 300.0
# only the arena names that have their own .rft, because the game loads <name>.rft with the level:
# the mod serves both members, so the arena's real terrain never shows under a generated area
POOL = ['arenao1', 'arenao2', 'arenao3', 'arenao4', 'arenao5', 'arena7']


def floor_name(area: int) -> str:
    """Member name an area is served under: an existing Resource.rpk level name
    (so the game's name lookup succeeds), cycling through the arena pool."""
    return POOL[(area - 1) % len(POOL)]


def _chunks(b: bytes):
    out, p = [], 0
    while p + 8 <= len(b):
        t, s = struct.unpack_from('<II', b, p)
        out.append((t, b[p + 8 : p + 8 + s]))
        p += 8 + s
    return out


def _chunk(t: int, payload: bytes) -> bytes:
    return struct.pack('<II', t, len(payload)) + payload


def _record_chunk_offset(data: bytes, tag: int) -> int:
    """Offset of a record chunk's payload (after its 8-byte header), or -1."""
    p = 0
    while p + 8 <= len(data):
        t, s = struct.unpack_from('<II', data, p)
        if t == tag:
            return p + 8
        p += s
    return -1


def _set_name16(data: bytes, name: str) -> bytes:
    """Rename a record: the 0x10000000 chunk's first 16 bytes."""
    o = _record_chunk_offset(data, TAG_NAME)
    if o < 0:
        raise ValueError('record has no name chunk')
    return data[:o] + name.encode('latin-1')[:16].ljust(16, b'\0') + data[o + 16 :]


def _set_door_opener(data: bytes, opener: int) -> bytes:
    """Door record chunk 0x40000: +4 = the key record id that unlocks it (static, KB)."""
    o = _record_chunk_offset(data, TAG_DOOR)
    if o < 0:
        raise ValueError('not a door record')
    return data[: o + 4] + struct.pack('<I', opener) + data[o + 8 :]


TAG_LOOK = 0x100000
TAG_DROPS = 0x200
DROP_HEAD, DROP_ROW = 0x18, 16
CONTAINER_HEAD, CONTAINER_ROW = 24, 12


def _clear_display_strings(data: bytes) -> bytes:
    """Look chunk +1C name / +20 description are 1-based indexes into the level's own string
    table; an imported record must not index another level's table."""
    o = _record_chunk_offset(data, TAG_LOOK)
    if o < 0:
        return data
    return data[: o + 0x1C] + struct.pack('<II', 0, 0) + data[o + 0x24 :]


def import_record(src_by_id: dict, src_id: int, dst_db, next_id_box: list, idmap: dict | None = None) -> int:
    """Copy a level-local record (a chest, a drop list) and everything it references by
    level-local id (0x80000000 | id) into `dst_db` under new ids (next_id_box[0] onward).
    Returns the new id, or 0 when the source id is missing."""
    idmap = {} if idmap is None else idmap
    if src_id in idmap:
        return idmap[src_id]
    src = src_by_id.get(src_id)
    if src is None:
        return 0
    new_id = next_id_box[0]
    next_id_box[0] += 1
    idmap[src_id] = new_id
    data = bytearray(_clear_display_strings(src.data))
    p = 0
    while p + 8 <= len(data):
        t, size = struct.unpack_from('<II', data, p)
        payload = p + 8
        if t == TAG_CONTAINER and size >= 8 + CONTAINER_HEAD:
            n = struct.unpack_from('<I', data, payload + 20)[0]
            for k in range(n):
                q = payload + CONTAINER_HEAD + k * CONTAINER_ROW
                if q + 4 > p + size:
                    break
                item = struct.unpack_from('<I', data, q)[0]
                if item & 0x80000000:
                    nid = import_record(src_by_id, item & 0x7FFFFFFF, dst_db, next_id_box, idmap)
                    struct.pack_into('<I', data, q, (0x80000000 | nid) if nid else 0)
        elif t == TAG_DROPS and size >= 8 + DROP_HEAD:
            q = payload + DROP_HEAD
            while q + DROP_ROW <= p + size:
                item = struct.unpack_from('<I', data, q)[0]
                if item & 0x80000000:
                    nid = import_record(src_by_id, item & 0x7FFFFFFF, dst_db, next_id_box, idmap)
                    struct.pack_into('<I', data, q, (0x80000000 | nid) if nid else 0)
                q += DROP_ROW
        p += size
    dst_db.records.append(rdb.Record(new_id, src.flags, 0, len(data), bytes(data)))
    return new_id


def _set_look_model(data: bytes, model: str) -> bytes:
    """Look chunk 0x100000: +0 = the Objlib model name (16 bytes)."""
    o = _record_chunk_offset(data, TAG_LOOK)
    if o < 0:
        raise ValueError('record has no look chunk')
    return data[:o] + model.encode('latin-1')[:16].ljust(16, b'\0') + data[o + 16 :]


def _set_device_target(data: bytes, target: int) -> bytes:
    """Device chunk 0x10000: +8 = the id the device drives (a lever's door; static, KB)."""
    o = _record_chunk_offset(data, TAG_DEVICE)
    if o < 0:
        raise ValueError('not a device record')
    return data[: o + 8] + struct.pack('<I', target) + data[o + 12 :]


def _set_container_rows(data: bytes, items: list[int]) -> bytes:
    """Container chunk 0x20000: 24-byte header (count at +20), then 12-byte rows
    (item id, 0, spot) copying the first existing row's spot."""
    p = 0
    while p + 8 <= len(data):
        t, s = struct.unpack_from('<II', data, p)
        if t == TAG_CONTAINER:
            c = data[p + 8 : p + s]
            n = struct.unpack_from('<I', c, 20)[0]
            spot = c[32:36] if n else b'\0' * 4
            body = b''.join(struct.pack('<II', it, 0) + spot for it in items)
            chunk = c[:20] + struct.pack('<I', len(items)) + body
            return data[:p] + struct.pack('<II', t, len(chunk) + 8) + chunk + data[p + s :]
        p += s
    raise ValueError('not a container record')


def _marker_record(src: rdb.Record, new_id: int, name: str, box, flags: int, zone_id: int, entry: int, level_id: int, script: bytes = b'') -> rdb.Record:
    """A marker record cloned from `src` with a new payload. Layout (offline,
    exanima01/02): u16 a, u16 b, u32 c (box size), u32 flags, u32 zone (+C),
    u32 0, u32 (+14: script length for zones, entry id for exits/arrivals), then
    +18: script text (zones) or the neighbouring level id (exits/arrivals)."""
    data = _set_name16(src.data, name)
    out = bytearray()
    p = 0
    while p + 8 <= len(data):
        t, s = struct.unpack_from('<II', data, p)
        if t == TAG_MARKER:
            if script:
                payload = struct.pack('<HHIIIII', box[0], box[1], box[2], flags, zone_id, 0, len(script)) + script
            else:
                payload = struct.pack('<HHIIIIII', box[0], box[1], box[2], flags, zone_id, 0, entry, level_id)
            out += struct.pack('<II', t, len(payload) + 8) + payload
        else:
            out += data[p : p + s]
        p += s
    return rdb.Record(new_id, src.flags, 0, len(out), bytes(out))


@dataclass
class Template:
    chunks: dict  # tag -> payload (top level)
    grid_names: bytes  # wall/floor set lists as stored
    light: bytes  # one 0x3D06 node chunk (tag+size+160)
    props: list  # [(name, raw 0x3DE10100 chunk)]
    stairs: bytes  # raw 0x3DE10100 chunk of the staircase decoration
    plate: bytes  # raw chunk of the floor plate decoration (unused: plates are devices now)
    marker_place: bytes  # raw 0xDB01 chunk
    chest_place: bytes
    door_place: bytes
    key_place: bytes
    fire_place: bytes
    lever_place: bytes
    gate_place: bytes
    item_db: bytes  # 0xDBDB chunk, raw
    item_strings: bytes  # 0xDBCD chunk, raw
    people_db: bytes  # 0xCECDDB00 chunk, raw
    arrival_id: int
    zone_id: int
    chest_ids: list
    key_ids: list
    door_ids: list
    key_chest_ids: list
    fire_ids: list
    lever_ids: list
    hazard_ids: list  # [push N, push W, push S, push E]
    fire_zone_ids: list  # one per fire slot (zone ids 11..15)
    gate_ids: list
    gate_lever_ids: list
    enemy_ids: list
    enemy_tiers: list  # [tier2, tier3, ...] lists of record ids
    boss_tiers: list  # [tier1, tier2, ...]
    floor_y: float
    secret_door_place: bytes = b''
    switch_place: bytes = b''
    plate_place: bytes = b''
    secret_door_ids: list = field(default_factory=list)  # 4 pairs: [a, b] per pair (both ends of a passage)
    switch_ids: list = field(default_factory=list)
    plate_fire_ids: list = field(default_factory=list)  # one plate per fire slot, targeting that fire
    plate_closet_ids: list = field(default_factory=list)  # one plate per closet, targeting its gate
    closet_gate_ids: list = field(default_factory=list)
    maze_gate_ids: list = field(default_factory=list)
    maze_lever_ids: list = field(default_factory=list)
    stages: list = field(default_factory=list)  # [(walls, floors)] tile-set stages by depth, from the ini
    terrain_head: bytes = b''  # .rft header (8) + palette (16) + sample float
    terrain_tile: bytes = b''  # one flat tile: flags, ix, iy, tag (16 bytes) + heights + layers; ix/iy and heights are rewritten
    companion_ids: list = field(default_factory=list)  # friendly records to find (make_companions.py)
    wall_props: list = field(default_factory=list)  # [(name, raw chunk)]
    debris: list = field(default_factory=list)
    chest_tiers: list = field(default_factory=list)  # [tier2, tier3, ...] chest record ids of deeper levels
    boss_bands: list = field(default_factory=list)  # per boss tier: [band1 ids, band2 ids, band3 ids]
    enemy_bands: list = field(default_factory=list)  # per enemy tier (tier 1 = enemies): the same
    pillar: bytes = b''  # the boss-room pillar object entry ('' when the archive has none)
    talk_zone_ids: list = field(default_factory=list)  # per spot, one per companion (spot-major)
    pair_zone_ids: list = field(default_factory=list)  # per pair spot, one per companion pair (spot-major)
    proctor_boss_id: int = 0  # the dead proctor Aldric recognises: the boss of the first area of depth 3 (0: none)
    sir_demon_id: int = 0  # the Archives' demon that roams the backrooms (0: none)
    reveal: list = field(default_factory=list)  # [(companion record id, [power ids])] granted at that companion's trust reveal
    bypass_gate_id: int = 0  # the companion bypass portcullis and its lever (0: no bypass)
    bypass_lever_id: int = 0
    puzzle_gate_id: int = 0  # the boss-lock puzzles' portcullis, its plate and four levers (0: none)
    puzzle_plate_id: int = 0
    puzzle_lever_ids: list = field(default_factory=list)
    wall_zone_id: int = 0  # the backrooms trigger in the perfect copy's corner (0: none)
    companion_roles: list = field(default_factory=list)  # each companion's main role id (the dialogue's ActivateTopicN needs it)
    salve_id: int = 0  # the Healing Salve item record (imported from exanima03; 0: none)
    prop_names: list = field(default_factory=list)  # the names behind `props`, in order
    prop_stages: dict = field(default_factory=dict)  # prop name -> stages (1-based) whose vanilla levels place it
    dress: dict = field(default_factory=dict)  # stage -> per class, dressings (load_dress)
    spot_order: dict = field(default_factory=dict)  # talk spot -> companion indices in speaking order (one voice per occasion)


def load_template(data: bytes, ini: str) -> Template:
    if struct.unpack_from('<I', data, 0)[0] != MAGIC:
        raise ValueError('not a level')
    top = dict(_chunks(data[4:]))
    keys = {}
    for line in ini.splitlines():
        if '=' in line and not line.startswith('['):
            k, v = line.split('=', 1)
            keys[k.strip()] = v.strip()
    g = top[TAG_GRID]
    n = struct.unpack_from('<I', g, 0)[0]
    p = 4 + 16 * n
    m = struct.unpack_from('<I', g, p)[0]
    p += 4 + 16 * m
    grid_names = g[:p]
    nodes = _chunks(top[TAG_NODES][4:])
    light = _chunk(*next(c for c in nodes if c[0] == 0x3D06))
    objects = _chunks(top[TAG_OBJECTS][4:])
    prop_names = keys['props'].split(';')
    props = [(name, _chunk(t, b)) for name, (t, b) in zip(prop_names, objects)]
    stairs = _chunk(*objects[len(prop_names)])
    plate = _chunk(*objects[len(prop_names) + 1])
    parts = dict(_chunks(top[TAG_ITEMS]))
    places = _chunks(parts[TAG_ITEM_PLACES][4:])
    people = _chunks(top[TAG_PEOPLE][4:])
    ints = lambda k: [int(x) for x in keys[k].split(',') if x]  # noqa: E731 (an empty value is an empty list, as gen.lua reads it)
    stages = []
    for i in range(1, 20):
        v = keys.get(f'stage{i}')
        if not v:
            break
        walls, floors = v.split('|')
        stages.append((walls.split(','), floors.split(',')))
    tp = Template(
        top, grid_names, light, props, stairs, plate, _chunk(*places[0]), _chunk(*places[1]), _chunk(*places[2]), _chunk(*places[3]),
        _chunk(*places[4]), _chunk(*places[5]), _chunk(*places[6]),
        _chunk(TAG_ITEM_DB, parts[TAG_ITEM_DB]), _chunk(TAG_ITEM_STRINGS, parts[TAG_ITEM_STRINGS]),
        _chunk(*next(c for c in people if c[0] == TAG_PEOPLE_DB)),
        int(keys['arrival']), int(keys['zone']), ints('chests'), ints('keys'), ints('doors'), ints('key_chests'),
        ints('fires'), ints('levers'), ints('hazards'), ints('fire_zones'), ints('gates'), ints('gate_levers'),
        ints('enemies'), [ints(f'enemies_t{i}') for i in range(2, 7) if f'enemies_t{i}' in keys], [ints(f'bosses_t{i}') for i in range(1, 7) if f'bosses_t{i}' in keys], float(keys['floor_y']),
        _chunk(*places[7]), _chunk(*places[8]), _chunk(*places[9]),
        ints('secret_doors'), ints('switches'), ints('plate_fires'), ints('plate_closets'), ints('closet_gates'),
        ints('maze_gates'), ints('maze_levers'),
    )
    tp.stages = stages
    tp.companion_ids = [int(x) for x in keys['companions'].split(',')] if keys.get('companions') else []
    wall_names = [n for n in keys.get('wall_props', '').split(';') if n]
    debris_names = [n for n in keys.get('debris', '').split(';') if n]
    base = len(prop_names) + 2  # after the props, the stairs and the plate
    tp.wall_props = [(n, _chunk(*objects[base + i])) for i, n in enumerate(wall_names)]
    tp.debris = [(n, _chunk(*objects[base + len(wall_names) + i])) for i, n in enumerate(debris_names)]
    if keys.get('pillar'):
        tp.pillar = _chunk(*objects[base + len(wall_names) + len(debris_names)])
    tp.chest_tiers = [ints(f'chests_t{i}') for i in range(2, 8) if f'chests_t{i}' in keys]
    tp.talk_zone_ids = ints('talk_zones')
    tp.pair_zone_ids = ints('pair_zones')
    tp.proctor_boss_id = int(keys.get('proctor_boss', 0))
    tp.sir_demon_id = int(keys.get('sir_demon', 0))
    tp.reveal = [(int(e.split(':')[0]), [int(x) for x in e.split(':')[1].split(',') if x]) for e in keys.get('reveal_powers', '').split(';') if e]
    tp.bypass_gate_id, tp.bypass_lever_id = int(keys.get('bypass_gate', 0)), int(keys.get('bypass_lever', 0))
    tp.puzzle_gate_id, tp.puzzle_plate_id = int(keys.get('puzzle_gate', 0)), int(keys.get('puzzle_plate', 0))
    tp.puzzle_lever_ids = [int(x) for x in keys.get('puzzle_levers', '').split(',') if x]
    tp.wall_zone_id = int(keys.get('wall_zone', 0))
    tp.companion_roles = ints('companion_roles') if keys.get('companion_roles') else []
    tp.salve_id = int(keys.get('salve', 0))
    tp.prop_names = list(prop_names)
    tp.prop_stages = {e.split(':')[0]: {int(x) for x in e.split(':')[1].split(',') if x} for e in keys.get('prop_stages', '').split(';') if e}
    tp.spot_order = {e.split(':')[0]: [int(x) for x in e.split(':')[1].split(',') if x] for e in keys.get('spot_order', '').split(';') if e}
    tp.boss_bands = [[ints(f'bosses_t{i}_b{k}') for k in range(1, BANDS + 1)] for i in range(1, 7) if f'bosses_t{i}_b1' in keys]
    tp.enemy_bands = [[ints(f'enemies_t{i}_b{k}') for k in range(1, BANDS + 1)] for i in range(1, 7) if f'enemies_t{i}_b1' in keys]
    return tp


TERRAIN_MAGIC = 0x3EEFAD01
TERRAIN_TAG = 0xBDAD
TN = 244  # stored samples per row/column of a tile
TSAMPLE = 20.0
TTILE = 4800.0


def load_terrain_template(tp: Template, data: bytes) -> None:
    """A 1 x 1 flat terrain (out/endless-template.rft): keeps its header and one tile's
    layers; the generator writes 2 x 2 tiles with its own heights."""
    if struct.unpack_from('<I', data, 0)[0] != TERRAIN_MAGIC:
        raise ValueError('not a terrain')
    t, size = struct.unpack_from('<II', data, 40)
    if t != TERRAIN_TAG:
        raise ValueError('terrain tile missing')
    tp.terrain_head = data[:28]  # magic/zero, palette, sample
    tp.terrain_tile = data[48 : 48 + size]


def world(c: int, r: int, w: int, h: int, fx: float = 0.5, fz: float = 0.5) -> tuple[float, float]:
    """World x, z of a point inside cell (c, r): fx/fz in 0..1 across the cell."""
    return (c - w / 2 + fx) * CELL, (r - h / 2 + fz) * CELL


def yaw_matrix(degrees: float) -> list[float]:
    a = math.radians(degrees)
    cs, sn = math.cos(a), math.sin(a)
    return [cs, 0.0, sn, 0.0, 1.0, 0.0, -sn, 0.0, cs]


def _light(tp: Template, pos, colour, strength: float, falloff: float, rng_range: float) -> bytes:
    b = bytearray(tp.light)
    struct.pack_into('<3f', b, 8 + 68, *pos)
    struct.pack_into('<3f', b, 8 + 116, *colour)
    struct.pack_into('<4f', b, 8 + 128, 1.0, strength, falloff, rng_range)
    return bytes(b)


def _flat(raw: bytes, pos) -> bytes:
    """An object laid flat: its model z axis turned up (a quarter turn about x)."""
    b = bytearray(raw)
    struct.pack_into('<9f', b, 8 + 20, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)
    struct.pack_into('<3f', b, 8 + 56, *pos)
    return bytes(b)


def _object(raw: bytes, pos, yaw: float) -> bytes:
    b = bytearray(raw)
    struct.pack_into('<9f', b, 8 + 20, *yaw_matrix(yaw))
    struct.pack_into('<3f', b, 8 + 56, *pos)
    return bytes(b)


def _placement(raw: bytes, item: int, pos, yaw: float, state: int = 0) -> bytes:
    b = bytearray(raw)
    struct.pack_into('<II', b, 8, item, state)
    struct.pack_into('<9f', b, 8 + 12, *yaw_matrix(yaw))
    struct.pack_into('<3f', b, 8 + 48, *pos)
    return bytes(b)


def _spawn(who: int, pos, yaw_radians: float) -> bytes:
    return _chunk(TAG_SPAWN, struct.pack('<I3ffII', who, pos[0], pos[1], pos[2], yaw_radians, 0, 0))


def _patch_script(item_db: bytes, area: int, seed: int, event: bytes = b'EndlessNext') -> bytes:
    i = item_db.find(SCRIPT_PREFIX)
    if i < 0:
        raise ValueError('template has no EndlessNext script')
    assert len(event) == 11  # the script keeps its width
    text = b'LuaEvent(%s,%010u_%010u);' % (event, area, seed & 0xFFFFFFFF)
    end = item_db.index(b';', i) + 1
    if end - i != len(text):
        raise ValueError('script width changed')
    return item_db[:i] + text + item_db[end:]


# the boss lock (Hunter, 2026-10-22: "weight plate, lever order, time gate (with failsafe), hold the door"):
# depth 1 a key; depth 2 a key, a weight plate or a held door in turn; deeper, all six in turn
PUZZLES = ('key', 'lever', 'plate', 'order', 'timed', 'hold')
PLATE_DIST, HOLD_DIST, TIMED_DIST = (3, 5), (1, 2), (4, 7)  # cells from the boss doorway (corridor steps)
TIMED_BASE, TIMED_PER_CELL = 5.0, 1.6  # seconds the timed gate stays up: base plus per cell of the way back
HEAVY = ('barrel wdo1 a02', 'cratel4', 'barrel wdo1 a01', 'cratesmall a')  # weight for the plate, if the stone has them
CLUE = ('bottle_wkr b', 'pot')  # the lever order's clue: 1, 2, 3 of these at each lever's foot


def puzzle_kind(area: int) -> str:
    depth = depth_of(area)
    if depth <= 1:
        return 'key'
    if depth == 2:
        return ('key', 'plate', 'hold')[(area - 1) % AREAS_PER_DEPTH]
    return PUZZLES[(area * 5 + depth) % len(PUZZLES)]


def is_lever_area(area: int) -> bool:
    """An area whose boss door opens by a hidden lever instead of a key (puzzle_kind)."""
    return puzzle_kind(area) == 'lever'


def fire_trap_count(area: int) -> int:
    return min(max(depth_of(area) - 1, 0), 5)


def push_trap_count(area: int) -> int:
    return min(max(depth_of(area) - 2, 0), 4)


def build_terrain(tp: Template, lay: Layout, w: int, h: int) -> bytes:
    """2 x 2 tiles (world -4800..4800 on both axes) of flat ground at floor level, exactly as
    level 1's own terrain lies under its floors. Served so the arena's real terrain never loads."""
    if not tp.terrain_tile:
        raise ValueError('terrain template not loaded')
    nx = ny = 2
    tiles = []
    for iy in range(ny):
        for ix in range(nx):
            cx, cz = (ix - (nx - 1) / 2) * TTILE, (iy - (ny - 1) / 2) * TTILE
            heights = [0.0] * (TN * TN)
            for j in range(TN):
                wz = cz + (j - 121) * TSAMPLE
                rr = int(math.floor(wz / CELL)) + h // 2
                for i in range(TN):
                    wx = cx + (i - 121) * TSAMPLE
                    cc = int(math.floor(wx / CELL)) + w // 2
            body = struct.pack('<IiiI', struct.unpack_from('<I', tp.terrain_tile, 0)[0], ix, iy, struct.unpack_from('<I', tp.terrain_tile, 12)[0])
            body += struct.pack(f'<{TN * TN}f', *heights) + tp.terrain_tile[16 + 4 * TN * TN :]
            tiles.append(struct.pack('<II', TERRAIN_TAG, len(body)) + body)
    return tp.terrain_head + struct.pack('<iiI', nx, ny, len(tiles)) + b''.join(tiles)


def enemy_count(area: int) -> int:
    """+3 per depth and +2 per area inside a depth, capped at ENEMY_CAP (reached at depth 11):
    past that the strength bands carry the curve, not the count."""
    depth = depth_of(area)
    return min(4 + 3 * depth + 2 * ((area - 1) % AREAS_PER_DEPTH), ENEMY_CAP)


def boss_minion_count(area: int) -> int:
    """The boss room fills steadily too: one minion per depth from depth 2, up to MINION_CAP."""
    return min(max(depth_of(area) - 1, 0), MINION_CAP)


def boss_count(area: int) -> int:
    """A second boss from depth 6, a third from depth 12; no more than BOSS_CAP."""
    return min(1 + depth_of(area) // 6, BOSS_CAP)


BANDS = 3  # strength bands beyond the shipped records (make_template.py writes them)


def band_of(depth: int) -> int:
    """Strength band of a depth: band k from depth 6k+1, up to BANDS."""
    return min((depth - 1) // 6, BANDS)


def enemy_roster(tp: Template, depth: int) -> list:
    """Which records can spawn at a depth: tier k (k = 1 level 1 zombies, 2 level 2, 3 level 3,
    4 ghouls/gobblers/ember knights, 5 fael/living armour/manipulators, 6 golems and the deep
    skeletons) joins at depth k. The newest two tiers are drawn three and two times, older ones
    once; beyond tier 6 everything stays in with the top tiers favoured. From depth 7 every tier
    comes in its strength band of the depth, so the depth keeps biting after the last tier joined."""
    tiers = [tp.enemy_ids] + tp.enemy_tiers
    top = min(depth, len(tiers))
    band = band_of(depth)
    out = []
    for k in range(top):
        weight = 3 if k == top - 1 else 2 if k == top - 2 else 1
        ids = tiers[k]
        if band and k < len(tp.enemy_bands) and tp.enemy_bands[k][band - 1]:
            ids = tp.enemy_bands[k][band - 1]
        out += list(ids) * weight
    return out


def boss_roster(tp: Template, depth: int) -> list:
    """The boss tier of the depth, in the strength band of the depth (band k from depth 6k+1)."""
    tiers = [t for t in tp.boss_tiers if t]
    if not tiers:
        return []
    k = min(depth, len(tiers)) - 1
    band = band_of(depth)
    if band and k < len(tp.boss_bands) and tp.boss_bands[k][band - 1]:
        return list(tp.boss_bands[k][band - 1])
    return list(tiers[k]) if tiers[k] else list(tiers[0])


def chest_roster(tp: Template, depth: int) -> list:
    """Chest records by depth: level 1's at depth 1, deeper levels' chests join one tier per
    depth with the newest two tiers weighted, like the enemies."""
    tiers = [tp.chest_ids] + tp.chest_tiers
    top = min(depth, len(tiers))
    out = []
    for k in range(top):
        if not tiers[k]:
            continue
        weight = 3 if k == top - 1 else 2 if k == top - 2 else 1
        out += tiers[k] * weight
    return out or list(tp.chest_ids)


def stage_of(tp: Template, area: int):
    """The tile sets of an area: the first stage for depths 1-2, then one stage per depth,
    cycling through the deeper stages again past the last."""
    if not tp.stages:
        return None
    depth = depth_of(area)
    i = 0 if depth <= 2 else depth - 2
    if i >= len(tp.stages):
        i = 1 + (i - 1) % (len(tp.stages) - 1) if len(tp.stages) > 1 else 0
    return tp.stages[i]


def _names_block(names: list) -> bytes:
    return struct.pack('<I', len(names)) + b''.join(n.encode('latin-1')[:16].ljust(16, b'\0') for n in names)


def _pillar_cells(boss) -> list:
    """The four inner-corner cells of a boss room (rooms are 4..5 cells a side), so the fight
    has cover instead of an open box; spawns avoid them."""
    if boss is None or boss.c1 - boss.c0 < 3 or boss.r1 - boss.r0 < 3:
        return []
    return [(boss.c0 + 1, boss.r0 + 1), (boss.c1 - 1, boss.r0 + 1), (boss.c0 + 1, boss.r1 - 1), (boss.c1 - 1, boss.r1 - 1)]


def is_vault_area(area: int) -> bool:
    """Two-key areas: from depth 4, on key (not lever) areas, the boss key sits in a locked
    room whose own key lies elsewhere."""
    return depth_of(area) >= 4 and puzzle_kind(area) == 'key'


def talk_zone_ids(tp: Template, spot: str, per_spot: int, present) -> list[int]:
    """The talk-zone records placed at a spot: one, the first companion in the spot's order who is
    present (`present`: companion indices in the party; None = all), else the first in the order;
    without an order (an older template) all of the spot's zones."""
    spot_index = TALK_SPOTS.index(spot)
    order = tp.spot_order.get(spot)
    if not order:
        return [tp.talk_zone_ids[spot_index * per_spot + k] for k in range(per_spot)]
    k = next((i for i in order if present is None or i in present), order[0])
    return [tp.talk_zone_ids[spot_index * per_spot + k]]


def assign_purposes(rng: Rng, lay: Layout, depth: int) -> None:
    """Every ordinary room gets a purpose: one quiet room per area from depth 2, stores,
    barracks, shrines (from depth 3), the rest plain. One rng call per ordinary room."""
    quiet_done = False
    for room in lay.rooms:
        if room.kind != 'room':
            continue
        roll = rng.between(0, 99)
        if depth >= 2 and not quiet_done and roll < 25:
            room.purpose = 'quiet'
            quiet_done = True
        elif roll < 34:
            room.purpose = 'store'
        elif roll < 48:
            room.purpose = 'barracks'
        elif roll < 60:
            room.purpose = 'kitchen'
        elif roll < 68:
            room.purpose = 'latrine'
        elif roll < 77:
            room.purpose = 'workshop'
        elif depth >= 3 and roll < 85:
            room.purpose = 'shrine'
        elif depth >= 2 and roll < 90:
            room.purpose = 'gaol'
        elif depth >= 4 and roll < 94:
            room.purpose = 'surgery'
        else:
            room.purpose = 'plain'


def rot_mask(m: int, k: int) -> int:
    """A wall mask turned k quarter steps (side q becomes side q + k)."""
    return ((m << k) | (m >> (4 - k))) & 15 if k else m


def rot_step(dx: float, dz: float, mtx: list):
    """One quarter step: an offset and the rows of a matrix, (x, y, z) -> (z, y, -x), which takes
    north (0, -1) to west (-1, 0), the side order and SIDE_YAW's direction."""
    return dz, -dx, [v for i in range(3) for v in (mtx[3 * i + 2], mtx[3 * i + 1], -mtx[3 * i])]


def _dress_objs(blob: bytes, p: int):
    (no,) = struct.unpack_from('<I', blob, p); p += 4
    objs = []
    for _ in range(no):
        dx, dy, dz, n = struct.unpack_from('<3fI', blob, p); p += 16
        objs.append((dx, dy, dz, blob[p:p + n])); p += n
    return objs, p


def dress_name(raw: bytes) -> str:
    return raw[12:28].split(b'\0')[0].decode('latin-1')


def load_dress(tp: Template, blob: bytes) -> None:
    """assets/endless-dress.bin (make_template.py, EDR2), per stage: the cell pools by wall class
    [objs], the whole rooms [(tag, [(class, objs)])], rooms by tag {tag: [room index]}, and the
    knocked-over seat poses {model: [(matrix, height)]}; offsets canonical."""
    tp.dress = {}
    tp.shapes = {}
    if not blob or blob[:4] not in (b'EDR4', b'EDR5'):
        return
    with_shapes = blob[:4] == b'EDR5'
    p = 4
    (nst,) = struct.unpack_from('<I', blob, p); p += 4
    for stage in range(1, nst + 1):
        (ncls,) = struct.unpack_from('<I', blob, p); p += 4
        classes = []
        for _ in range(ncls):
            (nd,) = struct.unpack_from('<I', blob, p); p += 4
            lst = []
            for _ in range(nd):
                objs, p = _dress_objs(blob, p)
                lst.append(objs)
            classes.append(lst)
        (nrooms,) = struct.unpack_from('<I', blob, p); p += 4
        rooms, by_tag = [], {}
        for ri in range(nrooms):
            tag, rw, rh, ncells = struct.unpack_from('<IIII', blob, p); p += 16
            cells = []
            for _ in range(ncells):
                cls, ck = struct.unpack_from('<II', blob, p); p += 8
                objs, p = _dress_objs(blob, p)
                (nit,) = struct.unpack_from('<I', blob, p); p += 4
                items = []
                for _ in range(nit):
                    items.append(struct.unpack_from('<I4f', blob, p)); p += 20
                cells.append((cls, objs, items, ck))
            rooms.append((tag, cells, rw, rh))
            by_tag.setdefault(tag, []).append(ri)
        (ntip,) = struct.unpack_from('<I', blob, p); p += 4
        tipped = {}
        for _ in range(ntip):
            name = blob[p:p + 16].split(b'\0')[0].decode('latin-1'); p += 16
            mtx = struct.unpack_from('<9f', blob, p); p += 36
            (dy,) = struct.unpack_from('<f', blob, p); p += 4
            tipped.setdefault(name, []).append((mtx, dy))
        tp.dress[stage] = (classes, rooms, by_tag, tipped)
        shapes = []
        if with_shapes:
            (nsh,) = struct.unpack_from('<I', blob, p); p += 4
            for _ in range(nsh):
                sw, sh, n = blob[p], blob[p + 1], blob[p + 2]; p += 3
                shapes.append((sw, sh, tuple((blob[p + 2 * k], blob[p + 2 * k + 1]) for k in range(n)))); p += 2 * n
        tp.shapes[stage] = shapes


# walkways (2026-10-22, "keep a walkway between doors"): in an ordinary room the cells on the shortest
# ways from its first doorway to each other doorway (to its middle when it has one) stay walkable: a
# dressing object there is left out unless it sits toward the cell's edge, by a wall
WALK_CLEAR = 0.3 * CELL
# furniture groups (2026-10-22, "place groups, not cells"): before the cell-by-cell dressing, a 2x2 patch
# of an ordinary room takes, this percent of the time, a whole 2x2 block of its source room whose cells
# have the same walls in the same turns, so a table, its chairs and what is on it go down together
GROUP_CHANCE = 50
# wall dressing by purpose (2026-10-22): an ordinary room's walled cells the dressing left bare take, this
# percent of the time, one wall-hung piece (above HUNG_Y) from a cell of the same wall class in the
# stone's rooms of the room's own purpose, so a kitchen gets a kitchen's shelves, a gaol its chains;
# the cell's turn puts it on the right wall, facing out
WALL_DRESS_CHANCE, HUNG_Y = 45, 80.0
# a wall-hung piece (above HUNG_Y) within HUNG_NEAR of a doorway side of its cell, with no wall side as
# near, is left out (a copied room's wall where this room has a doorway); pieces in the open (on a post,
# a stack, a shelf top) stay, as the shipped levels have them
HUNG_NEAR = 0.3 * CELL
# floor decals by use (2026-10-22): the stone's own floor decals (models named decal*), each with its own
# flat pose turned at random: on a walkway cell this percent of the time (worn floor between doors), and
# DECAL_FIGHT more in a room whose event was a fight, DECAL_KITCHEN in a kitchen
WALK_DECAL_CHANCE, DECAL_FIGHT, DECAL_KITCHEN = 35, 2, 1
# corridor clutter (2026-10-22): at a bend or a junction, this percent of the time one or two pieces of the
# stone's own debris; in a corridor cell with a doorway side, this percent of the time a wall-hung piece
# for that cell's walls (any purpose)
CORRIDOR_CLUTTER, DOORWAY_DRESS = 50, 50
# stories across rooms (2026-10-22): a room behind a barricade is a fight (the barricade was held); a fight
# leaves a trail of floor marks TRAIL_LEN cells down the corridor from its first doorway (each mark this
# percent of the time); a store beside a kitchen is dressed in every cell (stacked high)
TRAIL_LEN, TRAIL_CHANCE = 4, 75
# one showpiece per area (2026-10-22): an ordinary room of a purpose in SHOW_TAGS (shrine, surgery,
# workshop, kitchen: the first that has a match) whose size equals a whole vanilla room of that purpose on
# this stone is dressed as that room exactly, cell for cell, as the perfect copy is (without its chair)
SHOW_TAGS = (6, 8, 5, 3, 2, 1, 7, 4)  # then barracks, store, gaol, latrine when none of those has a match
# the boss pen (Hunter, 2026-10-22: "a portcullis trap + lever to some boss rooms in order to lure them to,
# and throw them into, the pit"): this percent of boss rooms get a 2x2 pen off one side, its portcullis
# raised (the mod opens it on arrival) and its lever on the boss room's wall beside the doorway; drop it
# with the boss inside and the boss counts as beaten (the mod opens the exit gate)
PEN_CHANCE = 40
# one event per room (2026-10-22, "give each room one event"): out of 100, below FIGHT a fight (every seat
# that can fall is knocked over, the stone's own debris scattered), below LOOTED looted (half the
# dressing, no groups, one seat over), below HURRY left in a hurry (seats shoved far round, one over),
# else left tidy (seats near square, none over). Remains stay the easter eggs' own.
EVENT_FIGHT, EVENT_LOOTED, EVENT_HURRY = 15, 30, 50
TIDY_JITTER, HURRY_JITTER = 8.0, 60.0
FIGHT_DEBRIS = 3


def walkway(lay: Layout, room: Room) -> set:
    cells = set(room.cells)
    doors = []
    for a, b in lay.doors:
        for x in (a, b):
            if x in cells and x not in doors:
                doors.append(x)
    if not doors:
        return set()
    targets = doors[1:] if len(doors) > 1 else [room.centre if room.centre in cells else doors[0]]
    parent = {doors[0]: None}
    queue = [doors[0]]
    i = 0
    while i < len(queue):
        c, r = queue[i]
        i += 1
        for dx, dz in SIDE:
            n = (c + dx, r + dz)
            if n in cells and n not in parent:
                parent[n] = (c, r)
                queue.append(n)
    out = set()
    for x in targets:
        if x not in parent:
            continue
        while x is not None:
            out.add(x)
            x = parent[x]
    return out


def turn_rows(mtx: list, degrees: float) -> list:
    """A matrix turned about the world's vertical axis (rows times the yaw matrix, as
    level.Placed.turn_by), keeping any tilt."""
    a = math.radians(degrees)
    c, s_ = math.cos(a), math.sin(a)
    return [v for i in range(3) for v in (mtx[3 * i] * c - mtx[3 * i + 2] * s_, mtx[3 * i + 1], mtx[3 * i] * s_ + mtx[3 * i + 2] * c)]


def themed(tp: Template, name: str, stage: int) -> bool:
    """Whether vanilla places this prop on a level that wears this stage's stone (no table or no
    stage: yes; a prop no listed level places: nowhere)."""
    if stage == 0 or name not in tp.prop_stages:
        return True
    return stage in tp.prop_stages[name]


def choose_sources(rng: Rng, lay: Layout, dress) -> None:
    """Each ordinary room's source room for its purpose (any of the stage's when the stone has none
    for it); the purpose then follows what the source holds (the quiet room keeps its own)."""
    if not dress:
        return
    _classes, d_rooms, d_by_tag, _tipped = dress
    if not d_rooms:
        return
    for room in lay.rooms:
        if room.kind != 'room':
            continue
        tag = PURPOSE_TAG.get(room.purpose)
        pool = d_by_tag.get(tag, []) if tag is not None else []
        if not pool:
            pool = list(range(len(d_rooms)))
        # by scale: a small room takes a small source room, a big one a big one, where the stone has them
        size = len(room.cells)
        near = [ri for ri in pool if len(d_rooms[ri][1]) * SIZE_FACTOR >= size and len(d_rooms[ri][1]) <= size * SIZE_FACTOR]
        if not near:
            best = min(abs(len(d_rooms[ri][1]) - size) for ri in pool)
            near = [ri for ri in pool if abs(len(d_rooms[ri][1]) - size) == best]
        room.src = rng.pick(near)
        if room.purpose != 'quiet' and d_rooms[room.src][0] in TAG_PURPOSE:
            room.purpose = TAG_PURPOSE[d_rooms[room.src][0]]


def pick_showpiece(rng: Rng, lay: Layout, dress) -> None:
    if not dress:
        return
    d_rooms = dress[1]
    for tag in SHOW_TAGS:
        purpose = TAG_PURPOSE.get(tag)
        pairs = []
        for i, room in enumerate(lay.rooms):
            if room.kind != 'room' or room.copy or room.cut or room.purpose != purpose:
                continue
            rw, rh = room.c1 - room.c0 + 1, room.r1 - room.r0 + 1
            for ri, dr in enumerate(d_rooms):
                if dr[0] == tag and dr[2] == rw and dr[3] == rh and len(dr[1]) == rw * rh:
                    pairs.append((i, ri))
        if pairs:
            i, ri = rng.pick(pairs)
            lay.rooms[i].src, lay.rooms[i].show = ri, True
            return


def pick_copy(rng: Rng, lay: Layout, dress, stage_no: int) -> None:
    """Easter egg 4: now and then, on the catacombs' stone, one ordinary room of a source room's exact
    size (same orientation, every cell kept) becomes that room exactly."""
    if not dress or stage_no != 1 or not rng.chance(COPY_CHANCE):
        return
    d_rooms = dress[1]
    pairs = []
    for i, room in enumerate(lay.rooms):
        if room.kind != 'room' or room.purpose == 'quiet' or room.cut:
            continue
        rw, rh = room.c1 - room.c0 + 1, room.r1 - room.r0 + 1
        for ri, dr in enumerate(d_rooms):
            if dr[2] == rw and dr[3] == rh and len(dr[1]) == rw * rh:
                pairs.append((i, ri))
    if not pairs:
        return
    i, ri = rng.pick(pairs)
    room = lay.rooms[i]
    room.src, room.copy = ri, True
    if d_rooms[ri][0] in TAG_PURPOSE:
        room.purpose = TAG_PURPOSE[d_rooms[ri][0]]


def arrange_neighbours(lay: Layout) -> None:
    """Swaps purposes (with their source rooms) between ordinary rooms until the neighbour and
    size rules hold where they can: for each room breaking a rule, in order, the first swap with
    another room (not the quiet room) that lowers the broken rules around both. No randomness."""
    rooms = [room for room in lay.rooms if room.kind == 'room']
    n = len(rooms)
    if n < 2:
        return
    nb = [[] for _ in range(n)]
    for i in range(n):
        a = rooms[i]
        for j in range(i + 1, n):
            b = rooms[j]
            gap = max(b.c0 - a.c1 - 1, a.c0 - b.c1 - 1, b.r0 - a.r1 - 1, a.r0 - b.r1 - 1)
            if gap <= NEIGHBOUR_GAP:
                nb[i].append(j)
                nb[j].append(i)
    sizes = [len(room.cells) for room in rooms]

    def broken(i):
        p = rooms[i].purpose
        bad = 0
        near = [rooms[j].purpose for j in nb[i]]
        if p == 'kitchen' and any(room.purpose == 'store' for room in rooms) and not any(q in ('store', 'kitchen') for q in near):
            bad += 1
        if p in ('gaol', 'latrine') and 'kitchen' in near:
            bad += 1
        if p == 'kitchen' and any(q in ('gaol', 'latrine') for q in near):
            bad += 1
        if p == 'shrine' and any(q in SHRINE_APART for q in near):
            bad += 1
        if p in SHRINE_APART and 'shrine' in near:
            bad += 1
        if p in SMALL_PURPOSES and sizes[i] > SMALL_MAX:
            bad += 1
        if p in BIG_PURPOSES and sizes[i] < BIG_MIN:
            bad += 1
        return bad

    def around(i, j):
        return sorted({i, j} | set(nb[i]) | set(nb[j]))

    def swap(i, j):
        a, b = rooms[i], rooms[j]
        a.purpose, b.purpose = b.purpose, a.purpose
        a.src, b.src = b.src, a.src

    for _ in range(NEIGHBOUR_PASSES):
        changed = False
        for i in range(n):
            if rooms[i].purpose == 'quiet' or broken(i) == 0:
                continue
            for j in range(n):
                if j == i or rooms[j].purpose == 'quiet' or rooms[j].purpose == rooms[i].purpose:
                    continue
                zone = around(i, j)
                before = sum(broken(k) for k in zone)
                swap(i, j)
                if sum(broken(k) for k in zone) < before:
                    changed = True
                    break
                swap(i, j)
        if not changed:
            break


def props_for(tp: Template, purpose: str, stage: int) -> list:
    """The (name, chunk) props a room of this purpose may hold on this stage, in template order
    (empty when vanilla pairs none of them with the stone)."""
    wanted = PURPOSE_PROPS.get(purpose, PROP_NAMES)
    return [pr for pr in tp.props if pr[0] in wanted and themed(tp, pr[0], stage)]


def rare_chests(tp: Template) -> list:
    """The deepest chest tier the template carries: the rare finds of shrine rooms."""
    for tier in reversed(tp.chest_tiers):
        if tier:
            return tier
    return list(tp.chest_ids)


def companion_for(tp: Template, area: int, met) -> int:
    """The companion record found on this area, or 0: the second area of each depth holds the
    depth's companion in the found order; one already met (`met`: companion indices, None =
    nobody) is skipped for the first not yet met, and after all three nothing is found."""
    if not tp.companion_ids or (area - 1) % AREAS_PER_DEPTH != 1:
        return 0
    which = (depth_of(area) - 1) % len(tp.companion_ids)
    if met is not None and which in met:
        which = next((i for i in range(len(tp.companion_ids)) if i not in met), -1)
    if which < 0:
        return 0
    if met is None and depth_of(area) > len(tp.companion_ids):
        return 0
    return tp.companion_ids[which]


def stage_index(tp: Template, area: int) -> int:
    """The 1-based tile-set stage of an area (0 without stages), as gen.lua's stage_index."""
    if not tp.stages:
        return 0
    depth = depth_of(area)
    i = 0 if depth <= 2 else depth - 2
    if i >= len(tp.stages):
        i = 1 + (i - 1) % (len(tp.stages) - 1) if len(tp.stages) > 1 else 0
    return i + 1


def pick_archetype(rng: Rng, depth: int) -> str:
    return 'warren' if depth < 2 else ARCH_ORDER[rng.below(len(ARCH_ORDER))]


def pick_mutator(rng: Rng, depth: int) -> str:
    if depth < 3 or not rng.chance(30):
        return 'none'
    return MUTATORS[rng.below(len(MUTATORS))]


def _proto(d_rooms, name: str):
    """The first upright vanilla object of this model in the stage's rooms: (dy, raw), or None."""
    for _tag, cells, _rw, _rh in d_rooms:
        for _cl, objs, _it, _k in cells:
            for _dx, dy, _dz, raw in objs:
                if dress_name(raw) == name and abs(struct.unpack_from('<f', raw, 8 + 20 + 16)[0]) >= 0.7:
                    return dy, raw
    return None


def _put(raw: bytes, pos, mtx) -> bytes:
    b = bytearray(raw)
    struct.pack_into('<9f', b, 8 + 20, *mtx)
    struct.pack_into('<3f', b, 8 + 56, *pos)
    return bytes(b)


def backrooms_lair(lay: Layout):
    """Where Sir waits in the backrooms: the ordinary room whose distance from the start is nearest half
    the farthest one's (first on ties), so it is met on the way, not at the door; never the key's room."""
    sc, sr = lay.rooms[0].centre
    rooms = [room for room in lay.rooms if room.kind == 'room' and not room.contains(*lay.key_cell)]
    if not rooms:
        return None
    far = max(abs(room.centre[0] - sc) + abs(room.centre[1] - sr) for room in rooms)
    best = None
    for room in rooms:
        d = abs(abs(room.centre[0] - sc) + abs(room.centre[1] - sr) - far / 2)
        if best is None or d < best[0]:
            best = (d, room)
    return best[1]


def backrooms_props(tp: Template, lay: Layout, w: int, h: int, seed: int, area: int, stage_no: int, lair=None) -> list[bytes]:
    """The backrooms' furniture (see BACK_ROWS): its own rng, so the plan, lights and key stay as they
    were; never in a cell with a doorway or the key's cell, so the way through stays open."""
    dress = tp.dress.get(stage_no) if tp.dress else None
    if not dress:
        return []
    proto = {}
    for name in BACK_PROPS:
        got = _proto(dress[1], name)
        if got is not None:
            proto[name] = got
    rng = Rng(seed ^ 0xBAC5, area)
    out = []
    fy = tp.floor_y

    def quiet(c, r):
        return (c, r) != tuple(lay.key_cell) and all(side_kind(lay, c, r, q) != DOOR for q in range(4))

    def add(name, c, r, fx, fz, mtx, lift=0.0):
        if name in proto:
            x, z = world(c, r, w, h, fx, fz)
            dy, raw = proto[name]
            out.append(_put(raw, (x, fy + dy + lift, z), mtx))

    rooms = [room for room in lay.rooms if room.kind == 'room']
    biggest = None
    for room in rooms:
        if biggest is None or len(room.cells) > len(biggest.cells):
            biggest = room
    for room in rooms:
        cc, cr = room.centre
        if room is lair:  # Sir's room stays bare
            continue
        if room is biggest:
            # a table set for one: the table in the middle, one chair drawn up to its south end
            if quiet(cc, cr):
                add('table_m_re a', cc, cr, 0.5, 0.5, yaw_matrix(0.0))
                add('chair a', cc, cr, 0.5, 0.5 + 125.0 / CELL, yaw_matrix(180.0))
            continue
        roll = rng.below(100)
        north = rng.below(2) == 0
        q = 0 if north else 2
        row = room.r0 if north else room.r1
        if roll < BACK_ROWS:
            # two rows of chairs along the wall, every one facing it, every one alike
            for c in range(room.c0, room.c1 + 1):
                if room.contains(c, row) and quiet(c, row) and side_kind(lay, c, row, q) == WALL:
                    for fz in ((0.22, 0.48) if north else (0.78, 0.52)):
                        for fx in (0.25, 0.5, 0.75):
                            add('chair a', c, row, fx, fz, yaw_matrix(180.0 if north else 0.0))
        elif roll < BACK_BEDS:
            # beds stood on end against the wall, one to a cell
            for c in range(room.c0, room.c1 + 1):
                if room.contains(c, row) and quiet(c, row) and side_kind(lay, c, row, q) == WALL:
                    add('bed b01', c, row, 0.5, 0.2 if north else 0.8, BED_ON_END, BED_HALF)
        elif roll < BACK_CENTRE:
            # one thing, square to the walls, at the room's exact middle
            name = rng.pick(BACK_CENTRE_PROPS)
            add(name, room.c0, room.r0, (room.c1 - room.c0 + 1) / 2, (room.r1 - room.r0 + 1) / 2, yaw_matrix(0.0))
        elif roll < BACK_TWIN:
            # the same chair and bucket in the same spot of every room that has them
            c, r = room.c0 + 1, room.r0 + 1
            if room.contains(c, r) and quiet(c, r):
                add('chair a', c, r, 0.3, 0.3, yaw_matrix(0.0))
                add('bucket wod a01', c, r, 0.7, 0.3, yaw_matrix(0.0))
    return out


def build_backrooms(tp: Template, seed: int, area: int) -> tuple[bytes, Layout]:
    """The backrooms for (seed, area): a vast plain level of the area's own stone, the backrooms plan,
    every lamp alike and dull, no props, no one in it; the key to the way back in the room farthest
    from it, and the exit zone's script raising EndlessBack (the mod returns you to the copy)."""
    w = h = BACK_GRID
    rng = Rng(seed ^ 0xBAC4, area)
    stage = stage_of(tp, area)
    start_cell = (int(START_X // CELL) + w // 2, int(START_Z // CELL) + h // 2)
    lay = generate_layout(rng, w, h, 1, start_cell, 'backrooms', False, True)
    for room in lay.rooms:
        room.style = 0
    layers = encode_grid(lay)
    names = _names_block(stage[0]) + _names_block(stage[1]) if stage else tp.grid_names
    grid = names + struct.pack('<IIII', w, h, 0, 600) + b''.join(struct.pack(f'<{w * h}I', *L) for L in layers)
    nodes = []
    for room in lay.rooms:
        if room.kind == 'maze':
            continue
        x, z = world(*room.centre, w, h)
        span = max(room.c1 - room.c0, room.r1 - room.r0)
        nodes.append(_light(tp, (x, LIGHT_Y, z), BACK_LIGHT, BACK_STRENGTH, 2.0, float(600 + 150 * span)))
    for k, (c, r) in enumerate(lay.corridor_cells):
        if k % 6 == 1:
            x, z = world(c, r, w, h)
            nodes.append(_light(tp, (x, LIGHT_Y, z), BACK_LIGHT, BACK_STRENGTH, 2.0, 600.0))
    node_chunk = struct.pack('<I', len(nodes)) + b''.join(nodes)
    exit_room = lay.exit_room
    gx, gz = world(*exit_room.centre, w, h)
    start = lay.rooms[0]
    sx, sz = world(*start.centre, w, h)
    places = [
        _placement(tp.marker_place, 0x80000000 | tp.arrival_id, (sx, 100.0, sz), 0.0),
        _placement(tp.marker_place, 0x80000000 | tp.zone_id, (gx, 100.0, gz), 0.0),
    ]
    pair = (area - 1) % len(tp.key_ids)
    inside, outside = lay.exit_door
    q = SIDE.index((outside[0] - inside[0], outside[1] - inside[1]))
    dx, dz = world(*inside, w, h)
    places.append(_placement(tp.door_place, 0x80000000 | tp.door_ids[pair], (dx, tp.floor_y, dz), SIDE_YAW[q], 1))
    rooms = [room for room in lay.rooms if room.kind == 'room'] or [start]
    key_room = max(rooms, key=lambda room: abs(room.centre[0] - inside[0]) + abs(room.centre[1] - inside[1]))
    kc, kr = rng.pick(key_room.cells)
    kx, kz = world(kc, kr, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
    places.append(_placement(tp.key_place, 0x80000000 | tp.key_ids[pair], (kx, tp.floor_y, kz), rng.unit() * 360.0))
    lay.key_cell = (kc, kr)
    item_chunk = _patch_script(tp.item_db, area, seed, b'EndlessBack') + tp.item_strings + _chunk(TAG_ITEM_PLACES, struct.pack('<I', len(places)) + b''.join(places))
    lair = backrooms_lair(lay) if tp.sir_demon_id else None
    objects = backrooms_props(tp, lay, w, h, seed, area, stage_index(tp, area), lair)
    object_chunk = struct.pack('<I', len(objects)) + b''.join(objects)
    spawns = []
    if lair is not None:  # Sir, facing the way you come in
        x, z = world(*lair.centre, w, h)
        spawns.append(_spawn(0x80000000 | tp.sir_demon_id, (x, tp.floor_y, z), 0.0))
    people_chunk = struct.pack('<I', 1 + len(spawns)) + tp.people_db + b''.join(spawns)
    env = bytearray(tp.chunks[TAG_ENV])
    struct.pack_into('<3f', env, 0x30, *(float(v) * 0.5 for v in struct.unpack_from('<3f', env, 0x30)))
    lay.info = {'backrooms': 1, 'boss': 0, 'gate': 0, 'props': len(objects), 'sir': tp.sir_demon_id if lair is not None else 0}
    payloads = {TAG_GRID: grid, TAG_NODES: node_chunk, TAG_OBJECTS: object_chunk, TAG_ITEMS: item_chunk, TAG_PEOPLE: people_chunk, TAG_ENV: bytes(env)}
    out = struct.pack('<I', MAGIC)
    for tag in (TAG_GRID, TAG_NODES, TAG_OBJECTS, TAG_ITEMS, TAG_PEOPLE, TAG_ENV):
        out += _chunk(tag, payloads[tag])
    lay.terrain = build_terrain(tp, lay, w, h) if tp.terrain_tile else b''
    return out, lay


def grid_size(area: int) -> int:
    return GRID_BY_DEPTH.get(depth_of(area), GRID_MAX)


def build_floor(tp: Template, seed: int, area: int, *, w: int = 0, h: int = 0, present=None, met=None, shrine_done: bool = False) -> tuple[bytes, Layout]:
    if not w:
        w = h = grid_size(area)
    rng = Rng(seed, area)
    stage = stage_of(tp, area)
    two_sets = bool(stage) and len(stage[0]) >= 2 and len(stage[1]) >= 2
    start_cell = (int(START_X // CELL) + w // 2, int(START_Z // CELL) + h // 2)
    arch_name = pick_archetype(rng, depth_of(area))
    mutator = pick_mutator(rng, depth_of(area))
    stage_no = stage_index(tp, area)
    blockers = [pr for pr in tp.props if pr[0] in BLOCKERS and themed(tp, pr[0], stage_no)]
    block_fill = [pr for pr in tp.props if pr[0] in BLOCK_FILL and themed(tp, pr[0], stage_no)]
    lay = generate_layout(rng, w, h, area, start_cell, arch_name, bool(blockers), False, tp.shapes.get(stage_no) if getattr(tp, 'shapes', None) else None)
    assign_purposes(rng, lay, depth_of(area))
    arrange_neighbours(lay)  # purposes to rooms by size and neighbours
    choose_sources(rng, lay, tp.dress.get(stage_no) if tp.dress else None)
    arrange_neighbours(lay)  # again, where a stone's rooms moved a purpose
    pick_copy(rng, lay, tp.dress.get(stage_no) if tp.dress else None, stage_no)
    pick_showpiece(rng, lay, tp.dress.get(stage_no) if tp.dress else None)
    lay.archetype, lay.mutator = arch_name, mutator
    pillars_ok = bool(tp.pillar) and themed(tp, PILLAR_NAME, stage_no)
    # pillared halls: an uncut ordinary room at least 4 cells a side, half the time
    for room in lay.rooms:
        if room.kind == 'room' and not room.cut and room.purpose != 'quiet' and room.c1 - room.c0 >= 3 and room.r1 - room.r0 >= 3 and pillars_ok:
            room.pillars = rng.chance(50)
    if not two_sets:
        for room in lay.rooms:
            room.style = 0  # the pillared variant needs a second wall and floor set
    layers = encode_grid(lay)
    names = _names_block(stage[0]) + _names_block(stage[1]) if stage else tp.grid_names
    grid = names + struct.pack('<IIII', w, h, 0, 600) + b''.join(struct.pack(f'<{w * h}I', *L) for L in layers)
    exit_room = lay.exit_room
    staircase = is_staircase(area)
    pair = (area - 1) % len(tp.key_ids)
    # lights: rooms (the exit red, a staircase blue-white, the stone's own colour elsewhere), every
    # fourth corridor cell (eighth in the dark), maze nodes
    room_colour = STAGE_LIGHT.get(stage_index(tp, area), (0.55, 0.38, 0.2))
    hall_colour = tuple(v * 0.65 for v in room_colour)
    dark = mutator == 'dark'
    room_strength = 0.45 if dark else 1.0
    every = 12 if dark else 6
    nodes = []
    room_lamp = {}  # ordinary room index -> its lamp's index in nodes (moved toward its furniture after the dressing)
    for i, room in enumerate(lay.rooms):
        if room.kind == 'maze':
            continue
        x, z = world(*room.centre, w, h)
        colour = ((0.3, 0.4, 0.6) if staircase else (0.5, 0.05, 0.05)) if room.kind == 'exit' else (0.45, 0.15, 0.5) if room.kind == 'boss' else QUIET_LIGHT if room.purpose == 'quiet' else room_colour
        strength = 1.0 if room.kind in ('exit', 'boss') else 1.3 if room.purpose == 'quiet' else room_strength  # the exit and the boss room stay lit in the dark
        if room.kind == 'room' and room.purpose != 'quiet':
            strength *= USE_LIGHT.get(room.purpose, 1.0)
            room_lamp[i] = len(nodes)
        span = max(room.c1 - room.c0, room.r1 - room.r0)
        nodes.append(_light(tp, (x, LIGHT_Y, z), colour, strength, 2.0, float(600 + 150 * span)))
    for k, (c, r) in enumerate(lay.corridor_cells):
        if k % every == 1:
            x, z = world(c, r, w, h)
            nodes.append(_light(tp, (x, LIGHT_Y, z), hall_colour, 0.7, 2.0, 600.0))
    for k, (c, r) in enumerate(lay.bypass_cells):
        if k % every == 1:
            x, z = world(c, r, w, h)
            nodes.append(_light(tp, (x, LIGHT_Y, z), hall_colour, 0.7, 2.0, 600.0))
    if exit_room.kind == 'maze':
        k = 0
        for r in range(exit_room.r0, exit_room.r1 + 1, 2):
            for c in range(exit_room.c0, exit_room.c1 + 1, 2):
                if k % 3 == 0:
                    x, z = world(c, r, w, h)
                    colour = ((0.3, 0.4, 0.6) if staircase else (0.5, 0.05, 0.05)) if (c, r) == exit_room.goal else (0.3, 0.2, 0.1)
                    nodes.append(_light(tp, (x, LIGHT_Y, z), colour, 0.8, 2.0, 700.0))
                k += 1
    if depth_of(area) == BLUE_DEPTH:  # easter egg 5: every lamp cold blue, whatever the stone
        blue = []
        for node in nodes:
            b = bytearray(node)
            struct.pack_into('<3f', b, 8 + 116, *BLUE_LIGHT)
            blue.append(bytes(b))
        nodes = blue
    node_chunk = struct.pack('<I', len(nodes)) + b''.join(nodes)
    # dressing: whole cells of the game's own levels for this stone, turned to fit each cell's walls;
    # rooms by purpose where a fitting dressing exists, corridors now and then
    objects = []
    dress_items = []  # loose items of the dressed cells, placed with the other items below
    info_eggs = {}  # the easter eggs this area carries (the mod and, later, the dialogue read them)
    hall_pillar_cells = {cell for room in lay.rooms if room.pillars for cell in _pillar_cells(room)}
    dress = tp.dress.get(stage_no) if tp.dress else None
    if dress:
        d_classes, d_rooms, d_by_tag, d_tipped = dress

        def class_of(c, r):
            m = sum(1 << q for q in range(4) if side_kind(lay, c, r, q) == WALL)
            for ci, cm in enumerate(DRESS_CLASSES):
                for k in range(4):
                    if rot_mask(cm, k) == m:
                        return ci, k
            return None

        def place(objs, c, r, k, clear=None):
            """Places a cell's objects turned k steps; returns (object index, model) of upright seats. On a
            walkway cell (`clear`) an object near the cell's middle is left out."""
            seats = []
            cx, cz = world(c, r, w, h)
            for dx, dy, dz, raw in objs:
                b = bytearray(raw)
                mtx = list(struct.unpack_from('<9f', b, 8 + 20))
                for _ in range(k):
                    dx, dz, mtx = rot_step(dx, dz, mtx)
                if clear and (c, r) in clear and abs(dx) < WALK_CLEAR and abs(dz) < WALK_CLEAR:
                    continue
                if dy > HUNG_Y:
                    near = [q for q, d in enumerate((CELL / 2 + dz, CELL / 2 + dx, CELL / 2 - dz, CELL / 2 - dx)) if d < HUNG_NEAR]
                    kinds = [side_kind(lay, c, r, q) for q in near]
                    if DOOR in kinds and WALL not in kinds:
                        continue
                struct.pack_into('<9f', b, 8 + 20, *mtx)
                struct.pack_into('<3f', b, 8 + 56, cx + dx, tp.floor_y + dy, cz + dz)
                name = dress_name(raw)
                low = name.lower()
                if ('chair' in low or 'stool' in low) and 'brok' not in low and abs(mtx[4]) >= 0.7:
                    seats.append((len(objects), name))
                objects.append(bytes(b))
            return seats

        room_cells = sum(len(room.cells) for room in lay.rooms if room.kind == 'room') or 1
        # what a fight leaves: the stone's own debris (not remains, not decals)
        fight_debris = [(n, raw) for n, raw in tp.debris if n != REMAINS and n in DEBRIS and not n.startswith('decal') and themed(tp, n, stage_no)]
        # the stone's own floor decals, in dressing order
        d_decals = [o for _tag, cells_, _rw, _rh in d_rooms for _cl, objs_, _it, _k in cells_ for o in objs_ if dress_name(o[3]).startswith('decal')]

        def put_decal(c, r):
            o = rng.pick(d_decals)
            x, z = world(c, r, w, h, rng.unit() * 0.4 + 0.3, rng.unit() * 0.4 + 0.3)
            mtx = turn_rows(list(struct.unpack_from('<9f', o[3], 8 + 20)), rng.unit() * 360.0)
            objects.append(_put(o[3], (x, tp.floor_y + o[1], z), mtx))

        # wall-hung pieces by (purpose tag, wall class), from the stone's own rooms
        d_hung = {}
        d_hung_any = {}  # by wall class only (corridor doorways)
        for tag_, cells_, _rw, _rh in d_rooms:
            for cl, objs_, _it, _k in cells_:
                if cl != 0:
                    for o in objs_:
                        if o[1] > HUNG_Y:
                            d_hung.setdefault((tag_, cl), []).append(o)
                            d_hung_any.setdefault(cl, []).append(o)
        room_chance = max(DRESS_MIN_CHANCE, min(DRESS_ROOM_CHANCE, DRESS_ROOM_CHANCE * DRESS_FULL_CELLS // room_cells))
        if mutator == 'collapsed':
            room_chance = min(DRESS_COLLAPSED_CHANCE, room_chance + 25)
        for room in lay.rooms:
            if room.kind != 'room':
                continue
            src_index = room.src  # chosen with the purpose (choose_sources, arrange_neighbours)
            src = d_rooms[src_index] if 0 <= src_index < len(d_rooms) else None
            if room.purpose == 'quiet' and depth_of(area) % CHAIR_DEPTHS == 0:
                # easter egg 6: the quiet room holds one chair, by its north wall
                seat = next((o for rm in d_rooms for _cl, objs, _it, _k in rm[1] for o in objs
                             if ('chair' in dress_name(o[3]).lower()) and abs(struct.unpack_from('<f', o[3], 8 + 20 + 16)[0]) >= 0.7), None)
                if seat is not None:
                    cc = (room.c0 + room.c1) // 2
                    b = bytearray(seat[3])
                    x, z = world(cc, room.r0, w, h, 0.5, 0.3)
                    struct.pack_into('<3f', b, 8 + 56, x, tp.floor_y + seat[1], z)
                    objects.append(bytes(b))
                continue
            if (room.copy or room.show) and src is not None:
                # easter egg 4 and the showpiece: the source room exactly, cell for cell, each in its own
                # original turn; in the copy's corner a chair facing the wall (the backrooms' door)
                seat = next((o for rm in d_rooms for _cl, objs, _it, _k in rm[1] for o in objs
                             if ('chair' in dress_name(o[3]).lower()) and abs(struct.unpack_from('<f', o[3], 8 + 20 + 16)[0]) >= 0.7), None) if room.copy else None
                if seat is not None:
                    b = bytearray(seat[3])
                    mtx = turn_rows(list(struct.unpack_from('<9f', b, 8 + 20)), 45.0)
                    struct.pack_into('<9f', b, 8 + 20, *mtx)
                    x, z = world(room.c0, room.r0, w, h, 0.38, 0.38)
                    struct.pack_into('<3f', b, 8 + 56, x, tp.floor_y + seat[1], z)
                    objects.append(bytes(b))
                for (c, r), (_cl, objs, cell_items, ck) in zip(room.cells, src[1]):
                    place(objs, c, r, ck)
                    cx, cz = world(c, r, w, h)
                    for iid, idx, idy, idz, iyaw in cell_items:
                        for _ in range(ck):
                            idx, idz = idz, -idx
                            iyaw -= 90.0
                        dress_items.append(_placement(tp.key_place, 0x80000000 | iid, (cx + idx, tp.floor_y + idy, cz + idz), iyaw))
                continue
            seats = []
            used = set()  # each source cell once per room, so a big room is not the same corner over and over
            clear = walkway(lay, room)
            roll = rng.below(100)
            event = 'fight' if roll < EVENT_FIGHT else 'looted' if roll < EVENT_LOOTED else 'hurry' if roll < EVENT_HURRY else 'tidy'
            if any(room.contains(*a) or room.contains(*b) for a, b in lay.blocked_doors):
                event = 'fight'  # the barricade was held
            chance = room_chance // 2 if event == 'looted' else room_chance
            if room.purpose == 'store':
                for o in lay.rooms:
                    if o.kind == 'room' and o.purpose == 'kitchen':
                        gap = max(o.c0 - room.c1 - 1, room.c0 - o.c1 - 1, o.r0 - room.r1 - 1, room.r0 - o.r1 - 1)
                        if gap <= NEIGHBOUR_GAP:
                            chance = 100  # the kitchen's stores, stacked high
            done = set()  # cells dressed by a group
            dressed = set()  # cells the cell-by-cell dressing filled
            if event != 'looted' and src is not None and src[2] >= 2 and src[3] >= 2 and len(src[1]) == src[2] * src[3]:
                inside = set(room.cells)
                srw = src[2]
                for c, r in room.cells:
                    quad = ((c, r), (c + 1, r), (c, r + 1), (c + 1, r + 1))
                    if len(objects) >= OBJECT_CAP or any(q in done or q not in inside or q in hall_pillar_cells for q in quad):
                        continue
                    if not rng.chance(GROUP_CHANCE):
                        continue
                    want = [class_of(*q) for q in quad]
                    if any(x is None for x in want):
                        continue
                    blocks = []
                    for j in range(src[3] - 1):
                        for i in range(srw - 1):
                            idx = (j * srw + i, j * srw + i + 1, (j + 1) * srw + i, (j + 1) * srw + i + 1)
                            if (all((src[1][x][0], src[1][x][3]) == want[n] and (src_index, x) not in used for n, x in enumerate(idx))
                                    and sum(len(src[1][x][1]) for x in idx) >= 2):
                                blocks.append(idx)
                    if not blocks:
                        continue
                    idx = rng.pick(blocks)
                    for n, (qc, qr) in enumerate(quad):
                        _cl, objs, cell_items, ck = src[1][idx[n]]
                        used.add((src_index, idx[n]))
                        done.add((qc, qr))
                        seats += place(objs, qc, qr, ck, clear)
                        cx, cz = world(qc, qr, w, h)
                        for iid, ix, iy, iz, iyaw in cell_items:
                            if len(dress_items) >= ITEM_CAP:
                                break
                            for _ in range(ck):
                                ix, iz = iz, -ix
                                iyaw -= 90.0
                            dress_items.append(_placement(tp.key_place, 0x80000000 | iid, (cx + ix, tp.floor_y + iy, cz + iz), iyaw))
            for c, r in room.cells:
                if (c, r) in done:
                    continue
                if (c, r) in hall_pillar_cells or not rng.chance(chance) or len(objects) >= OBJECT_CAP:
                    continue
                ck = class_of(c, r)
                if ck is None:
                    continue
                ci, k = ck
                objs = None
                if src is not None:
                    cand = [((src_index, j), o, it) for j, (cl, o, it, _k) in enumerate(src[1]) if cl == ci and (src_index, j) not in used]
                    if not cand:
                        cand = [((ri, j), o, it) for ri in d_by_tag.get(src[0], []) for j, (cl, o, it, _k) in enumerate(d_rooms[ri][1]) if cl == ci and (ri, j) not in used]
                    if not cand:  # every fitting cell of its purpose used once: they repeat (2026-10-22, density)
                        cand = [((ri, j), o, it) for ri in [src_index] + d_by_tag.get(src[0], []) for j, (cl, o, it, _k) in enumerate(d_rooms[ri][1]) if cl == ci]
                    if not cand:
                        continue
                    key, objs, cell_items = rng.pick(cand)
                    used.add(key)
                    # the cell's loose items (cups, books...) as they lay, turned with the cell
                    cx, cz = world(c, r, w, h)
                    for iid, idx, idy, idz, iyaw in cell_items:
                        if len(dress_items) >= ITEM_CAP:
                            break
                        for _ in range(k):
                            idx, idz = idz, -idx
                            iyaw -= 90.0
                        dress_items.append(_placement(tp.key_place, 0x80000000 | iid, (cx + idx, tp.floor_y + idy, cz + idz), iyaw))
                if objs is None:
                    pool = d_classes[ci] if ci < len(d_classes) else []
                    if not pool:
                        continue
                    objs = rng.pick(pool)
                seats += place(objs, c, r, k, clear)
                dressed.add((c, r))
            # wall dressing by purpose on the walled cells left bare
            if src is not None:
                for c, r in room.cells:
                    if (c, r) in done or (c, r) in dressed or (c, r) in hall_pillar_cells or len(objects) >= OBJECT_CAP:
                        continue
                    ck = class_of(c, r)
                    if ck is None or ck[0] == 0:
                        continue
                    pool = d_hung.get((src[0], ck[0]))
                    if not pool or not rng.chance(WALL_DRESS_CHANCE):
                        continue
                    place([rng.pick(pool)], c, r, ck[1])
            # floor decals by use: worn walkways, a fight's marks, a kitchen's spills
            if d_decals:
                for c, r in room.cells:
                    if len(objects) >= OBJECT_CAP:
                        break
                    if (c, r) in clear and rng.chance(WALK_DECAL_CHANCE):
                        put_decal(c, r)
                for _ in range(DECAL_FIGHT if event == 'fight' else DECAL_KITCHEN if room.purpose == 'kitchen' else 0):
                    if len(objects) >= OBJECT_CAP:
                        break
                    put_decal(*rng.pick(room.cells))
                # a fight's trail down the corridor from its first doorway
                if event == 'fight':
                    door = None
                    for a, b in lay.doors:
                        if room.contains(*a) and lay.at(*b) == Layout.CORRIDOR:
                            door = (a, b)
                        elif room.contains(*b) and lay.at(*a) == Layout.CORRIDOR:
                            door = (b, a)
                        if door is not None:
                            break
                    if door is not None:
                        prev, cell = door
                        for _ in range(TRAIL_LEN):
                            if len(objects) >= OBJECT_CAP:
                                break
                            if rng.chance(TRAIL_CHANCE):
                                put_decal(*cell)
                            nxt = None
                            for q, (dx, dz) in enumerate(SIDE):
                                nb = (cell[0] + dx, cell[1] + dz)
                                if nxt is None and nb != prev and lay.at(*nb) == Layout.CORRIDOR and side_kind(lay, cell[0], cell[1], q) != WALL:
                                    nxt = nb
                            if nxt is None:
                                break
                            prev, cell = cell, nxt
            # the story the event tells with the seats
            jitter = TIDY_JITTER if event == 'tidy' else HURRY_JITTER if event == 'hurry' else SEAT_JITTER
            to_knock = 0 if event == 'tidy' else len(seats) if event == 'fight' else 1
            knocked = 0
            for index, name in seats:
                b = bytearray(objects[index])
                tips = d_tipped.get(name)
                if knocked < to_knock and tips:
                    tm, tdy = rng.pick(tips)
                    mtx = turn_rows(list(tm), rng.unit() * 360.0)
                    x, _y, z = struct.unpack_from('<3f', b, 8 + 56)
                    struct.pack_into('<3f', b, 8 + 56, x, tp.floor_y + tdy, z)
                    knocked += 1
                else:
                    mtx = turn_rows(list(struct.unpack_from('<9f', b, 8 + 20)), rng.unit() * 2 * jitter - jitter)
                struct.pack_into('<9f', b, 8 + 20, *mtx)
                objects[index] = bytes(b)
            if event == 'fight' and fight_debris:
                for _ in range(FIGHT_DEBRIS):
                    if len(objects) >= OBJECT_CAP:
                        break
                    fc, fr = rng.pick(room.cells)
                    name, raw = rng.pick(fight_debris)
                    x, z = world(fc, fr, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
                    objects.append(_object(raw, (x, tp.floor_y + DEBRIS[name], z), rng.unit() * 360.0))
        for c, r in lay.corridor_cells:
            if rng.chance(DRESS_CORRIDOR_CHANCE) and len(objects) < OBJECT_CAP:
                ck = class_of(c, r)
                if ck is not None and ck[0] < len(d_classes) and d_classes[ck[0]]:
                    place(rng.pick(d_classes[ck[0]]), c, r, ck[1])
        # corridor clutter: debris where corridors bend or meet, a wall piece by their doorways
        for c, r in lay.corridor_cells:
            if len(objects) >= OBJECT_CAP:
                break
            sides = [side_kind(lay, c, r, q) for q in range(4)]
            exits = [q for q in range(4) if sides[q] != WALL]
            turn = len(exits) >= 3 or (len(exits) == 2 and (exits[1] - exits[0]) % 2 == 1)
            if turn and fight_debris and rng.chance(CORRIDOR_CLUTTER):
                for _ in range(1 + rng.below(2)):
                    name, raw = rng.pick(fight_debris)
                    x, z = world(c, r, w, h, rng.unit() * 0.5 + 0.25, rng.unit() * 0.5 + 0.25)
                    objects.append(_object(raw, (x, tp.floor_y + DEBRIS[name], z), rng.unit() * 360.0))
            if DOOR in sides:
                ck = class_of(c, r)
                if ck is not None and ck[0] != 0 and ck[0] in d_hung_any and rng.chance(DOORWAY_DRESS):
                    place([rng.pick(d_hung_any[ck[0]])], c, r, ck[1])
    # the barricades: on the room side of each blocked doorway, a barricade across it and something heaped beside
    for (ac, ar), (bc, br) in lay.blocked_doors:
        q = SIDE.index((bc - ac, br - ar))
        x, z = world(ac, ar, w, h, 0.5 + 0.32 * SIDE[q][0], 0.5 + 0.32 * SIDE[q][1])
        _name, raw = rng.pick(blockers)
        objects.append(_object(raw, (x, tp.floor_y, z), SIDE_YAW[q]))
        if block_fill:
            side = (q + 1) % 4
            x2, z2 = world(ac, ar, w, h, 0.5 + 0.22 * SIDE[q][0] + 0.25 * SIDE[side][0], 0.5 + 0.22 * SIDE[q][1] + 0.25 * SIDE[side][1])
            _name, raw = rng.pick(block_fill)
            objects.append(_object(raw, (x2, tp.floor_y, z2), rng.unit() * 360.0))
    remains = next((raw for name, raw in tp.debris if name == REMAINS), None) if themed(tp, REMAINS, stage_no) else None
    # (easter egg 1, the last descent's remains, was dropped 2026-10-22: Hunter, "last descent makes no
    # sense if each run is randomized")
    gaol = next((room for room in lay.rooms if room.kind == 'room' and room.purpose == 'gaol'), None)
    if remains is not None and gaol is not None and depth_of(area) >= 2 and rng.chance(ELARA_CHANCE):
        # easter egg 2: the twelfth name, remains by the bars of the first gaol
        x, z = world(gaol.c0, gaol.r0, w, h, 0.35, 0.35)
        objects.append(_object(remains, (x, DEBRIS[REMAINS], z), 205.0))
        info_eggs['elara'] = 1
    carving = next((raw for name, raw in tp.props if name == CARVING), None) if themed(tp, CARVING, stage_no) else None
    if carving is not None and lay.treasury is not None and depth_of(area) >= 6 and not shrine_done:
        # easter egg 3: the shrine's carving, in the treasury, once a run
        t_ = lay.treasury
        x, z = world(t_.c0, t_.r0, w, h, 0.9, 0.9)
        objects.append(_object(carving, (x, tp.floor_y, z), 0.0))
        info_eggs['shrine'] = 1
    pillar_cells = _pillar_cells(lay.boss_room) if pillars_ok else []
    hall_pillars = [cell for room in lay.rooms if room.pillars for cell in _pillar_cells(room)]
    for c, r in pillar_cells + hall_pillars:
        x, z = world(c, r, w, h)
        objects.append(_object(tp.pillar, (x, tp.floor_y, z), 0.0))
    blocked_cells = set(hall_pillars)
    goal = exit_room.goal if exit_room.kind == 'maze' else exit_room.centre
    gx, gz = world(*goal, w, h)
    if staircase:
        objects.append(_object(tp.stairs, (gx, tp.floor_y, gz), rng.unit() * 360.0))
    # (plates are known only after the items pass; the object chunk is assembled below)
    # items: arrival marker, the exit zone at the goal, the locked door, the key, chests
    start = lay.rooms[0]
    sx, sz = world(*start.centre, w, h)
    places = [
        _placement(tp.marker_place, 0x80000000 | tp.arrival_id, (sx, 100.0, sz), 0.0),
        _placement(tp.marker_place, 0x80000000 | tp.zone_id, (gx, 100.0, gz), 0.0),
    ]
    copy_room = next((room for room in lay.rooms if room.copy), None)
    if copy_room is not None and tp.wall_zone_id:
        x, z = world(copy_room.c0, copy_room.r0, w, h, 0.16, 0.16)
        places.append(_placement(tp.marker_place, 0x80000000 | tp.wall_zone_id, (x, 100.0, z), 0.0))
    objects_extra = []  # fire operatives are item placements too; listed after the markers
    plates = []  # plate decorations under push zones (objects, appended after the props)
    inside, outside = lay.exit_door
    q = SIDE.index((outside[0] - inside[0], outside[1] - inside[1]))
    dx, dz = world(*inside, w, h)
    kind = puzzle_kind(area)
    puzzled = kind in ('plate', 'order', 'timed', 'hold') and tp.puzzle_gate_id and len(tp.puzzle_lever_ids) >= 3
    if puzzled:  # the boss doorway is the puzzle's portcullis, down until the puzzle raises it
        places.append(_placement(tp.gate_place, 0x80000000 | tp.puzzle_gate_id, (dx, tp.floor_y, dz), SIDE_YAW[q], 1))
    else:
        places.append(_placement(tp.door_place, 0x80000000 | tp.door_ids[pair], (dx, tp.floor_y, dz), SIDE_YAW[q], 1))
    info = {'boss': 0, 'gate': 0, 'gate_lever': 0, 'fires': list(tp.fire_ids)}
    if lay.gate:
        (gbc, gbr), (gec, ger) = lay.gate
        gq = SIDE.index((gbc - gec, gbr - ger))  # the gate sits in the exit-side cell, facing the boss room
        gx, gz2 = world(gec, ger, w, h)
        places.append(_placement(tp.gate_place, 0x80000000 | tp.gate_ids[pair], (gx, tp.floor_y, gz2), SIDE_YAW[gq], 1))
        # its lever on a wall of the exit-side cell, behind the gate (the mod pulls it when the boss dies)
        walls = [wq for wq in range(4) if side_kind(lay, gec, ger, wq) == WALL] or [(gq + 2) % 4]
        lq = walls[rng.below(len(walls))]
        lx, lz = world(gec, ger, w, h, 0.5 + 0.42 * SIDE[lq][0], 0.5 + 0.42 * SIDE[lq][1])
        places.append(_placement(tp.lever_place, 0x80000000 | tp.gate_lever_ids[pair], (lx, LEVER_Y, lz), SIDE_YAW[(lq + 2) % 4]))
        info['gate'], info['gate_lever'] = tp.gate_ids[pair], tp.gate_lever_ids[pair]
    # the wing gate (another of the template's portcullis/lever pairs): in the far cell facing back,
    # its lever on the near side for the player to find
    if lay.wing and len(tp.gate_ids) > 1:
        (wac, war), (wbc, wbr), (wlc, wlr), wlq = lay.wing
        wk = (pair + 2) % len(tp.gate_ids)
        wq = SIDE.index((wac - wbc, war - wbr))
        wx, wz = world(wbc, wbr, w, h)
        places.append(_placement(tp.gate_place, 0x80000000 | tp.gate_ids[wk], (wx, tp.floor_y, wz), SIDE_YAW[wq], 1))
        lx, lz = world(wlc, wlr, w, h, 0.5 + 0.42 * SIDE[wlq][0], 0.5 + 0.42 * SIDE[wlq][1])
        places.append(_placement(tp.lever_place, 0x80000000 | tp.gate_lever_ids[wk], (lx, LEVER_Y, lz), SIDE_YAW[(wlq + 2) % 4]))
        info['wing_gate'] = tp.gate_ids[wk]
    # the boss pen: its portcullis in the pen cell facing the boss room (placed down; the mod raises it),
    # its lever on a wall of the boss cell beside the doorway; the mod needs the pen's box to see the boss in it
    if lay.pen and len(tp.gate_ids) > 2:
        (pc, pr), (bc, br), pen_room = lay.pen
        pk = (pair + 1) % len(tp.gate_ids)
        pq = SIDE.index((bc - pc, br - pr))
        walls = [q for q in ((pq + 1) % 4, (pq + 3) % 4, (pq + 2) % 4) if side_kind(lay, bc, br, q) == WALL]
        if walls:
            px, pz = world(pc, pr, w, h)
            places.append(_placement(tp.gate_place, 0x80000000 | tp.gate_ids[pk], (px, tp.floor_y, pz), SIDE_YAW[pq], 1))
            lq = walls[0]
            lx, lz = world(bc, br, w, h, 0.5 + 0.42 * SIDE[lq][0], 0.5 + 0.42 * SIDE[lq][1])
            places.append(_placement(tp.lever_place, 0x80000000 | tp.gate_lever_ids[pk], (lx, LEVER_Y, lz), SIDE_YAW[(lq + 2) % 4]))
            x0, z0 = world(pen_room.c0, pen_room.r0, w, h, 0.0, 0.0)
            x1, z1 = world(pen_room.c1, pen_room.r1, w, h, 1.0, 1.0)
            info['pen_gate'], info['pen_lever'], info['pen_box'] = tp.gate_ids[pk], tp.gate_lever_ids[pk], [x0, z0, x1, z1]
    # talk zones: the companions react at the boss door (its corridor side), past the gate, at the
    # stairs and in the start room of a new depth; all of a spot's zones sit on one cell
    per_spot = len(tp.talk_zone_ids) // len(TALK_SPOTS) if tp.talk_zone_ids else 0
    new_depth = depth_of(area) >= 2 and (area - 1) % AREAS_PER_DEPTH == 0
    spots = {'Boss Door': outside, 'Gate': lay.gate[0] if lay.gate else None,
             'Stairs': goal if staircase else None, 'Depth': start.centre if new_depth else None,
             'Key': None, 'Vault': None,
             'Closet': lay.closets[0][1] if lay.closets else None, 'Arrive': start.centre,
             'Boss': lay.boss_room.centre if lay.boss_room else None}
    # (the key spot is known only after the key is placed; it is appended below)
    for spot_index, spot in enumerate(TALK_SPOTS):
        cell = spots[spot]
        if cell is None or per_spot == 0:
            continue
        tx, tz = world(*cell, w, h)
        for zid in talk_zone_ids(tp, spot, per_spot, present):
            places.append(_placement(tp.marker_place, 0x80000000 | zid, (tx, 100.0, tz), 0.0))
    per_pair = len(tp.pair_zone_ids) // len(PAIR_SPOTS) if tp.pair_zone_ids else 0
    pair_spots = {'Gate': spots['Gate'], 'Depth': spots['Depth'], 'Boss': spots['Boss']}
    for spot_index, spot in enumerate(PAIR_SPOTS):
        cell = pair_spots[spot]
        if cell is None or per_pair == 0:
            continue
        tx, tz = world(*cell, w, h)
        for k in range(per_pair):
            places.append(_placement(tp.marker_place, 0x80000000 | tp.pair_zone_ids[spot_index * per_pair + k], (tx, 100.0, tz), 0.0))
    # the key: in the ordinary room farthest from the exit door; loose, or in a cache among decoys
    candidates = [room for room in lay.rooms if room.kind == 'room'] or [start]
    puzzle_objects = []
    if puzzled:
        p_places, p_objects, p_info, opener = _puzzle_parts(tp, lay, rng, kind, start, inside, outside, w, h, dress[1] if dress else None, stage_no)
        places += p_places
        puzzle_objects = p_objects  # added after the lamps are placed (as gen.lua, whose object chunk is made first)
        info.update(p_info)
        lay.key_cell = opener
    by_distance = sorted(candidates, key=lambda room: abs(room.centre[0] - inside[0]) + abs(room.centre[1] - inside[1]))
    far_half = by_distance[len(by_distance) // 2 :]  # not always the farthest room: any of the farther half
    vaults = []
    if is_vault_area(area) and not puzzled:
        vaults = [room for room in far_half if sum(1 for d in lay.doors if room.contains(*d[0]) or room.contains(*d[1])) == 1]
    key_room = rng.pick(vaults) if vaults else rng.pick(far_half)
    if not puzzled:
        kc, kr = rng.pick(key_room.cells)
        lay.key_cell = (kc, kr)
        kx, kz = world(kc, kr, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
    if puzzled:
        pass  # the puzzle's parts are placed above; no key, no lever
    elif is_lever_area(area):
        # the lever on a wall of the key room, facing into the room (its device target is this pair's door)
        edge = [(c, r, q) for (c, r) in key_room.cells for q in range(4) if side_kind(lay, c, r, q) == WALL]
        c, r, q = rng.pick(edge)
        lay.key_cell = (c, r)
        lx, lz = world(c, r, w, h, 0.5 + 0.42 * SIDE[q][0], 0.5 + 0.42 * SIDE[q][1])
        places.append(_placement(tp.lever_place, 0x80000000 | tp.lever_ids[pair], (lx, LEVER_Y, lz), SIDE_YAW[(q + 2) % 4]))
    elif rng.chance(50):
        places.append(_placement(tp.key_place, 0x80000000 | tp.key_ids[pair], (kx, tp.floor_y, kz), rng.unit() * 360.0))
    else:
        places.append(_placement(tp.chest_place, 0x80000000 | tp.key_chest_ids[pair], (kx, tp.floor_y, kz), rng.unit() * 360.0))
    if per_spot and not is_lever_area(area) and not puzzled:
        kx2, kz2 = world(*lay.key_cell, w, h)
        for zid in talk_zone_ids(tp, 'Key', per_spot, present):
            places.append(_placement(tp.marker_place, 0x80000000 | zid, (kx2, 100.0, kz2), 0.0))
    if vaults:
        # the vault: its one doorway gets the next pair's locked door, that pair's key goes to another room
        pair2 = (pair + 1) % len(tp.key_ids)
        d = next(d for d in lay.doors if key_room.contains(*d[0]) or key_room.contains(*d[1]))
        v_in, v_out = (d[0], d[1]) if key_room.contains(*d[0]) else (d[1], d[0])
        lay.vault_door = (v_in, v_out)
        vq = SIDE.index((v_out[0] - v_in[0], v_out[1] - v_in[1]))
        vx, vz = world(*v_in, w, h)
        places.append(_placement(tp.door_place, 0x80000000 | tp.door_ids[pair2], (vx, tp.floor_y, vz), SIDE_YAW[vq], 1))
        if per_spot:
            vx2, vz2 = world(*v_out, w, h)
            for zid in talk_zone_ids(tp, 'Vault', per_spot, present):
                places.append(_placement(tp.marker_place, 0x80000000 | zid, (vx2, 100.0, vz2), 0.0))
        others = [room for room in candidates if room is not key_room] or [start]
        if lay.wing:  # the vault's own key on the near side of the wing gate (the lever may stand in the vault)
            shut = {frozenset((lay.wing[0], lay.wing[1]))} | {frozenset((s_in, s_out)) for s_in, s_out, _ in lay.secrets}
            near = _reachable_shut(lay, start.centre, shut)
            others = [room for room in others if room.centre in near] or [start]
        k2_room = rng.pick(others)
        k2c, k2r = rng.pick(k2_room.cells)
        lay.vault_key_cell = (k2c, k2r)
        k2x, k2z = world(k2c, k2r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
        if rng.chance(50):
            places.append(_placement(tp.key_place, 0x80000000 | tp.key_ids[pair2], (k2x, tp.floor_y, k2z), rng.unit() * 360.0))
        else:
            places.append(_placement(tp.chest_place, 0x80000000 | tp.key_chest_ids[pair2], (k2x, tp.floor_y, k2z), rng.unit() * 360.0))
    # traps in corridor cells: a fire operative with a fire zone on it; push zones that shove toward a wall
    trap_cells = [cell for k, cell in enumerate(lay.corridor_cells) if k % 3 == 2 and abs(cell[0] - start.centre[0]) + abs(cell[1] - start.centre[1]) >= 5]
    for slot in range(min(fire_trap_count(area), len(tp.fire_ids))):
        if not trap_cells:
            break
        c, r = trap_cells.pop(rng.below(len(trap_cells)))
        x, z = world(c, r, w, h)
        objects_extra.append(_placement(tp.fire_place, 0x80000000 | tp.fire_ids[slot], (x, tp.floor_y, z), 0.0))
        places.append(_placement(tp.marker_place, 0x80000000 | tp.fire_zone_ids[slot], (x, 100.0, z), 0.0))
        # the plate you step on, half a cell before the fire along the corridor; it drives the fire natively
        opens = [q for q in range(4) if side_kind(lay, c, r, q) != WALL]
        q = rng.pick(opens) if opens else 0
        px, pz = world(c, r, w, h, 0.5 + 0.35 * SIDE[q][0], 0.5 + 0.35 * SIDE[q][1])
        places.append(_placement(tp.plate_place, 0x80000000 | tp.plate_fire_ids[slot], (px, tp.floor_y, pz), 0.0))
    # secret doors at both ends of the secret corridors, their brick switches on a wall of the room
    for k, (s_in, s_out, room) in enumerate(lay.secrets[: 2 * len(tp.switch_ids)]):  # named apart from inside/outside: the boss door's cells are still needed below
        q = SIDE.index((s_out[0] - s_in[0], s_out[1] - s_in[1]))
        sx2, sz2 = world(*s_in, w, h)
        places.append(_placement(tp.secret_door_place, 0x80000000 | tp.secret_door_ids[k % len(tp.secret_door_ids)], (sx2, tp.floor_y, sz2), SIDE_YAW[q], 1))
        edge = [(c, r, wq) for (c, r) in room.cells for wq in range(4) if side_kind(lay, c, r, wq) == WALL]
        c, r, wq = rng.pick(edge)
        wx, wz = world(c, r, w, h, 0.5 + 0.46 * SIDE[wq][0], 0.5 + 0.46 * SIDE[wq][1])
        places.append(_placement(tp.switch_place, 0x80000000 | tp.switch_ids[k % len(tp.switch_ids)], (wx, LEVER_Y + 45.0, wz), SIDE_YAW[(wq + 2) % 4]))
    # maze gates across the path, their levers in dead ends before them
    for k, (gate_cell, gq, lever_cell, lq) in enumerate(lay.maze_gates[: len(tp.maze_gate_ids)]):
        mx, mz = world(*gate_cell, w, h)
        places.append(_placement(tp.gate_place, 0x80000000 | tp.maze_gate_ids[k], (mx, tp.floor_y, mz), SIDE_YAW[gq], 1))
        lx, lz = world(*lever_cell, w, h, 0.5 + 0.42 * SIDE[lq][0], 0.5 + 0.42 * SIDE[lq][1])
        places.append(_placement(tp.lever_place, 0x80000000 | tp.maze_lever_ids[k], (lx, LEVER_Y, lz), SIDE_YAW[(lq + 2) % 4]))
    # the companion bypass: its portcullis in the outside cell facing the goal, its lever on the goal cell's other outer wall
    if lay.bypass and tp.bypass_gate_id:
        bg, bt, blq = lay.bypass
        bq = SIDE.index((bg[0] - bt[0], bg[1] - bt[1]))
        bx, bz = world(*bt, w, h)
        places.append(_placement(tp.gate_place, 0x80000000 | tp.bypass_gate_id, (bx, tp.floor_y, bz), SIDE_YAW[bq], 1))
        lx2, lz2 = world(*bg, w, h, 0.5 + 0.42 * SIDE[blq][0], 0.5 + 0.42 * SIDE[blq][1])
        places.append(_placement(tp.lever_place, 0x80000000 | tp.bypass_lever_id, (lx2, LEVER_Y, lz2), SIDE_YAW[(blq + 2) % 4]))
    # monster closets: a portcullis in the closet's doorway, a plate in the corridor cell that opens it
    for k, (closet_cell, corridor_cell, room) in enumerate(lay.closets[: len(tp.closet_gate_ids)]):
        q = SIDE.index((corridor_cell[0] - closet_cell[0], corridor_cell[1] - closet_cell[1]))
        cx2, cz2 = world(*closet_cell, w, h)
        places.append(_placement(tp.gate_place, 0x80000000 | tp.closet_gate_ids[k], (cx2, tp.floor_y, cz2), SIDE_YAW[q], 1))
        px, pz = world(*corridor_cell, w, h)
        places.append(_placement(tp.plate_place, 0x80000000 | tp.plate_closet_ids[k], (px, tp.floor_y, pz), 0.0))
    for _ in range(push_trap_count(area)):
        if not trap_cells:
            break
        c, r = trap_cells.pop(rng.below(len(trap_cells)))
        walls = [q for q in range(4) if side_kind(lay, c, r, q) == WALL]
        if not walls:
            continue
        q = rng.pick(walls)
        x, z = world(c, r, w, h)
        places.append(_placement(tp.marker_place, 0x80000000 | tp.hazard_ids[q], (x, 100.0, z), 0.0))
    places += objects_extra
    chests = chest_roster(tp, depth_of(area))
    for c, r in lay.spur_ends:  # a reason to walk a dead end, three times in five
        if rng.chance(60):
            x, z = world(c, r, w, h)
            places.append(_placement(tp.chest_place, 0x80000000 | rng.pick(chests), (x, tp.floor_y, z), rng.unit() * 360.0))
    rare = rare_chests(tp)
    rare_chance = min(10 + 5 * depth_of(area), 60)
    salves = 0
    for room in lay.rooms:
        if room.kind != 'room':
            continue
        if rng.chance(CHEST_CHANCE.get(room.purpose, 45)):
            c, r = rng.pick(room.cells)
            x, z = world(c, r, w, h)
            chest = rng.pick(rare) if room.purpose == 'shrine' and rng.chance(rare_chance) else rng.pick(chests)
            places.append(_placement(tp.chest_place, 0x80000000 | chest, (x, tp.floor_y, z), rng.unit() * 360.0))
        # the first healing salve: in the quiet room (the second is in the hidden treasury)
        if tp.salve_id and salves < 1 and room.purpose == 'quiet':
            c, r = rng.pick(room.cells)
            x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
            places.append(_placement(tp.key_place, 0x80000000 | tp.salve_id, (x, tp.floor_y, z), rng.unit() * 360.0))
            salves += 1
    if lay.treasury is not None:  # the hidden room: a rare find and the second salve, always
        tcells = lay.treasury.cells
        x, z = world(*tcells[0], w, h)
        places.append(_placement(tp.chest_place, 0x80000000 | rng.pick(rare), (x, tp.floor_y, z), rng.unit() * 360.0))
        if tp.salve_id:
            x, z = world(*tcells[3], w, h)
            places.append(_placement(tp.key_place, 0x80000000 | tp.salve_id, (x, tp.floor_y, z), 0.0))
    places += dress_items
    item_chunk = _patch_script(tp.item_db, area, seed) + tp.item_strings + _chunk(TAG_ITEM_PLACES, struct.pack('<I', len(places)) + b''.join(places))
    objects += plates
    # light by use: each ordinary room's lamp halfway toward the middle of the things standing in it
    sums = {}
    for raw in objects:
        ox, _oy, oz = struct.unpack_from('<3f', raw, 8 + 56)
        o = lay.at(math.floor(ox / CELL + w / 2), math.floor(oz / CELL + h / 2))
        if o in room_lamp:
            a = sums.setdefault(o, [0.0, 0.0, 0])
            a[0] += ox
            a[1] += oz
            a[2] += 1
    for o, (sx_, sz_, n) in sorted(sums.items()):
        b = bytearray(nodes[room_lamp[o]])
        lx, ly, lz = struct.unpack_from('<3f', b, 8 + 68)
        struct.pack_into('<3f', b, 8 + 68, (lx + sx_ / n) / 2, ly, (lz + sz_ / n) / 2)
        nodes[room_lamp[o]] = bytes(b)
    node_chunk = struct.pack('<I', len(nodes)) + b''.join(nodes)
    objects += puzzle_objects
    object_chunk = struct.pack('<I', len(objects)) + b''.join(objects)
    # people
    enemies = enemy_count(area)
    depth = depth_of(area)
    roster = enemy_roster(tp, depth)
    keep_out = 6 if depth == 1 else 4 if depth == 2 else 2  # cells from the start: no ambush on arrival
    if mutator == 'silent':
        enemies = max(4, enemies // 4)  # the halls are empty; the boss room is not
    elif mutator == 'ambush':
        enemies = min(enemies * 3 // 2, ENEMY_CAP)
        keep_out = 1
    spawns = []
    homes = []
    for room in lay.rooms:
        if room.kind in ('start', 'exit', 'boss', 'closet', 'treasury', 'pen') or room.purpose == 'quiet':
            continue
        homes += [room] * HOME_WEIGHT.get(room.purpose, 1)
    for room in lay.rooms:
        if room.kind == 'closet':  # two or three enemies waiting behind the plate-opened portcullis
            for cell in room.cells[: 2 + (1 if depth >= 4 else 0)]:
                x, z = world(cell[0], cell[1], w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
                spawns.append(_spawn(0x80000000 | rng.pick(roster), (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
    tries = 0
    boss_room = lay.boss_room
    if boss_room is not None:
        bosses = boss_roster(tp, depth)
        boss_id = rng.pick(bosses)
        if tp.proctor_boss_id and area == 1 + 2 * AREAS_PER_DEPTH:  # the first area of depth 3: the proctor
            boss_id = tp.proctor_boss_id
        bx, bz = world(*boss_room.centre, w, h)
        spawns.append(_spawn(0x80000000 | boss_id, (bx, tp.floor_y, bz), rng.unit() * 2 * math.pi))
        info['boss'] = boss_id
        info['bosses'] = [boss_id]
        boss_cells = [cell for cell in boss_room.cells if cell not in pillar_cells]
        for _ in range(min(boss_count(area) + (1 if mutator == 'silent' else 0), BOSS_CAP) - 1):  # extra bosses deeper down; the gate waits for the first
            c, r = rng.pick(boss_cells)
            x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
            extra = rng.pick(bosses)
            spawns.append(_spawn(0x80000000 | extra, (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
            info['bosses'].append(extra)
        for _ in range(min(boss_minion_count(area) * (2 if mutator == 'silent' else 1), MINION_CAP)):
            c, r = rng.pick(boss_cells)
            x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
            spawns.append(_spawn(0x80000000 | rng.pick(roster), (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
    while len(spawns) < enemies and tries < enemies * 8:
        tries += 1
        room = rng.pick(homes)
        if room.kind == 'maze':
            c, r = rng.pick([(c, r) for r in range(room.r0, room.r1 + 1, 2) for c in range(room.c0, room.c1 + 1, 2)])
            if abs(c - room.goal[0]) + abs(r - room.goal[1]) < 3:
                continue  # the exit zone must not be walked into by a wandering enemy
        else:
            c, r = rng.pick(room.cells)
        if abs(c - start.centre[0]) + abs(r - start.centre[1]) < keep_out or (c, r) in blocked_cells:
            continue
        x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
        spawns.append(_spawn(0x80000000 | rng.pick(roster), (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
    # a companion to find: on the second area of every depth, in the ordinary room that fits who they
    # are (Hunter, 2026-10-22): the soldier holds the room nearest the locked door, the Order's
    # apprentice stopped nearest the maze entry (where what holds the dead is strongest), the bandit
    # hides in the room farthest from everything; ties go to the first room in order
    cid = companion_for(tp, area, met)
    if cid:
        rooms_for = [room for room in lay.rooms if room.kind == 'room' and abs(room.centre[0] - start.centre[0]) + abs(room.centre[1] - start.centre[1]) >= 6]
        if rooms_for:
            which = tp.companion_ids.index(cid)  # 0 Tobin, 1 Aldric, 2 Mira: the room that fits them
            if which == 1:
                target = outside
                room = min(rooms_for, key=lambda rm: abs(rm.centre[0] - target[0]) + abs(rm.centre[1] - target[1]))
            elif which == 2:
                target = exit_room.entry if exit_room.kind == 'maze' else exit_room.centre
                room = min(rooms_for, key=lambda rm: abs(rm.centre[0] - target[0]) + abs(rm.centre[1] - target[1]))
            else:
                room = max(rooms_for, key=lambda rm: abs(rm.centre[0] - start.centre[0]) + abs(rm.centre[1] - start.centre[1]))
            c, r = rng.pick(room.cells)
            x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
            spawns.append(_spawn(0x80000000 | cid, (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
            info['companion'] = cid
    people_chunk = struct.pack('<I', 1 + len(spawns)) + tp.people_db + b''.join(spawns)
    info.update(info_eggs)
    if copy_room is not None:  # where the backrooms send you back to
        info['copy_x'], info['copy_z'] = world(*copy_room.centre, w, h)
    if any(room.copy for room in lay.rooms):
        info['copy'] = 1
    info['archetype'] = ARCH_ORDER.index(arch_name)
    info['mutator'] = MUTATORS.index(mutator) + 1 if mutator in MUTATORS else 0
    lay.info = info
    env = bytearray(tp.chunks[TAG_ENV])
    scale = max(0.4, 1.0 - 0.15 * (depth - 1)) * (0.5 if mutator == 'dark' else 1.0)  # ambient light fades with depth (env block +0x30, three floats)
    struct.pack_into('<3f', env, 0x30, *(float(v) * scale for v in struct.unpack_from('<3f', env, 0x30)))
    payloads = {TAG_GRID: grid, TAG_NODES: node_chunk, TAG_OBJECTS: object_chunk, TAG_ITEMS: item_chunk, TAG_PEOPLE: people_chunk, TAG_ENV: bytes(env)}
    out = struct.pack('<I', MAGIC)
    for tag in (TAG_GRID, TAG_NODES, TAG_OBJECTS, TAG_ITEMS, TAG_PEOPLE, TAG_ENV):
        out += _chunk(tag, payloads[tag])
    lay.terrain = build_terrain(tp, lay, w, h) if tp.terrain_tile else b''
    return out, lay


def main() -> int:
    ap = argparse.ArgumentParser(description='Generate one Endless area from the template.')
    here = Path(__file__).resolve().parents[1] / 'out'
    ap.add_argument('--template', type=Path, default=here / 'endless-template.rfc')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--area', type=int, default=1)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--picture', action='store_true')
    a = ap.parse_args()
    tp = load_template(a.template.read_bytes(), a.template.with_suffix('.ini').read_text(encoding='ascii'))
    load_terrain_template(tp, a.template.with_suffix('.rft').read_bytes())
    data, lay = build_floor(tp, a.seed, a.area)
    back = level.parse(data)
    problems = decode_check(level.grid(back).layers, lay)
    if a.picture:
        print('\n'.join(lay.picture()))
    print(f'area {a.area} (depth {depth_of(a.area)}{", staircase" if is_staircase(a.area) else ""}) seed {a.seed} as {floor_name(a.area)}: '
          f'{len(data)} bytes, rooms {len(lay.rooms)}, doors {len(lay.doors)}, exit {lay.exit_room.kind}, '
          f'objects {len(back.objects)}, items {len(back.items)}, spawns {len(back.spawns)}, lights {len(level.lights(back))}, '
          f'problems {len(problems)}')
    for p in problems[:10]:
        print('  ', p)
    print(f'secret doors {len(lay.secrets)}, closets {len(lay.closets)}, maze gates {len(lay.maze_gates)}, terrain {len(lay.terrain)} bytes, tile sets {stage_of(tp, a.area)}')
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(data)
        a.out.with_suffix('.rft').write_bytes(lay.terrain)
        print('wrote', a.out, 'and its .rft')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
