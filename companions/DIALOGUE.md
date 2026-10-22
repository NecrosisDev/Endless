# Endless companion dialogue (built 2026-10-22, static: read back from the roles file, not played)

The companion speaks by name, **You** is the player. Indentation = which line answers which.
Node names are what the engine opens: **Boss Door / Key / Vault / Closet / Gate / Stairs / Arrive / Depth /
Boss** from the zones the generator places (Depth: one line per new depth; Boss: the boss room), **Fight
1..3** on their own in the boss room while you are below half health, **Big Demon / Marlia** from the
sight events (a huge beast; the one dead person each of them knows), **Hurt / You hurt** on their own
below 40 health, **Idle 1..3** on their own while walking, **Talk / Secret / Secret 2 / Hold all / Follow
all / Part ways / Come along** from the talk list, **Aggressor / Threatened / Engage / Wary / Plead** by
the engine when you attack them. One voice per occasion: each zone, the hurt line, each call-out and each
first casting has an order of speakers (Aldric first at the boss door, gate, arrival, boss room, call-outs
and your wounds; Mira first at the stairs, a new depth and the vault; Tobin first at the key and the closet
plate, and alone for the beast); the first of them in the party speaks to you, and that line opens one
short exchange with the next in the order, listed under the banter headings by the same name. **Saw you /
Saw Mira / Spark** are the first castings (yours, Mira's, Tobin's), opened by the mod when it sees one;
**Dead <name>** is the first present survivor's line on a companion's death, then one exchange between the
two left; **Mourn <name> 1..3** come on their own afterwards, an hour apart, once each. Lines about a
dead companion are no longer offered and exchanges with one do not play.
Banter nodes open on their own when both follow. **About <B>** is a
talk-list line you say to one companion about another (once each): as that dialogue closes, the two of
them have the **Asked** exchange under the banter heading, and its end opens the other one's **<A> asked**
line to you. Three conversations chained by script; whether the hand-off plays is unseen.

## Tobin

### First meeting (their own role; the "Join me" yes runs the recruit script)

### Greeting

- Tobin: Stop there. Stop. You're alive? Say summat.

### Who are you?

- **You**: Who are you?
    - Tobin: Tobin. I did the heavy work for a band up top. Bram's lot.
    - Tobin: You got thrown in and all, didn't you. You lived. Most of them don't.
        - **You**: Thrown in. You would know about that.
            - Tobin: Aye. I would. I held the rope. Then they put me on the end of it. I fell a long way. It's deeper here than where the rest went in. There's no climbing out. I tried. I tried for days.
                - **You**: Why did they throw you in?
                - **You**: How many did you throw?
                    - Tobin: I never counted. Nine. Ten. Bram said the hole wanted feeding. I never asked what he meant. I should have asked sooner.
        - **You**: I do not remember who I am.
            - Tobin: None of them did, after. Bram said it was the fall. I don't reckon it was the fall.

### Why here

- **You**: Why did they throw you in?
    - Tobin: I asked Bram what we were feeding. He didn't like being asked. He kept us at the old shrine, where the carved folk are kneeling, and he said the hole wanted feeding or the dead would come up out of it. So they fed it me.
        - **You**: And do the dead come up out of it?
            - Tobin: Not that I ever saw. Bram believed it. He prayed at that shrine every night. I reckon he's still feeding it.
        - **You**: You had it coming.
            - Tobin: Aye. I know that. I don't need you to say it.

### Join me

- **You**: Come with me, thief. You know where keys get hidden. I can fight.
    - Tobin: Why? What do you want me for? Last lot that wanted me put me down a hole.
        - **You**: I want someone who can find a key and stand his ground. Nothing else.
            - Tobin: All right. All right. I'll come. You leave me behind, I'll know what you are.
        - **You**: You will earn your keep. For every one you threw.
            - Tobin: Aye. That's fair. That's more than fair.
                - Tobin: I'll come. I'm not slow and I'm not soft.

### Not now

- **You**: I want no bandit at my back.
    - Tobin: Suit yourself. I'll be here.

### Reconsidered

- **You**: I have thought again, thief. Come with me.
    - Tobin: Changed your mind, did you. All right. Don't leave me behind.

### Aggressor

- _(Tobin says nothing; the engine runs a script)_

### Threatened

- _(Tobin says nothing; the engine runs a script)_

### Wary

- Tobin: Nothing in my hands. Look. There's nothing in my hands.

_(on approach: `StartDialogue(Greeting);`)_

### Following you (main role)

### Talk

- **You**: Tell me of Bram's band.
    - Tobin: Six of us. Bram ran it. We took folk off the roads and we took them to the shrine. Bram said the hole wanted feeding. I did what I was told. I did the heavy work and I held the rope.
        - **You**: Did you believe him?
            - Tobin: I didn't think about it. That was the trouble. Then I did think about it, and here I am.
        - **You**: Where is the shrine?
            - Tobin: Up top. By the old road. Doesn't matter now. There's no road from here to there.
- **You**: What is this place, thief?
    - Tobin: Locks on everything. Good locks. Old ones. I've done locks since I was nine and these ones scare me.
        - **You**: Can you open them?
            - Tobin: Not these. There's always a key, though. Somebody always puts the key somewhere.
        - **You**: Who keeps a place like this?
            - Tobin: Don't know. Don't want to know.
- **You**: How do you fare?
    - Tobin: Hungry. I'm all right. I've had worse.
        - **You**: Good.
        - **You**: Tell me if you cannot go on.
            - Tobin: I can go on. Don't you worry about me. Worry about you.
