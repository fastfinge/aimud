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

def _build_context(source_room, max_chars=4000):
    """
    Walk up the world_parent chain from source_room, collecting room summaries.
    Returns a string with most-distant room first, source_room last.
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
                _make_exit(AIExit, name, room, room, pending=True,
                           hint=exit_data["destination_hint"])
    else:
        # First room — all AI exits are pending
        for exit_data in exits:
            _make_exit(AIExit, exit_data["name"], room, room, pending=True,
                       hint=exit_data["destination_hint"])

    return room


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
    context = _build_context(source_room)
    reverse = OPPOSITES.get(exit_name, "back")

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
                f"Nearby rooms (most distant first, closest at bottom):\n{context}\n\n"
                f"The player moves through the '{exit_name}' exit from the bottom room. "
                f"Generate the room they arrive in.\n\n"
                f"{hint_line}"
                f"Do NOT include a '{reverse}' exit — that direction leads back and is "
                f"created automatically. Include only forward exits."
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
