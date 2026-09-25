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

#: The rulebook that runs because something became true rather than because
#: somebody tried something. Kept out of PHASES on purpose: `rule_gen` offers
#: PHASES to a model asked about a verb, and this is never an answer to that
#: question. See world/becoming.py and docs/becoming-and-time.md §6.
BECOMES = "becomes"
STORED_PHASES = PHASES + (BECOMES,)

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
          outcome=None, source="generated", why="", overrides=None,
          evidence=None, report=""):
    """
    A rule with every slot present, so nothing downstream has to guess.

    `action` of None means every action, which is how a world says "nothing
    works while you are dead" once instead of once per verb.

    The last three carry provenance, and exist so that a *proposal* needs no
    storage of its own. `listed: false` already meant "in the book, not in
    force"; a suggestion is that plus a reason somebody can read, the rule it
    would override, and the counts that prompted it. Empty for every rule a
    world wrote for itself. See world/suggest.py and
    docs/rulebooks-from-inform.md 10.1.
    """
    return {
        "id": "",
        "name": str(name or ""),
        "phase": phase if phase in STORED_PHASES else CHECK,
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
        "why": str(why or ""),
        "overrides": overrides,
        "evidence": dict(evidence or {}),
        # What a becomes rule says when it fires, as an event template. It
        # never calls a model: a world's clock would otherwise be a paid tick.
        "report": str(report or ""),
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
    record["phase"] = (record["phase"] if record["phase"] in STORED_PHASES
                       else CHECK)
    record["scope"] = _clean_scope(record.get("scope"))
    if record["phase"] == BECOMES:
        # A becomes rule has no action: it runs because something became
        # true, not because anybody tried anything.
        record["action"] = None
        if record.get("report"):
            from world import events

            record["report"] = events.repair(record["report"])
    # Nodes tidied and held to their caps on the way in, whoever wrote the
    # rule. A condition that cannot be stored is dropped and logged rather
    # than kept to evaluate as nothing for ever.
    from world import conditions

    for field in ("conditions", "when"):
        kept, refused = conditions.normalise_all(record.get(field))
        if refused:
            logger.log_info(f"rules: dropped {len(refused)} unusable "
                            f"{field} from a rule: {refused!r}")
        record[field] = kept
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
    if record["phase"] == BECOMES:
        # A rule about a place may watch the clock, and a new boundary wants
        # the world's timer set afresh. See world/becoming.py.
        from world import becoming

        becoming.arm_clock(world_root)
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


#: What a filled-in `create_object` effect keeps from the item generator's
#: answer: everything `clothing.create` reads, except the name, which stays
#: as the rule wrote it so that a goal matching on it still matches.
CREATED_FIELDS = ("description", "kind", "kinds", "qualifiers", "sense",
                  "under", "affordances", "holds", "states", "takeable",
                  "clothing_type", "wearstyle", "trait_bonuses", "bonus_when",
                  "bonus_while")


def thin_creation(effect):
    """True for a `create_object` effect that names a thing and no more."""
    try:
        return (str(effect.get("type") or "") == "create_object"
                and bool(str(effect.get("name") or "").strip())
                and not effect.get("kind") and not effect.get("affordances"))
    except AttributeError:
        return False


def fill_created(world_root, rule_id, name, spec):
    """
    Keep what the item generator said a rule's thing is, on the rule.

    Every `create_object` effect in the rule that still names `name` and no
    more is filled in from `spec`, so the thing is built the same way each
    time the rule fires, with no model asked. The name the rule wrote is kept;
    a description the rule wrote is kept too. Answers how many were filled.
    """
    store = _store(world_root)
    rule = store.get(str(rule_id))
    if rule is None:
        return 0
    wanted = str(name or "").strip().lower()
    filled = 0

    def fill(effects):
        nonlocal filled
        out = []
        for effect in effects or []:
            if (thin_creation(effect)
                    and str(effect.get("name")).strip().lower() == wanted):
                effect = dict(effect)
                for field in CREATED_FIELDS:
                    if field not in spec or spec[field] in (None, "", []):
                        continue
                    if field == "description" and effect.get("description"):
                        continue
                    effect[field] = spec[field]
                filled += 1
            out.append(effect)
        return out

    effects = rule.get("effects")
    if hasattr(effects, "items"):
        rule["effects"] = {outcome: fill(branch)
                           for outcome, branch in effects.items()}
    else:
        rule["effects"] = fill(effects)
    if filled:
        store[str(rule_id)] = rule
        setattr(world_root.db, ATTR, store)
    return filled


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

    def __init__(self, world_root, action, bound=None, actor=None, room=None):
        from world import zones

        self.world_root = world_root
        self.action = str(action or "")
        self.bound = dict(bound or {})
        self.actor = actor
        # Given outright when there is no actor to work it out from: a becomes
        # rule about a lamp, or about a room, has nobody acting.
        self.room = room if room is not None else (
            getattr(actor, "location", None) if actor else None)
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


def gather(world_root, action, bound=None, actor=None, phase=None,
           guarded=True, words=None):
    """
    Every rule that applies to this attempt, most specific first.

    Dict lookups and set tests: no inference, no fixpoint, and bounded by the
    number of scopes in play rather than by how many rules a world holds.

    `guarded=False` matches scope and leaves `when` untested, for the after
    phase: which after rules are about an attempt is settled where it
    happened, and whether each follows is asked once carry-out has run. See
    docs/becoming-and-time.md 6.8.

    `words` is what the player typed for each role, which a guard may ask
    about with `called`. It is the only way a rule can be selected for a thing
    that does not exist: everything else here resolves a role to an object
    first. See `conditions._p_called`.
    """
    from world import conditions

    attempt = Attempt(world_root, action, bound, actor)
    ctx = conditions.context(bound, actor, world_root, action, words=words)
    found = []
    for rule in _store(world_root).values():
        if not rule.get("listed", True):
            continue
        if phase and rule.get("phase") != phase:
            continue
        if rule.get("phase") == BECOMES and phase != BECOMES:
            continue             # never part of an attempt's book
        wanted = rule.get("action")
        if wanted and wanted != attempt.action:
            continue
        tier = matches(rule, attempt)
        if tier is None:
            continue
        if guarded and not guards_pass(rule, ctx):
            continue
        found.append((rank(rule, tier, world_root), rule))
    ordered = [rule for _key, rule in sorted(found, key=lambda pair: pair[0])]
    if phase == BECOMES:
        # Most general first, the reverse of everywhere else. Elsewhere rank
        # picks a winner; here every rule that became true fires and nothing
        # wins, so order only decides whose effects land last -- and the
        # specific rule should have the last word. See docs 6.3.
        ordered.reverse()
    return ordered


def guards_pass(rule, ctx):
    """Whether every one of a rule's `when` conditions holds in `ctx`."""
    from world import conditions

    return all(conditions.evaluate(c, ctx) for c in (rule.get("when") or []))


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
                phase=None, guarded=True, words=None):
    """
    Every rule an attempt runs, in order: the world's own, plus the learned.

    The one call the pipeline makes. Seeds the standard rules if this world
    has never had them, folds in whatever the old generator learned about this
    verb, and hands back one ordered list per phase.
    """
    from world import standard_rules

    standard_rules.seed(world_root)
    found = gather(world_root, action, bound, actor, phase=phase,
                   guarded=guarded, words=words)
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


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`list_rules` and `show_rule`: the rulebook, for a model to read."""
    import json

    from world import toolbox as tb

    def listing(ctx, args):
        action = str(args.get("action") or "").strip().lower()
        rules = [rule for rule in all_rules(ctx.world_root)
                 if not action or rule.get("action") == action]
        return tb.paged(
            [f"{rule.get('id')} {rule.get('phase')} "
             f"{rule.get('action') or 'every action'} at "
             f"{said_scope(rule.get('scope'), ctx.world_root)} -- "
             f"{rule.get('name') or ''}"
             + ("" if rule.get("listed", True) else " (suspended)")
             for rule in rules], args, "rules")

    def showing(ctx, args):
        from evennia.utils.dbserialize import deserialize

        rule = get(ctx.world_root, str(args.get("id") or "").strip())
        if rule is None:
            return "This world has no rule by that id."
        return json.dumps(deserialize(rule), indent=1, default=str)

    def rooted(ctx):
        return ctx.world_root is not None

    return [
        tb.Tool("list_rules",
                "The rules this world holds: what each is about, where it "
                "applies, and what it says.",
                tb.params({**tb.PAGE, "action": {
                    "type": "string",
                    "description": "Optional. Only the rules about this verb"}}),
                tb.answering(listing), doing="reading the rulebook",
                looks=True, available=rooted),
        tb.Tool("show_rule", "One rule in full: its conditions and effects.",
                tb.params({"id": {"type": "string",
                                  "description": "The rule's id, like r12"}},
                          ["id"]),
                tb.answering(showing), doing="reading a rule", looks=True,
                available=rooted),
    ]