- **You**: You stop before I do. You hear things.
    - Tobin: I've always had a nose for it. When summat's wrong I get it in my gut before I know why. I had it the night before they put me down the hole. Didn't listen.
        - **You**: Then say so when you feel it.
            - Tobin: I will. You listen when I do.

### Secret

- **You**: The ones you threw. You remember them.
    - Tobin: All of them. There was a girl kept asking after her cousin. A big lad that thought we were taking him to work for a lord. A woman from the Fallen Oak that spat at Bram. I held the rope. I always held the rope.
        - **You**: You will know them when we see them.
            - Tobin: I've seen two already. Down here, before you came. I never said.
        - **You**: Why tell me?
            - Tobin: Somebody should know. Before summat gets me. And so you know what I am, before you decide what to do with me.

### Secret 2

- **You**: Tobin. Do you still think I will leave you?
    - Tobin: I don't know. I think about it. Every time you go through a door first I think, this is where it happens.
        - **You**: I have not left you yet.
            - Tobin: No. You haven't. I'm trying to get used to it.
        - **You**: I may have to, one day.
            - Tobin: Aye. Well. Say so when you do. Don't just go.

### Hold all

- **You**: All of you. Wait here.
- Tobin: Aye. You'll come back for us? Say you will.

### Follow all

- **You**: All of you. With me.
- Tobin: Aye. Coming.

### Boss Door

- Tobin: Stop. There's summat in there. I can hear it walking. Big lock. We need the key.

### Key

- Tobin: There. That's the key. Told you there'd be one.

### Vault

- Tobin: Another one. Two locks. Somebody's having a laugh at us.

### Closet

- Tobin: Stop. Stop. Summat's wrong here. There's a plate in the floor. Don't tread on it.

### Gate

- Tobin: It's up. Go, go, before it comes down.

### Stairs

- Tobin: Stairs. I'll go down first if you want. I don't mind going first.

### Arrive

- Tobin: Another one. Same as the last one. Key's somewhere.

### Boss

- Tobin: Gods. Right. I'll get round behind it. Hit it when it turns.

### Fight 1

- Tobin: It's on you! I've got it, I've got it!

### Fight 2

- Tobin: Get back! It's turned on me, get back!

### Fight 3

- Tobin: You're bleeding. Go. I'll keep it off you.

### Depth

- Tobin: Lower. Same as up there. Same smell.
- Tobin: Bigger rooms. More places for summat to stand.
- Tobin: Smells like a drain. I don't like it here.
- Tobin: Brick. Older than up there. Summat's wrong with this place.
- Tobin: They dug here. Mind the floor.
- Tobin: Old brick again. Older. I've got the feeling.
- Tobin: I've stopped counting floors. Just doors now. Just doors.

### Idle 1

- Tobin: Could've been a cobbler. My uncle was a cobbler. Nobody throws a cobbler down a hole.

### Idle 2

- Tobin: I'm hungry. Are you hungry? Never mind.

### Idle 3

- Tobin: I don't like how quiet it is. I get a feeling.

### Big Demon

- Tobin: Gods. Gods, look at it. Get round it. I'll get round it.

### Marlia

- Tobin: That's her. From the Fallen Oak. I held the rope for her. She's looking at me.
    - **You**: Keep walking.
        - Tobin: Aye. Aye.
    - **You**: You held the rope.
        - Tobin: I held the rope. I know.

### Hurt

- Tobin: I'm hit. Keep going. I'll keep up.

### You hurt

- Tobin: You're bleeding bad. Sit down. I'll watch the door.
    - **You**: There is no time.
        - Tobin: There's time. Sit.
    - **You**: A moment, then.
        - Tobin: I'll watch the door.

### Part ways

- **You**: Wait here, thief. I will return.
    - Tobin: You'll come back? Say you'll come back.

### Come along

- **You**: We go.
    - Tobin: You came back. All right. Coming.

### Saw you

- Tobin: What. What was that. You're one of them. You're like the ones in the books.
    - **You**: I am the one who pulled you out of that room. Nothing else has changed.
        - Tobin: Aye. Aye. All right. Don't do it near me.
    - **You**: Keep walking, thief.
        - Tobin: Walking. I'm walking.

### Saw Mira

- Tobin: I knew it. I knew there was summat off her. I felt it in my gut the first day.

### Spark

- Tobin: What. What was that. That came out of me. Did you see it?
    - **You**: I saw it. Do it again.
        - Tobin: I don't know how I did it the first time.
    - **You**: Later. Fight now.
        - Tobin: Fighting. Aye.

### Dead Aldric

- Tobin: He's dead. The soldier. He said he'd not leave me, and he didn't. He's dead instead.
    - **You**: He kept his word.
    - **You**: We go on, thief.

### Dead Mira

- Tobin: She's dead. She said she'd not hurt me and she never did. I had the feeling before it came and I said nothing.
    - **You**: Say it next time.
    - **You**: We go on, thief.

### Mourn Aldric 1

- Tobin: The soldier would've gone in first. I keep waiting for him to.

### Mourn Aldric 2

- Tobin: He wore that sash twenty years. Should've taken it off him. Should've kept it.

### Mourn Aldric 3

- Tobin: He said up top he'd hang me. I'd have let him, if it got him up top.

### Mourn Mira 1

- Tobin: She never ate. I think about that. I don't know why.

### Mourn Mira 2

- Tobin: I get the feeling and I look round for her. Then I remember.

### Mourn Mira 3

- Tobin: She said nobody'd put me down a hole. She kept to it. Weren't her fault.

### Aldric asked

- Tobin: The soldier says you asked if I'm to be trusted. I've not taken anything of yours. Count your things if you like.
    - **You**: I have counted them.
    - **You**: I believe you.

### Mira asked

