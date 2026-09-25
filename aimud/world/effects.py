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


#: Slots a description may use that are not word lists: they are answered by
#: the renderer itself. See `tokens._slot`.
_BUILTIN_SLOTS = frozenset(["self", "viewer", "user", "here", "world"])


def modify_complaints(obj, new_name="", new_description="", world_root=None,
                      room=None):
    """
    What stops this change being made, as short sentences; [] when nothing
    does.

    Shared by the `modify_object` effect and a character's `modify` tool, so a
    rule and a character cannot differ about what renaming a thing may do --
    and held to what every generator's names and descriptions are held to:

    * A name says what a thing is and never its condition. `broken`, `lit`
      and `half-empty` belong in states, where something can undo them; a
      name carrying one is wrong the moment the condition changes. See
      `verbs.name_contradicts_states`.
    * A description may only ask for word lists this world keeps. A slot
      nothing answers is shown to players as a raw `{smell}`. Checked by
      name and never by rendering, because rendering would keep the choices
      it made on the thing even for a change that is then refused.

    Permission is not asked here. A rule's effect is the result of a verb the
    world already allowed; a character's tool asks `attempt.permitted` itself.
    """
    from world import token_lists, tokens, verbs

    if obj is None:
        return ["there is nothing by that name to change"]
    if _protected(obj, room if room is not None else obj.location):
        return [f"{obj.key} is not something that can be changed"]

    complaints = []
    if new_name:
        wrong = verbs.name_contradicts_states(new_name, verbs.states(obj),
                                              world_root)
        if wrong:
            complaints.append(
                f"a name says what a thing is and not what condition it is "
                f"in, and {', '.join(wrong)} "
                f"{'is a condition' if len(wrong) == 1 else 'are conditions'}")
    if new_description:
        unknown = sorted(
            name for name in token_lists.references(new_description)
            if name not in _BUILTIN_SLOTS
            and name not in tokens._PROVIDED_SLOTS
            and (world_root is None
                 or token_lists.get(world_root, name) is None))
        if unknown:
            complaints.append(
                "the description asks for word lists this world does not "
                "keep: " + ", ".join("{" + name + "}" for name in unknown))
    return complaints


def modify(obj, new_name="", new_description="", affordances=None,
           world_root=None):
    """
    Change what a thing is called, how it looks, or what can be done to it.

    Nothing here refuses: `modify_complaints` is asked first. Answers whether
    anything changed.

    The old name is kept as a name the thing still answers to. Whoever
    remembered "the brass key" should still find it after it has been bent,
    and anything that learned the old name -- a goal, a quest, a character's
    memory -- would otherwise be looking for a thing that has vanished.
    """
    from world import tokens, verbs

    changed = False
    if new_name:
        old = str(obj.key or "")
        obj.key = new_name
        # The aliases its condition earns it spell out its name, so they
        # are stale the moment the name changes.
        verbs.refresh_state_aliases(obj)
        if old and old.lower() != new_name.lower():
            obj.aliases.add(old.lower())
        verbs.adopt_named_states(obj, world_root)
        changed = True
    if new_description:
        obj.db.desc = new_description
        tokens.settle(obj)
        changed = True
    if affordances is not None:
        # An object's affordances come from its kind, and this is the one
        # thing that may overrule them -- because a rule changing what a
        # particular thing can do is a deliberate act rather than drift.
        # Burning one book does not stop books being readable.
        from world import affordances as af

        obj.db.affordances = af.normalise(affordances)
    if changed:
        # Narrations were written about what this object was. A charred stub
        # is not the candle whose description was cached, so the stored text
        # is dropped and rewritten on next use.
        forget_narrations(obj)
    return changed


def _note_states(actor, obj, added, removed, world_root):
    """
    Write what a verb made true, and what it ended, as the world's history.

    A state belongs in a triple, not in anybody's memory of the moment: "the
    candle is now lit" stops being true, and a memory cannot say so, while a
    triple is closed by whatever replaces it. A state in an exclusive group
    supersedes the rest of its group -- lit ends unlit -- and one in no group
    stands beside whatever else is true. Fire-and-forget, and nothing if the
    world keeps no memory.
    """
    from world import memory, verbs

    # A rule that fired because something became true has nobody acting, and
    # the thing it happened to is who the history is about.
    where = memory.where_for(actor if actor is not None else obj, world_root)
    if not where.bank or obj is None:
        return
    for slug in added or ():
        if not slug:
            continue
        group = verbs.group_of(world_root, slug)
        exclusive = bool(group and verbs.group_rules(world_root, group)
                         .get("exclusive"))
        memory.note_triple(where, f"#{obj.id}", group or "is", slug,
                           supersede=exclusive)
    for slug in removed or ():
        if slug:
            memory.end_triples(where, f"#{obj.id}",
                               verbs.group_of(world_root, slug) or "is", slug)


def _protected(obj, room):
    """True for things a verb must never destroy or carry away."""
    from evennia.objects.objects import DefaultCharacter

    if obj is None or obj is room:
        return True
    if getattr(obj, "destination", None) is not None:
        return True  # an exit
    return isinstance(obj, DefaultCharacter)


def apply(actor, room, effects, bound=None, world_root=None, found=None):
    """
    Apply a list of effect dicts. Main thread only.

    Returns a list of lines describing what visibly happened, for the room to
    be told about.  Effects that cannot be applied are skipped rather than
    aborting the rest -- a half-understood verb should still do the parts it
    got right.

    `found` is what this rule's own conditions matched, filed under the names
    they were told to file it under; see `conditions.Context`. Empty for every
    caller with no conditions behind it, and then an effect naming a set finds
    nothing and does nothing, which is what an effect on nobody has always
    done.
    """
    bound = bound or {}
    found = {} if found is None else found
    announcements = []

    # Whatever these change was brought about by whoever is acting, unless a
    # cause is already being carried -- a becomes rule's own, down a chain.
    from world import becoming

    with becoming.caused_by(actor):
        for effect in effects or []:
            try:
                line = _apply_one(actor, room, effect, bound, world_root,
                                  found)
            except Exception as exc:
                logger.log_info(f"verb effect failed ({effect!r}): {exc}")
                continue
            if line:
                announcements.append(line)
    return announcements


