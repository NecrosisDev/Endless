"""Endless companions: friendly NPCs that join the player, with their own dialogue.

Each companion is three script roles written from scratch with convo.py and the lines in
endless_dialogue.py, on the shapes of Derrin's roles (the only recruitable NPC the game ships):
  main    Derrin's main role record (19) with its conversation replaced: the talk list, the
          zone/event reactions, the secret, parting; its event topics (the huge beast, a known
          dead one) are kept and pointed at the new role id; banter topics with the other
          companions are appended
  meet    Derrin's meet-outer record (35) with its conversation replaced: the first meeting and
          the recruit script (the companion's actor record carries this role)
  assail  Derrin's assail record (34), conversation replaced: when the player attacks first
Role ids are unused two-hex-digit ids after the shipped ones, ascending, so the table stays
sorted (the game finds roles by binary search).

Writes out/charroles-endless.rdb (the whole roles database with the new roles appended),
out/companions/<name>.actor (the records the template appends) and out/companions/roles.ini.
--export writes out/companions/DIALOGUE.md, every line read back from the built records.
Static only (2026-10-22): the records parse back; nothing has run in game.
"""

from __future__ import annotations

import argparse
import copy
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools' / 'exanimate'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from exanimate import rpk, rdb, dialogue, level, actor  # noqa: E402
import convo  # noqa: E402
import endless_dialogue as ed  # noqa: E402

COMPANIONS = list(ed.COMPANIONS)  # found in this order: Tobin, Aldric, Mira
# Thaumaturgy (static): a caster NPC's record ends with a CDEC01 block after the roles blob:
# u32 0, ten u32 prepared slots, u32 known count, known entries {u32 power id, u32 0x15FFF}, as
# the shipped UBM Thaumers carry. NPCs cast only powers with a native evaluator (Blast, Barrier,
# Shell, Strikes, Shock, Shock Weapons, Long Door, Constant Displacement, Summon Demon); Mind is
# refused for NPCs. Mira, the Order's sounding, gets the ones that fit a shaper on the defensive.
# Mira: Blast, Barrier (sustained), Shock, Shell and Constant Displacement (continuous); Tobin, who
# does not know he has it: Blast, Shock, Strikes (continuous). A continuous power needs a binding,
# and bindings come from Continuity, a Concentration technique (not a power id), so the records
# carry it from the start: Mira Continuity II (two bindings), Tobin Continuity (one).
POWERS = {'Mira': [0x201, 0x10205, 0x401, 0x20208, 0x20603], 'Tobin': [0x201, 0x401, 0x2020B]}
TECHNIQUES = {'Mira': ['Sustain', 'Continuity II', 'Abstraction'], 'Tobin': ['Sustain', 'Continuity', 'Clarity']}
# Aldric is strong as hell (Hunter): the three fighting skills at five techniques
STRONG = {'Aldric': {0: 25000, 2: 25000, 3: 25000}}  # Close Combat, Armour, Shields
# The record ships with the thaumaturgy skills but no caster block: Mira hides the talent until
# her trust reveal, whose dialogue action raises LuaEvent(EndlessReveal, 1); the mod then grants
# the block at runtime through characters.grant_powers (a 0.26.0 request, written behind a check).
REVEAL_AT_RUNTIME = True
CASTER_SKILLS = {4: 15000, 5: 15000}  # Insight, Concentration, in the shipped thaumers' range
TAG_POWERS = 0xCDEC01
KNOWN_TAIL = 0x00015FFF
SHAPES = {'main': 19, 'meet': 35, 'assail': 34}  # Derrin's records the three roles are built on
# The "recognised dead one" scene (sight events): Derrin's main role carries a flag-4 event
# topic whose id names one story character; a plain id instead names a role, and the topic fires
# on the NPC brain's first focus on any character holding it. Each companion gets a plain role of
# its own (the shape of 'Huge Demon', 23), the event topic is re-keyed to it, and make_template
# gives that role to the one dead record each of them would know.
KNOWN_SHAPE = 23
MARLIA_EVENT = 0xC000000280000008
NAME_PAD = bytes(16)
HUMAN, ACTIVITY_WAIT = 1, 0x21


def escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n')


def roles_of(rest: bytes) -> tuple[int, list[int], int]:
    """(offset of the role count, role ids, end offset) in an actor record tail:
    u32 n + n x 12 bytes, u32 role count, u32 blob length, entries of 12 bytes (u32 id ...)."""
    n = struct.unpack_from('<I', rest, 0)[0]
    p = 4 + 12 * n
    count, blob = struct.unpack_from('<II', rest, p)
    ids = []
    q = p + 8
    end = q + blob
    while q + 12 <= end and len(ids) < count:
        ids.append(struct.unpack_from('<I', rest, q)[0])
        q += 12
    return p, ids, end


def with_roles(rest: bytes, role_ids: list[int]) -> bytes:
    p, _, end = roles_of(rest)
    blob = b''.join(struct.pack('<I', rid) + bytes(8) for rid in role_ids)
    return rest[:p] + struct.pack('<II', len(role_ids), len(blob)) + blob + rest[end:]


def companion_record(base: 'actor.Actor', name: str, meet_role: int, powers: list[int] | None = None, strong: dict | None = None) -> bytes:
    """A friendly human: the base record's look and skills, name replaced, roles Human +
    Activity Wait + the companion's meet role (never Human Hater); with `powers`, the caster
    block appended and the thaumaturgy skills set."""
    a = copy.deepcopy(base)
    raw = name.encode('latin-1')[:16]
    a.lead = raw + NAME_PAD[: 16 - len(raw)] + a.lead[16:]  # lead starts at the name (16 bytes), after the magic/size words
    a.name = name
    a.rest = with_roles(a.rest, [HUMAN, ACTIVITY_WAIT, meet_role])
    if powers and not REVEAL_AT_RUNTIME:
        if len(powers) > 10:
            raise ValueError('ten prepared slots')
        slots = powers + [0] * (10 - len(powers))
        body = struct.pack('<I', 0) + struct.pack('<10I', *slots) + struct.pack('<I', len(powers))
        body += b''.join(struct.pack('<II', pid, KNOWN_TAIL) for pid in powers)
        a.rest = a.rest + struct.pack('<II', TAG_POWERS, len(body)) + body
    wanted = dict(CASTER_SKILLS) if powers else {}
    wanted.update(strong or {})
    if wanted:
        have = {sk.index: sk for sk in a.skills}
        for idx, val in wanted.items():
            if idx in have:
                have[idx].value = val
            else:
                a.skills.append(actor.Skill(idx, val, b''))
        a.skills.sort(key=lambda sk: sk.index)
    if powers and TECHNIQUES.get(name):
        actor.set_techniques(a, 'Concentration', TECHNIQUES[name])
    return actor.pack(a)


def powers_of(data: bytes) -> list[int]:
    """The prepared power ids of a record's caster block ([] without one)."""
    a = actor.parse(data)
    _, _, end = roles_of(a.rest)
    tail = a.rest[end:]
    i = tail.find(struct.pack('<I', TAG_POWERS))
    if i < 0:
        return []
    size = struct.unpack_from('<I', tail, i + 4)[0]
    body = tail[i + 8 : i + 8 + size]
    return [v for v in struct.unpack_from('<10I', body, 4) if v]


def named(data: bytes, label: str) -> bytes:
    raw = label.encode('latin-1')[:16]
    return data[:8] + raw + NAME_PAD[: 16 - len(raw)] + data[24:]


def retarget_event_topics(data: bytes, old_id: int, new_id: int) -> bytes:
    """Derrin's main role carries event topics whose scripts open nodes of role 19 by number
    (`Actor[0].ActivateTopicN(19, 7, Big Demon, 1);`); point them at the new role, same length."""
    old, new = b'ActivateTopicN(%d, 7,' % old_id, b'ActivateTopicN(%d, 7,' % new_id
    if len(old) != len(new):
        raise ValueError('role id digit count changed')
    return data.replace(old, new)


