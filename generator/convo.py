"""Conversation builder for the Endless companions: whole topics written from scratch.

Layout (tools/exanimate/exanimate/dialogue.py header; every shipped role parses with it):
  topic   u32 size, u32 flags (2 = conversation), u64 id (= partner role id), u32 0
  conv    u32 type (= partner id), u32 size, u32 actors, actors name[16] + 12 bytes,
          u32 node count, nodes
  node    u32 size, u32 flags, name[16], f32 x, f32 y, u32 m, m x u32 (0x10000 | 1-based
          follow-up node), u32 reply count, replies
  reply   u32 size, u32 flags, u32 line count, lines (u32 speaker, text), text condition,
          text action, u32 child count, children
  text    u32 length, bytes

Speakers: 1 = the role holder (the companion), 2 = the partner (the player). Node flags (static): low nibble = minimum gap class, bits 8-12 = uses before the cooldown, bits 16-19 =
cooldown class (0 never again .. 14 none), bits 20-22 = extra delay, 0x2000 value mode,
0x1000000 opens on its own, 0x8000000/0x9000000 engine-raised (Aggressor, Threatened, Engage).

A node is opened by the player from the talk list (when it is not a follow-up of another node
and its replies' conditions allow), by the engine by name (`ActivateTopicN(role, 7, name, v)`
from a zone script or an event topic), or on its own (0x1000000) when a condition holds.
"""

from __future__ import annotations

import re

import struct
from dataclasses import dataclass, field

from exanimate import dialogue

PLAYER = 7
ACTOR_TAIL_1 = bytes.fromhex('4040ff800000000000000000')  # copied from Derrin's conversation
ACTOR_TAIL_2 = bytes.fromhex('40c840800000000000000000')
REPLY_FLAGS = 0x7F0

# node flag presets
MENU = 0x0000000E          # in the talk list whenever a reply's condition allows; no cooldown
MENU_ONCE = 0x00000100     # one use, then never again (gap class 0)
AUTO = 0x01000000          # opens on its own when a condition holds; one use
AUTO_HOURLY = 0x01070107   # opens on its own, one use per hour of world time
ZONE = 0x010C2310          # Derrin's lamp-zone preset: value mode, 3 uses, 30 s cooldown
EVENT = 0x01004120         # Derrin's Big Demon preset: engine-raised, value mode
ENGINE = 0x09000000        # engine-raised handlers (Aggressor, Threatened, Engage)
FOLLOW = 0x30000000        # a follow-up node (reached through a link), as the shipped ones


@dataclass
class R:
    """A reply: lines spoken in order, then the conversation continues in `kids`."""
    lines: list  # [('A', text) companion, ('P', text) player]
    cond: str = ''
    act: str = ''
    kids: list = field(default_factory=list)


@dataclass
class N:
    name: str
    flags: int
    replies: list
    links: list = field(default_factory=list)  # names of follow-up nodes (an int is kept raw; the shipped roles use 0)


def _text(s: str) -> bytes:
    raw = s.replace(chr(13) + chr(10), chr(10)).replace(chr(10), chr(13) + chr(10)).encode('latin-1')
    return struct.pack('<I', len(raw)) + raw


def _reply(r: R, fields: set[str]) -> bytes:
    for kind, text in (('condition', r.cond), ('action', r.act)):
        # LuaEvent(...) is the script runtime's own command (it raises script.event in the mod);
        # the game's checker does not know it, so it is checked without those statements
        checked = '\n'.join(l for l in (text or '').split('\n') if not l.strip().startswith('LuaEvent('))
        checked = re.sub(r'LuaFlag\([A-Za-z0-9_]+\)', '1', checked)  # LuaFlag(name) reads an addon's integer
        errs = [m for k, m in dialogue.check_script(checked, kind, fields) if k == 'error']
        if errs:
            raise ValueError(f'{kind} {text!r}: ' + '; '.join(errs))
    body = struct.pack('<II', REPLY_FLAGS, len(r.lines))
    for who, text in r.lines:
        body += struct.pack('<I', 1 if who == 'A' else 2) + _text(text)
    body += _text(r.cond) + _text(r.act)
    kids = [_reply(k, fields) for k in r.kids]
    body += struct.pack('<I', len(kids)) + b''.join(kids)
    return struct.pack('<I', 4 + len(body)) + body


def _node(n: N, index: dict[str, int], fields: set[str], x: float, y: float) -> bytes:
    raw = n.name.encode('latin-1')
    if len(raw) > 15:
        raise ValueError(f'node name {n.name!r} is over 15 bytes')
    links = [(0x10000 | (index[l] + 1)) if isinstance(l, str) else l for l in n.links]
    body = struct.pack('<I', n.flags) + raw.ljust(16, b'\0') + struct.pack(f'<2fI{len(links)}I', x, y, len(links), *links)
    replies = [_reply(r, fields) for r in n.replies]
    body += struct.pack('<I', len(replies)) + b''.join(replies)
    return struct.pack('<I', 4 + len(body)) + body