#: Roles that mean several people rather than one thing.
#:
#: Every other role names a participant somebody typed -- the thing acted on,
#: the thing used, the person spoken to. There was no way to say "and everyone
#: standing here", so a fire could set the wood burning and could not warm the
#: room, and a shout could not startle anybody who was not named in it.
#:
#: Two, because both are wanted and the difference is not a matter of taste: a
#: fire warms whoever lit it, and a shout does not startle the one shouting.
#:
#: Deliberately confined to `set_state` and `set_trait` below. Destroying or
#: moving everybody present is not a thing a verb should be able to say in one
#: line, and a rule that means it can name them.
PLURAL_ROLES = ("everyone", "others")


def _everyone_in(room, actor, role):
    """The characters a plural role refers to."""
    from world.quests import is_person

    if room is None:
        return []
    found = [obj for obj in room.contents if is_person(obj)]
    if role == "others":
        found = [obj for obj in found if obj is not actor]
    return found


def _open_a_way(actor, room, effect, world_root):
    """
    Make somewhere new: dig a burrow, mine a shaft, build a shelter.

    **Nothing is generated here.** A way out is opened and left *pending*, and
    the room behind it is built by the ordinary generator the first time
    anybody walks through -- the same machinery a world grows by, with the
    same cost at the same moment. That is not a shortcut. Effects run
    synchronously and must stay free: `create_object` builds from a spec the
    rule already holds for exactly this reason, and a room that phoned a model
    while a rule was mid-flight would make every dig cost money whether or not
    anybody went and looked.

    What makes the room the right one is `why`, which becomes the exit's
    `destination_hint` -- the field the room generator already reads to keep a
    door's promise and the room behind it consistent. "Dug out of the packed
    earth with a shovel" and "walled with strut and heat-shield tile" are what
    a world says here, and the generator writes the place they describe.

    The direction is the rule's if it names one, and any free one otherwise.
    A named direction that is *not* free does nothing: digging down when down
    is already a staircase should fail rather than quietly dig sideways, and a
    rule about a shaft means the shaft.
    """
    from world import worldgen

    if room is None or world_root is None:
        return None
    free = worldgen.openable_directions(world_root, room)
    wanted = worldgen.canonical_direction(
        str(effect.get("direction") or "").strip())
    if wanted:
        if wanted not in free:
            return None
        going = wanted
    elif free:
        going = free[0]
    else:
        return None             # walled in on all six sides

    name = str(effect.get("exit") or "").strip() or going
    why = str(effect.get("why") or effect.get("hint") or "").strip()
    way = worldgen._make_exit(_ai_exit(), name, room, room, pending=True,
                              hint=why)
    if way is None:
        return None
    return (f"A way {name} opens from here."
            if name != going else f"A way {going} opens from here.")


def _ai_exit():
    from typeclasses.exits import AIExit

    return AIExit


def _destroy_one(obj, room, world_root):
    """
    Take one thing out of the world for good; answer what it was called.

    Its own function because `destroy_object` may now be given several things
    at once, and the bookkeeping each one needs -- who owned it, that it
    happened, what it was worth to whoever held it -- is the same for the
    first as for the fourth.
    """
    if _protected(obj, room):
        return ""
    label = obj.get_numbered_name(1, None, return_string=True)
    holder = obj.location
    # Whose it was, closed rather than erased. The object is about to stop
    # existing and its attributes with it, but what was recorded of it
    # outlives both -- which is what lets somebody ask after a sword that
    # was theirs and is not there. See world.ownership.forget.
    from world import ownership

    ownership.forget(obj)
    # And that it is gone, as the world's history. Before the deletion,
    # while the world can still be found from where the thing is.
    from world import memory

    memory.note_destroyed(obj, world_root)
    obj.delete()
    # A shattered shield protects nobody. Deletion is not a move, so the
    # hooks that keep gear honest do not fire for it.
    from world import gear

    gear.recompute(holder)
    return label


def _resolve_many(effect, key, bound, room, actor, found=None, crowds=True):
    """
    Everyone or everything an effect refers to, as a list.

    One element for the ordinary case, so callers that used to handle a single
    object handle both by looping. A role naming nobody present gives an empty
    list, and an effect on nobody is simply an effect that does nothing.

    There are two sorts of plural here and they are not the same claim:

    * A **found set** -- a name a condition of this same rule filed what it
      matched under. These are particular things the rule has already counted
      and been satisfied by, so any effect may name one: consuming the two
      lumps of coal a recipe just checked for is the whole point of having
      them, and no second search can disagree with the first.
    * A **crowd** -- `everyone` or `others`, worked out afresh from the room.
      Still confined to `set_state` and `set_trait` by the note above.

    `crowds` is how an effect says it will take the first and not the second.
    A found set is looked for first either way: a rule that named its own set
    means that set, whatever else the word might have meant.
    """
    role = effect.get(key + "_role") or effect.get("role")
    if role and found and role in found:
        return [obj for obj in (found.get(role) or []) if obj is not None]
    if crowds and role in PLURAL_ROLES:
        return _everyone_in(room, actor, role)
    one = _resolve(effect, key, bound, room, actor)
    return [one] if one is not None else []


