"""
Where a rule lives, and which rule wins.

A verb rule today is one object per verb per world, so `power` means one thing
everywhere and `launch` cannot name the thing it launches. A rulebook is the
other arrangement: many small rules, each filed against whatever it is a fact
about -- this object, this sort of thing, this room, this area, the world --
gathered per attempt and ordered most specific first.

Nothing here runs a rule. Gathering and ordering are the half that can be
decided for nothing and tested without a model, and they are the half where a
mistake is most expensive: if the order is wrong then `power datapad` powers
the ship you happen to be standing in, and no amount of good rule-writing
saves it. Running them is the cutover, phase 7.

**One store, not five.** The specification has rules living with their scopes --
a kind's rules in its spec, a room's on the room. This keeps them in one map on
the world root with the scope as a field, because the scope is already the
single statement of what a rule is about, and five stores plus an index is five
places to fall out of step. What that arrangement bought was locality, and a
filter over one map gives the same answer: `help bottle` lists the rules whose
scope is that kind. What it cost is that deleting an object no longer takes its
rules with it, so `gather` skips a rule whose object has gone and `orphans`
reports them.

**`about` decides what a scope is matched against**, and it is not decoration.
A rule scoped to `spacecraft.n.01` might mean the ship you are standing in or
a model spaceship on the shelf, and those are different rules with different
precedence. Saying which is the difference between `power datapad` powering the
datapad and powering the ship.
"""

import time

from evennia.utils import logger

#: Where a world keeps its rules, and the counter that names them.
ATTR = "rules"
COUNTER = "rule_counter"

#: The rulebooks an attempt runs, in the order it runs them. `report` is the
#: narration that already exists and is not stored here.
INSTEAD, CHECK, CARRY_OUT, AFTER = "instead", "check", "carry_out", "after"
PHASES = (INSTEAD, CHECK, CARRY_OUT, AFTER)

#: What a scope may be filed against. Every one is a closed identifier: a
#: synset, a zone id, a dbref, or the world. There is no free text in a scope,
#: so a scope cannot drift the way an affordance list drifted.
OBJECT, KIND, ROOM, ZONE, WORLD = "object", "kind", "room", "zone", "world"
SCOPES = (OBJECT, KIND, ROOM, ZONE, WORLD)

#: What a rule's scope is matched against. The roles are what a player named;
#: `here`, `zone` and `enclosure` are places nobody named.
HERE, ANY_ZONE, ENCLOSURE = "here", "zone", "enclosure"
PLACES = (HERE, ANY_ZONE, ENCLOSURE)


def _store(world_root):
    from evennia.utils.dbserialize import deserialize

    if not world_root:
        return {}
    return dict(deserialize(getattr(world_root.db, ATTR, None)) or {})


def all_rules(world_root):
    """Every rule this world holds, listed or not, oldest first."""
    return sorted(_store(world_root).values(),
                  key=lambda r: (r.get("born", 0), r.get("id", "")))


def get(world_root, rule_id):
    """One rule by its id, or None."""
    return _store(world_root).get(str(rule_id))


def blank(action=None, phase=CHECK, scope=None, about="direct", name="",
          when=None, conditions=None, effects=None, contest=None,
          outcome=None, source="generated"):
    """
    A rule with every slot present, so nothing downstream has to guess.

    `action` of None means every action, which is how a world says "nothing
    works while you are dead" once instead of once per verb.
    """
    return {
        "id": "",
        "name": str(name or ""),
        "phase": phase if phase in PHASES else CHECK,
        "action": str(action) if action else None,
        "scope": dict(scope or {WORLD: True}),
        "about": str(about or "direct"),
        "when": list(when or []),
        "conditions": list(conditions or []),
        "effects": list(effects or []),
        "contest": contest,
        "outcome": outcome,
        "listed": True,
        "source": str(source),
        "born": time.time(),
    }


