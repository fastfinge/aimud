"""
AI generation and reaction for NPCs.

generate_npc()          — create an NPC appropriate to a room (async)
generate_npc_reaction() — send tool-call request to dialogue model (async)
notify_npcs()           — notify all NPCs in a room of an event (sync helper)
"""

import re

from evennia.utils import logger

from world import llm, tokens


#: Words that are a station rather than a name. Two sergeants are not two
#: people with the same name, and rejecting the second one would be wrong.
TITLES = frozenset("""
    mr mrs ms miss mx dr doctor prof professor sir dame lady lord madam
    master mistress captain sergeant corporal officer constable brother
    sister father mother elder young old the of van von der den de la
""".split())

# ---------------------------------------------------------------------------
# Tool definitions sent to the dialogue model
# ---------------------------------------------------------------------------

NPC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Leave by one of the ways out of this room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "Which way out, by its name",
                    }
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "say",
            "description": "Say something aloud in the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The words, as you would say them",
                    },
                    "to": {
                        "type": "string",
                        "description": (
                            "Optional. Who you are speaking to, when it is "
                            "somebody in particular"
                        ),
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get",
            "description": (
                "Pick up something within reach: lying here, or in or on "
                "something that is open."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "What to pick up",
                    }
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "give",
            "description": "Give an object from your inventory to someone in the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "What to hand over, from what you are carrying",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Name of the player or NPC to give to",
                    },
                },
                "required": ["object_name", "recipient"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emote",
            "description": "Perform an action or gesture (third-person description).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "A short third-person phrase, e.g. 'nods solemnly' "
                            "or 'adjusts her hood'"
                        ),
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attempt",
            "description": (
                "Attempt an action on something, the way a player would type it: "
                "'light the candle', 'read the notice', 'open the drawer'. The "
                "world decides whether it works and what changes. Use this for "
                "anything physical rather than describing it in an emote. "
                "Clothes work this way too: 'wear the grey coat', 'remove my "
                "apron'. Anyone looking at you sees what you have on, so what "
                "you put on or take off really does change how you appear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The action as a short command, e.g. 'light candle'",
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_traits",
            "description": (
                "Take stock of somebody -- how strong, how skilled, how well, "
                "how well thought of. Your own figures you already know and "
                "they are given to you above; use this for other people in the "
                "room. What you find comes straight back to you, so you can "
                "act on it in the same turn. Sizing "
                "somebody up is a thing anyone can do by looking at them, so "
                "use it when it would matter -- before picking a fight, "
                "before trusting a stranger with an errand, when someone "
                "looks unwell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "person": {
                        "type": "string",
                        "description": (
                            "Which of the people here to size up, or "
                            "'myself'"
                        ),
                    },
                },
                "required": ["person"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer_quest",
            "description": (
                "Answer a request somebody has made of you. Refusing is a "
                "perfectly good answer, and the right one when it does not "
                "suit who you are or what you are already doing. Agreeing "
                "means you will work at it until it is done, fails, or you "
                "give it up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "accept": {
                        "type": "boolean",
                        "description": "true to agree to it, false to refuse",
                    },
                },
                "required": ["accept"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "offer_quest",
            "description": (
                "Ask someone present -- player or character -- to do something "
                "for you, in your own words. Say what you want, what you will "
                "give them for it, and any consequence of failing. The game "
                "works out how to check it, so describe the errand plainly "
                "rather than in any particular format, and ask only for "
                "something that could actually be done with what is around "
                "you. Use this sparingly: ask when you genuinely need a hand "
                "with what you are trying to do, not as a way of making "
                "conversation. Anyone already running an errand cannot take "
                "another."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "person": {
                        "type": "string",
                        "description": "Name of the person you are asking",
                    },
                    "request": {
                        "type": "string",
                        "description": (
                            "What you want done, said the way you would say it: "
                            "'bring me the chalk from the storeroom'"
                        ),
                    },
                    "offer": {
                        "type": "string",
                        "description": "What they get for doing it, e.g. 'my old brass compass'",
                    },
                    "consequence": {
                        "type": "string",
                        "description": "Optional. What happens if they fail or run out of time.",
                    },
                    "time_limit_seconds": {
                        "type": "integer",
                        "description": (
                            "Optional deadline in seconds. Leave it out if "
                            "there is no hurry."
                        ),
                    },
                },
                "required": ["person", "request", "offer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": (
                "Decide what you are going to work towards next, in your own "
                "words: 'get the storeroom key', 'see the lamp in the chapel "
                "lit', 'find out where the cook went'. You will then pursue it "
                "on your own between conversations, so choose something you "
                "could actually get done with what is around you. Use this "
                "when you have nothing in particular you are working towards."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "want": {
                        "type": "string",
                        "description": "What you want to bring about, in a sentence",
                    }
                },
                "required": ["want"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create",
            "description": (
                "Make real something this room already implies but that "
                "nothing in the game has yet -- the notice board the "
                "description mentions, the row of hooks by the door, the "
                "bottle behind the bar. Name it; the world decides whether "
                "it belongs here and works out what it is, so it comes back "
                "as a thing that can actually be handled rather than a name "
                "on nothing. This is not for furnishing: something nobody "
                "has any reason to reach for is better left unmade."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "What it is called, as you would name it: "
                            "'notice board', 'brass hooks'"
                        ),
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "destroy",
            "description": (
                "Destroy something lying here or that you carry. Ways out "
                "and people cannot be destroyed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "What to destroy",
                    }
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify",
            "description": (
                "Change what something within reach is called, or how it "
                "looks. A name says what a thing IS -- what it is made of, "
                "what it is for, whose it is -- and never its condition: "
                "'glass bottle', not 'broken glass bottle'. Everyone here sees "
                "you do it, and a change the world's rules refuse is not made."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "What to change, as it is called now",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "What it is called from now on, if that changes",
                    },
                    "new_description": {
                        "type": "string",
                        "description": (
                            "What it looks like from now on, if that changes: "
                            "what it is made of and what it is for, not how "
                            "full, lit or damaged it is"
                        ),
                    },
                },
                "required": ["object_name"],
            },
        },
    },
]

#: Every tool a character may be offered, by name. `NPC._execute_one` refuses
#: anything else, which is how a model inventing a tool gets noticed rather
#: than quietly ignored. Read off the list above, so the two cannot disagree.
TOOL_NAMES = frozenset(tool["function"]["name"] for tool in NPC_TOOLS)

#: How many things a character may DO in one turn. The prompt always said so,
#: and nothing held a model to it: a reply with eight tool calls was eight
#: actions.
MOST_ACTS = 3

#: Tools that only look, and so do not count against `MOST_ACTS`. Sizing
#: somebody up before deciding what to do about them is not a second action.
LOOKING = frozenset(["check_traits"])

#: How many of this world's known verbs `attempt`'s description names, and how
#: many things `get`'s description says where they are and whose they are.
MOST_VERBS_NAMED = 30
MOST_THINGS_SAID = 20

