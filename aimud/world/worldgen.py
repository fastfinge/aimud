"""
AI-powered world and room generation via OpenRouter.

All DB access (context building, object creation) runs in the main Twisted
thread.  Only the network call to OpenRouter is deferred to a thread pool.
"""

import json
import re

from evennia.utils import logger

from world import llm, tokens


DIRECTION_ALIASES = {
    "north": ["n"],
    "south": ["s"],
    "east":  ["e"],
    "west":  ["w"],
    "northeast": ["ne"],
    "northwest": ["nw"],
    "southeast": ["se"],
    "southwest": ["sw"],
    "up":   ["u"],
    "down": ["d"],
}

OPPOSITES = {
    "north": "south", "south": "north",
    "east": "west",   "west": "east",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
    "up": "down", "down": "up",
    "in": "out",  "out": "in",
}

# Every direction word and abbreviation mapped to its canonical name, so that
# "n", "north" and an exit labelled "north passage" all resolve the same way.
CANONICAL_DIRECTIONS = {
    word: direction
    for direction, aliases in DIRECTION_ALIASES.items()
    for word in [direction, *aliases]
}
CANONICAL_DIRECTIONS["in"] = "in"
CANONICAL_DIRECTIONS["out"] = "out"

# Directions a room may be built or doored in.  Diagonals are excluded: a door
# cut corner-to-corner between two rooms is not a thing buildings do, and no
# world has ever used one.  Diagonal neighbours still appear as context, they
# are simply always wall.
BUILDABLE_DIRECTIONS = ["north", "south", "east", "west", "up", "down"]

# How a room functions in the layout.  A destination is somewhere you go to;
# circulation is how you get between them; a threshold is the seam between
# areas.  Two destinations never open directly onto each other -- classrooms
# connect through the corridor, not through each other.
CATEGORIES = ("circulation", "destination", "threshold")

_PLAN_SYSTEM_PROMPT = """You plan the layout of a world for a text-based MUD.
Answer by calling plan_world.

Zones are the areas a place is made of — a school has an admin wing, a
classroom wing, a gym block. Give 3 to 6 zones.
room_types are lowercase underscore slugs ("classroom", "chem_lab", "corridor").
room_budget is how many rooms that zone is worth walking through: a gym block
is 4 to 8, a classroom wing 12 to 20, a broom cupboard of a records office 3.
Judge each zone on its own — when a zone has that many rooms it is finished,
and the world goes on growing somewhere else instead.
singleton_types lists the slugs that must exist only ONCE in the whole world —
a school has one principal's office and one gymnasium, but many classrooms.
Judge this at the scale of the WHOLE world: a world that is one school has one
gymnasium, but a world that is a county has one of very little."""

_ZONE_SYSTEM_PROMPT = """You describe one area of a world for a text-based MUD.
Answer by calling describe_area.

You are told the name of an area somebody has just arrived in, and what
contains it. Say what it actually is.

room_budget is how many rooms this area is worth walking through in its own
right. room_types are the kinds of room it is made of, as lowercase underscore
slugs.

singleton_types lists the slugs that may exist only once INSIDE THIS AREA,
however many times they occur elsewhere in the world. A school has one
gymnasium and one principal's office; a town has one school; a county has many
towns and so lists nothing of the sort. Judge it at this area's scale and no
other.

zones is for a place that is made of smaller places. A school is an admin
wing, a classroom wing and a gym block; a market town is a high street, a
wharf and a residential quarter; a single corridor is none of these and gets
an empty list. Give 0, or 2 to 5 — one sub-area is not a division. When you
give them, keep this area's own room_budget small: it covers only the rooms
that belong to the place as a whole rather than to any part of it — its
entrance, its main corridor, the yard everything opens onto."""

_NAME_SYSTEM_PROMPT = """You decide what one room in a text-based MUD is, and where it leads.
Answer by calling name_room. The name is 2-6 words, type is a lowercase
underscore slug, and each exit's destination_hint is one sentence on what lies
that way.

category:
- "circulation": how people move between places (corridor, stairwell, lobby, junction)
- "destination": somewhere people go to and stop (classroom, office, lab, kitchen)
- "threshold": a seam between areas (doorway, airlock, gate, foyer)

Two destinations must never open directly onto each other. If the room you are
entering from is a destination, this room must be circulation or a threshold.
A destination should have few exits — usually just the way in. Circulation is
what carries traffic, so it may have several.

zone is which area this room belongs to. Normally it is one of the zones you
are told are still being built. But those zones are a place, not the world:
when every one of them is finished, or when the room genuinely lies beyond
them all — you have stepped out of the building, past the wall, off the edge of
the district — name a NEW zone instead, and say in zone_purpose what happens
there. Leave zone_purpose empty whenever you name a zone that already exists.

A room only changes zone at a seam. Either the room being left is a threshold
or the room being entered is one: a doorway, a gate, a stair head, the mouth of
a tunnel. Two ordinary rooms in different zones never open onto each other.

Write no prose beyond the destination hints."""

_DESC_SYSTEM_PROMPT = """You write the description of one room in a text-based MUD.
Answer by calling describe_room, with a description of 2-4 sentences.

trait_bonuses is what being in this room does to whoever is in it, as
{"trait": amount}. Almost always empty. Use it only for something the
description already says is true of the place itself — a forge is warm, a
clearing at noon is bright, a reactor hall is irradiated — never for an
object in the room, which has its own.

|light| is the one the game reads by name. A room that is lit by daylight, a
window, a fire or a lamp fixed to the wall should give {"light": 2}.

A room that is dark — a cellar, a cave, a corridor with no lamp — gives
NOTHING AT ALL. Do not write {"light": 0}: leave trait_bonuses empty, and the
darkness follows on its own. Only brightness is ever stated.

Describe ONLY the permanent physical fabric of the room: its architecture,
surfaces, fixtures fixed in place, light, sound, smell, temperature, wear.

Never mention:
- objects a player could pick up or that might be removed (the game places those separately)
- people, creatures or NPCs (they move; the description would go stale)
- exits or compass directions (the game lists exits itself)
- the player: no "you", no second person, no narrating what anyone does

Present tense. Concrete and sensory rather than ornate. It may echo a
neighbouring area in general terms — chlorine on the air, a hum through the
bulkhead — but never name another room."""

_CONTENTS_SYSTEM_PROMPT = """You populate a room in a text-based MUD with its loose contents.
Answer by calling furnish_room. Each item's description is 1-2 sentences.

items are the portable, removable things that happen to be here — never the
room's fixtures, which are already in its description. Give 0 to 3, and prefer
0 for a bare corridor. Do not repeat anything already named in the description.

{affordance_rule}

kind is the one common noun the item IS, singular and lowercase, with the
describing words stripped off: a "Stained Slate Chalkboard" is a chalkboard.

{anchor_rule}

holds says where things go: ["in"] for anything hollow, ["on"] for anything
with a top, [] for anything solid.

states are conditions currently true of it (dusty, wet, broken), usually empty.

{naming_rule}

clothing_type goes with the "wear" affordance and says what kind of garment it is: hat,
jewelry, top, undershirt, gloves, fullbody, bottom, underpants, socks, shoes,
accessory. A coat left over a chair can be picked up and put on by anyone who
finds it. Leave it "" for everything that is not clothing.

wants_npc asks whether someone is in this room right now. Judge it from the
room: a place people work in, wait in, staff or gather in usually has somebody
there — an office has whoever works at it, a classroom has a teacher or a
pupil, a shop has someone behind the counter. Passageways, storerooms and
empty thresholds usually do not. Decide honestly for this room rather than
defaulting either way; a world where nobody is ever anywhere feels dead."""


# ---------------------------------------------------------------------------
# Network (runs in thread)
# ---------------------------------------------------------------------------

def _affordance_rule():
    """How to declare what can be done to a thing, shared by every generator."""
    from world import affordances

    return affordances.PROMPT


# ---------------------------------------------------------------------------
# Parsing (pure Python, safe anywhere)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Context building (runs in main thread — DB access)
# ---------------------------------------------------------------------------

def _room_exit_directions(room):
    """The compass directions a room actually has exits in."""
    seen = []
    for obj in room.contents:
        if getattr(obj, "destination", None) is None:
            continue
        direction = canonical_direction(obj.key)
        if direction and direction not in seen:
            seen.append(direction)
    return seen


def _offset_direction(offset):
    """Name the direction an (dx, dy, dz) offset points in, if any."""
    from world.coords import DIRECTION_VECTORS

    for direction, vector in DIRECTION_VECTORS.items():
        if vector == offset:
            return direction
    return None


