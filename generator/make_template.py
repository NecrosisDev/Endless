"""Build the Endless floor template (endless-template.rfc + endless-template.ini)
from the installed game's exanima01.rfc (read from Resource.rpk, which is what the
game itself reads; hm_files is only the Hellmode installer's source folder).

The template is exanima01 with:
- its placed objects reduced to one of each prop the generator uses (in a fixed
  order), its loose items reduced to one marker placement and one chest placement
  (both only cloned), its NPC spawns removed, its scene nodes reduced to one light;
- two marker records appended to the level-local item database: an arrival marker
  'Endless' and a zone 'EndlessNext' whose script is fixed-width
  'EndlessNext(0000000001,0000000001);' so a floor can patch the digits in place;
- its level-local item database (chest contents are drop lists), strings and
  character database kept verbatim.

Both the Python reference generator and the native port only do byte-level
surgery on this file, so they can be compared byte for byte.
"""
from __future__ import annotations

import argparse
import struct
import math
import os
import sys
from pathlib import Path

# the exanimate format library: EXANIMATE_TOOLS, else the Exanimate workspace this repo was split from
_TOOLS = os.environ.get('EXANIMATE_TOOLS') or str(Path(__file__).resolve().parents[3] / 'tools' / 'exanimate')
sys.path.insert(0, _TOOLS)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_companions as mc  # noqa: E402
from exanimate import level, rdb, rpk, actor  # noqa: E402
import endless_gen as eg  # noqa: E402

SCRIPT = b'LuaEvent(EndlessNext,0000000001_0000000001);'
PAIRS = 4  # key/door/cache record triples; area n uses triple n % PAIRS
CLOSETS = 3  # monster closets per area at most
MAZE_GATES = 3  # gates across the maze path at most
FIRES = 5  # fire trap slots per area (each its own operative record and zone, so the mod can drive one)