def _and_then(labels):
    """"a key, a candle and a coil of rope" -- for reading, not for parsing."""
    labels = [str(label) for label in labels if label]
    if len(labels) < 2:
        return labels[0] if labels else ""
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def _put(obj, where, effect, bound, room, actor, world_root=None):
    """
    Put one thing where an effect says, and answer with what the room saw.

    One account of moving something, because two effects need it now:
    `move_object` names a thing and `move_contents` empties one out. The
    destinations are the same for both -- your hands, the floor here, in or on
    something else involved, or another room entirely -- and a bulk move that
    understood any fewer of them would be a second, worse answer to a question
    already settled.
    """
    from world import relations

    if where not in ("actor", "room") and where in bound:
        # In or on something else involved. The case a rule could never say
        # before, and why a verb that meant to put the key in the box used to
        # drop it on the floor instead.
        host = bound[where]
        preposition = str(effect.get("preposition", "")).strip().lower()
        if preposition not in relations.PREPOSITIONS:
            preposition = relations.DEFAULT
        ok, message = relations.place(obj, host, preposition, quiet=True)
        return message if ok else None

    # Another room entirely, named the way a rule can name one: a ship that
    # launches, a letter that is sent, a bin that is emptied somewhere else.
    if where not in ("actor", "room"):
        from world import coords

        elsewhere = coords.room_named(world_root, where)
        if elsewhere is None:
            return None
        if not obj.move_to(elsewhere, quiet=True):
            return None
        relations.displace(obj)
        label = obj.get_numbered_name(1, None, return_string=True)
        return f"{label.capitalize()} is gone."

    destination = actor if where == "actor" else room
    if destination is None:
        return None
    if obj.move_to(destination, quiet=True):
        # It is in a hand or on a floor now, not on or in anything.
        relations.displace(obj)
        label = obj.get_numbered_name(1, None, return_string=True)
        return (f"{actor.get_display_name(actor)} takes {label}."
                if destination is actor else f"{label.capitalize()} is set down.")
    return None


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
    if not name or actor is None:
        # Finding a thing by name is a search made by somebody, and a rule
        # that fired because something became true has nobody to search.
        return None
    from commands.look_take_cmds import _find_one

    obj, _ = _find_one(actor, name, location=room)
    if not obj:
        obj, _ = _find_one(actor, name, location=actor)
    return obj


# ---------------------------------------------------------------------------
# What an effect is, in words
# ---------------------------------------------------------------------------

#: Every effect there is, and what each one means -- the register that makes
#: the vocabulary readable instead of only runnable.
#:
#: `takes` is the prose somebody reads; **`fields` is the same fact in a shape
#: a test can walk**, and it is here because the prose drifted. `create_object`
#: said it took `why`, which nothing has ever read, and said nothing about
#: `kind`, which decides what sort of thing it makes -- so the menu written
#: from it could not say, and every rule that made something got the sort
#: guessed from the head noun of whatever it was called. One list beside the
#: applier, and `tests/test_building.py` fails if a menu cannot reach it.
#:
#: This exists because a world was not examinable. `rules launch` printed what
#: launching *required* and never what it *did*, so the one question a person
#: most wants answered -- what will happen if I type this -- could only be
#: answered by reading the JSON. Three things read this register now: the
#: `effects` command, `help <effect>`, and `suggest.said`, which had grown a
#: third-of-a-renderer of its own with an `else: would: <type>` at the bottom.
#:
#: Kept here, beside `_apply_one`, for the reason `actions.prompt_block` and
#: `affordances.PROMPT` are kept beside what they describe: the sentence and
#: the code have to be able to drift only together. Adding an effect without
#: an entry here is caught by a test.
#:
#: Each entry says:
#:   means      what it does, in one sentence, in the second person
#:   takes      the fields it reads, for somebody writing one by hand
#:   backwards  whether `conditions.achieves` can read it as a goal. An effect
#:              nobody can read backwards is a hole in the planner (11.1), so
#:              a `False` here is a decision on the record rather than a gap
#:   answers    whether its own output is the whole of what the player reads,
#:              so no narration is paid for on top. See SPEAKS_FOR_ITSELF.
VOCABULARY = {
    "set_state": {
        "means": "puts something into a condition, or takes it out of one",
        "takes": 'role, add: [...], remove: [...], '
                 'styles: {state: how it is in it}',
        "fields": ("role", "add", "remove", "styles"),
        "backwards": True, "answers": False,
    },
    "set_trait": {
        "means": "moves a figure kept about a person, at once or over time",
        "takes": 'role, trait, change / set_to, rate',
        "fields": ("role", "trait", "change", "set_to", "rate"),
        "backwards": True, "answers": False,
    },
    "create_object": {
        "means": "brings something into being, here or in your hands",
        # What `clothing.create` actually reads, which is what this makes.
        # It said `why` for a long time, and nothing has ever read that --
        # a register that names a field the applier ignores is the drift it
        # exists to stop, and it cost a builder the one field they wanted:
        # with no `kind`, the sort of thing is guessed from the head noun of
        # whatever it is called.
        "takes": 'name, description, kind, takeable, states, '
                 'trait_bonuses, bonus_when, bonus_while, '
                 'location: "room" | "actor"',
        "fields": ("name", "description", "kind", "takeable", "states",
                   "trait_bonuses", "bonus_when", "bonus_while", "location"),
        "backwards": True, "answers": False,
    },
    "destroy_object": {
        "means": "takes something out of the world for good",
        "takes": "name_role",
        "fields": ("name_role",),
        "backwards": True, "answers": False,
    },
    "move_object": {
        "means": "puts something somewhere else -- your hands, the floor, "
                 "inside or on another thing, or another room entirely",
        "takes": 'name_role, to: "actor" | "room" | <role> | <a room\'s name>, '
                 "preposition",
        "fields": ("name_role", "to", "preposition"),
        "backwards": True, "answers": False,
    },
    "move_contents": {
        "means": "empties something out: everything it holds goes wherever "
                 "one thing would have gone",
        "takes": 'name_role, to: "actor" | "room" | <role> | <a room\'s name>, '
                 'preposition, from: "in" | "on" | "under" | "behind"',
        "fields": ("name_role", "to", "from"),
        "backwards": True, "answers": False,
    },
    "set_owner": {
        "means": "makes something somebody's, or nobody's",
        "takes": 'name_role, to: "actor" | <role> | "nobody", cascade',
        "fields": ("name_role", "to", "cascade"),
        "backwards": True, "answers": False,
    },
    "modify_object": {
        "means": "changes what something is called or what it looks like",
        "takes": "name_role, new_name, new_description, affordances",
        "fields": ("name_role", "new_name", "new_description", "affordances"),
        "backwards": False, "answers": False,
    },
    "modify_room": {
        "means": "changes what this place is called or what it looks like",
        "takes": "new_name, new_description",
        "fields": ("new_name", "new_description"),
        "backwards": False, "answers": False,
    },
    "move_actor": {
        "means": "takes you somewhere, by a way out or by naming the place",
        "takes": 'exit | to: <a room\'s name>',
        "fields": ("exit", "to"),
        "backwards": True, "answers": False,
    },
    "set_exit": {
        "means": "changes where a way out of this room leads",
        "takes": 'exit, to: <a room\'s name>',
        "fields": ("exit", "to"),
        "backwards": True, "answers": False,
    },
    "create_room": {
        "means": "opens a way onto somewhere new -- dug, mined or built -- "
                 "which is made the first time anybody goes through",
        "takes": "direction, exit, why (what the place is and how it came "
                 "to be)",
        # Not readable backwards, and that is a decision rather than a gap. A
        # goal names a room; the room this opens onto has no name until
        # somebody walks into it and the generator writes one, so there is
        # nothing for a planner to aim at. A character wanting to be somewhere
        # new walks through the way, which is `move_actor` and already read.
        "fields": ("direction", "exit", "why"),
        "backwards": False, "answers": False,
    },
    "describe": {
        "means": "shows what something looks like, and changes nothing",
        "takes": "role",
        "fields": ("role",),
        "backwards": False, "answers": True,
    },
    "narrate": {
        "means": "does nothing beyond being seen to happen -- for a verb "
                 "whose whole result is that somebody watched you do it",
        "takes": "nothing",
        "fields": (),
        "backwards": False, "answers": False,
    },
    "try": {
        "means": "means another verb instead, and runs it from the start",
        "takes": "action, roles",
        "fields": ("action", "roles"),
        "backwards": False, "answers": False,
    },
    "set_goal": {
        "means": "gives somebody something to work towards, which they then "
                 "set about on their own",
        "takes": "role, goal: [...]",
        "fields": ("role", "goal"),
        # Nothing is achieved by handing somebody a want: the world is exactly
        # as it was, and a planner reading this backwards would think a verb
        # that sets a goal is a way of reaching it. It is the opposite -- the
        # way of reaching it is whatever the person then does.
        "backwards": False, "answers": False,
    },
    "offer_quest": {
        "means": "asks somebody to run an errand this world has written",
        "takes": "quest, name_role (who asks), role (who is asked)",
        # A goal a planner could aim at is a state of the world; being offered
        # something is a state of a conversation. Nothing to read backwards,
        # and saying so here keeps it off the planner's list of holes.
        "fields": ("quest", "name_role", "role"),
        "backwards": False, "answers": False,
    },
}


