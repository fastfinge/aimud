"""
Applying the consequences of a verb.

Effects are the only way a verb changes the world, and they run identically
whether a player or an NPC triggered them -- an NPC that lights a lamp lights
it for everyone, through this code, not by narrating that it did.

One thing is permanently off limits: exits. Everything else in a world is fair
game to burn, break or carry off, but an exit is part of the map rather than
part of the furniture, and a character deleting one would strand the world.
Player characters are protected too, on the grounds that removing a person
from the game is a different kind of act from smashing a chair.
"""

from evennia.utils import logger


def forget_narrations(obj):
    """
    Drop the cached descriptions of what verbs do to this object.

    Rules survive -- what "read" means has not changed -- but the words
    describing this particular thing were written about the thing it used to
    be, and would otherwise be replayed for something that no longer matches.
    """
    if obj.db.ai_commands:
        obj.db.ai_commands = {}


def _protected(obj, room):
    """True for things a verb must never destroy or carry away."""
    from evennia.objects.objects import DefaultCharacter

    if obj is None or obj is room:
        return True
    if getattr(obj, "destination", None) is not None:
        return True  # an exit
    return isinstance(obj, DefaultCharacter)


def apply(actor, room, effects, bound=None, world_root=None):
    """
    Apply a list of effect dicts. Main thread only.

    Returns a list of lines describing what visibly happened, for the room to
    be told about.  Effects that cannot be applied are skipped rather than
    aborting the rest -- a half-understood verb should still do the parts it
    got right.
    """
    bound = bound or {}
    announcements = []

    for effect in effects or []:
        try:
            line = _apply_one(actor, room, effect, bound, world_root)
        except Exception as exc:
            logger.log_info(f"verb effect failed ({effect!r}): {exc}")
            continue
        if line:
            announcements.append(line)
    return announcements


def _resolve(effect, key, bound, room, actor):
    """
    Find the object an effect refers to.

    Effects name things by role where possible ("direct", "instrument"), so a
    rule learned for one object applies to another; a plain name is accepted
    as a fallback for things the rule invented itself.
    """
    role = effect.get(key + "_role") or effect.get("role")
    if role:
        if role == "actor":
            return actor
        return bound.get(role)

    name = str(effect.get(key, "")).strip()
    if not name:
        return None
    from commands.look_take_cmds import _find_one

    obj, _ = _find_one(actor, name, location=room)
    if not obj:
        obj, _ = _find_one(actor, name, location=actor)
    return obj


def _apply_one(actor, room, effect, bound, world_root):
    from evennia import create_object

    from typeclasses.objects import Object
    from world import verbs

    etype = str(effect.get("type", "")).strip()

    if etype == "create_object":
        name = str(effect.get("name", "")).strip()
        if not name:
            return None
        location = actor if effect.get("location") == "actor" else room
        obj = create_object(Object, key=name, location=location)
        obj.db.desc = str(effect.get("description", "")).strip()
        obj.db.ai_takeable = bool(effect.get("takeable", True))
        obj.db.is_ai_item = True
        obj.db.affordances = sorted({str(a).lower() for a in effect.get("affordances", [])})
        obj.db.states = sorted({str(s).lower() for s in effect.get("states", [])})
        where = "is now here" if location is room else "is now carried"
        return f"{obj.get_numbered_name(1, None, return_string=True)} {where}."

    if etype == "destroy_object":
        obj = _resolve(effect, "name", bound, room, actor)
        if _protected(obj, room):
            return None
        label = obj.get_numbered_name(1, None, return_string=True)
        obj.delete()
        return f"{label.capitalize()} is gone."

    if etype == "move_object":
        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None or _protected(obj, room):
            return None
        destination = actor if effect.get("to") == "actor" else room
        if obj.move_to(destination, quiet=True):
            label = obj.get_numbered_name(1, None, return_string=True)
            return (f"{actor.get_display_name(actor)} takes {label}." if destination is actor
                    else f"{label.capitalize()} is set down.")
        return None

    if etype == "modify_object":
        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None or _protected(obj, room):
            return None
        changed = False
        if effect.get("new_name"):
            obj.key = str(effect["new_name"]).strip()
            changed = True
        if effect.get("new_description"):
            obj.db.desc = str(effect["new_description"]).strip()
            changed = True
        if effect.get("affordances") is not None:
            obj.db.affordances = sorted(
                {str(a).lower().strip() for a in effect["affordances"] if a}
            )
        if changed:
            # Narrations were written about what this object was. A charred
            # stub is not the candle whose description was cached, so the
            # stored text is dropped and rewritten on next use.
            forget_narrations(obj)
        return None

    if etype == "set_state":
        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None:
            return None
        add, remove = [], []
        for slug in effect.get("add", []):
            add.append(verbs.register_state(world_root, str(slug)))
        for slug in effect.get("remove", []):
            remove.append(str(slug).lower().strip())
        verbs.apply_states(obj, add=add, remove=remove, world_root=world_root)
        return None

    if etype == "modify_room":
        if effect.get("new_description"):
            room.db.desc = str(effect["new_description"]).strip()
        if effect.get("new_name"):
            new_name = str(effect["new_name"]).strip()
            room.key = new_name
            room.db.room_title = new_name
        return None

    if etype == "move_actor":
        direction = str(effect.get("exit", "")).strip()
        if not direction:
            return None
        from commands.look_take_cmds import _find_one

        exit_obj, _ = _find_one(actor, direction, location=room)
        if exit_obj and getattr(exit_obj, "destination", None) is not None:
            exit_obj.at_traverse(actor, exit_obj.destination)
        return None

    return None
