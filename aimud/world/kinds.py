"""
What sort of thing something is, and what that sort can do.

An affordance is a fact about bottles. It was being stored on each bottle --
written fresh by a model, for every bottle that ever existed -- and across five
worlds seventy-three bottles arrived at twenty-five different answers. Since
`verbs.signature()` builds its cache key out of affordances, those are
twenty-five keys, and the thirty separate times those worlds learned what
`drink` means is what that costs.

So the fact moves to where it was always true. A kind owns its affordances; an
object owns a kind. Deciding once per kind rather than once per object is 58%
fewer decisions in worlds this size, every one of them reusable, and the
generalisation is untouched -- affordances are still the cache key, they are
just read through the kind instead of off the instance. Seventy-one percent of
kinds share their set with another kind, so one `read` rule still covers a
brochure, a flyer, a map, a menu, a newspaper and a pamphlet at once.

**A kind is closed or none of this works.** The point of moving the decision
is that the answer stops moving, and a free-written string starts moving
immediately: chest, storage chest, wooden chest, coffer. So a kind is a
WordNet synset -- `chest.n.02` -- which is an identifier rather than a
description and cannot drift.

Generated worlds are full of nouns no dictionary has heard of, and those keep
their bare noun as a kind and are **anchored**: the spec carries an `under`
naming the nearest real sense, so `datapad` hangs beneath `device.n.01` and
`ancestors()` walks through it. Without that a kind has no taxonomy above it
at all -- `lexicon.ancestors("datapad")` is empty, so it gets no floor, prunes
against nothing, and can never be reached by a rule filed against a sort of
thing. For a space game that is most of the vocabulary. Ask `needs_anchor`
whether a kind wants one; the generators offer the menu.

**A thing may be more than one kind, and kinds only ever add.** A sword with
runes on the blade is a sword and an inscription, and what it affords is what
either of them affords. There is deliberately no way to say a thing lacks what
its kind has: see docs/kinds-and-affordances.md for the measurements, but the
short of it is that almost every subtraction in these worlds was a model
forgetting rather than an exception, and a thing that genuinely cannot do what
its kind does is either in a state that prevents it -- sealed, blunted, broken
-- or is not really that kind.
"""

from evennia.utils import logger

from world import affordances as af

#: Where a world keeps what it has decided about each kind.
ATTR = "kind_specs"


# ---------------------------------------------------------------------------
# Naming a kind
# ---------------------------------------------------------------------------

def canonical(kind):
    """
    A kind as it is stored: a synset id, or a bare singular noun.

    A synset is passed through untouched -- it is an identifier and picking at
    it is how identifiers stop matching. Anything else is a word, and is
    reduced to the singular so that "bottles" and "bottle" are not two kinds --
    and then, where the dictionary can settle it unaided, to a sense.

    That last step was missing, and the cost was larger than it looks. Of the
    58 kinds the exported worlds had settled, **7 had any ancestry at all**:
    the rest were bare words like `bottle`, and a bare word has no hypernyms,
    so it took no floor from the taxonomy, pruned against nothing, and could
    never be reached by a rule filed against a sort of thing. Not only the
    invented nouns -- `bottle`, `book` and `broom` were all equally ungrounded.

    Forty of those 58 can be settled for nothing, because `needs_sense_choice`
    already says their senses do not disagree about what sort of thing they
    are. Nine genuinely need a model to choose, and get asked. Nine have no
    senses at all, and get an anchor instead.
    """
    from world import lexicon

    kind = str(kind or "").strip().lower()
    if not kind:
        return ""
    if lexicon.ancestors(kind):
        return kind            # a real synset, and it knows its own name
    word = lexicon.head_noun(kind)
    return lexicon.settled_noun_sense(word) or word


def prune(kinds, world_root=None):
    """
    Kinds with the redundant ones removed, primary first.

    A model asked for a set will offer the set it can think of, and the set it
    can think of includes the ancestors: sword and weapon, chest and container.
    Those add nothing -- the taxonomy already says a sword is a weapon, and
    `floor()` below reads it straight off the hypernym chain -- while every
    extra name is another way for two objects of the same sort to disagree.

    So a kind already implied by one that is kept is dropped. What survives is
    the primary and anything genuinely orthogonal to it: a sword stays a sword,
    a sword-and-inscription stays both.
    """
    kept = []
    for kind in [canonical(k) for k in (kinds or []) if canonical(k)]:
        if kind in kept:
            continue
        implied = False
        for other in kept:
            # Through the anchor, so that an invented kind and the sense it
            # hangs under are recognised as one thing: a "datapad, device" is
            # a datapad, the same way a "sword, weapon" is a sword.
            if (kind in ancestors(world_root, other)
                    or other in ancestors(world_root, kind)):
                implied = True
                break
        if not implied:
            kept.append(kind)
    return kept