- Tobin: Your apprentice says you've been talking about me. Say it to my face next time. I can take it.
    - **You**: I asked whether you were well.
    - **You**: I will.

### About Aldric

- **You**: The soldier. You keep clear of him.
- Tobin: He wants to hang me. He said so. He says he won't, down here. I believe him about the second part. Mostly.

### About Mira

- **You**: The apprentice. What do you make of her?
- Tobin: She's quiet. Too quiet. I get the feeling off her sometimes, same as before summat comes. Don't know why. She's never done me harm.

### Banter with Aldric (opens on its own when both follow you, once an hour each)

### In front

- Tobin: You keep going in front. Every door.
- Aldric: That's what a soldier's for.
- Tobin: I've known soldiers. They don't all do that.
- Aldric: This one does.

### Leaving

- Tobin: If it goes bad, you'll leave me. Everybody does.
- Aldric: I won't leave you.
- Tobin: You say that.
- Aldric: I say it because I've done it once. I won't do it again.

### The sash

- Tobin: You still wear the sash. Down here.
- Aldric: It's mine. I've worn it for twenty years.
- Tobin: Aye. I suppose you have.
- Aldric: Keep walking.

### Key

- Tobin: Told you there'd be one.
- Aldric: Good. Now the door.
- Tobin: Aye. The door.

### Big Demon

- Tobin: Gods. Look at the size of it.
- Aldric: I see it. Get round it. I'll take the front.

### Depth

- Tobin: Lower again. I've got the feeling already.
- Aldric: Then stay close. In front of me if you have to.

### Vault

- Tobin: Two locks. Somebody's having a laugh at us.
- Aldric: Then we find two keys.

### Asked Aldric

- Tobin: I was asked why I keep clear of you.
- Aldric: And?
- Tobin: I said you'd hang me.
- Aldric: Up top I would. Down here I said I won't, and I keep my word.
- Tobin: Aye. I'm counting on it.

### Banter with Mira (opens on its own when both follow you, once an hour each)

### Same hole

- Tobin: You came down the hole and all. On a rope, you said. Who held it?
- Mira: Nobody. I tied it off.
- Tobin: On your own.
- Mira: On my own.

### Books

- Tobin: What do they want with you, the Order? You don't look like much.
- Mira: I copy their books.
- Tobin: Down here?
- Mira: No. Not down here.

### Hungry

- Tobin: You don't eat. I've watched. You don't eat.
- Mira: I'm not hungry.
- Tobin: Everybody's hungry.
- Mira: Then I'll eat later.

### Closet

- Tobin: Plate in the floor. Don't tread on it.
- Mira: I see it. There's a gate beside it.
- Tobin: Don't like the gate neither.

### Boss Door

- Tobin: Summat's in there. I can hear it walking.
- Mira: So can I. We need the key first.

### Arrive

- Tobin: Same as the last. Key's somewhere.
- Mira: Far from the door, I expect.

### Boss

- Tobin: Gods. Right. I'll get round behind it.
- Mira: Go when it turns. I'll tell you when.

### Fight 2

- Tobin: It's on me! It's on me!
- Mira: Get back! Get back behind him!

### You hurt

- Tobin: Watch the door for me.
- Mira: I'm watching it.

### Spark

- Tobin: What was that? What did I do?
- Mira: That was you, Tobin. Breathe. It was you.

### Asked Mira

- Tobin: I get a feeling off you. Like before a thing goes wrong.
- Mira: What kind of feeling?
- Tobin: Don't know. In my gut. Like there's more of you than I can see.
- Mira: There isn't. Keep walking.

### If you attack them first (assail role)

### Negotiate

- **You**: Wait. I mean you no harm.
    - Tobin: You swung at me!
    - Tobin: Stay back. Come at me again and I'll break your arm.
    - Tobin: You swung at me. What for? What did I do?
        - **You**: I took you for one of the dead.
            - Tobin: I said stop. The dead don't say stop. Look first.
                - **You**: It will not happen again.
                    - Tobin: All right. Who are you, then?
                - **You**: I make no promises.
                    - Tobin: Then I'll stay over here.
        - **You**: You crept up on me.
            - Tobin: I walk quiet. I always have. I didn't mean anything by it.

### Start Over

- Tobin: No fighting. I'd lose, and you'd be no better off.
    - **You**: Then let us begin again. Who are you?
        - Tobin: Tobin. My own band put me down here. You?
            - **You**: I do not remember. I woke down here.
                - Tobin: Aye. Well. You'll want someone that knows where keys get hidden. I want someone that doesn't leave me behind.
                    - **You**: Come with me.
                        - Tobin: All right. Don't leave me behind.
                    - **You**: I go alone.
                        - Tobin: Suit yourself.
    - **You**: Stay out of my way.
        - Tobin: Aye. All right.

### Plead

- Tobin: Don't!
- Tobin: Wait!
- Tobin: Stop it!

### Aggressor

- _(Tobin says nothing; the engine runs a script)_

### Engage

- _(Tobin says nothing; the engine runs a script)_

## Aldric

### First meeting (their own role; the "Join me" yes runs the recruit script)

### Greeting

- Aldric: Stay there. Stay where you are. Are you alive?

### Who are you?

- **You**: Who are you?
    - Aldric: Aldric. I'm a soldier of Ardent. I came down after the proctor. He was sent about the folk missing from the villages.
    - Aldric: Who are you?
        - **You**: I do not know. I woke on the ground down here.
            - Aldric: Aye. Everybody I've met down here says that. There aren't many to ask.
                - **You**: Where is the proctor?
                - **You**: Who have you met?
                    - Aldric: Four of the missing. They were dead and walking. I had to put them down. That isn't what we came for.
        - **You**: That is my concern.
            - Aldric: All right. All right. Only keep your hands where I can see them.

