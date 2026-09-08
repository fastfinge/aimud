"""
AI-powered item validation and generation.

Two models are used (configured separately via the `models` command):
  validation — decides whether an object/action makes sense
  items       — creates the object with name, description, and takeability
"""

import json
import urllib.request

from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_EXISTENCE_SYSTEM_PROMPT = """You are a game master for a text MUD deciding if an object could plausibly exist in a room.
Respond with JSON only: {"valid": true|false, "reason": "one sentence"}
Be permissive — if it's plausible for the world and room, say valid.
Deny only clear impossibilities (e.g. a spaceship in a medieval dungeon).

One thing is never valid however plausible it sounds: part of a living body.
A hand, a shoulder, hair, a wing, an antenna belongs to whoever has it and is
not a separate object, so answer invalid — otherwise it is built and left
lying on the floor. This is about bodies only: part of a made thing (a door
handle, a table leg, a page of a book) is fine, and so is a part that has
plainly been cut free — a severed hand, a mounted stag's head, a bone."""

_TAKEABILITY_SYSTEM_PROMPT = """You are a game master deciding if a player can pick up an object in a MUD.
Respond with JSON only: {"valid": true|false, "reason": "one sentence"}
Fixed features (walls, doors, floor, built-in or very heavy furniture) cannot be taken.
Portable items (weapons, tools, books, loose objects) can be taken."""

_ITEM_SYSTEM_PROMPT = """You generate items for a text-based MUD.
Respond with a single JSON object — no other text:
{
  "name": "Item Name (2-4 words, title case)",
  "description": "2-3 sentence atmospheric description of the item.",
  "takeable": true|false,
  "affordances": ["readable", "flammable"],
  "states": ["dusty"],
  "clothing_type": "",
  "trait_bonuses": {"defence": 2},
  "bonus_when": "worn"
}
takeable should be false for fixed features (bolted or structural) and true for portable objects.

clothing_type is only for something that can be worn, and goes with the
"wearable" affordance. Use one of: hat, jewelry, top, undershirt, gloves,
fullbody, bottom, underpants, socks, shoes, accessory. Leave it "" for
anything that is not clothing.

affordances are what can be done with this thing, as lowercase single words:
readable, openable, container, surface, flammable, edible, drinkable, wearable,
(a "container" is hollow and things go IN it; a "surface" has a top and things
go ON it -- a table, a shelf, a counter, a desk. Many things are both.)
sittable, climbable, breakable, wet_able, movable, lockable, wieldable...
Use as many as genuinely apply and invent others where they fit — these decide
which verbs work on it, so a poster that cannot be read is a poster nobody can
read. Give an empty list only for something truly inert.

states are conditions currently true of it (locked, lit, wet, dirty, broken),
usually empty for a new object.

{naming_rule}"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _call_openrouter(api_key, model, messages):
    payload = {"model": model, "messages": messages}
    # The sampling settings chosen for this job ride on the model choice. See
    # world.model_params: only what the player actually set is sent.
    from world.model_params import of as _settings

    payload.update(_settings(model))
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
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


def _parse_json(content):
    """
    Parse a model response that should be a single JSON object.

    Delegates to world.model_json, which repairs the near-misses models make
    -- a trailing comma, a stray comment, an answer cut off mid-object --
    rather than losing a whole generation over one character.
    """
    from world.model_json import parse_object

    return parse_object(content)


def _room_context(room):
    title = room.db.room_title or room.key
    desc = room.db.desc or ""
    return f"[{title}]\n{desc}"


def _world_and_room(room, facet):
    """
    The world, what this world tells `facet` in particular, and the room.

    The facet is named by the caller rather than fixed here: deciding whether
    a thing could exist is the world's rules talking, and writing the thing
    once it may is the world's items talking, and the two want to be told
    different things.
    """
    from world import lore

    return (f"World: {lore.description(room)}\n\n"
            f"{lore.guidance_block(room, facet)}"
            f"Room:\n{_room_context(room)}")


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def validate_object_existence(account, room, object_name, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether object_name could exist in room.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = account.model_for("validation")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    messages = [
        {"role": "system", "content": _EXISTENCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'validation')}\n\n"
                f"Could '{object_name}' plausibly exist in this room?"
            ),
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            reason = str(data.get("reason", ""))
            if data.get("valid"):
                on_valid(reason)
            else:
                on_invalid(reason)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def validate_object_takeable(account, room, obj, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether obj can be picked up.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = account.model_for("validation")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    obj_name = obj.db.room_title or obj.key
    obj_desc = obj.db.desc or ""

    messages = [
        {"role": "system", "content": _TAKEABILITY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'validation')}\n\n"
                f"Object: {obj_name}\n{obj_desc}\n\n"
                f"Can the player pick up '{obj_name}'?"
            ),
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            reason = str(data.get("reason", ""))
            if data.get("valid"):
                on_valid(reason)
            else:
                on_invalid(reason)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def generate_item(account, room, object_name, on_success, on_error):
    """
    Async. Ask the item model to create object_name and spawn it in room.
    The created object has db.ai_takeable already set from the model response.
    Calls on_success(item_obj) or on_error(msg) in the main thread.
    """
    model = account.model_for("items")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    from world import gear, verbs

    messages = [
        {"role": "system",
         "content": _ITEM_SYSTEM_PROMPT.replace(
             "{naming_rule}", verbs.naming_rule())},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'items')}\n\n"
                f"{gear.prompt_block(room.db.world_root if room else None)}"
                f"Generate the item the player is examining: '{object_name}'"
            ),
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            name = str(data.get("name", object_name)).strip()
            description = str(data.get("description", "")).strip()
            takeable = bool(data.get("takeable", True))

            from world import clothing

            # Built through the clothing layer so that anything the model
            # called wearable really can be put on. A coat found in a
            # wardrobe is the same kind of thing as a coat a character was
            # born in, and nothing here has to know which.
            item = clothing.create(
                {**dict(data), "name": name, "description": description,
                 "takeable": takeable},
                location=room,
            )
            if item is None:
                raise ValueError("the model named no item")
            # Answer to the words that asked for it, not only to the name it
            # was given. Ask for an astrolabe and get a "Brass Orrery", and
            # without this the next request for an astrolabe finds nothing and
            # conjures another one.
            requested = str(object_name or "").strip().lower()
            if requested and requested != name.lower():
                item.aliases.add(requested)

            on_success(item)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)