def _neighbourhood(source_room, arrival_exit, radius=2, max_chars=4000):
    """
    Describe the area around the room being generated.

    Returns a JSON string naming the target cell, its immediate neighbours by
    direction, every room within `radius` cells, and the names already in use
    nearby.  Adjacency is stated outright rather than implied by a tree, which
    is what lets the model avoid rebuilding a room that already exists next
    door.

    Falls back to walking the world_parent chain for worlds with no
    coordinates -- rooms whose old layout overlapped itself and could not be
    placed.
    """
    from world import coords

    world_root = source_room.db.world_root
    source_coord = coords.get_coord(source_room)
    target = coords.step(source_coord, arrival_exit) if source_coord else None

    if world_root is None or target is None:
        return _parent_chain_context(source_room, max_chars)

    # The six buildable cells touching the target, looked up directly so that
    # adjacency and availability can never disagree -- a same-floor scan would
    # miss the room above or below, including the source room on a vertical
    # move.  Diagonal neighbours are context only and appear under "nearby".
    touching = {
        direction: coords.room_at(world_root, coords.step(target, direction))
        for direction in BUILDABLE_DIRECTIONS
    }

    # Being next to a room is not the same as opening onto it.  Classrooms
    # along a corridor share walls and connect only to the corridor, so each
    # direction reports which of the three it is: empty ground to build on, the
    # way back, or a neighbour a door could optionally be cut through to.
    back = OPPOSITES.get(arrival_exit, "back")
    adjacent = {}
    for direction, room in touching.items():
        if room is None:
            adjacent[direction] = {"room": None, "may_open_new_room": True}
        elif direction == back:
            adjacent[direction] = {
                "room": room.db.room_title or room.key,
                "already_connected": True,
                "note": "the way back; this exit is created automatically",
            }
        else:
            entry = {
                "room": room.db.room_title or room.key,
                "category": room.db.room_category or "unknown",
            }
            # Two destinations never open onto each other.
            if room.db.room_category == "destination":
                entry["may_connect"] = False
                entry["reason"] = "both are destinations; they share a wall"
            else:
                entry["may_connect"] = True
            adjacent[direction] = entry

    # Wider area, same floor, for names to avoid reusing.
    nearby = dict(coords.neighbours(world_root, target, radius=radius))
    for direction, room in touching.items():
        if room is not None:
            offset = coords.DIRECTION_VECTORS[direction]
            nearby.setdefault(offset, room)

    # Full descriptions for what the new room touches; names only further out.
    # Each room reports the directions it actually opens onto, which is what
    # shows the layout's habits: a corridor with doors on both sides, and
    # rooms off it that open one way only.
    detail, total = [], 0
    for offset, room in sorted(nearby.items(), key=lambda kv: sum(map(abs, kv[0]))):
        title = room.db.room_title or room.key
        entry = {
            "name": title,
            "coord": list(coords.get_coord(room) or ()),
            "opens_onto": _room_exit_directions(room),
        }
        if _offset_direction(offset) is not None:
            desc = tokens.text_of(room)
            if total + len(desc) <= max_chars:
                entry["description"] = desc
                total += len(desc)
        detail.append(entry)

    payload = {
        "target": {
            "coord": list(target),
            "arrived_from": back,
        },
        "adjacent": adjacent,
        "nearby": detail,
        "names_in_use": sorted({r.db.room_title or r.key for r in nearby.values()}),
    }
    return json.dumps(payload, indent=2)


def _parent_chain_context(source_room, max_chars=4000):
    """
    Walk up the world_parent chain from source_room, collecting room summaries.
    Returns a string with most-distant room first, source_room last.

    Only used for unmapped rooms; mapped worlds use _neighbourhood().
    """
    chain = []
    room = source_room
    total = 0
    visited = set()

    while room is not None and room.id not in visited:
        visited.add(room.id)
        title = room.db.room_title or room.key
        desc = tokens.text_of(room)
        block = f"[{title}]\n{desc}"
        if total + len(block) > max_chars:
            break
        chain.append(block)
        total += len(block)
        room = room.db.world_parent  # None at the root room

    chain.reverse()  # distant first, source_room last
    return "\n\n".join(chain)


# ---------------------------------------------------------------------------
# Room creation (runs in main thread — DB access)
# ---------------------------------------------------------------------------

def _create_room(title, description, exits, world_description, source_room, arrival_exit,
                 world_root=None, creator=None, room_type="", category="", zone="",
                 zone_purpose="", plan=None, bonuses=None, token_lists=None):
    """
    Create an Evennia Room and its exits.  Must run in the main thread.

    source_room  -- the room the player came FROM (None for the first room)
    arrival_exit -- the exit name used to enter (e.g. "north"); None for first room
    room_type    -- slug from the naming pass ("classroom"), used for singletons
    category     -- circulation | destination | threshold
    zone         -- the area this room belongs to; opened if the world has no
                    such zone yet, which is how a world grows past its plan
    zone_purpose -- what that area is for, when the room is opening a new one
    plan         -- the zone plan, for the first room of a world only
    """
    from evennia import create_object
    from typeclasses.rooms import Room
    from typeclasses.exits import AIExit

    room = create_object(Room, key=title)
    room.db.desc = description
    # What being in this place does to whoever is in it. Almost always nothing.
    # `gear` already treats a room as a source of trait bonuses in its own right
    # -- "a forge is warm whether or not anything in it is" -- and this is the
    # first thing that ever gave one any. Light is the case it exists for: a lit
    # room grants it, a dark one simply does not, and sight follows from the sum
    # without a line of light-specific code. See world/conditions.py _p_visible.
    if bonuses:
        room.db.trait_bonuses = dict(bonuses)
        room.db.bonus_when = "present"
    room.db.room_title = title
    room.db.world_description = world_description
    room.db.world_parent = source_room  # Evennia stores this as a dbref
    room.db.is_ai_room = True
    room.db.room_type = room_type
    room.db.room_category = category
    # What sort of place it is, so a rule can be about it. `room_type` is a
    # planner's slug -- "carousel_boutique_showroom", "spore_hollow" -- and its
    # head noun is what the dictionary can settle: a showroom, a hollow. All 64
    # distinct types in the exported worlds have a head noun WordNet knows.
    # Nobody is asked: the title is written by a call that had the world in
    # front of it, and a room is a cheaper thing to be slightly wrong about
    # than an object, which anchors a cache key.
    from world import kinds

    settled = kinds.canonical(room_type) or kinds.canonical(title)
    room.db.kinds = [settled] if settled else []

    # world_root is passed in for connected rooms; the first room sets itself as root.
    actual_root = world_root if world_root is not None else room
    room.db.world_root = actual_root
    if world_root is None:
        room.db.is_world_root = True
        # Before anything asks the world what its zones are: the registry is
        # built from the plan on first read, so the plan has to be there first.
        room.db.world_plan = plan or {}
        if creator is not None:
            room.db.world_creator = creator
    # Tag lets us find all rooms belonging to a world efficiently.
    room.tags.add(str(actual_root.id), category="ai_world")

    # The lists this room's description declared, then the choices it makes:
    # both need the world to exist, and the first room is the world.
    from world import token_lists as token_lists_mod, tokens

    token_lists_mod.declare(actual_root, token_lists)
    tokens.settle(room)

    # Place the room on the world's sparse map.  The first room defines the
    # origin; every other room sits one step from where the player came.
    from world import coords
    if source_room is None or arrival_exit is None:
        coords.place(actual_root, room, coords.ORIGIN)
    else:
        source_coord = coords.get_coord(source_room)
        target = coords.step(source_coord, arrival_exit) if source_coord else None
        if target is not None:
            coords.place(actual_root, room, target)

    # After placement, so the zone's box grows to include where this room
    # actually is rather than around a room with no coordinate yet. What kind
    # of room it is is recorded against the zone it lands in, which is what
    # makes "only one of these" a question about a place rather than a world.
    from world import zones
    zone_id = zones.attach(actual_root, room, zone, zone_purpose)
    zones.record_type(actual_root, zone_id, room_type, room)

    if source_room and arrival_exit:
        reverse = OPPOSITES.get(arrival_exit, "back")
        ai_names = {e["name"] for e in exits}

        # Ensure a real back-exit exists; honour it if AI included it, add it if not.
        if reverse not in ai_names:
            _make_exit(AIExit, reverse, room, source_room, pending=False)

        for exit_data in exits:
            name = exit_data["name"]
            if name == reverse:
                _make_exit(AIExit, name, room, source_room, pending=False)
            else:
                _make_ai_exit(room, actual_root, exit_data)
    else:
        # First room — all AI exits are pending
        for exit_data in exits:
            _make_ai_exit(room, actual_root, exit_data)

    return room


def _make_ai_exit(room, world_root, exit_data):
    """
    Create one exit the model asked for.

    An exit toward a cell that already holds a room is wired straight to it and
    given a way back, so the room lists a real destination instead of promising
    to generate something that is already standing there.  Everything else
    stays pending until a player walks it.
    """
    from typeclasses.exits import AIExit
    from world import coords

    name = exit_data["name"]
    coord = coords.get_coord(room)
    target = coords.step(coord, name) if coord else None
    existing = coords.room_at(world_root, target) if target else None

    if existing is not None and existing is not room:
        ex = _make_exit(AIExit, name, room, existing, pending=False)
        ensure_return_exit(existing, room, name)
        return ex

    return _make_exit(AIExit, name, room, room, pending=True,
                      hint=exit_data["destination_hint"])