def build(game: Path) -> tuple[bytes, str]:
    data = rpk.read(game / 'Resource.rpk', 'exanima01.rfc')
    # the template carries whatever the installed archive holds: on a Hellmode install that is
    # Hellmode's levels, enemies, loot lists and wall sets (its members are named hm*/gews_hm*)
    members = {m.name.lower() for m in rpk.members(game / 'Resource.rpk', nested=False)}
    flavour = 'hellmode' if any(n.startswith('gews_hm') for n in members) else 'vanilla'
    lv = level.parse(data)
    # markers and chests
    db = level._local_db(lv)
    markers = {}
    for r in db.records:
        for t, p, s in r.chunks():
            if t == eg.TAG_MARKER:
                flags = struct.unpack_from('<I', r.data, p + 8 + 8)[0]
                markers.setdefault(flags & 0xFFFF, r)
    chests = [c for c in level.containers(lv) if c['contents']]
    chest_ids = sorted({c['record'] for c in chests})
    chest_place = next(p for p in lv.items if p.item == 0x80000000 | chests[0]['record'])
    marker_place = next(p for p in lv.items if p.item == 0x80000000 | markers[eg.MARKER_EXIT].id)
    next_id = max(r.id for r in db.records) + 1
    next_id_box = [next_id + 2]  # ids after the arrival and zone markers
    arrival = eg._marker_record(markers[eg.MARKER_ARRIVAL], next_id, 'Endless', (50, 50, 50), eg.MARKER_ARRIVAL, 0, 0, 0)
    zone = eg._marker_record(markers[eg.MARKER_ZONE], next_id + 1, 'EndlessNext', (300, 150, 300), eg.MARKER_ZONE, 0, 0, 0, SCRIPT)
    # chest tiers: chests of deeper levels imported with their local drop lists (ids remapped,
    # display strings cleared because they would index another level's string table)
    chest_tiers = [chest_ids]
    for sources in (('exanima02',), ('exanima03',), ('exanima04', 'exanima05_sw'), ('exanima07',), ('exanima06', 'exanima08')):
        tier = []
        for other in sources:
            olv = level.parse(rpk.read(game / 'Resource.rpk', f'{other}.rfc'))
            odb = level._local_db(olv)
            if odb is None:
                continue
            oby = {r.id: r for r in odb.records}
            taken = 0
            for c in level.containers(olv):
                if not c['contents'] or c['record'] in (x for x in ()) or taken >= 12:
                    continue
                new_id = eg.import_record(oby, c['record'], db, next_id_box)
                if new_id:
                    tier.append(new_id)
                    taken += 1
        chest_tiers.append(tier)
    # the healing salve (exanima03's record, with what it references), for quiet rooms and stores
    salve_id = 0
    olv = level.parse(rpk.read(game / 'Resource.rpk', 'exanima03.rfc'))
    odb = level._local_db(olv)
    if odb is not None:
        src = next((r for r in odb.records if r.name == 'Healing Salve'), None)
        if src is not None:
            salve_id = eg.import_record({r.id: r for r in odb.records}, src.id, db, next_id_box)
    next_id = next_id_box[0]
    # key / locked door pairs and a chest that holds each key (ids cycle per area)
    key_src = next(r for r in db.records if r.name == 'Key A02')
    door_src = next(r for r in db.records if r.name == 'Door UW01A' and any(t == 0x40000 for t, _, _ in r.chunks()))
    chest_src = next(r for r in db.records if r.id == chests[0]['record'])
    door_place = next(p for p in lv.items if p.item == 0x80000000 | door_src.id)
    by_id = {r.id: r for r in db.records}
    key_place = next(p for p in lv.items if p.item & 0x80000000 and (p.item & 0x7FFFFFFF) in by_id and 'key' in by_id[p.item & 0x7FFFFFFF].name.lower())
    keys, doors, key_chests = [], [], []
    nid = next_id
    for k in range(PAIRS):
        key = rdb.Record(nid, key_src.flags, 0, len(key_src.data), eg._set_name16(key_src.data, f'Endless Key {k + 1}'))
        door = rdb.Record(nid + 1, door_src.flags, 0, 0, b'')
        door.data = eg._set_door_opener(eg._set_name16(door_src.data, f'Endless Door {k + 1}'), 0x80000000 | key.id)
        door.size = len(door.data)
        chest = rdb.Record(nid + 2, chest_src.flags, 0, 0, b'')
        chest.data = eg._set_container_rows(eg._set_name16(chest_src.data, f'Endless Cache {k + 1}'), [0x80000000 | key.id, 0x80000000 | chests[0]['contents'][0]['item'] & 0xFFFFFFFF])
        chest.size = len(chest.data)
        keys.append(key); doors.append(door); key_chests.append(chest)
        nid += 3
    # traps and puzzles: one fire operative record, one lever per pair (its device target is that
    # pair's door, so pulling it opens the door instead of the key), and hazard zones whose ZoneID
    # tells the mod the trap kind (1 fire; 2..5 push toward N/W/S/E)
    fire_src = next(r for r in db.records if r.name == 'Fire_Oprtv')
    lever_src = next(r for r in db.records if r.name == 'Lever A01')
    fire_place = next(p for p in lv.items if p.item == 0x80000000 | fire_src.id)
    lever_place = next(p for p in lv.items if p.item == 0x80000000 | lever_src.id)
    fires = []
    for k in range(FIRES):
        fires.append(rdb.Record(nid, fire_src.flags, 0, len(fire_src.data), eg._set_name16(fire_src.data, f'Endless Fire {k + 1}')))
        nid += 1
    levers = []
    for k in range(PAIRS):
        lever = rdb.Record(nid, lever_src.flags, 0, 0, b'')
        lever.data = eg._set_device_target(eg._set_name16(lever_src.data, f'Endless Lever {k + 1}'), 0x80000000 | doors[k].id)
        lever.size = len(lever.data)
        levers.append(lever)
        nid += 1
    hazards = []  # zone ids: 2..5 push toward N/W/S/E, 11..15 fire slot 1..5
    for kind, name, box in ((2, 'Endless Push N', (300, 150, 300)), (3, 'Endless Push W', (300, 150, 300)), (4, 'Endless Push S', (300, 150, 300)), (5, 'Endless Push E', (300, 150, 300))):
        hazards.append(eg._marker_record(markers[eg.MARKER_ZONE], nid, name, box, eg.MARKER_ZONE, kind, 0, 0, b'LuaEvent(EndlessTrap,%d);' % kind))
        nid += 1
    # talk zones: when a companion walks through one, its script opens that companion's node
    # (ActivateTopicN runs only for an actor holding the role, so the player passing is a no-op);
    # one record per spot per companion, spot-major; the generator places all three at a spot
    talk_zones = []
    roles_ini = (Path(__file__).resolve().parents[1] / 'out' / 'companions' / 'roles.ini').read_text(encoding='utf-8')
    # one voice per occasion (Hunter, 2026-10-22): one record per spot per companion, spot-major in
    # companion order; the generator places one of them per spot, the first in the spot's order
    # (ini spot_order) who is in the party; that one's line opens the exchange with the next
    main_roles = [int(x) for x in next(l for l in roles_ini.splitlines() if l.startswith('main_roles=')).split('=', 1)[1].split(',')]
    for spot_index, spot in enumerate(eg.TALK_SPOTS):
        for role in main_roles:
            script = b'Actor.ActivateTopicN(%d, 7, %s, 1);' % (role, spot.encode('latin-1'))
            talk_zones.append(eg._marker_record(markers[eg.MARKER_ZONE], nid, f'Endless Talk {spot_index}{role}', eg.TALK_ZONE_BOX.get(spot, (300, 150, 300)), eg.MARKER_ZONE, eg.TALK_ZONE_FIRST + spot_index, 0, 0, script))
            nid += 1
    pair_zones = []  # retired: the hops are opened by the speaker's line, not by a zone (the ini key stays, empty)
    # the backrooms trigger (Hunter, 2026-10-22): a small zone in the corner of the perfect copy
    wall_zone = eg._marker_record(markers[eg.MARKER_ZONE], nid, 'Endless Wall', (90, 150, 90), eg.MARKER_ZONE, 40, 0, 0, b'LuaEvent(EndlessWall,1);')
    nid += 1
    fire_zones = []
    for k in range(FIRES):
        fire_zones.append(eg._marker_record(markers[eg.MARKER_ZONE], nid, f'Endless Fire Z{k + 1}', (250, 150, 250), eg.MARKER_ZONE, 11 + k, 0, 0, b'LuaEvent(EndlessTrap,%d);' % (11 + k)))
        nid += 1
    # the gate between the boss room and the exit: a door whose opener is its own lever (as the
    # shipped portcullises do), the lever placed behind the gate and pulled by the mod on boss death
    gate_src = next(r for r in db.records if r.name == 'PortCullis UWA' and any(t == 0x40000 for t, _, _ in r.chunks()))
    gate_place = next(p for p in lv.items if p.item == 0x80000000 | gate_src.id)
    gates, gate_levers = [], []
    for k in range(PAIRS):
        gate = rdb.Record(nid, gate_src.flags, 0, 0, b'')
        lever = rdb.Record(nid + 1, lever_src.flags, 0, 0, b'')
        gate.data = eg._set_door_opener(eg._set_name16(gate_src.data, f'Endless Gate {k + 1}'), 0x80000000 | lever.id)
        gate.size = len(gate.data)
        lever.data = eg._set_device_target(eg._set_name16(lever_src.data, f'Endless GateLvr {k + 1}'), 0x80000000 | gate.id)
        lever.size = len(lever.data)
        gates.append(gate); gate_levers.append(lever)
        nid += 2
    # secret passages (records from exanima02: a wall-looking door and the brick switch that opens it),
    # floor plates (exanima05's contact button with the pressure-plate model) for fire traps and
    # monster closets (portcullis clones opened by a plate)
    lv2 = level.parse(rpk.read(game / 'Resource.rpk', 'exanima02.rfc')); db2 = level._local_db(lv2)
    sdoor_src = next(r for r in db2.records if r.name == 'Door Secret UW01')
    switch_src = next(r for r in db2.records if r.name == 'Secret Swt Brk')
    secret_door_place = next(p for p in lv2.items if p.item == 0x80000000 | sdoor_src.id)
    switch_place = next(p for p in lv2.items if p.item == 0x80000000 | switch_src.id)
    lv5 = level.parse(rpk.read(game / 'Resource.rpk', 'exanima05.rfc')); db5 = level._local_db(lv5)
    plate_src = next(r for r in db5.records if r.name == 'Button UB6 Scrt')
    plate_place = next(p for p in lv5.items if p.item == 0x80000000 | plate_src.id)
    secret_doors, switches = [], []
    for k in range(2 * PAIRS):
        sd = rdb.Record(nid, sdoor_src.flags, 0, 0, b'')
        sw = rdb.Record(nid + 1, switch_src.flags, 0, 0, b'')
        sd.data = eg._set_door_opener(eg._set_name16(sdoor_src.data, f'Endless Secret {k + 1}'), 0x80000000 | sw.id)
        sd.size = len(sd.data)
        sw.data = eg._set_device_target(eg._set_name16(switch_src.data, f'Endless Brick {k + 1}'), 0x80000000 | sd.id)
        sw.size = len(sw.data)
        secret_doors.append(sd); switches.append(sw)
        nid += 2
    plate_fires = []
    for k in range(FIRES):
        pl = rdb.Record(nid, plate_src.flags, 0, 0, b'')
        pl.data = eg._set_device_target(eg._set_look_model(eg._set_name16(plate_src.data, f'Endless Plate F{k + 1}'), 'pressplateuwa1'), 0x80000000 | fires[k].id)
        pl.size = len(pl.data)
        plate_fires.append(pl)
        nid += 1
    closet_gates, plate_closets = [], []
    for k in range(CLOSETS):
        cg = rdb.Record(nid, gate_src.flags, 0, 0, b'')
        pl = rdb.Record(nid + 1, plate_src.flags, 0, 0, b'')
        cg.data = eg._set_door_opener(eg._set_name16(gate_src.data, f'Endless Closet {k + 1}'), 0x80000000 | pl.id)
        cg.size = len(cg.data)
        pl.data = eg._set_device_target(eg._set_look_model(eg._set_name16(plate_src.data, f'Endless Plate C{k + 1}'), 'pressplateuwa1'), 0x80000000 | cg.id)
        pl.size = len(pl.data)
        closet_gates.append(cg); plate_closets.append(pl)
        nid += 2
    # the companion bypass: a corridor round the maze shut by a portcullis at the goal end, opened by
    # a lever in the goal cell (the player opens it after solving; the party walks round)
    bypass_gate = rdb.Record(nid, gate_src.flags, 0, 0, b'')
    bypass_lever = rdb.Record(nid + 1, lever_src.flags, 0, 0, b'')
    bypass_gate.data = eg._set_door_opener(eg._set_name16(gate_src.data, 'Endless Bypass'), 0x80000000 | bypass_lever.id)
    bypass_gate.size = len(bypass_gate.data)
    bypass_lever.data = eg._set_device_target(eg._set_name16(lever_src.data, 'Endless BypassLvr'), 0x80000000 | bypass_gate.id)
    bypass_lever.size = len(bypass_lever.data)
    nid += 2
    # maze gate puzzle: portcullises across the maze path, each opened by a lever hidden in a dead end before it
    maze_gates, maze_levers = [], []
    for k in range(MAZE_GATES):
        mg = rdb.Record(nid, gate_src.flags, 0, 0, b'')
        ml = rdb.Record(nid + 1, lever_src.flags, 0, 0, b'')
        mg.data = eg._set_door_opener(eg._set_name16(gate_src.data, f'Endless MazeGate {k + 1}'), 0x80000000 | ml.id)
        mg.size = len(mg.data)
        ml.data = eg._set_device_target(eg._set_name16(lever_src.data, f'Endless MazeLvr {k + 1}'), 0x80000000 | mg.id)
        ml.size = len(ml.data)
        maze_gates.append(mg); maze_levers.append(ml)
        nid += 2
    db.records += [arrival, zone, wall_zone] + keys + doors + key_chests + fires + levers + hazards + fire_zones + talk_zones + pair_zones + gates + gate_levers + secret_doors + switches + plate_fires + closet_gates + plate_closets + maze_gates + maze_levers + [bypass_gate, bypass_lever]
    level._set_local_db(lv, db)
    # objects: one per prop, generator order
    props = {}
    ys = []
    for o in lv.objects:
        if o.name in eg.PROP_NAMES and o.name not in props:
            props[o.name] = o
        if o.name == 'barrel wdo1 a02':
            ys.append(o.pos[1])
    for other in ('exanima02', 'exanima03', 'exanima04', 'exanima05', 'exanima06', 'exanima07', 'exanima08'):
        if all(n in props for n in eg.PROP_NAMES):
            break
        try:
            olv = level.parse(rpk.read(game / 'Resource.rpk', f'{other}.rfc'))
        except Exception:
            continue
        for o in olv.objects:
            if o.name in eg.PROP_NAMES and o.name not in props:
                props[o.name] = o
    names = [n for n in eg.PROP_NAMES if n in props]
    lv.objects = [props[n] for n in names]
    # the staircase decoration (an ordinary Objlib member, flags 0, standard child chunk): one entry
    # cloned from a prop with the name replaced; it is listed after the props and not in `props`
    stairs = level.Placed('object', eg.STAIRS_NAME, 0, [1, 0, 0, 0, 1, 0, 0, 0, 1], [0.0, 0.0, 0.0], props[names[0]].head, props[names[0]].rest, props[names[0]].tag)
    lv.objects.append(stairs)
    plate = level.Placed('object', eg.PLATE_NAME, 0, [1, 0, 0, 0, 1, 0, 0, 0, 1], [0.0, 0.0, 0.0], props[names[0]].head, props[names[0]].rest, props[names[0]].tag)
    lv.objects.append(plate)
    # wall-mounted props and floor debris: one entry each, from the source level's own placements
    extra = {}
    for o in level.parse(rpk.read(game / 'Resource.rpk', 'exanima01.rfc')).objects:
        if (o.name in eg.WALL_PROPS or o.name in eg.DEBRIS) and o.name not in extra:
            extra[o.name] = o
    wall_names = [n for n in eg.WALL_PROPS if n in extra]
    debris_names = [n for n in eg.DEBRIS if n in extra]
    for n in wall_names + debris_names:
        lv.objects.append(extra[n])
    # the boss-room pillar (level 1's freestanding column), one entry after the debris
    pillar = next((o for o in level.parse(rpk.read(game / 'Resource.rpk', 'exanima01.rfc')).objects if o.name == eg.PILLAR_NAME), None)
    if pillar is not None:
        lv.objects.append(pillar)
    lv.items = [marker_place, chest_place, door_place, key_place, fire_place, lever_place, gate_place, secret_door_place, switch_place, plate_place]
    # one light
    nodes = level._scene_nodes(lv)
    light = next(n for n in nodes if n.kind == 0x3D06 and n.light)
    light.index, light.parent, light.link = 1, 0, 0
    level._set_scene_nodes(lv, [light])
    # enemies
    cdb = level.characters(lv)
    enemies = [rec.id for rec in cdb.records if any(k in actor.parse(rec.data).name for k in ('Zombie', 'Skeleton', 'Sticky', 'Skel'))]
    # tougher rosters for deeper floors: hostile records of exanima02 and exanima03 appended with new ids
    # (actor records are self-contained; they spawn through this level's own list, so level id 0 is fine)
    # enemy tiers by depth (all hostile by their roles: knights carry "Human Hater"; the rest are
    # the shipped monsters) and boss tiers; records are self-contained actor files appended with new ids
    BANDS = 3  # extra strength bands per record (make_template and the generators agree)
    TIERS = [
        # (source level, enemy name parts (lower-case), boss name parts (exact case))
        [('exanima01', (), ('RedKnight', 'Sir92', 'Warden'))],
        [('exanima02', ('zombie', 'skel', 'sticky', 'ghoul'), ('DarkKnight', 'BigLord'))],
        [('exanima03', ('zombie', 'skel', 'sticky', 'ghoul'), ('GhostKnight', 'Proctor', 'BnicentKnight'))],
        [('exanima04', ('ghoulg', 'poorskelly', 'emberknight', 'skeleton_start'), ('EmberBoss', 'Sir')),
         ('exanima05_sw', ('ghoul', 'gobbler', 'fael'), ())],
        [('exanima07', ('ghoul', 'gobbler', 'fael', 'livingarmour', 'manipulator', 'deadskel'), ('GhostKnight',)),
         ('exanima07_sw', (), ('Blademaster',))],
        [('exanima06', ('golem', 'skeleton ub'), ('GolemBoss',)),
         ('exanima08', ('skeleton',), ()),
         ('exanima67', ('golem', 'skeleton', 'harvester'), ('GdnShaperD',)),
         ('exanimac1', ('shdwskel', 'possskel', 'skel'), ('BncientBoss', 'Shdwboss')),
         ('exanima04', ('sir',), ())],  # the Archives' giant beast ("Sir", look ML01) roams at the deepest tier too
    ]
    tiers = [enemies]
    bosses = [[rec.id for rec in cdb.records if any(k in actor.parse(rec.data).name for k in TIERS[0][0][2])]]
    nid = max(r.id for r in cdb.records) + 1
    for sources in TIERS[1:]:
        tier, boss_tier = [], []
        for other, enemy_parts, boss_parts in sources:
            odb = level.characters(level.parse(rpk.read(game / 'Resource.rpk', f'{other}.rfc')))
            for rec in odb.records:
                name = actor.parse(rec.data).name
                is_boss = any(name.startswith(k) for k in boss_parts)
                is_enemy = any(k in name.lower() for k in enemy_parts) and 'boss' not in name.lower()
                if is_boss or is_enemy:
                    cdb.records.append(rdb.Record(nid, rec.flags, 0, len(rec.data), rec.data))
                    (boss_tier if is_boss else tier).append(nid)
                    nid += 1
        tiers.append(tier)
        bosses.append(boss_tier)
    # strength bands: every boss and enemy record in BANDS extra strengths (skills x1.2 / x1.4 / x1.6
    # capped at 30000, AI skill +15 / +30 / +45 capped at 150); band k is used from depth 6k+1, so
    # the difficulty keeps rising after the last tier has joined (all tiers are in by depth 6)
    def banded(tier: list) -> list:
        nonlocal nid
        bands = [list(tier)]
        for k in range(1, BANDS + 1):
            band = []
            for rid in tier:
                src = next(r for r in cdb.records if r.id == rid)
                act = actor.parse(src.data)
                for sk in act.skills:
                    sk.value = min(int(sk.value * (1 + 0.2 * k)), 30000)
                act.ai_skill = min(act.ai_skill + 15 * k, 150.0)
                data = actor.pack(act)
                cdb.records.append(rdb.Record(nid, src.flags, 0, len(data), data))
                band.append(nid)
                nid += 1
            bands.append(band)
        return bands
    boss_bands = [banded(tier) for tier in bosses]
    enemy_bands = [banded(tier) for tier in tiers]
    # the dead each companion recognises: that record gets the companion's "known" role (make_companions.py)
    known_line = next((l for l in roles_ini.splitlines() if l.startswith('known_roles=')), '')
    for entry in known_line.split('=', 1)[1].split(';') if known_line else []:
        rec_name, role_id = entry.split(',')
        hits = [r for r in cdb.records if actor.parse(r.data).name == rec_name]  # the base record and its strength bands
        if not hits:
            raise SystemExit(f'known dead record {rec_name!r} is not in the merged roster')
        for rec in hits:
            act = actor.parse(rec.data)
            _, held, _ = mc.roles_of(act.rest)
            act.rest = mc.with_roles(act.rest, held + [int(role_id)])
            rec.data = actor.pack(act)
            rec.size = len(rec.data)
    # companions (made by make_companions.py): friendly humans with their own meet role
    companions = []
    # in the order they are found (mc.COMPANIONS: Tobin, Aldric, Mira), which the ini's companions=, the
    # generators' companion index, main.lua's TOBIN/ALDRIC/MIRA and roles.ini's reveal_powers indices all
    # read; sorting the file names gave Aldric, Mira, Tobin (fixed 2026-10-22)
    for f in [(Path(__file__).resolve().parents[1] / 'out' / 'companions' / f'{name}.actor') for name in mc.COMPANIONS]:
        cdb.records.append(rdb.Record(nid, 0, 0, len(f.read_bytes()), f.read_bytes()))
        companions.append(nid)
        nid += 1
    # boss-lock puzzles (Hunter, 2026-10-22: weight plate, lever order, timed gate, hold the door), after the
    # companions so their ids stay put: a portcullis for the boss doorway opened by its own floor plate, and
    # four levers wired to a dummy portcullis (placed out of sight) whose positions the mod reads; the mod
    # drives the puzzle portcullis for the lever puzzles
    puzzle_gate = rdb.Record(nid, gate_src.flags, 0, 0, b'')
    puzzle_plate = rdb.Record(nid + 1, plate_src.flags, 0, 0, b'')
    puzzle_dummy = rdb.Record(nid + 2, gate_src.flags, 0, 0, b'')
    puzzle_gate.data = eg._set_door_opener(eg._set_name16(gate_src.data, 'Endless PuzzleGate'), 0x80000000 | puzzle_plate.id)
    puzzle_gate.size = len(puzzle_gate.data)
    puzzle_plate.data = eg._set_device_target(eg._set_look_model(eg._set_name16(plate_src.data, 'Endless PuzzlePlate'), 'pressplateuwa1'), 0x80000000 | puzzle_gate.id)
    puzzle_plate.size = len(puzzle_plate.data)
    nid += 3
    puzzle_levers = []
    for k in range(4):
        pl = rdb.Record(nid, lever_src.flags, 0, 0, b'')
        pl.data = eg._set_device_target(eg._set_name16(lever_src.data, f'Endless PuzzleLvr {k + 1}'), 0x80000000 | puzzle_dummy.id)
        pl.size = len(pl.data)
        puzzle_levers.append(pl)
        nid += 1
    puzzle_dummy.data = eg._set_door_opener(eg._set_name16(gate_src.data, 'Endless PuzzleDummy'), 0x80000000 | puzzle_levers[0].id)
    puzzle_dummy.size = len(puzzle_dummy.data)
    db.records += [puzzle_gate, puzzle_plate, puzzle_dummy] + puzzle_levers
    level._set_local_db(lv, db)
    level.set_characters(lv, cdb)
    lv.spawns = []
    lv.people_order = ['db']
    lv.people_tail = b''
    spawn_ys = sorted(sp.pos[1] for sp in level.parse(rpk.read(game / 'Resource.rpk', 'exanima01.rfc')).spawns)
    floor_y = spawn_ys[len(spawn_ys) // 2]  # NPC feet height in the source level; props and spawns use it
    # tile-set stages by depth: shipped wall/floor pairings (and Hellmode's own deep brick set when
    # the archive has it); only sets the archive really holds are written, so a vanilla install
    # gets the vanilla list. The grid encoding is the same for every complete set (WC/WD/WL/WR + corners).
    stages = [
        (('GEWS_UWA01', 'GEWS_UwA01p'), ('GEFS_UWA01', 'GEFS_UWA01T')),      # catacombs (levels 1-3)
        (('GEWS_UWB03', 'GEWS_UWB02'), ('GEFS_UWB03', 'GEFS_UWB02')),        # the lower halls (level 4)
        (('GEWS_USA01',), ('GEFS_UB06B1',)),                                 # sewers
        (('GEWS_UBB01', 'GEWS_UBB01PA'), ('GEFS_UB06A1', 'GEFS_UB06B1')),    # deep brick (level 5)
        (('GEWS_UBMAT01', 'GEWS_UBMA01'), ('GEFS_UWB01C', 'GEFS_UWB02')),    # the mines (level 6)
        (('GEWS_hmUBB01', 'GEWS_UBB02PA'), ('GEFS_UB06B1',)),                # Hellmode's deep brick (level 7)
        (('GEWS_UBB02', 'GEWS_UBB02PA'), ('GEFS_UB06B1', 'GEFS_UB06A1')),    # the deepest brick (level 8)
    ]
    # the shipped levels each stage's stone comes from: a prop is placed on a stage only where one
    # of those levels places it (Hunter's theme rule: nothing vanilla does not pair with the stone)
    stage_sources = [('exanima01', 'exanima02', 'exanima03'), ('exanima04',), ('exanima05_sw',), ('exanima05',),
                     ('exanima06',), ('exanima07', 'exanima07_sw'), ('exanima08',)]
    lower_members = {n.lower() for n in members}
    stage_lines = []
    written_sources = []
    for (walls, floors), sources in zip(stages, stage_sources):
        if all(f'{n.lower()}.rfc' in lower_members for n in walls + floors):
            stage_lines.append(f'stage{len(stage_lines) + 1}={",".join(walls)}|{",".join(floors)}')
            written_sources.append(sources)
    placed_by = {}
    for k, sources in enumerate(written_sources, 1):
        for src_name in sources:
            if f'{src_name}.rfc'.lower() not in lower_members:
                continue
            for o in level.parse(rpk.read(game / 'Resource.rpk', f'{src_name}.rfc')).objects:
                placed_by.setdefault(o.name, set()).add(k)
    themed = list(eg.PROP_NAMES) + list(eg.WALL_PROPS) + list(eg.DEBRIS) + [eg.PILLAR_NAME]
    DRESS_OUT['blob'] = build_dress(game, lower_members, written_sources, db)
    level._set_local_db(lv, db)  # the loose items build_dress imported
    prop_stage_line = 'prop_stages=' + ';'.join(f'{n}:' + ','.join(str(k) for k in sorted(placed_by.get(n, ()))) for n in themed)
    ini = '\n'.join([
        '[template]',
        *stage_lines,
        f'source=exanima01.rfc (installed Resource.rpk, {flavour})',
        f'arrival={arrival.id}',
        f'zone={zone.id}',
        f'chests={",".join(map(str, chest_ids))}',
        *[f'chests_t{i + 1}={",".join(map(str, chest_tiers[i]))}' for i in range(1, len(chest_tiers))],
        f'keys={",".join(str(r.id) for r in keys)}',
        f'doors={",".join(str(r.id) for r in doors)}',
        f'key_chests={",".join(str(r.id) for r in key_chests)}',
        f'fires={",".join(str(r.id) for r in fires)}',
        f'fire_zones={",".join(str(r.id) for r in fire_zones)}',
        f'talk_zones={",".join(str(r.id) for r in talk_zones)}',
        f'wall_zone={wall_zone.id}',
        f'pair_zones={",".join(str(r.id) for r in pair_zones)}',
        f'levers={",".join(str(r.id) for r in levers)}',
        f'hazards={",".join(str(r.id) for r in hazards)}',
        f'gates={",".join(str(r.id) for r in gates)}',
        f'secret_doors={",".join(str(r.id) for r in secret_doors)}',
        f'switches={",".join(str(r.id) for r in switches)}',
        f'plate_fires={",".join(str(r.id) for r in plate_fires)}',
        f'plate_closets={",".join(str(r.id) for r in plate_closets)}',
        f'closet_gates={",".join(str(r.id) for r in closet_gates)}',
        f'maze_gates={",".join(str(r.id) for r in maze_gates)}',
        f'maze_levers={",".join(str(r.id) for r in maze_levers)}',
        f'bypass_gate={bypass_gate.id}',
        f'bypass_lever={bypass_lever.id}',
        f'puzzle_gate={puzzle_gate.id}',
        f'puzzle_plate={puzzle_plate.id}',
        f'puzzle_dummy={puzzle_dummy.id}',
        f'puzzle_levers={",".join(str(r.id) for r in puzzle_levers)}',
        f'gate_levers={",".join(str(r.id) for r in gate_levers)}',
        *[f'bosses_t{i + 1}={",".join(map(str, bosses[i]))}' for i in range(len(bosses))],
        *[f'bosses_t{i + 1}_b{k}={",".join(map(str, boss_bands[i][k]))}' for i in range(len(bosses)) for k in range(1, BANDS + 1)],
        *[f'enemies_t{i + 1}_b{k}={",".join(map(str, enemy_bands[i][k]))}' for i in range(len(tiers)) for k in range(1, BANDS + 1)],
        f'companions={",".join(map(str, companions))}',
        'companion_roles=' + ','.join(map(str, main_roles)),
        f'salve={salve_id}',
        prop_stage_line,
        'spot_order=' + next((l for l in roles_ini.splitlines() if l.startswith('spot_order=')), 'spot_order=').split('=', 1)[1],
        f'proctor_boss={next((r.id for r in cdb.records if actor.parse(r.data).name == "Proctor15"), 0)}',
        # the Archives' demon, Sir (Hunter, 2026-10-22: one roams the backrooms); its first, full-strength record
        f'sir_demon={next((r.id for r in cdb.records if actor.parse(r.data).name == "Sir36"), 0)}',
        'reveal_powers=' + ';'.join(f'{companions[int(e.split(":")[0])]}:{e.split(":")[1]}' for e in next((l for l in roles_ini.splitlines() if l.startswith('reveal_powers=')), 'reveal_powers=').split('=', 1)[1].split(';') if e),
        f'enemies={",".join(map(str, enemies))}',
        *[f'enemies_t{i + 1}={",".join(map(str, tiers[i]))}' for i in range(1, len(tiers))],
        f'props={";".join(names)}',
        f'wall_props={";".join(wall_names)}',
        f'debris={";".join(debris_names)}',
        f'pillar={eg.PILLAR_NAME if pillar is not None else ""}',
        f'floor_y={floor_y!r}',
        '',
    ])
    return level.pack(lv), ini


DRESS_OUT = {}
DRESS_CAP = 80  # cell dressings kept per stage and class (the corridor and fallback pools)
DRESS_SKIP = ('stair', 'door', 'portcul', 'cavebld', 'lever', 'chest', 'trunk', 'bridge', 'brdg', 'uwportal')
# loose items a room keeps (cups, books, candles...): item records by name, imported into the template
# (no books, parchments or scrolls: nothing readable down here, and some teach skills; Hunter's lore rule)
CLUTTER = ('cup', 'mug', 'bowl', 'plate', 'jug', 'bottle', 'flask', 'candle',
           'inkpot', 'tray', 'spoon', 'brush', 'calipers', 'chisel', 'vase', 'goblet', 'tankard', 'pitcher')
CLUTTER_NOT = ('chest', 'shelf', 'case', 'lever', 'door', 'key', 'book', 'scroll', 'parchment')
# what a room holds decides its tag (eg.DRESS_TAGS order); a specific word counts three times
TAG_WORDS = [
    (1, ('barrel', 'crate', 'sack', 'keg', 'boxcan', 'basket'), ()),
    (2, ('nightstand', 'weaponsrack', 'clothrack'), ('bed',)),
    (3, ('table', 'chair', 'stool', 'bench', 'bowl', 'jug', 'tray', 'bottle'), ('cookpot', 'oven')),
    (4, ('bucket', 'washtube', 'washboard', 'bathwood'), ('latrin',)),
    (5, ('log', 'plank', 'saw', 'cart', 'hammer', 'dyepot', 'potter', 'barrow'), ('workbench',)),
    (6, ('skelbase', 'urn', 'candle'), ('coffin',)),
    (7, ('chain_wall', 'shackle', 'stocks', 'feeder', 'trough'), ('cage', 'cell')),
    (8, ('tabmed', 'traymed', 'armpr'), ('stretcher', 'bathtub')),
    (9, ('shelf', 'desk', 'scroll', 'draw_brass'), ('table_school',)),
]


def room_tag(names: list) -> int:
    best, best_score = 0, 0
    for tag, words, strong in TAG_WORDS:
        score = 0
        for name in names:
            low = name.lower()
            if any(w in low for w in strong):
                score += 3
            elif any(w in low for w in words):
                score += 1
        if score > best_score:
            best, best_score = tag, score
    return best


def _pack_objs(entry) -> bytes:
    out = struct.pack('<I', len(entry))
    for dx, dy, dz, raw in entry:
        out += struct.pack('<3fI', dx, dy, dz, len(raw)) + raw
    return out


SHAPE_CAP = 48  # room outlines kept per stage


def build_dress(game: Path, lower_members: set, written_sources: list, db=None) -> bytes:
    """EDR2, per stage from its own levels: (1) cell pools by wall class (every plain-sided built
    cell with 1..8 floor-level objects), (2) every enclosed rectangular room 2..7 cells a side with
    3 objects or more, kept whole: its tag and each cell's class and objects, (3) the seat poses
    of knocked-over chairs and stools. Offsets from the cell centre, turned to the class's
    canonical orientation; heights from the level's floor. EDR5 adds (4) the outlines of the stage's
    rooms that are not full rectangles (L, T, cross...), 3..7 cells a side, as cell lists, for the
    generator to stamp (Hunter, 2026-10-22: rooms shaped like the game's own)."""
    out = bytearray(b'EDR5') + struct.pack('<I', len(written_sources))
    next_box = [max(r.id for r in db.records) + 1] if db is not None else [0]
    for sources in written_sources:
        classes = [[] for _ in eg.DRESS_CLASSES]
        rooms = []
        tipped = []
        shapes = set()  # (w, h, cells) normalised to the outline's corner
        for src_name in sources:
            if f'{src_name}.rfc'.lower() not in lower_members:
                continue
            data = rpk.read(game / 'Resource.rpk', f'{src_name}.rfc')
            lv = level.parse(data)
            g = level.grid(lv)
            top = dict(eg._chunks(data[4:]))
            raws = eg._chunks(top[eg.TAG_OBJECTS][4:])
            decals = sorted(o.pos[1] for o in lv.objects if o.name.startswith('decal'))
            ys = sorted(o.pos[1] for o in lv.objects)
            floor = decals[len(decals) // 2] if decals else ys[len(ys) // 20]
            # loose clutter items per cell, their records imported into the template (one id per source record)
            ldb = level._local_db(lv)
            lby = {r.id: r for r in ldb.records} if ldb is not None else {}
            idmap = {}
            item_cells = {}
            for pl in lv.items:
                if db is None or not pl.item & 0x80000000:
                    continue
                rec = lby.get(pl.item & 0x7FFFFFFF)
                if rec is None:
                    continue
                low = rec.name.lower()
                if not any(w in low for w in CLUTTER) or any(w in low for w in CLUTTER_NOT):
                    continue
                dy = pl.pos[1] - floor
                if not 0 <= dy <= 250:
                    continue
                c = math.floor(pl.pos[0] / 600 + g.w / 2)
                r = math.floor(pl.pos[2] / 600 + g.h / 2)
                new_id = eg.import_record(lby, rec.id, db, next_box, idmap)
                if new_id:
                    item_cells.setdefault((c, r), []).append((new_id, pl.pos[0], dy, pl.pos[2], pl.yaw))
            cells = {}
            for (tag_, body), o in zip(raws, lv.objects):
                c = math.floor(o.pos[0] / 600 + g.w / 2)
                r = math.floor(o.pos[2] / 600 + g.h / 2)
                cells.setdefault((c, r), []).append((tag_, body, o))
                low = o.name.lower()
                if ('chair' in low or 'stool' in low) and 'brok' not in low and abs(o.rot[4]) < 0.7 and 0 <= o.pos[1] - floor <= 120:
                    tipped.append((o.name, o.rot, o.pos[1] - floor))

            def cell_entry(c, r, strict):
                """(class, objects) of a cell, or None; strict: the pool rules (1..8, all clean)."""
                objs = cells.get((c, r), [])
                if strict and (not objs or len(objs) > 8):
                    return None
                if len(objs) > 16:
                    return None
                a = g.cell(c, r)[0]
                if not a & 0x80000:
                    return None
                kinds = [(a >> 4 * q) & 0xF for q in range(4)]
                if any(k not in (0, 7, 0xB) for k in kinds):
                    return None
                m = sum(1 << q for q in range(4) if kinds[q] == 7)
                found = next(((ci, k) for ci, cm in enumerate(eg.DRESS_CLASSES) for k in range(4) if eg.rot_mask(cm, k) == m), None)
                if found is None:
                    return None
                ci, k = found
                cx, cz = (c - g.w / 2 + 0.5) * 600, (r - g.h / 2 + 0.5) * 600
                entry = []
                for tag_, body, o in objs:
                    bad = any(word in o.name.lower() for word in DRESS_SKIP) or not -30 <= o.pos[1] - floor <= 450
                    if bad:
                        if strict:
                            return None
                        continue
                    dx, dz = o.pos[0] - cx, o.pos[2] - cz
                    raw = bytearray(eg._chunk(tag_, body))
                    mtx = list(struct.unpack_from('<9f', raw, 8 + 20))
                    for _ in range((4 - k) % 4):
                        dx, dz, mtx = eg.rot_step(dx, dz, mtx)
                    struct.pack_into('<9f', raw, 8 + 20, *mtx)
                    entry.append((dx, o.pos[1] - floor, dz, bytes(raw)))
                if strict:
                    return ci, entry
                items = []
                for new_id, ix, idy, iz, iyaw in item_cells.get((c, r), []):
                    dx, dz = ix - cx, iz - cz
                    for _ in range((4 - k) % 4):
                        dx, dz = dz, -dx
                        iyaw -= 90.0
                    items.append((new_id, dx, idy, dz, iyaw))
                return ci, entry, items, k

            for r in range(g.h):
                for c in range(g.w):
                    got = cell_entry(c, r, True)
                    if got and got[1]:
                        classes[got[0]].append(got[1])
            # whole rooms: built cells joined by open sides, a full rectangle, walled round
            seen = set()
            for r in range(g.h):
                for c in range(g.w):
                    if (c, r) in seen or not g.cell(c, r)[0] & 0x80000:
                        continue
                    comp, stack = [], [(c, r)]
                    seen.add((c, r))
                    while stack:
                        cc, rr = stack.pop()
                        comp.append((cc, rr))
                        a = g.cell(cc, rr)[0]
                        for q, (dx, dz) in enumerate(eg.SIDE):
                            if (a >> 4 * q) & 0xF == 0:
                                nb = (cc + dx, rr + dz)
                                if nb not in seen and 0 <= nb[0] < g.w and 0 <= nb[1] < g.h and g.cell(*nb)[0] & 0x80000:
                                    seen.add(nb)
                                    stack.append(nb)
                    cs = [x for x, _ in comp]
                    rs = [y for _, y in comp]
                    rw, rh = max(cs) - min(cs) + 1, max(rs) - min(rs) + 1
                    if rw * rh != len(comp) and 3 <= rw <= 7 and 3 <= rh <= 7 and len(comp) >= 5:
                        shapes.add((rw, rh, tuple(sorted((x - min(cs), y - min(rs)) for x, y in comp))))
                    if rw * rh != len(comp) or not (2 <= rw <= 7 and 2 <= rh <= 7):
                        continue
                    rcells = []
                    names = []
                    n_items = 0
                    for rr in range(min(rs), max(rs) + 1):
                        for cc in range(min(cs), max(cs) + 1):
                            got = cell_entry(cc, rr, False)
                            if got is not None:
                                rcells.append(got)
                                names += [eg.dress_name(raw) for _, _, _, raw in got[1]]
                                n_items += len(got[2])
                    if len(names) >= 3:
                        rooms.append((room_tag(names), rcells, rw, rh))
        out += struct.pack('<I', len(eg.DRESS_CLASSES))
        for lst in classes:
            if len(lst) > DRESS_CAP:
                step = len(lst) / DRESS_CAP
                lst = [lst[int(i * step)] for i in range(DRESS_CAP)]
            out += struct.pack('<I', len(lst))
            for entry in lst:
                out += _pack_objs(entry)
        out += struct.pack('<I', len(rooms))
        for tag_, rcells, rw, rh in rooms:
            out += struct.pack('<IIII', tag_, rw, rh, len(rcells))
            for ci, entry, items, k in rcells:
                out += struct.pack('<II', ci, k) + _pack_objs(entry) + struct.pack('<I', len(items))
                for new_id, dx, dy, dz, yaw in items:
                    out += struct.pack('<I4f', new_id, dx, dy, dz, yaw)
        out += struct.pack('<I', len(tipped))
        for name, rot, dy in tipped:
            out += name.encode('latin-1')[:16].ljust(16, b'\0') + struct.pack('<9f', *rot) + struct.pack('<f', dy)
        shapes = sorted(shapes)[:SHAPE_CAP]
        out += struct.pack('<I', len(shapes))
        for sw, sh, cells in shapes:
            out += struct.pack('<BBB', sw, sh, len(cells)) + bytes(v for cell in cells for v in cell)
        DRESS_OUT.setdefault('shapes', []).append(len(shapes))
        DRESS_OUT.setdefault('summary', []).append((len(rooms), [sum(1 for t_, _, _, _ in rooms if t_ == k) for k in range(len(eg.DRESS_TAGS))], len(tipped),
                                                    sum(len(it) for _, rc, _, _ in rooms for _, _, it, _ in rc)))
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--game', type=Path, default=os.environ.get('EXANIMA_DIR'), required=not os.environ.get('EXANIMA_DIR'),
                    help='the Exanima folder (or set EXANIMA_DIR)')
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'out')
    a = ap.parse_args()
    data, ini = build(a.game)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'endless-template.rfc').write_bytes(data)
    (a.out / 'endless-template.ini').write_text(ini, encoding='ascii')
    if DRESS_OUT.get('blob'):
        (a.out / 'endless-dress.bin').write_bytes(DRESS_OUT['blob'])
        print(f'dressings: {len(DRESS_OUT["blob"])} bytes; room outlines per stage: {DRESS_OUT.get("shapes")}')
        for k, (nrooms, tags, ntip, nitems) in enumerate(DRESS_OUT.get('summary', []), 1):
            print(f'  stage {k}: {nrooms} rooms ' + ', '.join(f'{eg.DRESS_TAGS[i]} {n}' for i, n in enumerate(tags) if n) + f'; {ntip} knocked-over seats; {nitems} loose items')
    back = level.parse(data)
    print(f'template: {len(data)} bytes, objects {len(back.objects)}, items {len(back.items)}, spawns {len(back.spawns)}, lights {len(level.lights(back))}')
    print(ini)
    return 0


if __name__ == '__main__':
    sys.exit(main())
