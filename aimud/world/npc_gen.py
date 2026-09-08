"""
AI generation and reaction for NPCs.

generate_npc()          — create an NPC appropriate to a room (async)
generate_npc_reaction() — send tool-call request to dialogue model (async)
notify_npcs()           — notify all NPCs in a room of an event (sync helper)
"""

import json
import re
import urllib.request

from evennia.utils import logger
from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

#: How many times a character may be sent back to be renamed. Each retry is a
#: whole generation rather than a cheap naming call the way a room's is, so
#: the model is asked to keep the character it invented and change only the
#: name -- and after this many tries the answer is taken as it stands.
NAME_ATTEMPTS = 3

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
            "description": "Move through an available exit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "Exit direction or name (e.g. 'north', 'east')",
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
                    "message": {"type": "string"}
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get",
            "description": "Pick up an object from the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"}
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
                    "object_name": {"type": "string"},
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
                        "description": "Third-person description, e.g. 'nods solemnly' or 'adjusts her hood'",
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
                "room. What you find comes back to you as something you have "
                "noticed, so you can act on it on your next turn. Sizing "
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
                        "description": "Who to size up. Leave empty for yourself.",
                    },
                },
                "required": [],
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
                        "description": "Optional deadline in seconds. Omit if there is no hurry.",
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
            "description": "Create a new object in the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "takeable": {
                        "type": "boolean",
                        "description": "Whether the object can be picked up by players",
                    },
                },
                "required": ["name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "destroy",
            "description": "Destroy an object in the room or in your inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"}
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify",
            "description": "Change the name or description of an existing object.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "Current name of the object to modify",
                    },
                    "new_name": {"type": "string"},
                    "new_description": {"type": "string"},
                },
                "required": ["object_name"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_NPC_GEN_SYSTEM = """You generate NPC characters for a text-based MUD.
Respond with a single JSON object only — no other text:
{
  "name": "Character Name (1-3 words)",
  "description": "2-4 sentences: what they look like, and nothing else",
  "manner": "2-3 sentences: who they are and how they behave",
  "goal": [ ... ],
  "traits": [{"slug": "swordsmanship", "value": 12}]
}

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
Name only things that plausibly exist in this world. Give an empty list for a
character with nothing in particular to pursue.

"traits" is what is measurably true of this character, as figures. Give 0 to 4,
and ONLY ones already in the world's register, which is listed for you below.
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
    "{known_verbs}"
    "{want}"
    "Use the available tools to react naturally to recent events. "
    "You may call 0-3 tools per response. "
    "If nothing warrants a response, call no tools. Keep reactions brief and in-character.\n\n"
    "To do something physical, use the `attempt` tool with the action written "
    "as a short command — 'light candle', 'open drawer', 'read notice'. That "
    "actually changes the world: the object really is lit, opened or taken, and "
    "everyone present sees it. Do not use `emote` to pretend an action happened; "
    "emote is for gestures and expression only. You are free to attempt actions "
    "nobody has tried before."
)

_NPC_OUTFIT_SYSTEM = """You dress a character in a text-based MUD and give them what they carry.
Respond with a single JSON object — no other text — matching:
{
  "worn": [
    {"name": "item name", "description": "1-2 sentences",
     "clothing_type": "top", "wearstyle": "",
     "affordances": ["wearable"], "states": [],
     "trait_bonuses": {}, "bonus_when": ""}
  ],
  "carried": [
    {"name": "item name", "description": "1-2 sentences", "takeable": true,
     "affordances": ["readable"], "states": [],
     "trait_bonuses": {}, "bonus_when": ""}
  ]
}

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

affordances are what can be done with a thing, as lowercase single words:
readable, openable, container, surface, flammable, edible, drinkable, wearable,
(a "container" is hollow and things go IN it; a "surface" has a top and things
go ON it -- a table, a shelf, a counter, a desk. Many things are both.)
breakable, wieldable. Every garment must include "wearable". states are
conditions currently true of it (patched, bloodstained, damp), usually empty.

{naming_rule}
Return only the JSON object."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_openrouter(api_key, model, messages, tools=None):
    payload = {"model": model, "messages": messages}
    # The sampling settings chosen for this job ride on the model choice. See
    # world.model_params: only what the player actually set is sent.
    from world.model_params import of as _settings

    payload.update(_settings(model))
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _parse_json(content):
    """
    Parse a model response that should be a single JSON object.

    Delegates to world.model_json, which repairs the near-misses models make
    -- a trailing comma, a stray comment, an answer cut off mid-object --
    rather than losing a whole generation over one character.
    """
    from world.model_json import parse_object

    return parse_object(content)


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
            marks = list(obj.db.affordances or [])
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
        asked = offer.get("description") or offer.get("title")
        return (
            f"{offer['giver']} has asked something of you: {asked}\n"
            "Answer with answer_quest, as this character would. You are free "
            "to refuse; agreeing means you will work at it until it is done "
            "or you give it up.\n\n"
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


def _tools_for(npc, room):
    """
    The tools this character may use at this moment.

    A tool that cannot be used is worse than a missing one: offered every
    turn, it gets chosen every turn and refused every turn. Both quest tools
    are usable only in one specific situation, so they are only offered in
    it -- which is most of why players were being buried in requests, and why
    the world read as though it revolved around them.
    """
    from world import quests

    drop = set()
    if quests.offered_to(npc) is None:
        drop.add("answer_quest")
    if not quests.candidates(room, exclude=npc):
        drop.add("offer_quest")
    if not drop:
        return NPC_TOOLS
    return [tool for tool in NPC_TOOLS if tool["function"]["name"] not in drop]


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
    from world.memory import bank_for

    history = npc.db.action_history or []
    recent = history[-WORKING_MEMORY_EVENTS:]
    on_show = [_format_history([event]) for event in recent]
    cues = _recall_cues(npc, room, room_title)
    return _format_history(recent), bank_for(npc), cues, on_show


def _format_history(history):
    if not history:
        return "(no prior events)"
    from world.memory import describe_event

    return "\n".join(
        describe_event(
            event.get("type", "action"),
            event.get("actor", "?"),
            event.get("text", ""),
        )
        for event in history
    )


# ---------------------------------------------------------------------------
# Public sync helper
# ---------------------------------------------------------------------------

def notify_npcs(room, event_type, actor_name, text, exclude=None, actor=None):
    """
    Tell everyone in `room` that something happened. Main thread only.

    NPCs witness it, which may provoke a reaction; player characters record it
    to memory.  NPCs write their own memories through their history hook, so
    they are not recorded twice here.

    event_type : "say" | "action" | "emote"
    exclude    : an object to skip (e.g. the NPC that caused the event)
    actor      : the character responsible, when it is one -- they remember
                 doing it rather than merely seeing it
    """
    from world.memory import record_room_event

    record_room_event(room, event_type, actor_name, text, actor=actor)

    for obj in room.contents:
        if obj is exclude:
            continue
        if obj.db.is_npc:
            obj.witness(event_type, actor_name, text)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def generate_npc(account, room, on_success, on_error):
    """
    Async. Generate and spawn an NPC appropriate for the room.
    Calls on_success(npc_obj) or on_error(msg) in the main thread.
    """
    model = account.model_for("npcs")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    from world import lore, traits

    world_desc = lore.description(room)
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""

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
                f"{traits.vocabulary_block(room.db.world_root)}"
                f"Room: [{room_title}]\n{room_desc}\n\n"
                f"{taken}"
                "Generate an NPC who would naturally be found here."
            ),
        },
    ]

    def _attempt(remaining, convo):
        """One try at a character, sending it back if the name is taken."""
        def _answered(raw):
            try:
                content = raw["choices"][0]["message"].get("content") or ""
                data = _parse_json(content)
            except Exception as exc:
                on_error(str(exc))
                return

            complaint = _check_name(data, existing)
            if complaint and remaining > 1:
                _attempt(remaining - 1, convo + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": complaint},
                ])
                return
            if complaint:
                # Out of tries. Better a second Yuna than no character at
                # all, but it is worth knowing the model would not budge.
                logger.log_info(
                    f"npc naming: kept '{data.get('name')}' after "
                    f"{NAME_ATTEMPTS} tries; it clashes with somebody here"
                )
            _spawn(data)

        threads.deferToThread(
            _call_openrouter, api_key, model, convo
        ).addCallbacks(_answered, _fail)

    def _spawn(data):
        try:
            name = str(data.get("name", "Stranger")).strip()
            description = str(data.get("description", "")).strip()
            manner = str(data.get("manner", "")).strip()

            from evennia import create_object
            from typeclasses.npcs import NPC

            npc = create_object(NPC, key=name, location=room)
            npc.db.desc = description
            # Kept apart from the description: this is who they are, which
            # players never see by looking, and which the character itself
            # needs in order to behave like anyone in particular.
            npc.db.manner = manner
            # What they are trying to bring about. The planner works at this
            # between conversations, so a character arrives already wanting
            # something rather than waiting to be given a purpose.
            from world import goals

            npc.db.goal = goals.sanitise(data.get("goal"))
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
            dress_npc(account, npc)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    _attempt(NAME_ATTEMPTS, messages)


