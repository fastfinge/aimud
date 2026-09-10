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

from world import checks
from world import effects as effects_mod
from world import verb_gen, verbs

#: Effects an NPC may not cause on its own initiative. NPCs act without a
#: player choosing to let them, so the destructive end of the range stays
#: behind a player's decision.
NPC_FORBIDDEN_EFFECTS = frozenset(["modify_room", "move_actor"])


def _hits_everyone(effect):
    """
    Whether an effect is aimed at the room's whole company rather than at one
    named participant.

    Held to the same line as `modify_room` and `move_actor`, and for the same
    reason: a character acts without anybody choosing to let it, so the wide
    end of what a verb can do stays behind a player's decision. One NPC
    deciding to alarm everybody present is a different kind of event from one
    NPC opening a door, however reasonable the rule that says so.
    """
    from world import effects as effects_mod

    try:
        role = effect.get("role") or effect.get("name_role")
    except AttributeError:
        return False
    return role in effects_mod.PLURAL_ROLES


def _world_root(room):
    return room.db.world_root if room else None


def _cached_narration(bound, verb, outcome="success"):
    """
    A narration already learned for these exact objects, if any.

    Kept per outcome as well as per verb, because a contested verb has more
    than one thing to say about the same object: the first time somebody
    misses their swing must not become the text everybody sees when they land
    it. That also keeps a contest affordable -- four narrations per object and
    verb at the very most, however many times it is attempted.

    Entries written by the previous command system stored a single "response"
    and were often about the room they were produced in, which is the problem
    this system exists to fix. They are ignored, so the first use of a verb
    regenerates text that travels with the object instead.
    """
    anchor = _anchor(bound)
    if anchor is None:
        return None
    entry = (anchor.db.ai_commands or {}).get(verb)
    if entry is None:
        return None
    # Attributes come back as Evennia _SaverDict, which is a MutableMapping
    # and NOT a dict subclass -- an isinstance(entry, dict) test here rejects
    # every stored entry and silently defeats the whole cache.
    try:
        inner = entry.get(outcome)
    except AttributeError:
        return None      # a plain string from the old command system
    if inner is None:
        # Written before outcomes existed: one entry, describing the verb
        # working. That is the success text and it is not any of the others.
        inner = entry if outcome == "success" else None
    if inner is None:
        return None
    try:
        actor_text = inner.get("actor")
        room_text = inner.get("room", "")
    except AttributeError:
        return None
    if not actor_text:
        return None
    return {"actor": actor_text, "room": room_text or ""}


def _store_narration(bound, verb, outcome, entry):
    anchor = _anchor(bound)
    if anchor is None:
        return
    cache = dict(anchor.db.ai_commands or {})

    # Only entries already keyed by outcome are carried over. A single old
    # entry cannot be told apart from the outcome it described, so it is let
    # go and written again on the next success rather than filed under a
    # result it may never have been about.
    by_outcome = {}
    existing = cache.get(verb)
    try:
        items = list(existing.items())
    except AttributeError:
        items = []
    for name, value in items:
        if name in checks.OUTCOMES and hasattr(value, "get"):
            by_outcome[name] = dict(value)

    by_outcome[outcome] = entry
    cache[verb] = by_outcome
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