### Why here

- **You**: Where is the proctor?
    - Aldric: Ahead of me. He went down first. I came after. I've been looking for him since I landed and I haven't found him.
        - **You**: Why did he go first?
            - Aldric: He was the proctor. He went where he liked. I was to follow him down. I did. Later.
        - **You**: What will you do now?
            - Aldric: Find him. Or find out. I can't go back up and say I don't know.

### Join me

- **You**: Come with me, soldier. There is no way up. I go down.
    - Aldric: There's no up. I've looked at every stair. Aye. I'll come. I'll go first, if you want. I'd rather go first.
        - **You**: Then come. Keep behind me.
            - Aldric: Behind you. If that's how you want it.
        - **You**: You will do as I say.
            - Aldric: Aye. What do you mean to do?
                - **You**: Find the key. Open the door. Kill what is behind it. Take the stairs.
                    - Aldric: Then I'll be in front of you when the door opens. Lead on.
                - **You**: I have not decided.
                    - Aldric: Then I'll wait. I'm not going anywhere on my own.

### Not now

- **You**: I go alone.
    - Aldric: Don't. Don't go alone. There's nothing down here but the dead.
        - **You**: I will manage.
            - Aldric: Then I'll be here. If you come back this way, I'll be here.
        - **You**: Stay out of my way.
            - Aldric: Aye.

### Reconsidered

- **You**: I have thought again, soldier. Come with me.
    - Aldric: Aye. Thank you. I'll go first.

### Aggressor

- _(Aldric says nothing; the engine runs a script)_

### Threatened

- _(Aldric says nothing; the engine runs a script)_

### Wary

- Aldric: Easy. Easy. I don't want this.

_(on approach: `StartDialogue(Greeting);`)_

### Following you (main role)

### Talk

- **You**: Tell me of the missing.
    - Aldric: Twelve. There was a girl, Elara. A woman called Tessa wrote to her cousin about her and the letter got to Ardent in the end. A serving woman from the Fallen Oak. A farm lad of Lord Ermus'. The letters said bandits. Bandits don't take folk that have nothing.
        - **You**: Then why take them?
            - Aldric: That's what the proctor came to find out.
        - **You**: You know their names.
            - Aldric: I carried the list. I read it enough times.
- **You**: What is this place, soldier?
    - Aldric: I don't know. It's old. Somebody built it to be held. Gates, barracks. Then they were gone and the dead were here.
        - **You**: Gone where?
            - Aldric: Down. Everything here goes down.
        - **You**: Held against what?
            - Aldric: I've thought about that. The doors get heavier the lower we go. I don't think it was built to keep anything out.
- **You**: How do you fare?
    - Aldric: Well enough. I've been eating what was left in the jars. I don't know how long it's been since I saw daylight.
        - **You**: Good.
        - **You**: Tell me if you cannot go on.
            - Aldric: I'll go on. I'll go in front.
- **You**: You put yourself in front of everything. Why?
    - Aldric: That's what a soldier's for.
        - **You**: That is not an answer.
            - Aldric: It's the one I've got.

### Secret

- **You**: The proctor. You said he went down first and you came after. Tell me the rest.
    - Aldric: We stood at the hole. He went down the rope. I was to go after him. I had my hands on the rope and I couldn't. I couldn't make my legs do it. He called up for me and I didn't answer. Two days I sat by that hole. Then I went down, because I couldn't go back to Ardent and say what I'd done.
        - **You**: You left him alone down here.
            - Aldric: I left him alone down here. And now you've seen what that came to.
        - **You**: You came down in the end.
            - Aldric: Two days late. He was dead by then, I expect. I'll be in front of you from here. That's all I can do about it.

### Secret 2

- **You**: Aldric. If you could go back to that rope.
    - Aldric: I'd like to say I'd go down after him. I don't know that I would. I know what's down here now. I think I'd have run from you too, that first day, if you'd given me room.
        - **You**: You did not run.
            - Aldric: No. Not that time.
        - **You**: That is honest, at least.
            - Aldric: It's late to start. I'll be in front.

### Hold all

- **You**: All of you. Wait here.
- Aldric: Aye. I'll hold here.

### Follow all

- **You**: All of you. With me.
- Aldric: Aye. I'll go first.

### Boss Door

- Aldric: Locked. There's something in there. I can hear it moving. When it opens, let me go in first.

### Key

- Aldric: That's a key. Take it.

### Vault

- Aldric: Another lock. There'll be another key somewhere.

### Closet

- Aldric: There's a plate in the floor there. Don't step on it. There's something behind that gate.

### Gate

- Aldric: The gate's up. Go. I'll come behind.

### Stairs

- Aldric: Stairs. I'll go first.

### Arrive

- Aldric: Another one. Same as the last. Find the key.

### Boss

- Aldric: There it is. Get to its side. I'll take the front.

### Fight 1

- Aldric: Fall back. Fall back, I have it.

### Fight 2

- Aldric: You're bleeding. Get behind me.

### Fight 3

- Aldric: Behind me. Now. Let it come to me.

### Depth

- Aldric: Lower. Same stone. Same dead, I expect.
- Aldric: Colder here. Bigger halls.
- Aldric: Wet. It smells like a drain. Mind your feet.
- Aldric: Brick. Older than the rest.
- Aldric: Rough stone. Mines, by the look of it.
- Aldric: Different stone. Old. Watch the floor.
- Aldric: I'm getting old for this. I'll go first anyway.

### Idle 1

- Aldric: The lamps are still lit. Nobody's filled them. I don't like it.

### Idle 2