def topic(partner_id: int, owner: str, partner: str, nodes: list[N], fields: set[str], start_script: str = '', flags: int = 2) -> bytes:
    """`start_script` (topic flag 4, as the meet roles: `StartDialogue(Greeting);`) runs when the
    conversation is approached and names the node that opens it."""
    index = {n.name: i for i, n in enumerate(nodes)}
    if len(index) != len(nodes):
        raise ValueError('duplicate node names')
    blobs = [_node(n, index, fields, 300.0, 300.0 + 100.0 * i) for i, n in enumerate(nodes)]
    actors = owner.encode('latin-1').ljust(16, b'\0') + ACTOR_TAIL_1 + partner.encode('latin-1').ljust(16, b'\0') + ACTOR_TAIL_2
    conv_body = struct.pack('<I', 2) + actors + struct.pack('<I', len(blobs)) + b''.join(blobs)
    if start_script:
        errs = [m for k, m in dialogue.check_script(start_script, 'action', fields) if k == 'error']
        if errs:
            raise ValueError('start script: ' + '; '.join(errs))
        conv_body += _text(start_script)
        flags |= 4
    conv = struct.pack('<II', partner_id, 8 + len(conv_body)) + conv_body
    body = struct.pack('<IQI', flags, partner_id, 0) + conv
    return struct.pack('<I', 4 + len(body)) + body


def fields_of(role_data: bytes) -> set[str]:
    """Role.<name> variables and constants of a script role (the 20-byte entries after the
    head), for the script checker; dialogue.role_fields refuses the meet roles' topics."""
    a, b = struct.unpack_from('<II', role_data, 0x24)
    off = struct.unpack_from('<i', role_data, 0x34)[0]
    names = set()
    for i in range(a + b):
        raw = role_data[0x38 + off + 20 * i : 0x38 + off + 20 * i + 16].split(b'\0')[0]
        name = raw.decode('latin-1')
        if name.isidentifier():
            names.add(name)
    return names


def replace_topic(role_data: bytes, which: int, new_topic: bytes) -> bytes:
    """Swap topic `which` of a script role for `new_topic` (record size follows; the topic
    count does not change) and prove the chain still parses."""
    tops = dialogue.topics(role_data)
    tp, ts, _, _ = tops[which]
    out = bytearray(role_data[:tp] + new_topic + role_data[tp + ts :])
    struct.pack_into('<I', out, 0, len(out))
    data = bytes(out)
    after = dialogue.topics(data)
    if len(after) != len(tops):
        raise dialogue.DialogueError('topic chain changed length')
    return data


def append_topic(role_data: bytes, new_topic: bytes) -> bytes:
    tops = dialogue.topics(role_data)
    out = bytearray(role_data + new_topic)
    struct.pack_into('<I', out, 0, len(out))
    struct.pack_into('<I', out, 0x30, len(tops) + 1)
    data = bytes(out)
    if len(dialogue.topics(data)) != len(tops) + 1:
        raise dialogue.DialogueError('appended topic did not chain')
    return data


def read_nodes(role_data: bytes, which: int) -> list[dict]:
    """Tolerant reader of one conversation topic (dialogue.tree refuses the meet roles'
    0x1006 topics although their layout is the same): [{name, flags, links, replies}] with
    replies as {lines: [(speaker, text)], cond, act, kids}."""
    tp, ts, fl, _ = dialogue.topics(role_data)[which]
    d = role_data
    u = lambda p: struct.unpack_from('<I', d, p)[0]

    def text(t):
        n = u(t)
        return d[t + 4 : t + 4 + n].decode('latin-1'), t + 4 + n

    def reply(p):
        size, _flags, nl = struct.unpack_from('<III', d, p)
        t = p + 12
        lines = []
        for _ in range(nl):
            sp = u(t)
            s, t = text(t + 4)
            lines.append((sp, s))
        cond, t = text(t)
        act, t = text(t)
        kids = []
        nc = u(t)
        t += 4
        for _ in range(nc):
            kids.append(reply(t))
            t += u(t)
        return {'lines': lines, 'cond': cond, 'act': act, 'kids': kids, 'end': p + size}

    b = tp + 0x14 + (4 + u(tp + 0x14) if fl & 1 else 0)
    n_actors = u(b + 8)
    p = b + 12 + 28 * n_actors
    count = u(p)
    p += 4
    out = []
    for _ in range(count):
        size, flags = struct.unpack_from('<II', d, p)
        name = d[p + 8 : p + 24].split(b'\0')[0].decode('latin-1')
        m = u(p + 32)
        links = [u(p + 36 + 4 * i) & 0xFFFF for i in range(m)]
        q = p + 36 + 4 * m
        k = u(q)
        q += 4
        replies = []
        for _ in range(k):
            r = reply(q)
            replies.append(r)
            q = r['end']
        out.append({'name': name, 'flags': flags, 'links': links, 'replies': replies})
        p += size
    end = b + u(b + 4)
    if p != end:
        script, p = text(p)  # topic flag 4: the approach script, e.g. StartDialogue(Greeting);
        out.append({'name': '', 'flags': 0, 'links': [], 'replies': [], 'start_script': script})
    if p != end:
        raise dialogue.DialogueError('conversation does not end where its size says')
    return out


def render(role_data: bytes, which: int, owner: str, partner: str = '**You**') -> list[str]:
    """Markdown lines of one conversation: the companion by name, **You** for the player
    (or the partner's name in a banter topic)."""
    out = []

    def walk(r, ind):
        for sp, text in r['lines']:
            who = owner if sp == 1 else partner
            out.append('    ' * ind + f'- {who}: {text.replace(chr(13) + chr(10), " / ")}' if text.strip() else '    ' * ind + f'- _({who} says nothing; the engine runs a script)_')
        for k in r['kids']:
            walk(k, ind + 1)

    for n in read_nodes(role_data, which):
        if not n['name']:
            out.append(f'_(on approach: `{n["start_script"]}`)_')
            out.append('')
            continue
        out.append(f'### {n["name"]}')
        out.append('')
        for r in n['replies']:
            walk(r, 0)
        out.append('')
    return out