def add(world_root, rule):
    """
    File a rule, giving it an id. Answers with the rule as stored.

    Ids are sequential rather than random so that the tie-break at the end of
    the sort is stable and readable: `r7` fired before `r8` because it was
    written first, which is what somebody reading `rules` needs to know.
    """
    if not world_root:
        return None
    record = dict(blank(), **{k: v for k, v in dict(rule or {}).items()
                              if k in blank()})
    record["phase"] = record["phase"] if record["phase"] in PHASES else CHECK
    record["scope"] = _clean_scope(record.get("scope"))
    if record["action"]:
        from world import verbs

        record["action"] = verbs.canonical_verb(str(record["action"]))

    number = int(getattr(world_root.db, COUNTER, 0) or 0) + 1
    setattr(world_root.db, COUNTER, number)
    record["id"] = f"r{number}"
    if not record.get("born"):
        record["born"] = time.time()

    store = _store(world_root)
    store[record["id"]] = record
    setattr(world_root.db, ATTR, store)
    logger.log_info(
        f"rules: {record['id']} {record['phase']} "
        f"{record['action'] or 'any action'} at {said_scope(record['scope'])}"
        + (f" -- {record['name']}" if record["name"] else ""))
    return record


def _clean_scope(scope):
    """A scope with only one closed key in it, or the world."""
    try:
        scope = dict(scope or {})
    except (TypeError, ValueError):
        return {WORLD: True}
    for key in SCOPES:
        if key in scope:
            return {key: scope[key]}
    return {WORLD: True}


def set_listed(world_root, rule_id, listed=True):
    """
    Take a rule out of its rulebook, or put it back.

    Inform's `is not listed in`, and the repair this design offers instead of
    revision: a rule that turns out to be wrong stops applying without being
    deleted, so the world's history stays legible and a mistake is reversible.
    """
    store = _store(world_root)
    rule = store.get(str(rule_id))
    if not rule:
        return None
    rule["listed"] = bool(listed)
    store[str(rule_id)] = rule
    setattr(world_root.db, ATTR, store)
    return rule


# ---------------------------------------------------------------------------
# Which rules are about this attempt
# ---------------------------------------------------------------------------

class Attempt:
    """
    One verb attempt, as far as gathering is concerned.

    Holds the places once rather than walking them per rule: a world with two
    hundred rules would otherwise climb the zone chain two hundred times to
    answer the same question.
    """

    def __init__(self, world_root, action, bound=None, actor=None):
        from world import zones

        self.world_root = world_root
        self.action = str(action or "")
        self.bound = dict(bound or {})
        self.actor = actor
        self.room = getattr(actor, "location", None) if actor else None
        self.zone_ids = []
        zone_id = zones.slugify(getattr(self.room.db, "zone", "") or "") \
            if self.room else ""
        while zone_id and zone_id != zones.ROOT:
            self.zone_ids.append(zone_id)
            zone_id = zones.parent_of(world_root, zone_id)

    def things(self, about):
        """The objects a scope with this `about` is matched against."""
        if about in self.bound:
            return [self.bound[about]]
        if about == "actor" and self.actor is not None:
            return [self.actor]
        return []


def gather(world_root, action, bound=None, actor=None, phase=None):
    """
    Every rule that applies to this attempt, most specific first.

    Dict lookups and set tests: no inference, no fixpoint, and bounded by the
    number of scopes in play rather than by how many rules a world holds.
    """
    from world import conditions

    attempt = Attempt(world_root, action, bound, actor)
    ctx = conditions.context(bound, actor, world_root)
    found = []
    for rule in _store(world_root).values():
        if not rule.get("listed", True):
            continue
        if phase and rule.get("phase") != phase:
            continue
        wanted = rule.get("action")
        if wanted and wanted != attempt.action:
            continue
        tier = matches(rule, attempt)
        if tier is None:
            continue
        if not all(conditions.evaluate(c, ctx) for c in (rule.get("when") or [])):
            continue
        found.append((rank(rule, tier, world_root), rule))
    return [rule for _key, rule in sorted(found, key=lambda pair: pair[0])]