def ensure_return_exit(target_room, source_room, arrival_exit):
    """
    Give `target_room` an exit leading back to `source_room`, if it has none.

    Used when a player walks into a cell that is already occupied: the forward
    exit is linked to the room found there, and the room found there needs a
    way back or the connection is one-way.
    """
    from typeclasses.exits import AIExit

    reverse = OPPOSITES.get(arrival_exit, "back")
    for obj in target_room.contents:
        if getattr(obj, "destination", None) is None:
            continue
        # Already connected back, or the name is taken by another exit.
        if obj.destination == source_room or obj.key == reverse:
            return obj
    return _make_exit(AIExit, reverse, target_room, source_room, pending=False)


def _make_exit(typeclass, key, location, destination, pending, hint=""):
    from evennia import create_object
    ex = create_object(
        typeclass, key=key, location=location, destination=destination,
        aliases=direction_aliases(key, location),
    )
    ex.db.is_ai_exit = True
    if pending:
        ex.db.pending_generation = True
        ex.db.destination_hint = hint
    return ex


# ---------------------------------------------------------------------------
# Keeping somewhere left to go
#
# A world grows the way a branching process does. Every room built spends one
# unexplored way -- the one the player walked -- and leaves behind however
# many the namer chose to write. Above one on average the world expands; below
# one it dies out, and dies out quickly.
#
# Everything about the design pushed it below one. A destination is told to
# have "usually just the way in", which is none. Doors into destinations are
# dropped. A door is to be added "ONLY if a door genuinely belongs". And an
# exit toward a cell that already holds a room is wired to that room rather
# than left unexplored -- which is what lets a world close back on itself, and
# also means the denser a world gets the fewer new ways each room leaves. That
# last one accelerates: the bigger the world, the faster its frontier shrinks.
#
# So a world ending was not bad luck. It was where the arithmetic was always
# going. These two functions are the floor under it: one counts what is left,
# and the other guarantees the count is never zero.
# ---------------------------------------------------------------------------

#: How few unexplored ways a world may have before the namer is pressed to
#: open more. Above this, growth is left to happen naturally.
FRONTIER_FLOOR = 3


def pending_exits(world_root):
    """Every exit in this world that promises a room nobody has built yet."""
    if world_root is None:
        return []
    from evennia import search_tag

    found = []
    for room in search_tag(str(world_root.id), category="ai_world"):
        for obj in room.contents:
            if getattr(obj, "destination", None) is None:
                continue
            if obj.db.pending_generation:
                found.append(obj)
    return found


def frontier(world_root):
    """How many ways out of this world's built part remain unexplored."""
    return len(pending_exits(world_root))


def openable_directions(world_root, room):
    """
    Ways out of `room` that could be opened: buildable, free, and unused.

    Free ground is checked on the map rather than in the room, because a
    direction with no exit in it may still be a wall shared with a room that
    is already standing there.
    """
    from world import coords

    coord = coords.get_coord(room)
    if coord is None:
        return []
    taken = {
        canonical_direction(obj.key)
        for obj in room.contents
        if getattr(obj, "destination", None) is not None
    }
    return [
        direction for direction in BUILDABLE_DIRECTIONS
        if direction not in taken
        and coords.room_at(world_root, coords.step(coord, direction)) is None
    ]


def _room_for_new_way(world_root, near=None):
    """
    The best room to open a new way out of, and the directions it could take.

    Preferences, in order: somewhere that carries traffic, because a corridor
    with another turning is ordinary and a fourth door in a broom cupboard is
    not; somewhere in an area still being built, since an unfinished zone is
    already a promise of more rooms; and then whatever is nearest to `near`,
    so the world opens up where somebody actually is rather than behind them.
    """
    from evennia import search_tag

    from world import coords, zones

    origin = coords.get_coord(near) if near is not None else None

    best = None
    for room in search_tag(str(world_root.id), category="ai_world"):
        directions = openable_directions(world_root, room)
        if not directions:
            continue
        category = room.db.room_category or ""
        coord = coords.get_coord(room)
        distance = (
            sum(abs(a - b) for a, b in zip(coord, origin))
            if origin is not None and coord is not None else 0
        )
        rank = (
            0 if category in ("circulation", "threshold") else 1,
            0 if not zones.full(world_root, zones.slugify(room.db.zone)) else 1,
            distance,
        )
        if best is None or rank < best[0]:
            best = (rank, room, directions)

    if best is None:
        return None, []
    return best[1], best[2]


def _room_to_grow_into(world_root, room, directions):
    """
    Which way to open, preferring somewhere with space to carry on.

    A direction whose second cell is also free can become a passage; one that
    opens into a single pocket between rooms already built is a cupboard, and
    a cupboard leaves the world exactly as stuck as it was.
    """
    from world import coords

    coord = coords.get_coord(room)
    roomy = [
        direction for direction in directions
        if coords.room_at(world_root, coords.step(
            coords.step(coord, direction), direction)) is None
    ]
    return (roomy or directions)[0]


def ensure_frontier(world_root, near=None):
    """
    Guarantee this world still has somewhere left to go. Returns the exit, or None.

    Called after each room is built, and by `worldopen` for a world that has
    already closed. Nothing happens while any unexplored way remains: a world
    that is growing on its own is left alone, and this only ever runs at the
    moment one would otherwise have ended.

    It cannot fail while the world has a single room on the map. A world
    occupies finitely many cells of an unbounded grid, so some room on its
    edge always has open ground beside it.
    """
    if world_root is None or frontier(world_root) > 0:
        return None

    room, directions = _room_for_new_way(world_root, near)
    if room is None:
        return None

    from typeclasses.exits import AIExit

    direction = _room_to_grow_into(world_root, room, directions)
    # No hint: nothing has ever said what lies this way, and inventing a
    # promise here would be this function guessing at the world rather than
    # leaving that to the namer, which can see the whole neighbourhood.
    ex = _make_exit(AIExit, direction, room, room, pending=True)
    logger.log_info(
        f"worldgen: {world_root.key!r} had no unexplored ways left; opened "
        f"{direction} from {room.db.room_title or room.key!r}"
    )
    # Somebody standing here would otherwise find a door that was not there a
    # moment ago and no reason given for it.
    room.msg_contents(
        f"You notice a way {direction} you had not seen before."
    )
    return ex


# ---------------------------------------------------------------------------
# Direction helpers
# ---------------------------------------------------------------------------

def canonical_direction(word):
    """
    Return the canonical direction name for a direction word or abbreviation
    ("n" and "north" both give "north"), or None if it is not a direction.
    """
    return CANONICAL_DIRECTIONS.get(str(word).lower().strip())


def direction_aliases(key, location):
    """
    Direction aliases to give an exit named `key` leading out of `location`.

    A plain "north" gains "n"; a labelled "north passage" gains both "north"
    and "n", so that every exit answers to its direction and to the
    abbreviation.  Names already used by another exit in the room are skipped,
    so adding aliases can never create an ambiguous match.
    """
    direction = canonical_direction(key)
    if direction is None:
        # A labelled exit gets aliases only when it names exactly one direction.
        named = {canonical_direction(word) for word in key.split()} - {None}
        direction = named.pop() if len(named) == 1 else None
    if direction is None:
        return []

    taken = {
        name.lower()
        for obj in location.contents
        if getattr(obj, "destination", None) is not None
        for name in [obj.key, *obj.aliases.all()]
    }
    candidates = [direction, *DIRECTION_ALIASES.get(direction, [])]
    return [name for name in candidates if name != key and name not in taken]


# ---------------------------------------------------------------------------
# Pipeline stages
#
# A room is built in three passes rather than one, so each can be checked
# before the next spends tokens on it: a short naming call that is cheap to
# reject and retry, a description call that sees the names around it, and a
# contents pass that runs after the player has already arrived.
# ---------------------------------------------------------------------------

def _normalise(name):
    """Lowercase word set for comparing room names."""
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if len(w) > 2}


def _too_similar(name, existing_names, threshold=0.6):
    """True when `name` overlaps an existing name enough to read as a repeat."""
    words = _normalise(name)
    if not words:
        return False
    for other in existing_names:
        other_words = _normalise(other)
        if not other_words:
            continue
        overlap = len(words & other_words) / len(words | other_words)
        if overlap >= threshold:
            return True
    return False


def world_plan(world_root):
    """The world's zone plan, or an empty plan if it has none."""
    return (world_root.db.world_plan or {}) if world_root else {}


def _singletons_taken(world_root, zone_id):
    """
    What a room in `zone_id` may not be, as {slug: (room name, the place)}.

    Scoped rather than global. A world used to allow one gymnasium anywhere in
    it, which is right for a school and absurd for a country -- so the question
    is asked of every place this room is inside, and each answers only about
    itself.
    """
    from world import zones

    return zones.singletons_taken(world_root, zone_id)