def dress_npc(account, npc):
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
        api_key = account.get_openrouter_key()
    except ValueError:
        return
    model = account.model_for("contents", "items", "npcs")

    from world import gear, goals, lore, verbs

    system = _NPC_OUTFIT_SYSTEM.replace(
        "{garment_types}", ", ".join(clothing.GARMENT_TYPES)
    ).replace("{naming_rule}", verbs.naming_rule())
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"World: {lore.description(room)}\n\n"
                f"{lore.guidance_block(room, 'npcs')}"
                f"Room: [{room.db.room_title or room.key}]\n"
                f"{room.db.desc or ''}\n\n"
                f"Character: {npc.key}\n"
                f"Their body: {npc.db.desc or '(not described)'}\n"
                f"Who they are: {npc.db.manner or '(not described)'}\n"
                f"What they want: {goals.describe(npc.db.goal)}\n\n"
                f"{gear.prompt_block(room.db.world_root)}"
                f"Dress {npc.key} and give them what they carry."
            ),
        },
    ]

    def _done(raw):
        try:
            content = raw["choices"][0]["message"].get("content") or ""
            data = _parse_json(content)
        except Exception:
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

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda _f: None)


def generate_npc_idle(account, npc, room, on_success, on_error):
    """
    Async. Prompt the NPC to take a spontaneous, self-initiated action.
    Uses the same tool-calling infrastructure as generate_npc_reaction but
    asks the model what the NPC would do of its own accord right now.
    Calls on_success(list[{"name", "args"}]) or on_error(msg) in the main thread.
    """
    model = account.model_for("dialogue")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    # {{user}} names whoever is here, so an NPC reads the world the way
    # the player it is talking to appears in it.
    from world import clothing, lore
    from world.activity import active_players_in

    nearby = active_players_in(room)
    world_desc = (lore.description(room, nearby[0] if nearby else None)
                  or npc.db.world_description or "")
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""
    room_contents = _room_context(room, npc)
    history_text, bank, cues, on_show = _memory_inputs(npc, room, room_title)

    verbs_known = _known_verbs(room)
    known_line = (
        f"Actions this world already understands: {', '.join(verbs_known)}\n\n"
        if verbs_known else ""
    )

    tools = _tools_for(npc, room)

    system = _NPC_REACT_SYSTEM.format(
        npc_name=npc.key,
        world_desc=world_desc,
        guidance=lore.guidance_block(room, "dialogue",
                                     nearby[0] if nearby else None),
        npc_desc=clothing.own_appearance(npc, npc.db.desc or "") or "(no description)",
        npc_traits=_trait_line(npc),
        npc_manner=(f"Who you are: {npc.db.manner}\n\n" if npc.db.manner else "\n"),
        room_title=room_title,
        room_desc=room_desc,
        room_contents=room_contents,
        known_verbs=known_line,
        want=_want_line(npc),
    )

    def _fetch():
        from world.memory import format_memories, recall_for_cues

        recalled = format_memories(
            recall_for_cues(bank, cues, top_k=6, already_known=on_show))
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"What you remember about this place and these people:\n"
                    f"{recalled}\n\n"
                    f"Just now:\n{history_text}\n\n"
                    "Nothing has just happened — act of your own accord. "
                    "What do you do right now, naturally and in character? "
                    "Choose something that fits the moment and the world."
                ),
            },
        ]
        return _call_openrouter(api_key, model, messages, tools=tools)

    def _done(raw):
        try:
            message = raw["choices"][0]["message"]
            tool_calls_raw = message.get("tool_calls") or []
            parsed = []
            for tc in tool_calls_raw:
                if tc.get("type") == "function":
                    fn = tc["function"]
                    try:
                        # Repaired rather than parsed: a tool call whose
                        # arguments will not parse used to arrive empty, and
                        # an NPC saying nothing is worse than a stray comma.
                        call_args = _parse_json(fn.get("arguments") or "{}")
                    except ValueError:
                        call_args = {}
                    parsed.append({"name": fn["name"], "args": call_args})
            on_success(parsed)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def generate_npc_reaction(account, npc, room, on_success, on_error):
    """
    Async. Send the NPC's context + history to the dialogue model with tool-calling.
    Calls on_success(list[{"name", "args"}]) or on_error(msg) in the main thread.
    """
    model = account.model_for("dialogue")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    # {{user}} names whoever is here, so an NPC reads the world the way
    # the player it is talking to appears in it.
    from world import clothing, lore
    from world.activity import active_players_in

    nearby = active_players_in(room)
    world_desc = (lore.description(room, nearby[0] if nearby else None)
                  or npc.db.world_description or "")
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""
    room_contents = _room_context(room, npc)

    # Working memory verbatim, long memory by relevance.  Anything the model
    # needs from further back is recalled rather than replayed.
    history_text, bank, cues, on_show = _memory_inputs(npc, room, room_title)

    verbs_known = _known_verbs(room)
    known_line = (
        f"Actions this world already understands: {', '.join(verbs_known)}\n\n"
        if verbs_known else ""
    )

    tools = _tools_for(npc, room)

    system = _NPC_REACT_SYSTEM.format(
        npc_name=npc.key,
        world_desc=world_desc,
        guidance=lore.guidance_block(room, "dialogue",
                                     nearby[0] if nearby else None),
        npc_desc=clothing.own_appearance(npc, npc.db.desc or "") or "(no description)",
        npc_traits=_trait_line(npc),
        npc_manner=(f"Who you are: {npc.db.manner}\n\n" if npc.db.manner else "\n"),
        room_title=room_title,
        room_desc=room_desc,
        room_contents=room_contents,
        known_verbs=known_line,
        want=_want_line(npc),
    )

    def _fetch():
        # Recall runs here, inside the thread that was already being deferred
        # for the network call, so it costs no extra hop and never touches the
        # reactor.
        from world.memory import format_memories, recall_for_cues

        recalled = format_memories(
            recall_for_cues(bank, cues, top_k=6, already_known=on_show))
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"What you remember that bears on this:\n{recalled}\n\n"
                    f"Just now:\n{history_text}\n\nHow do you respond?"
                ),
            },
        ]
        return _call_openrouter(api_key, model, messages, tools=tools)

    def _done(raw):
        try:
            message = raw["choices"][0]["message"]
            tool_calls_raw = message.get("tool_calls") or []
            parsed = []
            for tc in tool_calls_raw:
                if tc.get("type") == "function":
                    fn = tc["function"]
                    try:
                        # Repaired rather than parsed: a tool call whose
                        # arguments will not parse used to arrive empty, and
                        # an NPC saying nothing is worse than a stray comma.
                        call_args = _parse_json(fn.get("arguments") or "{}")
                    except ValueError:
                        call_args = {}
                    parsed.append({"name": fn["name"], "args": call_args})
            on_success(parsed)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)
