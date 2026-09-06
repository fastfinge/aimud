"""
AI-powered world and room generation via OpenRouter.

All DB access (context building, object creation) runs in the main Twisted
thread.  Only the network call to OpenRouter is deferred to a thread pool.
"""

import json
import random
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

_ROOM_SYSTEM_PROMPT = """You generate rooms for a text-based MUD.
Respond with a single JSON object — no other text — matching:
{
  "title": "Short room name (3–8 words)",
  "description": "Atmospheric 2–4 sentence description",
  "exits": [
    {"name": "direction or label", "destination_hint": "one sentence about what lies beyond"}
  ]
}
Use cardinal directions (north, south, east, west, up, down) or vivid labels.
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

def _parse_room(content):
    try:
        raw = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON in model response: {content!r}")
        raw = json.loads(m.group())

    title = str(raw.get("title", "Unknown Room")).strip()
    description = str(raw.get("description", "")).strip()
    exits = [
        {"name": str(e["name"]).lower().strip(), "destination_hint": str(e.get("destination_hint", ""))}
        for e in raw.get("exits", [])
        if str(e.get("name", "")).strip()
    ]
    return title, description, exits


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

    # The ten cells touching the target, looked up directly so that adjacency
    # and availability can never disagree -- a same-floor scan would miss the
    # room above or below, including the source room on a vertical move.
    touching = {
        direction: coords.room_at(world_root, coords.step(target, direction))
        for direction in coords.DIRECTION_VECTORS
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
            adjacent[direction] = {
                "room": room.db.room_title or room.key,
                "may_connect": True,
            }

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
                 world_root=None, creator=None):
    """
    Create an Evennia Room and its exits.  Must run in the main thread.

    source_room  -- the room the player came FROM (None for the first room)
    arrival_exit -- the exit name used to enter (e.g. "north"); None for first room
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

    # world_root is passed in for connected rooms; the first room sets itself as root.
    actual_root = world_root if world_root is not None else room
    room.db.world_root = actual_root
    if world_root is None:
        room.db.is_world_root = True
        if creator is not None:
            room.db.world_creator = creator
    # Tag lets us find all rooms belonging to a world efficiently.
    room.tags.add(str(actual_root.id), category="ai_world")

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


def _maybe_spawn_npc(account, room, on_ready):
    """
    Roll a 25% chance to populate the room with an NPC.

    If an NPC will be spawned, on_ready(room) is called only AFTER the NPC
    generation API call completes, so the player never enters an empty room
    that suddenly gains an NPC a moment later.

    If the roll fails, or if NPC generation errors out, on_ready(room) is
    called immediately so the player is never stranded.
    """
    if random.random() >= 0.25:
        on_ready(room)
        return

    from evennia.utils import logger
    from world.npc_gen import generate_npc

    def _npc_error(err):
        logger.log_err(f"NPC generation failed for room '{room.key}': {err}")
        account.msg(f"|y(NPC generation error: {err})|n")
        on_ready(room)

    generate_npc(
        account=account,
        room=room,
        on_success=lambda _npc: on_ready(room),
        on_error=_npc_error,
    )


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
# Public async API
# ---------------------------------------------------------------------------

def generate_first_room(account, world_description, on_success, on_error):
    """
    Async. Generate the starting room for a new world.
    Calls on_success(room) or on_error(msg) in the main thread.
    """
    model = account.get_model_for("rooms") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    messages = [
        {"role": "system", "content": _ROOM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"World theme: {world_description}\n\n"
                "Generate the starting room. It should feel like a natural entry point."
            ),
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            title, desc, exits = _parse_room(content)
            room = _create_room(title, desc, exits, world_description, None, None,
                                creator=account)
            # Record this world on the account so `worlds` can list it.
            created = account.db.created_worlds or []
            created.append(room.id)
            account.db.created_worlds = created
            _maybe_spawn_npc(account, room, on_success)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


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
    model = account.get_model_for("rooms") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    # Build context here (main thread — DB access is safe)
    context = _neighbourhood(source_room, exit_name)
    reverse = OPPOSITES.get(exit_name, "back")
    source_title = source_room.db.room_title or source_room.key

    hint_line = (
        f"When the '{exit_name}' exit was written, the room beyond it was described "
        f"as: \"{destination_hint}\"\n"
        f"The room you generate must match that description.\n\n"
        if destination_hint else ""
    )

    messages = [
        {"role": "system", "content": _ROOM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"World theme: {world_description}\n\n"
                f"The player leaves '{source_title}' through its '{exit_name}' exit. "
                f"Generate the room they arrive in.\n\n"
                f"{hint_line}"
                f"Surrounding area:\n{context}\n\n"
                f"'adjacent' gives each direction from the new room. A room being "
                f"next to yours does NOT mean a door joins them: classrooms along a "
                f"corridor share walls but open only onto the corridor. Each "
                f"direction is one of three cases:\n"
                f"  may_open_new_room — empty ground; an exit here builds a new room\n"
                f"  may_connect       — a room is already there; add an exit ONLY if "
                f"a door genuinely belongs between the two, otherwise leave it as a "
                f"shared wall\n"
                f"  already_connected — the way back, created automatically; never "
                f"list a '{reverse}' exit\n\n"
                f"'opens_onto' shows which directions each nearby room actually has "
                f"doors in — follow the layout's habits. Your room must make sense "
                f"among its neighbours: do not repeat a room that already exists "
                f"nearby, and do not reuse any name in 'names_in_use'."
            ),
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            title, desc, exits = _parse_room(content)
            # Drop reverse if the model included it anyway
            exits = [e for e in exits if e["name"] != reverse]
            room = _create_room(
                title, desc, exits, world_description, source_room, exit_name,
                world_root=source_room.db.world_root,
            )
            _maybe_spawn_npc(account, room, on_success)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)