def tier_of(rule):
    """
    How specific a rule is, from its scope and what it is about.

    Derived rather than discovered, so that a listing with no attempt in front
    of it sorts the same way an attempt would -- which is the whole use of
    `rules`: seeing the order before something goes wrong rather than after.

        0  this one thing
        1  the sort of a thing somebody named
        2  the sort of place they are standing in
        3  this room
        4  this area
        5  everywhere

    Tiers 1 and 2 are the same scope and differ only by `about`, which is why
    that slot is load-bearing: a rule about `spacecraft.n.01` may mean the ship
    you are in or a model on the shelf, and those want different precedence.
    """
    scope = rule.get("scope") or {}
    about = str(rule.get("about") or "direct")
    if OBJECT in scope:
        return 0
    if KIND in scope:
        return 2 if about in PLACES else 1
    if ROOM in scope:
        return 3
    if ZONE in scope:
        return 4
    return 5


def matches(rule, attempt):
    """
    Which tier this rule matched at, or None if it does not apply.

    The tier is the answer as much as the yes: a rule scoped to a kind means
    something different depending on whether it matched a thing the player
    named or the place they are standing in, and the difference is exactly
    `power datapad` against `power`.
    """
    from world import kinds

    scope = rule.get("scope") or {}
    about = str(rule.get("about") or "direct")
    root = attempt.world_root

    tier = tier_of(rule)

    if WORLD in scope:
        return tier

    if ROOM in scope:
        here = attempt.room
        return tier if here is not None and here.id == scope[ROOM] else None

    if ZONE in scope:
        return tier if scope[ZONE] in attempt.zone_ids else None

    if OBJECT in scope:
        for thing in attempt.things(about) or list(attempt.bound.values()):
            if getattr(thing, "id", None) == scope[OBJECT]:
                return tier
        return None

    if KIND in scope:
        wanted = scope[KIND]
        # A place, when the rule says it is about one. This is the enclosure
        # case: "aboard a ship" rather than "a model ship on the shelf".
        if about in PLACES:
            what, _handle = kinds.enclosure(attempt.actor, wanted,
                                            world_root=root)
            if what is None and attempt.room is not None:
                if kinds.any_is_a(root, kinds.of(attempt.room), wanted):
                    return tier
                return None
            return tier if what is not None else None
        for thing in attempt.things(about):
            if kinds.any_is_a(root, kinds.of(thing), wanted):
                return tier
        return None

    return None


def rank(rule, tier=None, world_root=None):
    """
    Where a rule sorts. Lower is more specific, and every tie is broken.

    Written as one tuple rather than a comparison so that it can be printed
    beside a rule in `rules`: "why did that one win" must never be a mystery,
    and Inform's hardest bug class is exactly this.

        named action before any action
        the tier it matched at -- see `matches`
        deeper in the taxonomy, or deeper in the zone tree, first
        a guarded rule before an open one, and more guards first
        older first
        and the id last, so no two rules can ever tie
    """
    from world import kinds, lexicon, zones

    scope = rule.get("scope") or {}
    if tier is None:
        tier = tier_of(rule)
    depth = 0
    if KIND in scope:
        depth = -len(kinds.ancestors(world_root, scope[KIND]))
    elif ZONE in scope and world_root is not None:
        depth = -zones.depth(world_root, scope[ZONE])

    guards = rule.get("when") or []
    return (
        0 if rule.get("action") else 1,
        tier,
        depth,
        0 if guards else 1,
        -len(guards),
        rule.get("born", 0),
        rule.get("id", ""),
    )


def orphans(world_root):
    """
    Rules whose object or room no longer exists.

    The cost of keeping every rule in one map instead of on the thing it is
    about: deleting a chest no longer deletes the rule about that chest. They
    are skipped when gathering and reported here, which `worldcheck` can say
    out loud.
    """
    from evennia.objects.models import ObjectDB

    found = []
    for rule in all_rules(world_root):
        scope = rule.get("scope") or {}
        for key in (OBJECT, ROOM):
            if key not in scope:
                continue
            if not ObjectDB.objects.filter(id=scope[key]).exists():
                found.append(rule)
    return found