def attempt(caller, raw, account, on_message, allow_effects=None, on_wait=None,
            allow_promote=True, fuzzy=False):
    """
    Try to perform `raw` as a verb.

    on_message(actor_text, room_text) delivers the result; room_text may be
    empty when nothing was visible from outside.  allow_effects, when given,
    filters which effect types may fire -- NPCs are handed a narrower set.

    on_wait() is called at most once, and only if the attempt is about to go
    to a model, so a cached verb answers instantly with no spurious 'please
    wait' and a slow one does not look like the game ignored the player.

    allow_promote decides whether a noun that matches nothing may be conjured
    out of the room's description.

    fuzzy loosens noun binding, so a name that merely resembles something
    already here counts as that thing. NPCs use it: they name things from
    memory in their own words, and should reuse the fixture on the wall rather
    than add another beside it.
    """
    room = caller.location
    if room is None:
        return

    parsed = verbs.parse(raw)
    verb = parsed["verb"]
    if not verb:
        return

    # Some states stop their holder doing anything at all. Asked here because
    # this is the one road every action takes, a player's and a character's
    # alike, so a dead thing stops acting without any rule having to say so
    # and without every verb ever learned having to remember it.
    refusal = verbs.refuse(caller, "prevents_acting", _world_root(room))
    if refusal:
        on_message(refusal, "")
        return

    if verb == "follow":
        # Standing arrangements are not verbs. Without this an NPC asking to
        # follow someone would have the world learn a "follow" rule, which can
        # only describe the moment it was used and not the arrangement.
        _follow(caller, parsed, on_message)
        return

    # "Eat all" is not one action on a strange object called "all", it is as
    # many ordinary actions as there are things to eat. Expanded here, before
    # anything binds, so everything downstream sees only single objects and
    # keeps its one anchor, one check and one cached narration apiece.
    from world import bulk

    spread = bulk.expand(caller, verb, parsed["roles"])
    if spread:
        _in_turn(caller, account, spread, on_message, allow_effects, on_wait,
                 fuzzy)
        return

    bound, unbound = verbs.bind_all(caller, parsed["roles"], fuzzy=fuzzy)
    waiter = _once(on_wait)

    # Wearing is a mechanic, not something a world has to work out. Caught
    # here, before any of the learning machinery, so a player's `wear` command
    # and an NPC deciding to put its coat on reach the same code and the same
    # limits -- and so no world ever invents its own private meaning for it.
    # `handle` declines anything that is not really about clothes, and those
    # go on through the ordinary pipeline.
    from world import clothing, gear, relations

    if clothing.handle(caller, verb, bound, on_message):
        return

    # Taking a thing in hand is a mechanic for exactly the reasons wearing is,
    # and the generators have been calling things "wieldable" since before
    # anything could be wielded. `handle` declines anything that is not really
    # about wielding -- "draw the curtain" -- and those go on to the model.
    if gear.handle(caller, verb, bound, on_message):
        return

    # Putting a thing in, on, under or behind another thing is a mechanic for
    # the same reason wearing is: every one of those words means exactly one
    # thing and the game already knows what. `handle` declines anything that
    # is not really a placement -- "put out the fire" -- and those go on to
    # the ordinary pipeline.
    if relations.handle(caller, verb, parsed, bound, on_message):
        return

    if unbound:
        if not allow_promote:
            # Nothing here resembles what was asked for, and this caller may
            # not invent it. Silent: groping for a thing that does not exist
            # is not worth announcing, and it cost nothing.
            logger.log_info(
                f"{caller.key} attempted {raw!r} but nothing matched "
                f"{[parsed['roles'][r] for r in unbound]}"
            )
            on_message("", "")
            return
        # A noun that is not an object yet may still be real -- fixtures live
        # in the room description until something reaches for them.
        waiter()
        _promote(caller, room, account, parsed, bound, unbound,
                 lambda: _with_bindings(caller, room, account, raw, verb, bound,
                                        on_message, allow_effects, waiter),
                 on_message, fuzzy=fuzzy)
        return

    _with_bindings(caller, room, account, raw, verb, bound, on_message,
                   allow_effects, waiter)


def _in_turn(caller, account, spread, on_message, allow_effects, on_wait,
             fuzzy):
    """
    Run an expanded bulk command one action at a time, then say what happened.

    One at a time and not all at once, which matters for more than tidiness.
    These are network round trips, and a dozen launched together would land in
    whatever order they finished, so the room would hear about the last bottle
    before the first. Worse, they would each decide what to do against a world
    the others had not changed yet -- drinking the last of something twice.

    Nothing is conjured during a bulk action. The names came from things that
    are already here, so a miss means the thing went away while we worked
    through the list, and inventing a replacement for it would be absurd.
    """
    told, results = _once(on_wait), []

    def step(remaining):
        if not remaining:
            _report(caller, on_message, results)
            return
        obj, command = remaining[0]

        def collected(actor_text, room_text=""):
            if actor_text:
                results.append((obj, actor_text, room_text))
            step(remaining[1:])

        if obj.pk is None:
            step(remaining[1:])      # consumed by an earlier step
            return
        attempt(caller, command, account, collected,
                allow_effects=allow_effects, on_wait=told,
                allow_promote=False, fuzzy=fuzzy)

    step(list(spread))


def _report(caller, on_message, results):
    """
    What a bulk action comes to, as one answer rather than a dozen.

    The lines are kept whole rather than summarised. A world writes them one
    per object and they are the interesting part -- collapsing twelve into
    "you eat everything" throws away what the game just spent its time
    saying. What is collapsed is the framing: one message, in order, instead
    of a dozen arriving separately with the prompt between them.
    """
    if not results:
        on_message("There is nothing here to do that to.", "")
        return
    actor_text = "\n".join(text for _obj, text, _room in results)
    room_text = " ".join(text for _obj, _actor, text in results if text)
    on_message(actor_text, room_text)


