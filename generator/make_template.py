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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools' / 'exanimate'))
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
    db.records += [arrival, zone] + keys + doors + key_chests + fires + levers + hazards + fire_zones + talk_zones + pair_zones + gates + gate_levers + secret_doors + switches + plate_fires + closet_gates + plate_closets + maze_gates + maze_levers + [bypass_gate, bypass_lever]
    level._set_local_db(lv, db)
    # objects: one per prop, generator order
    props = {}
    ys = []
    for o in lv.objects:
        if o.name in eg.PROP_NAMES and o.name not in props:
            props[o.name] = o
        if o.name == 'barrel wdo1 a02':
            ys.append(o.pos[1])
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
    for f in sorted((Path(__file__).resolve().parents[1] / 'out' / 'companions').glob('*.actor')):
        cdb.records.append(rdb.Record(nid, 0, 0, len(f.read_bytes()), f.read_bytes()))
        companions.append(nid)
        nid += 1
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
    lower_members = {n.lower() for n in members}
    stage_lines = []
    for walls, floors in stages:
        if all(f'{n.lower()}.rfc' in lower_members for n in walls + floors):
            stage_lines.append(f'stage{len(stage_lines) + 1}={",".join(walls)}|{",".join(floors)}')
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
        f'gate_levers={",".join(str(r.id) for r in gate_levers)}',
        *[f'bosses_t{i + 1}={",".join(map(str, bosses[i]))}' for i in range(len(bosses))],
        *[f'bosses_t{i + 1}_b{k}={",".join(map(str, boss_bands[i][k]))}' for i in range(len(bosses)) for k in range(1, BANDS + 1)],
        *[f'enemies_t{i + 1}_b{k}={",".join(map(str, enemy_bands[i][k]))}' for i in range(len(tiers)) for k in range(1, BANDS + 1)],
        f'companions={",".join(map(str, companions))}',
        'companion_roles=' + ','.join(map(str, main_roles)),
        'spot_order=' + next((l for l in roles_ini.splitlines() if l.startswith('spot_order=')), 'spot_order=').split('=', 1)[1],
        f'proctor_boss={next((r.id for r in cdb.records if actor.parse(r.data).name == "Proctor15"), 0)}',
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--game', type=Path, default=Path(r'D:\SteamLibrary\steamapps\common\Exanima'))
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'out')
    a = ap.parse_args()
    data, ini = build(a.game)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'endless-template.rfc').write_bytes(data)
    (a.out / 'endless-template.ini').write_text(ini, encoding='ascii')
    back = level.parse(data)
    print(f'template: {len(data)} bytes, objects {len(back.objects)}, items {len(back.items)}, spawns {len(back.spawns)}, lights {len(level.lights(back))}')
    print(ini)
    return 0


if __name__ == '__main__':
    sys.exit(main())