def _check_name(data, existing_names, world_root, source_room, target=None,
                arrival_exit=None):
    """
    Validate a naming response. Returns a complaint string, or None if good.

    The complaint is fed back to the model on retry, so it must say what to do
    differently rather than merely what was wrong.
    """
    source_category = source_room.db.room_category if source_room else ""

    name = str(data.get("name", "")).strip()
    if not name:
        return "You returned no name. Give a room name of 2-6 words."
    if _too_similar(name, existing_names):
        return (f"'{name}' repeats a room that already exists nearby. "
                f"Name a different kind of room, not a variation on those.")

    category = str(data.get("category", "")).strip().lower()
    if category not in CATEGORIES:
        return f"category must be one of {', '.join(CATEGORIES)}."
    if category == "destination" and source_category == "destination":
        return ("The room you are entering from is already a destination, and two "
                "destinations must not open onto each other. Make this circulation "
                "or a threshold.")

    # Zone first, because what may exist only once depends on where you are:
    # a second gymnasium is wrong in a school and unremarkable in a county.
    complaint = _check_zone(data, world_root, source_room, category, target)
    if complaint:
        return complaint

    complaint = _check_singleton(data, world_root, source_room)
    if complaint:
        return complaint

    return _check_way_on(data, world_root, source_room, arrival_exit, target)


def _check_way_on(data, world_root, source_room, arrival_exit, target):
    """
    Whether this room may be a dead end. A complaint, or None.

    Only asked when the world is nearly out of unexplored ways. A world that
    still has plenty is left to build whatever it likes, dead ends included --
    a corridor of closed doors is what makes the open one worth walking.

    The check is on the exits that would actually survive `_allowed_exits`,
    not on the ones asked for, because an exit into a wall or into a
    destination is dropped afterwards and would leave the room a dead end
    anyway. And it is skipped where there is nowhere to open onto: a room
    walled in on every side cannot be talked into having another door, and
    demanding one would only spend three retries finding that out.
    """
    if arrival_exit is None or target is None:
        return None
    if frontier(world_root) > FRONTIER_FLOOR:
        return None

    from world import coords

    free = [
        direction for direction in BUILDABLE_DIRECTIONS
        if direction != OPPOSITES.get(arrival_exit)
        and coords.room_at(world_root, coords.step(target, direction)) is None
    ]
    if not free:
        return None

    reverse = OPPOSITES.get(arrival_exit, "back")
    if _allowed_exits(data.get("exits"), source_room, arrival_exit, reverse):
        return None

    return (
        f"This world is nearly out of places left to explore, and a room with "
        f"no way on but the way back would close it off for good. Give this "
        f"room at least one exit onto open ground — "
        f"{', '.join(free)} {'is' if len(free) == 1 else 'are'} free — and say "
        f"what lies that way."
    )


def _check_singleton(data, world_root, source_room):
    """
    Whether this kind of room may exist where the room says it is going.

    Asked of the zone the room claims, and through it of every place that zone
    is inside. A zone the world has not opened yet has no rooms and so forbids
    nothing of its own -- but the places around it still do, which is what
    stops a brand new wing being founded to hold a second principal's office.
    """
    from world import zones

    slug = str(data.get("type", "")).strip().lower()
    if not slug:
        return None

    claimed = zones.slugify(data.get("zone", ""))
    source_id = zones.slugify(source_room.db.zone) if source_room else ""
    scope = claimed if zones.get(world_root, claimed) else (
        zones.parent_of(world_root, source_id) if source_id else zones.ROOT
    )

    taken = _singletons_taken(world_root, scope)
    if slug not in taken:
        return None
    holder, place = taken[slug]
    return (f"{place} already has its '{slug}' ({holder}), and there is only "
            f"ever one in a place like that. Choose a different kind of room.")


def _check_zone(data, world_root, source_room, category, target):
    """
    Whether this room may be in the zone it claims. A complaint, or None.

    Three rules, and between them they are what stops a world circling its
    original zones forever:

    A finished zone takes no more rooms. That is the one that does the work --
    it is what leaves the namer with nowhere to put this room and so makes it
    say what is out here instead.

    A zone is somewhere, so a room can only be in one it is actually near. A
    label is true wherever you write it, which is how "Gym Block" ended up on
    rooms four corridors apart.

    Zones change at seams. Without this a world would fray at every edge cell
    at once, and you would walk from a classroom straight into a marketplace
    with no door between them.
    """
    from world import zones

    claimed = str(data.get("zone", "")).strip()
    if not claimed:
        return ("You gave no zone. Every room is in one: name the area this "
                "room belongs to.")

    zone_id = zones.slugify(claimed)
    source_id = zones.slugify(source_room.db.zone) if source_room else ""
    known = zones.all_zones(world_root)

    if source_id and zone_id != source_id and not _at_a_seam(source_room, category):
        return (f"This room is in a different area from the one it is entered "
                f"from, and areas only change at a seam. Either put it in "
                f"'{zones.name_of(world_root, source_id)}', or make it a "
                f"threshold — the doorway or gate that leads out.")

    if zone_id in known:
        if zones.is_world(world_root, zone_id):
            return ("That is the world itself, not a place in it. Name the area "
                    "this room belongs to.")
        if zones.full(world_root, zone_id):
            record = known[zone_id]
            inside = zones.children_of(world_root, zone_id)
            within = ", ".join(
                zones.name_of(world_root, zid) for zid in inside
                if not zones.full(world_root, zid)
            )
            return (f"'{record['name']}' is built out — it has all "
                    f"{record['budget']} rooms of its own it was meant to have. "
                    + (f"Put this room in one of the areas inside it "
                       f"({within}). " if within else
                       f"Put this room in one of the areas still being built, "
                       f"or, if none of them reaches out here, name a new area "
                       f"and say in zone_purpose what it is for."))
        if target is not None and not zones.contains(world_root, zone_id, target):
            return (f"'{known[zone_id]['name']}' is somewhere else in this "
                    f"world and this room is nowhere near it. Use an area that "
                    f"reaches this spot, or name a new one.")
        return None

    # A zone nobody has heard of: the model is opening one. Allowed only where
    # the world has actually run out -- otherwise every room with an awkward
    # exit would found a district rather than joining the one it is standing
    # in, and the world would fray into a hundred one-room areas.
    open_here = [
        zid for zid in zones.around(world_root, target)
        if not zones.full(world_root, zid)
    ]
    if open_here:
        names = ", ".join(zones.name_of(world_root, zid) for zid in open_here)
        return (f"'{claimed}' is a new area, but this room is inside one that "
                f"is still being built ({names}). Put it there. Only open a new "
                f"area where none of the existing ones reaches.")

    waiting = zones.unbuilt_near(world_root, source_id)
    if waiting:
        names = ", ".join(zones.name_of(world_root, zid) for zid in waiting)
        return (f"'{claimed}' is a new area, but there are places here nobody "
                f"has been to yet ({names}). This is where one of them starts. "
                f"Build out what is already planned before adding to it.")
    return None


def _at_a_seam(source_room, category):
    """
    Whether a zone may change between `source_room` and a room of `category`.

    A seam is a threshold on one side or the other. Rooms with no category at
    all -- anything built before categories existed -- are let through rather
    than deadlocked on a rule they cannot satisfy.
    """
    source_category = (source_room.db.room_category if source_room else "") or ""
    if not source_category:
        return True
    return source_category == "threshold" or category == "threshold"


def _guide(source, facet):
    """
    This world's instructions for one generator, as a block for a prompt.

    `source` is a room, a world root, or the wizard spec a world is about to
    be built from -- so the first room reads the same guidance as every room
    after it, before there is a world to read it off.
    """
    from world import lore

    return lore.guidance_block(source, facet)