def _follow(caller, parsed, on_message):
    """Start or stop following, for whoever asked -- player or NPC."""
    from commands.follow_cmds import _find_person
    from world.following import follow, unfollow

    wanted = (parsed["roles"].get("direct")
              or parsed["roles"].get("target") or "").strip()
    if not wanted:
        on_message(unfollow(caller), "")
        return

    target = _find_person(caller, wanted)
    if target is None:
        on_message(f"You see no {wanted} here.", "")
        return

    started, message = follow(caller, target)
    room_text = ""
    if started:
        room_text = (f"{caller.get_display_name(caller)} begins following "
                     f"{target.get_display_name(caller)}.")
    on_message(message, room_text)


def _promote(caller, room, account, parsed, bound, unbound, resume, on_message,
             fuzzy=False):
    """
    Try to turn an unbound noun into a real object.

    The room's description mentions a blackboard; nothing in the database does.
    Rather than refuse the verb or weld its result to this room, the fixture is
    created as a real object, after which the verb behaves exactly as it would
    for anything else.

    The making itself is item_gen.conjure, which is also how a character that
    sets out to produce something gets there. One pipeline and one set of
    guards, whichever end it is entered from.
    """
    from world.item_gen import conjure

    role = unbound[0]

    def ready(obj, created):
        bound[role] = obj
        remaining = unbound[1:]
        if not remaining:
            resume()
            return
        if created:
            # Only one fixture is conjured per attempt; asking for two things
            # that both need inventing is a sign the parse was wrong.
            on_message("You cannot make sense of that here.", "")
            return
        # Finding something that was already there costs nothing, so the next
        # noun still gets its turn -- and gets the near-name check too, which
        # it did not when this walked the roles itself.
        _promote(caller, room, account, parsed, bound, remaining, resume,
                 on_message, fuzzy=fuzzy)

    conjure(caller, room, account, parsed["roles"][role], ready,
            lambda message: on_message(message, ""), fuzzy=fuzzy)

def _busy(obj, verb):
    """True if this verb is already in flight against this object."""
    return verb in (obj.ndb.busy_verbs or set())


def _hold(obj, verb):
    busy = set(obj.ndb.busy_verbs or set())
    busy.add(verb)
    obj.ndb.busy_verbs = busy


def _drop(obj, verb):
    busy = set(obj.ndb.busy_verbs or set())
    busy.discard(verb)
    obj.ndb.busy_verbs = busy


def _once(callback):
    """Wrap a callback so it fires at most once, and tolerates None."""
    fired = []

    def call():
        if callback is None or fired:
            return
        fired.append(True)
        callback()

    return call


def _with_bindings(caller, room, account, raw, verb, bound, on_message,
                   allow_effects, waiter=None):
    world_root = _world_root(room)

    # A verb the game already answers is never learned, however it got here.
    #
    # Players cannot reach this: their `get` is caught by the command set long
    # before an attempt is made. Characters can, because they act by calling
    # this function directly with a sentence rather than by typing into a
    # command set -- so an NPC deciding to fetch a bucket walked straight past
    # the engine and taught its world what "get" means. That was 137 rules
    # across five worlds, a fifth of everything they had learned, for ten
    # verbs the game answers for itself: `get` alone had seventy-six.
    #
    # Handed to the command set rather than refused, so the NPC actually picks
    # the bucket up. Anything the engine declines it declines in its own
    # words, which is the right answer and costs nothing.
    if verb in verbs.engine_verbs():
        caller.execute_cmd(raw)
        on_message("", "")
        return

    # Learning a rule and writing a narration are network round trips, and the
    # effects land only once they return. Without a hold on the object itself,
    # two people pulling the same lever in that window both apply its effects.
    # The lock is per object AND verb, so one person reading a notice does not
    # stop another burning it.
    anchor = _anchor(bound)
    if anchor is not None:
        if _busy(anchor, verb):
            on_message("Someone else is already doing that.", "")
            return
        _hold(anchor, verb)

    def release(actor_text, room_text=""):
        if anchor is not None:
            _drop(anchor, verb)
        _release(caller, on_message, actor_text, room_text)

    waiter = waiter or _once(None)
    key = verbs.rule_key(verb, bound)
    rule = verb_gen.get_rule(world_root, key)

    def with_rule(known_rule):
        """Once the verb's meaning is settled, ask whether this sort admits it."""
        _admitted(caller, room, account, raw, verb, bound, known_rule,
                  release, allow_effects, world_root, waiter)

    if rule is not None:
        with_rule(rule)
        return

    def learned(new_rule):
        verb_gen.store_rule(world_root, key, new_rule)
        with_rule(new_rule)

    waiter()
    verb_gen.learn_rule(
        account, world_root, verb, bound, caller, raw,
        on_success=learned,
        on_error=lambda err: release(f"|r{err}|n"),
    )