def rekey_event_topic(data: bytes, old_id: int, new_id: int) -> bytes:
    """Point a flag-4 event topic (u32 size, u32 flags, u32 idLo, u32 idHi) at another id."""
    for tp, _ts, fl, ident in dialogue.topics(data):
        if fl & 4 and ident == old_id:
            out = bytearray(data)
            struct.pack_into('<Q', out, tp + 8, new_id)
            return bytes(out)
    raise ValueError(f'event topic {old_id:#x} not found')


def known_role(by: dict, rid: int, name: str) -> rdb.Record:
    src = by[KNOWN_SHAPE]
    return rdb.Record(rid, src.flags, 0, len(src.data), named(src.data, f'EN_Known_{name}'))


def chain_main_nodes(name: str, ids_by_name: dict) -> list[convo.N]:
    """The chain nodes of `name`'s talk with the player: the asks (name is A) and the closing
    lines (name is B). A reply's `TopicUsed` conditions refer to the owner's own topic."""
    nodes = []
    me = ids_by_name[name]['main']
    for (a, b), chain in ed.CHAINS.items():
        other = ids_by_name[b if a == name else a]['main']
        if a == name:
            ask, answer = chain['ask']
            act = f'Actor[0].LeaveDialogue;\nActor[0].ActivateTopicN({me}, {other}, Asked {b}, 1);'
            nodes.append(convo.N(f'About {b}', convo.MENU_ONCE, [convo.R([('P', ask), ('A', answer)], ed.FOLLOWING, act)]))
        elif b == name:
            text, replies = chain['after']
            told = ed.CHAIN_TOLD.get((a, b))
            alternatives = [(text, ed.NOT_TOLD if told else ed.FOLLOWING, replies)]
            if told:
                alternatives.append((told[0], ed.TOLD, told[1]))
            nodes.append(convo.N(f'{a} asked', convo.ZONE, [convo.R([('A', t)], c, '', [convo.R([('P', r)]) for r in rs]) for t, c, rs in alternatives]))
    return nodes


def with_leaf_action(r: convo.R, act: str) -> convo.R:
    """The action appended to every leaf reply (the last line of each path through the node)."""
    if r.kids:
        return convo.R(list(r.lines), r.cond, r.act, [with_leaf_action(k, act) for k in r.kids])
    return convo.R(list(r.lines), r.cond, (r.act + chr(10) if r.act else '') + act, [])


def flag_name(node: str, index: int) -> str:
    """The LuaFlag the mod sets for one companion's reaction: endless_saw_you_0 and so on."""
    return 'endless_' + node.lower().replace(' ', '_') + f'_{index}'


def flagged(n: convo.N, name: str, ids_by_name: dict) -> convo.N:
    """A reaction node opens on its own (AUTO) when the mod has set this companion's flag for it
    and the companion follows; an existing condition is kept, ANDed."""
    flag = flag_name(n.name, list(ids_by_name).index(name))
    gate = f'(LuaFlag({flag}) = 1) & (Actor[0].Role($1F).Activity = 4)'
    out = []
    for r in n.replies:
        cond = r.cond.strip()
        if cond:
            assert cond.startswith('result = ') and cond.endswith(';'), cond
            cond = f'result = {gate} & ({cond[len("result = "):-1]});'
        else:
            cond = f'result = {gate};'
        out.append(convo.R(list(r.lines), cond, r.act, list(r.kids)))
    return convo.N(n.name, convo.AUTO, out, n.links)