def _generate_plan(sponsor, world_description, guidance, on_done):
    """
    Async. Ask for the world's zones and singleton room types.

    Failure is not fatal: a world with no plan simply generates without zone
    guidance, so on_done is always called.
    """
    model = sponsor.model_for("rooms")
    messages = [
        {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
        {"role": "user",
         "content": f"World theme: {world_description}\n\n{guidance}Plan its zones."},
    ]

    def _done(raw):
        try:
            raw = dict(raw or {})
            from world import zones as zonelib

            zones = [
                {
                    "name": str(z.get("name", "")).strip(),
                    "purpose": str(z.get("purpose", "")).strip(),
                    "room_types": [str(t).strip().lower() for t in z.get("room_types", [])],
                    "room_budget": zonelib.clamp_budget(z.get("room_budget")),
                }
                for z in raw.get("zones", [])
                if str(z.get("name", "")).strip()
            ]
            singles = [str(t).strip().lower() for t in raw.get("singleton_types", [])]
            on_done({"zones": zones, "singleton_types": singles})
        except Exception:
            on_done({})

    from world import toolbox as tb

    # Rounds out, the last plan is used as it stands; a failure is no plan.
    llm.converse(sponsor, model, messages,
                 tb.Toolbox([plan_world_tool()],
                            tb.ToolContext(sponsor=sponsor, job="rooms")),
                 on_done=_done, on_error=lambda _why: on_done({}),
                 on_exhausted=_done, rounds=PLAN_ROUNDS,
                 timeout=llm.SLOW_TIMEOUT)


#: (world id, zone id) for the areas currently being described.
#:
#: A zone is only marked planned once its answer arrives, so two rooms built in
#: a new place in quick succession would otherwise each pay for the same
#: question. Held in memory rather than on the world: a plan lost to a reload
#: should be asked for again, not abandoned half-done.
_PLANNING = set()


def plan_zone(sponsor, world_root, zone_id):
    """
    Async, fire-and-forget. Find out what one area of a world actually is.

    Runs the first time a room is built in a place -- whether the world plan
    named it in passing or a doorway opened it a moment ago -- and never again.
    Until it answers, the zone runs on a guessed budget and forbids nothing,
    which costs at most the first room or two of somewhere new; that is much
    cheaper than making a player wait at a door while a district is designed
    around them.

    The answer may say the place is made of smaller places, and that is the
    only way this world ever gets deeper. A school entered from a high street
    becomes a school with wings in it because somebody walked into it, not
    because anything decided in advance how many levels a world should have.
    """
    from world import lore, zones

    record = zones.get(world_root, zone_id)
    if record is None or not zones.needs_plan(world_root, zone_id):
        return
    ticket = (getattr(world_root, "id", None), zones.slugify(zone_id))
    if ticket in _PLANNING:
        return
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError:
        return
    _PLANNING.add(ticket)

    within = zones.path_of(world_root, zones.parent_of(world_root, zone_id))
    known = ", ".join(record["room_types"])
    messages = [
        {"role": "system", "content": _ZONE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"World theme: {lore.description(world_root)}\n\n"
                f"{_guide(world_root, 'rooms')}"
                f"Area: {record['name']}\n"
                + (f"Inside: {within}\n" if within else "")
                + (f"Said so far to be: {record['purpose']}\n"
                   if record["purpose"] else "")
                + (f"Rooms expected in it: {known}\n" if known else "")
                + f"\nSay what this area is, how many rooms it is worth, what "
                  f"may exist only once in it, and whether it is made of "
                  f"smaller areas."
            ),
        },
    ]

    def _done(data):
        _PLANNING.discard(ticket)
        if not isinstance(data, dict):
            return
        try:
            opened = zones.apply_plan(world_root, zone_id, data)
        except Exception as exc:
            logger.log_err(f"zones: could not plan {zone_id!r}: {exc}")
            return
        if opened:
            logger.log_info(
                f"zones: {record['name']!r} turned out to be made of "
                f"{', '.join(zones.name_of(world_root, z) for z in opened)}"
            )

    def _failed(_reason):
        _PLANNING.discard(ticket)

    from world import lookups
    from world import toolbox as tb

    box = tb.Toolbox([area_tool(world_root, zone_id)]
                     + lookups.named(*AREA_LOOKUPS),
                     tb.ToolContext(world_root=world_root, sponsor=sponsor,
                                    job="rooms"))
    llm.converse(sponsor, sponsor.model_for("rooms"), messages, box,
                 on_done=_done, on_error=_failed, on_exhausted=_done,
                 rounds=PLAN_ROUNDS, timeout=llm.SLOW_TIMEOUT)


def _generate_name(sponsor, world_description, context, source_room,
                   exit_name, hint, on_success, on_error):
    """
    Async. Name the room, sending back whatever validation rejects.

    Short output, so a rejected answer costs one small call rather than a whole
    room's worth of prose.
    """
    from world import coords, zones

    model = sponsor.model_for("naming", "rooms")
    world_root = source_room.db.world_root
    existing = _nearby_names(source_room, exit_name)
    source_category = source_room.db.room_category

    source_coord = coords.get_coord(source_room)
    target = coords.step(source_coord, exit_name) if source_coord else None

    source_zone = zones.slugify(source_room.db.zone)
    zone_lines = zones.menu(world_root, target, source_zone)
    done = zones.full_names(world_root, target)
    taken = _singletons_taken(world_root, source_zone)

    base = (
        f"World theme: {world_description}\n\n"
        + _guide(source_room, "rooms")
        + (f"Areas still being built:\n{zone_lines}\n\n" if zone_lines else
           "Every area of this world is built out. This room lies beyond all of "
           "them: name a new area for it and say what it is for.\n\n")
        + (f"Built out, and taking no more rooms: {', '.join(done)}\n\n"
           if done else "")
        + (f"The room being left is in "
           f"{zones.path_of(world_root, source_zone) or zones.name_of(world_root, source_zone)}"
           + (", which is built out.\n\n" if zones.full(world_root, source_zone)
              else ".\n\n")
           if source_zone else "")
        + (f"Already here, do not create a second one: "
           f"{', '.join(f'{k} ({v[0]} in {v[1]})' for k, v in taken.items())}\n\n"
           if taken else "")
        + f"The player leaves '{source_room.db.room_title or source_room.key}' "
        f"(category: {source_category or 'unknown'}) through its '{exit_name}' exit.\n\n"
        + (f"That exit was written as leading to: \"{hint}\"\n\n" if hint else "")
        + _hints_block(
            naming_hints(world_root),
            "Places and things somebody in this world is looking for, which "
            "nothing here provides yet. A way out may lead somewhere like "
            "one of these, if it fits:")
        + f"Surrounding area:\n{context}\n\n"
        f"'adjacent' gives each direction from the new room. Being next to a room "
        f"does NOT mean a door joins them: classrooms along a corridor share walls "
        f"but open only onto the corridor.\n"
        f"  may_open_new_room: true  — empty ground; an exit here builds a new room\n"
        f"  may_connect: true        — a room is already there; add an exit ONLY if "
        f"a door genuinely belongs, otherwise leave it a shared wall\n"
        f"  may_connect: false       — leave it a wall\n"
        f"  already_connected        — the way back; never list a "
        f"'{OPPOSITES.get(exit_name, 'back')}' exit\n"
        f"Directions not listed are walls and cannot be used. 'opens_onto' shows "
        f"which directions each nearby room actually has doors in — follow the "
        f"layout's habits.\n\n"
        f"Name the room they arrive in and give its exits. Do not reuse or "
        f"paraphrase any of these names: "
        f"{', '.join(sorted(existing)) or '(none nearby)'}"
    )

    messages = [
        {"role": "system", "content": _NAME_SYSTEM_PROMPT},
        {"role": "user", "content": base},
    ]

    from world import lookups
    from world import toolbox as tb

    # The conversation this used to build by hand -- the answer, then the
    # complaint as a user turn, three times -- is the loop's own now, with the
    # complaint as the tool's result. Rounds out, the last name is taken as it
    # stands, as the third retry's always was.
    box = tb.Toolbox(
        [name_tool(existing, world_root, source_room, target, exit_name)]
        + lookups.named(*NAME_LOOKUPS),
        tb.ToolContext(world_root=world_root, room=source_room,
                       sponsor=sponsor, job="naming"))
    llm.converse(sponsor, model, messages, box, on_done=on_success,
                 on_error=on_error,
                 on_exhausted=lambda last: on_success(last) if last
                 else on_error("no room name came back"),
                 rounds=NAME_ROUNDS, timeout=llm.SLOW_TIMEOUT)


def _allowed_exits(raw_exits, source_room, arrival_exit, reverse):
    """
    Keep only the exits the new room is actually permitted.

    The model is told the rules, but a prompt is not a guarantee: this drops
    the way back, diagonals, duplicates, and doors into a destination room --
    so two classrooms cannot end up joined even if the model asks for it.
    """
    from world import coords

    world_root = source_room.db.world_root
    source_coord = coords.get_coord(source_room)
    target = coords.step(source_coord, arrival_exit) if source_coord else None

    kept, seen = [], set()
    for entry in (raw_exits or []):
        name = canonical_direction(str(entry.get("name", "")).strip())
        if not name or name == reverse or name in seen:
            continue
        if name not in BUILDABLE_DIRECTIONS:
            continue
        if target is not None:
            neighbour = coords.room_at(world_root, coords.step(target, name))
            if neighbour is not None and neighbour.db.room_category == "destination":
                continue
        seen.add(name)
        kept.append({
            "name": name,
            "destination_hint": str(entry.get("destination_hint", "")).strip(),
        })
    return kept


def _nearby_names(source_room, exit_name):
    """Room names close enough to the new room that repeating one would show."""
    from world import coords

    world_root = source_room.db.world_root
    source_coord = coords.get_coord(source_room)
    target = coords.step(source_coord, exit_name) if source_coord else None
    names = {source_room.db.room_title or source_room.key}
    if world_root and target:
        for room in coords.neighbours(world_root, target, radius=2).values():
            names.add(room.db.room_title or room.key)
    return names


