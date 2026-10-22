"""The Endless companions' conversations, written on the game's own lore (2026-10-22; read from
every note, book and dialogue in Resource.rpk).

Three roles per companion, all built by convo.py:
  meet   the first meeting; the player recruits them here (role shape: Derrin's meet-outer 35)
  main   the talk list while they follow, the zone/event reactions, their secret, parting
  assail what happens when the player attacks them first (role shape: Derrin's assail 34)
plus a banter topic per other companion inside the main role (BANTER: hourly exchanges while both
follow; HOPS: the one exchange a lead's line opens with a partner at each occasion).

The cast (Hunter, 2026-10-22):
  Aldric  a soldier of Ardent sent down with the proctor who came about the missing villagers.
          At the hole he could not make himself go down the rope. The proctor went alone. Days
          later Aldric went after him, and now he puts himself in front of everything to make
          up for it. He does not know what became of the proctor until he finds him dead and
          walking (the generator makes the proctor the boss of the first area of depth 3), and
          only then admits what he did.
  Tobin   rough, not clever, braver than he looks. Hired by Bram's band for the heavy work; the
          band fed people to the hole at the old shrine because Bram believed it wanted feeding;
          when Tobin asked why, they fed him to it. He trusts nobody now, and he has a nose for
          when something is about to go wrong.
  Mira    an apprentice of the Order who says she copies books. She has the talent and keeps it
          hidden until she trusts the player (her feel-based lines unlock after her first
          secret). A master of the Order went below years ago to study dead that stand on their
          own and never came back; her own master wanted to know why and died last winter; Mira
          came down alone, on a rope, with nobody's leave.
Nobody paid the bandits and Ardent is guilty of nothing worse than not coming sooner; the main
story's open questions stay open.

Tone: frightened, hungry, grieving people in the dark with no way out, hunted by the dead. Nobody
is witty. Nobody comments on what is not in front of them. Lines are short, whole, plain; no
"X, not Y", no quips, no aphorisms, no echo endings. What they know they brought from above; a
new depth is announced in the start room, so it is the stone, the wet, the cold, the smell, the
dark. The player speaks as in Derrin's trees: measured, few contractions, cold, calls them
soldier, apprentice, thief. Aldric: short, formal, "aye", eager to be useful. Mira: careful,
precise, "I expect". Tobin: country speech ("reckon", "I never", "summat"), blunt, repeats himself.

Speaker 'A' is the companion, 'P' the player. Node names are what the engine looks up:
  Boss Door / Gate / Stairs / Depth / Key / Vault / Closet / Arrive / Boss   the talk zones
  Fight 1..3                          mid-fight call-outs (in the boss room, player below half health)
  Big Demon / Marlia                  the sight events (a huge beast; the one dead person they know)
  (one voice per occasion: SPOT_ORDER is the order of speakers, the first present one speaks, and
  its hop with the next is in HOPS; REACTIONS are the first-casting nodes the mod opens)
  Hold all / Follow all               the player's group orders (fan out through Explorer's own
                                      Wait Here / Follow me nodes to every subordinate nearby)
  About <B> / Asked / <A> asked       a talk you start with A that passes to B and comes back to
                                      you (three conversations chained by ActivateTopicN; CHAINS)
  Aggressor / Threatened / Engage / Wary / Plead   engine-raised handlers (kept by name)
Scripts use the role ids the build assigns (fill_ids puts them in).
"""

from __future__ import annotations

from convo import AUTO_HOURLY, EVENT, MENU, N, R, ZONE

DEPTH_FLAGS = 0x01070707  # opens on its own when the zone wakes it; 7 uses, an hour of world time apart
IDLE = AUTO_HOURLY        # opens on its own while following, once an hour of world time

RECRUIT = ('Actor[0].RemoveRole({meet});\nActor[0].RemoveRole($21);\nActor[0].AddRole({main});\n'
           'Actor[0].AddRole($1F);\nActor[1].AddRole($1F);\nActor[0].AddRelation(Actor[1], $1E);\n'
           'Actor[1].AddRelation(Actor[0], $1D);\nActor[0].Role($1F).Activity = 4;')
PART = 'Actor[0].RemRelation(Actor[1], $1E);\nActor[1].RemRelation(Actor[0], $1D);\nActor[0].Role($1F).Activity = 2;'
REJOIN = 'Actor[0].AddRelation(Actor[1], $1E);\nActor[1].AddRelation(Actor[0], $1D);\nActor[0].Role($1F).Activity = 4;'
HOLD_ALL = 'Actor[1].ActivateTopicN(31, 29, Wait Here, 1);'
FOLLOW_ALL = 'Actor[1].ActivateTopicN(31, 29, Follow me, 1);'
FOLLOWING = 'result = (Actor[0].Role($1F).Activity = 4);'
NOT_FOLLOWING = 'result = (Actor[0].Role($1F).Activity ! 4);'
MEET_AGGRESSOR = 'Actor[0].RemoveRole({meet});\nActor[0].RemoveRole($21);\nActor[0].AddRole({assail});'
MEET_THREATENED = 'Actor[0].LeaveDialogue;\nActivateTopic(Wary);'
ASSAIL_AGGRESSOR = 'Actor[0].LeaveDialogue;\nActor[0].ActivateTopicN({assail}, 14, Plead, 1);\nActor[0].RemRelation(Actor[1], $15);\n? Role.Negotiate = 1 : Role.Negotiate = 2;'
ASSAIL_RECRUIT = ('Actor[0].RemoveRole({assail});\nActor[0].RemRelation(Actor[1], $15);\nActor[0].AddRole({main});\n'
                  'Actor[0].AddRole($1F);\nActor[1].AddRole($1F);\nActor[0].AddRelation(Actor[1], $1E);\n'
                  'Actor[1].AddRelation(Actor[0], $1D);\nActor[0].Role($1F).Activity = 4;')
ASSAIL_ENGAGE = 'Actor[0].LeaveDialogue;\n? Role.Negotiate = 1 : Role.Negotiate = 2;'
HURT = 'result = (Actor[0].Health < 40) & (Actor[0].Role($1F).Activity = 4);'
YOU_HURT = 'result = (Actor[1].Health < 40) & (Actor[0].Role($1F).Activity = 4);'
INTRO = 'result = (TopicUsed(Join me) = 0) & (TopicUsed(Not now) = 0);'
AGAIN = 'result = (TopicUsed(Not now) > 0) | (TopicUsed(Join me) > 0);'
TOLD = 'result = (TopicUsed(Secret) > 0);'      # Mira has told the player about the talent
NOT_TOLD = 'result = (TopicUsed(Secret) = 0);'


def fill_ids(text: str, ids: dict) -> str:
    return text.format(main=f'${ids["main"]:02X}', meet=f'${ids["meet"]:02X}', assail=f'${ids["assail"]:02X}').replace('ActivateTopicN($', 'ActivateTopicN(').replace(f'(${ids["assail"]:02X}, 14', f'({ids["assail"]}, 14')


def meet_engine_nodes() -> list[N]:
    return [
        N('Aggressor', 0x9000040, [R([('A', '')], '', MEET_AGGRESSOR)], [0]),
        N('Threatened', 0x900003E, [R([('A', '')], '', MEET_THREATENED)], [0]),
    ]


def assail_engine_nodes(plead: list[str]) -> list[N]:
    return [
        N('Plead', 0x10D014E, [R([('A', line)]) for line in plead]),
        N('Aggressor', 0x900004E, [R([('A', '')], 'result = (Actor[2] = Actor[0]);', ASSAIL_AGGRESSOR)]),
        N('Engage', 0x9000000, [R([('A', '')], 'result = (Actor[2] = Actor[0]);', ASSAIL_ENGAGE)], [0]),
    ]


def depth_node(by_stage: dict, deeper: str) -> N:
    """A line for the tile-set stage the new depth wears (the mod sets LuaFlag endless_stage:
    1 catacombs (depths 1-2), 2 lower halls, 3 sewers, 4 brick, 5 mines, 6 old brick, 7 deeper
    brick, then 2..7 again), so what they say matches what the seed built; `deeper` for any
    stage without a line of its own."""
    replies = [R([('A', t)], f'result = (LuaFlag(endless_stage) = {k});') for k, t in sorted(by_stage.items())]
    others = ' & '.join(f'(LuaFlag(endless_stage) ! {k})' for k in sorted(by_stage))
    replies.append(R([('A', deeper)], f'result = {others};'))
    return N('Depth', DEPTH_FLAGS, replies)


