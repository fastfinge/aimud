"""
AI-powered world and room generation via OpenRouter.

All DB access (context building, object creation) runs in the main Twisted
thread.  Only the network call to OpenRouter is deferred to a thread pool.
"""

import json
import re
import urllib.request

from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
Respond with a single JSON object — no other text — matching:
{
  "zones": [
    {"name": "short zone name",
     "purpose": "one sentence on what happens here",
     "room_types": ["slug", "slug"]}
  ],
  "singleton_types": ["slug", "slug"]
}
Zones are the areas a place is made of — a school has an admin wing, a
classroom wing, a gym block. Give 3 to 6 zones.
room_types are lowercase underscore slugs ("classroom", "chem_lab", "corridor").
singleton_types lists the slugs that must exist only ONCE in the whole world —
a school has one principal's office and one gymnasium, but many classrooms.
Return only the JSON object."""

_NAME_SYSTEM_PROMPT = """You decide what one room in a text-based MUD is, and where it leads.
Respond with a single JSON object — no other text — matching:
{
  "name": "Room name, 2-6 words",
  "type": "slug",
  "category": "circulation|destination|threshold",
  "zone": "zone name",
  "exits": [{"name": "direction", "destination_hint": "one sentence on what lies that way"}]
}

category:
- "circulation": how people move between places (corridor, stairwell, lobby, junction)
- "destination": somewhere people go to and stop (classroom, office, lab, kitchen)
- "threshold": a seam between areas (doorway, airlock, gate, foyer)

Two destinations must never open directly onto each other. If the room you are
entering from is a destination, this room must be circulation or a threshold.
A destination should have few exits — usually just the way in. Circulation is
what carries traffic, so it may have several.

Write no prose beyond the destination hints. Return only the JSON object."""

_DESC_SYSTEM_PROMPT = """You write the description of one room in a text-based MUD.
Respond with a single JSON object — no other text — matching:
{"description": "2-4 sentences"}

Describe ONLY the permanent physical fabric of the room: its architecture,
surfaces, fixtures fixed in place, light, sound, smell, temperature, wear.

Never mention:
- objects a player could pick up or that might be removed (the game places those separately)
- people, creatures or NPCs (they move; the description would go stale)
- exits or compass directions (the game lists exits itself)
- the player: no "you", no second person, no narrating what anyone does

Present tense. Concrete and sensory rather than ornate. It may echo a
neighbouring area in general terms — chlorine on the air, a hum through the
bulkhead — but never name another room.
Return only the JSON object."""

_CONTENTS_SYSTEM_PROMPT = """You populate a room in a text-based MUD with its loose contents.
Respond with a single JSON object — no other text — matching:
{
  "items": [
    {"name": "item name", "description": "1-2 sentences", "takeable": true,
     "affordances": ["readable"], "states": []}
  ],
  "wants_npc": <true or false>
}

items are the portable, removable things that happen to be here — never the
room's fixtures, which are already in its description. Give 0 to 3, and prefer
0 for a bare corridor. Do not repeat anything already named in the description.

affordances are what can be done with each item, as lowercase single words:
readable, openable, container, flammable, edible, drinkable, wearable,
breakable, wieldable, and so on. They decide which verbs work on it, so give
every one that genuinely applies. states are conditions currently true of it
(dusty, wet, broken), usually empty.

