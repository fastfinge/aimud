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
from world import counters, verb_gen, verbs

#: How many times one verb may become another before the world gives up. A
#: redirect is a rule sending an action somewhere else, and two rules can send
#: it back and forth -- so the chain is capped rather than trusted. Two is
#: enough for the case this exists for: `launch` becomes launching the ship,
#: and nothing sensible needs a third hop.
MAX_REDIRECTS = 2

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


def _cached_narration(bound, verb, outcome="success", actor=None):
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
    anchor = _anchor(bound, actor)
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


def _store_narration(bound, verb, outcome, entry, actor=None):
    anchor = _anchor(bound, actor)
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


def _anchor(bound, actor=None):
    """
    The thing a narration belongs to.

    The direct object if there is one, else whatever else was named -- so
    "smile at Rina" is stored on Rina, and the next person to smile at her is
    answered for nothing.

    A verb that named nothing at all is stored on whoever did it. That looks
    like a special case and is the ordinary rule applied honestly: the part
    that is specific goes on the specific thing, and when somebody laughs the
    only specific thing in the sentence is them. Without it "laugh" was
    written again every single time it was typed, for ever, because there was
    nowhere to put the answer.

    Whose laugh it is matters, too. Stored per character rather than per
    world, so Rina's laugh is not the innkeeper's -- which is the same reason
    a narration is stored per object rather than per kind.
    """
    if not bound:
        return actor
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

    # Some states stop their holder doing anything at all. That used to be a
    # guard here, because there was nowhere for a rule about every verb to
    # live. There is now: "you must be able to act" is a world-scope check
    # rule with no action, seeded into every world, and it runs in the check
    # phase with everything else -- where it can be read in `rules`, and where
    # a world can add its own beside it.

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
                   allow_effects, waiter=None, redirects=0):
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
    #
    # Only what the command set will actually recognise, and under the name it
    # knows. A verb is folded before it gets here -- "study" arrives as "look"
    # -- so handing back the words the player typed hands back "study scroll",
    # which is not a command, which comes round to this pipeline again, which
    # hands it back again. The rest of `engine_verbs` is handled inside this
    # pipeline by clothing, gear and placement, and those have already had
    # their say by now: reaching here means they declined, and passing their
    # verbs to a command set that has never heard of them would bounce the
    # same way.
    # Whichever spelling the command set actually knows, the player's for
    # preference. Folding runs both ways here: "study" folds to "look" and
    # only "look" is a command, while "groups" folds to "group" and only
    # "groups" is. Sending either the raw word or the folded one alone would
    # bounce on the other.
    known = verbs.command_verbs()
    typed, _, rest = raw.strip().partition(" ")
    spelling = typed.lower() if typed.lower() in known else (
        verb if verb in known else "")
    # Except the ones the pipeline has taken over. A command still exists for
    # `look` -- it is how a player types it -- but what looking MEANS is now a
    # world's business, so handing it back would return it to the code the
    # rules were written to replace, and the rules would never run.
    #
    # Tested on the canonical verb rather than on what was typed, so every one
    # of `look`, `l`, `x`, `examine`, `inspect`, `study` and `view` is caught by
    # the one entry. Getting that wrong is the bounce the comment above
    # describes, in the other direction.
    if verb in verbs.PIPELINE_VERBS:
        spelling = ""
    if spelling:
        caller.execute_cmd(f"{spelling} {rest}".strip())
        on_message("", "")
        return

    # Learning a rule and writing a narration are network round trips, and the
    # effects land only once they return. Without a hold on the object itself,
    # two people pulling the same lever in that window both apply its effects.
    # The lock is per object AND verb, so one person reading a notice does not
    # stop another burning it.
    anchor = _anchor(bound, caller)
    if anchor is not None:
        if _busy(anchor, verb):
            on_message("Someone else is already doing that.", "")
            return
        _hold(anchor, verb)

    done = []

    def release(actor_text, room_text=""):
        # At most once. The visible symptom of a second release is two answers
        # to one attempt; the invisible one is that the hold above is dropped
        # twice, so a release arriving late lets go of a hold somebody else is
        # relying on. It also lets the guard below release unconditionally
        # without having to know how far the attempt got.
        if done:
            return
        done.append(True)
        if anchor is not None:
            _drop(anchor, verb)
        _release(caller, on_message, actor_text, room_text)

    def guarded(step):
        """
        Run a step of the attempt, and let the object go if it falls over.

        The hold is not a transaction: nothing rolls it back, and it lives in
        ndb, so an exception anywhere between taking it and releasing it wedges
        that verb on that object until the server restarts. Every later attempt
        is answered "Someone else is already doing that" while nobody is doing
        it, which reads as a game bug rather than as the crash it was. A rule
        that would not serialise into a prompt did exactly this to `sign`.

        The steps are chained through callbacks rather than nested, so each
        entry point into the chain -- the synchronous start, and each reply
        from a model -- is wrapped where it enters. Every ordinary path out of
        here ends in `release`; this keeps that promise when the way out is a
        traceback.
        """
        try:
            step()
        except Exception:
            logger.log_trace(
                f"{caller.key}: {verb!r} on {raw!r} did not finish")
            release("|rSomething went wrong doing that.|n")

    waiter = waiter or _once(None)

    def with_rule(known_rule):
        """Once the verb's meaning is settled, ask whether this sort admits it."""
        _admitted(caller, room, account, raw, verb, bound, known_rule,
                  release, allow_effects, world_root, waiter, guarded,
                  redirects)

    def begin():
        # What this verb takes, settled once, and the first of the two
        # questions a new verb costs. It comes first because its answer
        # changes the second one: a `direct` declared optional is what lets
        # `power` typed bare reach an `instead` rule rather than being told
        # "power what?", and a role declared `carried` is picked up on the
        # way in rather than refused.
        #
        # `actions.observe` is the fallback, not the ordinary path -- a
        # declaration is settled once and first one wins, so an arity read off
        # whatever the first attempt happened to name would lock out the real
        # answer for good. It still matters: an NPC acting on its own
        # initiative has no account to ask with.
        from world import actions

        def declared(_spec):
            # "Launch what?" is the right answer right up until a rule exists
            # that knows what. An `instead` rule guarded by `unbound` is exactly
            # that rule -- aboard a ship, `launch` means launching the ship --
            # and refusing before the rulebooks are consulted would make every
            # such rule dead on arrival, including one a world had just been
            # persuaded to accept.
            #
            # So the question is asked second. Nothing changes for a verb with
            # no redirect waiting, which is almost all of them: the sentence the
            # player reads is the same one, from the same place.
            wanted = actions.missing_role(world_root, verb, bound)
            if wanted and _redirect_waiting(world_root, verb, bound, caller):
                wanted = ""
            if wanted:
                # The count the spaceship needs. "launch what?" eleven times
                # aboard a ship is the evidence for a redirect rule, and until
                # now nothing anywhere remembered that it had been said.
                counters.note(world_root, verb, bound, caller,
                              counters.NO_OBJECT)
                release(actions.asking_for(verb, wanted))
                return
            settle()

        if actions.spec(world_root, verb) is None:
            waiter()
            actions.learn(account, world_root, verb, bound, caller,
                          on_success=lambda spec: guarded(
                              lambda: declared(spec)),
                          on_error=lambda err: release(f"|r{err}|n"))
            return
        declared(None)

    def settle():
        """What this verb means here, once it is known what it takes."""
        from world import rule_gen, rulebooks

        # What this world already knows how to do about this verb.
        #
        # Something has to actually happen, so a carry-out rule settles it --
        # and so does an `instead` rule, which either replaces the action
        # outright or sends it somewhere that has one. Asking on the strength
        # of a missing carry-out alone would buy a rule for every verb that
        # only ever redirects: aboard a ship nobody powers "nothing", so
        # `power` typed bare has no carry-out of its own and never will.
        #
        # And a learned rule settles it whatever it bridges to. A world that
        # decided a verb is impossible bridges that to a check nothing can
        # pass and no carry-out at all, so reading the book alone would ask
        # again on every attempt -- paying, each time, to be told the same no.
        key = verbs.rule_key(verb, bound)
        learned_rule = verb_gen.get_rule(world_root, key)
        book = rulebooks.for_attempt(world_root, verb, bound, caller,
                                     verb_rule=learned_rule)
        settled = learned_rule is not None or any(
            r["phase"] in (rulebooks.CARRY_OUT, rulebooks.INSTEAD)
            for r in book)
        if settled:
            with_rule(learned_rule or {})
            return

        # Unless this world has already asked and come away with nothing. Twice
        # is enough: the first empty answer may have been unlucky, the second is
        # evidence that there is no rule to be had. Without this a verb nobody
        # can write a rule for costs a call every time anybody types it -- and
        # since a character working at a goal may now try a verb the world has
        # never learned, that is a bill that could run on its own.
        if not rule_gen.worth_asking(world_root, verb):
            release(f"Nothing here knows how to {verb}.")
            return

        # Nobody has settled it, so ask -- and ask for rules rather than for
        # one universal definition. The prompt shows what already applies and
        # a menu of places to file against; see world/rule_gen.py for why
        # that is a smaller question than the one it replaces.
        def written(_rules):
            with_rule({})

        waiter()
        rule_gen.learn(
            account, world_root, verb, bound, caller,
            on_success=lambda rules: guarded(lambda: written(rules)),
            on_error=lambda err: release(f"|r{err}|n"),
        )

    guarded(begin)