def group_orders(hold: str, follow: str) -> list[N]:
    return [
        N('Hold all', MENU, [R([('P', "All of you. Wait here."), ('A', hold)], FOLLOWING, HOLD_ALL)]),
        N('Follow all', MENU, [R([('P', "All of you. With me."), ('A', follow)], NOT_FOLLOWING, FOLLOW_ALL)]),
    ]


FIGHT_FLAGS = 0x010C030C  # opens on its own in the boss room, player below half health; 3 uses, 30 s apart
FIGHT = 'result = (TopicUsed(Boss) > 0) & (Actor[1].Health < 50) & (Actor[0].Role($1F).Activity = 4);'


def fight_nodes(enter: list, callouts: list[str]) -> list[N]:
    """`enter` is a list of (text, condition) alternatives; the first whose condition holds plays."""
    return [N('Boss', ZONE, [R([('A', t)], c) for t, c in enter])] + [N(f'Fight {k + 1}', FIGHT_FLAGS, [R([('A', t)], FIGHT)]) for k, t in enumerate(callouts)]


def idle_nodes(lines: list[str]) -> list[N]:
    return [N(f'Idle {k + 1}', IDLE, [R([('A', t)], FOLLOWING)]) for k, t in enumerate(lines)]


def zone_node(name: str, alternatives: list) -> N:
    """A zone node with (text, condition) alternatives; the first whose condition holds plays."""
    return N(name, ZONE, [R([('A', t)], c) for t, c in alternatives])


# =========================================================== Aldric
ALDRIC = {
    'meet_start': 'StartDialogue(Greeting);',
    'meet': [
        N('Greeting', 0x110000C, [R([('A', "Stay there. Stay where you are. Are you alive?")], 'result = (TopicUsed(Who are you?) = 0);')], [0]),
        N('Who are you?', 0x330000E, [R([('P', "Who are you?")], INTRO, '', [
            R([('A', "Aldric. I'm a soldier of Ardent. I came down after the proctor. He was sent about the folk missing from the villages."), ('A', "Who are you?")], '', '', [
                R([('P', "I do not know. I woke on the ground down here.")], '', '', [
                    R([('A', "Aye. Everybody I've met down here says that. There aren't many to ask.")], '', '', [
                        R([('P', "Where is the proctor?")]),
                        R([('P', "Who have you met?")], '', '', [
                            R([('A', "Four of the missing. They were dead and walking. I had to put them down. That isn't what we came for.")]),
                        ]),
                    ]),
                ]),
                R([('P', "That is my concern.")], '', '', [
                    R([('A', "All right. All right. Only keep your hands where I can see them.")]),
                ]),
            ]),
        ])], ['Why here']),
        N('Why here', 0x0, [R([('P', "Where is the proctor?")], '', '', [
            R([('A', "Ahead of me. He went down first. I came after. I've been looking for him since I landed and I haven't found him.")], '', '', [
                R([('P', "Why did he go first?")], '', '', [R([('A', "He was the proctor. He went where he liked. I was to follow him down. I did. Later.")])]),
                R([('P', "What will you do now?")], '', '', [R([('A', "Find him. Or find out. I can't go back up and say I don't know.")])]),
            ]),
        ])], ['Join me', 'Not now']),
        N('Join me', 0x0, [R([('P', "Come with me, soldier. There is no way up. I go down.")], '', '', [
            R([('A', "There's no up. I've looked at every stair. Aye. I'll come. I'll go first, if you want. I'd rather go first.")], '', '', [
                R([('P', "Then come. Keep behind me.")], '', RECRUIT, [R([('A', "Behind you. If that's how you want it.")])]),
                R([('P', "You will do as I say.")], '', '', [
                    R([('A', "Aye. What do you mean to do?")], '', '', [
                        R([('P', "Find the key. Open the door. Kill what is behind it. Take the stairs.")], '', RECRUIT, [R([('A', "Then I'll be in front of you when the door opens. Lead on.")])]),
                        R([('P', "I have not decided.")], '', '', [R([('A', "Then I'll wait. I'm not going anywhere on my own.")])]),
                    ]),
                ]),
            ]),
        ])]),
        N('Not now', 0x0, [R([('P', "I go alone.")], '', '', [
            R([('A', "Don't. Don't go alone. There's nothing down here but the dead.")], '', '', [
                R([('P', "I will manage.")], '', '', [R([('A', "Then I'll be here. If you come back this way, I'll be here.")])]),
                R([('P', "Stay out of my way.")], '', '', [R([('A', "Aye.")])]),
            ]),
        ])]),
        N('Reconsidered', 0x330000E, [R([('P', "I have thought again, soldier. Come with me.")], AGAIN, '', [
            R([('A', "Aye. Thank you. I'll go first.")], '', RECRUIT),
        ])]),
        *meet_engine_nodes(),
        N('Wary', 0x10D013D, [R([('A', "Easy. Easy. I don't want this.")])]),
    ],
    'main': [
        N('Talk', MENU, [
            R([('P', "Tell me of the missing.")], '', '', [
                R([('A', "Twelve. There was a girl, Elara. A woman called Tessa wrote to her cousin about her and the letter got to Ardent in the end. A serving woman from the Fallen Oak. A farm lad of Lord Ermus'. The letters said bandits. Bandits don't take folk that have nothing.")], '', '', [
                    R([('P', "Then why take them?")], '', '', [R([('A', "That's what the proctor came to find out.")])]),
                    R([('P', "You know their names.")], '', '', [R([('A', "I carried the list. I read it enough times.")])]),
                ]),
            ]),
            R([('P', "What is this place, soldier?")], '', '', [
                R([('A', "I don't know. It's old. Somebody built it to be held. Gates, barracks. Then they were gone and the dead were here.")], '', '', [
                    R([('P', "Gone where?")], '', '', [R([('A', "Down. Everything here goes down.")])]),
                    R([('P', "Held against what?")], '', '', [R([('A', "I've thought about that. The doors get heavier the lower we go. I don't think it was built to keep anything out.")])]),
                ]),
            ]),
            R([('P', "How do you fare?")], '', '', [
                R([('A', "Well enough. I've been eating what was left in the jars. I don't know how long it's been since I saw daylight.")], '', '', [
                    R([('P', "Good.")]),
                    R([('P', "Tell me if you cannot go on.")], '', '', [R([('A', "I'll go on. I'll go in front.")])]),
                ]),
            ]),
            R([('P', "You put yourself in front of everything. Why?")], 'result = (TopicUsed(Depth) > 0);', '', [
                R([('A', "That's what a soldier's for.")], '', '', [
                    R([('P', "That is not an answer.")], '', '', [R([('A', "It's the one I've got.")])]),
                ]),
            ]),
        ]),
        N('Secret', MENU, [R([('P', "The proctor. You said he went down first and you came after. Tell me the rest.")], 'result = (TopicUsed(Marlia) > 0) & (TopicUsed(Secret) = 0);', '', [
            R([('A', "We stood at the hole. He went down the rope. I was to go after him. I had my hands on the rope and I couldn't. I couldn't make my legs do it. He called up for me and I didn't answer. Two days I sat by that hole. Then I went down, because I couldn't go back to Ardent and say what I'd done.")], '', '', [
                R([('P', "You left him alone down here.")], '', '', [R([('A', "I left him alone down here. And now you've seen what that came to.")])]),
                R([('P', "You came down in the end.")], '', '', [R([('A', "Two days late. He was dead by then, I expect. I'll be in front of you from here. That's all I can do about it.")])]),
            ]),
        ])]),
        N('Secret 2', MENU, [R([('P', "Aldric. If you could go back to that rope.")], 'result = (TopicUsed(Depth) > 3) & (TopicUsed(Secret) > 0) & (TopicUsed(Secret 2) = 0);', '', [
            R([('A', "I'd like to say I'd go down after him. I don't know that I would. I know what's down here now. I think I'd have run from you too, that first day, if you'd given me room.")], '', '', [
                R([('P', "You did not run.")], '', '', [R([('A', "No. Not that time.")])]),
                R([('P', "That is honest, at least.")], '', '', [R([('A', "It's late to start. I'll be in front.")])]),
            ]),
        ])]),
        *group_orders("Aye. I'll hold here.", "Aye. I'll go first."),
        N('Boss Door', ZONE, [R([('A', "Locked. There's something in there. I can hear it moving. When it opens, let me go in first.")])]),
        N('Key', ZONE, [R([('A', "That's a key. Take it.")])]),
        N('Vault', ZONE, [R([('A', "Another lock. There'll be another key somewhere.")])]),
        N('Closet', ZONE, [R([('A', "There's a plate in the floor there. Don't step on it. There's something behind that gate.")])]),
        N('Gate', ZONE, [R([('A', "The gate's up. Go. I'll come behind.")])]),
        N('Stairs', ZONE, [R([('A', "Stairs. I'll go first.")])]),
        N('Arrive', ZONE, [R([('A', "Another one. Same as the last. Find the key.")])]),
        *fight_nodes([("There it is. Get to its side. I'll take the front.", '')], [
            "Fall back. Fall back, I have it.",
            "You're bleeding. Get behind me.",
            "Behind me. Now. Let it come to me.",
        ]),
        depth_node({
            1: "Lower. Same stone. Same dead, I expect.",
            2: "Colder here. Bigger halls.",
            3: "Wet. It smells like a drain. Mind your feet.",
            4: "Brick. Older than the rest.",
            5: "Rough stone. Mines, by the look of it.",
            6: "Different stone. Old. Watch the floor.",
        }, "I'm getting old for this. I'll go first anyway."),
        *idle_nodes([
            "The lamps are still lit. Nobody's filled them. I don't like it.",
            "It's quiet. I'd rather hear them coming.",
            "I keep thinking I'll see the sky round the next corner. I know I won't.",
        ]),
        N('Big Demon', EVENT, [R([('A', "Gods below. Look at the size of it. Get behind me.")])]),
        N('Marlia', EVENT, [R([('A', "That's him. That's the proctor. That's his coat.")], '', '', [
            R([('P', "You said he went ahead of you.")], '', '', [R([('A', "I did say that. I'll tell you. Not here. Put him down first.")])]),
            R([('P', "Then he is found.")], '', '', [R([('A', "Aye. He's found. I'll tell you how it was. Not here.")])]),
        ])]),
        N('Hurt', AUTO_HOURLY, [R([('A', "I'm hit. Keep going. I'm still in front.")], HURT)]),
        N('You hurt', AUTO_HOURLY, [R([('A', "You're bleeding. Sit down. Bind it. I'll watch.")], YOU_HURT, '', [
            R([('P', "Later.")], '', '', [R([('A', "Sit down.")])]),
            R([('P', "A moment, then.")], '', '', [R([('A', "I'll watch the door.")])]),
        ])]),
        N('Part ways', MENU, [R([('P', "Hold here, soldier. I will return.")], FOLLOWING, '', [
            R([('A', "Aye. I'll hold it. Don't be long.")], '', PART),
        ])]),
        N('Come along', MENU, [R([('P', "We go.")], NOT_FOLLOWING, '', [
            R([('A', "Aye. I'll go first.")], '', REJOIN),
        ])]),
    ],
    'assail_plead': ["Stop!", "Hold!", "Enough!"],
    'assail': [
        N('Negotiate', 0x100002E, [R([('P', "Wait. I mean you no harm.")], '', '? Role.Negotiate = 0 : Role.Negotiate = 1;', [
            R([('A', "You've a strange way of showing it.")]),
            R([('A', "Put it down first.")], 'result = (Role.Negotiate = 2) | (Actor[0].Trust(Actor[1]) < -50);'),
            R([('A', "You came at me. Up top that's a hanging.")], '', '', [
                R([('P', "I took you for one of the dead.")], '', 'Actor[0].AddRelation(Actor[1], $15);', [
                    R([('A', "The dead don't wear a sash. Look before you swing.")], '', '', [
                        R([('P', "I will.")], '', '', [R([('A', "Who are you, then?")])]),
                        R([('P', "I make no promises.")], '', '', [R([('A', "Then stay over there.")])]),
                    ]),
                ]),
                R([('P', "You were in my way.")], '', '', [R([('A', "Then say so.")])]),
            ]),
        ])], ['Start Over']),
        N('Start Over', 0x0, [R([('A', "I don't want to fight you. I've done enough of that down here.")], '', '', [
            R([('P', "Then let us begin again. Who are you?")], '', '', [
                R([('A', "Aldric. A soldier of Ardent. I came down after the proctor and I haven't found him. You?")], '', '', [
                    R([('P', "I do not remember. I woke down here.")], '', '', [
                        R([('A', "Like the rest. Come with me or don't. Just don't come at me again.")], '', '', [
                            R([('P', "Come with me.")], '', ASSAIL_RECRUIT, [R([('A', "Aye. I'll go first.")])]),
                            R([('P', "I go alone.")], '', '', [R([('A', "Go on, then.")])]),
                        ]),
                    ]),
                ]),
            ]),
            R([('P', "Stay out of my way.")], '', '', [R([('A', "Gladly.")])]),
        ])]),
        *assail_engine_nodes(["Stop!", "Hold!", "Enough!"]),
    ],
}