def known(etype):
    """What this game knows about an effect type, or {} for one it does not."""
    return dict(VOCABULARY.get(str(etype or "").strip()) or {})


def _role_words(effect, key="name"):
    """How to name whatever an effect is aimed at."""
    from world import conditions

    role = effect.get(key + "_role") or effect.get("role")
    if role:
        return conditions._SUBJECT_WORDS.get(str(role), str(role))
    named = str(effect.get(key) or "").strip()
    return named or "it"


def _listed(values):
    return ", ".join(str(v) for v in (values or []) if v)


def say(effect):
    """
    One effect as a clause somebody can read: "makes what you act on burning".

    Present tense and second person, because every reader of this is being told
    what will happen to them if they type the verb. An effect this game does
    not know is said as itself rather than hidden, which is the whole point of
    a listing somebody is checking.
    """
    try:
        etype = str(effect.get("type") or "").strip()
    except AttributeError:
        return "something unreadable"
    what = _role_words(effect)

    if etype == "set_state":
        added, gone = _listed(effect.get("add")), _listed(effect.get("remove"))
        if added and gone:
            return f"makes {what} {added}, and no longer {gone}"
        if added:
            return f"makes {what} {added}"
        if gone:
            return f"leaves {what} no longer {gone}"
        return f"changes nothing about {what}"

    if etype == "set_trait":
        trait = str(effect.get("trait") or "something").replace("_", " ")
        who = _role_words(effect) if (effect.get("role")
                                      or effect.get("name_role")) else "you"
        parts = []
        if effect.get("set_to") is not None:
            parts.append(f"puts {who} at {effect['set_to']} {trait}")
        change = effect.get("change")
        if change:
            try:
                amount = float(change)
            except (TypeError, ValueError):
                amount = 0
            way = "costs" if amount < 0 else "gains"
            parts.append(f"{way} {who} {abs(amount):g} {trait}")
        rate = effect.get("rate")
        if rate:
            try:
                per = float(rate)
            except (TypeError, ValueError):
                per = 0
            if per:
                way = "drain" if per < 0 else "climb"
                parts.append(f"sets {trait} to {way} by "
                             f"{abs(per):g} a second")
            else:
                parts.append(f"stops {trait} drifting")
        return ", and ".join(parts) or f"changes {who}'s {trait}"

    if etype == "create_object":
        return f"produces {str(effect.get('name') or 'something')}"

    if etype == "destroy_object":
        return f"destroys {what}"

    if etype == "set_owner":
        where = str(effect.get("to") or "actor").strip()
        if where == "nobody":
            return f"leaves {what} belonging to nobody"
        if where == "actor":
            return f"makes {what} yours"
        from world import conditions

        return (f"makes {what} belong to "
                f"{conditions._SUBJECT_WORDS.get(where, where)}")

    if etype == "move_object":
        where = str(effect.get("to") or "room").strip()
        if where == "actor":
            return f"puts {what} in your hands"
        if where == "room":
            return f"sets {what} down here"
        from world import conditions

        if where in conditions.ROLES:
            preposition = str(effect.get("preposition") or "in")
            return (f"puts {what} {preposition} "
                    f"{conditions._SUBJECT_WORDS.get(where, where)}")
        return f"sends {what} to {where}"

    if etype == "move_contents":
        where = str(effect.get("to") or "actor").strip()
        if where == "actor":
            return f"empties {what} into your hands"
        if where == "room":
            return f"empties {what} out onto the floor"
        return f"empties {what} into {where}"

    if etype == "modify_object":
        said = []
        if effect.get("new_name"):
            said.append(f"renames {what} to {effect['new_name']}")
        if effect.get("new_description"):
            said.append(f"changes what {what} looks like")
        if effect.get("affordances") is not None:
            said.append(f"changes what can be done to {what}")
        return ", and ".join(said) or f"changes {what}"

    if etype == "modify_room":
        said = []
        if effect.get("new_name"):
            said.append(f"renames this place to {effect['new_name']}")
        if effect.get("new_description"):
            said.append("changes what this place looks like")
        return ", and ".join(said) or "changes this place"

    if etype == "move_actor":
        if effect.get("exit"):
            return f"takes you {effect['exit']}"
        if effect.get("to"):
            return f"takes you to {effect['to']}"
        return "takes you somewhere"

    if etype == "set_exit":
        way = str(effect.get("exit") or effect.get("name") or "a way out")
        return f"makes {way} lead to {effect.get('to') or 'somewhere else'}"

    if etype == "create_room":
        going = str(effect.get("direction") or "").strip()
        where = f" {going}" if going else ""
        why = str(effect.get("why") or "").strip()
        return (f"opens a way{where} onto somewhere new"
                + (f", {why}" if why else ""))

    if etype == "describe":
        # Not "shows you what {what} looks like": the role words are written
        # as subjects -- "what you act on" -- and that sentence comes out with
        # two whats in it.
        return f"describes {what}"

    if etype == "narrate":
        return "nothing but what you see happen"

    if etype == "try":
        return f"means {effect.get('action') or 'something else'} instead"

    if etype == "set_goal":
        from world import goals as goals_mod

        who = _role_words(effect) if effect.get("role") else "whoever it is"
        wanted = effect.get("goal") or []
        if not wanted:
            return f"gives {who} a purpose"
        return f"sets {who} to {goals_mod.describe(wanted)}"

    if etype == "offer_quest":
        return f"offers {what} the errand {effect.get('quest') or ''}".rstrip()

    return f"does something this game calls {etype or 'nothing'}"