def order_nodes(name: str, nodes: list[convo.N], ids_by_name: dict) -> list[convo.N]:
    """One voice per occasion (ed.SPOT_ORDER): a companion keeps an occasion node only when it is
    in the order; the node's last lines open the hop with the next in the order (ed.HOPS)."""
    out = []
    for n in nodes:
        order = ed.SPOT_ORDER.get(n.name)
        if order is None:
            out.append(n)
        elif name in order:
            k = order.index(name)
            if k + 1 < len(order) and n.name in ed.HOPS.get((name, order[k + 1]), {}):
                act = f'Actor[0].ActivateTopicN({ids_by_name[name]["main"]}, {ids_by_name[order[k + 1]]["main"]}, {n.name}, 1);'
                out.append(convo.N(n.name, n.flags, [with_leaf_action(r, act) for r in n.replies], n.links))
            else:
                out.append(n)
    return out


def build_roles(by: dict, name: str, ids: dict, ids_by_name: dict | None = None) -> list[rdb.Record]:
    spec = ed.COMPANIONS[name]
    out = []
    # main: Derrin's head (its XAU_Memory variable stays) and event topics, a new conversation
    src = by[SHAPES['main']]
    data = retarget_event_topics(src.data, SHAPES['main'], ids['main'])
    data = rekey_event_topic(data, MARLIA_EVENT, ids['known'])
    fields = convo.fields_of(data)
    nodes = [convo.N(n.name, n.flags, [fill(r, ids) for r in n.replies], n.links) for n in spec['main']]
    if ids_by_name:
        nodes += [flagged(n, name, ids_by_name) for n in ed.REACTIONS.get(name, [])]
        nodes = order_nodes(name, nodes, ids_by_name) + chain_main_nodes(name, ids_by_name)
    data = convo.replace_topic(data, 0, convo.topic(convo.PLAYER, name, 'Unknown', nodes, fields))
    out.append(rdb.Record(ids['main'], src.flags, 0, len(data), named(data, f'EN_{name}')))
    # meet: the meet-outer shape (approach script opens Greeting)
    src = by[SHAPES['meet']]
    fields = convo.fields_of(src.data)
    nodes = [convo.N(n.name, n.flags, [fill(r, ids) for r in n.replies], n.links) for n in spec['meet']]
    data = convo.replace_topic(src.data, 0, convo.topic(convo.PLAYER, name, 'Unknown', nodes, fields, spec['meet_start'], 0x1002))
    out.append(rdb.Record(ids['meet'], src.flags, 0, len(data), named(data, f'EN_{name}_Meet')))
    # assail: the assail shape (topic keyed by XA_Unknown 14, its Negotiate variable kept)
    src = by[SHAPES['assail']]
    fields = convo.fields_of(src.data)
    nodes = [convo.N(n.name, n.flags, [fill(r, ids) for r in n.replies], n.links) for n in spec['assail']]
    data = convo.replace_topic(src.data, 0, convo.topic(14, name, 'Unknown', nodes, fields))
    out.append(rdb.Record(ids['assail'], src.flags, 0, len(data), named(data, f'EN_{name}_Assail')))
    out.append(known_role(by, ids['known'], name))
    return out


def fill(r: convo.R, ids: dict) -> convo.R:
    return convo.R(list(r.lines), ed.fill_ids(r.cond, ids), ed.fill_ids(r.act, ids), [fill(k, ids) for k in r.kids])


def add_banter(records: dict, main_ids: dict) -> int:
    count = 0
    for (owner, partner), exchanges in ed.BANTER.items():
        rec = records[main_ids[owner]]
        nodes = [convo.N(name, convo.AUTO_HOURLY, [convo.R(lines, ed.BOTH_FOLLOWING)]) for name, lines in exchanges]
        # the hops a lead's line opens (the node runs only when the partner is near)
        for spot, lines in ed.HOPS.get((owner, partner), {}).items():
            nodes.append(convo.N(spot, ed.DEPTH_FLAGS if spot == 'Depth' else convo.ZONE, [convo.R(lines)]))
            count += 1
        # the middle of a chain: the owner's answer to the player opened it; its end opens the
        # partner's closing line to the player (the partner holds its main role; 7 = Player)
        chain = ed.CHAINS.get((owner, partner))
        if chain:
            act = f'Actor[1].ActivateTopicN({main_ids[partner]}, 7, {owner} asked, 1);'
            nodes.append(convo.N(f'Asked {partner}', convo.ZONE, [convo.R(chain['between'], ed.BOTH_FOLLOWING, act)]))
            count += 1
        rec.data = convo.append_topic(rec.data, convo.topic(main_ids[partner], owner, partner, nodes, convo.fields_of(rec.data)))
        rec.size = len(rec.data)
        count += len(exchanges)
    return count