# ---------------------------------------------------------------------------
# What a kind affords
# ---------------------------------------------------------------------------

def anchor(world_root, kind):
    """
    The real sense an invented kind hangs beneath, or "".

    Checked rather than trusted: a model asked for the nearest sense can name
    one that does not exist, and an anchor WordNet does not recognise is worse
    than none, because everything downstream would believe the kind was
    grounded when it is not.
    """
    from world import lexicon

    entry = spec(world_root, kind) or {}
    try:
        under = str(entry.get("under") or "").strip()
    except AttributeError:
        return ""
    return under if lexicon.ancestors(under) else ""


def needs_anchor(kind):
    """
    Whether a kind has nothing above it and no sense to reach for.

    Three states, and they want three different answers, so this is careful to
    name only the third:

    * the word's senses agree about what sort of thing it is -- `canonical`
      grounds it in the first one and nobody is asked anything;
    * they disagree -- `lexicon.sense_prompt` asks a generator that can see the
      room, because which sense is meant is a fact about the room;
    * the dictionary has never heard of the word at all -- and only then is
      there nothing to choose between, and an anchor is the answer.

    So `key` and `cup` are not anchor cases even though they arrive
    ungrounded: they have senses, and a sense choice is what settles them.
    `datapad` and `holodeck` are.
    """
    from world import lexicon

    settled = canonical(kind)
    if not settled or lexicon.ancestors(settled):
        return False
    return not lexicon.senses(lexicon.head_noun(kind), pos="n", limit=1)


def ancestors(world_root, kind):
    """
    Every sense a kind descends from, following its anchor if it has one.

    The one function anything asking about a kind's ancestry should call.
    `lexicon.ancestors` answers about English and knows nothing about what a
    world decided an invented noun was; this knows both.
    """
    from world import lexicon

    kind = canonical(kind)
    own = lexicon.ancestors(kind)
    if own:
        return own
    under = anchor(world_root, kind)
    if not under:
        return frozenset()
    return frozenset({under}) | lexicon.ancestors(under)


#: Buckets a thing cannot be in and still be picked up. The cheap half of
#: telling a badly chosen sense from a good one, with no model involved: the
#: generator says what the thing affords, the taxonomy says what the sense is,
#: and a takeable person is a contradiction rather than a judgement call.
#:
#: `blaster` is the case this exists for. Its only WordNet sense is "a workman
#: employed to blast with explosives" -- a person -- and being a single sense it
#: is never asked about, so a blaster pistol becomes a kind of person for the
#: life of the world. Declared wieldable and takeable, it contradicts, and the
#: generator gets asked after all.
#:
#: Deliberately two entries. A wider list would start guessing, and the honest
#: position is that this catches some bad senses and not all: a virtual reality
#: `pod` lands on "the vessel that contains the seeds of a plant", whose bucket
#: is nothing at all, so there is nothing for a declared affordance to
#: contradict. See docs/rulebooks-from-inform.md 7.
UNTAKEABLE_BUCKETS = ("person", "structure")

#: What a character is. Named rather than spelled at each use, because it is
#: written by two typeclasses and a generator and a mistyped synset would fail
#: by matching nothing -- the worst way, since a rule filed against people would
#: simply never gather and nobody would see an error.
PERSON = "person.n.01"


def ensure_person(obj):
    """
    Make sure a character has a kind, and answer with whether one was added.

    Rooms have had kinds since phase 2 and objects since kinds existed; people
    had none. So no rule could be filed against `person.n.01`, the admission
    question never applied to anybody, and every character in a world counted as
    one question to the attempt counters rather than one per sort of person.

    Called from `at_init` as well as at creation, because a world already in
    play cannot be asked to start again for this, and `at_init` runs when an
    object is loaded into the cache: one attribute read per load, one write per
    character ever.

    Only when there is nothing there. A character somebody has made into a ghost
    or a construct keeps whatever it was made, which is the same first-one-wins
    rule every other kind follows.
    """
    if obj is None or obj.db.kinds:
        return False
    obj.db.kinds = [PERSON]
    return True