#: Effects whose return value is the whole of what the player should read.
#:
#: Ordinarily an effect's text is an aside broadcast to the room -- "the candle
#: is now lit" beside a narrated sentence somebody paid for. These are not
#: asides: they ARE the answer, they go to whoever acted rather than to the
#: room, and asking a model to narrate on top of one would both cost money and
#: talk over the thing it was asked to describe.
#:
#: This is why `describe` is allowed to be the only effect in the vocabulary
#: that `conditions.achieves` cannot read backwards. Nothing is ever a goal "to
#: have been told something"; what an NPC wants from looking is whatever an
#: `after` rule does next, and that is a `set_trait` or a `set_state` like any
#: other. See docs/rulebooks-from-inform.md 8.1.
SPEAKS_FOR_ITSELF = tuple(sorted(
    name for name, entry in VOCABULARY.items() if entry.get("answers")))


def speaks_for_itself(effects):
    """Whether this rule's own effects are the answer the player reads."""
    for effect in (effects or []):
        try:
            if str(effect.get("type") or "") in SPEAKS_FOR_ITSELF:
                return True
        except AttributeError:
            continue
    return False


def _apply_one(actor, room, effect, bound, world_root, found=None):
    from world import verbs

    etype = str(effect.get("type", "")).strip()

    if etype == "create_object":
        from world import clothing

        location = (actor if effect.get("location") == "actor"
                    and actor is not None else room)
        # Through the clothing layer: a verb that produces a cloak has
        # produced something wearable, not a cloak-shaped prop.
        obj = clothing.create(effect, location=location)
        if obj is None:
            return None
        # Somebody made it, so it is theirs -- whether it landed in their hands
        # or on the floor in front of them. A room furnishing itself comes
        # through `clothing.create` with no actor at all and stays nobody's,
        # which is the difference that matters: a chair that was always in the
        # tavern is not the barman's property.
        from world import ownership

        ownership.claim(actor, obj)
        where = "is now here" if location is room else "is now carried"
        return f"{obj.get_numbered_name(1, None, return_string=True)} {where}."

    if etype == "set_goal":
        # Giving somebody something to work towards, written as a rule.
        #
        # The half a world with no model was missing. A character's goal was
        # reachable three ways and all three needed a model: it set one for
        # itself out of what it said (`npcs._set_goal`), it accepted an
        # errand, or the dialogue model decided. So "ask the apprentice for
        # steam" could be matched by a rule -- `called` sees the word -- and
        # the rule had no way to finish the sentence.
        #
        # Nothing is planned here and nothing is paid for. The goal is a list
        # of conditions the planner already knows how to test and to work
        # backwards from: a world that has settled that combining fire and
        # water makes steam has, in that rule's `create_object`, the step the
        # planner needs -- so "steam exists" is a goal the apprentice can
        # actually get to, and it gets there by combining, in the room, where
        # everybody can see it happen.
        from world import goals as goals_mod

        to = str(effect.get("role") or "direct")
        who = actor if to == "actor" else bound.get(to)
        if who is None:
            return None
        if not getattr(who.db, "is_npc", False):
            # A goal is what the planner works at, and nothing plans for a
            # player. Said in the log rather than silently: a rule that sets
            # a player a goal is a rule whose author meant somebody else.
            logger.log_info(
                f"goals: a rule set a goal on {who.key}, who is not a "
                f"character this world plays -- nothing works at it")
            return None
        if who.db.goal_from_quest:
            # Already promised to somebody. Abandoning that quietly would
            # leave the errand's own bookkeeping pointing at a goal nobody is
            # working at, and the person who asked waiting for ever.
            logger.log_info(
                f"goals: {who.key} was not given a new goal -- still at the "
                f"errand {who.db.goal_from_quest}")
            return None
        wanted = goals_mod.sanitise(effect.get("goal") or [], owner=who)
        if not wanted:
            logger.log_info(
                f"goals: a rule gave {who.key} a goal with nothing testable "
                f"in it: {effect.get('goal')!r}")
            return None
        who.db.goal = wanted
        who.db.goal_stalls = 0
        who.db.goal_waiting = None
        return f"{who.key} sets about it."

    if etype == "offer_quest":
        # Offering is an effect rather than a hook, so *when* an errand is
        # offered is something a world writes as a rule -- on being greeted,
        # on walking in, on being asked a third time -- rather than a
        # behaviour hardcoded in the quest module. It works identically
        # whether a person, a character or a model set it going, which is the
        # standing rule for effects, and it is the whole of what a world with
        # no model needs in order to hand out work.
        from world import quests

        # Who asks and who is asked, and they are two different questions.
        # `name_role` is the giver and defaults to what is being acted on --
        # greeting Hob offers Hob's errand -- because a rule that names only
        # one role means the other one is the actor. Resolved apart rather
        # than through `_resolve`'s single fallback, which would have made
        # both of them the same person and turned the whole effect into a
        # silent no-op.
        to = str(effect.get("role") or "actor")
        taker = actor if to == "actor" else bound.get(to)
        asking = str(effect.get("name_role") or "").strip()
        if asking:
            giver = actor if asking == "actor" else bound.get(asking)
        else:
            giver = bound.get("direct") or bound.get("target")
        record = quests.spec(world_root, effect.get("quest"))
        if record is None:
            logger.log_info(f"quests: a rule offers {effect.get('quest')!r}, "
                            f"which this world does not hold")
            return None
        if taker is None or giver is None or taker is giver:
            logger.log_info(
                f"quests: {record['id']} was not offered -- "
                f"{'nobody to ask' if giver is None else 'nobody to ask it of'}")
            return None
        allowed, _why = quests.available(taker, world_root, record)
        if not allowed:
            return None
        own = next((said for npc, said in quests.givers_of(world_root, record)
                    if npc is giver), "")
        quest = quests.offer_spec(giver, taker, record, description=own)
        if quest is None:
            return None
        return f"{giver.key} asks about {quest['title']}."

    if etype == "describe":
        # The one effect that changes nothing and only says something.
        #
        # Looking has to produce prose, and must not pay a model for it: the
        # appearance is already assembled from the thing as written, the states
        # it is in, and whatever is placed on it. So the carry-out rule for
        # looking returns that, and `attempt` skips the narration call when a
        # rule speaks for itself -- see SPEAKS_FOR_ITSELF below.
        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None:
            return None
        said = obj.return_appearance(actor)
        # The hook a look has always fired. Keeping it means everything hung on
        # being examined -- an NPC noticing, a trap arming -- still happens now
        # that the look arrives through the pipeline instead of the command.
        try:
            obj.at_desc(looker=actor)
        except Exception as exc:
            logger.log_info(f"at_desc failed on {obj}: {exc}")
        return said

    if etype == "narrate":
        # A verb whose whole result is that it was seen: smiling, humming,
        # listening at a door. It changes nothing and says nothing here, and
        # both of those are the point.
        #
        # The gap it closes was measured rather than guessed. `rule_gen`
        # refuses a carry_out rule with no effects, correctly -- a verb that
        # reports success having changed nothing is the silent no-op this whole
        # design exists to end -- so a purely expressive verb had no legal rule
        # at all, was asked about twice, and was given up on. Across the two
        # soak worlds that is `smile`, `nod`, `hum`, `hear`, `feel`, `tap` and
        # `read`, and nine `cannot_say` answers saying so in as many words:
        # "there is no effect available to output text".
        #
        # There is no such effect and there should not be. The report phase --
        # the narration -- already writes what the player and the room read,
        # for every verb, whether or not anything changed. What was missing was
        # a way for a world to SAY that is all that happens, rather than
        # leaving it to be inferred from an empty list. So this is a
        # declaration and not a mechanism, which is why it is one word with no
        # fields and why applying it does nothing.
        #
        # Unlike `describe` it does not speak for itself: there is a narration
        # to pay for here, and it is the whole of the answer.
        return None

    if etype == "destroy_object":
        # Every one of them, which for everything but a found set is exactly
        # one. A recipe consumes the things its own check counted, and says so
        # in one sentence. `crowds=False`: "destroy everybody here" is still
        # not something a verb may say in a line.
        labels = [
            _destroy_one(obj, room, world_root)
            for obj in _resolve_many(effect, "name", bound, room, actor,
                                     found, crowds=False)]
        said = _and_then([label for label in labels if label])
        if not said:
            return None
        return f"{said[0].upper()}{said[1:]} " \
               f"{'are' if len([l for l in labels if l]) > 1 else 'is'} gone."

    if etype == "set_owner":
        # Whose a thing is, which is a fact about it and not a thing anybody
        # can see happen -- so nothing is returned for the room to be told.
        # A world that wants the handing-over narrated narrates the handing
        # over; this is only the record of it.
        from world import ownership

        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None:
            return None
        where = str(effect.get("to", "actor")).strip()
        owner = None
        if where == "actor":
            if actor is None:
                return None      # nobody acting is nobody to own it
            owner = actor
        elif where != "nobody":
            owner = bound.get(where)
            if owner is None:
                return None
        cascade = effect.get("cascade")
        ownership.set_owner(obj, owner,
                            cascade=True if cascade is None else bool(cascade))
        return None

    if etype == "move_object":
        where = str(effect.get("to", "room")).strip()
        moved = [_put(obj, where, effect, bound, room, actor, world_root)
                 for obj in _resolve_many(effect, "name", bound, room, actor,
                                          found, crowds=False)
                 if not _protected(obj, room)]
        return " ".join(line for line in moved if line) or None

    if etype == "move_contents":
        from world import clothing

        # What "loot" needs, and "empty", "unpack", "tip out" and "rob" with
        # it. Three times over two worlds a model was asked what looting a
        # crate does and answered, in as many words, that it could not say:
        # "move all contents of the container to the actor's inventory" was
        # not something the vocabulary could express, because `move_object`
        # names one thing. `cannot_say` is what measured that.
        from world import relations

        host = _resolve(effect, "name", bound, room, actor)
        if host is None:
            return None
        taken = str(effect.get("from") or "").strip().lower()
        holding = relations.contents(
            host, taken if taken in relations.PREPOSITIONS else None)
        # Worn things are on somebody rather than in them, so looting a body
        # takes what it carries and leaves its clothes where they are. A verb
        # that strips somebody is a different rule saying a different thing.
        holding = [obj for obj in holding
                   if not clothing.is_worn(obj)
                   and not _protected(obj, room)]
        if not holding:
            return None

        where = str(effect.get("to", "actor")).strip()
        moved = [obj.get_numbered_name(1, None, return_string=True)
                 for obj in holding
                 if _put(obj, where, effect, bound, room, actor, world_root)]
        if not moved:
            return None
        emptied = host.get_numbered_name(1, None, return_string=True)
        if actor is None:
            return f"{emptied.capitalize()} is emptied: {_and_then(moved)}."
        return (f"{actor.get_display_name(actor)} empties {emptied}: "
                f"{_and_then(moved)}.")

    if etype == "create_room":
        return _open_a_way(actor, room, effect, world_root)

    if etype == "set_exit":
        # Where a way out of here leads. The effect a launching ship needs: its
        # airlock opened onto a landing pad a moment ago and opens onto a dock
        # now, and nothing in the vocabulary could say so -- exits were built by
        # `worldgen` and never touched again.
        #
        # Rooms are named rather than referenced. A dbref means nothing to
        # whoever writes the rule and is wrong the moment a world is rebuilt,
        # so the name a world calls a place is the only thing a rule may use.
        from world import coords

        name = str(effect.get("exit") or effect.get("name") or "").strip()
        if not name:
            return None
        found = [e for e in room.exits
                 if str(e.key or "").strip().lower() == name.lower()
                 or name.lower() in [str(a).lower() for a in (e.aliases.all()
                                                              or [])]]
        if not found:
            return None
        exit_obj = found[0]

        wanted = str(effect.get("to") or "").strip()
        if not wanted:
            return None
        elsewhere = coords.room_named(world_root, wanted)
        if elsewhere is None or elsewhere is room:
            return None
        if exit_obj.destination is elsewhere:
            return None                 # already there; say nothing twice
        exit_obj.destination = elsewhere
        # A way that was waiting to be built no longer is: it leads somewhere
        # real, and generating a second room behind it would strand this one.
        exit_obj.db.pending_generation = False
        return (f"{exit_obj.get_numbered_name(1, None, return_string=True)}"
                f" leads somewhere else now.")

    if etype == "modify_object":
        obj = _resolve(effect, "name", bound, room, actor)
        if obj is None or _protected(obj, room):
            return None
        new_name = str(effect.get("new_name") or "").strip()
        new_description = str(effect.get("new_description") or "").strip()
        complaints = modify_complaints(obj, new_name, new_description,
                                       world_root, room=room)
        if complaints:
            # Refused rather than half-done, and said where somebody reading
            # the log can find it: a rule that tries this every time it runs
            # is a rule worth rewriting.
            logger.log_info(f"effects: {obj.key} not changed: "
                            f"{'; '.join(complaints)}")
            return None
        modify(obj, new_name=new_name, new_description=new_description,
               affordances=effect.get("affordances"), world_root=world_root)
        return None

    if etype == "set_trait":
        # The one effect that acts on a person rather than a thing. `role`
        # names whom -- almost always "actor" -- and `rate` is what makes an
        # effect play out over time instead of all at once: a poison that
        # drains, a skill that goes rusty, a wound that closes.
        from world import traits

        # Named roles are honoured, and a plural one names the room's company
        # -- a shout that costs everyone hearing it their composure. A trait
        # effect with nobody named at all is about whoever acted, which is
        # what it has always meant.
        slug = str(effect.get("trait", "")).strip()
        if not slug:
            return None
        for who in (_resolve_many(effect, "name", bound, room, actor,
                                  found)
                    or [actor]):
            if not traits.has_traits(who):
                continue
            traits.adjust(
                who, slug,
                change=effect.get("change"),
                set_to=effect.get("set_to"),
                rate=effect.get("rate"),
                world_root=world_root,
            )
        # The characters have already been told directly; the room is told
        # only that something about them changed, never the figure itself.
        return None

    if etype == "set_state":
        # A list, because a role may name the room's whole company: lighting a
        # fire makes the wood burn and everybody standing by it warm.
        targets = _resolve_many(effect, "name", bound, room, actor, found)
        if not targets:
            return None
        from world.model_json import listed

        add, remove = [], []
        for slug in listed(effect.get("add")):
            add.append(verbs.register_state(world_root, str(slug)))
        for slug in listed(effect.get("remove")):
            remove.append(str(slug).lower().strip())
        # Nor recorded as history: a derived state is worked out, and
        # `apply_states` refuses to write one, so noting it here would leave
        # memory saying something happened that did not.
        derived = set(verbs.derived_states(world_root))
        add = [slug for slug in add if slug not in derived]
        remove = [slug for slug in remove if slug not in derived]
        from world import kinds

        from world import gear

        # How a thing is in the state it is being put into: "burning low",
        # "held point-down". Applied after, because `apply_states` clears the
        # style of anything it removed and an exclusive group removes as it
        # adds. Anything naming a state of its own is refused by `set_style`
        # and leaves the plain state behind, which is the safe outcome.
        styles = effect.get("styles") or {}
        try:
            styles = {str(k): str(v) for k, v in dict(styles).items()}
        except (TypeError, ValueError):
            styles = {}

        for obj in targets:
            verbs.apply_states(obj, add=add, remove=remove,
                               world_root=world_root)
            for slug, how in styles.items():
                if slug in add:
                    verbs.set_style(obj, slug, how, world_root)
            _note_states(actor, obj, add, remove, world_root)
            # A lamp going out stops lighting whoever holds it, and a fire
            # going out stops warming the room. Only for things whose worth is
            # gated on a state, so the ordinary case costs one lookup.
            if gear.gated_by(obj):
                where = getattr(obj, "location", None)
                if gear.condition(obj) == "present":
                    gear.recompute_room(where)
                elif where is not None:
                    gear.recompute(where)
            # What this sort of thing turns out to get up to. Both halves: a
            # bottle that can be emptied is a bottle that can be full, and a
            # rule written about bottles later should be shown both words
            # rather than left to coin "drained" beside them.
            kinds.note_state(world_root, obj.db.kinds, add + remove)
        return None

    if etype == "modify_room":
        if effect.get("new_description"):
            room.db.desc = str(effect["new_description"]).strip()
            from world import tokens

            tokens.settle(room)
        if effect.get("new_name"):
            new_name = str(effect["new_name"]).strip()
            room.key = new_name
            room.db.room_title = new_name
        return None

    if etype == "move_actor":
        if actor is None:
            return None          # nobody is acting, so nobody is taken anywhere
        direction = str(effect.get("exit", "")).strip()
        if direction:
            from commands.look_take_cmds import _find_one

            exit_obj, _ = _find_one(actor, direction, location=room)
            if exit_obj and getattr(exit_obj, "destination", None) is not None:
                exit_obj.at_traverse(actor, exit_obj.destination)
            return None

        # Or a room by name, which is the half 11.1 said to add "the day a goal
        # about being somewhere is planned wrongly often enough to notice". The
        # soak said it sooner and for a different reason: a world trying to
        # write what reviving means answered `cannot_say` -- "I cannot move the
        # actor to a saved starting location" -- so a world that kills somebody
        # had no way at all to let them up again.
        #
        # Named the way `set_exit` and `move_object` name one, and for the same
        # reason: a dbref means nothing to whoever writes the rule and is wrong
        # the moment a world is rebuilt. A name nothing answers to does nothing
        # at all rather than guessing.
        from world import coords

        wanted = str(effect.get("to") or "").strip()
        if not wanted:
            return None
        elsewhere = coords.room_named(world_root, wanted)
        if elsewhere is None or elsewhere is room:
            return None
        actor.move_to(elsewhere, quiet=False, move_type="teleport")
        return None

    return None