#: How many rounds one character's turn may take. See docs §10.3; the soak
#: sets it from what `rounds dialogue` says turns actually use.
TURN_ROUNDS = 8

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_NPC_GEN_SYSTEM = """You generate NPC characters for a text-based MUD.
Answer by calling make_character. The name is 1-3 words, the description 2-4
sentences, and the manner 2-3 sentences.

"name" is how the player will address this character, so it has to belong to
one person. Any names already used in this world are listed for you; do not
reuse one and do not vary on one, because a second character with the same
first name is one the player cannot speak to. Reach past the first name that
comes to mind: real places are full of ordinary names that are not the most
typical one for the setting, and a hostel with four women called Yuna in it
is not a place. A shared family name is fine — families exist.

"description" is the character's BODY, and nothing else. It is shown again
every single time anyone looks at them, for the rest of the character's life,
so every word of it must still be true years later in another room wearing
different clothes. Write only what they cannot take off or put down.

Write about: species, apparent age, height and build, skin, hair colour,
length and texture, eye colour, the shape of the face, hands, voice, and
permanent marks -- scars, tattoos, a missing finger, a birthmark. Two to four
sentences of that, in the present tense.

It must NOT contain:
- clothing, armour, jewellery, footwear, spectacles, or anything else worn.
  The game dresses characters separately and lists what they have on beneath
  this text; naming a coat here would go on describing a coat they took off an
  hour ago, and describe it twice while they still wear it.
- anything they are carrying, holding, or have slung over a shoulder. They put
  things down.
- anything they are doing. No sitting, standing, watching, straightening,
  fidgeting, smiling, or greeting anyone. They will not be doing it later.
- where they are, or any furniture, room or fixture. They walk from room to
  room, and a character described behind a desk is wrong the moment they
  leave it.
- personality, mood, motive or history -- what they think, feel, want, or
  have stopped caring about. None of that is visible.
- the player: no "you", no "your", no reacting to being looked at.

If you find yourself writing "wearing", "dressed", "clad", "in a", "carries"
or "holds", stop: that belongs to the clothing, not to the person.

"pronouns" is what other people say about this character: one of the sets
this world already keeps, by name. The pronouns field names them. Pick whichever
suits the person you have written, and vary it across a world the way a real
place varies.

"new_pronoun_set" is for a character none of those sets suits -- a hive mind,
a ship's computer, somebody who goes by a word this world has not met. Leave
it out almost always. When you do give one, give it whole:
{"subject": "ze", "object": "zir", "adjective": "zir", "possessive": "zirs",
 "reflexive": "zirself", "plural": false,
 "means": "one sentence on who this set is for"}
and put its subject form in "pronouns" as well. A set missing any of those is
discarded entire, because the missing form is a sentence written wrong every
time it comes up afterwards. "plural" is whether the verb after it is plural:
"they pick up the sword" is true, "she picks up the sword" is false.

"manner" is the opposite and is never shown to players: temperament, habits,
what they want, how they speak and treat people. Put the character there.

"goal" is the one thing this character is trying to bring about, written as
conditions the game can check. Keep it small and near at hand -- something
they could plausibly work at with what is around them, not a life ambition.
Each entry is one of:
{"type": "holds",     "object": "brass key"}          they want to be carrying it
{"type": "worn",      "object": "grey habit"}         they want to have it on
{"type": "state",     "object": "lamp", "is": ["lit"]} they want it to be so
{"type": "in_room",   "room": "Kitchen"}               they want to get there
{"type": "delivered", "object": "letter", "to": "Clerk"}
{"type": "gone",      "object": "rats"}
Any condition that names an "object" may instead name a "kind" -- the sort of
thing rather than one particular thing. {"type": "holds", "kind": "cake"} is
satisfied by any cake; {"type": "holds", "object": "chocolate cake"} only by
that one. Prefer "kind" whenever any of them would genuinely do, because a
want pinned to one object fails for good the moment somebody else takes it.
Use "object" when it really must be that one -- a letter addressed to them,
the key to this door.

Name only things that plausibly exist in this world. Give an empty list for a
character with nothing in particular to pursue.

"traits" is what is measurably true of this character, as figures. Give 0 to 4,
and ONLY ones already in the world's register, which the traits field names.
Do not invent a trait here: a register is only worth having if everyone in the
world is measured by the same yardstick, and new traits are added when the
world's rules need them, not when a character is born. Give an empty list if
none of the registered traits say anything about this person. "value" is where
they stand — an ordinary person is middling, not exceptional.

The character must fit naturally in the world and room described."""

_NPC_REACT_SYSTEM = (
    "You are {npc_name}, a character in a text-based MUD. Stay in character at all times.\n\n"
    "World: {world_desc}\n"
    "{guidance}"
    "How you look: {npc_desc}\n"
    "{npc_traits}"
    "{npc_manner}"
    "Current room: [{room_title}]\n"
    "{room_desc}\n"
    "{room_contents}\n\n"
    "{want}"
    "Use the available tools to react naturally to recent events. "
    "You may do up to three things per response; sizing somebody up with "
    "check_traits does not count as one. "
    "If nothing warrants a response, call no tools. Keep reactions brief and in-character.\n\n"
    "To do something physical, use the `attempt` tool with the action written "
    "as a short command — 'light candle', 'open drawer', 'read notice'. That "
    "actually changes the world: the object really is lit, opened or taken, and "
    "everyone present sees it. Do not use `emote` to pretend an action happened; "
    "emote is for gestures and expression only. You are free to attempt actions "
    "nobody has tried before."
)