def _admitted(caller, room, account, raw, verb, bound, rule, release,
              allow_effects, world_root, waiter, guarded, redirects=0):
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

    anchor = _anchor(bound, caller)
    obj_kinds = list(getattr(anchor.db, "kinds", None) or []) if anchor else []

    def proceed():
        _with_rule(caller, room, account, raw, verb, bound, rule, release,
                   allow_effects, world_root, waiter, guarded, redirects)

    def refuse():
        name = (anchor.get_numbered_name(1, None, return_string=True)
                if anchor is not None else "that")
        counters.note(world_root, verb, bound, caller, counters.NOT_ADMITTED)
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
        on_answer=lambda allowed, reason: guarded(
            lambda: answered(allowed, reason)),
        on_error=lambda err: release(f"|r{err}|n"),
    )


def _specifics_of(bound, verb, actor=None):
    """What was learned about this verb on these particular objects, if any."""
    anchor = _anchor(bound, actor)
    if anchor is None:
        return {}
    try:
        return dict((anchor.db.verb_specifics or {}).get(verb) or {})
    except (AttributeError, TypeError, ValueError):
        return {}


def _store_specifics(bound, verb, specifics, actor=None):
    """
    Keep what this object does under this verb, beside its narration.

    Written once, the first time the verb reaches this object, and only where
    the object actually differs -- an empty answer is stored as an empty
    answer so the question is not asked twice.
    """
    anchor = _anchor(bound, actor)
    if anchor is None:
        return
    store = dict(anchor.db.verb_specifics or {})
    if verb in store:
        return
    store[verb] = dict(specifics or {})
    anchor.db.verb_specifics = store