wants_npc asks whether someone is in this room right now. Judge it from the
room: a place people work in, wait in, staff or gather in usually has somebody
there — an office has whoever works at it, a classroom has a teacher or a
pupil, a shop has someone behind the counter. Passageways, storerooms and
empty thresholds usually do not. Decide honestly for this room rather than
defaulting either way; a world where nobody is ever anywhere feels dead.
Return only the JSON object."""


# ---------------------------------------------------------------------------
# Network (runs in thread)
# ---------------------------------------------------------------------------

def _call_openrouter(api_key, model, messages):
    payload = {"model": model, "messages": messages}
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Parsing (pure Python, safe anywhere)
# ---------------------------------------------------------------------------

def _parse_json_object(content):
    """Parse a model response that should be a single JSON object."""
    try:
        return json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON in model response: {content!r}")
        return json.loads(match.group())


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
            desc = room.db.desc or ""
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
        desc = room.db.desc or ""
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
                 world_root=None, creator=None, room_type="", category="", zone=""):
    """
    Create an Evennia Room and its exits.  Must run in the main thread.

    source_room  -- the room the player came FROM (None for the first room)
    arrival_exit -- the exit name used to enter (e.g. "north"); None for first room
    room_type    -- slug from the naming pass ("classroom"), used for singletons
    category     -- circulation | destination | threshold
    zone         -- which of the world plan's zones this room belongs to
    """
    from evennia import create_object
    from typeclasses.rooms import Room
    from typeclasses.exits import AIExit

    room = create_object(Room, key=title)
    room.db.desc = description
    room.db.room_title = title
    room.db.world_description = world_description
    room.db.world_parent = source_room  # Evennia stores this as a dbref
    room.db.is_ai_room = True
    room.db.room_type = room_type
    room.db.room_category = category
    room.db.zone = zone

    # world_root is passed in for connected rooms; the first room sets itself as root.
    actual_root = world_root if world_root is not None else room
    room.db.world_root = actual_root
    if world_root is None:
        room.db.is_world_root = True
        if creator is not None:
            room.db.world_creator = creator
    # Tag lets us find all rooms belonging to a world efficiently.
    room.tags.add(str(actual_root.id), category="ai_world")
    _record_type(actual_root, room_type, room)

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


def _singletons_taken(world_root):
    """{slug: room name} for singleton types already placed in this world."""
    used = (world_root.db.room_types_used or {}) if world_root else {}
    singles = set(world_plan(world_root).get("singleton_types") or [])
    return {slug: name for slug, name in used.items() if slug in singles}


def _record_type(world_root, slug, room):
    """Note that `slug` is now used in this world."""
    if not world_root or not slug:
        return
    used = dict(world_root.db.room_types_used or {})
    used.setdefault(slug, room.db.room_title or room.key)
    world_root.db.room_types_used = used


def _check_name(data, existing_names, world_root, source_category):
    """
    Validate a naming response. Returns a complaint string, or None if good.

    The complaint is fed back to the model on retry, so it must say what to do
    differently rather than merely what was wrong.
    """
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

    slug = str(data.get("type", "")).strip().lower()
    taken = _singletons_taken(world_root)
    if slug and slug in taken:
        return (f"This world already has its '{slug}' ({taken[slug]}), and there is "
                f"only ever one. Choose a different kind of room.")
    return None


def _generate_plan(account, api_key, world_description, on_done):
    """
    Async. Ask for the world's zones and singleton room types.

    Failure is not fatal: a world with no plan simply generates without zone
    guidance, so on_done is always called.
    """
    model = account.get_model_for("rooms") or "openai/gpt-4o-mini"
    messages = [
        {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": f"World theme: {world_description}\n\nPlan its zones."},
    ]

    def _done(content):
        try:
            raw = _parse_json_object(content)
            zones = [
                {
                    "name": str(z.get("name", "")).strip(),
                    "purpose": str(z.get("purpose", "")).strip(),
                    "room_types": [str(t).strip().lower() for t in z.get("room_types", [])],
                }
                for z in raw.get("zones", [])
                if str(z.get("name", "")).strip()
            ]
            singles = [str(t).strip().lower() for t in raw.get("singleton_types", [])]
            on_done({"zones": zones, "singleton_types": singles})
        except Exception:
            on_done({})

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda _f: on_done({}))


def _generate_name(account, api_key, world_description, context, source_room,
                   exit_name, hint, on_success, on_error, attempts=3):
    """
    Async. Name the room, retrying while validation rejects the answer.

    Short output, so a rejected answer costs one small call rather than a whole
    room's worth of prose.
    """
    model = (account.get_model_for("naming")
             or account.get_model_for("rooms")
             or "openai/gpt-4o-mini")
    world_root = source_room.db.world_root
    plan = world_plan(world_root)
    existing = _nearby_names(source_room, exit_name)
    source_category = source_room.db.room_category

    zone_lines = "\n".join(
        f"- {z['name']}: {z['purpose']} (typical rooms: {', '.join(z['room_types'])})"
        for z in plan.get("zones", [])
    )
    taken = _singletons_taken(world_root)

    base = (
        f"World theme: {world_description}\n\n"
        + (f"Zones in this world:\n{zone_lines}\n\n" if zone_lines else "")
        + (f"Already built, do not create a second one: "
           f"{', '.join(f'{k} ({v})' for k, v in taken.items())}\n\n" if taken else "")
        + f"The player leaves '{source_room.db.room_title or source_room.key}' "
        f"(category: {source_category or 'unknown'}) through its '{exit_name}' exit.\n\n"
        + (f"That exit was written as leading to: \"{hint}\"\n\n" if hint else "")
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

    def attempt(remaining, convo):
        def _done(content):
            try:
                data = _parse_json_object(content)
            except Exception as exc:
                return _retry(remaining, convo, f"That was not valid JSON: {exc}")
            complaint = _check_name(data, existing, world_root, source_category)
            if complaint and remaining > 1:
                return _retry(remaining, convo + [
                    {"role": "assistant", "content": content},
                ], complaint)
            on_success(data)

        threads.deferToThread(
            _call_openrouter, api_key, model, convo
        ).addCallbacks(_done, lambda f: on_error(f.getErrorMessage()))

    def _retry(remaining, convo, complaint):
        attempt(remaining - 1, convo + [{"role": "user", "content": complaint}])

    attempt(attempts, messages)


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


def _generate_description(account, api_key, world_description, context, name,
                          room_type, category, on_success, on_error):
    """Async. Write the room's description, given the area around it."""
    model = account.get_model_for("rooms") or "openai/gpt-4o-mini"
    messages = [
        {"role": "system", "content": _DESC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"World theme: {world_description}\n\n"
                f"Room: {name}\n"
                f"Kind: {room_type or 'unspecified'} ({category or 'unspecified'})\n\n"
                f"Surrounding area, for continuity only — do not name these rooms:\n"
                f"{context}\n\n"
                f"Describe this room's permanent physical fabric."
            ),
        },
    ]

    def _done(content):
        try:
            data = _parse_json_object(content)
            desc = str(data.get("description", "")).strip()
            if not desc:
                raise ValueError("empty description")
            on_success(desc)
        except Exception as exc:
            on_error(str(exc))

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda f: on_error(f.getErrorMessage()))