def _admitted(caller, room, account, raw, verb, bound, rule, release,
              allow_effects, world_root, waiter):
    """
    Whether this sort of thing can be verbed at all, and then get on with it.

    The question the old design answered by inventing a whole rule. An object
    that said nothing about the verb being tried used to buy another copy of
    what the verb means -- 86% of every rule five worlds had learned came from
    exactly that silence, and none of it was about the verb.

    So the silence is filled in where it belongs: one bit, on the kind, true
    for every bottle the world will ever hold. A no ends the attempt here,
    without a rule, a roll or a narration.
    """
    from world import kinds

    anchor = _anchor(bound)
    obj_kinds = list(getattr(anchor.db, "kinds", None) or []) if anchor else []

    def proceed():
        _with_rule(caller, room, account, raw, verb, bound, rule, release,
                   allow_effects, world_root, waiter)

    def refuse():
        name = (anchor.get_numbered_name(1, None, return_string=True)
                if anchor is not None else "that")
        release(f"You cannot {verb} {name}.")

    if not obj_kinds:
        proceed()            # nothing to ask about; the rule's own checks stand
        return

    settled = kinds.admits(world_root, obj_kinds, verb)
    if settled is True:
        proceed()
        return
    if settled is False:
        refuse()
        return

    def answered(allowed, _reason):
        kinds.admit(world_root, obj_kinds, verb, allowed)
        proceed() if allowed else refuse()

    waiter()
    verb_gen.ask_admission(
        account, world_root, verb, rule, obj_kinds[0],
        on_answer=answered,
        on_error=lambda err: release(f"|r{err}|n"),
    )


def _specifics_of(bound, verb):
    """What was learned about this verb on these particular objects, if any."""
    anchor = _anchor(bound)
    if anchor is None:
        return {}
    try:
        return dict((anchor.db.verb_specifics or {}).get(verb) or {})
    except (AttributeError, TypeError, ValueError):
        return {}


def _store_specifics(bound, verb, specifics):
    """
    Keep what this object does under this verb, beside its narration.

    Written once, the first time the verb reaches this object, and only where
    the object actually differs -- an empty answer is stored as an empty
    answer so the question is not asked twice.
    """
    anchor = _anchor(bound)
    if anchor is None:
        return
    store = dict(anchor.db.verb_specifics or {})
    if verb in store:
        return
    store[verb] = dict(specifics or {})
    anchor.db.verb_specifics = store


def _with_specifics(rule, bound, verb):
    """
    The rule as it applies to these objects.

    A shallow overlay and nothing cleverer: this object's own effects replace
    the rule's, and its difficulty replaces the rule's, and everything else --
    what the verb requires, whether it is contested at all, whether it repeats
    -- stays the verb's business. The rule decides that prying is a strength
    contest; the crate decides that this one is a 12.
    """
    specifics = _specifics_of(bound, verb)
    if not specifics:
        return rule

    merged = dict(rule)
    if specifics.get("effects") is not None:
        merged["effects"] = specifics["effects"]
    if specifics.get("difficulty"):
        contest = dict(merged.get("check") or {})
        if contest:
            contest["difficulty"] = specifics["difficulty"]
            # A fixed number and an opposed trait are two different contests,
            # and a thing cannot be both. Naming a difficulty for this object
            # settles it as the first.
            contest.pop("against", None)
            merged["check"] = contest
    return merged