# =========================================================== Mira
MIRA = {
    'meet_start': 'StartDialogue(Greeting);',
    'meet': [
        N('Greeting', 0x110000C, [R([('A', "You're alive. Stay there. Stay there a moment, please.")], 'result = (TopicUsed(Who are you?) = 0);')], [0]),
        N('Who are you?', 0x330000E, [R([('P', "Who are you?")], INTRO, '', [
            R([('A', "Mira. I'm with the Order. An apprentice. I copy their books."), ('A', "I wanted to be sure you weren't one of the dead. They don't talk. Who are you?")], '', '', [
                R([('P', "I do not know. I woke on the ground down here.")], '', '', [
                    R([('A', "Everyone I've met down here says that. I don't know what does it."), ('A', "I came down on a rope. The rope ended and I fell the rest of the way. I don't know how far. You came another way, I expect. It doesn't put us all in the same place.")], '', '', [
                        R([('P', "Why did the Order send you?")]),
                        R([('P', "Everyone?")], '', '', [
                            R([('A', "A soldier. A thief. Some of the villagers, before they died. None of them remembered.")]),
                        ]),
                    ]),
                ]),
                R([('P', "I care nothing for the Order.")], '', '', [R([('A', "Nor do I, lately.")])]),
            ]),
        ])], ['Why here']),
        N('Why here', 0x0, [R([('P', "Why did the Order send you down?")], '', '', [
            R([('A', "They didn't. I came. Years ago a master of the Order went below to study the dead here, the ones that stand up with no necromancer near them. He never came back. My master wanted to know why. She died last winter and nobody else wanted to know. So I came.")], '', '', [
                R([('P', "Alone. On a rope.")], '', '', [R([('A', "Alone. On a rope. I didn't think about it very carefully.")])]),
                R([('P', "What did you mean to do down here?")], '', '', [R([('A', "Find out what holds the dead up. I still mean to.")])]),
            ]),
        ])], ['Join me', 'Not now']),
        N('Join me', 0x0, [R([('P', "Come with me, apprentice. You know what the Order knows. I will do the fighting.")], '', '', [
            R([('A', "Yes. All right. I'll keep out of your way when they come.")], '', '', [
                R([('P', "Agreed. Stay close.")], '', RECRUIT, [R([('A', "I will.")])]),
                R([('P', "You will do as I say.")], '', '', [
                    R([('A', "Yes. Within reason.")], '', RECRUIT, [R([('A', "Down, then.")])]),
                ]),
            ]),
        ])]),
        N('Not now', 0x0, [R([('P', "I have no need of a copyist.")], '', '', [
            R([('A', "No. I'll be here. There's nowhere else for me to be.")]),
        ])]),
        N('Reconsidered', 0x330000E, [R([('P', "I have thought again. Come with me.")], AGAIN, '', [
            R([('A', "Yes. Thank you.")], '', RECRUIT),
        ])]),
        *meet_engine_nodes(),
        N('Wary', 0x10D013D, [R([('A', "Don't. Please don't.")])]),
    ],
    'main': [
        N('Talk', MENU, [
            R([('P', "Tell me of the Order.")], '', '', [
                R([('A', "They live in towers, away from people. A master takes an apprentice so that what they know goes on after them. I was taken on to copy. That's what they said it was for.")], '', '', [
                    R([('P', "And what was it for?")], '', '', [R([('A', "I don't know yet.")])]),
                    R([('P', "Your master.")], '', '', [R([('A', "She died last winter. I'd rather not talk about her.")])]),
                ]),
            ]),
            R([('P', "What is this place?")], '', '', [
                R([('A', "A city, once. The Order's books say the ancients dug below the earth and found something, and lost their gods over it. Then they were gone. The dead stayed.")], '', '', [
                    R([('P', "What gods?")], '', '', [R([('A', "The Guardian. The Keeper of the Dead. The stories say he raises the dead as an army when he needs one.")])]),
                    R([('P', "Gone where?")], '', '', [R([('A', "The books don't say. Down, I expect. There's nowhere else.")])]),
                ]),
            ]),
            R([('P', "How do you fare, apprentice?")], '', '', [
                R([('A', "Tired. I don't sleep. I'm all right.")], NOT_TOLD, '', [
                    R([('P', "Good.")]),
                ]),
                R([('A', "Tired. The dead press on my mind, all of them at once. I don't sleep. I'm all right.")], TOLD, '', [
                    R([('P', "Tell me if it worsens.")], '', '', [R([('A', "You'd notice. I'd start answering them.")])]),
                    R([('P', "Good.")]),
                ]),
            ]),
            R([('P', "What holds the dead up? Your master wanted to know.")], 'result = (TopicUsed(Depth) > 0);', '', [
                R([('A', "A binding, the Order would say. When a shaper lets go of a binding it breaks. These have held for I don't know how long. So either someone is still holding them, or they hold themselves.")], '', '', [
                    R([('P', "Hold themselves.")], '', '', [R([('A', "Yes. And a thing that holds itself has to be fed. I don't want to know with what.")])]),
                ]),
            ]),
        ]),
        # the talent comes out three ways: she tells you (Secret), she is driven to it with someone near
        # death (Dire), or you turn on her (Engage); each raises the event that grants her powers
        N('Dire', 0x01000000, [R([('A', "No. Not like this. Get behind me. I'll explain after.")], 'result = ((Actor[0].Health < 25) | (Actor[1].Health < 25)) & (Actor[0].Role($1F).Activity = 4);', 'LuaEvent(EndlessReveal, 3);')]),
        N('Engage', 0x9000040, [R([('A', '')], '', 'Actor[0].LeaveDialogue;' + chr(10) + 'LuaEvent(EndlessReveal, 2);')], [0]),
        N('Secret', MENU, [R([('P', "You are no copyist. Tell me what you are.")], 'result = (TopicUsed(Depth) > 1) & (TopicUsed(Secret) = 0);', '', [
            R([('A', "No. I'm not. I have the talent. I can feel them. I've been able to feel them since I landed. I didn't tell you because people don't like it, and I didn't know you.")], '', 'LuaEvent(EndlessReveal, 1);', [
                R([('P', "You know me now.")], '', '', [R([('A', "I know you haven't left me behind. That's enough to be going on with. When I say stop, stop. I'll know before you can see them.")])]),
                R([('P', "What else have you hidden?")], '', '', [R([('A', "Nothing that would hurt you. Ask me again lower down.")])]),
            ]),
        ])]),
        N('Secret 2', MENU, [R([('P', "The locks open more easily the deeper I go. Why?")], 'result = (TopicUsed(Depth) > 3) & (TopicUsed(Secret) > 0) & (TopicUsed(Secret 2) = 0);', '', [
            R([('A', "Because it knows you. The thing that holds the dead. I feel it turn toward you at every door. Your mind isn't shut from your side. Something below has the key to it, and it's opening you a little at a time. The same as the doors.")], '', '', [
                R([('P', "It wants me at the bottom.")], '', '', [R([('A', "There's a story the Order keeps, the Guardian's Wrath. Our ancestors dug for the earth's lifeblood and found the Guardian, and sealed the entrances after. I expect the hole you fell through was one of the seals. I expect the master who came down before me felt it turn to him too.")])]),
                R([('P', "Can you cut it?")], '', '', [R([('A', "I could try. He probably tried. Ask me when you're certain.")])]),
            ]),
        ])]),
        *group_orders("Yes.", "Yes."),
        zone_node('Boss Door', [("Locked. There's something behind it. I can hear it.", NOT_TOLD), ("Locked. There's something behind it. It has a mind, of a kind. It's waiting.", TOLD)]),
        N('Key', ZONE, [R([('A', "There. That's the key.")])]),
        N('Vault', ZONE, [R([('A', "Another lock. Its key will be somewhere else. Someone built this to be slow.")])]),
        zone_node('Closet', [("Don't step on the plate. There's a gate beside it, and I don't like the gate.", NOT_TOLD), ("Don't step on the plate. There are some behind that gate. I can feel them.", TOLD)]),
        N('Gate', ZONE, [R([('A', "It's up. Go through.")])]),
        N('Stairs', ZONE, [R([('A', "Stairs. Down again. That's another one I've counted.")])]),
        N('Arrive', ZONE, [R([('A', "Another one. The same shape. It's always the same shape.")])]),
        *fight_nodes([("There it is. Go when it turns.", NOT_TOLD), ("I can feel it. It knows we're here. Go when it turns.", TOLD)], [
            "I'll hold it. A moment. Hit it when it stops.",
            "Back. Get back. Let me put something between you.",
            "You're bleeding. Stand behind me. Please.",
        ]),
        depth_node({
            1: "Lower. The same stone. I've counted this flight.",
            2: "Bigger halls. There'll be more of them here.",
            3: "Wet. The air is bad. Don't drink anything.",
            4: "Old brick. Be careful here.",
            5: "They dug here. It's quieter than it should be.",
            6: "Older brick. Something walks here that I can't feel at all.",
        }, "I've stopped counting. It's the same, lower down. It's always the same."),
        *idle_nodes([
            "The lamps burn without oil. I try not to think about what they burn.",
            "I keep listening for something that isn't footsteps.",
            "My master would have called this a great opportunity. She said things like that.",
        ]),
        N('Big Demon', EVENT, [R([('A', "That's one of the beasts. There's a plate of it in the Order's bestiary. Don't let it touch you.")])]),
        N('Marlia', EVENT, [R([('A', "Wait. The robe. That's one of ours. That's a master's robe.")], '', '', [
            R([('P', "The one who came before you.")], '', '', [R([('A', "I expect so. He found what he came for. Come on.")])]),
            R([('P', "Then he never turned back.")], '', '', [R([('A', "No. Come on.")])]),
        ])]),
        N('Hurt', AUTO_HOURLY, [R([('A', "I'm hurt. I don't think it's bad. I don't know what bad looks like.")], HURT)]),
        N('You hurt', AUTO_HOURLY, [R([('A', "You're bleeding badly. Sit. Let me look at it.")], YOU_HURT, '', [
            R([('P', "Later.")], '', '', [R([('A', "Now. Please. Sit.")])]),
            R([('P', "A moment, then.")], '', '', [R([('A', "Look at me. Don't look at it.")])]),
        ])]),
        N('Part ways', MENU, [R([('P', "Wait here, apprentice. I will return.")], FOLLOWING, '', [
            R([('A', "All right. Don't be long.")], '', PART),
        ])]),
        N('Come along', MENU, [R([('P', "We go.")], NOT_FOLLOWING, '', [
            R([('A', "Thank you.")], '', REJOIN),
        ])]),
    ],
    'assail_plead': ["Stop!", "Don't!", "Please!"],
    'assail': [
        N('Negotiate', 0x100002E, [R([('P', "Wait. I mean you no harm.")], '', '? Role.Negotiate = 0 : Role.Negotiate = 1;', [
            R([('A', "You tried to kill me.")]),
            R([('A', "Stay back. Stay back from me.")], 'result = (Role.Negotiate = 2) | (Actor[0].Trust(Actor[1]) < -50);'),
            R([('A', "You struck first. What did you take me for?")], '', '', [
                R([('P', "One of the dead.")], '', 'Actor[0].AddRelation(Actor[1], $15);', [
                    R([('A', "The dead don't flinch. Look, next time. Please.")], '', '', [
                        R([('P', "I will.")], '', '', [R([('A', "Then who are you?")])]),
                        R([('P', "I make no promises.")], '', '', [R([('A', "Then keep away from me.")])]),
                    ]),
                ]),
                R([('P', "You startled me.")], '', '', [R([('A', "I was standing still.")])]),
            ]),
        ])], ['Start Over']),
        N('Start Over', 0x0, [R([('A', "I don't want to fight. I'd lose.")], '', '', [
            R([('P', "Then let us begin again. Who are you?")], '', '', [
                R([('A', "Mira. I'm an apprentice of the Order. I came down to find out why the dead here stand up. You?")], '', '', [
                    R([('P', "I do not remember. I woke down here.")], '', '', [
                        R([('A', "Like the others. Come with me, if you want. I know what the Order knows. You can fight.")], '', '', [
                            R([('P', "Come with me.")], '', ASSAIL_RECRUIT, [R([('A', "All right. Don't do that again.")])]),
                            R([('P', "I go alone.")], '', '', [R([('A', "As you like.")])]),
                        ]),
                    ]),
                ]),
            ]),
            R([('P', "Stay out of my way.")], '', '', [R([('A', "I wasn't in it.")])]),
        ])]),
        *assail_engine_nodes(["Stop!", "Don't!", "Please!"]),
    ],
}