# ---------------------------------------------------------------------------
# Saying where a rule lives
# ---------------------------------------------------------------------------

def said_scope(scope, world_root=None):
    """A scope as a person would read it, for `rules` and for the log."""
    from world import lexicon

    scope = scope or {}
    if WORLD in scope:
        return "everywhere"
    if KIND in scope:
        return f"any {lexicon.word_of(scope[KIND])}"
    if ZONE in scope:
        from world import zones

        name = zones.name_of(world_root, scope[ZONE]) if world_root else ""
        return f"in {name or scope[ZONE]}"
    if ROOM in scope:
        return f"in room #{scope[ROOM]}"
    if OBJECT in scope:
        return f"one thing (#{scope[OBJECT]})"
    return "nowhere in particular"


# ---------------------------------------------------------------------------
# Reading a learned verb rule as a rulebook
# ---------------------------------------------------------------------------

def from_verb_rule(rule, action, world_root=None):
    """
    One learned verb rule, as the phase-rules it amounts to.

    The bridge across the cutover. A verb rule is preconditions plus effects
    for a whole world, which is exactly a stack of world-scope check rules and
    one world-scope carry-out rule -- so the phases can run on everything a
    world already knows, before any generator has been taught to write rules
    directly. Phase 8 replaces the conversion with the real thing.

    Computed rather than stored, deliberately. Storing it would mean the same
    rule written down twice, in two shapes, with nothing keeping them in step,
    and drift between two copies of one fact is the failure this whole design
    exists to end.
    """
    from world import conditions

    try:
        rule = dict(rule or {})
    except (TypeError, ValueError):
        return []
    if not rule:
        # No learned rule at all, which the pipeline says by handing over an
        # empty one. Distinct from a learned rule that happens to do nothing:
        # a world that decided `sing` has no effects still decided something,
        # and its carry-out is what stops the verb being asked about again.
        # Bridging {} would put a nameless do-nothing carry-out in every book
        # -- harmless while a real rule outranks it, and a verb that silently
        # succeeds when one does not.
        return []
    if not rule.get("valid", True):
        return [blank(
            action=action, phase=CHECK, scope={WORLD: True},
            name=str(rule.get("reason") or "you cannot do that"),
            conditions=[{"subject": "world", "never": True,
                         "because": str(rule.get("reason")
                                        or "You can't do that.")}],
            source="learned")]

    out = []
    for condition in conditions.from_requires(rule.get("requires")):
        out.append(blank(
            action=action, phase=CHECK, scope={WORLD: True},
            about=str(condition.get("subject") or "direct"),
            name=conditions.describe(condition),
            conditions=[condition], source="learned"))
    out.append(blank(
        action=action, phase=CARRY_OUT, scope={WORLD: True},
        name=f"what {action} does", effects=rule.get("effects") or [],
        contest=rule.get("check"), source="learned"))
    for index, entry in enumerate(out):
        entry["id"] = f"learned:{action}:{index}"
    return out


def for_attempt(world_root, action, bound=None, actor=None, verb_rule=None,
                phase=None):
    """
    Every rule an attempt runs, in order: the world's own, plus the learned.

    The one call the pipeline makes. Seeds the standard rules if this world
    has never had them, folds in whatever the old generator learned about this
    verb, and hands back one ordered list per phase.
    """
    from world import standard_rules

    standard_rules.seed(world_root)
    found = gather(world_root, action, bound, actor, phase=phase)
    if verb_rule is None:
        return found

    attempt = Attempt(world_root, action, bound, actor)
    converted = []
    for rule in from_verb_rule(verb_rule, action, world_root):
        if phase and rule.get("phase") != phase:
            continue
        tier = matches(rule, attempt)
        if tier is None:
            continue
        converted.append((rank(rule, tier, world_root), rule))
    if not converted:
        return found

    ranked = [(rank(r, matches(r, attempt) or 5, world_root), r)
              for r in found] + converted
    return [rule for _key, rule in sorted(ranked, key=lambda pair: pair[0])]