def sense_contradicts(sense, affordances=None, takeable=None):
    """
    Whether a chosen sense disagrees with what the generator said the thing is.

    Returns the bucket that clashes, or "". A signal to ask for the sense
    rather than a verdict on it -- see `UNTAKEABLE_BUCKETS`.
    """
    from world import affordances as af
    from world import lexicon

    buckets = lexicon.buckets(sense)
    if not buckets:
        return ""
    handled = bool(takeable) or bool(
        af.afforded(af.normalise(affordances)) & {"get", "wield", "wear"})
    if not handled:
        return ""
    for bucket in UNTAKEABLE_BUCKETS:
        if bucket in buckets:
            return bucket
    return ""


def floor(world_root, kind):
    """
    What the taxonomy already guarantees about a kind, as an affordance map.

    A chest is a container whoever generated it, and a sword is something to
    wield. This is the part no model has to be asked and no model may
    contradict: it stops the first object of a kind deciding something the
    dictionary already answers, which matters because the first object of a
    kind now decides for all of them.

    Thin on purpose. WordNet has an opinion about six of the sixty-odd
    affordances these worlds invented and none at all about burning,
    crushing, brewing or flushing, which are exactly the interesting ones. A
    floor is all this is.
    """
    from world import lexicon

    return af.normalise(sorted(
        lexicon.implied_by(ancestors(world_root, kind))))


#: Where things may be put, and what a kind has to be for it. "under" and
#: "behind" ask nothing -- everything has an underneath.
#:
#: This is deliberately NOT an affordance. "Container" and "surface" are not
#: things done to an object, they are shapes it has, and `world.relations` is
#: the module that asks. They lived in the affordance list for as long as that
#: list was the only place to put a fact about an object, and the cost was a
#: cache key that mixed what can be done to a thing with where things fit on
#: it -- so a table and a shelf failed to share a rule over whether one of
#: them had been called a surface that day.
PLACEMENT = ("in", "on")


def holds(world_root, kinds):
    """Which of PLACEMENT a thing of these kinds accepts."""
    settled = set()
    for kind in prune(kinds, world_root):
        entry = spec(world_root, kind) or {}
        try:
            settled |= {str(p) for p in (entry.get("holds") or [])}
        except AttributeError:
            pass
    return settled & set(PLACEMENT)


def spec(world_root, kind):
    """What this world has decided about a kind, or None if it is new."""
    if not world_root or not kind:
        return None
    return (getattr(world_root.db, ATTR, None) or {}).get(canonical(kind))


def _placement_floor(kind):
    """What the taxonomy says a kind holds: a container takes things in."""
    from world import lexicon

    buckets = lexicon.buckets(kind)
    found = set()
    if "container" in buckets:
        found.add("in")
    if "surface" in buckets:
        found.add("on")
    return found


def remember(world_root, kind, declared, accepts=(), under=""):
    """
    Settle what a kind affords, once, and answer with what was settled.

    First one wins. A kind that has already been decided is not revised by the
    next object claiming to be one, because revising it would change the
    affordances of everything already made -- which would change their cache
    keys, and quietly orphan every rule those objects had taught the world.
    An answer that is merely different is not worth that; an answer that is
    actually wrong is worth a reset, which is a decision for a person.
    """
    kind = canonical(kind)
    if not kind:
        return {}

    settled = spec(world_root, kind)
    if settled is not None:
        return dict(settled.get("affordances") or {})

    # An anchor is settled with the kind and before the floor is read, since
    # the floor is read *through* it: an invented noun hanging under
    # `container.n.01` is a container, and nothing else would have said so.
    from world import lexicon

    under = str(under or "").strip()
    if world_root and under and needs_anchor(kind) and lexicon.ancestors(under):
        store = dict(getattr(world_root.db, ATTR, None) or {})
        store[kind] = dict(store.get(kind) or {}, under=under)
        setattr(world_root.db, ATTR, store)
        logger.log_info(f"kinds: {kind} anchored under {under}")

    # The floor is applied last so that it wins: a model may add to what a
    # chest can do and may not talk it out of being a container.
    decided = af.merge(af.normalise(declared), floor(world_root, kind))
    takes = ({str(p).lower() for p in (accepts or [])} | _placement_floor(kind)
             ) & set(PLACEMENT)
    if world_root:
        store = dict(getattr(world_root.db, ATTR, None) or {})
        entry = dict(store.get(kind) or {})
        entry.update({"affordances": decided, "holds": sorted(takes)})
        store[kind] = entry
        setattr(world_root.db, ATTR, store)
        logger.log_info(
            f"kinds: {kind} settled as "
            f"{sorted(af.afforded(decided)) or 'nothing in particular'}"
            + (f", holds things {'/'.join(sorted(takes))}" if takes else "")
        )
    return decided