def _generate_description(sponsor, world_description, guidance, context,
                          name, room_type, category, on_success, on_error,
                          world_root=None):
    """
    Async. Write the room's description, given the area around it.

    `on_success(description, bonuses, token_lists)`: the lists are whatever
    the description declared, for `_create_room` to register once there is a
    world to register them in.
    """
    from world import token_lists

    model = sponsor.model_for("rooms")
    messages = [
        {"role": "system", "content": _DESC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"World theme: {world_description}\n\n"
                f"{guidance}"
                f"{token_lists.TOOL_PROMPT}\n"
                f"Room: {name}\n"
                f"Kind: {room_type or 'unspecified'} ({category or 'unspecified'})\n\n"
                f"Surrounding area, for continuity only — do not name these rooms:\n"
                f"{context}\n\n"
                f"Describe this room's permanent physical fabric."
            ),
        },
    ]

    def _done(data):
        data = data if isinstance(data, dict) else {}
        desc = str(data.get("description") or "").strip()
        if not desc:
            on_error("no description came back")
            return
        bonuses = data.get("trait_bonuses")
        lists = data.get("new_token_lists")
        on_success(desc, bonuses if isinstance(bonuses, dict) else {},
                   lists if isinstance(lists, list) else [])

    from world import lookups
    from world import toolbox as tb

    # Rounds out, the last description is used as it stands: a room with a
    # slot nobody fills reads a little oddly, and a room that was never built
    # strands whoever walked towards it.
    box = tb.Toolbox([description_tool()]
                     + lookups.named(*DESCRIPTION_LOOKUPS),
                     tb.ToolContext(world_root=world_root, sponsor=sponsor,
                                    job="rooms"))
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=on_error, on_exhausted=_done,
                 rounds=DESCRIPTION_ROUNDS, timeout=llm.SLOW_TIMEOUT)


def _join_names(names):
    """"a, b and c" -- for reading aloud, not for parsing."""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def populate_room(sponsor, room):
    """
    Async, fire-and-forget. Give a finished room its loose contents.

    Runs after the player has arrived, so it costs them no waiting; items and
    any NPC appear in the room as they are created.  Errors are swallowed --
    an unfurnished room is a small loss, a stranded player is not.
    """
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError:
        return
    model = sponsor.model_for("contents", "items")

    from world import gear, kinds, lore, verbs

    messages = [
        {"role": "system",
         "content": _CONTENTS_SYSTEM_PROMPT.replace(
             "{naming_rule}", verbs.naming_rule()).replace(
             "{anchor_rule}", kinds.anchor_rule()).replace(
             "{affordance_rule}", _affordance_rule())},
        {
            "role": "user",
            "content": (
                f"World theme: {lore.description(room)}\n\n"
                f"{_guide(room, 'items')}"
                f"Room: {room.db.room_title or room.key}\n"
                f"Kind: {room.db.room_type or 'unspecified'} "
                f"({room.db.room_category or 'unspecified'})\n\n"
                f"Description: {tokens.text_of(room)}\n\n"
                f"{gear.prompt_block(room.db.world_root)}"
                + _hints_block(
                    contents_hints(room.db.world_root, room),
                    "Wanted by somebody in this world, and to be found "
                    "nowhere yet. Include one only if it genuinely belongs in "
                    "this room, and name it as the line says:")
                + "What loose items are here?"
            ),
        },
    ]

    def _done(data):
        from world import clothing

        if not isinstance(data, dict):
            return

        created = []
        for item in [entry for entry in (data.get("items") or [])
                     if isinstance(entry, dict)][:3]:
            # Through the clothing layer, so a coat left over the back of a
            # chair is a coat somebody can pick up and put on.
            obj = clothing.create(item, location=room)
            if obj is None:
                continue
            # Evennia's own singular form, so it reads "a dried-out marker"
            # rather than "dried-out marker".
            created.append(obj.get_numbered_name(1, None, return_string=True))

        # The player is already standing here, so anything that appears has to
        # announce itself -- otherwise they only find it by leaving and coming
        # back. An empty room simply gets no message.
        if created:
            room.msg_contents(f"You notice {_join_names(created)} here.")

        if data.get("wants_npc"):
            from world.npc_gen import generate_npc

            def arrived(npc):
                room.msg_contents(f"You notice {npc.key} here.")

            generate_npc(sponsor=sponsor, room=room,
                         on_success=arrived,
                         on_error=lambda _err: None)

    from world import lookups
    from world import toolbox as tb

    # Rounds out, the last contents are placed as they stand; a failure is an
    # unfurnished room, which is the small loss it always was.
    box = tb.Toolbox([contents_tool(tokens.text_of(room))]
                     + lookups.named(*CONTENTS_LOOKUPS),
                     tb.ToolContext(world_root=room.db.world_root, room=room,
                                    sponsor=sponsor, job="contents"))
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=lambda _why: None, on_exhausted=_done,
                 rounds=CONTENTS_ROUNDS, timeout=llm.SLOW_TIMEOUT)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def generate_first_room(sponsor, spec, on_success, on_error,
                        creator_character=None):
    """
    Async. Generate the starting room for a new world.

    `spec` is what the worldgen wizard collected: title, description, the
    player's name and appearance in this world, and the per-generator
    guidance. A bare string is accepted as the description alone, so older
    callers keep working.

    Calls on_success(room) or on_error(msg) in the main thread.
    """
    if isinstance(spec, str):
        spec = {"description": spec}
    world_description = (spec.get("description") or "").strip()
    # Read off the spec: the world does not exist yet to be asked.
    rooms_guidance = _guide(spec, "rooms")

    model = sponsor.model_for("rooms")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    def with_plan(plan):
        zone_lines = "\n".join(
            f"- {z['name']}: {z['purpose']} (typical rooms: {', '.join(z['room_types'])})"
            for z in plan.get("zones", [])
        )
        messages = [
            {"role": "system", "content": _NAME_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"World theme: {world_description}\n\n"
                    + rooms_guidance
                    + (f"Zones in this world:\n{zone_lines}\n\n" if zone_lines else "")
                    + f"This is the world's first room — the way in. It should be "
                      f"circulation or a threshold rather than a destination, so the "
                      f"world can open out from it.\n\n"
                      f"Name it and give its exits. Use only these directions: "
                      f"{', '.join(BUILDABLE_DIRECTIONS)}."
                ),
            },
        ]

        def with_name(named):
            named = named if isinstance(named, dict) else {}
            name = str(named.get("name", "")).strip() or "Unnamed Room"
            room_type = str(named.get("type", "")).strip().lower()
            category = str(named.get("category", "")).strip().lower()
            if category not in CATEGORIES:
                category = "threshold"
            zone = str(named.get("zone", "")).strip()
            exits = [
                {"name": d, "destination_hint": str(e.get("destination_hint", "")).strip()}
                for e in (named.get("exits") or []) if isinstance(e, dict)
                for d in [canonical_direction(str(e.get("name", "")).strip())]
                if d in BUILDABLE_DIRECTIONS
            ]

            def finish(description, bonuses=None, lists=None):
                try:
                    room = _create_room(
                        name, description, exits, world_description, None, None,
                        creator=sponsor.account, room_type=room_type, category=category,
                        zone=zone, plan=plan, bonuses=bonuses, token_lists=lists,
                    )

                    # Title, long description, and the player's name and
                    # appearance here -- all set before anyone arrives, so the
                    # first look already shows the world as it was designed.
                    from world import lore

                    lore.store(room, spec)
                    lore.apply_to_player(room, creator_character, spec)
                    # Record this world on the sponsor so `worlds` can list it,
                    # and on the world so anything standing in it can find out
                    # whose key pays for what happens here. Both directions,
                    # because the two questions are asked from opposite ends:
                    # `worlds` starts from a player, and a sponsor starts from
                    # a room. See world.sponsor.
                    from world import sponsor as sponsor_mod

                    created = sponsor.account.db.created_worlds or []
                    created.append(room.id)
                    sponsor.account.db.created_worlds = created
                    sponsor_mod.claim(room, sponsor.account)
                    on_success(room)
                    populate_room(sponsor, room)
                    plan_zone(sponsor, room, room.db.zone)
                    # A first room the namer gave no exits would otherwise be
                    # a world of one room with nowhere to go.
                    ensure_frontier(room, near=room)
                except Exception as exc:
                    on_error(str(exc))

            _generate_description(
                sponsor, world_description, rooms_guidance,
                "(this is the first room)", name, room_type, category,
                on_success=finish, on_error=on_error,
            )

        from world import toolbox as tb

        llm.converse(sponsor, model, messages,
                     tb.Toolbox([first_name_tool(plan)],
                                tb.ToolContext(sponsor=sponsor, job="rooms")),
                     on_done=with_name, on_error=on_error,
                     on_exhausted=lambda last: with_name(last) if last
                     else on_error("no room name came back"),
                     rounds=NAME_ROUNDS, timeout=llm.SLOW_TIMEOUT)

    _generate_plan(sponsor, world_description, rooms_guidance, with_plan)


