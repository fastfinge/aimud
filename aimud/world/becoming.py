"""
Has anything become true?

A becomes rule runs because a fact changed rather than because somebody tried
something: "when a person's health becomes at most 0, they are dead" is one
rule, filed once, and not a line inside every verb that can hurt somebody. See
docs/becoming-and-time.md §6.

**Nothing ticks and nothing scans.** A rule is asked about a thing because
that thing is changing, and only then. The doors every change already comes
through -- `verbs.apply_states`, `traits.adjust`, a move, an owner changing,
something being put on or taken off, a figure found to have drifted -- call
`mark` *before* they write. `mark` asks the becomes rules about that one thing
what they say now, and keeps the answer. `settle`, called where an operation
ends, asks them again, and fires the ones that went from false to true.

**The before is taken at the door rather than remembered.** A memo of what was
true of everything would read a missing entry as false, and "stops boiling"
(`lacks: boiling`) is true of nearly everything, so every chair would stop
boiling the first time anything happened to it. The door can see the before,
so nothing is stored for things at all. See 6.4.

**Every rule that became true fires, most general first, and none stops
another.** A specific rule refines a general one by landing after it.

**`cause` is whoever acted**, bound when somebody did and not otherwise. A
condition about the cause is a guard and never the edge: "killed by somebody"
fires when health reaches 0 and somebody did it, not a second time when
somebody strikes a body that is already at 0. See 6.2.

**Chains are the point, and they end.** A rule's effects go through the same
doors and mark what they change, and settling goes round again -- at most
MAX_PASSES times, each rule at most once per thing. Whatever is still waiting
after that is a loop, not a chain: it is logged, counted against the rules
that fired last, and dropped rather than left to spin.

Nothing here calls a model. A rule says what happened with its own `report`,
a template `world.events` renders per viewer.

One simplification from the plan, on the record: the plan indexed rules by
what their conditions read, so a change would ask only the rules that read it.
This asks every becomes rule that applies to the thing. Becomes rules are few,
and an index that missed a predicate would make a rule silently never fire,
which is a worse failure than asking a handful of extra questions.
"""

import threading

from evennia.utils import logger

#: How many times settling goes round before what is still waiting is taken
#: to be a loop. Four, because the longest honest chain anybody has described
#: is three: a blow, a death, a dropped lantern that sets the straw alight.
MAX_PASSES = 4

#: The clock the backstop runs on. None is the reactor; a test puts one here.
CLOCK = None

#: Where a world counts the rules that kept setting each other off.
OVERFLOW_ATTR = "becomes_overflow"

#: A cause nobody has decided yet. Filled in by `settle` when it is given one,
#: and read as nobody when it is not.
_UNKNOWN = object()

#: What is waiting: {world root id: {"root": root, "things": {id: _Waiting}}}.
_WAITING = {}

_LOCAL = threading.local()


class _Waiting:
    """One thing that is changing, and what its rules said before it did."""

    __slots__ = ("obj", "before", "cause")

    def __init__(self, obj, before, cause):
        self.obj = obj
        self.before = before
        self.cause = cause


# ---------------------------------------------------------------------------
# Who is acting
# ---------------------------------------------------------------------------

def _causes():
    stack = getattr(_LOCAL, "causes", None)
    if stack is None:
        stack = _LOCAL.causes = []
    return stack


class caused_by:
    """
    Everything changed inside this was brought about by `who`.

    Nests the way a chain does: an inner `caused_by` keeps the outer cause, so
    the effects of a rule an attack set off are still the attacker's doing.
    `force` sets it regardless, which is how a becomes rule hands its effects
    the cause it fired with -- including nobody.
    """

    def __init__(self, who, force=False):
        self.who = who
        self.force = force

    def __enter__(self):
        stack = _causes()
        stack.append(stack[-1] if stack and not self.force else self.who)
        return self

    def __exit__(self, *exc):
        _causes().pop()
        return False


def acting():
    """True while something is being done, and settling should wait for it."""
    return bool(_causes())


def current_cause(default=None):
    """Whoever the surrounding `caused_by` names, or `default` outside one."""
    stack = _causes()
    return stack[-1] if stack else default


# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------

def _gone(obj):
    return obj is None or getattr(obj, "pk", None) is None


def room_of(obj):
    """The room a thing is in, however deeply; a room is its own."""
    from evennia.objects.objects import DefaultRoom

    here, steps = obj, 0
    while here is not None and steps < 32:
        if isinstance(here, DefaultRoom):
            return here
        here = getattr(here, "location", None)
        steps += 1
    return None


def world_of(obj):
    """The world a thing belongs to, or None."""
    room = room_of(obj)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# Which rules are about a thing, and what they say
# ---------------------------------------------------------------------------

def rules(world_root):
    """Every becomes rule in force in this world."""
    from world import rulebooks

    if world_root is None:
        return []
    return [rule for rule in rulebooks.all_rules(world_root)
            if rule.get("phase") == rulebooks.BECOMES
            and rule.get("listed", True)]


