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


def fire(world_root, rule, obj, cause=None, silent=False):
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
    if not silent:
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
# Predicted crossings
# ---------------------------------------------------------------------------
#
# Every door above is somebody doing something. A poison draining a character
# while a player stands and watches is nobody doing anything, and yet somebody
# is looking. A figure with a rate moves in a straight line, though, so the
# moment it will reach a threshold a rule cares about can be worked out -- and
# one timer per character, for the earliest such moment, fires exactly then.
# Not a poll: it fires once, and re-arms for the next. Only while the world is
# awake, since a world nobody is watching costs nothing, not even free work; a
# crossing that happens while it sleeps is still true when somebody next looks,
# because the figure is worked out whenever it is read. See docs §7.

#: How late a timer fires past the moment it worked out, so that a figure
#: arrived at by floating-point arithmetic has really arrived.
SLACK = 0.05

#: Where a character keeps its timer. In memory only: a reload ends it, and
#: `arm_everyone_awake` puts it back.
TIMER = "crossing_timer"


def _awake(world_root):
    """Whether this world is being watched, which is when timers may run."""
    from world import activity

    return bool(world_root is not None
                and (activity.world_has_active_player(world_root)
                     or activity.always_on(world_root)))


def _trait_figures(condition, found):
    """Add every trait bound in `condition` to found: {slug: {figure, ...}}."""
    from world import conditions

    for leaf, _optional in conditions.leaves(condition):
        slug = leaf.get("trait")
        if not slug:
            continue
        for bound in conditions.TRAIT_BOUNDS:
            figure = leaf.get(bound)
            if figure is None:
                continue
            try:
                found.setdefault(str(slug).lower(), set()).add(float(figure))
            except (TypeError, ValueError):
                continue


def _named_states(condition):
    """The states a condition asks about by name."""
    from world import conditions
    from world.model_json import listed

    named = set()
    for leaf, _optional in conditions.leaves(condition):
        for field in ("is", "lacks"):
            named |= {str(s).lower() for s in listed(leaf.get(field))}
    return named


def thresholds(world_root, character):
    """
    {trait slug: {figure, ...}}: the figures at which something about this
    character would change.

    The trait bounds in the `when` of the becomes rules about the character,
    and in the definitions of derived states those rules ask about -- so a rule
    on `is: starving` is timed by hunger -- and in derived states that are
    worth something to a figure, since gear has to follow those as well.
    """
    from world import verbs

    found = {}
    derived = verbs.derived_states(world_root)
    wanted = set()
    for rule in applying(world_root, character):
        for condition in (rule.get("when") or []):
            _trait_figures(condition, found)
            wanted |= _named_states(condition)
    wanted |= {slug for slug in verbs.state_bonuses(world_root)
               if slug in derived}
    seen = set()
    while wanted:
        slug = wanted.pop()
        if slug in seen or slug not in derived:
            continue
        seen.add(slug)
        for condition in (derived[slug].get("when") or []):
            _trait_figures(condition, found)
            wanted |= _named_states(condition)
    return found


def next_crossing(world_root, character):
    """
    Seconds until one of this character's moving figures reaches a threshold,
    or None when none of them will.

    A figure only reaches one ahead of it in the direction it is moving, and
    only if its bounds and `ratetarget` let it get there: the Traits contrib
    stops a rate at either.
    """
    from world import traits

    if not traits.has_traits(character):
        return None
    soonest = None
    for slug, figures in thresholds(world_root, character).items():
        trait = character.traits.get(slug)
        if trait is None:
            continue
        rate = float(getattr(trait, "rate", 0) or 0)
        if not rate:
            continue
        current = trait.value
        low, high = traits._bounds(trait)
        target = getattr(trait, "ratetarget", None)
        for figure in figures:
            if rate > 0 and figure > current:
                limit = min(x for x in (high, target, float("inf"))
                            if x is not None)
                if figure > limit:
                    continue
                seconds = (figure - current) / rate
            elif rate < 0 and figure < current:
                limit = max(x for x in (low, target, float("-inf"))
                            if x is not None)
                if figure < limit:
                    continue
                seconds = (current - figure) / -rate
            else:
                continue
            if soonest is None or seconds < soonest:
                soonest = seconds
    return soonest


def arm(character, world_root=None):
    """
    Set this character's one timer for the next crossing, or clear it.

    Called when a rate is set, when the character settles, when a world wakes
    around them, and when the timer itself fires. Cheap to call too often:
    it works the next moment out afresh and replaces whatever was set.
    """
    if _gone(character):
        return
    disarm(character)
    root = world_root or world_of(character)
    if root is None or not _awake(root):
        return
    seconds = next_crossing(root, character)
    if seconds is None:
        return
    try:
        from twisted.internet import reactor

        call = (CLOCK or reactor).callLater(max(seconds, 0) + SLACK,
                                            _crossed, character)
    except Exception as exc:
        logger.log_info(f"becomes: could not arm a crossing for "
                        f"{character}: {exc}")
        return
    setattr(character.ndb, TIMER, call)