def _join_names(names):
    """"a, b and c" -- for reading aloud, not for parsing."""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def populate_room(account, room):
    """
    Async, fire-and-forget. Give a finished room its loose contents.

    Runs after the player has arrived, so it costs them no waiting; items and
    any NPC appear in the room as they are created.  Errors are swallowed --
    an unfurnished room is a small loss, a stranded player is not.
    """
    try:
        api_key = account.get_openrouter_key()
    except ValueError:
        return
    model = (account.get_model_for("contents")
             or account.get_model_for("items")
             or "openai/gpt-4o-mini")

    messages = [
        {"role": "system", "content": _CONTENTS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"World theme: {room.db.world_description}\n\n"
                f"Room: {room.db.room_title or room.key}\n"
                f"Kind: {room.db.room_type or 'unspecified'} "
                f"({room.db.room_category or 'unspecified'})\n\n"
                f"Description: {room.db.desc}\n\n"
                f"What loose items are here?"
            ),
        },
    ]

    def _done(content):
        from evennia import create_object
        from typeclasses.objects import Object

        try:
            data = _parse_json_object(content)
        except Exception:
            return

        created = []
        for item in (data.get("items") or [])[:3]:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            obj = create_object(Object, key=name, location=room)
            obj.db.desc = str(item.get("description", "")).strip()
            obj.db.ai_takeable = bool(item.get("takeable", True))
            obj.db.is_ai_item = True
            obj.db.affordances = sorted(
                {str(a).lower().strip() for a in item.get("affordances", []) if a}
            )
            obj.db.states = sorted(
                {str(s).lower().strip() for s in item.get("states", []) if s}
            )
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

            generate_npc(account=account, room=room,
                         on_success=arrived,
                         on_error=lambda _err: None)

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda _f: None)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def generate_first_room(account, spec, on_success, on_error,
                        creator_character=None):
    """
    Async. Generate the starting room for a new world.

    `spec` is what the worldgen wizard collected: title, description, and the
    player's name and appearance in this world. A bare string is accepted as
    the description alone, so older callers keep working.

    Calls on_success(room) or on_error(msg) in the main thread.
    """
    if isinstance(spec, str):
        spec = {"description": spec}
    world_description = (spec.get("description") or "").strip()

    model = account.get_model_for("rooms") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
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
                    + (f"Zones in this world:\n{zone_lines}\n\n" if zone_lines else "")
                    + f"This is the world's first room — the way in. It should be "
                      f"circulation or a threshold rather than a destination, so the "
                      f"world can open out from it.\n\n"
                      f"Name it and give its exits. Use only these directions: "
                      f"{', '.join(BUILDABLE_DIRECTIONS)}."
                ),
            },
        ]

        def with_name(content):
            try:
                named = _parse_json_object(content)
            except Exception as exc:
                return on_error(str(exc))

            name = str(named.get("name", "")).strip() or "Unnamed Room"
            room_type = str(named.get("type", "")).strip().lower()
            category = str(named.get("category", "")).strip().lower()
            if category not in CATEGORIES:
                category = "threshold"
            zone = str(named.get("zone", "")).strip()
            exits = [
                {"name": d, "destination_hint": str(e.get("destination_hint", "")).strip()}
                for e in (named.get("exits") or [])
                for d in [canonical_direction(str(e.get("name", "")).strip())]
                if d in BUILDABLE_DIRECTIONS
            ]

            def finish(description):
                try:
                    room = _create_room(
                        name, description, exits, world_description, None, None,
                        creator=account, room_type=room_type, category=category,
                        zone=zone,
                    )
                    room.db.world_plan = plan

                    # Title, long description, and the player's name and
                    # appearance here -- all set before anyone arrives, so the
                    # first look already shows the world as it was designed.
                    from world import lore

                    lore.store(room, spec)
                    lore.apply_to_player(room, creator_character, spec)
                    # Record this world on the account so `worlds` can list it.
                    created = account.db.created_worlds or []
                    created.append(room.id)
                    account.db.created_worlds = created
                    on_success(room)
                    populate_room(account, room)
                except Exception as exc:
                    on_error(str(exc))

            _generate_description(
                account, api_key, world_description, "(this is the first room)",
                name, room_type, category,
                on_success=finish, on_error=on_error,
            )

        threads.deferToThread(
            _call_openrouter, api_key, model, messages
        ).addCallbacks(with_name, lambda f: on_error(f.getErrorMessage()))

    _generate_plan(account, api_key, world_description, with_plan)