def _with_specifics(rule, bound, verb, actor=None):
    """
    The rule as it applies to these objects.

    A shallow overlay and nothing cleverer: this object's own effects replace
    the rule's, and its difficulty replaces the rule's, and everything else --
    what the verb requires, whether it is contested at all, whether it repeats
    -- stays the verb's business. The rule decides that prying is a strength
    contest; the crate decides that this one is a 12.
    """
    specifics = _specifics_of(bound, verb, actor)
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


def _redirect_waiting(world_root, verb, bound, caller):
    """
    Whether some `instead` rule would send this attempt somewhere else.

    Asked only when a role the action requires was left unbound, and only to
    decide whether to complain about that or to get on with it. Deliberately not
    "would the redirect succeed": that is the pipeline's business a moment later,
    and answering it twice is how two places come to disagree about one rule.
    """
    from world import rulebooks

    try:
        book = rulebooks.for_attempt(world_root, verb, bound, caller,
                                     phase=rulebooks.INSTEAD)
    except Exception:
        return False
    for rule in book:
        for effect in (rule.get("effects") or []):
            try:
                if str(effect.get("type") or "") == "try":
                    return True
            except AttributeError:
                continue
    return False


def _redirect(effect, bound, caller, world_root):
    """
    The roles a `try` effect names, bound to real things, or None.

    A redirect may fill a role from a place rather than from something the
    player typed -- `{"direct": {"enclosure": "spacecraft.n.01"}}` is the ship
    they are standing in -- which is the whole reason it exists. Anything it
    cannot resolve makes the redirect impossible rather than partial, since a
    verb sent at nothing is worse than a verb refused.
    """
    from world import conditions, kinds

    wanted = dict(bound or {})
    try:
        roles = dict(effect.get("roles") or {})
    except (TypeError, ValueError):
        return None
    for role, named in roles.items():
        if isinstance(named, str):
            if named == conditions.HERE:
                # The room itself, which is what bare `look` redirects to.
                # `{"enclosure": kind}` answers the same question for a place
                # of some particular sort; this is the case where any place
                # will do, and asking for a kind would mean inventing one that
                # every room in every world happened to be.
                found = getattr(caller, "location", None)
            else:
                found = bound.get(named) if named in bound else None
        else:
            try:
                kind = dict(named).get("enclosure")
            except (TypeError, ValueError):
                return None
            what, handle = kinds.enclosure(caller, kind,
                                           world_root=world_root)
            found = handle if what == kinds.ROOM else None
            if what == kinds.ZONE:
                # A zone is not a thing a verb can act on. The room stands in
                # for it, which is where its states are read from anyway.
                found = getattr(caller, "location", None)
        if found is None:
            return None
        wanted[str(role)] = found
    return wanted