- Aldric: It's quiet. I'd rather hear them coming.

### Idle 3

- Aldric: I keep thinking I'll see the sky round the next corner. I know I won't.

### Marlia

- Aldric: That's him. That's the proctor. That's his coat.
    - **You**: You said he went ahead of you.
        - Aldric: I did say that. I'll tell you. Not here. Put him down first.
    - **You**: Then he is found.
        - Aldric: Aye. He's found. I'll tell you how it was. Not here.

### Hurt

- Aldric: I'm hit. Keep going. I'm still in front.

### You hurt

- Aldric: You're bleeding. Sit down. Bind it. I'll watch.
    - **You**: Later.
        - Aldric: Sit down.
    - **You**: A moment, then.
        - Aldric: I'll watch the door.

### Part ways

- **You**: Hold here, soldier. I will return.
    - Aldric: Aye. I'll hold it. Don't be long.

### Come along

- **You**: We go.
    - Aldric: Aye. I'll go first.

### Saw you

- Aldric: What was that? What did you just do?
    - **You**: The same thing the dead do. I will not use it on you.
        - Aldric: See that you don't. I'll stay in front. It doesn't change that.
    - **You**: Keep walking, soldier.
        - Aldric: Aye. I'll keep walking.

### Saw Mira

- Aldric: The girl. The Order sent us a shaper and told us nothing. I should have known. Good. Point it at them, girl, and not at us.

### Dead Tobin

- Aldric: The thief's down. I said I'd not leave anyone again. I didn't leave him. It wasn't enough.
    - **You**: It was not your doing.
    - **You**: We go on, soldier.

### Dead Mira

- Aldric: The girl. Gods below. She was behind me. She was meant to be behind me.
    - **You**: She was. It was not your doing.
    - **You**: We go on, soldier.

### Mourn Tobin 1

- Aldric: I keep looking for the thief at my back. Habit.

### Mourn Tobin 2

- Aldric: He'd have found that key quicker than we did.

### Mourn Tobin 3

- Aldric: Twelve names on the list. I never put his on it. I should have.

### Mourn Mira 1

- Aldric: The girl counted the stairs. I've started counting them. I don't know why.

### Mourn Mira 2

- Aldric: She'd have felt that one coming.

### Mourn Mira 3

- Aldric: I had her behind me the whole way down. One door. One.

### About Mira

- **You**: The apprentice. Does she hold up?
- Aldric: She holds up. She doesn't eat and she doesn't sleep, and she still keeps pace with me. I'll have a word with her.

### About Tobin

- **You**: The thief. Can he be trusted?
- Aldric: At your back, yes. With your purse, no. He'll not run from a fight. I've watched him. I'll tell him you asked.

### Mira asked

- Aldric: The girl says you set her to asking me who I look for. If you want to know a thing about me, ask me yourself.
    - **You**: Then I ask. Who is it?
    - **You**: Fair enough.

### Tobin asked

- Aldric: The thief says you asked him about me. He's right to keep clear. I said I'd hang him and I meant it. I said not down here, and I meant that too.
    - **You**: Keep to the second.
    - **You**: Good.

### Banter with Tobin (opens on its own when both follow you, once an hour each)

### The rope

- Aldric: You held the rope. There were twelve people taken from those villages. I want to know how many of them you put down that hole.
- Tobin: I don't know. Nobody told us their names and we never asked.
- Aldric: One was a girl called Elara. Nineteen years old. She had never been out of her village.
- Tobin: There was a girl that kept asking after her cousin. Aye. I held the rope for her.
- Aldric: If we were up top I would hang you for that. Down here I need every hand I can get. Don't forget which of those is true today.

### Standing

- Aldric: When the dead come at us, get behind me. Don't run past me.
- Tobin: I don't run. I'll go round them.
- Aldric: Then go round them behind me. I have the shield.
- Tobin: Aye. All right.

### The shrine

- Aldric: This shrine Bram prayed at. What was on it?
- Tobin: A man with a crown. Folk kneeling to him. Bram said it was the Guardian.
- Aldric: And he fed it people.
- Tobin: He fed it people. I held the rope. You know that already.

### Boss Door

- Aldric: Thief. You hear that?
- Tobin: I hear it. Summat big, walking about. Key first.

### Arrive

- Aldric: Thief. Where would you put the key, in a place like this?
- Tobin: Far from the door. They always put it far from the door.

### Boss

- Aldric: Thief. Get round behind it. Keep out of my swing.
- Tobin: Behind it. Aye. Don't swing wide.

### Fight 2

- Aldric: Thief! Its side!
- Tobin: I'm on it! I'm on it!

### You hurt

- Aldric: Thief. The door.
- Tobin: Watching it.

### Saw Mira

- Aldric: Did you see that? The girl.
- Tobin: I felt it. I told you I felt summat off her.

### Dead Mira

- Aldric: Thief. Stay close. There's two of us now.
- Tobin: Aye. Two.

### Asked Tobin

- Aldric: You were asked about. Whether you can be trusted.
- Tobin: What did you say?
- Aldric: That you'll not run. It's the one good thing I know of you.
- Tobin: It's enough.

### Banter with Mira (opens on its own when both follow you, once an hour each)

### No way up

- Aldric: You count the stairs as we go. Have any of them gone up?
- Mira: None. I've counted every one and none of them go up.
- Aldric: Then there is no way out of here.
- Mira: There is still down.

### The proctor

- Aldric: You asked where my proctor is. I don't know.
- Mira: You said he was ahead of you.
- Aldric: I said that.
- Mira: I won't ask again.

### Her

- Aldric: Your master. The one who died. Did she send you down here?
- Mira: No. She wanted to know. I came because she couldn't.
- Aldric: That's a poor reason.
- Mira: I know.