def render_all(records: dict, ids_by_name: dict) -> str:
    out = ['# Endless companion dialogue (built 2026-10-22, static: read back from the roles file, not played)', '',
           'The companion speaks by name, **You** is the player. Indentation = which line answers which.',
           'Node names are what the engine opens: **Boss Door / Key / Vault / Closet / Gate / Stairs / Arrive / Depth /',
           'Boss** from the zones the generator places (Depth: one line per new depth; Boss: the boss room), **Fight',
           '1..3** on their own in the boss room while you are below half health, **Big Demon / Marlia** from the',
           'sight events (a huge beast; the one dead person each of them knows), **Hurt / You hurt** on their own',
           'below 40 health, **Idle 1..3** on their own while walking, **Talk / Secret / Secret 2 / Hold all / Follow',
           'all / Part ways / Come along** from the talk list, **Aggressor / Threatened / Engage / Wary / Plead** by',
           'the engine when you attack them. One voice per occasion: each zone, the hurt line, each call-out and each',
           'first casting has an order of speakers (Aldric first at the boss door, gate, arrival, boss room, call-outs',
           'and your wounds; Mira first at the stairs, a new depth and the vault; Tobin first at the key and the closet',
           'plate, and alone for the beast); the first of them in the party speaks to you, and that line opens one',
           'short exchange with the next in the order, listed under the banter headings by the same name. **Saw you /',
           'Saw Mira / Spark** are the first castings (yours, Mira\'s, Tobin\'s), opened by the mod when it sees one.',
           'Banter nodes open on their own when both follow. **About <B>** is a',
           'talk-list line you say to one companion about another (once each): as that dialogue closes, the two of',
           'them have the **Asked** exchange under the banter heading, and its end opens the other one\'s **<A> asked**',
           'line to you. Three conversations chained by script; whether the hand-off plays is unseen.', '']
    for name, ids in ids_by_name.items():
        out += [f'## {name}', '', '### First meeting (their own role; the "Join me" yes runs the recruit script)', '']
        out += convo.render(records[ids['meet']].data, 0, name)
        out += ['### Following you (main role)', '']
        out += convo.render(records[ids['main']].data, 0, name)
        for k, (tp, ts, fl, ident) in enumerate(dialogue.topics(records[ids['main']].data)):
            if k and fl & 2:
                partner = next(n for n, i in ids_by_name.items() if i['main'] == ident)
                out += [f'### Banter with {partner} (opens on its own when both follow you, once an hour each)', '']
                out += convo.render(records[ids['main']].data, k, name, partner)
        out += ['### If you attack them first (assail role)', '']
        out += convo.render(records[ids['assail']].data, 0, name)
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--game', type=Path, default=Path(r'D:\SteamLibrary\steamapps\common\Exanima'))
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'out')
    ap.add_argument('--export', action='store_true', help='also write DIALOGUE.md from the built records')
    a = ap.parse_args()
    db = rdb.parse(rpk.read(a.game / 'Resource.rpk', 'charroles.rdb'))
    by = {r.id: r for r in db.records}
    for key, rid in SHAPES.items():
        if rid not in by:
            print(f'role {rid} ({key}) missing from charroles.rdb')
            return 1
    used = {r.id for r in db.records}
    free = [i for i in range(0x30, 0x100) if i not in used]
    lines_dir = a.out / 'companions'
    lines_dir.mkdir(parents=True, exist_ok=True)
    keys = list(SHAPES) + ['known']
    ids_by_name = {name: {key: free[len(keys) * n + k] for k, key in enumerate(keys)} for n, name in enumerate(COMPANIONS)}
    records = {}
    for name, ids in ids_by_name.items():
        for rec in build_roles(by, name, ids, ids_by_name):
            records[rec.id] = rec
    banter_count = add_banter(records, {n: i['main'] for n, i in ids_by_name.items()})
    db.records += list(records.values())
    # companion actor records from a friendly human of the installed first level
    lv = level.parse(rpk.read(a.game / 'Resource.rpk', 'exanima01.rfc'))
    cdb = level.characters(lv)
    base = None
    for rec in cdb.records:
        act = actor.parse(rec.data)
        if act.version != 7 or not act.rest:
            continue
        try:
            roles_of(act.rest)
        except struct.error:
            continue
        # Hellmode gives every level-1 human the Human Hater role; the roles are replaced wholesale,
        # so any human look will do (patients and the like keep civilian gear)
        if act.name.lower().startswith(('patient', 'granny', 'fatlady', 'villager', 'linus', 'kade')):
            base = act
            break
    if base is None:
        print('no friendly human record to base companions on')
        return 1
    summary = []
    for name, ids in ids_by_name.items():
        data = companion_record(base, name, ids['meet'], POWERS.get(name), STRONG.get(name))
        check = actor.parse(data)
        _, got, _ = roles_of(check.rest)
        assert check.name == name and got == [HUMAN, ACTIVITY_WAIT, ids['meet']], (check.name, got)
        assert powers_of(data) == ([] if REVEAL_AT_RUNTIME else POWERS.get(name, [])), powers_of(data)
        (lines_dir / f'{name}.actor').write_bytes(data)
        cast = ' powers=' + ','.join(f'{p:#x}' for p in POWERS[name]) if name in POWERS else ''
        summary.append(f'{name}: roles main={ids["main"]} meet={ids["meet"]} assail={ids["assail"]} known={ids["known"]}{cast}')
    summary.append(f'main_roles={",".join(str(ids_by_name[n]["main"]) for n in COMPANIONS)}')
    names = list(COMPANIONS)
    summary.append('spot_order=' + ';'.join(f'{spot}:' + ','.join(str(names.index(n)) for n in order) for spot, order in ed.SPOT_ORDER.items()))
    summary.append('known_roles=' + ';'.join(f'{ed.KNOWN_DEAD[n]},{ids_by_name[n]["known"]}' for n in COMPANIONS))
    summary.append('reveal_powers=' + ';'.join(f'{COMPANIONS.index(n)}:{",".join(str(p) for p in ps)}' for n, ps in POWERS.items()))
    summary.append(f'banter: {banter_count} exchanges in {len(ed.BANTER)} pair topics')
    summary.append(f'companion records based on {base.name}: ' + ', '.join(COMPANIONS))
    db.records.sort(key=lambda r: r.id)
    data = rdb.pack(db)
    back = rdb.parse(data)
    assert [r.id for r in back.records] == sorted(r.id for r in db.records)
    for rec in back.records:
        if rec.id >= 0x30 and rec.name.startswith('EN_') and 'Known' not in rec.name:
            for k, (_tp, _ts, fl, _id) in enumerate(dialogue.topics(rec.data)):
                if fl & 2:
                    convo.read_nodes(rec.data, k)  # every conversation of every new role reads back
    (a.out / 'charroles-endless.rdb').write_bytes(data)
    (lines_dir / 'roles.ini').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    if a.export:
        (lines_dir / 'DIALOGUE.md').write_text(render_all({r.id: r for r in back.records}, ids_by_name), encoding='utf-8')
    print(f'charroles-endless.rdb: {len(data)} bytes, {len(back.records)} roles')
    print('\n'.join(summary))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