# =========================================================== Tobin
TOBIN = {
    'meet_start': 'StartDialogue(Greeting);',
    'meet': [
        N('Greeting', 0x110000C, [R([('A', "Stop there. Stop. You're alive? Say summat.")], 'result = (TopicUsed(Who are you?) = 0);')], [0]),
        N('Who are you?', 0x330000E, [R([('P', "Who are you?")], INTRO, '', [
            R([('A', "Tobin. I did the heavy work for a band up top. Bram's lot."), ('A', "You got thrown in and all, didn't you. You lived. Most of them don't.")], '', '', [
                R([('P', "Thrown in. You would know about that.")], '', '', [
                    R([('A', "Aye. I would. I held the rope. Then they put me on the end of it. I fell a long way. It's deeper here than where the rest went in. There's no climbing out. I tried. I tried for days.")], '', '', [
                        R([('P', "Why did they throw you in?")]),
                        R([('P', "How many did you throw?")], '', '', [
                            R([('A', "I never counted. Nine. Ten. Bram said the hole wanted feeding. I never asked what he meant. I should have asked sooner.")]),
                        ]),
                    ]),
                ]),
                R([('P', "I do not remember who I am.")], '', '', [R([('A', "None of them did, after. Bram said it was the fall. I don't reckon it was the fall.")])]),
            ]),
        ])], ['Why here']),
        N('Why here', 0x0, [R([('P', "Why did they throw you in?")], '', '', [
            R([('A', "I asked Bram what we were feeding. He didn't like being asked. He kept us at the old shrine, where the carved folk are kneeling, and he said the hole wanted feeding or the dead would come up out of it. So they fed it me.")], '', '', [
                R([('P', "And do the dead come up out of it?")], '', '', [R([('A', "Not that I ever saw. Bram believed it. He prayed at that shrine every night. I reckon he's still feeding it.")])]),
                R([('P', "You had it coming.")], '', '', [R([('A', "Aye. I know that. I don't need you to say it.")])]),
            ]),
        ])], ['Join me', 'Not now']),
        N('Join me', 0x0, [R([('P', "Come with me, thief. You know where keys get hidden. I can fight.")], '', '', [
            R([('A', "Why? What do you want me for? Last lot that wanted me put me down a hole.")], '', '', [
                R([('P', "I want someone who can find a key and stand his ground. Nothing else.")], '', RECRUIT, [R([('A', "All right. All right. I'll come. You leave me behind, I'll know what you are.")])]),
                R([('P', "You will earn your keep. For every one you threw.")], '', '', [
                    R([('A', "Aye. That's fair. That's more than fair.")], '', RECRUIT, [R([('A', "I'll come. I'm not slow and I'm not soft.")])]),
                ]),
            ]),
        ])]),
        N('Not now', 0x0, [R([('P', "I want no bandit at my back.")], '', '', [
            R([('A', "Suit yourself. I'll be here.")]),
        ])]),
        N('Reconsidered', 0x330000E, [R([('P', "I have thought again, thief. Come with me.")], AGAIN, '', [
            R([('A', "Changed your mind, did you. All right. Don't leave me behind.")], '', RECRUIT),
        ])]),
        *meet_engine_nodes(),
        N('Wary', 0x10D013D, [R([('A', "Nothing in my hands. Look. There's nothing in my hands.")])]),
    ],
    'main': [
        N('Talk', MENU, [
            R([('P', "Tell me of Bram's band.")], '', '', [
                R([('A', "Six of us. Bram ran it. We took folk off the roads and we took them to the shrine. Bram said the hole wanted feeding. I did what I was told. I did the heavy work and I held the rope.")], '', '', [
                    R([('P', "Did you believe him?")], '', '', [R([('A', "I didn't think about it. That was the trouble. Then I did think about it, and here I am.")])]),
                    R([('P', "Where is the shrine?")], '', '', [R([('A', "Up top. By the old road. Doesn't matter now. There's no road from here to there.")])]),
                ]),
            ]),
            R([('P', "What is this place, thief?")], '', '', [
                R([('A', "Locks on everything. Good locks. Old ones. I've done locks since I was nine and these ones scare me.")], '', '', [
                    R([('P', "Can you open them?")], '', '', [R([('A', "Not these. There's always a key, though. Somebody always puts the key somewhere.")])]),
                    R([('P', "Who keeps a place like this?")], '', '', [R([('A', "Don't know. Don't want to know.")])]),
                ]),
            ]),
            R([('P', "How do you fare?")], '', '', [
                R([('A', "Hungry. I'm all right. I've had worse.")], '', '', [
                    R([('P', "Good.")]),
                    R([('P', "Tell me if you cannot go on.")], '', '', [R([('A', "I can go on. Don't you worry about me. Worry about you.")])]),
                ]),
            ]),
            R([('P', "You stop before I do. You hear things.")], 'result = (TopicUsed(Depth) > 0);', '', [
                R([('A', "I've always had a nose for it. When summat's wrong I get it in my gut before I know why. I had it the night before they put me down the hole. Didn't listen.")], '', '', [
                    R([('P', "Then say so when you feel it.")], '', '', [R([('A', "I will. You listen when I do.")])]),
                ]),
            ]),
        ]),
        N('Secret', MENU, [R([('P', "The ones you threw. You remember them.")], 'result = (TopicUsed(Depth) > 1) & (TopicUsed(Secret) = 0);', '', [
            R([('A', "All of them. There was a girl kept asking after her cousin. A big lad that thought we were taking him to work for a lord. A woman from the Fallen Oak that spat at Bram. I held the rope. I always held the rope.")], '', '', [
                R([('P', "You will know them when we see them.")], '', '', [R([('A', "I've seen two already. Down here, before you came. I never said.")])]),
                R([('P', "Why tell me?")], '', '', [R([('A', "Somebody should know. Before summat gets me. And so you know what I am, before you decide what to do with me.")])]),
            ]),
        ])]),
        N('Secret 2', MENU, [R([('P', "Tobin. Do you still think I will leave you?")], 'result = (TopicUsed(Depth) > 3) & (TopicUsed(Secret) > 0) & (TopicUsed(Secret 2) = 0);', '', [
            R([('A', "I don't know. I think about it. Every time you go through a door first I think, this is where it happens.")], '', '', [
                R([('P', "I have not left you yet.")], '', '', [R([('A', "No. You haven't. I'm trying to get used to it.")])]),
                R([('P', "I may have to, one day.")], '', '', [R([('A', "Aye. Well. Say so when you do. Don't just go.")])]),
            ]),
        ])]),
        *group_orders("Aye. You'll come back for us? Say you will.", "Aye. Coming."),
        N('Boss Door', ZONE, [R([('A', "Stop. There's summat in there. I can hear it walking. Big lock. We need the key.")])]),
        N('Key', ZONE, [R([('A', "There. That's the key. Told you there'd be one.")])]),
        N('Vault', ZONE, [R([('A', "Another one. Two locks. Somebody's having a laugh at us.")])]),
        N('Closet', ZONE, [R([('A', "Stop. Stop. Summat's wrong here. There's a plate in the floor. Don't tread on it.")])]),
        N('Gate', ZONE, [R([('A', "It's up. Go, go, before it comes down.")])]),
        N('Stairs', ZONE, [R([('A', "Stairs. I'll go down first if you want. I don't mind going first.")])]),
        N('Arrive', ZONE, [R([('A', "Another one. Same as the last one. Key's somewhere.")])]),
        *fight_nodes([("Gods. Right. I'll get round behind it. Hit it when it turns.", '')], [
            "It's on you! I've got it, I've got it!",
            "Get back! It's turned on me, get back!",
            "You're bleeding. Go. I'll keep it off you.",
        ]),
        depth_node({
            1: "Lower. Same as up there. Same smell.",
            2: "Bigger rooms. More places for summat to stand.",
            3: "Smells like a drain. I don't like it here.",
            4: "Brick. Older than up there. Summat's wrong with this place.",
            5: "They dug here. Mind the floor.",
            6: "Old brick again. Older. I've got the feeling.",
        }, "I've stopped counting floors. Just doors now. Just doors."),
        *idle_nodes([
            "Could've been a cobbler. My uncle was a cobbler. Nobody throws a cobbler down a hole.",
            "I'm hungry. Are you hungry? Never mind.",
            "I don't like how quiet it is. I get a feeling.",
        ]),
        N('Big Demon', EVENT, [R([('A', "Gods. Gods, look at it. Get round it. I'll get round it.")])]),
        N('Marlia', EVENT, [R([('A', "That's her. From the Fallen Oak. I held the rope for her. She's looking at me.")], '', '', [
            R([('P', "Keep walking.")], '', '', [R([('A', "Aye. Aye.")])]),
            R([('P', "You held the rope.")], '', '', [R([('A', "I held the rope. I know.")])]),
        ])]),
        N('Hurt', AUTO_HOURLY, [R([('A', "I'm hit. Keep going. I'll keep up.")], HURT)]),
        N('You hurt', AUTO_HOURLY, [R([('A', "You're bleeding bad. Sit down. I'll watch the door.")], YOU_HURT, '', [
            R([('P', "There is no time.")], '', '', [R([('A', "There's time. Sit.")])]),
            R([('P', "A moment, then.")], '', '', [R([('A', "I'll watch the door.")])]),
        ])]),
        N('Part ways', MENU, [R([('P', "Wait here, thief. I will return.")], FOLLOWING, '', [
            R([('A', "You'll come back? Say you'll come back.")], '', PART),
        ])]),
        N('Come along', MENU, [R([('P', "We go.")], NOT_FOLLOWING, '', [
            R([('A', "You came back. All right. Coming.")], '', REJOIN),
        ])]),
    ],
    'assail_plead': ["Don't!", "Wait!", "Stop it!"],
    'assail': [
        N('Negotiate', 0x100002E, [R([('P', "Wait. I mean you no harm.")], '', '? Role.Negotiate = 0 : Role.Negotiate = 1;', [
            R([('A', "You swung at me!")]),
            R([('A', "Stay back. Come at me again and I'll break your arm.")], 'result = (Role.Negotiate = 2) | (Actor[0].Trust(Actor[1]) < -50);'),
            R([('A', "You swung at me. What for? What did I do?")], '', '', [
                R([('P', "I took you for one of the dead.")], '', 'Actor[0].AddRelation(Actor[1], $15);', [
                    R([('A', "I said stop. The dead don't say stop. Look first.")], '', '', [
                        R([('P', "It will not happen again.")], '', '', [R([('A', "All right. Who are you, then?")])]),
                        R([('P', "I make no promises.")], '', '', [R([('A', "Then I'll stay over here.")])]),
                    ]),
                ]),
                R([('P', "You crept up on me.")], '', '', [R([('A', "I walk quiet. I always have. I didn't mean anything by it.")])]),
            ]),
        ])], ['Start Over']),
        N('Start Over', 0x0, [R([('A', "No fighting. I'd lose, and you'd be no better off.")], '', '', [
            R([('P', "Then let us begin again. Who are you?")], '', '', [
                R([('A', "Tobin. My own band put me down here. You?")], '', '', [
                    R([('P', "I do not remember. I woke down here.")], '', '', [
                        R([('A', "Aye. Well. You'll want someone that knows where keys get hidden. I want someone that doesn't leave me behind.")], '', '', [
                            R([('P', "Come with me.")], '', ASSAIL_RECRUIT, [R([('A', "All right. Don't leave me behind.")])]),
                            R([('P', "I go alone.")], '', '', [R([('A', "Suit yourself.")])]),
                        ]),
                    ]),
                ]),
            ]),
            R([('P', "Stay out of my way.")], '', '', [R([('A', "Aye. All right.")])]),
        ])]),
        *assail_engine_nodes(["Don't!", "Wait!", "Stop it!"]),
    ],
}