def _with_rule(caller, room, account, raw, verb, bound, rule, release,
               allow_effects, world_root, waiter=None, guarded=None,
               redirects=0):
    from world import conditions, rulebooks

    ctx = conditions.context(bound, caller, world_root, verb)
    book = rulebooks.for_attempt(world_root, verb, bound, caller,
                                 verb_rule=rule)

    # INSTEAD. The most specific rule that says this means something else
    # here wins outright, and processing ends. One winner, never a merge:
    # merging is how a rule system stops being predictable, and this is the
    # phase where meaning lives.
    for aside in [r for r in book if r["phase"] == rulebooks.INSTEAD]:
        # A redirect is how a verb typed with no object comes to have one:
        # aboard a ship, `launch` means launching the ship. Inform calls it
        # trying another action, and it re-enters the whole pipeline rather
        # than short-cutting to the effects -- so every check that applies to
        # launching a ship applies, without the redirect having to know them.
        again = next((e for e in (aside.get("effects") or [])
                      if str(e.get("type") or "") == "try"), None)
        if again is not None and redirects < MAX_REDIRECTS:
            wanted = _redirect(again, bound, caller, world_root)
            if wanted is not None:
                _with_bindings(
                    caller, room, account, raw,
                    str(again.get("action") or verb), wanted,
                    lambda actor_text, room_text="": release(actor_text,
                                                             room_text),
                    allow_effects, waiter, redirects + 1)
                return
        extra = effects_mod.apply(caller, room, aside.get("effects") or [],
                                  bound=bound, world_root=world_root)
        counters.note(world_root, verb, bound, caller, counters.DONE)
        release(aside.get("name") or "", " ".join(extra).strip())
        return

    # CHECK. Every gathered rule, cumulatively, in specificity order. The
    # first unmet condition is what the player is told. This phase is safe to
    # extend by construction: a check rule can only ever make an action
    # stricter, never change what it means.
    for gate in [r for r in book if r["phase"] == rulebooks.CHECK]:
        complaint = conditions.unmet(gate.get("conditions") or [], ctx)
        if complaint:
            counters.note(world_root, verb, bound, caller, counters.REFUSED)
            release(complaint)
            return

    # CARRY OUT. The most specific rule with anything to do supplies both what
    # happens and what it is contested by, so there is one roll per attempt
    # and one place the change comes from. For a world that has not been
    # asked yet this is the bridged learned rule; for one that has, it is a
    # rule somebody wrote against a scope.
    doing = next((r for r in book if r["phase"] == rulebooks.CARRY_OUT), None)
    rule = {
        "valid": True,
        "effects": (doing or {}).get("effects") or [],
        "check": (doing or {}).get("contest"),
        "repeatable": bool(rule.get("repeatable")),
    }

    # What this particular thing does, and how hard it is on this particular
    # thing. The rule says what the verb means for everything of its sort; the
    # specifics say how this door differs from that door, and were written by
    # the same call that wrote what the player reads. Absent for almost
    # everything, which means the rule's own answer stands.
    rule = _with_specifics(rule, bound, verb, caller)

    # Preconditions say whether the attempt was allowed; the check says
    # whether it worked. That order is the whole point: you are told you have
    # no key before anything is rolled, and told you fumbled the lock only
    # once the attempt was a real one.
    contest = checks.wanted(rule)
    result = (checks.resolve(caller, contest, bound, world_root)
              if contest else None)
    outcome = result["outcome"] if result else "success"

    cached = _cached_narration(bound, verb, outcome, caller)
    # A contested verb always runs its effects again: the player swung again,
    # and this time it landed. Only a verb with a settled, single outcome may
    # answer from the cache without touching the world.
    if cached is not None and result is None and not rule.get("repeatable"):
        # What is cached is the template, so the room line still names its
        # actor as {actor} and has to be filled in here too -- broadcasting it
        # raw hands a stray format placeholder to msg_contents.
        # Counted like any other success. A verb answered from the cache is the
        # commonest kind of working verb there is, and leaving it out would make
        # every world look as though it refused far more than it allowed --
        # which is the exact figure a suggester weighs its proposals by.
        counters.note(world_root, verb, bound, caller, counters.DONE)
        release(cached.get("actor", ""),
                _for_room(cached.get("room", ""), caller, raw))
        return

    # Whether this rule's own effects are the whole of the answer. Looking is
    # the case: `describe` returns the appearance, and a model asked to narrate
    # on top of it would cost money to talk over the thing it was describing.
    speaks = effects_mod.speaks_for_itself(rule.get("effects"))

    def _finish(actor_text, room_text, specifics=None):
        # The template is cached, not the finished line: the room text names
        # the actor as {actor}, so the same narration reads correctly when
        # somebody else does the same thing to the same object later.
        #
        # Nothing is cached for a rule that speaks for itself: there is no
        # model reply to save, and the effect will say it again for nothing
        # next time -- which is the point of it.
        if not speaks:
            _store_narration(bound, verb, outcome,
                             {"actor": actor_text, "room": room_text}, caller)
        # Whatever the same reply said this thing does differently, kept
        # beside it. Stored even when empty, so a thing that turned out to be
        # perfectly ordinary is not asked about a second time.
        if specifics is not None:
            _store_specifics(bound, verb, specifics, caller)
        effective = _with_specifics(rule, bound, verb, caller)
        allowed = [
            e for e in checks.effects_for(effective, outcome)
            if (allow_effects is None or e.get("type") in allow_effects)
            and not (allow_effects is not None and _hits_everyone(e))
        ]
        extra = effects_mod.apply(caller, room, allowed, bound=bound,
                                  world_root=world_root)
        if speaks:
            # The effects produced the words, and they are an answer to
            # whoever acted rather than an announcement to the room: a look is
            # not an event, and a room told about everybody's reading would be
            # unusable. Joined on newlines because an appearance is already
            # several lines of its own.
            actor_text = "\n".join(
                part for part in [actor_text] + extra if part).strip()
            extra = []
        spoken = _for_room(room_text, caller, raw)
        visible = " ".join([spoken] + extra).strip()
        # AFTER. What follows from it having worked, gathered before any of
        # it landed so that nothing an after-rule does can set another one
        # going. Bounded by the action, which is how consequence happens here
        # without a tick: launching a ship makes everyone aboard weightless,
        # and the rule saying so lives on `spacecraft` rather than inside
        # `launch`.
        if outcome != "failure":
            for later in [r for r in book if r["phase"] == rulebooks.AFTER]:
                extra += effects_mod.apply(
                    caller, room, later.get("effects") or [],
                    bound=bound, world_root=world_root)

        _remember(caller, raw, bound, actor_text, extra, outcome=outcome,
                  contested=result is not None)
        # A contested attempt that came out badly is still a thing that
        # happened rather than a thing that was refused: the player was allowed
        # to try and the dice said no, which is not evidence of a missing rule.
        counters.note(world_root, verb, bound, caller, counters.DONE)
        release(actor_text, visible)
        # The world just changed under everyone here, which is exactly when a
        # quest may have quietly become finished.
        from world.quests import review_room
        review_room(room)

    if cached is not None:
        _finish(cached.get("actor", ""), cached.get("room", ""))
        return

    # No narrator for a rule that speaks for itself, and no round trip: the
    # whole reason looking can be an action is that it costs nothing to run.
    if speaks:
        _finish("", "")
        return

    if waiter:
        waiter()
    # `_finish` changes the world -- effects land, quests are reviewed -- and
    # it runs in a deferred callback, where a raise is swallowed as an
    # unhandled failure and the hold above never comes back. Wrapped so it
    # comes back.
    finish = _finish if guarded is None else (
        lambda *args, **kwargs: guarded(lambda: _finish(*args, **kwargs)))
    verb_gen.narrate(
        account, verb, bound, caller, raw,
        on_success=finish,
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
