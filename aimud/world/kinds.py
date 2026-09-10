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
description and cannot drift. Generated worlds are full of nouns no dictionary
has heard of, and those keep their bare noun as a kind and are anchored under
the nearest real synset, so a greatsword still lands somewhere closed.

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
    reduced to the singular so that "bottles" and "bottle" are not two kinds.
    """
    from world import lexicon

    kind = str(kind or "").strip().lower()
    if not kind:
        return ""
    if lexicon.ancestors(kind):
        return kind            # a real synset, and it knows its own name
    return lexicon.head_noun(kind)


def prune(kinds):
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
    from world import lexicon

    kept = []
    for kind in [canonical(k) for k in (kinds or []) if canonical(k)]:
        if kind in kept:
            continue
        implied = False
        for other in kept:
            if kind in lexicon.ancestors(other) or other in lexicon.ancestors(kind):
                implied = True
                break
        if not implied:
            kept.append(kind)
    return kept


# ---------------------------------------------------------------------------
# What a kind affords
# ---------------------------------------------------------------------------

def floor(kind):
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

    return af.normalise(sorted(lexicon.implied_affordances(kind)))


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
    for kind in prune(kinds):
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


def remember(world_root, kind, declared, accepts=()):
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

    # The floor is applied last so that it wins: a model may add to what a
    # chest can do and may not talk it out of being a container.
    decided = af.merge(af.normalise(declared), floor(kind))
    takes = ({str(p).lower() for p in (accepts or [])} | _placement_floor(kind)
             ) & set(PLACEMENT)
    if world_root:
        store = dict(getattr(world_root.db, ATTR, None) or {})
        store[kind] = {"affordances": decided, "holds": sorted(takes)}
        setattr(world_root.db, ATTR, store)
        logger.log_info(
            f"kinds: {kind} settled as "
            f"{sorted(af.afforded(decided)) or 'nothing in particular'}"
            + (f", holds things {'/'.join(sorted(takes))}" if takes else "")
        )
    return decided


def resolve(world_root, kinds, declared=None, accepts=()):
    """
    What a thing of these kinds affords.

    The union across its kinds, with `declared` settling any kind this world
    is meeting for the first time. An object made of a kind that already
    exists costs nothing here and cannot disagree with its siblings; an object
    that introduces one teaches the world, once.
    """
    kinds = prune(kinds)
    if not kinds:
        return af.normalise(declared)

    if len(kinds) == 1:
        # The ordinary case, and the one the drift was in. What the generator
        # said settles the kind if the kind is new, and is ignored if it is
        # not: the seventy-third bottle does not get an opinion.
        return remember(world_root, kinds[0], declared, accepts)

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
                    else floor(kind))
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
    for kind in prune(obj_kinds):
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
    ordered = prune(obj_kinds)
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
    ordered = prune(obj_kinds)
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
    for kind in prune(obj_kinds):
        entry = spec(world_root, kind) or {}
        try:
            seen |= {str(s) for s in (entry.get("states") or [])}
        except (AttributeError, TypeError, ValueError):
            continue
    return seen


def vocabulary(world_root):
    """Every kind this world has settled, for a prompt that should reuse one."""
    return sorted((getattr(world_root.db, ATTR, None) or {}) if world_root else {})
