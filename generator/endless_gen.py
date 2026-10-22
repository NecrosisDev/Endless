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
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools' / 'exanimate'))
from exanimate import level, rdb  # noqa: E402

CELL = 600.0
SIDE = [(0, -1), (-1, 0), (0, 1), (1, 0)]  # q -> (dx, dz): N, W, S, E
SIDE_YAW = [0.0, -90.0, -180.0, 90.0]  # a door facing side q (from shipped placements)
WALL, DOOR = 7, 0xB
BUILT = 0x80000
ROCK = 0xFFFF
TAG_MARKER = 0x8000AC07
TAG_NAME = 0x10000000
TAG_DOOR = 0x40000
TAG_CONTAINER = 0x20000
TAG_DEVICE = 0x10000
LEVER_Y = 145.0  # wall levers in exanima01 sit at 135..170 cm
MARKER_ARRIVAL, MARKER_EXIT, MARKER_ZONE = 0x1040, 0x1120, 0x1110
PROP_NAMES = ['barrel wdo1 a02', 'cratesmall a', 'cratesmall b', 'sack a', 'stool a', 'chair a', 'bucket wod a01', 'cratel4', 'coffin01', 'pot9', 'basket_wkr e']
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

    @property
    def cells(self):
        return [(c, r) for r in range(self.r0, self.r1 + 1) for c in range(self.c0, self.c1 + 1)]

    @property
    def centre(self):
        if self.kind == 'maze':
            return self.entry
        return ((self.c0 + self.c1) // 2, (self.r0 + self.r1) // 2)

    def contains(self, c: int, r: int) -> bool:
        return self.c0 <= c <= self.c1 and self.r0 <= r <= self.r1

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
    terrain: bytes = b''  # the .rft served with the level
    gate: tuple = ()  # ((boss cell), (exit cell)) of the gate the boss death opens, when a boss room exists

    CORRIDOR = 10_000

    def at(self, c: int, r: int) -> int:
        return self.owner[r * self.w + c] if 0 <= c < self.w and 0 <= r < self.h else -1

    def built(self, c: int, r: int) -> bool:
        return self.at(c, r) >= 0

    def is_door(self, a, b) -> bool:
        return (a, b) in self.doors or (b, a) in self.doors

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
    best = {}
    buckets = {0: [(a, -1, [a])]}
    cost = 0
    while cost < 4 * (w + h) and buckets:
        if cost not in buckets:
            cost += 1
            continue
        for cell, heading, path in buckets.pop(cost):
            if best.get((cell, heading), INF) < cost:
                continue
            if cell == b:
                return path
            for q, (dx, dz) in enumerate(SIDE):
                n = (cell[0] + dx, cell[1] + dz)
                if not (1 <= n[0] < w - 1 and 1 <= n[1] < h - 1):
                    continue
                if n != b and n in blocked:
                    continue
                c2 = cost + 1 + (3 if heading not in (-1, q) else 0)
                if best.get((n, q), INF) <= c2:
                    continue
                best[(n, q)] = c2
                buckets.setdefault(c2, []).append((n, q, path + [n]))
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


def generate_layout(rng: Rng, w: int, h: int, area: int, start_cell) -> Layout:
    """Rooms (2..5 cells a side) that never touch, a 3x3 start room around
    `start_cell`, the exit room farthest from it (a maze from depth 2), corridors
    along a nearest-neighbour spanning tree (the exit room only ever a leaf) plus a
    few loops, connectivity repaired by BFS, and exactly one doorway into the exit."""
    depth = depth_of(area)
    sc, sr = start_cell
    rooms = [Room(sc - 1, sr - 1, sc + 1, sr + 1, 'start')]
    wanted = min(8 + 2 * depth, 18)
    attempts = 0
    while len(rooms) < wanted and attempts < 600:
        attempts += 1
        hall = depth >= 2 and rng.chance(25)
        rw = rng.between(5, 7) if hall else rng.between(2, 5)
        rh = rng.between(5, 7) if hall else rng.between(2, 5)
        c0 = rng.between(2, w - 3 - rw)
        r0 = rng.between(2, h - 3 - rh)
        room = Room(c0, r0, c0 + rw - 1, r0 + rh - 1)
        if any(room.touches(o) for o in rooms):
            continue
        room.style = 0x11 if rng.chance(30) else 0
        rooms.append(room)
    start = rooms[0]
    far = max(range(1, len(rooms)), key=lambda i: abs(rooms[i].centre[0] - start.centre[0]) + abs(rooms[i].centre[1] - start.centre[1]))
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
    boss = None
    gate = None
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
        rooms.append(boss)
    boss_index = len(rooms) - 1 if boss is not None else -1
    owner = [-1] * (w * h)
    for i, room in enumerate(rooms):
        if room.kind == 'maze':
            continue
        for c, r in room.cells:
            owner[r * w + c] = i
    lay = Layout(w, h, owner, rooms)
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
    for _ in range(min(len(rooms) // 3, 4)):
        a, b = rng.below(len(rooms)), rng.below(len(rooms))
        if a != b and a != far and b != far and a != boss_index and b != boss_index and (a, b) not in edges and (b, a) not in edges:
            edges.append((a, b))
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
    _maze_gates(lay, rng, depth)
    _maze_bypass(lay)
    return lay


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
            if n in seen or not lay.built(*n) or side_kind(lay, c, r, q) == WALL or frozenset(((c, r), n)) in shut:
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
    if me == other:
        return 0
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
    if not lay.built(c, r):
        return ROCK, 0, 0
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
            if not a & BUILT:
                if a != ROCK:
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
        if len(boss_doors) != 2 or not lay.gate:
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
    reveal: list = field(default_factory=list)  # [(companion record id, [power ids])] granted at that companion's trust reveal
    bypass_gate_id: int = 0  # the companion bypass portcullis and its lever (0: no bypass)
    bypass_lever_id: int = 0
    companion_roles: list = field(default_factory=list)  # each companion's main role id (the dialogue's ActivateTopicN needs it)
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
    tp.reveal = [(int(e.split(':')[0]), [int(x) for x in e.split(':')[1].split(',') if x]) for e in keys.get('reveal_powers', '').split(';') if e]
    tp.bypass_gate_id, tp.bypass_lever_id = int(keys.get('bypass_gate', 0)), int(keys.get('bypass_lever', 0))
    tp.companion_roles = ints('companion_roles') if keys.get('companion_roles') else []
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


def _patch_script(item_db: bytes, area: int, seed: int) -> bytes:
    i = item_db.find(SCRIPT_PREFIX)
    if i < 0:
        raise ValueError('template has no EndlessNext script')
    text = b'LuaEvent(EndlessNext,%010u_%010u);' % (area, seed & 0xFFFFFFFF)
    end = item_db.index(b';', i) + 1
    if end - i != len(text):
        raise ValueError('script width changed')
    return item_db[:i] + text + item_db[end:]


def is_lever_area(area: int) -> bool:
    """From depth 3 every other area hides a lever that opens the door instead of a key."""
    return depth_of(area) >= 3 and area % 2 == 1


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
    """Endless and steady: +3 per depth and +2 per area inside a depth, no cap (the number of
    spawn cells is the only limit; a frame-rate guard belongs to the player's settings)."""
    depth = depth_of(area)
    return 4 + 3 * depth + 2 * ((area - 1) % AREAS_PER_DEPTH)


def boss_minion_count(area: int) -> int:
    """The boss room fills steadily too: one minion per depth from depth 2."""
    return max(depth_of(area) - 1, 0)


def boss_count(area: int) -> int:
    """A second boss from depth 6, a third from depth 12, and so on."""
    return 1 + depth_of(area) // 6


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
    return depth_of(area) >= 4 and not is_lever_area(area)


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


def build_floor(tp: Template, seed: int, area: int, *, w: int = 48, h: int = 48, present=None) -> tuple[bytes, Layout]:
    rng = Rng(seed, area)
    stage = stage_of(tp, area)
    two_sets = bool(stage) and len(stage[0]) >= 2 and len(stage[1]) >= 2
    start_cell = (int(START_X // CELL) + w // 2, int(START_Z // CELL) + h // 2)
    lay = generate_layout(rng, w, h, area, start_cell)
    if not two_sets:
        for room in lay.rooms:
            room.style = 0  # the pillared variant needs a second wall and floor set
    layers = encode_grid(lay)
    names = _names_block(stage[0]) + _names_block(stage[1]) if stage else tp.grid_names
    grid = names + struct.pack('<IIII', w, h, 0, 600) + b''.join(struct.pack(f'<{w * h}I', *L) for L in layers)
    exit_room = lay.exit_room
    staircase = is_staircase(area)
    pair = (area - 1) % len(tp.key_ids)
    # lights: rooms (the exit red, a staircase blue-white), every fourth corridor cell, maze nodes
    nodes = []
    for room in lay.rooms:
        if room.kind == 'maze':
            continue
        x, z = world(*room.centre, w, h)
        colour = ((0.3, 0.4, 0.6) if staircase else (0.5, 0.05, 0.05)) if room.kind == 'exit' else (0.45, 0.15, 0.5) if room.kind == 'boss' else (0.55, 0.38, 0.2)
        span = max(room.c1 - room.c0, room.r1 - room.r0)
        nodes.append(_light(tp, (x, LIGHT_Y, z), colour, 1.0, 2.0, float(900 + 250 * span)))
    for k, (c, r) in enumerate(lay.corridor_cells):
        if k % 4 == 1:
            x, z = world(c, r, w, h)
            nodes.append(_light(tp, (x, LIGHT_Y, z), (0.35, 0.25, 0.14), 0.7, 2.0, 800.0))
    for k, (c, r) in enumerate(lay.bypass_cells):
        if k % 4 == 1:
            x, z = world(c, r, w, h)
            nodes.append(_light(tp, (x, LIGHT_Y, z), (0.35, 0.25, 0.14), 0.7, 2.0, 800.0))
    if exit_room.kind == 'maze':
        k = 0
        for r in range(exit_room.r0, exit_room.r1 + 1, 2):
            for c in range(exit_room.c0, exit_room.c1 + 1, 2):
                if k % 2 == 0:
                    x, z = world(c, r, w, h)
                    colour = ((0.3, 0.4, 0.6) if staircase else (0.5, 0.05, 0.05)) if (c, r) == exit_room.goal else (0.3, 0.2, 0.1)
                    nodes.append(_light(tp, (x, LIGHT_Y, z), colour, 0.8, 2.0, 700.0))
                k += 1
    node_chunk = struct.pack('<I', len(nodes)) + b''.join(nodes)
    # props; the staircase decoration in the exit on staircase areas
    objects = []
    for room in lay.rooms:
        if room.kind in ('start', 'maze', 'boss', 'closet'):
            continue
        cells = room.cells
        edge_cells = [(c, r) for c, r in cells if c in (room.c0, room.c1) or r in (room.r0, room.r1)]
        count = rng.between(1, 2 + len(cells) // 2)
        for _ in range(count):
            c, r = rng.pick(edge_cells)
            name, raw = rng.pick(tp.props)
            fx = 0.2 if c == room.c0 else 0.8 if c == room.c1 else rng.unit() * 0.6 + 0.2
            fz = 0.2 if r == room.r0 else 0.8 if r == room.r1 else rng.unit() * 0.6 + 0.2
            x, z = world(c, r, w, h, fx, fz)
            objects.append(_object(raw, (x, tp.floor_y, z), rng.unit() * 360.0))
    # wall-mounted props on wall sides of ordinary rooms and corridors, floor debris in rooms
    if tp.wall_props:
        for room in lay.rooms:
            if room.kind in ('start', 'maze', 'boss', 'closet'):
                continue
            walls = [(c, r, q) for (c, r) in room.cells for q in range(4) if side_kind(lay, c, r, q) == WALL]
            for _ in range(rng.between(1, 1 + len(walls) // 4)):
                c, r, q = rng.pick(walls)
                name, raw = rng.pick(tp.wall_props)
                dist_, height, rel = WALL_PROPS[name]
                along = rng.unit() * 0.6 + 0.2
                fx = (0.5 + (0.5 - dist_) * SIDE[q][0]) if SIDE[q][0] else along
                fz = (0.5 + (0.5 - dist_) * SIDE[q][1]) if SIDE[q][1] else along
                x, z = world(c, r, w, h, fx, fz)
                objects.append(_object(raw, (x, height, z), SIDE_YAW[q] + rel))
        for k, (c, r) in enumerate(lay.corridor_cells):
            if k % 5 == 3:
                walls = [q for q in range(4) if side_kind(lay, c, r, q) == WALL]
                if walls:
                    q = rng.pick(walls)
                    name, raw = rng.pick(tp.wall_props)
                    dist_, height, rel = WALL_PROPS[name]
                    along = rng.unit() * 0.6 + 0.2
                    fx = (0.5 + (0.5 - dist_) * SIDE[q][0]) if SIDE[q][0] else along
                    fz = (0.5 + (0.5 - dist_) * SIDE[q][1]) if SIDE[q][1] else along
                    x, z = world(c, r, w, h, fx, fz)
                    objects.append(_object(raw, (x, height, z), SIDE_YAW[q] + rel))
    if tp.debris:
        for room in lay.rooms:
            if room.kind in ('start', 'maze', 'closet'):
                continue
            for _ in range(rng.between(0, 1 + len(room.cells) // 3)):
                c, r = rng.pick(room.cells)
                name, raw = rng.pick(tp.debris)
                x, z = world(c, r, w, h, rng.unit() * 0.8 + 0.1, rng.unit() * 0.8 + 0.1)
                objects.append(_object(raw, (x, DEBRIS[name], z), rng.unit() * 360.0))
    pillar_cells = _pillar_cells(lay.boss_room) if tp.pillar else []
    for c, r in pillar_cells:
        x, z = world(c, r, w, h)
        objects.append(_object(tp.pillar, (x, tp.floor_y, z), 0.0))
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
    objects_extra = []  # fire operatives are item placements too; listed after the markers
    plates = []  # plate decorations under push zones (objects, appended after the props)
    inside, outside = lay.exit_door
    q = SIDE.index((outside[0] - inside[0], outside[1] - inside[1]))
    dx, dz = world(*inside, w, h)
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
    by_distance = sorted(candidates, key=lambda room: abs(room.centre[0] - inside[0]) + abs(room.centre[1] - inside[1]))
    far_half = by_distance[len(by_distance) // 2 :]  # not always the farthest room: any of the farther half
    vaults = []
    if is_vault_area(area):
        vaults = [room for room in far_half if sum(1 for d in lay.doors if room.contains(*d[0]) or room.contains(*d[1])) == 1]
    key_room = rng.pick(vaults) if vaults else rng.pick(far_half)
    kc, kr = rng.pick(key_room.cells)
    lay.key_cell = (kc, kr)
    kx, kz = world(kc, kr, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
    if is_lever_area(area):
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
    if per_spot and not is_lever_area(area):
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
    for room in lay.rooms:
        if room.kind == 'room' and rng.chance(45):
            c, r = rng.pick(room.cells)
            x, z = world(c, r, w, h)
            places.append(_placement(tp.chest_place, 0x80000000 | rng.pick(chests), (x, tp.floor_y, z), rng.unit() * 360.0))
    item_chunk = _patch_script(tp.item_db, area, seed) + tp.item_strings + _chunk(TAG_ITEM_PLACES, struct.pack('<I', len(places)) + b''.join(places))
    objects += plates
    object_chunk = struct.pack('<I', len(objects)) + b''.join(objects)
    # people
    enemies = enemy_count(area)
    depth = depth_of(area)
    roster = enemy_roster(tp, depth)
    keep_out = 6 if depth == 1 else 4 if depth == 2 else 2  # cells from the start: no ambush on arrival
    spawns = []
    homes = [room for room in lay.rooms if room.kind not in ('start', 'exit', 'boss', 'closet')]
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
        for _ in range(boss_count(area) - 1):  # extra bosses deeper down; the gate waits for the first
            c, r = rng.pick(boss_cells)
            x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
            extra = rng.pick(bosses)
            spawns.append(_spawn(0x80000000 | extra, (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
            info['bosses'].append(extra)
        for _ in range(boss_minion_count(area)):
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
        if abs(c - start.centre[0]) + abs(r - start.centre[1]) < keep_out:
            continue
        x, z = world(c, r, w, h, rng.unit() * 0.6 + 0.2, rng.unit() * 0.6 + 0.2)
        spawns.append(_spawn(0x80000000 | rng.pick(roster), (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
    # a companion to find: on the second area of every depth, in the ordinary room that fits who they
    # are (Hunter, 2026-10-22): the soldier holds the room nearest the locked door, the Order's
    # apprentice stopped nearest the maze entry (where what holds the dead is strongest), the bandit
    # hides in the room farthest from everything; ties go to the first room in order
    if tp.companion_ids and (area - 1) % AREAS_PER_DEPTH == 1:
        rooms_for = [room for room in lay.rooms if room.kind == 'room' and abs(room.centre[0] - start.centre[0]) + abs(room.centre[1] - start.centre[1]) >= 6]
        if rooms_for:
            which = (depth_of(area) - 1) % len(tp.companion_ids)  # 0 Tobin (depth 1), 1 Aldric, 2 Mira
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
            cid = tp.companion_ids[(depth_of(area) - 1) % len(tp.companion_ids)]
            spawns.append(_spawn(0x80000000 | cid, (x, tp.floor_y, z), rng.unit() * 2 * math.pi))
            info['companion'] = cid
    people_chunk = struct.pack('<I', 1 + len(spawns)) + tp.people_db + b''.join(spawns)
    lay.info = info
    env = bytearray(tp.chunks[TAG_ENV])
    scale = max(0.4, 1.0 - 0.15 * (depth - 1))  # ambient light fades with depth (env block +0x30, three floats)
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