def generate_connected_room(sponsor, world_description, source_room, exit_name,
                            on_success, on_error, destination_hint=""):
    """
    Async. Generate the room reached by going through exit_name from source_room.
    Context is built synchronously before the network call.
    Calls on_success(room) or on_error(msg) in the main thread.

    destination_hint is what the source room said lay beyond this exit when it
    was written. Honouring it is what keeps a door's promise and the room
    behind it consistent.
    """
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    # Build context here (main thread — DB access is safe)
    context = _neighbourhood(source_room, exit_name)
    reverse = OPPOSITES.get(exit_name, "back")
    rooms_guidance = _guide(source_room, "rooms")

    def with_name(named):
        name = str(named.get("name", "")).strip() or "Unnamed Room"
        room_type = str(named.get("type", "")).strip().lower()
        category = str(named.get("category", "")).strip().lower()
        if category not in CATEGORIES:
            category = "circulation"
        zone = str(named.get("zone", "")).strip()
        zone_purpose = str(named.get("zone_purpose", "")).strip()

        exits = _allowed_exits(named.get("exits"), source_room, exit_name, reverse)

        _generate_description(
            sponsor, world_description, rooms_guidance, context, name,
            room_type, category,
            on_success=lambda description, bonuses=None, lists=None: finish(
                name, description, exits, room_type, category, zone,
                zone_purpose, bonuses, lists),
            on_error=on_error,
            world_root=source_room.db.world_root,
        )

    def finish(name, description, exits, room_type, category, zone,
               zone_purpose, bonuses=None, lists=None):
        try:
            room = _create_room(
                name, description, exits, world_description, source_room, exit_name,
                world_root=source_room.db.world_root,
                room_type=room_type, category=category, zone=zone,
                zone_purpose=zone_purpose, bonuses=bonuses, token_lists=lists,
            )
            # The player moves now; contents arrive behind them, and so does
            # any thinking about the place they have just walked into.
            on_success(room)
            populate_room(sponsor, room)
            plan_zone(sponsor, room.db.world_root, room.db.zone)
            # Last, and only if this room closed the world off: a world that
            # is still growing on its own is left alone.
            ensure_frontier(room.db.world_root, near=room)
        except Exception as exc:
            on_error(str(exc))

    _generate_name(
        sponsor, world_description, context, source_room, exit_name,
        destination_hint,
        on_success=with_name,
        on_error=on_error,
    )


# ---------------------------------------------------------------------------
# The finish tools (docs/generator-tool-loops.md §4.2)
# ---------------------------------------------------------------------------

#: Rounds each may take (§10.3). Planning is background work nobody waits on;
#: a room's name and description are waited on by whoever walked that way.
PLAN_ROUNDS = 10
NAME_ROUNDS = 8
DESCRIPTION_ROUNDS = 8

#: The lookups offered to each.
AREA_LOOKUPS = ("list_zones", "zone_info")
NAME_LOOKUPS = ("list_zones", "zone_info", "find_rooms")
DESCRIPTION_LOOKUPS = ("list_word_lists", "show_word_list", "list_traits")


def _listed(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _zone_item():
    """One area, as the world plan and an area's plan both give it."""
    from world import zones

    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A short name"},
            "purpose": {"type": "string",
                        "description": "One sentence on what happens there"},
            "room_types": {"type": "array", "items": {"type": "string"},
                           "description": "The kinds of room it is made of, "
                                          "as lowercase underscore slugs"},
            "room_budget": {"type": "integer", "minimum": zones.MIN_BUDGET,
                            "maximum": zones.MAX_BUDGET,
                            "description": "How many rooms it is worth "
                                           "walking through"},
        },
        "required": ["name", "purpose", "room_types", "room_budget"],
    }


def _singletons_unknown(singletons, zones_given, own_types=()):
    """Singleton types no room type anywhere in the answer mentions."""
    types = {str(t).strip().lower() for t in _listed(own_types)}
    for zone in zones_given:
        types |= {str(t).strip().lower() for t in _listed(zone.get("room_types"))}
    return sorted({str(t).strip().lower() for t in _listed(singletons)} - types)


