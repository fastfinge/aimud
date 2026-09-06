"""
AI validation and generation for unknown player commands.

Two models are used (configured via the `models` command):
  validation — decides whether an action makes sense in context
  commands   — narrates what happens and describes any world effects
"""

import json
import re
import urllib.request

from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_VALIDATION_SYSTEM = """You are a game master for a text MUD. Decide if a player action makes sense in context.
Respond with JSON only: {"valid": true|false, "reason": "one sentence"}
Be permissive — mark valid if the action has any plausible meaning in this world and room.
Deny only actions that are completely impossible for the setting (e.g. "hack computer" in a medieval dungeon)."""

_COMMAND_SYSTEM = """You are a game master resolving a player action in a text-based MUD.
Respond with a single JSON object only — no other text:
{
  "response": "2-4 sentence atmospheric second-person narration of what happens.",
  "cache_on": "object|room|player",
  "repeatable": false,
  "effects": []
}

cache_on:
- "object": action is tied to a specific named object in the room (e.g. "read scroll", "push lever")
- "room": action depends on the current room but not a specific object (e.g. "listen", "search")
- "player": character ability independent of location (e.g. "meditate", "pray", "flex")

repeatable: true if the action can logically happen multiple times with the same result
(e.g. "brew potion" creates a new potion each time). false for one-time actions
(e.g. "pull lever" should only open a door once).

effects: list of world changes that logically result from this action. Use an empty list for
pure narration. Each element is one of the following shapes:

Create a new object in the room or the player's inventory:
{"type": "create_object", "name": "Object Name", "description": "Evocative 2-3 sentence description.", "takeable": true|false, "location": "room|player"}

Permanently remove an object:
{"type": "destroy_object", "name": "exact object name as it appears in the room"}

Move an object between the room and the player's inventory:
{"type": "move_object", "name": "object name", "from": "room|player", "to": "room|player"}

Change an object's name or description:
{"type": "modify_object", "name": "object name", "new_name": "optional", "new_description": "optional"}

Rewrite the current room's description or name:
{"type": "modify_room", "new_description": "complete new room description", "new_name": "optional new room name"}

Move the player through an existing exit:
{"type": "move_player", "exit": "exit direction or name, e.g. north"}

Only include effects that genuinely change the world. A purely narrative action has an empty effects list."""


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
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"No JSON in model response: {content!r}")


def _build_context(room, caller=None, target_obj=None):
    """Build a context string with world, room, objects, exits, and target."""
    world_desc = room.db.world_description or ""
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""
    ctx = f"World: {world_desc}\nRoom: [{room_title}]\n{room_desc}"

    # Objects visible in the room (not exits, not characters, not the caller)
    objects = [
        obj for obj in room.contents
        if getattr(obj, "destination", None) is None
        and not hasattr(obj, "sessions")
        and obj is not caller
    ]
    if objects:
        ctx += "\nObjects in room: " + ", ".join(obj.key for obj in objects)

    exits = [obj for obj in room.contents if getattr(obj, "destination", None) is not None]
    if exits:
        ctx += "\nExits: " + ", ".join(ex.key for ex in exits)

    if target_obj:
        obj_desc = target_obj.db.desc or ""
        ctx += f"\nTarget object: {target_obj.key}\n{obj_desc}"

    return ctx


# ---------------------------------------------------------------------------
# Effect application (runs in main thread only)
# ---------------------------------------------------------------------------

def apply_effects(caller, room, effects):
    """
    Apply a list of effect dicts returned by the commands model.
    Must be called from the main Twisted thread (i.e. inside a callback).
    """
    from commands.look_take_cmds import _find_one
    from evennia import create_object
    from typeclasses.objects import Object

    for effect in effects:
        etype = effect.get("type", "")

        if etype == "create_object":
            name = str(effect.get("name", "An object")).strip()
            description = str(effect.get("description", "")).strip()
            takeable = bool(effect.get("takeable", True))
            location = caller if effect.get("location") == "player" else room
            obj = create_object(Object, key=name, location=location)
            obj.db.desc = description
            obj.db.ai_takeable = takeable
            obj.db.is_ai_item = True

        elif etype == "destroy_object":
            name = str(effect.get("name", "")).strip()
            if name:
                obj, _ = _find_one(caller, name, location=room)
                if not obj:
                    obj, _ = _find_one(caller, name, location=caller)
                if obj and obj is not room and obj is not caller:
                    obj.delete()

        elif etype == "move_object":
            name = str(effect.get("name", "")).strip()
            if name:
                src = caller if effect.get("from") == "player" else room
                obj, _ = _find_one(caller, name, location=src)
                if obj and obj is not room and obj is not caller:
                    dest = caller if effect.get("to") == "player" else room
                    obj.move_to(dest, quiet=True)

        elif etype == "modify_object":
            name = str(effect.get("name", "")).strip()
            if name:
                obj, _ = _find_one(caller, name, location=room)
                if not obj:
                    obj, _ = _find_one(caller, name, location=caller)
                if obj and obj is not room and obj is not caller:
                    if "new_name" in effect:
                        obj.key = str(effect["new_name"]).strip()
                    if "new_description" in effect:
                        obj.db.desc = str(effect["new_description"]).strip()

        elif etype == "modify_room":
            if "new_description" in effect:
                room.db.desc = str(effect["new_description"]).strip()
            if "new_name" in effect:
                new_name = str(effect["new_name"]).strip()
                room.key = new_name
                room.db.room_title = new_name

        elif etype == "move_player":
            exit_name = str(effect.get("exit", "")).strip()
            if exit_name:
                from commands.look_take_cmds import _find_one as _fo
                exit_obj, _ = _fo(caller, exit_name, location=room)
                if exit_obj and getattr(exit_obj, "destination", None) is not None:
                    exit_obj.at_traverse(caller, exit_obj.destination)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def validate_command(account, room, action, target_obj, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether `action` makes sense in this room.
    Calls on_valid(), on_invalid(reason), or on_error(msg) in the main thread.
    """
    model = account.get_model_for("validation") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    ctx = _build_context(room, target_obj=target_obj)
    messages = [
        {"role": "system", "content": _VALIDATION_SYSTEM},
        {
            "role": "user",
            "content": f"{ctx}\n\nPlayer action: '{action}'\nIs this valid in this context?",
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            if data.get("valid"):
                on_valid()
            else:
                on_invalid(str(data.get("reason", "")))
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def generate_command_response(account, caller, room, action, target_obj, on_success, on_error):
    """
    Async. Ask the commands model to narrate `action` and list its world effects.
    Calls on_success(response, cache_on, obj_or_None, effects, repeatable)
    or on_error(msg) in the main thread.
    """
    model = account.get_model_for("commands") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    ctx = _build_context(room, caller=caller, target_obj=target_obj)
    messages = [
        {"role": "system", "content": _COMMAND_SYSTEM},
        {
            "role": "user",
            "content": f"{ctx}\n\nPlayer performed: '{action}'\nResolve this action.",
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            response = str(data.get("response", "")).strip()
            cache_on = str(data.get("cache_on", "room")).strip()
            if cache_on not in ("object", "room", "player"):
                cache_on = "room"
            repeatable = bool(data.get("repeatable", False))
            effects = data.get("effects", [])
            if not isinstance(effects, list):
                effects = []
            # Fall back to room-level cache when model picks "object" but there's no target
            if cache_on == "object" and not target_obj:
                cache_on = "room"
            obj = target_obj if cache_on == "object" else None
            on_success(response, cache_on, obj, effects, repeatable)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)