def _place_tier(rule, attempt, room):
    """Which tier a rule about a place matched `room` at, or None."""
    from world import kinds, rulebooks

    scope = rule.get("scope") or {}
    tier = rulebooks.tier_of(rule)
    if rulebooks.WORLD in scope:
        return tier
    if rulebooks.ROOM in scope:
        return tier if room.id == scope[rulebooks.ROOM] else None
    if rulebooks.ZONE in scope:
        return tier if scope[rulebooks.ZONE] in attempt.zone_ids else None
    if rulebooks.KIND in scope:
        wanted = scope[rulebooks.KIND]
        return tier if kinds.any_is_a(attempt.world_root, kinds.of(room),
                                      wanted) else None
    return None


def applying(world_root, obj):
    """
    The becomes rules about this thing, most general first.

    A rule `about` a place is about rooms, and every other rule is about
    things and people -- the same `about` an attempt matches by.
    """
    from world import rulebooks
    from world.quests import is_person

    found = []
    room = room_of(obj)
    is_room = obj is room
    person = obj if not is_room and is_person(obj) else None
    attempt = rulebooks.Attempt(world_root, "", {"direct": obj}, person,
                                room=room)
    for rule in rules(world_root):
        about_place = str(rule.get("about") or "direct") in rulebooks.PLACES
        if about_place != is_room:
            continue
        tier = (_place_tier(rule, attempt, obj) if is_room
                else rulebooks.matches(rule, attempt))
        if tier is None:
            continue
        found.append((rulebooks.rank(rule, tier, world_root), rule))
    return [rule for _key, rule in sorted(found, key=lambda pair: pair[0],
                                          reverse=True)]


def _context(world_root, obj, cause=None):
    from world import conditions
    from world.quests import is_person

    room = room_of(obj)
    person = obj if obj is not room and is_person(obj) else None
    bound = {"direct": obj}
    if cause is not None and cause is not _UNKNOWN:
        bound["cause"] = cause
    return conditions.context(bound, person, world_root, "", room=room)


def _without_cause(condition):
    """
    A condition with everything it asks about the cause taken out.

    The edge a rule watches is what happened to the thing. Who did it is a
    guard, asked only once the edge has risen -- otherwise hitting a body that
    is already at 0 health would make "killed by somebody" true a second time,
    since the cause is nobody before the blow and somebody after it.
    """
    from world import conditions

    kind, members = conditions.node_of(condition)
    if kind:
        return {kind: [_without_cause(member) for member in members]}
    try:
        if condition.get("subject") == "cause":
            return {}            # asks nothing, which holds
    except AttributeError:
        return condition
    return condition


def _edges(world_root, obj):
    """[(rule, whether its edge holds now)] for the rules about this thing."""
    from world import conditions

    ctx = _context(world_root, obj)
    found = []
    for rule in applying(world_root, obj):
        edge = all(conditions.evaluate(_without_cause(c), ctx)
                   for c in (rule.get("when") or []))
        found.append((rule, edge))
    return found


# ---------------------------------------------------------------------------
# Marking what is about to change
# ---------------------------------------------------------------------------

def mark(obj, world_root=None, cause=_UNKNOWN, overlay=None):
    """
    Note that `obj` is about to change, and what its rules say before it does.

    Called by a door *before* it writes. The first mark in a settle takes the
    before; later ones only fill in a cause that was not known. In a world
    with no becomes rules this is one lookup.

    `cause` defaults to whoever the surrounding `caused_by` names, or to not
    yet known. `overlay` is for a change that has already happened by the time
    anybody notices it -- a figure that drifted -- and lays the figures as they
    were over the live ones while the rules are asked: {trait slug: value}.
    """
    if _gone(obj):
        return
    root = world_root or world_of(obj)
    if root is None or not rules(root):
        return
    if cause is _UNKNOWN and _causes():
        cause = _causes()[-1]

    waiting = _WAITING.setdefault(root.id, {"root": root, "things": {}})
    entry = waiting["things"].get(obj.id)
    if entry is not None:
        if entry.cause is _UNKNOWN and cause is not _UNKNOWN:
            entry.cause = cause
        return

    from world import traits

    with traits.overlaid(obj, overlay):
        before = {rule["id"]: edge for rule, edge in _edges(root, obj)}
    waiting["things"][obj.id] = _Waiting(obj, before, cause)
    _arm_backstop()


def waiting():
    """How many things are waiting to be settled. For tests and for `view`."""
    return sum(len(entry["things"]) for entry in _WAITING.values())


def forget_waiting():
    """Drop everything waiting, unsettled. For tests."""
    _WAITING.clear()
    _LOCAL.causes = []
    _LOCAL.settling = False
    _LOCAL.armed = False


# ---------------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------------