### Gate

- Aldric: The gate's up. Are you hurt?
- Mira: No. Go through. I'm behind you.

### Fight 1

- Aldric: Back. Get back behind me.
- Mira: I'm back. Hit it when it stops.

### Fight 3

- Aldric: Mira. Behind me. Now.
- Mira: I'm here. Hold it still.

### Key

- Aldric: The key. Mark where it was, girl, in case there's another.
- Mira: I will.

### Big Demon

- Aldric: Girl. Stay back from that one.
- Mira: I'm staying back.

### Saw you

- Aldric: You saw that.
- Mira: I saw it.

### Dead Tobin

- Aldric: The thief's gone.
- Mira: I know. I counted him.

### Asked Mira

- Aldric: You were asked after.
- Mira: Asked what?
- Aldric: Whether you hold up. I said you do.
- Mira: I do.

### If you attack them first (assail role)

### Negotiate

- **You**: Wait. I mean you no harm.
    - Aldric: You've a strange way of showing it.
    - Aldric: Put it down first.
    - Aldric: You came at me. Up top that's a hanging.
        - **You**: I took you for one of the dead.
            - Aldric: The dead don't wear a sash. Look before you swing.
                - **You**: I will.
                    - Aldric: Who are you, then?
                - **You**: I make no promises.
                    - Aldric: Then stay over there.
        - **You**: You were in my way.
            - Aldric: Then say so.

### Start Over

- Aldric: I don't want to fight you. I've done enough of that down here.
    - **You**: Then let us begin again. Who are you?
        - Aldric: Aldric. A soldier of Ardent. I came down after the proctor and I haven't found him. You?
            - **You**: I do not remember. I woke down here.
                - Aldric: Like the rest. Come with me or don't. Just don't come at me again.
                    - **You**: Come with me.
                        - Aldric: Aye. I'll go first.
                    - **You**: I go alone.
                        - Aldric: Go on, then.
    - **You**: Stay out of my way.
        - Aldric: Gladly.

### Plead

- Aldric: Stop!
- Aldric: Hold!
- Aldric: Enough!

### Aggressor

- _(Aldric says nothing; the engine runs a script)_

### Engage

- _(Aldric says nothing; the engine runs a script)_

## Mira

### First meeting (their own role; the "Join me" yes runs the recruit script)

### Greeting

- Mira: You're alive. Stay there. Stay there a moment, please.

### Who are you?

- **You**: Who are you?
    - Mira: Mira. I'm with the Order. An apprentice. I copy their books.
    - Mira: I wanted to be sure you weren't one of the dead. They don't talk. Who are you?
        - **You**: I do not know. I woke on the ground down here.
            - Mira: Everyone I've met down here says that. I don't know what does it.
            - Mira: I came down on a rope. The rope ended and I fell the rest of the way. I don't know how far. You came another way, I expect. It doesn't put us all in the same place.
                - **You**: Why did the Order send you?
                - **You**: Everyone?
                    - Mira: A soldier. A thief. Some of the villagers, before they died. None of them remembered.
        - **You**: I care nothing for the Order.
            - Mira: Nor do I, lately.

### Why here

- **You**: Why did the Order send you down?
    - Mira: They didn't. I came. Years ago a master of the Order went below to study the dead here, the ones that stand up with no necromancer near them. He never came back. My master wanted to know why. She died last winter and nobody else wanted to know. So I came.
        - **You**: Alone. On a rope.
            - Mira: Alone. On a rope. I didn't think about it very carefully.
        - **You**: What did you mean to do down here?
            - Mira: Find out what holds the dead up. I still mean to.

### Join me

- **You**: Come with me, apprentice. You know what the Order knows. I will do the fighting.
    - Mira: Yes. All right. I'll keep out of your way when they come.
        - **You**: Agreed. Stay close.
            - Mira: I will.
        - **You**: You will do as I say.
            - Mira: Yes. Within reason.
                - Mira: Down, then.

### Not now

- **You**: I have no need of a copyist.
    - Mira: No. I'll be here. There's nowhere else for me to be.

### Reconsidered

- **You**: I have thought again. Come with me.
    - Mira: Yes. Thank you.

### Aggressor

- _(Mira says nothing; the engine runs a script)_

### Threatened

- _(Mira says nothing; the engine runs a script)_

### Wary

- Mira: Don't. Please don't.

_(on approach: `StartDialogue(Greeting);`)_

### Following you (main role)

### Talk

- **You**: Tell me of the Order.
    - Mira: They live in towers, away from people. A master takes an apprentice so that what they know goes on after them. I was taken on to copy. That's what they said it was for.
        - **You**: And what was it for?
            - Mira: I don't know yet.
        - **You**: Your master.
            - Mira: She died last winter. I'd rather not talk about her.
- **You**: What is this place?
    - Mira: A city, once. The Order's books say the ancients dug below the earth and found something, and lost their gods over it. Then they were gone. The dead stayed.
        - **You**: What gods?
            - Mira: The Guardian. The Keeper of the Dead. The stories say he raises the dead as an army when he needs one.
        - **You**: Gone where?
            - Mira: The books don't say. Down, I expect. There's nowhere else.
- **You**: How do you fare, apprentice?
    - Mira: Tired. I don't sleep. I'm all right.
        - **You**: Good.
    - Mira: Tired. The dead press on my mind, all of them at once. I don't sleep. I'm all right.
        - **You**: Tell me if it worsens.
            - Mira: You'd notice. I'd start answering them.
        - **You**: Good.
