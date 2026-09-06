"""
AI-powered item validation and generation.

Two models are used (configured separately via the `models` command):
  validation — decides whether an object/action makes sense
  items       — creates the object with name, description, and takeability
"""

import json
import re
import urllib.request

from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_EXISTENCE_SYSTEM_PROMPT = """You are a game master for a text MUD deciding if an object could plausibly exist in a room.
Respond with JSON only: {"valid": true|false, "reason": "one sentence"}
Be permissive — if it's plausible for the world and room, say valid.
Deny only clear impossibilities (e.g. a spaceship in a medieval dungeon)."""

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
  "states": ["dusty"]
}
takeable should be false for fixed features (bolted or structural) and true for portable objects.

affordances are what can be done with this thing, as lowercase single words:
readable, openable, container, flammable, edible, drinkable, wearable,
sittable, climbable, breakable, wet_able, movable, lockable, wieldable...
Use as many as genuinely apply and invent others where they fit — these decide
which verbs work on it, so a poster that cannot be read is a poster nobody can
read. Give an empty list only for something truly inert.

states are conditions currently true of it (locked, lit, wet, dirty, broken),
usually empty for a new object."""


# ---------------------------------------------------------------------------
# Shared helpers
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


def _parse_json(content):
    try:
        return json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"No JSON in model response: {content!r}")


def _room_context(room):
    title = room.db.room_title or room.key
    desc = room.db.desc or ""
    return f"[{title}]\n{desc}"


def _world_and_room(room):
    from world import lore

    return f"World: {lore.description(room)}\nRoom:\n{_room_context(room)}"


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def validate_object_existence(account, room, object_name, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether object_name could exist in room.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = account.get_model_for("validation") or "openai/gpt-4o-mini"
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
                f"{_world_and_room(room)}\n\n"
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
    model = account.get_model_for("validation") or "openai/gpt-4o-mini"
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
                f"{_world_and_room(room)}\n\n"
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
    model = account.get_model_for("items") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    messages = [
        {"role": "system", "content": _ITEM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room)}\n\n"
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

            from evennia import create_object
            from typeclasses.objects import Object

            item = create_object(Object, key=name, location=room)
            # Answer to the words that asked for it, not only to the name it
            # was given. Ask for an astrolabe and get a "Brass Orrery", and
            # without this the next request for an astrolabe finds nothing and
            # conjures another one.
            requested = str(object_name or "").strip().lower()
            if requested and requested != name.lower():
                item.aliases.add(requested)
            item.db.desc = description
            item.db.ai_takeable = takeable
            item.db.is_ai_item = True
            # What can be done with it, and what is currently true of it.
            # Verb rules test these, so an object without affordances is one
            # no verb will work on.
            item.db.affordances = sorted(
                {str(a).lower().strip() for a in data.get("affordances", []) if a}
            )
            item.db.states = sorted(
                {str(s).lower().strip() for s in data.get("states", []) if s}
            )

            on_success(item)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)