# in the order they are found (Hunter, 2026-10-22): the same hole, different times, each as deep as
# they got; Tobin on depth 1, Aldric on depth 2 (the proctor one deeper), Mira on depth 3
COMPANIONS = {'Tobin': TOBIN, 'Aldric': ALDRIC, 'Mira': MIRA}

# the dead record each companion recognises (the 'Marlia' node): a shipped enemy record by name;
# make_template gives it the companion's "known" role, and the sight event fires on first focus.
# Aldric's is the proctor: the generator makes that record the boss of the first area of depth 3.
KNOWN_DEAD = {'Aldric': 'Proctor15', 'Mira': 'ZombieOfficeSt16', 'Tobin': 'ToxZombieW32'}

# ------------------------------------------------------ banter (pair topics in the main role)
# A's topic with B: A speaks as 'A', B as 'P' (the partner slot). Opens on its own when both follow.
BOTH_FOLLOWING = 'result = (Actor[0].Role($1F).Activity = 4) & (Actor[1].Role($1F).Activity = 4);'
BANTER = {
    ('Aldric', 'Tobin'): [
        ('The rope', [('A', "You held the rope. There were twelve people taken from those villages. I want to know how many of them you put down that hole."), ('P', "I don't know. Nobody told us their names and we never asked."), ('A', "One was a girl called Elara. Nineteen years old. She had never been out of her village."), ('P', "There was a girl that kept asking after her cousin. Aye. I held the rope for her."), ('A', "If we were up top I would hang you for that. Down here I need every hand I can get. Don't forget which of those is true today.")]),
        ('Standing', [('A', "When the dead come at us, get behind me. Don't run past me."), ('P', "I don't run. I'll go round them."), ('A', "Then go round them behind me. I have the shield."), ('P', "Aye. All right.")]),
        ('The shrine', [('A', "This shrine Bram prayed at. What was on it?"), ('P', "A man with a crown. Folk kneeling to him. Bram said it was the Guardian."), ('A', "And he fed it people."), ('P', "He fed it people. I held the rope. You know that already.")]),
    ],
    ('Tobin', 'Aldric'): [
        ('In front', [('A', "You keep going in front. Every door."), ('P', "That's what a soldier's for."), ('A', "I've known soldiers. They don't all do that."), ('P', "This one does.")]),
        ('Leaving', [('A', "If it goes bad, you'll leave me. Everybody does."), ('P', "I won't leave you."), ('A', "You say that."), ('P', "I say it because I've done it once. I won't do it again.")]),
        ('The sash', [('A', "You still wear the sash. Down here."), ('P', "It's mine. I've worn it for twenty years."), ('A', "Aye. I suppose you have."), ('P', "Keep walking.")]),
    ],
    ('Aldric', 'Mira'): [
        ('No way up', [('A', "You count the stairs as we go. Have any of them gone up?"), ('P', "None. I've counted every one and none of them go up."), ('A', "Then there is no way out of here."), ('P', "There is still down.")]),
        ('The proctor', [('A', "You asked where my proctor is. I don't know."), ('P', "You said he was ahead of you."), ('A', "I said that."), ('P', "I won't ask again.")]),
        ('Her', [('A', "Your master. The one who died. Did she send you down here?"), ('P', "No. She wanted to know. I came because she couldn't."), ('A', "That's a poor reason."), ('P', "I know.")]),
    ],
    ('Mira', 'Aldric'): [
        ('Looking', [('A', "You look at every one of the dead before you put it down. In the face."), ('P', "Aye."), ('A', "Who are you looking for?"), ('P', "Somebody I owe.")]),
        ('Counting', [('A', "You count the ones you knew. Four, you said."), ('P', "Four from the list. Aye."), ('A', "Why count them?"), ('P', "Somebody should. Nobody else is going to.")]),
        ('The rope', [('A', "I came down on a rope. Did you?"), ('P', "Aye. A rope."), ('A', "Was it hard? Letting go of the top?"), ('P', "Don't ask me that.")]),
    ],
    ('Mira', 'Tobin'): [
        ('Trust', [('A', "You watch me when you think I'm not looking."), ('P', "I watch everybody."), ('A', "I'm not going to hurt you, Tobin."), ('P', "Everybody says that. Then they do.")]),
        ('The shrine', [('A', "The hole was by a shrine. Was anything carved on it?"), ('P', "A man with a crown. Folk kneeling to him."), ('A', "The Guardian."), ('P', "Bram said that. You know it too?"), ('A', "I've read it. It isn't a good thing to know.")]),
        ('Quiet', [('A', "You go quiet before something comes. I've noticed."), ('P', "I get a feeling. In my gut."), ('A', "Say it out loud, when you get it."), ('P', "I will. You listen.")]),
        ('Lesson 1', [('A', "That feeling of yours. When it comes, don't push it away. Look at it."), ('P', "Look at it how? It's in my gut."), ('A', "Then look at your gut. Where does it sit? Is it cold or warm?"), ('P', "Cold. Like a stone."), ('A', "Good. Next time, find the stone before anything comes.")]),
        ('Lesson 2', [('A', "Did you find the stone?"), ('P', "Once. In the last room. Before the door opened."), ('A', "Before the door opened. That's it. Keep finding it."), ('P', "Why do you care?"), ('A', "Because it's the only thing down here that warns us.")]),
        ('Lesson 3', [('A', "When you find the stone, don't hold it. Let it go through your hands."), ('P', "That makes no sense."), ('A', "It will. Do it anyway."), ('P', "Aye. All right. Let it go through my hands.")]),
    ],
    ('Tobin', 'Mira'): [
        ('Same hole', [('A', "You came down the hole and all. On a rope, you said. Who held it?"), ('P', "Nobody. I tied it off."), ('A', "On your own."), ('P', "On my own.")]),
        ('Books', [('A', "What do they want with you, the Order? You don't look like much."), ('P', "I copy their books."), ('A', "Down here?"), ('P', "No. Not down here.")]),
        ('Hungry', [('A', "You don't eat. I've watched. You don't eat."), ('P', "I'm not hungry."), ('A', "Everybody's hungry."), ('P', "Then I'll eat later.")]),
    ],
}