def settle(cause=_UNKNOWN):
    """
    Fire every becomes rule that became true since things were marked.

    `cause` is who a thing marked without one was changed by: the actor of the
    attempt or the mechanic that has just finished. A thing whose cause was
    never known is read as changed by nobody.

    Does nothing while something is still being done (see `acting`), so a
    move in the middle of an attempt's effects does not fire a rule before the
    blow that set it off has been narrated: the attempt settles when it ends.
    Does nothing if it is already settling, since the pass it is in will pick
    up whatever was marked.
    """
    if acting() or getattr(_LOCAL, "settling", False):
        return
    if not _WAITING:
        return
    _LOCAL.settling = True
    fired = set()
    last_pass = []
    try:
        for _pass in range(MAX_PASSES):
            if not _WAITING:
                break
            batch = list(_WAITING.values())
            _WAITING.clear()
            last_pass = []
            for waiting_here in batch:
                root = waiting_here["root"]
                for entry in waiting_here["things"].values():
                    if entry.cause is _UNKNOWN:
                        entry.cause = None if cause is _UNKNOWN else cause
                    last_pass += _settle_one(root, entry, fired)
        if _WAITING:
            _overflowed(last_pass)
    finally:
        _LOCAL.settling = False


def _settle_one(root, entry, fired):
    """Fire what became true of one thing. Answers the rules that fired."""
    from world import conditions

    obj = entry.obj
    if _gone(obj):
        return []
    done = []
    for rule, edge in _edges(root, obj):
        rule_id = rule["id"]
        if not edge or entry.before.get(rule_id, True):
            # Not true now, true already, or not a rule about this thing
            # before it changed -- none of which is becoming true.
            continue
        if (rule_id, obj.id) in fired:
            continue
        ctx = _context(root, obj, entry.cause)
        if not all(conditions.evaluate(c, ctx)
                   for c in (rule.get("when") or [])):
            continue             # the edge rose, and the guard on who says no
        fired.add((rule_id, obj.id))
        fire(root, rule, obj, entry.cause)
        done.append(rule)
    return done


def fire(world_root, rule, obj, cause=None):
    """
    Run one becomes rule about `obj`, and say what it says.

    `direct` is the thing, `actor` is the thing when it is a person, and
    `cause` is whoever acted, when somebody did. Its effects mark whatever they
    change with the same cause, which is what lets a chain keep it.
    """
    from world import effects
    from world.quests import is_person

    room = room_of(obj)
    person = obj if obj is not room and is_person(obj) else None
    bound = {"direct": obj}
    if cause is not None:
        bound["cause"] = cause
    logger.log_info(f"becomes: {rule.get('id')} fired for {obj}"
                    + (f", caused by {cause}" if cause is not None else ""))
    with caused_by(cause, force=True):
        lines = effects.apply(person, room, rule.get("effects") or [],
                              bound=bound, world_root=world_root)
    _report(rule, person, room, bound, lines)


def _report(rule, person, room, bound, lines):
    """
    Tell the room what happened, in the rule's own words.

    Rendered for each reader, the person it happened to included -- "You
    collapse to the ground." -- and never by a model. A report that names the
    cause when there was nobody is left unsaid rather than shown with a raw
    "{cause}" in it.
    """
    from world import events

    template = str(rule.get("report") or "")
    if "{cause" in template and "cause" not in bound:
        template = ""
    if room is None or not (template.strip() or lines):
        return
    event = events.Event(actor=person, room=room, verb="", roles=bound,
                         outcome="success", effects=list(lines or []),
                         room_template=template)
    events.deliver(event, to_actor=False)
    if person is not None and hasattr(person, "msg"):
        line = events.render(event.template(), person, event)
        if line.strip():
            person.msg(line)


def _overflowed(last_pass):
    """
    Settling went round MAX_PASSES times and things are still changing.

    That is a loop rather than a chain. What is waiting is dropped, so it
    cannot spin for ever, and the rules that fired on the last pass are
    counted where `view faults` can name them.
    """
    stuck = list(_WAITING.values())
    _WAITING.clear()
    for waiting_here in stuck:
        root = waiting_here["root"]
        counts = dict(getattr(root.db, OVERFLOW_ATTR, None) or {})
        for rule in last_pass:
            counts[rule["id"]] = counts.get(rule["id"], 0) + 1
        setattr(root.db, OVERFLOW_ATTR, counts)
    logger.log_info(
        f"becomes: still changing after {MAX_PASSES} passes; dropped what was "
        f"waiting. Last to fire: "
        f"{', '.join(str(r.get('id')) for r in last_pass) or 'nothing'}")


# ---------------------------------------------------------------------------
# The backstop
# ---------------------------------------------------------------------------

def _arm_backstop():
    """
    Settle soon, for a change made outside anything that settles when done.

    `npc_gen` giving a character its figures, a token list choosing a state:
    these write through the same doors and nothing calls `settle` after them.
    Rather than each having to remember to, the first mark into an empty set
    arms one call for the next turn of the reactor.
    """
    if getattr(_LOCAL, "armed", False):
        return
    _LOCAL.armed = True
    try:
        from twisted.internet import reactor

        (CLOCK or reactor).callLater(0, _backstop)
    except Exception as exc:
        _LOCAL.armed = False
        logger.log_info(f"becomes: could not arm the backstop: {exc}")


def _backstop():
    _LOCAL.armed = False
    settle()