_NPC_OUTFIT_SYSTEM = """You dress a character in a text-based MUD and give them what they carry.
Answer by calling dress_character. Each item's description is 1-2 sentences.

You are given the character's body — their build, colouring and permanent
marks. That is fixed and already written. Your job is everything they can take
off or put down.

worn is what they have on, from the skin outwards. Give 2 to 6 garments: real
people are not wearing one thing. Dress them for who they are, what they do
and where they are, and let the clothes say something the body cannot — rank,
trade, poverty, vanity, mourning, how long since they last changed.

clothing_type must be one of: {garment_types}. Use "fullbody" for a robe,
dress or overall; "accessory" for a belt, bag or scarf; "jewelry" for rings and
chains. Only one hat, one pair of gloves, one pair of socks and one pair of
shoes each.

wearstyle is optional, and is shown after the garment's name: "slung over one
shoulder", "buttoned to the throat". Leave it "" unless it says something.

carried is what is in their hands or pockets — 0 to 3 things, and 0 is a fine
answer. Tools of their trade, something they are taking somewhere, something
they should not have.

name every item as a bare noun phrase with no article and no capital letters
unless it is a proper name: "scuffed leather apron", not "A Scuffed Leather
Apron". The game adds the article when it shows the item.

Anything that comes as a pair is named "pair of ...": "pair of hobnailed
boots", "pair of wool gloves". Never a bare plural on its own.

descriptions are what a player sees on looking at that item alone, so they
must not mention the character, the room, or anything else.

{affordance_rule}
Every garment must afford "wear".

kind is the one common noun the thing IS, singular and lowercase, with the
describing words stripped off: a "Patched Wool Coat" is a coat. holds says
where things go: ["in"] for a pouch, [] for anything solid.

{anchor_rule}

states are conditions currently true of it (patched, bloodstained, damp), usually empty.

{naming_rule}"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _affordance_rule():
    """How to declare what can be done to a thing, shared by every generator."""
    from world import affordances

    return affordances.PROMPT


# ---------------------------------------------------------------------------
# Telling one person from another
#
# Rooms already refuse to be named a variation on their neighbours. People
# need the same guard and a stricter one, because the model is never shown
# who else it has invented: asked four times over for somebody who belongs in
# a Korean hostel, it answers "Yuna Choi" four times, each with a different
# face and the same name. Nothing downstream can tell them apart, and neither
# can the player.
# ---------------------------------------------------------------------------

def _name_words(name):
    """
    A person's name as comparable words, stations and particles dropped.

    Hyphens are kept inside a word rather than split on. "Min-ji" and
    "Min-seo" are two different given names that happen to share a syllable,
    and a world drawing on Korean names would be almost unusable if that
    counted as a collision.
    """
    cleaned = re.sub(r"[^a-z0-9'-]+", " ", (name or "").lower())
    words = [w.strip("'-") for w in cleaned.split()]
    return [w for w in words if len(w) > 1 and w not in TITLES]


def _too_similar(name, existing):
    """
    True when `name` is close enough to somebody here to be confusing.

    Stricter than the test a room gets, and deliberately. A room name is
    scenery; a person's name is what the player types to speak to them, so
    two women answering to "Yuna" are not a blemish on the map, they are two
    characters neither of whom can be addressed.

    A shared FAMILY name is allowed through. Worlds have families in them,
    real naming pools are small -- a Korean one is four surnames wide in
    practice -- and forbidding those would reject every honest answer until
    the retries ran out. What is refused is a shared first name, or two names
    made of the same words in any order.
    """
    words = _name_words(name)
    if not words:
        return True                 # nothing usable to be called
    mine = set(words)
    for other in existing:
        theirs = _name_words(other)
        if not theirs:
            continue
        if words[0] == theirs[0]:
            return True             # both answer to the same first name
        if mine <= set(theirs) or set(theirs) <= mine:
            return True             # "Yuna Choi" against "Choi Yuna", or "Yuna"
    return False


def _people_in_world(room):
    """
    Every name already spoken for in this world.

    World-wide, which is where this parts company with rooms: two identical
    taverns at opposite ends of a map are a thin patch in the scenery, but
    the player walks the whole world and meets everybody in it. The world's
    coordinate index is the list of its rooms, so this is two queries however
    large the world has grown.
    """
    from evennia.objects.models import ObjectDB

    from world import coords

    world_root = room.db.world_root if room is not None else None
    room_ids = set(coords.get_index(world_root).values())
    if room is not None and room.id:
        room_ids.add(room.id)
    if not room_ids:
        return set()

    from typeclasses.characters import Character
    from typeclasses.npcs import NPC

    names = set()
    for typeclass in (NPC, Character):
        names.update(
            typeclass.objects.filter(db_location__id__in=room_ids)
            .values_list("db_key", flat=True)
        )
    return {name for name in names if name}


def _check_name(data, existing):
    """
    What is wrong with the name this character was given, if anything.

    Phrased as an instruction rather than a verdict, and asking for the same
    character back, because the model has already invented a face and a
    manner worth keeping -- only the name has to change.
    """
    name = str(data.get("name", "")).strip()
    if not name:
        return "You returned no name. Give this character a name of 1-3 words."
    if _too_similar(name, existing):
        return (
            f"'{name}' is the name of somebody already living in this world. "
            f"Return the same character again -- the same description, manner, "
            f"goal and traits -- under a different first name. Not a variation "
            f"on this one: a different name. Already taken: "
            f"{', '.join(sorted(existing))}"
        )
    return None



def _room_context(room, npc):
    """
    Build a short room context string for the reaction prompt.

    Objects are listed with what can be done to them and what is currently
    true of them, because an NPC choosing an action needs to know that the
    candle is flammable and already lit.  People are told apart by typeclass:
    every Evennia object has a `sessions` attribute, so testing for one
    listed keys, exits and NPCs alike as people.
    """
    from evennia.objects.objects import DefaultCharacter

    from world import clothing

    def person(obj, label):
        # What somebody has on is half of what there is to notice about them,
        # and the only half that changes. A character who cannot see the
        # bloodstained apron has nothing to remark on.
        outfit = clothing.inventory_line(obj, npc)
        return f"{label} — {outfit}" if outfit else label

    people, objects, exits, unexplored = [], [], [], []
    for obj in room.contents:
        if obj is npc:
            continue
        if getattr(obj, "destination", None) is not None:
            exits.append(obj.key)
            if obj.db.pending_generation or obj.destination is room:
                unexplored.append(obj.key)
        elif obj.db.is_npc:
            people.append(person(obj, f"{obj.key} (NPC)"))
        elif isinstance(obj, DefaultCharacter):
            people.append(person(obj, obj.get_display_name(npc)))
        else:
            from world import verbs as _verbs

            marks = sorted(_verbs.affordances(obj))
            condition = list(obj.db.states or [])
            detail = ", ".join(marks) or "nothing special"
            if condition:
                detail += "; currently " + ", ".join(condition)
            objects.append(f"{obj.key} ({detail})")

    parts = []
    if people:
        parts.append("People present: " + ", ".join(people))
    if objects:
        parts.append("Objects here: " + "; ".join(objects))
    if exits:
        parts.append("Exits: " + ", ".join(exits))
    if unexplored:
        # Named on their own line rather than folded into the list above, so
        # what comes back to the move tool stays a bare direction. Worth
        # telling: a character with somewhere to be and no known way there
        # should be able to decide to go and look.
        parts.append(
            "Nobody has been through these yet: " + ", ".join(unexplored))
    return "\n".join(parts)


def _trait_line(npc):
    """
    What is measurably true of this character, for its own prompt.

    Free, like the want line: the prompt is being sent anyway. A character
    that does not know it is down to ten stamina cannot decide to sit, and one
    that does not know its own standing cannot trade on it.
    """
    from world import traits

    described = traits.describe(npc)
    return f"What is true of you: {described}\n" if described else ""


def _want_line(npc):
    """
    What this character is trying to bring about, if anything.

    This is the whole of the goal layer as far as an NPC is concerned: a
    tested condition handed over as context. It costs nothing extra -- the
    prompt is being sent anyway -- and it is the difference between a
    character who reacts to the last thing said and one who wants something.

    An errand somebody set is the same thing wearing a different hat, so it
    belongs here too: what was asked, who asked, and whether it is still
    waiting on an answer.
    """
    from world import goals, quests

    room = npc.location
    world_root = room.db.world_root if room else None

    # An unanswered request comes before anything else this character wants.
    # It is the only situation in which answer_quest is offered at all, so
    # leaving it unsaid would be offering a tool with no reason given.
    offer = quests.offered_to(npc)
    if offer is not None:
        # What was asked, what is offered and by when are on answer_quest
        # itself, where the choice is made.
        return (
            f"{offer['giver']} has asked something of you and is waiting for "
            "your answer; answer_quest says what they asked and what they "
            "offer. Answer as this character would. You are free to refuse; "
            "agreeing means you will work at it until it is done or you give "
            "it up.\n\n"
        )

    goal = list(npc.db.goal or [])
    if not goal:
        # A character with nothing to pursue is asked to find something. The
        # planner works at whatever is set here for free, so this is the one
        # moment worth spending a call on: it buys purpose for a long while.
        return (
            "You are working towards nothing in particular. If anything here "
            "suggests a purpose, set one with set_goal and you will pursue it "
            "on your own between conversations.\n\n"
        )

    outstanding = [
        text for met, text in goals.progress(goal, npc, world_root) if not met
    ]
    if not outstanding:
        return "You have what you wanted for now.\n\n"

    quest = quests.current(npc)
    owed = f" You took this on for {quest['giver']}." if quest else ""
    return (
        "What you want: " + ", then ".join(outstanding) + f".{owed}\n"
        "Work towards it when the moment allows, in character.\n\n"
    )


#: Which tool arguments have to name something already here, and where the
#: names come from. Anything not listed stays free text on purpose: `attempt`
#: and `create` are how a thing the room only describes becomes real, and a
#: closed list would be exactly the wrong shape for either.
_TOOL_CHOICES = {
    "move":         {"direction": "exits"},
    "get":          {"object_name": "within_reach"},
    "give":         {"object_name": "carried", "recipient": "people"},
    "check_traits": {"person": "sizable"},
    "destroy":      {"object_name": "reachable"},
    "modify":       {"object_name": "changeable"},
}


def _distinct(names):
    """
    Names in the order first seen, blanks and repeats dropped.

    Three brass tuning forks on one floor are three identical rows in a list
    somebody has to choose from, and every one of them means the same thing.
    """
    seen, kept = set(), []
    for name in names:
        name = str(name or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            kept.append(name)
    return kept


def _nameable(npc, room):
    """
    What is here, under the names anything looking for them will accept.

    People are named the way the rest of the prompt names them. That is safe
    because setting a world name adds it as an alias, so the name a character
    is known by finds them again -- "Samuel" reaches the character whose key
    is something else entirely.
    """
    from evennia.objects.objects import DefaultCharacter

    from world import ownership, relations

    people, objects, exits, unexplored = [], [], [], []
    for obj in (room.contents if room else ()):
        if obj is npc:
            continue
        if getattr(obj, "destination", None) is not None:
            exits.append(obj.key)
            if obj.db.pending_generation or obj.destination is room:
                unexplored.append(obj.key)
        elif obj.db.is_npc or isinstance(obj, DefaultCharacter):
            people.append(obj.get_display_name(npc))
        else:
            objects.append(obj.key)

    # Within reach is wider than lying loose: into whatever is open, and onto
    # whatever something else is on. A letter in an open tray is a letter
    # anybody here can take, and `get` searched the room alone, so no
    # character ever could.
    within = [obj for obj in relations.reachable(npc)
              if obj.location is not npc]
    said = []
    for obj in within:
        where = []
        host = relations.host_of(obj)
        if host is not None:
            where.append(f"{relations.preposition_of(obj)} {host.key}")
        if ownership.owner_of(obj) is npc:
            where.append("yours")
        elif ownership.owner_name(obj):
            where.append(f"{ownership.owner_name(obj)}'s")
        else:
            where.append("nobody's")
        said.append(f"{obj.key} ({', '.join(where)})")

    # What it is wearing is not what it can hand over.
    carried = [obj.key for obj in npc.contents if not obj.db.worn]

    here = {
        "people": _distinct(people),
        "objects": _distinct(objects),
        "within_reach": _distinct(obj.key for obj in within),
        "said_within_reach": _distinct(said)[:MOST_THINGS_SAID],
        "exits": _distinct(exits),
        "unexplored": _distinct(unexplored),
        "carried": _distinct(carried),
    }
    # Loose or carried, which is what the effect layer finds by name.
    here["reachable"] = _distinct(here["objects"] + here["carried"])
    here["changeable"] = _distinct(here["within_reach"] + here["carried"])
    # Sizing up yourself is worth offering only beside somebody else to size
    # up: a character's own figures are already in its prompt.
    here["sizable"] = here["people"] + ["myself"] if here["people"] else []
    return here


def _tools_for(npc, room):
    """
    The tools this character may use at this moment, and what they may name.

    A tool that cannot be used is worse than a missing one: offered every
    turn, it gets chosen every turn and refused every turn. Both quest tools
    are usable only in one specific situation, so they are only offered in
    it -- which is most of why players were being buried in requests, and why
    the world read as though it revolved around them.

    The same reasoning runs down into the arguments. A parameter typed only
    as a string is a blank filled from prose read further up the prompt, and
    it gets filled with whatever was remembered: an object somebody else is
    carrying, an exit from the room before this one. Nothing said so. `get`
    looked the name up, missed, and returned without a word to anybody --
    the character had taken its turn and visibly done nothing.

    So every argument that must name something already here is given the
    list of what that is, and a tool whose list would be empty is dropped
    beside the situational ones. Naming a thing that is not there stops
    being a silent miss and becomes impossible.

    What is deliberately NOT listed: `attempt` and `create`. Those are how
    something the room merely describes becomes real, and a closed list is
    the one thing that would take that away.

    What is said about this moment goes into the descriptions: whose each thing
    within reach is and where it sits, which ways out lead somewhere nobody has
    been, the terms of a request waiting on an answer, and what this world
    already knows how to do.
    """
    from world import quests

    here = _nameable(npc, room)
    askable = _distinct(person.get_display_name(npc)
                        for person in quests.candidates(room, exclude=npc))

    offered = []
    for tool in NPC_TOOLS:
        name = tool["function"]["name"]

        if name == "answer_quest":
            offer = quests.offered_to(npc)
            if offer is None:
                continue
            offered.append(_described(tool, _terms_of(offer)))
            continue

        if name == "offer_quest":
            if not askable:
                continue
            tool = _with_choices(tool, {"person": askable})
            deadline = tool["function"]["parameters"]["properties"][
                "time_limit_seconds"]
            deadline["minimum"] = quests.MIN_TIME_LIMIT
            deadline["maximum"] = quests.MAX_TIME_LIMIT
            offered.append(_described(tool, _carrying_note(here["carried"])))
            continue

        if name == "attempt":
            offered.append(_described(tool, _attempt_note(room)))
            continue

        if name == "say":
            # Anybody in particular to speak to, or nobody, in which case the
            # argument is not offered at all.
            offered.append(_with_choices(tool, {"to": here["people"]})
                           if here["people"] else _without(tool, "to"))
            continue

        wanted = _TOOL_CHOICES.get(name)
        if not wanted:
            offered.append(tool)
            continue

        choices = {argument: here.get(source) or []
                   for argument, source in wanted.items()}
        # Every one of them, not any: `give` with something to give and
        # nobody to give it to is as useless as `give` with neither.
        if not all(choices.values()):
            continue
        tool = _with_choices(tool, choices)
        noting = _NOTES.get(name)
        offered.append(_described(tool, noting(here)) if noting else tool)

    return offered


def _with_choices(tool, choices):
    """A copy of `tool` whose named arguments are closed to these values."""
    from copy import deepcopy

    tool = deepcopy(tool)
    properties = tool["function"]["parameters"]["properties"]
    for argument, values in choices.items():
        properties[argument]["enum"] = list(values)
    return tool


def _described(tool, note):
    """A copy of `tool` with something about this moment added to what it says."""
    if not note:
        return tool
    from copy import deepcopy

    tool = deepcopy(tool)
    tool["function"]["description"] = f"{tool['function']['description']} {note}"
    return tool


def _without(tool, argument):
    """A copy of `tool` that does not offer `argument` at all."""
    from copy import deepcopy

    tool = deepcopy(tool)
    tool["function"]["parameters"]["properties"].pop(argument, None)
    return tool


def _unexplored_note(here):
    names = here["unexplored"]
    if not names:
        return ""
    return (f"Nobody has been through {', '.join(names)} yet: going that way "
            f"builds somewhere new, and takes a while.")


def _within_reach_note(here):
    said = here["said_within_reach"]
    return f"Within reach: {'; '.join(said)}." if said else ""


#: What each tool is told about this moment, beyond what it may name.
_NOTES = {
    "move": _unexplored_note,
    "get": _within_reach_note,
}


def _carrying_note(carried):
    """What a character has to offer, so a reward it promises is a real one."""
    if carried:
        return f"You are carrying {', '.join(carried)}."
    return ("You are carrying nothing to give, so offer something you can do "
            "rather than something you have.")


def _terms_of(offer):
    """A request waiting on an answer, as the character choosing is told it."""
    from world import quests

    asked = str(offer.get("description") or offer.get("title")
                or "something").strip().rstrip(".")
    said = [f"{offer.get('giver') or 'Somebody'} has asked you: {asked}.",
            f"They offer: {quests._summarise(offer.get('reward'))}."]
    if offer.get("punishment"):
        said.append(f"If it is not done: "
                    f"{quests._summarise(offer.get('punishment'))}.")
    if offer.get("time_limit"):
        said.append(f"It has to be done within "
                    f"{quests._short_time(offer['time_limit'])}.")
    return " ".join(said)


def _attempt_note(room):
    """
    What `attempt` can already do here, which was a line of the system prompt
    and belongs beside the tool it is about.

    Named in two halves. The verbs the game itself handles, read off the
    modules that take them over, so a character knows wearing and putting are
    already understood. And the verbs this world has worked out, capped,
    because a world learns verbs without end.
    """
    from world import clothing, gear, ownership, relations

    handled = sorted({str(verb) for module in (clothing, gear, ownership,
                                               relations)
                      for verb in getattr(module, "VERBS", ())})
    said = []
    if handled:
        said.append(f"The game itself handles {', '.join(handled)}.")
    known = _known_verbs(room)
    if known:
        shown = known[:MOST_VERBS_NAMED]
        more = len(known) - len(shown)
        said.append(f"This world has already worked out {', '.join(shown)}"
                    + (f", and {more} more." if more else "."))
    return " ".join(said)

def _known_verbs(room):
    """
    Verbs this world has already worked out, cheapest first to reuse.

    Offering them is not a restriction -- an NPC may attempt anything, and a
    verb nobody has used yet simply costs the world one call to learn. Naming
    the ones already known nudges reuse of what is free.
    """
    world_root = room.db.world_root if room else None
    if not world_root:
        return []
    seen = []
    for key in (world_root.db.verb_rules or {}):
        verb = key.split("#", 1)[0]
        if verb not in seen:
            seen.append(verb)
    return sorted(seen)


#: How many recent events go into a prompt verbatim.  Everything older is
#: reached through memory instead, so this stays small on purpose.
WORKING_MEMORY_EVENTS = 5


def _recall_cues(npc, room, room_title):
    """
    What to ask a character's memory about, best cue first.

    Recall used to be asked about the last thing that happened, which is the
    one thing it cannot usefully answer: the last thing that happened is
    already in the prompt, verbatim, two inches further down. What is missing
    from the prompt is everything older -- and what makes an old memory worth
    having now is the situation the character is standing in.

    So the cues are the situation itself, in the order they earn their place:

    Who is here. The strongest of them, and the one recency serves worst: a
    character who has been sitting with somebody for twenty turns has long
    since pushed their arrival out of working memory, so the history of
    knowing them is exactly what the prompt no longer says. Someone who is not
    in the room is left out on purpose -- what a character remembers about an
    absent third party is rarely what they should be thinking about.

    What they are trying to do, which is what makes a memory relevant rather
    than merely familiar.

    Where they are, for whatever happened here before.

    What they are carrying, last: an NPC holding a key seldom needs memories
    about the key, and it earns its place only on the turns when the stronger
    cues came back with nothing.

    The last event is kept as a cue too, but as one among several rather than
    the only one. It is still what provoked this turn, and a memory that bears
    on it is still worth having -- it is being the sole cue that was wrong.
    """
    from evennia.objects.objects import DefaultCharacter

    from world import goals

    people, things = [], []
    for obj in room.contents:
        if obj is npc or getattr(obj, "destination", None) is not None:
            continue
        if obj.db.is_npc or isinstance(obj, DefaultCharacter):
            people.append(obj.key)

    for obj in npc.contents:
        if not obj.db.worn:
            things.append(obj.key)

    world_root = room.db.world_root
    want = goals.describe(npc.db.goal, npc, world_root) if npc.db.goal else ""

    history = npc.db.action_history or []
    cues = list(people)
    if want and want != "nothing in particular":
        cues.append(want)
    cues.append(room_title)
    if history:
        cues.append(_format_history(history[-1:]))
    cues.extend(things)
    return cues


def _memory_inputs(npc, room, room_title):
    """
    Prepare an NPC's prompt memory. Main thread -- it reads the Evennia DB.

    Returns (recent events as text, memory bank name, recall cues, the lines
    already on show).

    The lines already on show are handed to recall so it can leave them out.
    A character remembers an event in the very words its working memory holds
    it in, so without that the events it is being asked about come back as the
    memories most relevant to themselves -- and the prompt says everything
    twice. See memory.recall_sync.
    """
    from world.memory import where_for

    history = npc.db.action_history or []
    recent = history[-WORKING_MEMORY_EVENTS:]
    on_show = [_format_history([event]) for event in recent]
    cues = _recall_cues(npc, room, room_title)
    return _format_history(recent), where_for(npc), cues, on_show


def _format_history(history):
    """
    Working memory as the prompt reads it, each line as it was remembered.

    The line an entry was remembered by, when it has one, so that "Just now"
    and what recall finds are the same words -- past tense both -- and recall
    can leave out what is already on show by comparing them.
    """
    if not history:
        return "(no prior events)"
    from world.memory import describe_event

    return "\n".join(
        event.get("line") or describe_event(
            event.get("type", "action"),
            event.get("actor", "?"),
            event.get("text", ""),
        )
        for event in history
    )


# ---------------------------------------------------------------------------
# Public sync helper
# ---------------------------------------------------------------------------

def notify_npcs(room, event_type, actor_name, text, exclude=None, actor=None,
                about=None, addressed=None, targets=(), line=None,
                metadata=None):
    """
    Tell everyone in `room` that something happened. Main thread only.

    NPCs witness it, which may provoke a reaction; player characters record it
    to memory.  NPCs write their own memories through their history hook, so
    they are not recorded twice here.

    event_type : "say" | "action" | "emote"
    exclude    : an object to skip (e.g. the NPC that caused the event)
    actor      : the character responsible, when it is one -- they remember
                 doing it rather than merely seeing it
    about      : who and what it concerned, as `memory.remember` takes it
    addressed  : who was spoken to, the same shape
    targets    : whoever the command itself named, such as a whisper's
                 listener
    line       : the memory already written, when there is an event behind
                 it -- see `memory.episode_of` -- and `metadata` to go with it

    For speech and poses nobody has said who was involved, so the words are
    read for names -- see `world.recognition` -- and every memory of the
    moment, and every NPC deciding whether it was spoken to, gets the answer.
    """
    from world.memory import record_room_event

    if about is None and addressed is None and event_type in ("say", "emote"):
        from world import recognition

        mentions = recognition.recognise(text, speaker=actor, room=room,
                                         targets=targets)
        about = recognition.about(mentions)
        addressed = recognition.addressed(mentions)
    about, addressed = list(about or ()), list(addressed or ())

    record_room_event(room, event_type, actor_name, text, actor=actor,
                      about=about, addressed=addressed, line=line,
                      metadata=metadata)

    for obj in room.contents:
        if obj is exclude:
            continue
        if obj.db.is_npc:
            obj.witness(event_type, actor_name, text, about=about,
                        addressed=addressed, line=line, metadata=metadata)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def generate_npc(sponsor, room, on_success, on_error):
    """
    Async. Generate and spawn an NPC appropriate for the room.
    Calls on_success(npc_obj) or on_error(msg) in the main thread.
    """
    model = sponsor.model_for("npcs")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    from world import lore, pronouns, token_lists, tokens, traits

    world_desc = lore.description(room)
    room_title = room.db.room_title or room.key
    room_desc = tokens.text_of(room)

    # Who is already here, so the model is not asked to invent a stranger in
    # ignorance of everyone it has invented before. Listing them is most of
    # the fix; the check below is what happens when the list is ignored.
    existing = _people_in_world(room)
    taken = (
        f"Already living in this world, and not to be named again or "
        f"varied on: {', '.join(sorted(existing))}\n\n" if existing else ""
    )

    messages = [
        {"role": "system", "content": _NPC_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {world_desc}\n\n"
                f"{lore.guidance_block(room, 'npcs')}"
                f"{token_lists.TOOL_PROMPT}\n"
                f"Room: [{room_title}]\n{room_desc}\n\n"
                f"{taken}"
                "Generate an NPC who would naturally be found here."
            ),
        },
    ]

    def _spawn(data):
        try:
            data = dict(data or {})
            name = str(data.get("name") or "Stranger").strip()
            description = str(data.get("description", "")).strip()
            manner = str(data.get("manner", "")).strip()

            from evennia import create_object
            from typeclasses.npcs import NPC
            from world import kinds

            token_lists.declare(room.db.world_root, data.get("new_token_lists"))
            npc = create_object(NPC, key=name, location=room)
            npc.db.desc = description
            # A character is a sort of thing. Said here as well as in the
            # typeclass because a generated character is given its description
            # and its manner in this order, and a kind belongs beside them.
            kinds.ensure_person(npc)
            # Their eyes are one colour from the first moment, whoever looks.
            tokens.settle(npc)
            # Kept apart from the description: this is who they are, which
            # players never see by looking, and which the character itself
            # needs in order to behave like anyone in particular.
            npc.db.manner = manner
            # What other people will say about them. A set this world already
            # keeps is used by name; a declared one is registered first and
            # then given, because `give` refuses a word the register has never
            # heard -- which is the discipline rather than an obstacle to it.
            # A declaration that folds onto an existing set comes back as that
            # set's slug, which is why the return value is what gets used.
            wanted = str(data.get("pronouns", "") or "").strip()
            declared = data.get("new_pronoun_set")
            if declared:
                wanted = pronouns.register(room.db.world_root, declared) or wanted
            pronouns.give(npc, wanted, room.db.world_root)
            # What they are trying to bring about. The planner works at this
            # between conversations, so a character arrives already wanting
            # something rather than waiting to be given a purpose.
            from world import goals

            npc.db.goal = goals.sanitise(data.get("goal"), owner=npc)
            npc.db.world_description = room.db.world_description
            # Only traits the world already keeps. A character born with one
            # nobody else has is the beginning of a second vocabulary, which
            # is the one thing the register exists to prevent -- so anything
            # unregistered is dropped here rather than quietly added.
            world_root = room.db.world_root
            for spec in (data.get("traits") or [])[:4]:
                try:
                    slug = traits._slug(spec.get("slug", ""))
                    if not slug or not traits.known(world_root, slug):
                        continue
                    traits.adjust(npc, slug, set_to=spec.get("value"),
                                  world_root=world_root, announce=False)
                except Exception as exc:
                    logger.log_info(f"could not give {npc.key} a trait: {exc}")
            on_success(npc)
            # Nobody arrives naked and empty-handed. A second pass, the way a
            # finished room gets its contents: the character exists and can be
            # spoken to already, and their clothes catch up a moment later.
            dress_npc(sponsor, npc)
        except Exception as exc:
            on_error(str(exc))

    def _after_rounds(last):
        if not last:
            on_error("no character came back")
            return
        if _check_name(last, existing):
            # Out of rounds. Better a second Yuna than no character at all,
            # but it is worth knowing the model would not budge.
            logger.log_info(
                f"npc naming: kept '{last.get('name')}' after {NPC_ROUNDS} "
                f"rounds; it clashes with somebody here")
        _spawn(last)

    from world import lookups
    from world import toolbox as tb

    # The retries this used to build by hand -- the answer, then the name
    # complaint as a user turn -- are the loop's own now, and a trait, goal,
    # pronoun set or word list that would have been dropped is sent back too.
    box = tb.Toolbox([character_tool(existing)] + lookups.named(*NPC_LOOKUPS),
                     tb.ToolContext(world_root=room.db.world_root, room=room,
                                    sponsor=sponsor, job="npcs"))
    llm.converse(sponsor, model, messages, box, on_done=_spawn,
                 on_error=on_error, on_exhausted=_after_rounds,
                 rounds=NPC_ROUNDS)


def dress_npc(sponsor, npc):
    """
    Async, fire-and-forget. Give a new character their clothes and belongings.

    A second pass rather than part of the first, for the same reason a room's
    contents are: the character is usable the moment they exist, and asking
    one call to invent a person and their wardrobe together gets a worse
    answer at both. Errors are swallowed -- an underdressed character is a
    small loss and a stalled generation is not.
    """
    from world import clothing

    room = npc.location
    if room is None:
        return
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError:
        return
    model = sponsor.model_for("contents", "items", "npcs")

    from world import gear, goals, kinds, lore, verbs

    system = _NPC_OUTFIT_SYSTEM.replace(
        "{garment_types}", ", ".join(clothing.GARMENT_TYPES)
    ).replace("{naming_rule}", verbs.naming_rule()
    ).replace("{anchor_rule}", kinds.anchor_rule()
    ).replace("{affordance_rule}", _affordance_rule())
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"World: {lore.description(room)}\n\n"
                f"{lore.guidance_block(room, 'npcs')}"
                f"Room: [{room.db.room_title or room.key}]\n"
                f"{tokens.text_of(room)}\n\n"
                f"Character: {npc.key}\n"
                f"Their body: {tokens.text_of(npc) or '(not described)'}\n"
                f"Who they are: {npc.db.manner or '(not described)'}\n"
                f"What they want: {goals.describe(npc.db.goal)}\n\n"
                f"{gear.prompt_block(room.db.world_root)}"
                + _hints_block(
                    carry_hints(npc),
                    "Somebody in this world wants these, and there are none "
                    "anywhere. Give this character one to carry only if their "
                    "trade or errand would plausibly have it, named as the "
                    "line says:")
                + f"Dress {npc.key} and give them what they carry."
            ),
        },
    ]

    def _done(data):
        if not isinstance(data, dict):
            return
        if npc.location is None:
            return      # deleted while the call was in flight

        # Worn first and in the order given: the model dresses from the skin
        # outwards, and the contrib covers an undershirt only when the shirt
        # that hides it goes on after it.
        for spec in (data.get("worn") or [])[:8]:
            try:
                clothing.create(spec, location=npc, worn_on=npc)
            except Exception as exc:
                logger.log_info(f"could not dress {npc.key}: {exc}")
        for spec in (data.get("carried") or [])[:3]:
            try:
                clothing.create(spec, location=npc)
            except Exception as exc:
                logger.log_info(f"could not equip {npc.key}: {exc}")

    from world import lookups
    from world import toolbox as tb

    # Rounds out, the last outfit is put on as it stands; a failure leaves
    # them as they arrived, the small loss it always was.
    box = tb.Toolbox([dressing_tool()] + lookups.named(*DRESS_LOOKUPS),
                     tb.ToolContext(world_root=room.db.world_root, room=room,
                                    actor=npc, sponsor=sponsor, job="contents"))
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=lambda _why: None, on_exhausted=_done,
                 rounds=DRESS_ROUNDS)


def generate_npc_idle(sponsor, npc, room, on_success, on_error, depth=0):
    """
    Async. The character does something of its own accord. See `_npc_turn`.
    Calls on_success({tool: calls}) or on_error(msg) in the main thread.
    """
    _npc_turn(
        sponsor, npc, room, on_success, on_error,
        remembered="What you remember about this place and these people, "
                   "oldest first:",
        asked=("Nothing has just happened — act of your own accord. "
               "What do you do right now, naturally and in character? "
               "Choose something that fits the moment and the world."),
        depth=depth,
    )


def generate_npc_reaction(sponsor, npc, room, on_success, on_error, depth=0):
    """
    Async. The character answers what has just happened. See `_npc_turn`.
    Calls on_success({tool: calls}) or on_error(msg) in the main thread.
    """
    _npc_turn(
        sponsor, npc, room, on_success, on_error,
        remembered="What you remember that bears on this, oldest first:",
        asked="How do you respond?",
        depth=depth,
    )


def _npc_turn(sponsor, npc, room, on_success, on_error, remembered, asked,
              depth=0):
    """
    One turn for a character: its prompt, its memories, its tools, and what
    it chose to do.

    Idle and reaction were this function twice, down to the parsing of the
    tool calls, and differed only in how their memories were introduced and
    what they were finally asked.

    The turn goes round (Phase 3): each tool runs as the model calls it, and
    what it found or why it was refused comes back as its result. Sizing
    somebody up and answering them are one turn now, where the answer used to
    wait for the next. What `on_success` is handed is how often each tool was
    used; the tools themselves have already run.
    """
    model = sponsor.model_for("dialogue")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    # {{user}} names whoever is here, so an NPC reads the world the way
    # the player it is talking to appears in it.
    from world import clothing, lore, tokens
    from world.activity import active_players_in

    nearby = active_players_in(room)
    world_desc = (lore.description(room, nearby[0] if nearby else None)
                  or npc.db.world_description or "")
    room_title = room.db.room_title or room.key
    room_desc = tokens.text_of(room)
    room_contents = _room_context(room, npc)

    # Working memory verbatim, long memory by relevance.  Anything the model
    # needs from further back is recalled rather than replayed.
    history_text, bank, cues, on_show = _memory_inputs(npc, room, room_title)

    box = _toolbox_for(npc, room, depth)

    system = _NPC_REACT_SYSTEM.format(
        npc_name=npc.key,
        world_desc=world_desc,
        guidance=lore.guidance_block(room, "dialogue",
                                     nearby[0] if nearby else None),
        npc_desc=clothing.own_appearance(npc, tokens.text_of(npc)) or "(no description)",
        npc_traits=_trait_line(npc),
        npc_manner=(f"Who you are: {npc.db.manner}\n\n" if npc.db.manner else "\n"),
        room_title=room_title,
        room_desc=room_desc,
        room_contents=room_contents,
        want=_want_line(npc),
    )

    def _recall():
        # In the thread pool, off the reactor: recall is SQLite and slow.
        from world.memory import recall_for_cues

        return recall_for_cues(bank, cues, top_k=6, already_known=on_show,
                               rows=True)

    def _recalled(rows):
        # Back on the main thread, because saying a memory again with the
        # names things have now reads the game's database, which a worker
        # thread may not touch -- and then out again for the model. One hop
        # more than when recall and the call shared a thread; see
        # docs/tokens-and-phrases.md, phase 6.
        from world.memory import format_recalled

        try:
            recalled = format_recalled(rows)
        except Exception as exc:
            on_error(str(exc))
            return
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (f"{remembered}\n{recalled}\n\n"
                            f"Just now:\n{history_text}\n\n{asked}"),
            },
        ]
        llm.converse(sponsor, model, messages, box,
                     on_done=lambda _said: on_success(dict(box.used)),
                     on_error=on_error, rounds=TURN_ROUNDS)

    def _fail(failure):
        on_error(failure.getErrorMessage())

    llm.fetch(_recall, on_success=_recalled, on_error=_fail)


#: What an acting tool tells the model when nothing was said against it.
_DONE = {
    "attempt": ("Underway. How it went will be in front of you on your next "
                "turn."),
    "move": "You went.",
    "say": "Said.",
    "emote": "Done.",
}


def _toolbox_for(npc, room, depth=0):
    """
    A character's tools for one turn, each running as the model calls it.

    Lookups answer at once. Anything that acts runs through the character's
    own handler, and whatever the character was told about it -- the refusal
    `_note_to_self` would have kept for the next prompt -- is its result
    now. At most `MOST_ACTS` things act in one turn, across every round.

    `attempt` answers at once rather than waiting for the attempt to finish.
    Some of its early returns never call back, and a turn waiting on one of
    those would leave the character thinking for ever; what comes of it
    reaches the next prompt the way it always has.
    """
    from world import toolbox as tb

    acted = {"count": 0}

    def running(name):
        def handler(ctx, args, answer):
            if name in LOOKING:
                return answer(npc._sized_up(str(args.get("person") or "").strip(),
                                            room))
            if acted["count"] >= MOST_ACTS:
                return answer("Not done: that is enough for one turn.")
            acted["count"] += 1
            npc.ndb.idle_probability = 0
            npc.ndb.noticing = []
            try:
                npc._execute_one(name, args, room, depth)
                noticed = list(npc.ndb.noticing or [])
            finally:
                npc.ndb.noticing = None
            answer("; ".join(noticed) if noticed else _DONE.get(name, "Done."))
        return handler

    tools = [tb.from_schema(schema, running(schema["function"]["name"]),
                            looks=schema["function"]["name"] in LOOKING)
             for schema in _tools_for(npc, room)]
    # The first lookups a character is offered: a closer look at something
    # here, its own memory, what this world already knows how to do, and what
    # is wrong with its rules. Each is left out where it cannot answer.
    from world import lookups

    tools += lookups.named("examine", "recall", "list_known_verbs",
                           "world_faults")
    return tb.Toolbox(tools, tb.ToolContext(
        world_root=room.db.world_root if room else None, room=room,
        actor=npc, job="dialogue"))


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`name_taken`: whether a person's name is free in this world."""
    from world import toolbox as tb

    def checking(ctx, args):
        name = str(args.get("name") or "").strip()
        existing = _people_in_world(ctx.room)
        if not name:
            return "Give a name to check."
        if _too_similar(name, existing):
            close = sorted(other for other in existing
                           if _too_similar(name, [other]))
            return (f"{name} is too close to somebody already in this world: "
                    f"{', '.join(close) or 'the name is unusable'}. Choose a "
                    f"different first name.")
        return f"{name} is free."

    return [tb.Tool(
        "name_taken",
        "Whether a person's name is free in this world. A shared first name, "
        "or the same words in another order, is taken; a shared family name "
        "is fine.",
        tb.params({"name": {"type": "string",
                            "description": "The name to check"}}, ["name"]),
        tb.answering(checking), doing="checking a name is free", looks=True,
        available=lambda ctx: ctx.room is not None)]