# ------------------------------------------------------ chains: you ask A about B
# The game only ever pairs two actors, so a talk that passes between three people is three
# conversations run one after another: your talk-list line to A (A answers and, as the dialogue
# closes, opens A's topic with B at the middle node), A and B's exchange (its last line opens
# B's topic with you), then B's line to you. Each chain is asked once.
#   ask:     (your line, A's answer)
#   between: A and B's lines ('A' = A, 'P' = B)
#   after:   (B's line to you, [your replies]); a reply may be ("text", condition)
# Only things both of them have in front of them: each other, the dead, the rope, the way down.
CHAINS = {
    ('Aldric', 'Mira'): dict(
        ask=("The apprentice. Does she hold up?", "She holds up. She doesn't eat and she doesn't sleep, and she still keeps pace with me. I'll have a word with her."),
        between=[('A', "You were asked after."), ('P', "Asked what?"), ('A', "Whether you hold up. I said you do."), ('P', "I do.")],
        after=("Aldric says you asked after me. I'm all right. If I'm not, I'll say so.", ["See that you do.", "Good."]),
    ),
    ('Aldric', 'Tobin'): dict(
        ask=("The thief. Can he be trusted?", "At your back, yes. With your purse, no. He'll not run from a fight. I've watched him. I'll tell him you asked."),
        between=[('A', "You were asked about. Whether you can be trusted."), ('P', "What did you say?"), ('A', "That you'll not run. It's the one good thing I know of you."), ('P', "It's enough.")],
        after=("The soldier says you asked if I'm to be trusted. I've not taken anything of yours. Count your things if you like.", ["I have counted them.", "I believe you."]),
    ),
    ('Mira', 'Aldric'): dict(
        ask=("The soldier. What do you make of him?", "He goes in front of everything. He looks every one of the dead in the face before he puts it down. I think he's looking for someone. I'll ask him."),
        between=[('A', "Who are you looking for? Among the dead."), ('P', "You've asked me that before."), ('A', "You didn't answer."), ('P', "The man I was sworn to. If I see him, I'll know him.")],
        after=("The girl says you set her to asking me who I look for. If you want to know a thing about me, ask me yourself.", ["Then I ask. Who is it?", "Fair enough."]),
    ),
    ('Mira', 'Tobin'): dict(
        ask=("The thief. He watches you.", "He watches everyone. His own people put him down the hole. He thinks we'll do the same. I'll talk to him."),
        between=[('A', "Nobody here is going to put you down a hole, Tobin."), ('P', "You don't know that."), ('A', "I know I won't."), ('P', "Aye. Well. You're the only one that's said it.")],
        after=("Your apprentice says you've been talking about me. Say it to my face next time. I can take it.", ["I asked whether you were well.", "I will."]),
    ),
    ('Tobin', 'Aldric'): dict(
        ask=("The soldier. You keep clear of him.", "He wants to hang me. He said so. He says he won't, down here. I believe him about the second part. Mostly."),
        between=[('A', "I was asked why I keep clear of you."), ('P', "And?"), ('A', "I said you'd hang me."), ('P', "Up top I would. Down here I said I won't, and I keep my word."), ('A', "Aye. I'm counting on it.")],
        after=("The thief says you asked him about me. He's right to keep clear. I said I'd hang him and I meant it. I said not down here, and I meant that too.", ["Keep to the second.", "Good."]),
    ),
    ('Tobin', 'Mira'): dict(
        ask=("The apprentice. What do you make of her?", "She's quiet. Too quiet. I get the feeling off her sometimes, same as before summat comes. Don't know why. She's never done me harm."),
        between=[('A', "I get a feeling off you. Like before a thing goes wrong."), ('P', "What kind of feeling?"), ('A', "Don't know. In my gut. Like there's more of you than I can see."), ('P', "There isn't. Keep walking.")],
        after=("Tobin says you asked about me. He says I make him uneasy. I don't mean to.", ["He means no harm by it.", "Noted."]),
    ),
}
# Mira, once she has told you: Tobin's unease is the talent he can feel and cannot name
CHAIN_TOLD = {
    ('Tobin', 'Mira'): ("Tobin says you asked about me. He says I make him uneasy. He's not wrong. He feels it. He doesn't know what it is.", ["Keep it so.", "He means no harm by it."]),
}


