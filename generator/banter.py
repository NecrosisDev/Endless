"""Companion banter: pair topics between the Endless companions.

A conversation topic is keyed by the partner's role id (1BAC90 looks a role's topic up by
that id), so companion A talks to companion B through a topic in A's main role whose id is B's
main role id. Every banter node auto-opens (flag 0x1000000, as Derrin's "Learning" node) when
both are following the player, with a long cooldown so a pair does not repeat itself all the
way down. Each ordered pair gets its own exchanges: A's topic with B holds A's lines as speaker
1 and B's answers as speaker 2.

Byte layout (tools/exanimate/exanimate/dialogue.py header; every shipped role parses to the last
byte with it): topic u32 size, u32 flags 2, u64 id, u32 0, conversation u32 type (= partner
id), u32 size, u32 actors, actors name[16] + 12 bytes, u32 node count, nodes. The two actor
tails are copied from Derrin's conversation with the Player.

Static only (2026-10-22): the records parse back with dialogue.tree; nothing has run in game.
"""

from __future__ import annotations

import struct

from exanimate import dialogue

ACTOR_TAIL_1 = bytes.fromhex('4040ff800000000000000000')  # Derrin's own actor entry tail
ACTOR_TAIL_2 = bytes.fromhex('40c840800000000000000000')  # the partner's
EXPLORER = 0x1F  # the role whose Activity 4 is "following" (the recruit script sets it)
# auto-open, at most 1 use per cooldown of class 7 (1 h of world time), minimum gap class 7
BANTER_FLAGS = 0x01000000 | (7 << 16) | (1 << 8) | 7
REPLY_FLAGS = 0x7F0
BOTH_FOLLOWING = f'result = (Actor[0].Role(${EXPLORER:X}).Activity = 4) & (Actor[1].Role(${EXPLORER:X}).Activity = 4);'


def _text(s: str) -> bytes:
    raw = s.encode('latin-1')
    return struct.pack('<I', len(raw)) + raw


def _reply(lines: list[tuple[int, str]], condition: str, action: str, children: list | None = None) -> bytes:
    body = struct.pack('<II', REPLY_FLAGS, len(lines))
    for speaker, text in lines:
        body += struct.pack('<I', speaker) + _text(text)
    body += _text(condition) + _text(action)
    kids = children or []
    body += struct.pack('<I', len(kids)) + b''.join(kids)
    return struct.pack('<I', 4 + len(body)) + body


def _node(name: str, replies: list[bytes], flags: int, x: float, y: float) -> bytes:
    raw = name.encode('latin-1')
    if len(raw) > 15:
        raise ValueError(f'node name {name!r} is over 15 bytes')
    body = struct.pack('<I', flags) + raw.ljust(16, b'\0') + struct.pack('<2fI', x, y, 0)
    body += struct.pack('<I', len(replies)) + b''.join(replies)
    return struct.pack('<I', 4 + len(body)) + body


def pair_topic(partner_id: int, owner: str, partner: str, exchanges: list[tuple[str, list[tuple[int, str]]]]) -> bytes:
    """A conversation topic with `partner`'s role: one auto-opening node per exchange, each a
    single reply holding its lines (speaker 1 = the owner, 2 = the partner)."""
    nodes = []
    for k, (name, lines) in enumerate(exchanges):
        nodes.append(_node(name, [_reply(lines, BOTH_FOLLOWING, '')], BANTER_FLAGS, 300.0, 300.0 + 100.0 * k))
    actors = owner.encode('latin-1').ljust(16, b'\0') + ACTOR_TAIL_1 + partner.encode('latin-1').ljust(16, b'\0') + ACTOR_TAIL_2
    conv_body = struct.pack('<I', 2) + actors + struct.pack('<I', len(nodes)) + b''.join(nodes)
    conv = struct.pack('<II', partner_id, 8 + len(conv_body)) + conv_body
    body = struct.pack('<IQI', 2, partner_id, 0) + conv
    return struct.pack('<I', 4 + len(body)) + body


def add_pair_topic(role_data: bytes, partner_id: int, owner: str, partner: str, exchanges) -> bytes:
    """Append the topic to a script role record (the topic chain ends at the record end), bump
    the record size and topic count, and prove the result still parses."""
    before = dialogue.topics(role_data)
    topic = pair_topic(partner_id, owner, partner, exchanges)
    out = bytearray(role_data + topic)
    struct.pack_into('<I', out, 0, len(out))
    struct.pack_into('<I', out, 0x30, len(before) + 1)
    data = bytes(out)
    after = dialogue.topics(data)
    if len(after) != len(before) + 1 or after[-1][3] != partner_id:
        raise dialogue.DialogueError('pair topic did not chain')
    tree = dialogue.tree(data)
    names = [n['name'] for n in tree if n['topic'] == len(after) - 1]
    if names != [name for name, _ in exchanges]:
        raise dialogue.DialogueError(f'pair topic nodes read back as {names}')
    for kind, text in (('condition', BOTH_FOLLOWING),):
        errs = [m for k, m in dialogue.check_script(text, kind, dialogue.role_fields(data)) if k == 'error']
        if errs:
            raise dialogue.DialogueError('; '.join(errs))
    return data