def disarm(character):
    """Cancel this character's crossing timer, if one is set."""
    call = getattr(getattr(character, "ndb", None), TIMER, None)
    if call is None:
        return
    try:
        if call.active():
            call.cancel()
    except Exception:
        pass
    setattr(character.ndb, TIMER, None)


def _crossed(character):
    """
    A figure has reached a threshold with nobody doing anything.

    Asks the character what drifted, which marks them with the figures as they
    were, then settles, then sets the timer for the next one. Into a world
    that has gone to sleep it does nothing at all and does not re-arm: the
    crossing is still true when somebody next looks.
    """
    if _gone(character):
        return
    setattr(character.ndb, TIMER, None)
    root = world_of(character)
    if root is None or not _awake(root):
        return
    from world import traits

    traits.notice_changes(character)
    traits._recount_worth(character, root)
    settle()
    arm(character, root)


def arm_around(obj):
    """Arm every person in the room `obj` is in, `obj` included."""
    from world.quests import is_person

    room = room_of(obj)
    people = [thing for thing in (room.contents if room is not None else [])
              if is_person(thing)]
    if obj is not None and obj not in people and is_person(obj):
        people.append(obj)
    for person in people:
        arm(person)
    arm_clock(world_of(room))


def arm_everyone_awake():
    """
    After a start or a reload, arm the people in every room somebody is
    playing in. Timers live in memory, so a reload ends every one of them.
    """
    from evennia.server.sessionhandler import SESSIONS

    for session in SESSIONS.get_sessions():
        puppet = getattr(session, "puppet", None)
        if puppet is not None:
            arm_around(puppet)


# ---------------------------------------------------------------------------
# The clock, and places
# ---------------------------------------------------------------------------
#
# A room changes with nobody in it and no door to take a before: dawn comes
# whether anybody is standing in the square or not. So a place rule that
# watches the clock is asked in two ways, and neither is a scan:
#
# * **Live**, for a room somebody is in -- player or NPC -- when the world's one
#   clock timer fires at a boundary a place rule mentions. The before is the
#   clock just short of the boundary, the after is now, and a rule that rose
#   fires and says so.
# * **On arrival**, for a room nobody was watching. Each room remembers, per
#   rule, what was true when it was last asked and when; a rising edge since
#   then fires **once, silently**. The stock was replaced at midnight, and
#   nobody arriving at noon hears a bell.
#
# That memo is on the world root, and holds only rooms somebody has been in
# since the rule was written. See docs/becoming-and-time.md 8.4.

#: Where a world keeps what its place rules said about each room, and when:
#: {rule id: {room id: [was true, real timestamp]}}.
SEEN_ATTR = "becomes_seen"

#: Where a world keeps its clock timer. In memory only, like a character's.
CLOCK_TIMER = "clock_timer"


def _clock_hours_in(world_root, conditions_list, derived=None, seen=None):
    """Every hour a list of conditions watches, through derived states too."""
    from world import conditions, verbs

    derived = verbs.derived_states(world_root) if derived is None else derived
    seen = set() if seen is None else seen
    hours = set()
    for condition in conditions_list or []:
        for leaf, _optional in conditions.leaves(condition):
            span = conditions._clock_span(leaf.get("clock")) \
                if leaf.get("clock") is not None else None
            if span is not None:
                hours |= set(span)
        for slug in _named_states(condition):
            if slug in derived and slug not in seen:
                seen.add(slug)
                hours |= _clock_hours_in(world_root,
                                         derived[slug].get("when"),
                                         derived, seen)
    return hours


def _place_rules(world_root):
    """The becomes rules about places that watch the clock."""
    from world import rulebooks

    return [rule for rule in rules(world_root)
            if str(rule.get("about") or "direct") in rulebooks.PLACES
            and _clock_hours_in(world_root, rule.get("when"))]


def clock_hours(world_root):
    """Every hour on the dial at which some place rule might change."""
    hours = set()
    for rule in _place_rules(world_root):
        hours |= _clock_hours_in(world_root, rule.get("when"))
    return hours


def _edge_at(world_root, room, rule, real_when=None):
    """Whether a rule's edge held for a room at real time `real_when`."""
    from world import clock, conditions

    def asked():
        ctx = _context(world_root, room)
        return all(conditions.evaluate(_without_cause(c), ctx)
                   for c in (rule.get("when") or []))

    if real_when is None:
        return asked()
    with clock.pinned(real_when):
        return asked()