# ------------------------------------------------------ one voice per occasion
# Hunter (2026-10-22): nobody talks over anybody. Each occasion (a talk-zone spot, the hurt line,
# the huge beast, each boss call-out, each first casting) has an order of speakers. Every
# companion keeps its own node for the occasion, in its own voice, but only one is opened: the
# first in the order who is in the party (the mod places that one's zone; for the castings the
# mod picks the observer). The opened node's last line runs
# `Actor[0].ActivateTopicN(me, next, <occasion>, 1)`, which opens the hop below in the
# speaker's banter topic with the next in the order (it plays only when that one is near). So
# at most two of them speak at any one occasion, one after the other, each saying a different
# thing. Big Demon is a sight event each observer raises for itself, so it has one speaker.
SPOT_ORDER = {
    'Boss Door': ['Aldric', 'Tobin', 'Mira'], 'Gate': ['Aldric', 'Mira', 'Tobin'], 'Arrive': ['Aldric', 'Tobin', 'Mira'],
    'Boss': ['Aldric', 'Tobin', 'Mira'], 'Fight 1': ['Aldric', 'Mira', 'Tobin'], 'Fight 2': ['Aldric', 'Tobin', 'Mira'],
    'Fight 3': ['Aldric', 'Mira', 'Tobin'], 'You hurt': ['Aldric', 'Tobin', 'Mira'],
    'Stairs': ['Mira', 'Aldric', 'Tobin'], 'Depth': ['Mira', 'Tobin', 'Aldric'], 'Vault': ['Mira', 'Tobin', 'Aldric'],
    'Key': ['Tobin', 'Aldric', 'Mira'], 'Closet': ['Tobin', 'Mira', 'Aldric'], 'Big Demon': ['Tobin'],
    # first castings (the mod opens the first present observer's node; Lua, not a zone)
    'Saw you': ['Aldric', 'Mira', 'Tobin'], 'Saw Mira': ['Aldric', 'Tobin'], 'Spark': ['Tobin'],
    # a companion's death (the mod opens the first present survivor's node; Lua)
    'Dead Tobin': ['Aldric', 'Mira'], 'Dead Aldric': ['Mira', 'Tobin'], 'Dead Mira': ['Aldric', 'Tobin'],
}
# the hops: A's node in its banter topic with B ('A' = A, 'P' = B)
HOPS = {
    ('Aldric', 'Tobin'): {
        'Boss Door': [('A', "Thief. You hear that?"), ('P', "I hear it. Summat big, walking about. Key first.")],
        'Arrive': [('A', "Thief. Where would you put the key, in a place like this?"), ('P', "Far from the door. They always put it far from the door.")],
        'Boss': [('A', "Thief. Get round behind it. Keep out of my swing."), ('P', "Behind it. Aye. Don't swing wide.")],
        'Fight 2': [('A', "Thief! Its side!"), ('P', "I'm on it! I'm on it!")],
        'You hurt': [('A', "Thief. The door."), ('P', "Watching it.")],
        'Saw Mira': [('A', "Did you see that? The girl."), ('P', "I felt it. I told you I felt summat off her.")],
        'Dead Mira': [('A', "Thief. Stay close. There's two of us now."), ('P', "Aye. Two.")],
    },
    ('Aldric', 'Mira'): {
        'Gate': [('A', "The gate's up. Are you hurt?"), ('P', "No. Go through. I'm behind you.")],
        'Fight 1': [('A', "Back. Get back behind me."), ('P', "I'm back. Hit it when it stops.")],
        'Fight 3': [('A', "Mira. Behind me. Now."), ('P', "I'm here. Hold it still.")],
        'Key': [('A', "The key. Mark where it was, girl, in case there's another."), ('P', "I will.")],
        'Big Demon': [('A', "Girl. Stay back from that one."), ('P', "I'm staying back.")],
        'Saw you': [('A', "You saw that."), ('P', "I saw it.")],
        'Dead Tobin': [('A', "The thief's gone."), ('P', "I know. I counted him.")],
    },
    ('Mira', 'Aldric'): {
        'Stairs': [('A', "Aldric."), ('P', "I'll go first."), ('A', "Go, then.")],
        'Closet': [('A', "There's a plate there. Don't step on it."), ('P', "I see it. Nobody steps on it.")],
        'Spark': [('A', "Aldric. Did you see what Tobin did?"), ('P', "I saw it. Gods below. The thief.")],
    },
    ('Mira', 'Tobin'): {
        'Depth': [('A', "You've gone quiet."), ('P', "I've got the feeling. Summat's down here."), ('A', "I know.")],
        'Vault': [('A', "Its key will be somewhere else."), ('P', "Two keys. Somebody's having a laugh at us."), ('A', "Somebody built this to be slow.")],
        'Gate': [('A', "It's up. Go through."), ('P', "Going. Don't shut it on me.")],
        'Fight 1': [('A', "Tobin. Get back."), ('P', "I'm back. I'm back.")],
        'Fight 3': [('A', "Tobin. Behind me."), ('P', "Behind you. Aye.")],
        'Saw you': [('A', "Tobin. Did you see?"), ('P', "I saw. I don't want to talk about it.")],
        'Dead Aldric': [('A', "He's gone, Tobin."), ('P', "I know. I saw. Don't talk to me for a bit.")],
    },
    ('Tobin', 'Aldric'): {
        'Key': [('A', "Told you there'd be one."), ('P', "Good. Now the door."), ('A', "Aye. The door.")],
        'Big Demon': [('A', "Gods. Look at the size of it."), ('P', "I see it. Get round it. I'll take the front.")],
        'Depth': [('A', "Lower again. I've got the feeling already."), ('P', "Then stay close. In front of me if you have to.")],
        'Vault': [('A', "Two locks. Somebody's having a laugh at us."), ('P', "Then we find two keys.")],
    },
    ('Tobin', 'Mira'): {
        'Closet': [('A', "Plate in the floor. Don't tread on it."), ('P', "I see it. There's a gate beside it."), ('A', "Don't like the gate neither.")],
        'Boss Door': [('A', "Summat's in there. I can hear it walking."), ('P', "So can I. We need the key first.")],
        'Arrive': [('A', "Same as the last. Key's somewhere."), ('P', "Far from the door, I expect.")],
        'Boss': [('A', "Gods. Right. I'll get round behind it."), ('P', "Go when it turns. I'll tell you when.")],
        'Fight 2': [('A', "It's on me! It's on me!"), ('P', "Get back! Get back behind him!")],
        'You hurt': [('A', "Watch the door for me."), ('P', "I'm watching it.")],
        'Spark': [('A', "What was that? What did I do?"), ('P', "That was you, Tobin. Breathe. It was you.")],
    },
}

