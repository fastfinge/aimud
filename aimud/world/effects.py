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
    from world import verbs

    etype = str(effect.get("type", "")).strip()

    if etype == "create_object":
        from world import clothing

        location = actor if effect.get("location") == "actor" else room
        # Through the clothing layer: a verb that produces a cloak has
        # produced something wearable, not a cloak-shaped prop.
        obj = clothing.create(effect, location=location)
        if obj is None:
            return None
        where = "is now here" if location is room else "is now carried"
        return f"{obj.get_numbered_name(1, None, return_string=True)} {where}."

    if etype == "destroy_object":
        obj = _resolve(effect, "name", bound, room, actor)
        if _protected(obj, room):
            return None
        label = obj.get_numbered_name(1, None, return_string=True)
        holder = obj.location
        obj.delete()
        # A shattered shield protects nobody. Deletion is not a move, so the
        # hooks that keep gear honest do not fire for it.
        from world import gear

        gear.recompute(holder)
        return f"{label.capitalize()} is gone."

    if etype == "move_object":
        from world import relations

        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None or _protected(obj, room):
            return None

        # "to" is the actor, the room, or the role of something to put it in
        # or on. That last case is the one a rule could never say before, and
        # is why a verb that meant to put the key in the box used to drop it
        # on the floor instead.
        where = str(effect.get("to", "room")).strip()
        if where not in ("actor", "room") and where in bound:
            host = bound[where]
            preposition = str(effect.get("preposition", "")).strip().lower()
            if preposition not in relations.PREPOSITIONS:
                preposition = relations.DEFAULT
            ok, message = relations.place(obj, host, preposition, quiet=True)
            return message if ok else None

        destination = actor if where == "actor" else room
        if obj.move_to(destination, quiet=True):
            # It is in a hand or on a floor now, not on or in anything.
            relations.displace(obj)
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
            # An object's affordances come from its kind, and this is the one
            # thing that may overrule them -- because a rule changing what a
            # particular thing can do is a deliberate act rather than drift.
            # Burning one book does not stop books being readable.
            from world import affordances as af

            obj.db.affordances = af.normalise(effect["affordances"])
        if effect.get("new_name"):
            # The aliases its condition earns it spell out its name, so they
            # are stale the moment the name changes.
            verbs.refresh_state_aliases(obj)
        if changed:
            # Narrations were written about what this object was. A charred
            # stub is not the candle whose description was cached, so the
            # stored text is dropped and rewritten on next use.
            forget_narrations(obj)
        return None

    if etype == "set_trait":
        # The one effect that acts on a person rather than a thing. `role`
        # names whom -- almost always "actor" -- and `rate` is what makes an
        # effect play out over time instead of all at once: a poison that
        # drains, a skill that goes rusty, a wound that closes.
        from world import traits

        # Named roles are honoured, but a trait effect with nobody named is
        # about whoever acted -- that is what it always means.
        who = _resolve(effect, "name", bound, room, actor) or actor
        if not traits.has_traits(who):
            return None
        slug = str(effect.get("trait", "")).strip()
        if not slug:
            return None
        outcome = traits.adjust(
            who, slug,
            change=effect.get("change"),
            set_to=effect.get("set_to"),
            rate=effect.get("rate"),
            world_root=world_root,
        )
        if outcome is None:
            return None
        # The character has already been told directly; the room is told only
        # that something about them changed, never the figure itself.
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
        # What this sort of thing turns out to get up to. Both halves: a
        # bottle that can be emptied is a bottle that can be full, and a rule
        # written about bottles later should be shown both words rather than
        # left to coin "drained" beside them.
        from world import kinds

        kinds.note_state(world_root, obj.db.kinds, add + remove)
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