def resolve(world_root, kinds, declared=None, accepts=(), under=""):
    """
    What a thing of these kinds affords.

    The union across its kinds, with `declared` settling any kind this world
    is meeting for the first time. An object made of a kind that already
    exists costs nothing here and cannot disagree with its siblings; an object
    that introduces one teaches the world, once.
    """
    kinds = prune(kinds, world_root)
    if not kinds:
        return af.normalise(declared)

    if len(kinds) == 1:
        # The ordinary case, and the one the drift was in. What the generator
        # said settles the kind if the kind is new, and is ignored if it is
        # not: the seventy-third bottle does not get an opinion.
        return remember(world_root, kinds[0], declared, accepts, under)

    # A thing that is genuinely two things is rare and deliberate, and what it
    # affords cannot be pinned on either kind alone -- a sword with runes on
    # it is readable because of the runes, and filing that under `sword` would
    # make every sword in the world readable. So its kinds are consulted but
    # not taught, and what the generator said applies to this object only.
    #
    # Which is a per-object exception, arrived at deliberately and confined to
    # the one case that needs one. Single-kind objects, which is everything
    # the drift was ever measured in, cannot reach this.
    maps = []
    for kind in kinds:
        settled = spec(world_root, kind)
        maps.append(dict(settled.get("affordances") or {}) if settled
                    else floor(world_root, kind))
    return af.merge(*maps, af.normalise(declared))


def admits(world_root, obj_kinds, verb):
    """
    Whether a thing of these kinds can be verbed at all: True, False or None.

    None means nobody has decided, which is the ordinary state of almost every
    pair. Generators declare what they can think of at the moment a thing is
    made -- read, drink, wear, wield, burn -- and players type the rest of
    English at it. Across five worlds, 86% of every rule ever learned existed
    because of exactly this gap: the object said nothing about the verb, so
    the world generated a whole rule to cover its silence.

    A rule is a large thing to invent in answer to a small question. The
    question is "can a bottle be burned", the answer is one bit, and this is
    where that bit goes -- decided once, by kind, and true for every bottle
    the world will ever hold.
    """
    answer = None
    for kind in prune(obj_kinds, world_root):
        entry = spec(world_root, kind) or {}
        known = dict(entry.get("affordances") or {})
        if verb in known:
            if known[verb]:
                return True      # any kind saying yes is enough
            answer = False
    return answer


def admit(world_root, obj_kinds, verb, allowed):
    """
    Record that this sort of thing does or does not admit a verb.

    Written against the primary kind, since that is what the thing IS. A
    secondary kind is a thing's other nature and not the place to settle a
    question that was asked about it as a whole.
    """
    ordered = prune(obj_kinds, world_root)
    if not world_root or not ordered:
        return
    kind = ordered[0]
    store = dict(getattr(world_root.db, ATTR, None) or {})
    entry = dict(store.get(kind) or {})
    granted = dict(entry.get("affordances") or {})
    if verb in granted:
        return                   # already settled; first answer stands
    granted[verb] = bool(allowed)
    entry["affordances"] = granted
    entry.setdefault("holds", [])
    store[kind] = entry
    setattr(world_root.db, ATTR, store)
    logger.log_info(
        f"kinds: {kind} {'can' if allowed else 'cannot'} be {verb}ed"
    )