# ---------------------------------------------------------------------------
# Making and dressing a character on finish tools (docs §4.2)
# ---------------------------------------------------------------------------

#: Rounds each may take (§10.3). A character is made while somebody walks into
#: a room; dressing them is background work nobody waits on.
NPC_ROUNDS = 8
DRESS_ROUNDS = 10

NPC_LOOKUPS = ("list_traits", "show_trait", "list_pronoun_sets",
               "list_word_lists", "show_word_list", "find_rooms",
               "list_states")
DRESS_LOOKUPS = ("list_states", "list_state_groups", "list_traits",
                 "kind_info", "commonsense")

#: How many wanted things a character being dressed is shown (§5.1).
CARRY_WANTS = 2


def _listed(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _hints_block(lines, header):
    """A header and its lines for a prompt, or "" when there are none."""
    if not lines:
        return ""
    return header + "\n" + "\n".join(f"  - {line}" for line in lines) + "\n\n"


def character_tool(existing):
    """
    `make_character`, the finish tool `generate_npc` answers with.

    `traits[].slug` is closed to the register up to the enum cap; `goal` is
    `goals.schema`; `new_pronoun_set` is `pronouns.set_schema`. `pronouns` is
    left open, because a declared set's subject form goes there too, and its
    handler says which sets exist.
    """
    from world import toolbox as tb

    def parameters(ctx):
        from world import goals, pronouns, token_lists, traits

        known = sorted(traits.vocabulary(ctx.world_root))
        sets = sorted(pronouns.vocabulary(ctx.world_root))
        trait = {"type": "object",
                 "properties": {
                     "slug": tb.choice(known, "A trait this world measures",
                                       ask="list_traits"),
                     "value": {"type": "number",
                               "description": "Where they stand; an ordinary "
                                              "person is middling"}},
                 "required": ["slug", "value"]}
        return tb.params({
            "name": {"type": "string",
                     "description": "How the player will address them, 1-3 "
                                    "words"},
            "description": {"type": "string",
                            "description": "Their body, and nothing else"},
            "manner": {"type": "string",
                       "description": "Who they are and how they behave"},
            "pronouns": {"type": "string",
                         "description": "What others say about them: one of "
                                        + ", ".join(sets)
                                        + ", or a declared set's subject form"},
            "new_pronoun_set": dict(
                pronouns.set_schema(ctx),
                description="Only for somebody none of the sets suits, and "
                            "then complete"),
            "goal": {"type": "array", "items": goals.schema(ctx),
                     "description": "What they are trying to bring about; "
                                    "empty for nothing in particular"},
            "traits": {"type": "array", "items": trait, "maxItems": 4,
                       "description": "0 to 4 figures, only traits this world "
                                      "measures"},
            "new_token_lists": {"type": "array",
                                "items": token_lists.schema(ctx),
                                "description": "Word lists the description "
                                               "uses that this world does not "
                                               "keep yet"},
        }, ["name", "description", "manner"])

    def handler(ctx, args, answer):
        said = character_complaints(args, existing, ctx.world_root)
        if said:
            answer(tb.complain("Not made: " + "; ".join(said) + ". Send the "
                               "same character again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("make_character", "Make the character who belongs here.",
                   parameters, handler, finishes=True)


def character_complaints(args, existing, world_root):
    """
    What is wrong with a character that asking again can put right.

    A name somebody already answers to, which was the one thing checked
    before; and what used to be dropped without a word: a pronoun set nobody
    keeps or one declared incomplete, goal conditions nothing can test,
    traits nothing measures, and word lists that would be refused.
    """
    from world import goals, pronouns, token_lists, traits, vocabulary

    said = []
    complaint = _check_name(args, existing)
    if complaint:
        said.append(complaint.rstrip("."))

    wanted = pronouns._slug(args.get("pronouns"))
    declared = args.get("new_pronoun_set")
    if isinstance(declared, dict) and declared:
        entry, why = pronouns.clean(declared)
        if entry is None:
            said.append(f"the new pronoun set cannot be kept: {why}")
        else:
            said += [line.rstrip(".") for line in vocabulary.near_duplicates(
                world_root, new_pronoun_set=declared)]
            if wanted and wanted != entry["subject"]:
                said.append(f"pronouns has to be the new set's subject form, "
                            f"{entry['subject']}")
    elif wanted and wanted not in pronouns.vocabulary(world_root):
        said.append(f"this world keeps no pronoun set called {wanted}; use "
                    f"one of {', '.join(sorted(pronouns.vocabulary(world_root)))}"
                    f", or declare it whole in new_pronoun_set")

    goal = _listed(args.get("goal"))
    if goal:
        kept = goals.sanitise(goal)
        if len(kept) < len(goal):
            said.append(f"{len(goal) - len(kept)} of the goal's conditions "
                        f"cannot be tested and would be dropped")

    given = [trait for trait in _listed(args.get("traits"))
             if isinstance(trait, dict)]
    if len(given) > 4:
        said.append(f"give at most 4 traits, not {len(given)}")
    strange = sorted({traits._slug(trait.get("slug")) for trait in given}
                     - set(traits.vocabulary(world_root)) - {""})
    if strange:
        said.append("traits names " + ", ".join(strange) + ", which this "
                    "world does not measure; list_traits shows what it does")

    declared_lists = _listed(args.get("new_token_lists"))
    said += token_lists.complaints(world_root, declared_lists,
                                   [args.get("description")])
    said += [line.rstrip(".") for line in vocabulary.near_duplicates(
        world_root, new_token_lists=[entry for entry in declared_lists
                                     if isinstance(entry, dict)])]
    return said


def dressing_tool():
    """
    `dress_character`, the finish tool `dress_npc` answers with: garments with
    `clothing.spec_schema(worn=True)`, things carried with the plain schema.
    """
    from world import toolbox as tb

    def parameters(ctx):
        from world import clothing

        return tb.params({
            "worn": {"type": "array",
                     "items": clothing.spec_schema(ctx, worn=True),
                     "maxItems": 8,
                     "description": "What they have on, from the skin "
                                    "outwards: 2 to 6 garments"},
            "carried": {"type": "array", "items": clothing.spec_schema(ctx),
                        "maxItems": 3,
                        "description": "What is in their hands or pockets: 0 "
                                       "to 3 things"},
        }, ["worn", "carried"])

    def handler(ctx, args, answer):
        said = dressing_complaints(args, ctx.world_root)
        if said:
            answer(tb.complain("Not dressed: " + "; ".join(said) + ". Send "
                               "the outfit again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("dress_character", "Dress this character and give them "
                                      "what they carry.",
                   parameters, handler, finishes=True)


def dressing_complaints(args, world_root):
    """Each item held to `make_item`'s rules, and every garment wearable."""
    from world import item_gen

    said = []
    for field, most in (("worn", 8), ("carried", 3)):
        items = [item for item in _listed(args.get(field))
                 if isinstance(item, dict)]
        if len(items) > most:
            said.append(f"give at most {most} {field} things, not {len(items)}")
        for item in items[:most]:
            name = str(item.get("name") or "").strip() or f"a {field} thing"
            said += [f"{name}: {line}"
                     for line in item_gen.item_complaints(item, world_root)]
            given = item.get("affordances")
            if field == "worn" and not (isinstance(given, dict)
                                        and given.get("wear")):
                said.append(f"{name}: a garment has to afford wear")
    return said


def carry_hints(npc):
    """
    Things somebody wants that exist nowhere, for a character to carry (§5.1).

    Never the character's own wants -- dressed carrying what they were made
    wanting, they would be satisfied before taking a step -- and never in a
    room the want avoids. A merchant carrying the ore turns an impossible
    quest into a trade; whether this one would, the prompt leaves to the
    model.
    """
    room = getattr(npc, "location", None)
    world_root = room.db.world_root if room is not None else None
    if world_root is None:
        return []
    from world import planner, worldgen

    lines = []
    for want in worldgen._wants(world_root):
        if (want.get("reason") != planner.MISSING_THING
                or not want.get("words")
                or getattr(want.get("who"), "id", None) == npc.id
                or room.id in (want.get("avoid") or ())):
            continue
        who = getattr(want.get("who"), "key", "somebody")
        lines.append(f"{who} wants something {want['words']}.")
        if len(lines) >= CARRY_WANTS:
            break
    return lines
