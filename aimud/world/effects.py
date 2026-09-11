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


def _resolve_many(effect, key, bound, room, actor):
    """
    Everyone or everything an effect refers to, as a list.

    One element for the ordinary case, so callers that used to handle a single
    object handle both by looping. A role naming nobody present gives an empty
    list, and an effect on nobody is simply an effect that does nothing.
    """
    role = effect.get(key + "_role") or effect.get("role")
    if role in PLURAL_ROLES:
        return _everyone_in(room, actor, role)
    found = _resolve(effect, key, bound, room, actor)
    return [found] if found is not None else []


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


# ---------------------------------------------------------------------------
# What an effect is, in words
# ---------------------------------------------------------------------------

#: Every effect there is, and what each one means -- the register that makes
#: the vocabulary readable instead of only runnable.
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
        "takes": 'role, add: [...], remove: [...]',
        "backwards": True, "answers": False,
    },
    "set_trait": {
        "means": "moves a figure kept about a person, at once or over time",
        "takes": 'role, trait, change / set_to, rate',
        "backwards": True, "answers": False,
    },
    "create_object": {
        "means": "brings something into being, here or in your hands",
        "takes": 'name, description, location: "room" | "actor"',
        "backwards": True, "answers": False,
    },
    "destroy_object": {
        "means": "takes something out of the world for good",
        "takes": "name_role",
        "backwards": True, "answers": False,
    },
    "move_object": {
        "means": "puts something somewhere else -- your hands, the floor, "
                 "inside or on another thing, or another room entirely",
        "takes": 'name_role, to: "actor" | "room" | <role> | <a room\'s name>, '
                 "preposition",
        "backwards": True, "answers": False,
    },
    "modify_object": {
        "means": "changes what something is called or what it looks like",
        "takes": "name_role, new_name, new_description, affordances",
        "backwards": False, "answers": False,
    },
    "modify_room": {
        "means": "changes what this place is called or what it looks like",
        "takes": "new_name, new_description",
        "backwards": False, "answers": False,
    },
    "move_actor": {
        "means": "takes you somewhere, by a way out or by naming the place",
        "takes": 'exit | to: <a room\'s name>',
        "backwards": True, "answers": False,
    },
    "set_exit": {
        "means": "changes where a way out of this room leads",
        "takes": 'exit, to: <a room\'s name>',
        "backwards": True, "answers": False,
    },
    "describe": {
        "means": "shows what something looks like, and changes nothing",
        "takes": "role",
        "backwards": False, "answers": True,
    },
    "narrate": {
        "means": "does nothing beyond being seen to happen -- for a verb "
                 "whose whole result is that somebody watched you do it",
        "takes": "nothing",
        "backwards": False, "answers": False,
    },
    "try": {
        "means": "means another verb instead, and runs it from the start",
        "takes": "action, roles",
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

    if etype == "describe":
        # Not "shows you what {what} looks like": the role words are written
        # as subjects -- "what you act on" -- and that sentence comes out with
        # two whats in it.
        return f"describes {what}"

    if etype == "narrate":
        return "nothing but what you see happen"

    if etype == "try":
        return f"means {effect.get('action') or 'something else'} instead"

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

        # Another room entirely, named the way a rule can name one. Until now
        # `to` reached the actor, this room, or a role -- never a different
        # place -- so a ship that launched could not put anything anywhere, and
        # nor could a verb that sent a letter or emptied a bin.
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
        if obj.move_to(destination, quiet=True):
            # It is in a hand or on a floor now, not on or in anything.
            relations.displace(obj)
            label = obj.get_numbered_name(1, None, return_string=True)
            return (f"{actor.get_display_name(actor)} takes {label}." if destination is actor
                    else f"{label.capitalize()} is set down.")
        return None

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

        # Named roles are honoured, and a plural one names the room's company
        # -- a shout that costs everyone hearing it their composure. A trait
        # effect with nobody named at all is about whoever acted, which is
        # what it has always meant.
        slug = str(effect.get("trait", "")).strip()
        if not slug:
            return None
        for who in (_resolve_many(effect, "name", bound, room, actor)
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
        targets = _resolve_many(effect, "name", bound, room, actor)
        if not targets:
            return None
        add, remove = [], []
        for slug in effect.get("add", []):
            add.append(verbs.register_state(world_root, str(slug)))
        for slug in effect.get("remove", []):
            remove.append(str(slug).lower().strip())
        from world import kinds

        from world import gear

        for obj in targets:
            verbs.apply_states(obj, add=add, remove=remove,
                               world_root=world_root)
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
        if effect.get("new_name"):
            new_name = str(effect["new_name"]).strip()
            room.key = new_name
            room.db.room_title = new_name
        return None

    if etype == "move_actor":
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