def plan_world_tool():
    """`plan_world`, the finish tool `_generate_plan` answers with."""
    from world import toolbox as tb

    def parameters(ctx):
        return tb.params({
            "zones": {"type": "array", "items": _zone_item(), "minItems": 3,
                      "maxItems": 6, "description": "The areas the place is "
                                                    "made of"},
            "singleton_types": {"type": "array", "items": {"type": "string"},
                                "description": "Room types that exist only "
                                               "once in the whole world"},
        }, ["zones"])

    def handler(ctx, args, answer):
        given = [zone for zone in _listed(args.get("zones"))
                 if isinstance(zone, dict)]
        said = []
        if not 3 <= len(given) <= 6:
            said.append(f"give 3 to 6 zones, not {len(given)}")
        stray = _singletons_unknown(args.get("singleton_types"), given)
        if stray:
            said.append("singleton_types names " + ", ".join(stray)
                        + ", which no zone has among its room_types")
        if said:
            answer(tb.complain("Not planned: " + "; ".join(said) + ".",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("plan_world", "Plan the areas this world is made of.",
                   parameters, handler, finishes=True)


def area_tool(world_root, zone_id):
    """
    `describe_area`, the finish tool `plan_zone` answers with.

    `zones` is left out entirely for an area already at `zones.MAX_DEPTH`,
    where `apply_plan` would ignore it: a field that cannot be used is not
    offered.
    """
    from world import toolbox as tb
    from world import zones

    def parameters(ctx):
        properties = {
            "purpose": {"type": "string",
                        "description": "One sentence on what happens here"},
            "room_types": {"type": "array", "items": {"type": "string"},
                           "description": "The kinds of room it is made of, "
                                          "as lowercase underscore slugs"},
            "room_budget": {"type": "integer", "minimum": zones.MIN_BUDGET,
                            "maximum": zones.MAX_BUDGET,
                            "description": "How many rooms of its own it is "
                                           "worth"},
            "singleton_types": {"type": "array", "items": {"type": "string"},
                                "description": "Room types that exist only "
                                               "once inside this area"},
        }
        if zones.depth(world_root, zone_id) < zones.MAX_DEPTH:
            properties["zones"] = {
                "type": "array", "items": _zone_item(), "maxItems": 5,
                "description": "The smaller areas it is made of: none, or "
                               "2 to 5"}
        return tb.params(properties, ["purpose", "room_types", "room_budget"])

    def handler(ctx, args, answer):
        inner = [zone for zone in _listed(args.get("zones"))
                 if isinstance(zone, dict)]
        said = []
        if len(inner) == 1:
            said.append("one smaller area is not a division: give none, or "
                        "2 to 5")
        elif len(inner) > 5:
            said.append(f"give at most 5 smaller areas, not {len(inner)}")
        stray = _singletons_unknown(args.get("singleton_types"), inner,
                                    args.get("room_types"))
        if stray:
            said.append("singleton_types names " + ", ".join(stray)
                        + ", which is not among the room types given")
        if said:
            answer(tb.complain("Not planned: " + "; ".join(said) + ".",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("describe_area", "Say what this area is.", parameters,
                   handler, finishes=True)


def _open_directions(world_root, target, reverse):
    """
    The directions a new room's exits may take: what `_allowed_exits` keeps.

    Never the way back, never a diagonal, and never into a destination next
    door -- so the schema offers exactly what would survive, instead of the
    model asking for a door that is then quietly dropped.
    """
    from world import coords

    found = []
    for direction in BUILDABLE_DIRECTIONS:
        if direction == reverse:
            continue
        if target is not None and world_root is not None:
            neighbour = coords.room_at(world_root, coords.step(target, direction))
            if (neighbour is not None
                    and neighbour.db.room_category == "destination"):
                continue
        found.append(direction)
    return found


def _name_parameters(categories, directions, zone_names=()):
    from world import toolbox as tb

    exit_name = {"type": "string", "description": "Which way"}
    if directions:
        exit_name["enum"] = list(directions)
    zone_said = ("The area this room belongs to: "
                 + (", ".join(zone_names) + ", or a new area's name"
                    if zone_names else "a new area's name"))
    return tb.params({
        "name": {"type": "string", "description": "The room's name, 2-6 words"},
        "type": {"type": "string",
                 "description": "What kind of room, as a lowercase underscore "
                                "slug"},
        "category": {"type": "string", "enum": list(categories),
                     "description": "circulation, destination or threshold"},
        "zone": {"type": "string", "description": zone_said},
        "zone_purpose": {"type": "string",
                         "description": "Only for a new area: what happens "
                                        "there"},
        "exits": {"type": "array", "maxItems": len(directions),
                  "items": {"type": "object",
                            "properties": {
                                "name": exit_name,
                                "destination_hint": {
                                    "type": "string",
                                    "description": "One sentence on what lies "
                                                   "that way"}},
                            "required": ["name"],
                            "additionalProperties": False},
                  "description": "The ways on, besides the way back"},
    }, ["name", "category", "zone"])


def name_tool(existing, world_root, source_room, target, arrival_exit):
    """
    `name_room`, the finish tool `_generate_name` answers with.

    The category leaves out `destination` when the room being left is one,
    the exits are limited to the directions that would survive, and `zone`
    names the areas this room could be put in. `_check_name` is the handler,
    so what it would have said in a retry is the tool's result instead.
    """
    from world import toolbox as tb
    from world import zones

    source_category = source_room.db.room_category if source_room else ""
    reverse = OPPOSITES.get(arrival_exit, "back")

    def parameters(ctx):
        categories = [category for category in CATEGORIES
                      if not (category == "destination"
                              and source_category == "destination")]
        source_zone = zones.slugify(source_room.db.zone) if source_room else ""
        names = [zones.name_of(world_root, zone_id) for zone_id
                 in zones.offerable(world_root, target, source_zone)]
        return _name_parameters(categories,
                                _open_directions(world_root, target, reverse),
                                names)

    def handler(ctx, args, answer):
        data = dict(args, exits=[entry for entry in _listed(args.get("exits"))
                                 if isinstance(entry, dict)])
        complaint = _check_name(data, existing, world_root, source_room,
                                target, arrival_exit)
        if complaint:
            answer(tb.complain(complaint, value=data))
            return
        answer(tb.accept(data))

    return tb.Tool("name_room", "Say what this room is, and where it leads.",
                   parameters, handler, finishes=True)


def first_name_tool(plan):
    """`name_room` for a world's first room: a way in, in any direction."""
    from world import toolbox as tb

    def parameters(ctx):
        names = [zone.get("name") for zone in (plan or {}).get("zones", [])
                 if isinstance(zone, dict) and zone.get("name")]
        return _name_parameters(("circulation", "threshold"),
                                BUILDABLE_DIRECTIONS, names)

    return tb.Tool("name_room", "Say what this world's first room is, and "
                                "where it leads.",
                   parameters, lambda ctx, args, answer: answer(tb.accept(args)),
                   finishes=True)


def description_tool():
    """`describe_room`, the finish tool `_generate_description` answers with."""
    from world import toolbox as tb

    def parameters(ctx):
        from world import token_lists, traits

        known = sorted(traits.vocabulary(ctx.world_root))
        return tb.params({
            "description": {"type": "string",
                            "description": "2-4 sentences on the room's "
                                           "permanent fabric"},
            "trait_bonuses": {
                "type": "object",
                "description": "Almost always empty. What being here does to "
                               "whoever is here, as {trait: amount}, naming "
                               "only traits this world measures"
                               + (": " + ", ".join(known)
                                  if known and len(known) <= tb.ENUM_MOST
                                  else " (list_traits)")},
            "new_token_lists": {"type": "array",
                                "items": token_lists.schema(ctx),
                                "description": "Word lists the description "
                                               "uses that this world does not "
                                               "keep yet"},
        }, ["description"])

    def handler(ctx, args, answer):
        said = description_complaints(args, ctx.world_root)
        if said:
            answer(tb.complain("Not described: " + "; ".join(said) + ". Send "
                               "the description again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("describe_room", "Describe this room.", parameters,
                   handler, finishes=True)


def description_complaints(args, world_root):
    """
    What is wrong with a room's description that asking again can put right.

    A trait nothing measures, light given as nothing, a word list that would
    be refused, a slot no list answers, and a list the world keeps under
    another spelling. All of these used to be dropped after the fact.
    """
    from world import token_lists, traits, vocabulary

    said = []
    bonuses = args.get("trait_bonuses")
    if bonuses is not None and not isinstance(bonuses, dict):
        said.append("trait_bonuses has to be an object of {trait: amount}")
    elif bonuses:
        known = traits.vocabulary(world_root)
        strange = sorted(slug for slug in bonuses
                         if traits._slug(slug) not in known
                         and traits._slug(slug) != "light")
        if strange:
            said.append("trait_bonuses names " + ", ".join(strange)
                        + ", which this world does not measure; list_traits "
                          "shows what it does")
        for slug, amount in bonuses.items():
            try:
                number = float(amount)
            except (TypeError, ValueError):
                said.append(f"the bonus for {slug} has to be a number")
                continue
            if traits._slug(slug) == "light" and number <= 0:
                said.append("a dark room gives no light bonus at all: leave "
                            "light out rather than giving it 0")

    declared = _listed(args.get("new_token_lists"))
    said += token_lists.complaints(world_root, declared,
                                   [args.get("description")])
    said += [line.rstrip(".") for line in vocabulary.near_duplicates(
        world_root, new_token_lists=[entry for entry in declared
                                     if isinstance(entry, dict)])]
    return said


# ---------------------------------------------------------------------------
# A room's contents, and what people want that nothing provides (§5.1)
# ---------------------------------------------------------------------------

#: Rounds `populate_room` may take (§10.3): nobody waits on it.
CONTENTS_ROUNDS = 10

CONTENTS_LOOKUPS = ("list_states", "list_state_groups", "list_traits",
                    "kind_info", "commonsense")

#: The most wants shown to one generator call (§5.1).
MOST_WANTS = 3

#: How many wanted things a room is shown when there is no corpus to say
#: which of them belong in it.
UNSORTED_WANTS = 2


def _hints_block(lines, header):
    """A header and its lines for a prompt, or "" when there are none."""
    if not lines:
        return ""
    return header + "\n" + "\n".join(f"  - {line}" for line in lines) + "\n\n"


def _wants(world_root):
    """`goals.blocked_wants`, never raising: a hint must not cost a room."""
    from world import goals

    try:
        return goals.blocked_wants(world_root)
    except Exception:
        logger.log_trace("worldgen: the wants could not be worked out")
        return []


def _spelled(items):
    return {str(item).lower().replace("_", " ") for item in items}


def contents_hints(world_root, room):
    """
    Things somebody wants that exist nowhere, and that belong in this room.

    With ConceptNet, a thing belongs where `AtLocation` read forward from it
    shares a word with the room's type, name or area -- ore goes to mines and
    quarries. Without it, the first `UNSORTED_WANTS` are shown anyway, and the
    prompt says to include one only if it belongs. Never in a room the want
    says to avoid: the giver's, or the wanting character's own.
    """
    if world_root is None or room is None:
        return []
    from world import commonsense, planner, zones

    wanted = [want for want in _wants(world_root)
              if want.get("reason") == planner.MISSING_THING
              and want.get("what") and want.get("words")
              and room.id not in (want.get("avoid") or ())]
    if not wanted:
        return []

    def said(want):
        who = getattr(want.get("who"), "key", "somebody")
        return f"{who} wants something {want['words']}."

    if not commonsense.available():
        return [said(want) for want in wanted[:UNSORTED_WANTS]]

    here = set()
    for text in (room.db.room_type, room.db.room_title or room.key,
                 zones.name_of(world_root, zones.slugify(room.db.zone or ""))
                 if room.db.zone else ""):
        here |= set(str(text or "").lower().replace("_", " ").split())
    lines = []
    for want in wanted:
        places = _spelled(commonsense.forward(want["what"], "AtLocation"))
        if {word for place in places for word in place.split()} & here:
            lines.append(said(want))
        if len(lines) >= MOST_WANTS:
            break
    return lines


def naming_hints(world_root):
    """
    Rooms somebody wants that nobody has built, and where the things somebody
    wants are found, for the room namer.
    """
    if world_root is None:
        return []
    from world import commonsense, planner

    corpus = commonsense.available()
    lines = []
    for want in _wants(world_root):
        if len(lines) >= MOST_WANTS:
            break
        who = getattr(want.get("who"), "key", "somebody")
        if want.get("reason") == planner.MISSING_ROOM and want.get("words"):
            lines.append(f"{who} is looking for {want['words']}, which nobody "
                         f"has built.")
        elif (want.get("reason") == planner.MISSING_THING and corpus
              and want.get("what")):
            places = sorted(_spelled(
                commonsense.forward(want["what"], "AtLocation")))[:3]
            if places:
                lines.append(f"{who} wants something {want['words']}, which "
                             f"is found at {', '.join(places)}.")
    return lines


def _named_in(name, text):
    """Whether a thing's head noun is already written into a description."""
    import re

    from world import lexicon

    word = lexicon.head_noun(name)
    return bool(word) and re.search(rf"(?<![a-z]){re.escape(word)}",
                                    str(text or "").lower()) is not None


def contents_tool(description):
    """
    `furnish_room`, the finish tool `populate_room` answers with.

    Up to three items with `clothing.spec_schema`, each held to what
    `make_item` holds one to, and none that the room's description already
    names -- the rule the prompt stated and nothing checked.
    """
    from world import clothing, item_gen
    from world import toolbox as tb

    def parameters(ctx):
        return tb.params({
            "items": {"type": "array", "items": clothing.spec_schema(ctx),
                      "maxItems": 3,
                      "description": "0 to 3 loose things; none for a bare "
                                     "corridor"},
            "wants_npc": {"type": "boolean",
                          "description": "Whether somebody is in this room "
                                         "right now"},
        }, ["items", "wants_npc"])

    def handler(ctx, args, answer):
        items = [item for item in _listed(args.get("items"))
                 if isinstance(item, dict)]
        said = []
        if len(items) > 3:
            said.append(f"give at most 3 items, not {len(items)}")
        for item in items[:3]:
            name = str(item.get("name") or "").strip() or "an item"
            said += [f"{name}: {line}"
                     for line in item_gen.item_complaints(item, ctx.world_root)]
            if _named_in(name, description):
                said.append(f"{name}: the room's description already has "
                            f"one, as part of the room; give loose things it "
                            f"does not mention")
        if said:
            answer(tb.complain("Not placed: " + "; ".join(said) + ". Send the "
                               "contents again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("furnish_room", "Give this room its loose contents.",
                   parameters, handler, finishes=True)