def _with_rule(caller, room, account, raw, verb, bound, rule, release,
               allow_effects, world_root, waiter=None):
    if not rule.get("valid", True):
        release(rule.get("reason") or "You can't do that.")
        return

    complaint = verbs.check(rule.get("requires"), bound, caller,
                            world_root=world_root)
    if complaint:
        release(complaint)
        return

    # What this particular thing does, and how hard it is on this particular
    # thing. The rule says what the verb means for everything of its sort; the
    # specifics say how this door differs from that door, and were written by
    # the same call that wrote what the player reads. Absent for almost
    # everything, which means the rule's own answer stands.
    rule = _with_specifics(rule, bound, verb)

    # Preconditions say whether the attempt was allowed; the check says
    # whether it worked. That order is the whole point: you are told you have
    # no key before anything is rolled, and told you fumbled the lock only
    # once the attempt was a real one.
    contest = checks.wanted(rule)
    result = (checks.resolve(caller, contest, bound, world_root)
              if contest else None)
    outcome = result["outcome"] if result else "success"

    cached = _cached_narration(bound, verb, outcome)
    # A contested verb always runs its effects again: the player swung again,
    # and this time it landed. Only a verb with a settled, single outcome may
    # answer from the cache without touching the world.
    if cached is not None and result is None and not rule.get("repeatable"):
        # What is cached is the template, so the room line still names its
        # actor as {actor} and has to be filled in here too -- broadcasting it
        # raw hands a stray format placeholder to msg_contents.
        release(cached.get("actor", ""),
                _for_room(cached.get("room", ""), caller, raw))
        return

    def _finish(actor_text, room_text, specifics=None):
        # The template is cached, not the finished line: the room text names
        # the actor as {actor}, so the same narration reads correctly when
        # somebody else does the same thing to the same object later.
        _store_narration(bound, verb, outcome,
                         {"actor": actor_text, "room": room_text})
        # Whatever the same reply said this thing does differently, kept
        # beside it. Stored even when empty, so a thing that turned out to be
        # perfectly ordinary is not asked about a second time.
        if specifics is not None:
            _store_specifics(bound, verb, specifics)
        effective = _with_specifics(rule, bound, verb)
        allowed = [
            e for e in checks.effects_for(effective, outcome)
            if (allow_effects is None or e.get("type") in allow_effects)
            and not (allow_effects is not None and _hits_everyone(e))
        ]
        extra = effects_mod.apply(caller, room, allowed, bound=bound,
                                  world_root=world_root)
        spoken = _for_room(room_text, caller, raw)
        visible = " ".join([spoken] + extra).strip()
        _remember(caller, raw, bound, actor_text, extra, outcome=outcome,
                  contested=result is not None)
        release(actor_text, visible)
        # The world just changed under everyone here, which is exactly when a
        # quest may have quietly become finished.
        from world.quests import review_room
        review_room(room)

    if cached is not None:
        _finish(cached.get("actor", ""), cached.get("room", ""))
        return

    if waiter:
        waiter()
    verb_gen.narrate(
        account, verb, bound, caller, raw,
        on_success=_finish,
        on_error=lambda err: release(f"|r{err}|n"),
        result=result,
    )


def _for_room(template, actor, raw):
    """
    The third-person line the room sees, with the actor filled in.

    The narration names whoever acted as the literal {actor}, so the right
    name appears whoever it turns out to be -- and a cached narration stays
    true when a different character repeats the action. A model that returns
    nothing, or a bare fragment with no subject, is repaired here rather than
    broadcast as "lights the candle." with nobody attached to it.
    """
    name = actor.get_display_name(actor)
    text = (template or "").strip()
    if not text:
        return ""
    if "{actor}" in text:
        return text.replace("{actor}", name)
    # A fragment starting with a verb: give it its subject back.
    if text[:1].islower():
        return f"{name} {text}"
    return text


def _remember(caller, raw, bound, actor_text, changes, outcome="success",
              contested=False):
    """
    Record what the character did, and what it changed.

    Goes into the actor's own bank whether or not anyone saw it: reading a
    letter alone in a room is still something you did, and "remember what did
    the notice say?" should find it. What other people in the room remember
    comes through the normal witnessing path, which only carries what was
    actually visible.
    """
    from world.memory import remember

    what = ", ".join(sorted(bound[r].key for r in bound)) or None
    line = f"I tried to: {raw}" if contested else f"I did: {raw}"
    if what:
        line += f" (involving {what})"
    # A failure is a thing that happened to you and worth remembering as one:
    # an NPC beaten off twice should know it before trying a third time, and
    # "I did: attack the guard" on its own reads as a victory.
    if contested:
        line += (" and succeeded" if outcome in checks.GOOD
                 else " and failed")
    if actor_text:
        line += f" — {actor_text}"
    if changes:
        line += " " + " ".join(changes)
    remember(caller, line, kind="did", importance=0.65)


def _release(caller, on_message, actor_text, room_text=""):
    caller.ndb.attempting = None
    on_message(actor_text, room_text)