def generate_connected_room(account, world_description, source_room, exit_name,
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
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    # Build context here (main thread — DB access is safe)
    context = _neighbourhood(source_room, exit_name)
    reverse = OPPOSITES.get(exit_name, "back")

    def with_name(named):
        name = str(named.get("name", "")).strip() or "Unnamed Room"
        room_type = str(named.get("type", "")).strip().lower()
        category = str(named.get("category", "")).strip().lower()
        if category not in CATEGORIES:
            category = "circulation"
        zone = str(named.get("zone", "")).strip()

        exits = _allowed_exits(named.get("exits"), source_room, exit_name, reverse)

        _generate_description(
            account, api_key, world_description, context, name, room_type, category,
            on_success=lambda description: finish(name, description, exits,
                                                  room_type, category, zone),
            on_error=on_error,
        )

    def finish(name, description, exits, room_type, category, zone):
        try:
            room = _create_room(
                name, description, exits, world_description, source_room, exit_name,
                world_root=source_room.db.world_root,
                room_type=room_type, category=category, zone=zone,
            )
            # The player moves now; contents arrive behind them.
            on_success(room)
            populate_room(account, room)
        except Exception as exc:
            on_error(str(exc))

    _generate_name(
        account, api_key, world_description, context, source_room, exit_name,
        destination_hint,
        on_success=with_name,
        on_error=on_error,
    )