- **You**: What holds the dead up? Your master wanted to know.
    - Mira: A binding, the Order would say. When a shaper lets go of a binding it breaks. These have held for I don't know how long. So either someone is still holding them, or they hold themselves.
        - **You**: Hold themselves.
            - Mira: Yes. And a thing that holds itself has to be fed. I don't want to know with what.

### Dire

- Mira: No. Not like this. Get behind me. I'll explain after.

### Engage

- _(Mira says nothing; the engine runs a script)_

### Secret

- **You**: You are no copyist. Tell me what you are.
    - Mira: No. I'm not. I have the talent. I can feel them. I've been able to feel them since I landed. I didn't tell you because people don't like it, and I didn't know you.
        - **You**: You know me now.
            - Mira: I know you haven't left me behind. That's enough to be going on with. When I say stop, stop. I'll know before you can see them.
        - **You**: What else have you hidden?
            - Mira: Nothing that would hurt you. Ask me again lower down.

### Secret 2

- **You**: The locks open more easily the deeper I go. Why?
    - Mira: Because it knows you. The thing that holds the dead. I feel it turn toward you at every door. Your mind isn't shut from your side. Something below has the key to it, and it's opening you a little at a time. The same as the doors.
        - **You**: It wants me at the bottom.
            - Mira: There's a story the Order keeps, the Guardian's Wrath. Our ancestors dug for the earth's lifeblood and found the Guardian, and sealed the entrances after. I expect the hole you fell through was one of the seals. I expect the master who came down before me felt it turn to him too.
        - **You**: Can you cut it?
            - Mira: I could try. He probably tried. Ask me when you're certain.

### Hold all

- **You**: All of you. Wait here.
- Mira: Yes.

### Follow all

- **You**: All of you. With me.
- Mira: Yes.

### Boss Door

- Mira: Locked. There's something behind it. I can hear it.
- Mira: Locked. There's something behind it. It has a mind, of a kind. It's waiting.

### Key

- Mira: There. That's the key.

### Vault

- Mira: Another lock. Its key will be somewhere else. Someone built this to be slow.

### Closet

- Mira: Don't step on the plate. There's a gate beside it, and I don't like the gate.
- Mira: Don't step on the plate. There are some behind that gate. I can feel them.

### Gate

- Mira: It's up. Go through.

### Stairs

- Mira: Stairs. Down again. That's another one I've counted.

### Arrive

- Mira: Another one. The same shape. It's always the same shape.

### Boss

- Mira: There it is. Go when it turns.
- Mira: I can feel it. It knows we're here. Go when it turns.

### Fight 1

- Mira: I'll hold it. A moment. Hit it when it stops.

### Fight 2

- Mira: Back. Get back. Let me put something between you.

### Fight 3

- Mira: You're bleeding. Stand behind me. Please.

### Depth

- Mira: Lower. The same stone. I've counted this flight.
- Mira: Bigger halls. There'll be more of them here.
- Mira: Wet. The air is bad. Don't drink anything.
- Mira: Old brick. Be careful here.
- Mira: They dug here. It's quieter than it should be.
- Mira: Older brick. Something walks here that I can't feel at all.
- Mira: I've stopped counting. It's the same, lower down. It's always the same.

### Idle 1

- Mira: The lamps burn without oil. I try not to think about what they burn.

### Idle 2

- Mira: I keep listening for something that isn't footsteps.

### Idle 3

- Mira: My master would have called this a great opportunity. She said things like that.

### Marlia

- Mira: Wait. The robe. That's one of ours. That's a master's robe.
    - **You**: The one who came before you.
        - Mira: I expect so. He found what he came for. Come on.
    - **You**: Then he never turned back.
        - Mira: No. Come on.

### Hurt

- Mira: I'm hurt. I don't think it's bad. I don't know what bad looks like.

### You hurt

- Mira: You're bleeding badly. Sit. Let me look at it.
    - **You**: Later.
        - Mira: Now. Please. Sit.
    - **You**: A moment, then.
        - Mira: Look at me. Don't look at it.

### Part ways

- **You**: Wait here, apprentice. I will return.
    - Mira: All right. Don't be long.

### Come along

- **You**: We go.
    - Mira: Thank you.

### Saw you

- Mira: You have the talent. I didn't know. You should have said.
    - **You**: So should you, apprentice.
        - Mira: Yes. I know.
    - **You**: Now you know.
- Mira: So that's two of us. Good. Don't push it. It pushes back.
    - **You**: I know.
    - **You**: What do you mean, it pushes back?
        - Mira: The more you use it, the more you feel them. The dead. All of them at once. Rest between.

### Dead Aldric

- Mira: Aldric. He went in front. He always went in front. I'll count him with the others.
    - **You**: Count him.
    - **You**: We go on, apprentice.

### Dead Tobin

- Mira: Tobin. I told him nobody here would hurt him. I meant it. It wasn't enough.
    - **You**: It was not your doing.
    - **You**: We go on, apprentice.

### Mourn Aldric 1

- Mira: Aldric would have gone through that door first.

### Mourn Aldric 2

- Mira: I count the stairs for him now. He asked me once how many.

### Mourn Aldric 3

- Mira: He looked for his proctor in every face. I look for his now. I don't mean to.

### Mourn Tobin 1

- Mira: Tobin would have gone quiet before that one. I miss the quiet.

### Mourn Tobin 2

- Mira: I told him to find the stone in his gut. I hope he found it, at the end.

### Mourn Tobin 3

- Mira: He never did eat. I should have made him.

### Aldric asked

- Mira: Aldric says you asked after me. I'm all right. If I'm not, I'll say so.
    - **You**: See that you do.
    - **You**: Good.

### About Aldric