# ------------------------------------------------------ deaths (the mod opens these)
# One line each on the death of each other companion, in their own voice, to you. The talk-list
# lines about a dead companion stop being offered (LuaFlag endless_dead_<index>), and the hops
# with a dead partner do not play (the partner's Health).
DEATHS = {
    'Aldric': {
        'Dead Tobin': ("The thief's down. I said I'd not leave anyone again. I didn't leave him. It wasn't enough.", ["It was not your doing.", "We go on, soldier."]),
        'Dead Mira': ("The girl. Gods below. She was behind me. She was meant to be behind me.", ["She was. It was not your doing.", "We go on, soldier."]),
    },
    'Mira': {
        'Dead Aldric': ("Aldric. He went in front. He always went in front. I'll count him with the others.", ["Count him.", "We go on, apprentice."]),
        'Dead Tobin': ("Tobin. I told him nobody here would hurt him. I meant it. It wasn't enough.", ["It was not your doing.", "We go on, apprentice."]),
    },
    'Tobin': {
        'Dead Aldric': ("He's dead. The soldier. He said he'd not leave me, and he didn't. He's dead instead.", ["He kept his word.", "We go on, thief."]),
        'Dead Mira': ("She's dead. She said she'd not hurt me and she never did. I had the feeling before it came and I said nothing.", ["Say it next time.", "We go on, thief."]),
    },
}

# Mourning (Hunter): every so often, not only at the death. Three lines per survivor per dead
# companion, in order, once each, an hour of world time apart, while following.
MOURN = 0x01070101  # opens on its own, one use, the hourly gap of the idle lines
MOURNING = {
    'Aldric': {
        'Tobin': ["I keep looking for the thief at my back. Habit.",
                  "He'd have found that key quicker than we did.",
                  "Twelve names on the list. I never put his on it. I should have."],
        'Mira': ["The girl counted the stairs. I've started counting them. I don't know why.",
                 "She'd have felt that one coming.",
                 "I had her behind me the whole way down. One door. One."],
    },
    'Mira': {
        'Aldric': ["Aldric would have gone through that door first.",
                   "I count the stairs for him now. He asked me once how many.",
                   "He looked for his proctor in every face. I look for his now. I don't mean to."],
        'Tobin': ["Tobin would have gone quiet before that one. I miss the quiet.",
                  "I told him to find the stone in his gut. I hope he found it, at the end.",
                  "He never did eat. I should have made him."],
    },
    'Tobin': {
        'Aldric': ["The soldier would've gone in first. I keep waiting for him to.",
                   "He wore that sash twenty years. Should've taken it off him. Should've kept it.",
                   "He said up top he'd hang me. I'd have let him, if it got him up top."],
        'Mira': ["She never ate. I think about that. I don't know why.",
                 "I get the feeling and I look round for her. Then I remember.",
                 "She said nobody'd put me down a hole. She kept to it. Weren't her fault."],
    },
}

# ------------------------------------------------------ first castings (the mod opens these)
# 'Saw you': you cast for the first time in front of them. 'Saw Mira': Mira's first casting
# (after her reveal). 'Spark': Tobin's first casting, in a boss fight, after enough time with
# Mira; he did not know he had it.
REACTIONS = {
    'Aldric': [
        N('Saw you', ZONE, [R([('A', "What was that? What did you just do?")], '', '', [
            R([('P', "The same thing the dead do. I will not use it on you.")], '', '', [R([('A', "See that you don't. I'll stay in front. It doesn't change that.")])]),
            R([('P', "Keep walking, soldier.")], '', '', [R([('A', "Aye. I'll keep walking.")])]),
        ])]),
        N('Saw Mira', ZONE, [R([('A', "The girl. The Order sent us a shaper and told us nothing. I should have known. Good. Point it at them, girl, and not at us.")])]),
    ],
    'Mira': [
        N('Saw you', ZONE, [
            R([('A', "You have the talent. I didn't know. You should have said.")], NOT_TOLD, '', [
                R([('P', "So should you, apprentice.")], '', '', [R([('A', "Yes. I know.")])]),
                R([('P', "Now you know.")]),
            ]),
            R([('A', "So that's two of us. Good. Don't push it. It pushes back.")], TOLD, '', [
                R([('P', "I know.")]),
                R([('P', "What do you mean, it pushes back?")], '', '', [R([('A', "The more you use it, the more you feel them. The dead. All of them at once. Rest between.")])]),
            ]),
        ]),
    ],
    'Tobin': [
        N('Saw you', ZONE, [R([('A', "What. What was that. You're one of them. You're like the ones in the books.")], '', '', [
            R([('P', "I am the one who pulled you out of that room. Nothing else has changed.")], '', '', [R([('A', "Aye. Aye. All right. Don't do it near me.")])]),
            R([('P', "Keep walking, thief.")], '', '', [R([('A', "Walking. I'm walking.")])]),
        ])]),
        N('Saw Mira', ZONE, [R([('A', "I knew it. I knew there was summat off her. I felt it in my gut the first day.")])]),
        N('Spark', ZONE, [R([('A', "What. What was that. That came out of me. Did you see it?")], '', '', [
            R([('P', "I saw it. Do it again.")], '', '', [R([('A', "I don't know how I did it the first time.")])]),
            R([('P', "Later. Fight now.")], '', '', [R([('A', "Fighting. Aye.")])]),
        ])]),
    ],
}