# ---- the exchanges. Relationships: Aldric's lord's son
# hired Tobin's crew to open the halls; Mira sold a copy of her stolen map to that crew.
BANTER: dict[tuple[str, str], list[tuple[str, list[tuple[int, str]]]]] = {
    ('Aldric', 'Tobin'): [
        ('Whose coin', [
            (1, "Six men and a map, Tobin. Who paid your crew?"),
            (2, "Didn't ask. Never ask. The coin was good and the lock was interesting."),
            (1, "It was my lord's son's coin. I let him walk down here with it."),
            (2, "Then we're both to blame and neither of us was there. Comforting, isn't it."),
        ]),
        ('Lock talk', [
            (1, "That door back there. You had it open before I'd drawn breath."),
            (2, "Good lock, that. Honest work. Someone cared when they made it."),
            (1, "You admire the lock and not the man who paid for it. That's thieves for you."),
            (2, "Locks don't lie to you, Aldric. Men do. You've met a few."),
        ]),
        ('Old guard', [
            (1, "Stay behind me on the stairs. I'm slower but I'm wider."),
            (2, "Wider's one word for it."),
            (1, "Keep talking and you can go first."),
            (2, "Behind you it is. Lead on, wall."),
        ]),
    ],
    ('Tobin', 'Aldric'): [
        ('Your lordling', [
            (1, "This lord's son of yours. What did he look like?"),
            (2, "Tall. Fair. Carried a sword he'd never used. Why?"),
            (1, "The one with the map. He kept his hood up. I never saw his face."),
            (2, "Then keep your eyes open. I'd know him. Even now."),
        ]),
        ('Running', [
            (1, "When they come, I run. Just so you know. It's not personal."),
            (2, "Run toward me, then. A man running past a shield wall is a man without one."),
            (1, "That's... actually sensible."),
            (2, "Twenty years at a door, lad. You learn where to stand."),
        ]),
        ('Money owed', [
            (1, "Your friend Hask. The dead one. You said he owed you money."),
            (2, "Four silver and a dinner. Eleven years running."),
            (1, "I could've had that off him in a minute, back then."),
            (2, "He'd have broken your fingers. He was that kind of friend."),
        ]),
    ],
    ('Aldric', 'Mira'): [
        ('The map', [
            (1, "You read, girl. What does your map say is at the bottom?"),
            (2, "It doesn't. The spiral runs off the page. The copyist stopped, or was stopped."),
            (1, "Then it's no map. It's a drawing of a hole."),
            (2, "Most maps are, if you follow them far enough."),
        ]),
        ('Listening', [
            (1, "You talk a great deal for someone who spent her life in a quiet room."),
            (2, "I was quiet for years. It seems I'd saved it up."),
            (1, "Keep some for the stairs. Sound carries down there."),
            (2, "Noted. I'll whisper my footnotes."),
        ]),
        ('Respect', [
            (1, "I don't hold with thieves. But you stole a book, not a purse."),
            (2, "A map. And it was knowledge, not property. The Order would disagree."),
            (1, "I've known lords who'd hang you for either. Walk closer to me."),
            (2, "Is that concern, Aldric?"),
            (1, "It's a shield. Make of it what you like."),
        ]),
    ],
    ('Mira', 'Aldric'): [
        ('A question', [
            (1, "Aldric. Your lord's son. Did he carry a map in a red leather case?"),
            (2, "He did. How would you know that?"),
            (1, "The archive binds its copies in red. I'm wondering which copy he had."),
            (2, "You're wondering whether it was yours."),
            (1, "I'm wondering a great many things. That is one of them."),
        ]),
        ('Counting', [
            (1, "You count the dead you knew. I've noticed. Three so far."),
            (2, "Four. One I didn't say."),
            (1, "Why count?"),
            (2, "So someone has. Nobody else will, down here."),
        ]),
        ('Reading', [
            (1, "Do you read, Aldric? Honestly."),
            (2, "Enough to know a duty roster from a death warrant. Why?"),
            (1, "I may need someone to check my copy of this place against what we see."),
            (2, "Then read it to me. Slowly. I'm old."),
        ]),
    ],
    ('Mira', 'Tobin'): [
        ('Grammar', [
            (1, "\"Me and the crew.\" The crew and I, Tobin."),
            (2, "The crew's dead, Mira. Grammar's not going to bring them back."),
            (1, "No. But it might keep the rest of us from sounding like them."),
            (2, "Harsh. Fair, but harsh."),
        ]),
        ('The copy', [
            (1, "Your crew's map. Was it bound in red?"),
            (2, "Red leather, yeah. Fancy. The boss kept it in his shirt. Why?"),
            (1, "No reason. Archive habit. I notice bindings."),
            (2, "You went quiet after you asked. That's not no reason."),
        ]),
        ('Pockets', [
            (1, "Tobin. My pen."),
            (2, "What pen?"),
            (1, "The one in your left sleeve. I watched you take it."),
            (2, "Just keeping in practice. Here. It's a terrible pen, by the way."),
        ]),
    ],
    ('Tobin', 'Mira'): [
        ('Lock and book', [
            (1, "You and me are the same trade, you know. I open doors, you open books."),
            (2, "Books don't have you hanged."),
            (1, "Yours did, nearly. You said so."),
            (2, "...Point taken. Different doors. Same hanging."),
        ]),
        ('Talent', [
            (1, "That thing you did with the light. Can you do it to a lock?"),
            (2, "A binding borrows force. A lock is just force in a shape. In theory."),
            (1, "In theory. Right. So that's a no."),
            (2, "It's a not yet. Find me one worth the headache."),
        ]),
        ('Nervous', [
            (1, "You go very still when you're scared. I go the other way."),
            (2, "I noticed. You talk."),
            (1, "Helps me think. Does the still thing help you?"),
            (2, "No. But it's quieter, and the dead hear."),
        ]),
    ],
}