- **You**: The soldier. What do you make of him?
- Mira: He goes in front of everything. He looks every one of the dead in the face before he puts it down. I think he's looking for someone. I'll ask him.

### About Tobin

- **You**: The thief. He watches you.
- Mira: He watches everyone. His own people put him down the hole. He thinks we'll do the same. I'll talk to him.

### Tobin asked

- Mira: Tobin says you asked about me. He says I make him uneasy. I don't mean to.
    - **You**: He means no harm by it.
    - **You**: Noted.
- Mira: Tobin says you asked about me. He says I make him uneasy. He's not wrong. He feels it. He doesn't know what it is.
    - **You**: Keep it so.
    - **You**: He means no harm by it.

### Banter with Aldric (opens on its own when both follow you, once an hour each)

### Looking

- Mira: You look at every one of the dead before you put it down. In the face.
- Aldric: Aye.
- Mira: Who are you looking for?
- Aldric: Somebody I owe.

### Counting

- Mira: You count the ones you knew. Four, you said.
- Aldric: Four from the list. Aye.
- Mira: Why count them?
- Aldric: Somebody should. Nobody else is going to.

### The rope

- Mira: I came down on a rope. Did you?
- Aldric: Aye. A rope.
- Mira: Was it hard? Letting go of the top?
- Aldric: Don't ask me that.

### Stairs

- Mira: Aldric.
- Aldric: I'll go first.
- Mira: Go, then.

### Closet

- Mira: There's a plate there. Don't step on it.
- Aldric: I see it. Nobody steps on it.

### Spark

- Mira: Aldric. Did you see what Tobin did?
- Aldric: I saw it. Gods below. The thief.

### Asked Aldric

- Mira: Who are you looking for? Among the dead.
- Aldric: You've asked me that before.
- Mira: You didn't answer.
- Aldric: The man I was sworn to. If I see him, I'll know him.

### Banter with Tobin (opens on its own when both follow you, once an hour each)

### Trust

- Mira: You watch me when you think I'm not looking.
- Tobin: I watch everybody.
- Mira: I'm not going to hurt you, Tobin.
- Tobin: Everybody says that. Then they do.

### The shrine

- Mira: The hole was by a shrine. Was anything carved on it?
- Tobin: A man with a crown. Folk kneeling to him.
- Mira: The Guardian.
- Tobin: Bram said that. You know it too?
- Mira: I've read it. It isn't a good thing to know.

### Quiet

- Mira: You go quiet before something comes. I've noticed.
- Tobin: I get a feeling. In my gut.
- Mira: Say it out loud, when you get it.
- Tobin: I will. You listen.

### Lesson 1

- Mira: That feeling of yours. When it comes, don't push it away. Look at it.
- Tobin: Look at it how? It's in my gut.
- Mira: Then look at your gut. Where does it sit? Is it cold or warm?
- Tobin: Cold. Like a stone.
- Mira: Good. Next time, find the stone before anything comes.

### Lesson 2

- Mira: Did you find the stone?
- Tobin: Once. In the last room. Before the door opened.
- Mira: Before the door opened. That's it. Keep finding it.
- Tobin: Why do you care?
- Mira: Because it's the only thing down here that warns us.

### Lesson 3

- Mira: When you find the stone, don't hold it. Let it go through your hands.
- Tobin: That makes no sense.
- Mira: It will. Do it anyway.
- Tobin: Aye. All right. Let it go through my hands.

### Depth

- Mira: You've gone quiet.
- Tobin: I've got the feeling. Summat's down here.
- Mira: I know.

### Vault

- Mira: Its key will be somewhere else.
- Tobin: Two keys. Somebody's having a laugh at us.
- Mira: Somebody built this to be slow.

### Gate

- Mira: It's up. Go through.
- Tobin: Going. Don't shut it on me.

### Fight 1

- Mira: Tobin. Get back.
- Tobin: I'm back. I'm back.

### Fight 3

- Mira: Tobin. Behind me.
- Tobin: Behind you. Aye.

### Saw you

- Mira: Tobin. Did you see?
- Tobin: I saw. I don't want to talk about it.

### Dead Aldric

- Mira: He's gone, Tobin.
- Tobin: I know. I saw. Don't talk to me for a bit.

### Asked Tobin

- Mira: Nobody here is going to put you down a hole, Tobin.
- Tobin: You don't know that.
- Mira: I know I won't.
- Tobin: Aye. Well. You're the only one that's said it.

### If you attack them first (assail role)

### Negotiate

- **You**: Wait. I mean you no harm.
    - Mira: You tried to kill me.
    - Mira: Stay back. Stay back from me.
    - Mira: You struck first. What did you take me for?
        - **You**: One of the dead.
            - Mira: The dead don't flinch. Look, next time. Please.
                - **You**: I will.
                    - Mira: Then who are you?
                - **You**: I make no promises.
                    - Mira: Then keep away from me.
        - **You**: You startled me.
            - Mira: I was standing still.

### Start Over

- Mira: I don't want to fight. I'd lose.
    - **You**: Then let us begin again. Who are you?
        - Mira: Mira. I'm an apprentice of the Order. I came down to find out why the dead here stand up. You?
            - **You**: I do not remember. I woke down here.
                - Mira: Like the others. Come with me, if you want. I know what the Order knows. You can fight.
                    - **You**: Come with me.
                        - Mira: All right. Don't do that again.
                    - **You**: I go alone.
                        - Mira: As you like.
    - **You**: Stay out of my way.
        - Mira: I wasn't in it.

### Plead

- Mira: Stop!
- Mira: Don't!
- Mira: Please!

### Aggressor

- _(Mira says nothing; the engine runs a script)_

### Engage

- _(Mira says nothing; the engine runs a script)_
