"""
Running one verb attempt, for a player or an NPC.

The order here is the whole design. Everything that can be decided without a
model is decided first:

  parse -> bind nouns -> cached rule? -> preconditions -> cached narration?

Only a genuinely new combination reaches a model, and only the parts that are
actually unknown: a world that has learned "read" spends nothing to read the
next readable thing except the words on it, and nothing at all to read the
same thing twice.

Players and NPCs run through this same function, so an NPC that lights a lamp
lights it for everyone rather than claiming to.
"""

from evennia.utils import logger

from world import effects as effects_mod
from world import verb_gen, verbs

#: Effects an NPC may not cause on its own initiative. NPCs act without a
#: player choosing to let them, so the destructive end of the range stays
#: behind a player's decision.
NPC_FORBIDDEN_EFFECTS = frozenset(["modify_room", "move_actor"])


def _world_root(room):
    return room.db.world_root if room else None


def _cached_narration(bound, verb):
    """
    A narration already learned for these exact objects, if any.

    Entries written by the previous command system stored a single "response"
    and were often about the room they were produced in, which is the problem
    this system exists to fix. They are ignored, so the first use of a verb
    regenerates text that travels with the object instead.
    """
    anchor = _anchor(bound)
    if anchor is None:
        return None
    entry = (anchor.db.ai_commands or {}).get(verb)
    if not isinstance(entry, dict) or "actor" not in entry:
        return None
    return entry


def _store_narration(bound, verb, entry):
    anchor = _anchor(bound)
    if anchor is None:
        return
    cache = dict(anchor.db.ai_commands or {})
    cache[verb] = entry
    anchor.db.ai_commands = cache


def _anchor(bound):
    """
    The object a narration belongs to.

    The direct object if there is one, else whatever else was named. Verbs
    with no nouns at all ("smell") have nothing object-specific to say, so
    they are not cached per object.
    """
    if not bound:
        return None
    return bound.get("direct") or next(iter(bound.values()))


def attempt(caller, raw, account, on_message, allow_effects=None):
    """
    Try to perform `raw` as a verb.

    on_message(actor_text, room_text) delivers the result; room_text may be
    empty when nothing was visible from outside.  allow_effects, when given,
    filters which effect types may fire -- NPCs are handed a narrower set.
    """
    room = caller.location
    if room is None:
        return

    parsed = verbs.parse(raw)
    verb = parsed["verb"]
    if not verb:
        return

    bound, unbound = verbs.bind_all(caller, parsed["roles"])

    if unbound:
        # A noun that is not an object yet may still be real -- fixtures live
        # in the room description until something reaches for them.
        _promote(caller, room, account, parsed, bound, unbound,
                 lambda: _with_bindings(caller, room, account, raw, verb, bound,
                                        on_message, allow_effects),
                 on_message)
        return

    _with_bindings(caller, room, account, raw, verb, bound, on_message, allow_effects)


def _promote(caller, room, account, parsed, bound, unbound, resume, on_message):
    """
    Try to turn an unbound noun into a real object.

    The room's description mentions a blackboard; nothing in the database does.
    Rather than refuse the verb or weld its result to this room, the fixture is
    created as a real object, after which the verb behaves exactly as it would
    for anything else.
    """
    role = unbound[0]
    phrase = parsed["roles"][role]

    from world.item_gen import generate_item, validate_object_existence

    def on_valid(_reason):
        generate_item(
            account, room, phrase,
            on_success=lambda item: _promoted(item, role, bound, unbound, resume, on_message),
            on_error=lambda err: on_message(f"|rCould not resolve {phrase}: {err}|n", ""),
        )

    def on_invalid(_reason):
        on_message(f"You see no {phrase} here.", "")

    validate_object_existence(account, room, phrase, on_valid, on_invalid,
                              lambda err: on_message(f"|rError: {err}|n", ""))


def _promoted(item, role, bound, unbound, resume, on_message):
    bound[role] = item
    remaining = unbound[1:]
    if remaining:
        # Only one fixture is conjured per attempt; asking for two things that
        # both need inventing is a sign the parse was wrong.
        on_message(f"You cannot make sense of that here.", "")
        return
    resume()


def _with_bindings(caller, room, account, raw, verb, bound, on_message, allow_effects):
    world_root = _world_root(room)
    key = verbs.rule_key(verb, bound)
    rule = verb_gen.get_rule(world_root, key)

    if rule is not None:
        _with_rule(caller, room, account, raw, verb, bound, rule, on_message,
                   allow_effects, world_root)
        return

    def learned(new_rule):
        verb_gen.store_rule(world_root, key, new_rule)
        _with_rule(caller, room, account, raw, verb, bound, new_rule, on_message,
                   allow_effects, world_root)

    verb_gen.learn_rule(
        account, world_root, verb, bound, caller, raw,
        on_success=learned,
        on_error=lambda err: _release(caller, on_message, f"|r{err}|n"),
    )


def _with_rule(caller, room, account, raw, verb, bound, rule, on_message,
               allow_effects, world_root):
    if not rule.get("valid", True):
        _release(caller, on_message, rule.get("reason") or "You can't do that.")
        return

    complaint = verbs.check(rule.get("requires"), bound, caller)
    if complaint:
        _release(caller, on_message, complaint)
        return

    cached = _cached_narration(bound, verb)
    if cached is not None and not rule.get("repeatable"):
        _release(caller, on_message, cached.get("actor", ""), cached.get("room", ""))
        return

    def _finish(actor_text, room_text):
        _store_narration(bound, verb, {"actor": actor_text, "room": room_text})
        allowed = [
            e for e in rule.get("effects", [])
            if allow_effects is None or e.get("type") in allow_effects
        ]
        extra = effects_mod.apply(caller, room, allowed, bound=bound,
                                  world_root=world_root)
        _release(caller, on_message, actor_text,
                 " ".join([room_text] + extra).strip())

    if cached is not None:
        _finish(cached.get("actor", ""), cached.get("room", ""))
        return

    verb_gen.narrate(
        account, verb, bound, caller, raw,
        on_success=_finish,
        on_error=lambda err: _release(caller, on_message, f"|r{err}|n"),
    )


def _release(caller, on_message, actor_text, room_text=""):
    caller.ndb.attempting = None
    on_message(actor_text, room_text)