def note_state(world_root, obj_kinds, slugs):
    """
    Remember that things of this sort have been in these conditions.

    Not a declaration and not a restriction -- an observation. A bottle that
    has been full and empty and cracked says something true about bottles, and
    the next rule written about a bottle would rather be shown those six words
    than the world's whole vocabulary of sixty.

    Kept on the kind because that is the level it generalises at. Which states
    a thing may hold is not worth constraining -- the same looseness that lets
    `pry` leave a chest `open` is the looseness that would have to go -- but it
    is very much worth *recalling*, since a model shown "empty" does not go on
    to coin "drained".
    """
    ordered = prune(obj_kinds, world_root)
    if not world_root or not ordered:
        return
    wanted = {str(s).lower().strip() for s in (slugs or []) if s}
    if not wanted:
        return
    kind = ordered[0]
    store = dict(getattr(world_root.db, ATTR, None) or {})
    entry = dict(store.get(kind) or {})
    seen = set(entry.get("states") or []) | wanted
    if seen == set(entry.get("states") or []):
        return
    entry["states"] = sorted(seen)
    entry.setdefault("affordances", {})
    entry.setdefault("holds", [])
    store[kind] = entry
    setattr(world_root.db, ATTR, store)


def states_of(world_root, obj_kinds):
    """Every condition things of these kinds have been in."""
    seen = set()
    for kind in prune(obj_kinds, world_root):
        entry = spec(world_root, kind) or {}
        try:
            seen |= {str(s) for s in (entry.get("states") or [])}
        except (AttributeError, TypeError, ValueError):
            continue
    return seen


def vocabulary(world_root):
    """Every kind this world has settled, for a prompt that should reuse one."""
    return sorted((getattr(world_root.db, ATTR, None) or {}) if world_root else {})

# ---------------------------------------------------------------------------
# Is this thing one of those?
# ---------------------------------------------------------------------------

def of(obj):
    """
    Every kind a thing is, as stored. Works for objects, rooms and zones alike.

    One reader, because from here on the answer is asked of places as well as
    of things: a rule filed against `spacecraft.n.01` has to be able to match
    the room somebody is standing in.
    """
    try:
        return [str(k) for k in (obj.db.kinds or []) if k]
    except AttributeError:
        return []


def is_a(world_root, kind, wanted):
    """
    Whether `kind` is `wanted`, or a sort of it.

    The test a scope will be matched by: a rule about `vehicle.n.01` applies to
    a spacecraft because a spacecraft is a vehicle. Through the anchored chain,
    so an invented noun hanging under `device.n.01` is a device too.
    """
    kind, wanted = canonical(kind), canonical(wanted)
    if not kind or not wanted:
        return False
    return kind == wanted or wanted in ancestors(world_root, kind)


def any_is_a(world_root, obj_kinds, wanted):
    """Whether any of these kinds is `wanted`, or a sort of it."""
    return any(is_a(world_root, kind, wanted) for kind in (obj_kinds or []))


#: What an enclosure turned out to be. A room is an object and carries its own
#: states; a zone is a record in the world and does not, so the two cannot be
#: handed back as the same thing. Naming which it is beats making the caller
#: guess from the type.
ROOM, ZONE = "room", "zone"


def enclosure(obj, wanted, world_root=None):
    """
    The nearest place around `obj` that is a `wanted`, as (what, handle).

    `(ROOM, room)` or `(ZONE, zone_id)`, or `(None, None)`. Outward from where
    the thing is: the room first, then the zone the room is in, then that
    zone's parent, and so on to the world.

    This is what makes "the ship I am in" sayable. A one-room ship is a room of
    kind `spacecraft.n.01`; a ship with a bridge and an engine room is a zone
    of that kind; both answer here, and a caller asking for its condition does
    not have to know which it was. See docs/rulebooks-from-inform.md 5.4.
    """
    from world import zones

    room = obj if getattr(obj, "destination", None) is None and _is_room(obj) \
        else getattr(obj, "location", None)
    if room is None:
        return None, None
    if world_root is None:
        world_root = getattr(room.db, "world_root", None)

    if any_is_a(world_root, of(room), wanted):
        return ROOM, room

    zone_id = zones.slugify(getattr(room.db, "zone", "") or "")
    while zone_id and zone_id != zones.ROOT:
        if is_a(world_root, zones.kind_of(world_root, zone_id), wanted):
            return ZONE, zone_id
        zone_id = zones.parent_of(world_root, zone_id)
    return None, None


def _is_room(obj):
    """
    True for a place rather than a thing in one.

    Duck-typed on having nowhere to be: a room is the thing at the top. An
    exit, a character and an object all have a location and fall through to it,
    which is what the walk wants anyway.
    """
    return obj is not None and getattr(obj, "location", None) is None