def _rose_between(world_root, room, rule, was_true, start, end):
    """
    Whether a rule became true for a room at some moment after `start`.

    The plain comparison first: false then and true now. Then each boundary
    the rule watches, at the last time the dial reached it: a rule that was
    true, went false and came true again while nobody watched still rose, at
    the boundary where it came true.
    """
    from world import clock

    if not was_true and _edge_at(world_root, room, rule):
        return True
    for boundary in _clock_hours_in(world_root, rule.get("when")):
        crossed = clock.real_time_of_last(world_root, boundary, before=end)
        if crossed <= start:
            continue
        if (not _edge_at(world_root, room, rule, crossed - SLACK)
                and _edge_at(world_root, room, rule, crossed + SLACK)):
            return True
    return False


def settle_place(world_root, room, boundary=None):
    """
    Fire the clock-watching place rules that became true for one room.

    With `boundary` -- the real time the clock timer was set for -- a rule
    that rose across it fires and says so. Without, this is a room somebody
    has just come into, and a rule that rose since it was last asked fires
    once and silently. Either way the room's memo is brought up to now.
    """
    from world import clock

    if world_root is None or room is None:
        return
    places = [rule for rule in applying(world_root, room)
              if rule in _place_rules(world_root)]
    if not places:
        return
    now = clock._real_now()
    seen = dict(getattr(world_root.db, SEEN_ATTR, None) or {})
    key = str(room.id)
    for rule in places:
        entries = dict(seen.get(rule["id"]) or {})
        entry = entries.get(key)
        rose = False
        if boundary is not None:
            rose = (_edge_at(world_root, room, rule)
                    and not _edge_at(world_root, room, rule,
                                     boundary - 2 * SLACK))
        elif entry is not None:
            try:
                rose = _rose_between(world_root, room, rule, bool(entry[0]),
                                     float(entry[1]), now)
            except (TypeError, ValueError, IndexError):
                rose = False
        if rose:
            fire(world_root, rule, room, None, silent=boundary is None)
        entries[key] = [_edge_at(world_root, room, rule), now]
        seen[rule["id"]] = entries
    setattr(world_root.db, SEEN_ATTR, seen)


def occupied_rooms(world_root):
    """
    The rooms of this world a person is in, player or NPC.

    Players by their sessions and NPCs by their typeclass, so a world is never
    walked room by room: a room with nobody in it is exactly the one this does
    not need to find.
    """
    from evennia.server.sessionhandler import SESSIONS

    from typeclasses.npcs import NPC

    found = {}
    people = [getattr(session, "puppet", None)
              for session in SESSIONS.get_sessions()]
    people += list(NPC.objects.all_family())
    for person in people:
        if _gone(person):
            continue
        room = room_of(person)
        if room is not None and world_of(room) == world_root:
            found[room.id] = room
    return list(found.values())


def arm_clock(world_root):
    """
    Set this world's one clock timer for the next boundary a place rule
    watches, or clear it. Only while the world is awake.
    """
    if world_root is None or _gone(world_root):
        return
    call = getattr(world_root.ndb, CLOCK_TIMER, None)
    if call is not None:
        try:
            if call.active():
                call.cancel()
        except Exception:
            pass
        setattr(world_root.ndb, CLOCK_TIMER, None)
    if not _awake(world_root):
        return
    hours = clock_hours(world_root)
    if not hours:
        return
    from world import clock

    seconds = min(clock.real_seconds_until(world_root, h) for h in hours)
    boundary = clock._real_now() + seconds
    try:
        from twisted.internet import reactor

        call = (CLOCK or reactor).callLater(seconds + SLACK, _clock_crossed,
                                            world_root, boundary)
    except Exception as exc:
        logger.log_info(f"becomes: could not arm the clock for "
                        f"{world_root}: {exc}")
        return
    setattr(world_root.ndb, CLOCK_TIMER, call)


def _clock_crossed(world_root, boundary):
    """The dial reached a boundary: settle every room somebody is in."""
    if _gone(world_root):
        return
    setattr(world_root.ndb, CLOCK_TIMER, None)
    if not _awake(world_root):
        return
    for room in occupied_rooms(world_root):
        settle_place(world_root, room, boundary=boundary)
    arm_clock(world_root)


def arrived(person):
    """
    Somebody has come into a room: catch it up on what the clock did.

    Silent, and once, for whatever rose while nobody was there to see it.
    """
    room = room_of(person)
    root = world_of(room)
    if root is not None:
        settle_place(root, room)


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