# ---------------------------------------------------------------------------
# The shape of an effect, for a tool's parameters (docs §4.1)
# ---------------------------------------------------------------------------

def schema(ctx=None):
    """
    One effect, as a finish tool's parameters describe it.

    In the conservative dialect: `type` is closed to what this module can
    apply, and every other field is optional, its description saying which
    types use it. What depends on the type is enforced by whoever validates
    the answer, as `rule_gen.validate` does, rather than by `oneOf`, which not
    every provider honours.
    """
    from world import conditions, relations
    from world import toolbox as tb

    world_root = getattr(ctx, "world_root", None)
    known_traits = []
    if world_root is not None:
        from world import traits

        known_traits = sorted(traits.vocabulary(world_root))
    roles = list(conditions.ROLES)
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": sorted(VOCABULARY),
                     "description": "What it does: " + "; ".join(
                         f"{name} {entry['means']}"
                         for name, entry in sorted(VOCABULARY.items()))},
            "role": tb.choice(roles + list(PLURAL_ROLES),
                              "set_state, set_trait: whose state or figure "
                              "changes"),
            "name_role": tb.choice(roles, "destroy_object, move_object, "
                                          "move_contents, modify_object, "
                                          "set_owner: which participant it "
                                          "is about"),
            "name": {"type": "string",
                     "description": "create_object: what the new thing is "
                                    "called"},
            "description": {"type": "string",
                            "description": "create_object: what it looks "
                                           "like, if you want to say; it is "
                                           "worked out otherwise"},
            "why": {"type": "string",
                    "description": "create_object: what it is made for, so "
                                   "what is made fits"},
            "location": {"type": "string", "enum": ["room", "actor"],
                         "description": "create_object: on the floor, or in "
                                        "the hands of whoever acted"},
            "add": {"type": "array", "items": {"type": "string"},
                    "description": "set_state: conditions to put it in"},
            "remove": {"type": "array", "items": {"type": "string"},
                       "description": "set_state: conditions to take away"},
            "trait": tb.choice(known_traits, "set_trait: the figure",
                               ask="list_traits"),
            "change": {"type": "number",
                       "description": "set_trait: how far to move it"},
            "set_to": {"type": "number",
                       "description": "set_trait: where to put it"},
            "rate": {"type": "number",
                     "description": "set_trait: change per second from now "
                                    "on; 0 stops it"},
            "to": {"type": "string",
                   "description": "move_object, move_contents: 'actor', "
                                  "'room', a participant or a room's name; "
                                  "set_owner: 'actor', a participant or "
                                  "'nobody'; set_exit, move_actor: a room's "
                                  "name"},
            "preposition": {"type": "string",
                            "enum": list(relations.PREPOSITIONS),
                            "description": "move_object, move_contents to a "
                                           "participant: how it goes there"},
            "from": {"type": "string",
                     "enum": list(relations.PREPOSITIONS),
                     "description": "move_contents: take only what is in it, "
                                    "on it, under or behind it; leave it out "
                                    "for everything it holds"},
            "exit": {"type": "string",
                     "description": "set_exit, move_actor: which way out"},
            "new_name": {"type": "string",
                         "description": "modify_object, modify_room: what "
                                        "it is called from now on"},
            "new_description": {"type": "string",
                                "description": "modify_object, modify_room: "
                                               "what it looks like from now "
                                               "on"},
            "action": {"type": "string",
                       "description": "try: the verb this means instead"},
            "roles": {"type": "object",
                      "description": "try: the participants for that verb"},
            "cascade": {"type": "boolean",
                        "description": "set_owner: whether what it holds "
                                       "changes hands too"},
            # Read by `offer_quest` and never offered here, so an effect
            # naming an errand could be written by a person and not by a
            # model. A plain identifier, so it costs the schema nothing.
            "quest": {"type": "string",
                      "description": "offer_quest: which errand this world "
                                     "has already written"},
            # `set_goal`'s own field is deliberately absent, and it is the
            # one place in this schema where a field is withheld rather than
            # forgotten. A goal is a list of spelled-out conditions, and this
            # schema is already inside one list of objects inside another:
            # rules, then effects, then goals is three deep, which Google
            # refuses outright on a call that names the tool it must use --
            # the last round of every loop. See
            # `tests/test_schema_portability.py`.
            #
            # So `set_goal` is a person's effect for now. `rule_gen.validate`
            # refuses one that names no goal, which is the only shape a model
            # could write, and says so -- rather than filing a rule that
            # hands somebody an empty purpose and does nothing for ever.
        },
        "required": ["type"],
    }
