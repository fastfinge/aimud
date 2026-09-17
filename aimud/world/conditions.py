"""
One way of saying what must be true, for everything that needs to say it.

There were two. A verb rule wrote its preconditions keyed by role --
`{"direct": {"has": ["read"], "lacks": ["burning"]}}` -- and `verbs.check`
tested them. A goal wrote conditions tagged by type -- `{"type": "state",
"object": "lantern", "is": ["lit"]}` -- and `goals._test` tested those. The two
describe the same facts about the same world, and `goals.py` says so in its own
docstring: "the condition vocabulary deliberately mirrors verb preconditions".

Mirroring by hand is not a mechanism, and they drifted. A goal can ask whether
something is worn and a rule cannot. A rule can ask for a trait by range and a
goal asks differently. `planner._effect_achieves` has to guess at the
correspondence between the two every time it reads one against the other.

So: one form, three operations, and everything else becomes a caller.

    evaluate(condition, context)   -> True or False
    describe(condition, context)   -> "the ship is not powered"
    achieves(effect, condition)    -> would that effect satisfy this?

`evaluate` serves verb preconditions, rule guards, quest testing and goal
testing. `describe` serves refusals, `help`, quest listings and the `rules`
command. `achieves` serves the planner. Today those are three partial
implementations that have to agree by hand.

**A condition is a subject and a predicate.** The subject says what is being
asked about, the predicate says what must be true of it:

    {"subject": "direct", "is": ["powered"]}
    {"subject": "actor", "trait": "piloting", "min": 10}
    {"subject": {"enclosure": "spacecraft.n.01"}, "lacks": ["damaged"]}

The subject is the half that is new, and the half `launch` needed: a rule can
now be about the ship somebody is standing in, which is not a word anybody
typed. See docs/rulebooks-from-inform.md 5.4.

**Describing has two moods**, and it is worth knowing why rather than
discovering it. A goal is a want -- "be carrying the brass key" -- and a
refusal is a complaint -- "You are not holding the brass key." Same condition,
same evaluation, two sentences, because a quest listing and a refused verb are
read by somebody in two different frames of mind. `verbs.check` and
`goals._test` each wrote one of them and neither could produce the other.
"""

from collections import namedtuple

#: What a condition can be about. The six roles are what a player named, and
#: the rest are what nobody named but a rule may still mean.
ROLES = ("actor", "direct", "instrument", "target", "container", "source")

#: How a subject may be written, beyond a bare role.
#:
#: here            the room
#: {"enclosure": kind}  the nearest room or zone of that sort, outward
#: {"zone": true}  the innermost zone, whatever sort it is
#: world           the world itself
#: {"named": ...}  a thing found by name, which is how goals refer to things
#: {"of_kind": ...} the nearest thing of a sort, for a goal that wants "a cake"
HERE, WORLD = "here", "world"

#: Which mood `describe` is speaking in. A want and a complaint are the same
#: fact said to somebody in two different frames of mind -- and `abstract` is
#: the same fact said with no world in front of it at all, which is what `help`
#: and the `rules` listing need: they print what a rule requires without
#: evaluating it against anybody.
WANT, UNMET, ABSTRACT = "want", "unmet", "abstract"

#: What was found when a subject was resolved. Not every subject is an object:
#: a zone is a record in the world and carries its states there, and the world
#: itself is neither. Naming which it is beats making each predicate guess.
THING, ROOM, ZONE, NOWHERE = "thing", "room", "zone", "nowhere"

#: Everything a condition needs in order to be tested. Bundled so that adding
#: something later does not change every signature.
#:
#: `action` is the one field that is not about the world: it is which action is
#: being attempted, and only one predicate reads it. `reachable_by` has to,
#: because how near you must be to a thing is a fact about the action rather
#: than about the thing -- reading a notice across a room and prising it off the
#: wall ask different things of the same notice. Everything that tests a
#: condition outside an attempt (a quest, a goal, a `rules` listing) leaves it
#: empty, and the predicate then asks for reach, which is the safe answer.
#:
#: `room` is where it is being asked, when that is not simply wherever the actor
#: stands now. An after rule's guards are tested once carry-out has run, and a
#: carry-out may have moved the actor -- but `here` in a rule about launching
#: still means the bridge the ship was launched from. Empty for everything else,
#: and then `here` is the actor's room as it always was.
Context = namedtuple("Context", "bound actor world_root action room")
Context.__new__.__defaults__ = (None, None, None, "", None)


def context(bound=None, actor=None, world_root=None, action="", room=None):
    """The world as a condition sees it."""
    if world_root is None and actor is not None:
        where = room or getattr(actor, "location", None)
        world_root = getattr(where.db, "world_root", None) if where else None
    return Context(dict(bound or {}), actor, world_root, str(action or ""),
                   room)


def _still_here(obj):
    """
    The object, or None if it has been deleted since it was bound.

    A carry-out can destroy what the attempt was about, and an after rule is
    asked about the world afterwards. Evennia leaves the Python object behind
    with its primary key cleared, so a role bound to a burnt note still holds
    something, and every predicate would go looking in a row that is gone.
    """
    if obj is not None and getattr(obj, "pk", True) is None:
        return None
    return obj


# ---------------------------------------------------------------------------
# Who a condition is about
# ---------------------------------------------------------------------------

class Subject:
    """
    Whatever a condition turned out to be about, and how to ask it things.

    A thin face over four different sorts of answer -- an object, a room, a
    zone record, the world -- so that a predicate can ask for states or kinds
    without knowing which it got. `found` is false when the subject names
    nothing here, which is itself an answer: a condition about a thing that is
    not present is not met.
    """

    def __init__(self, what=NOWHERE, obj=None, zone_id="", ctx=None):
        self.what = what
        self.obj = obj
        self.zone_id = zone_id
        self.ctx = ctx or Context()

    @property
    def found(self):
        return self.what != NOWHERE

    def states(self):
        """
        What is true of this subject, group defaults included.

        `verbs.implied_states` rather than `verbs.states`, because a rule asking
        whether somebody is `alive` is asking what is true of them and not what
        somebody remembered to write down. See the note on `life_status`.
        """
        from world import verbs, zones

        if self.what == ZONE:
            return zones.states(self.ctx.world_root, self.zone_id)
        if self.obj is not None:
            return verbs.implied_states(self.obj, self.ctx.world_root)
        return set()

    def kinds(self):
        from world import kinds as kinds_mod
        from world import zones

        if self.what == ZONE:
            settled = zones.kind_of(self.ctx.world_root, self.zone_id)
            return [settled] if settled else []
        return kinds_mod.of(self.obj) if self.obj is not None else []

    def affordances(self):
        from world import verbs

        return verbs.affordances(self.obj) if self.obj is not None else set()

    def name(self, looker=None):
        """What to call it in a sentence."""
        from world import zones

        if self.what == ZONE:
            return zones.name_of(self.ctx.world_root, self.zone_id) \
                or self.zone_id
        if self.what == WORLD:
            return "this world"
        if self.obj is None:
            return "it"
        if self.obj is self.ctx.actor:
            return "you"
        try:
            return self.obj.get_display_name(looker or self.ctx.actor)
        except AttributeError:
            return str(getattr(self.obj, "key", "it"))

    def is_actor(self):
        return self.obj is not None and self.obj is self.ctx.actor


def resolve(subject, ctx):
    """The Subject a condition is about, found or not."""
    from world import kinds as kinds_mod

    if subject in (None, ""):
        subject = "direct"

    if isinstance(subject, str):
        if subject == HERE:
            room = ctx.room or getattr(ctx.actor, "location", None)
            return Subject(ROOM, room, ctx=ctx) if room else Subject(ctx=ctx)
        if subject == WORLD:
            return Subject(WORLD, ctx.world_root, ctx=ctx)
        obj = ctx.actor if subject == "actor" else ctx.bound.get(subject)
        obj = _still_here(obj)
        return Subject(THING, obj, ctx=ctx) if obj is not None \
            else Subject(ctx=ctx)

    try:
        wanted = dict(subject)
    except (TypeError, ValueError):
        return Subject(ctx=ctx)

    if "enclosure" in wanted:
        what, handle = kinds_mod.enclosure(
            ctx.actor, wanted["enclosure"], world_root=ctx.world_root)
        if what == kinds_mod.ROOM:
            return Subject(ROOM, handle, ctx=ctx)
        if what == kinds_mod.ZONE:
            return Subject(ZONE, zone_id=handle, ctx=ctx)
        return Subject(ctx=ctx)

    if wanted.get("zone"):
        from world import zones

        room = getattr(ctx.actor, "location", None)
        zone_id = zones.slugify(getattr(room.db, "zone", "") or "") if room \
            else ""
        return Subject(ZONE, zone_id=zone_id, ctx=ctx) if zone_id \
            else Subject(ctx=ctx)

    if "named" in wanted or "of_kind" in wanted:
        obj = _find(wanted.get("named", ""), wanted.get("of_kind", ""), ctx)
        return Subject(THING, obj, ctx=ctx) if obj is not None \
            else Subject(ctx=ctx)

    return Subject(ctx=ctx)


def _find(name, kind, ctx):
    """
    A thing a goal referred to by name or by sort, or None.

    Nothing is found without somebody to look: `goals` searches outward from
    the actor, so with no actor there is no search to make. Describing a
    condition abstractly reaches here, and must not raise.
    """
    from world import goals

    if ctx.actor is None or ctx.world_root is None:
        return None
    if name:
        return goals.find_object(ctx.world_root, ctx.actor, name)
    if kind:
        return goals.find_of_kind(ctx.world_root, ctx.actor, kind)
    return None


# ---------------------------------------------------------------------------
# What must be true of it
# ---------------------------------------------------------------------------

def _listed(value):
    """A clause's value as a list, however few things it names.

    Asked for one condition a model writes one word rather than a list of one,
    and read as written that is not one requirement but six, one per letter --
    see `verbs.requirements`, which learned this the hard way -- and then
    `effects`, which had not, and coined a condition per letter of "sharpened"
    in somebody's world. One answer for all of them now.
    """
    from world.model_json import listed

    return listed(value)


#: Every predicate there is, in the order `predicate_of` looks for them.
PREDICATES = ("is", "lacks", "affords", "kind", "not_kind", "holds",
              "not_holds", "wears", "not_wears", "owned_by", "not_owned_by",
              "placed", "not_placed", "trait", "in_room", "not_in_room",
              "exists", "gone", "able", "reachable_by", "visible_to",
              "leads_to", "not_leads_to", "never", "unbound")


def predicate_of(condition):
    """Which predicate a condition uses, and what it names."""
    if not hasattr(condition, "keys"):
        return "", None
    for name in PREDICATES:
        if name in condition:
            return name, condition[name]
    return "", None


def evaluate(condition, ctx):
    """Whether this condition holds. The one test everything shares."""
    met, _said = _judge(condition, ctx, WANT)
    return met


# ---------------------------------------------------------------------------
# Joining conditions: `all` and `any`
# ---------------------------------------------------------------------------
#
# A list of conditions already means all of them, and it still does. What
# could not be said at all was "or": check rules accumulate, so "holding a key
# or a lockpick" had no form, not even as two rules. So a condition may be a
# node instead of a leaf -- {"any": [...]} or {"all": [...]} -- with no subject
# of its own, whose members are conditions or further nodes. `all` exists only
# to be used inside `any`. See docs/becoming-and-time.md 4.2.
#
# There is deliberately no `not`. Every predicate declares its own opposite
# instead (OPPOSITES, below), and `negate` works a mirror out when something
# needs one, so nothing that reads a condition ever meets a negation it has to
# carry the polarity of.

ALL, ANY = "all", "any"
COMBINATORS = (ALL, ANY)

#: How deep a stored condition may nest, and how many members one node may
#: hold. Past these a condition has stopped being a fact about the world and
#: started being a program, which basic-principles.md keeps out of reach.
MAX_DEPTH = 3
MAX_MEMBERS = 8


def node_of(condition):
    """
    (`all` or `any`, its members) for a node, and ("", None) for a leaf.

    Asked of whatever is stored, which comes back from an Evennia attribute as
    a _SaverDict holding a _SaverList -- a mapping and a sequence, but not a
    dict or a list -- so neither is tested for by type.
    """
    if not hasattr(condition, "keys"):
        return "", None
    for kind in COMBINATORS:
        if kind in condition:
            members = condition[kind]
            if isinstance(members, (str, bytes)) or hasattr(members, "keys"):
                return kind, []
            try:
                return kind, list(members)
            except TypeError:
                return kind, []
    return "", None


def _tidy(condition):
    """
    A condition with its nodes flattened and unwrapped, or None.

    A node of one member is that member; a node inside a node of the same kind
    is part of it; an empty node, or a leaf that asks nothing, is None. No caps
    are applied, because `negate` builds its answer through here and a mirror
    may be a level deeper than what it mirrors.
    """
    kind, members = node_of(condition)
    if not kind:
        try:
            leaf = dict(condition)
        except (TypeError, ValueError):
            return None
        return leaf if predicate_of(leaf)[0] else None
    kept = []
    for member in members:
        member = _tidy(member)
        if member is None:
            # One member nobody can evaluate spoils the node: dropping it from
            # an `any` would make the node harder to pass than was written, and
            # from an `all` easier.
            return None
        inner_kind, inner = node_of(member)
        if inner_kind == kind:
            kept.extend(inner)
        else:
            kept.append(member)
    if not kept:
        return None
    if len(kept) == 1:
        return kept[0]
    return {kind: kept}


def depth_of(condition):
    """How many nodes deep a condition goes. A leaf is 0."""
    kind, members = node_of(condition)
    if not kind:
        return 0
    return 1 + max((depth_of(m) for m in members), default=0)


def _widest(condition):
    """The most members any node in this condition holds."""
    kind, members = node_of(condition)
    if not kind:
        return 0
    return max([len(members)] + [_widest(m) for m in members])


def normalise(condition):
    """
    A condition fit to be stored, or None when it is not one.

    Tidied (see `_tidy`) and then held to MAX_DEPTH and MAX_MEMBERS. Refused
    rather than trimmed: a condition cut down to fit says something other than
    what was written.
    """
    tidy = _tidy(condition)
    if tidy is None:
        return None
    if depth_of(tidy) > MAX_DEPTH or _widest(tidy) > MAX_MEMBERS:
        return None
    return tidy


def normalise_all(conditions):
    """
    A list of conditions fit to be stored, and the ones that were not.

    Returns (kept, refused). A top-level `all` joins the list around it, since
    that is what the list already means.
    """
    kept, refused = [], []
    for condition in (conditions or []):
        tidy = normalise(condition)
        if tidy is None:
            refused.append(condition)
            continue
        kind, members = node_of(tidy)
        if kind == ALL:
            kept.extend(members)
        else:
            kept.append(tidy)
    return kept, refused


def leaves(condition, optional=False):
    """
    Every plain condition inside this one, as (leaf, optional) pairs.

    `optional` is true for a leaf that is only one way of passing -- anything
    under an `any` of more than one member -- which is what a reader looking
    for what a rule *demands* has to know. A state inside an `any` is required
    only if every other branch fails too.
    """
    kind, members = node_of(condition)
    if not kind:
        if hasattr(condition, "keys"):
            yield condition, optional
        return
    for member in members:
        yield from leaves(member,
                          optional or (kind == ANY and len(members) > 1))


#: The words a shared opening of several phrases must not end on, so that
#: "be carrying the key" and "be carrying the lockpick" join as "be carrying
#: the key or the lockpick" rather than "be carrying the key or lockpick".
_ARTICLES = frozenset(("a", "an", "the", "some"))


def _joined(phrases, word):
    """
    Several phrases as one, joined with `word` ("or", "and").

    The opening they share is said once. Read aloud, "be carrying the key or be
    carrying the lockpick" is a sentence somebody has to hold in their head
    twice; "be carrying the key or the lockpick" is not.
    """
    seen = []
    for phrase in phrases:
        phrase = str(phrase or "").strip()
        if phrase and phrase not in seen:
            seen.append(phrase)
    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]
    split = [phrase.split() for phrase in seen]
    common = 0
    while (all(len(words) > common + 1 for words in split)
           and len({words[common] for words in split}) == 1):
        common += 1
    while common and split[0][common - 1].lower() in _ARTICLES:
        common -= 1
    head = " ".join(split[0][:common])
    tails = [" ".join(words[common:]) for words in split]
    if len(tails) == 2:
        body = f"{tails[0]} {word} {tails[1]}"
    else:
        body = ", ".join(tails[:-1]) + f", {word} {tails[-1]}"
    return f"{head} {body}".strip()


def _judge_node(kind, members, ctx, mood, depth):
    """
    A node, evaluated and said.

    An `all` complains about its first unmet member, exactly as a list of
    conditions does. An `any` that fails makes one complaint out of what each
    branch wants -- "You need to be carrying the key or the lockpick." -- and
    never one per branch, which would read as though every one were required.
    """
    if depth > MAX_DEPTH * 2:
        return False, ""         # a guard, not a limit: `normalise` is that
    if kind == ALL:
        judged = [_judge(m, ctx, mood, depth + 1) for m in members]
        met = all(ok for ok, _said in judged)
        if mood == UNMET:
            return met, next((said for ok, said in judged if not ok), "")
        return met, _joined([said for _ok, said in judged], "and")

    judged = [_judge(m, ctx, WANT, depth + 1) for m in members]
    met = any(ok for ok, _said in judged)
    wants = _joined([said for _ok, said in judged], "or")
    if mood == UNMET:
        return met, (f"You need to {wants}." if wants and not met else "")
    return met, wants


# ---------------------------------------------------------------------------
# Opposites, and working out a mirror
# ---------------------------------------------------------------------------

#: Every predicate's exact opposite. Exact means two things, and every pair
#: here keeps both, since the pairs that already existed set the rule:
#:
#: * a list flips from "all of these" to "none of these" -- `is: [wet, cold]`
#:   is both, `lacks: [wet, cold]` is neither;
#: * a missing subject flips too -- `is` says no about a thing that is not
#:   there and `lacks` says yes.
#:
#: `unbound` and `trait` are their own opposites, with a value flipped: true
#: for false, and each bound for the exclusive bound on its other side.
OPPOSITES = {
    "is": "lacks", "lacks": "is",
    "holds": "not_holds", "not_holds": "holds",
    "wears": "not_wears", "not_wears": "wears",
    "placed": "not_placed", "not_placed": "placed",
    "in_room": "not_in_room", "not_in_room": "in_room",
    "kind": "not_kind", "not_kind": "kind",
    "leads_to": "not_leads_to", "not_leads_to": "leads_to",
    "owned_by": "not_owned_by", "not_owned_by": "owned_by",
    "exists": "gone", "gone": "exists",
    "unbound": "unbound",
    "trait": "trait",
}

#: The predicates that have no opposite, and why. A decision on the record
#: rather than a gap: `negate` refuses them, and a test fails for any
#: predicate that is in neither table.
UNNEGATABLE = {
    "affords": "it also asks about placement, and \"cannot be done to it\" is "
               "a different question from \"nobody said it can\"",
    "reachable_by": "it answers whether this action may touch a thing, and "
                    "excuses a role declared visible; the complement of an "
                    "excuse is not \"out of reach\"",
    "visible_to": "it answers whether this action may see a thing, and excuses "
                  "things the same way; darkness is the light trait",
    "able": "it is waived per action; the opposite of being free to act is "
            "being in a state that stops you, which is `is` on that state",
    "never": "its opposite is no condition at all",
}

#: Predicates whose value is a list meaning "all of these".
_LISTED = frozenset(("is", "lacks", "holds", "not_holds", "wears",
                     "not_wears"))

#: The four bounds a trait condition may carry. `min` and `max` include the
#: figure they name; `below` and `above` do not, which is what makes each the
#: exact opposite of the one on its other side.
TRAIT_BOUNDS = ("min", "max", "below", "above")
_FLIPPED_BOUND = {"min": "below", "below": "min", "max": "above",
                  "above": "max"}


def negate(condition):
    """
    The exact opposite of a condition, or None when it has none.

    Worked out, never stored, and never containing a `not`: a leaf becomes its
    opposite predicate, a list of several values becomes an `any` of their
    single opposites, and `all` and `any` swap (De Morgan). If any part refuses,
    the whole negation does. See docs/becoming-and-time.md 4.4.
    """
    kind, members = node_of(condition)
    if kind:
        flipped = []
        for member in members:
            mirror = negate(member)
            if mirror is None:
                return None
            flipped.append(mirror)
        if not flipped:
            return None
        return _tidy({ANY if kind == ALL else ALL: flipped})

    try:
        condition = dict(condition)
    except (TypeError, ValueError):
        return None
    name, value = predicate_of(condition)
    if not name or name not in OPPOSITES:
        return None
    rest = {key: val for key, val in condition.items()
            if key != name and key not in TRAIT_BOUNDS}

    if name in _LISTED:
        values = _listed(value)
        opposite = OPPOSITES[name]
        if len(values) <= 1:
            return dict(rest, **{opposite: list(values)})
        return {ANY: [dict(rest, **{opposite: [v]}) for v in values]}

    if name in ("exists", "gone"):
        return dict(rest, **{OPPOSITES[name]: True})

    if name == "unbound":
        return dict(rest, unbound=not bool(value))

    # `owned_by: nobody` and `owned_by: somebody` look like a pair and are not
    # one: both say no about a thing that is not there. So even those two are
    # mirrored by `not_owned_by`, which says yes.

    if name == "trait":
        bounds = [(bound, condition[bound]) for bound in TRAIT_BOUNDS
                  if condition.get(bound) is not None]
        if not bounds:
            return None          # "has some of it" has no opposite yet
        parts = [dict(rest, trait=value, **{_FLIPPED_BOUND[bound]: figure})
                 for bound, figure in bounds]
        return parts[0] if len(parts) == 1 else {ANY: parts}

    return dict(rest, **{OPPOSITES[name]: value})


def sees(looker, obj, world_root=None):
    """
    Whether `looker` can see `obj`. The `visible_to` predicate, asked directly.

    For the places sight matters and no action is being attempted. Walking into
    a cellar is the case: Evennia describes the room you have arrived in, and
    that is a movement hook rather than a look, so the check rule that refuses
    looking in the dark never runs. Without this, a world could refuse to let
    you examine anything in the dark and still hand you the room description on
    the way in.
    """
    ctx = context({"direct": obj}, looker, world_root, "look")
    return evaluate({"subject": "direct", "visible_to": "actor"}, ctx)


def darkness(looker, obj, world_root=None):
    """What to say instead, when `looker` cannot see `obj`."""
    ctx = context({"direct": obj}, looker, world_root, "look")
    _met, said = _judge({"subject": "direct", "visible_to": "actor"},
                        ctx, UNMET)
    return said


def describe(condition, ctx=None, mood=None):
    """
    This condition as a sentence: a want, a complaint, or a plain statement.

    With no context there is nothing to evaluate against, so it is said
    abstractly -- which is not a fallback but the mood `help` and `rules` want.
    A rulebook listing prints what a rule requires; it does not ask whether the
    reader happens to satisfy it.
    """
    ctx = ctx or Context()
    if mood is None:
        mood = WANT if ctx.actor is not None else ABSTRACT
    if mood == ABSTRACT:
        return _abstractly(condition)
    _met, said = _judge(condition, ctx, mood)
    return said


def progress(conditions, ctx):
    """[(met, said)] for each condition, in order. What a quest listing wants."""
    return [_judge(c, ctx, WANT) for c in (conditions or [])]


def satisfied(conditions, ctx):
    """True when every condition holds. An empty list is never satisfied."""
    if not conditions:
        return False
    return all(met for met, _ in progress(conditions, ctx))


def complaints(conditions, ctx, limit=None):
    """
    Every condition that does not hold, said as a complaint.

    All of them rather than the first, because a refusal that names one
    missing thing at a time is a conversation: a player fixes it, tries again,
    and is told the next. `verbs.check` capped the list for the same reason it
    is capped here -- past two or three, a refusal stops being read.
    """
    said = []
    for condition in (conditions or []):
        met, complaint = _judge(condition, ctx, UNMET)
        if not met and complaint and complaint not in said:
            said.append(complaint)
        if limit and len(said) >= limit:
            break
    return said


def unmet(conditions, ctx):
    """The first condition that does not hold, as a complaint, or ""."""
    for condition in (conditions or []):
        met, said = _judge(condition, ctx, UNMET)
        if not met:
            return said
    return ""


def _judge(condition, ctx, mood, depth=0):
    """One condition, evaluated and said. The single implementation."""
    kind, members = node_of(condition)
    if kind:
        return _judge_node(kind, members, ctx, mood, depth)
    try:
        condition = dict(condition)
    except (TypeError, ValueError):
        return True, ""

    name, value = predicate_of(condition)
    if not name:
        return True, ""          # nothing asked is nothing to refuse

    subject = resolve(condition.get("subject"), ctx)
    handler = _PREDICATES.get(name)
    if handler is None:
        return True, ""
    return handler(subject, value, condition, ctx, mood)


#: How a subject reads when there is no world to look it up in.
_SUBJECT_WORDS = {
    "actor": "you", "direct": "what you act on", "instrument": "what you use",
    "target": "what you aim at", "container": "what it goes in",
    "source": "what it comes from", HERE: "this place", WORLD: "this world",
}


def _abstractly(condition):
    """
    A condition as a plain statement, with nothing to check it against.

    Written from the words of the condition rather than from anything it
    resolves to, because in this mood nothing resolves: `rules launch` prints
    what launching requires while standing in a field.
    """
    kind, members = node_of(condition)
    if kind:
        return _joined([_abstractly(m) for m in members],
                       "or" if kind == ANY else "and")
    try:
        condition = dict(condition)
    except (TypeError, ValueError):
        return ""
    name, value = predicate_of(condition)
    if not name:
        return ""
    subject = _subject_words(condition)
    # "you" takes plural agreement and everything else takes singular. Worth
    # getting right rather than living with: this text is read aloud at least
    # as often as it is looked at, and "you has piloting" stops a sentence
    # dead in a way a misaligned column never does.
    plural = subject == "you"
    be, have = ("are", "have") if plural else ("is", "has")

    # A `has` list is every one of them; a `lacks` list is none of them, and
    # "is not damaged and breached" says the wrong thing about the pair.
    listed = " and ".join(_said(v) for v in _listed(value))
    nor = " or ".join(_said(v) for v in _listed(value))

    if name == "is":
        return f"{subject} {be} {listed}"
    if name == "lacks":
        return f"{subject} {be} not {nor}"
    if name == "affords":
        # "can be climb" is what gluing an affordance into that sentence gets
        # you, and this module refuses to guess English morphology anywhere
        # else -- so it is phrased the way the evaluated moods below already
        # phrase it, which is grammatical for every verb without inflecting
        # one. `affords` names a verb, never an adjective made out of one.
        joined = " and ".join(_said(v) for v in _listed(value))
        return f"{subject} {be} something you can {joined}"
    if name in ("kind", "not_kind"):
        from world import lexicon

        negated = " not" if name == "not_kind" else ""
        return f"{subject} {be}{negated} a {lexicon.word_of(value)}"
    if name == "holds":
        return f"{subject} {be} holding {listed or 'it'}"
    if name == "not_holds":
        return f"{subject} {be} not holding {nor or 'it'}"
    if name == "wears":
        return f"{subject} {be} wearing {listed or 'it'}"
    if name == "not_wears":
        return f"{subject} {be} not wearing {nor or 'it'}"
    if name in ("owned_by", "not_owned_by"):
        whose, through = _owner_wanted(value)
        negated = name == "not_owned_by"
        if whose == NOBODY:
            return f"{subject} {be} {'somebody' if negated else 'nobody'}'s"
        if whose == SOMEBODY:
            return f"{subject} {be} {'nobody' if negated else 'somebody'}'s"
        said = _SUBJECT_WORDS.get(whose, whose)
        where = " or in something of theirs" if through else ""
        if negated:
            doing = "do not belong" if plural else "does not belong"
        else:
            doing = "belong" if plural else "belongs"
        return f"{subject} {doing} to {said}{where}"
    if name in ("placed", "not_placed"):
        negated = " not" if name == "not_placed" else ""
        try:
            preposition, host = next(iter(dict(value).items()))
        except (TypeError, ValueError, StopIteration):
            return f"{subject} {be}{negated} somewhere in particular"
        return f"{subject} {be}{negated} {preposition} {host}"
    if name == "trait":
        label = str(value).replace("_", " ")
        worded = {"min": "of {} or more", "max": "of {} or less",
                  "below": "below {}", "above": "above {}"}
        bounds = [worded[bound].format(condition[bound])
                  for bound in TRAIT_BOUNDS
                  if condition.get(bound) is not None]
        if not bounds:
            return f"{subject} {have} some {label}"
        return f"{subject} {have} {label} {' and '.join(bounds)}"
    if name == "in_room":
        return f"{subject} {be} in {value}"
    if name == "not_in_room":
        return f"{subject} {be} not in {value}"
    if name == "exists":
        return f"{subject} exists"
    if name == "gone":
        return f"{subject} {be} gone"
    if name == "able":
        doing = {"acting": "act", "moving": "move",
                 "speaking": "speak"}.get(str(value), "act")
        return f"{subject} can {doing}"
    if name == "reachable_by":
        who = _SUBJECT_WORDS.get(str(value), str(value))
        return f"{who} can reach {subject}"
    if name == "visible_to":
        who = _SUBJECT_WORDS.get(str(value), str(value))
        return f"{who} can see {subject}"
    if name == "leads_to":
        return f"a way leads from {subject} to {value}"
    if name == "not_leads_to":
        return f"no way leads from {subject} to {value}"
    if name == "never":
        return str(condition.get("because") or "this cannot be done")
    if name == "unbound":
        return (f"nobody said {subject}" if value
                else f"somebody said {subject}")
    return ""


def _said(value):
    """
    One word of a clause, as it should be read.

    A clause may name a role rather than a thing -- "to throw it you must be
    holding `direct`" -- and the role is machinery, not something a player
    would recognise. Said as what it means instead.
    """
    word = str(value)
    if word in ROLES:
        return _SUBJECT_WORDS.get(word, word)
    return word.replace("_", " ")


def _missing(subject, condition, mood):
    """What to say when the subject is not here at all."""
    said = _subject_words(condition)
    if mood == WANT:
        return False, f"find {said}"
    return False, "There is nothing here to do that to."


def _subject_name(condition):
    """The name a condition's subject was written with, or "".

    For reading an effect backwards, where there is nothing to resolve
    against and the written name is all there is to compare.
    """
    subject = condition.get("subject")
    if isinstance(subject, dict):
        return str(subject.get("named") or subject.get("of_kind") or "")
    return ""


def _subject_words(condition):
    """How to name a subject with nothing to look it up by."""
    subject = condition.get("subject")
    if subject in (None, ""):
        subject = "direct"
    if isinstance(subject, str):
        return _SUBJECT_WORDS.get(subject, subject)
    if isinstance(subject, dict):
        if subject.get("zone"):
            return "the area you are in"
        if "named" in subject:
            return str(subject["named"])
        if "of_kind" in subject:
            from world import lexicon

            return f"a {lexicon.word_of(subject['of_kind'])}"
        if "enclosure" in subject:
            from world import lexicon

            return f"the {lexicon.word_of(subject['enclosure'])} you are in"
    return "it"


def _p_is(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    wanted = {str(s).lower() for s in _listed(value)}
    now = {str(s).lower() for s in subject.states()}
    missing = sorted(wanted - now)
    said = " and ".join(missing) or " and ".join(sorted(wanted))
    if mood == WANT:
        return not missing, f"get {subject.name()} {said}"
    return not missing, _plainly(subject, f"not {said}", ctx)


def _p_lacks(subject, value, condition, ctx, mood):
    if not subject.found:
        return True, ""          # what is not here is not in that condition
    unwanted = {str(s).lower() for s in _listed(value)}
    now = {str(s).lower() for s in subject.states()}
    held = sorted(unwanted & now)
    said = " and ".join(held) or " and ".join(sorted(unwanted))
    if mood == WANT:
        return not held, f"stop {subject.name()} being {said}"
    return not held, _plainly(subject, f"already {said}", ctx)


def _p_affords(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    from world import affordances as af
    from world import kinds as kinds_mod

    wanted, placement = _split_placement(_listed(value))
    have = subject.affordances()
    lacking = sorted(v for v in wanted if v not in have)

    for preposition in placement:
        if preposition not in kinds_mod.holds(ctx.world_root, subject.kinds()):
            if mood == WANT:
                return False, f"find something things go {preposition}"
            return False, (f"{_cap(subject.name())} is not something things "
                           f"go {preposition}.")
    if not lacking:
        if mood == WANT:
            return True, f"find something you can {wanted[0]}" if wanted \
                else ""
        return True, ""
    if mood == WANT:
        return False, f"find something you can {lacking[0]}"
    said = f"You cannot {lacking[0]} {_in_a_sentence(subject, ctx)}."
    if have:
        from evennia.utils.utils import iter_to_str

        said += (f" You can {iter_to_str(sorted(have))} "
                 f"{'yourself' if subject.is_actor() else 'it'}.")
    return False, said


def _split_placement(wanted):
    """`has` may still name a container or a surface, which is placement."""
    from world import affordances as af
    from world import kinds as kinds_mod

    verbs_wanted, placement = [], []
    for word in wanted:
        said = str(word).lower().strip()
        if said == "container":
            placement.append("in")
        elif said == "surface":
            placement.append("on")
        else:
            folded = af.to_verb(said)
            if folded:
                verbs_wanted.append(folded)
    return verbs_wanted, placement


def _p_kind(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    from world import kinds as kinds_mod
    from world import lexicon

    met = kinds_mod.any_is_a(ctx.world_root, subject.kinds(), value)
    word = lexicon.word_of(value)
    if mood == WANT:
        return met, f"find a {word}"
    return met, f"{_cap(subject.name())} is not a {word}."


def _p_not_kind(subject, value, condition, ctx, mood):
    if not subject.found:
        return True, ""          # what is not here is not a sword either
    from world import kinds as kinds_mod
    from world import lexicon

    met = not kinds_mod.any_is_a(ctx.world_root, subject.kinds(), value)
    word = lexicon.word_of(value)
    if mood == WANT:
        return met, f"find something that is not a {word}"
    return met, f"{_cap(subject.name())} is a {word}."


def _p_holds(subject, value, condition, ctx, mood):
    """
    Whether the subject is carrying something.

    Says what it wants whether or not it has it: a quest listing shows every
    condition, ticked or not, and a met one printing nothing leaves a blank
    line where "be carrying the brass key" belongs.
    """
    if not subject.found:
        return _missing(subject, condition, mood)
    missing = []
    names = []
    for wanted in _listed(value):
        held, said = _held(subject, wanted, ctx)
        names.append(said)
        if not held:
            missing.append(said)
    listed = " and ".join(missing or names) or "it"
    if mood == WANT:
        return not missing, f"be carrying {listed}"
    return not missing, _plainly(subject, f"not holding {listed}", ctx,
                                 verb="is")


def _p_not_holds(subject, value, condition, ctx, mood):
    """Whether the subject is carrying none of these. The opposite of `holds`."""
    if not subject.found:
        return True, ""          # nobody here is holding anything
    held, names = [], []
    for wanted in _listed(value):
        holding, said = _held(subject, wanted, ctx)
        names.append(said)
        if holding:
            held.append(said)
    if mood == WANT:
        return not held, f"stop carrying {' or '.join(held or names) or 'it'}"
    return not held, _plainly(subject,
                              f"still holding {' and '.join(held) or 'it'}",
                              ctx, verb="is")


def _held(subject, wanted, ctx):
    """(is it held, what to call it) for one thing a `holds` clause names."""
    import re

    carrier = subject.obj
    named = str(wanted).strip().lower()
    # A rule usually means another role -- "to throw it you must be holding
    # it" is about whatever is being thrown, which has no name until somebody
    # throws something. Read literally it asks for an object called "direct".
    role = ctx.bound.get(named) if named in ROLES else None
    if role is not None:
        found = getattr(carrier, "contents", []) or []
        return role in found, Subject(THING, role, ctx=ctx).name()
    plain = re.sub(r"^(?:an?|the|some)\s+", "", str(wanted).strip(),
                   flags=re.IGNORECASE)
    for obj in (getattr(carrier, "contents", []) or []):
        if plain.lower() in str(obj.key).lower():
            return True, f"the {plain}"
    return False, f"the {plain}"


def _wearing(subject, wanted):
    """Whether the subject has on something answering to `wanted`."""
    return any(str(wanted).lower() in str(obj.key).lower() and obj.db.worn
               for obj in (getattr(subject.obj, "contents", []) or []))


def _p_wears(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    missing = [str(wanted) for wanted in _listed(value)
               if not _wearing(subject, wanted)]
    listed = " and ".join(missing or [str(v) for v in _listed(value)]) or "it"
    if mood == WANT:
        return not missing, f"be wearing {listed}"
    return not missing, _plainly(subject, f"not wearing {listed}", ctx,
                                 verb="is")


def _p_not_wears(subject, value, condition, ctx, mood):
    """Whether the subject has on none of these. The opposite of `wears`."""
    if not subject.found:
        return True, ""
    worn = [str(wanted) for wanted in _listed(value)
            if _wearing(subject, wanted)]
    if mood == WANT:
        named = worn or [str(v) for v in _listed(value)]
        return not worn, f"take off {' or '.join(named) or 'it'}"
    return not worn, _plainly(subject,
                              f"still wearing {' and '.join(worn) or 'it'}",
                              ctx, verb="is")


def _placement(subject, value, ctx):
    """(preposition, what the host is called, whether it is so), or None."""
    from world import relations

    try:
        where = dict(value)
    except (TypeError, ValueError):
        return None
    preposition, host_name = next(iter(where.items()), (None, None))
    if not preposition:
        return None
    host = resolve(host_name, ctx)
    if not host.found:
        host_obj = _find(str(host_name), "", ctx)
    else:
        host_obj = host.obj
    met = relations.test(subject.obj, preposition, host_obj)
    called = host.name() if host.found else str(host_name)
    return preposition, called, met


def _p_placed(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    found = _placement(subject, value, ctx)
    if found is None:
        return True, ""
    preposition, called, met = found
    if mood == WANT:
        return met, f"get {subject.name()} {preposition} {called}"
    return met, (f"{_cap(subject.name())} is not {preposition} {called}.")


#: How taking a thing away from where it was put reads, by how it was put.
_AWAY = {"in": "out of", "on": "off", "under": "out from under",
         "behind": "out from behind"}


def _p_not_placed(subject, value, condition, ctx, mood):
    """Whether the subject is not where it names. The opposite of `placed`."""
    if not subject.found:
        return True, ""
    found = _placement(subject, value, ctx)
    if found is None:
        return True, ""
    preposition, called, placed = found
    if mood == WANT:
        away = _AWAY.get(preposition, "away from")
        return not placed, f"get {subject.name()} {away} {called}"
    return not placed, (f"{_cap(subject.name())} is still {preposition} "
                        f"{called}.")


def _trait_met(current, low, high, under, over):
    """
    Whether a figure meets a trait condition's bounds.

    `min` and `max` include the figure they name, and `below` and `above` do
    not. A figure somebody does not have meets no inclusive bound and every
    exclusive one: a stone golem has no hunger, so it is not starving (`max 10`)
    and it is not fed either (`min 30`), but "below 10" and "above 30" are both
    true of it. That asymmetry is exactly what makes `below` the opposite of
    `min`. With no bounds at all, the question is whether there is any figure.
    """
    exclusive = under is not None or over is not None
    inclusive = low is not None or high is not None
    if current is None:
        return exclusive and not inclusive
    return ((low is None or current >= low)
            and (high is None or current <= high)
            and (under is None or current < under)
            and (over is None or current > over))


def _p_trait(subject, value, condition, ctx, mood):
    from world import traits

    slug = str(value)
    low, high = condition.get("min"), condition.get("max")
    under, over = condition.get("below"), condition.get("above")
    if not subject.found:
        # Nobody is here to have the figure, which is the missing figure asked
        # of nobody: met exactly when a missing figure would be.
        if _trait_met(None, low, high, under, over):
            return True, ""
        return _missing(subject, condition, mood)
    current = traits.value(subject.obj, slug)
    met = _trait_met(current, low, high, under, over)
    label = slug.replace("_", " ")
    if mood == WANT:
        if low is not None:
            return met, f"get {label} to {traits._round(low)}"
        if high is not None:
            return met, f"get {label} down to {traits._round(high)}"
        if under is not None:
            return met, f"get {label} below {traits._round(under)}"
        if over is not None:
            return met, f"get {label} above {traits._round(over)}"
        return met, f"have some {label}"
    if met:
        return True, ""
    if low is not None or high is not None or (under is None and over is None):
        said = traits.meets(subject.obj, {slug: {"min": low, "max": high}})
        if said:
            return False, said
        if current is None:
            return False, f"{_cap(subject.name())} has no {label}."
    whose = "Your" if subject.is_actor() else f"{_cap(subject.name())}'s"
    if under is not None and current is not None and current >= under:
        return False, (f"{whose} {label} is not below "
                       f"{traits._round(under)} ({traits._round(current)}).")
    if over is not None and current is not None and current <= over:
        return False, (f"{whose} {label} is not above "
                       f"{traits._round(over)} ({traits._round(current)}).")
    return False, f"{_cap(subject.name())} has no {label}."


def _room_title_of(subject, ctx):
    who = subject.obj if subject.found else ctx.actor
    here = getattr(who, "location", None)
    return (here.db.room_title or here.key) if here is not None else ""


def _p_in_room(subject, value, condition, ctx, mood):
    title = _room_title_of(subject, ctx)
    met = bool(value) and str(value).lower() in str(title).lower()
    if mood == WANT:
        return met, f"be in {value}"
    return met, f"You are not in {value}."


def _p_not_in_room(subject, value, condition, ctx, mood):
    title = _room_title_of(subject, ctx)
    met = not (bool(value) and str(value).lower() in str(title).lower())
    if mood == WANT:
        return met, f"leave {value}"
    return met, f"You are still in {value}."


def _p_exists(subject, value, condition, ctx, mood):
    met = subject.found
    said = _subject_words(condition)
    if mood == WANT:
        return met, f"bring {said} into being"
    return met, f"There is no {said} here."


def _p_gone(subject, value, condition, ctx, mood):
    met = not subject.found
    said = _subject_words(condition)
    if mood == WANT:
        return met, f"get rid of {said}"
    return met, f"{_cap(said)} is still here."


#: What "owned by nobody" is written as. A word rather than a null, because a
#: rule saying it is making a claim -- this thing is going spare -- and
#: `{"owned_by": null}` reads as somebody having forgotten to fill the field
#: in.
NOBODY = "nobody"

#: What "owned by somebody" is written as: anybody at all, as long as it is not
#: nobody. The guard on "you may not take what is not yours", which has to be
#: gathered only for a thing somebody has a claim on -- and the condition
#: language has no "not" to write that with.
SOMEBODY = "somebody"


def _p_owned_by(subject, value, condition, ctx, mood):
    """
    Whose the subject is.

    The value is a role -- almost always `actor` -- or `nobody`, which is true
    of a thing nobody has ever claimed and of a thing whose owner has left the
    world. Those two are one answer here deliberately: to whoever is reaching
    for it they are the same situation, and the standard rule that makes
    picking a thing up yours wants both.

    `{"role": "actor", "through": "containers"}` is the other form, and asks
    the standing question instead: is this theirs, or is it inside something
    that is. Not the default and never what a seeded rule uses -- if I own a
    chest and you put your sword in it, the sword is still yours -- but a
    world with a landlord or a ship's captain in it means exactly this, and
    shipping the syntax is what keeps such a world from writing the inference
    into every rule by hand. See docs/pronouns-and-ownership.md 6.3.
    """
    from world import ownership

    if not subject.found:
        return _missing(subject, condition, mood)

    wanted, through = _owner_wanted(value)
    if wanted == SOMEBODY:
        met = not ownership.claimable(subject.obj)
        if mood == WANT:
            return met, f"see {_in_a_sentence(subject, ctx)} owned"
        return met, f"{_cap(subject.name())} belongs to nobody."
    if wanted == NOBODY:
        met = ownership.claimable(subject.obj)
        if mood == WANT:
            return met, f"leave {_in_a_sentence(subject, ctx)} unclaimed"
        held = ownership.owner_name(subject.obj) or "somebody else"
        return met, f"{_cap(subject.name())} belongs to {held}."

    owner = ctx.actor if wanted == "actor" else ctx.bound.get(wanted)
    if owner is None:
        # Nobody to be the owner, so nothing to be true: a rule about the
        # target's property, asked of a sentence that named no target.
        return True, ""
    met = (ownership.owns_through_containers(owner, subject.obj) if through
           else ownership.owns(owner, subject.obj))

    whose = "yours" if owner is ctx.actor else \
        f"{owner.get_display_name(ctx.actor)}'s"
    if mood == WANT:
        return met, f"own {_in_a_sentence(subject, ctx)}"
    return met, f"{_cap(subject.name())} is not {whose}."


def _p_not_owned_by(subject, value, condition, ctx, mood):
    """
    Whose the subject is not. The opposite of `owned_by`.

    Not the actor's means nobody's or somebody else's, and a thing that is not
    here is nobody's in particular. With nobody to be the owner there is
    nothing to be true, exactly as `owned_by` answers.
    """
    from world import ownership

    if not subject.found:
        return True, ""
    wanted, through = _owner_wanted(value)
    if wanted == SOMEBODY:
        met = ownership.claimable(subject.obj)
        if mood == WANT:
            return met, f"leave {_in_a_sentence(subject, ctx)} unclaimed"
        held = ownership.owner_name(subject.obj) or "somebody"
        return met, f"{_cap(subject.name())} belongs to {held}."
    if wanted == NOBODY:
        met = not ownership.claimable(subject.obj)
        if mood == WANT:
            return met, f"see {_in_a_sentence(subject, ctx)} owned"
        return met, f"{_cap(subject.name())} belongs to nobody."

    owner = ctx.actor if wanted == "actor" else ctx.bound.get(wanted)
    if owner is None:
        return True, ""
    owns = (ownership.owns_through_containers(owner, subject.obj) if through
            else ownership.owns(owner, subject.obj))
    whose = "yours" if owner is ctx.actor else \
        f"{owner.get_display_name(ctx.actor)}'s"
    if mood == WANT:
        return not owns, f"part with {_in_a_sentence(subject, ctx)}"
    return not owns, f"{_cap(subject.name())} is {whose}."


def _owner_wanted(value):
    """(whose it must be, whether containers count) from either written form."""
    if isinstance(value, dict):
        return (str(value.get("role") or value.get("owner") or "actor"),
                str(value.get("through") or "") == "containers")
    return str(value or "actor"), False


#: What a state can stop its holder doing. Three, and never a list of
#: forbidden verbs: a state is settled once while new verbs go on being
#: invented, so any list would be stale within a week.
GATES = {"acting": "prevents_acting", "moving": "prevents_moving",
         "speaking": "prevents_speaking"}


def _p_unbound(subject, value, condition, ctx, mood):
    """
    Whether nobody named this role.

    What a redirect is guarded by, and the reason it needs saying rather than
    being inferred: "powering aboard a ship means powering the ship" must fire
    when somebody typed `power`, and must NOT fire when they typed `power
    datapad`. Both are the same verb in the same room; the difference is only
    whether a role was filled.

    Distinct from `exists`, which asks whether the thing a condition names is
    anywhere to be found. This asks whether anybody named one.
    """
    met = not subject.found if bool(value) else subject.found
    if mood == WANT:
        return met, "say what you mean"
    return met, ""


def _on_somebody_here(obj, here):
    """
    Whether `obj` is something a person in this room has on them.

    Worn or carried, it is in plain sight: looking at a person already lists
    it -- "Bram is wearing a canvas vest" -- so it has to be something that can
    be looked at. Out of reach all the same; seeing a vest is not taking it.
    """
    from world.quests import is_person

    holder = getattr(obj, "location", None)
    return (here is not None and holder is not None
            and getattr(holder, "location", None) is here
            and is_person(holder))


def _p_visible(subject, value, condition, ctx, mood):
    """
    Whether whoever `value` names could see the subject.

    The other half of Inform's accessibility, and the half that has never been
    enforced: 5.1 has given every role a `visible` / `touchable` / `carried`
    level since actions were first declared, `actions.access_for` has read it,
    and nothing has ever asked the question. So a notice across the room and a
    moon overhead were not merely undescribed, they were unlookable, because the
    one standard rule that applied to every action demanded reach.

    Wider than reach on purpose, and narrower in one way reach is not. Anything
    within reach can be seen, and so can the place you are standing in and
    whatever else is simply here with you. But sight needs light, and reach does
    not: you can find a door in the dark.

    Light is a trait rather than a subsystem -- a lit room grants it, a lit lamp
    grants it while burning, and `gear` sums both. A world that has never
    registered the trait has no darkness in it; see `traits.lights`.
    """
    from world import relations, traits

    if not subject.found:
        return _missing(subject, condition, mood)
    who = resolve(value or "actor", ctx)
    if not who.found or subject.obj is None:
        return True, ""
    if subject.obj is who.obj:
        return True, ""

    here = getattr(who.obj, "location", None)
    near = (subject.obj in relations.reachable(who.obj, include_self=True)
            or subject.obj in relations.enclosing(who.obj)
            or (here is not None and subject.obj.location is here)
            or _on_somebody_here(subject.obj, here))
    if not near:
        if mood == WANT:
            return False, f"get to where you can see {subject.name()}"
        return False, f"You cannot see {subject.name()} from here."

    if traits.lights(ctx.world_root):
        if (traits.value(who.obj, traits.LIGHT) or 0) < 1:
            if mood == WANT:
                return False, "find some light"
            return False, "It is too dark to see anything."
    return True, ""


def _p_leads_to(subject, value, condition, ctx, mood):
    """
    Whether a way out of this place reaches the room named.

    What reads `set_exit` backwards, and the reason `set_exit` is allowed to
    exist: 11.1 holds that an effect nobody can read backwards is not a cheap
    effect but a hole in the planner, so an effect that changes where a door
    leads needs a condition that asks where a door leads.

    Deliberately about one step rather than about reachability. "Is the dock
    reachable from here" is a search over the whole world and would answer yes
    for somewhere twenty rooms away, which is not what a rule about an airlock
    means. One step is also what the planner can act on: a way that does not
    lead there yet is a way something could be made to lead there.
    """
    wanted = str(value or "").strip().lower()
    if not wanted:
        return True, ""
    room = subject.obj if subject.what in (ROOM, THING) else None
    if room is None:
        room = getattr(ctx.actor, "location", None)
    if room is None:
        return _missing(subject, condition, mood)

    met = False
    for exit_obj in room.exits:
        where = getattr(exit_obj, "destination", None)
        if where is None:
            continue
        for name in (where.db.room_title, where.key):
            if str(name or "").strip().lower() == wanted:
                met = True
                break
        if met:
            break
    if mood == WANT:
        return met, f"open a way to {value}"
    return met, f"Nothing here leads to {value}."


def _p_not_leads_to(subject, value, condition, ctx, mood):
    """No way out of this place reaches the room named. See `_p_leads_to`."""
    wanted = str(value or "").strip().lower()
    if not wanted:
        return True, ""
    room = subject.obj if subject.what in (ROOM, THING) else None
    if room is None:
        room = getattr(ctx.actor, "location", None)
    if room is None:
        return True, ""          # nowhere, and nowhere leads nowhere
    met = not any(
        str(name or "").strip().lower() == wanted
        for exit_obj in room.exits
        if getattr(exit_obj, "destination", None) is not None
        for name in (exit_obj.destination.db.room_title,
                     exit_obj.destination.key))
    if mood == WANT:
        return met, f"close the way to {value}"
    return met, f"A way from here still leads to {value}."


def _p_never(subject, value, condition, ctx, mood):
    """
    A condition that cannot be met, carrying its own reason.

    For a verb a world has decided is not a verb here. The refusal is the
    rule's name, since there is nothing about the world to report -- it is not
    that the door is locked, it is that there is no such thing as doing this.
    """
    return False, str(condition.get("because") or "You can't do that.")


def _p_able(subject, value, condition, ctx, mood):
    """
    Whether nothing the subject is in stops them doing this sort of thing.

    The three `prevents_` flags on a state group, asked as a condition. They
    were a hard-coded guard at the top of the attempt pipeline; as a rule they
    are one line in `rules`, they compose with everything else, and a world
    can add its own without anybody touching the pipeline.

    **Unless the action was declared to happen in spite of this one.** Check
    rules are monotone -- adding one can only make an action stricter -- so
    nothing a world writes can let a dead character act, which is right for
    every verb except the ones whose whole purpose is to end the state. A
    world says so once, when it declares the action, and `actions.waives`
    answers for it here. See `actions.GATES`; this is the same shape
    `_p_reachable` below uses to excuse a role declared `visible`.
    """
    from world import actions, verbs

    gate = GATES.get(str(value), GATES["acting"])
    doing = {"acting": "do that", "moving": "move",
             "speaking": "speak"}.get(str(value), "do that")
    if ctx.action and actions.waives(ctx.world_root, ctx.action, str(value)):
        return True, ""
    if not subject.found:
        return True, ""
    stopped = verbs.blocked(subject.obj, gate, ctx.world_root)
    if mood == WANT:
        return not stopped, f"be able to {doing}"
    if not stopped:
        return True, ""
    return False, verbs.refuse(subject.obj, gate, ctx.world_root) \
        or _plainly(subject, f"in no condition to {doing}", ctx)


def _p_reachable(subject, value, condition, ctx, mood):
    """
    Whether whoever `value` names could take hold of the subject.

    Inform's basic accessibility rule. `relations.reachable` already knows the
    answer -- your own inventory, the room, what is on or under anything you
    can reach, and inside anything open -- and a closed box stopping the
    search is the whole reason a lid is worth having.
    """
    from world import actions, relations

    if not subject.found:
        return _missing(subject, condition, mood)

    # What this action actually asks of this role, which is not always reach.
    # 5.1 has given every role a `visible` / `touchable` / `carried` level since
    # actions were first declared, and until now nothing read it -- so the one
    # standard rule that applies to every action demanded reach for all of them,
    # and looking at a thing across a room was refused for not being within
    # arm's length. A role declared `visible` is excused here and answered by
    # `visible_to` instead.
    role = condition.get("subject")
    if ctx.action and isinstance(role, str) and role in ROLES:
        if actions.access_for(ctx.world_root, ctx.action,
                              role) == actions.VISIBLE:
            return True, ""

    who = resolve(value or "actor", ctx)
    if not who.found or subject.obj is None:
        return True, ""
    if subject.obj is who.obj:
        return True, ""
    # The place you are in is within reach of you, and so is the place that
    # place is part of. `relations.reachable` searches downwards -- your
    # pockets, the floor, inside an open box -- and never upwards, because
    # nothing needed it to until a rule could act on a room. Aboard a ship,
    # `power` means the ship: the ship is not in the room, it is the room.
    within = (subject.obj in relations.reachable(who.obj, include_self=True)
              or subject.obj in relations.enclosing(who.obj))
    # People are not things, and `relations.reachable` only walks things -- so
    # without this every character was out of reach of everybody, and every
    # verb that names a person was refused before it began. Somebody standing
    # in the same place is within arm's length. An exit is not a person, and
    # is left to the rule that already governs it.
    if not within:
        here = getattr(who.obj, "location", None)
        within = (here is not None and subject.obj.location is here
                  and getattr(subject.obj, "destination", None) is None
                  and not relations._is_thing(subject.obj))
    if mood == WANT:
        return within, f"get within reach of {subject.name()}"
    return within, f"{_cap(subject.name())} is out of reach."


_PREDICATES = {
    "is": _p_is,
    "visible_to": _p_visible,
    "leads_to": _p_leads_to,
    "not_leads_to": _p_not_leads_to,
    "lacks": _p_lacks,
    "affords": _p_affords,
    "kind": _p_kind,
    "not_kind": _p_not_kind,
    "holds": _p_holds,
    "not_holds": _p_not_holds,
    "wears": _p_wears,
    "not_wears": _p_not_wears,
    "owned_by": _p_owned_by,
    "not_owned_by": _p_not_owned_by,
    "placed": _p_placed,
    "not_placed": _p_not_placed,
    "trait": _p_trait,
    "in_room": _p_in_room,
    "not_in_room": _p_not_in_room,
    "exists": _p_exists,
    "gone": _p_gone,
    "able": _p_able,
    "reachable_by": _p_reachable,
    "never": _p_never,
    "unbound": _p_unbound,
}


# ---------------------------------------------------------------------------
# Saying it
# ---------------------------------------------------------------------------

def _cap(text):
    """Capitalise the first letter, stepping over a colour code."""
    text = str(text or "")
    start = 2 if text[:1] == "|" and len(text) > 2 else 0
    return text[:start] + text[start:start + 1].upper() + text[start + 1:]


def _plainly(subject, said, ctx, verb=None):
    """"You are not powered" / "The chest is not open"."""
    if subject.is_actor():
        return f"You are {said}."
    return f"{_cap(subject.name())} {verb or 'is'} {said}."


def _in_a_sentence(subject, ctx):
    """The subject as it reads mid-sentence, article and all."""
    if subject.is_actor():
        return "yourself"
    obj = subject.obj
    try:
        return obj.get_numbered_name(1, ctx.actor, return_string=True)
    except AttributeError:
        return subject.name()


# ---------------------------------------------------------------------------
# Reading a condition backwards
# ---------------------------------------------------------------------------

def achieves(effect, condition):
    """
    Whether this effect would make this condition true.

    What the planner reads. Deliberately about the *shape* of an effect rather
    than about running it: an effect is model-written and often incomplete, so
    a planner that believed one wholesale would build long plans on a promise.
    This says only "that would help", and the step is checked afterwards.

    Every new effect type has to be answerable here, or goals that need it
    become quietly unreachable. See docs/rulebooks-from-inform.md 11.1: an
    effect nobody can read backwards is not a cheap effect, it is a hole in
    the planner.
    """
    kind, members = node_of(condition)
    if kind:
        # An `any` is met by meeting any branch, and an `all` is helped by
        # helping any member: "that would help" is all this ever says.
        return any(achieves(effect, member) for member in members)
    try:
        etype = str(effect.get("type") or "")
        condition = dict(condition)
    except (AttributeError, TypeError, ValueError):
        return False
    name, value = predicate_of(condition)

    if name == "not_holds":
        # Put down, handed over, put somewhere, or gone.
        if etype == "move_object":
            return str(effect.get("to") or "") not in ("", "actor")
        return etype == "destroy_object"

    if name == "not_wears":
        if etype == "move_object":
            return str(effect.get("to") or "") not in ("", "actor")
        return etype == "destroy_object"

    if name == "not_placed":
        if etype == "destroy_object":
            return True
        if etype != "move_object":
            return False
        try:
            preposition = next(iter(dict(value)))
        except (TypeError, ValueError, StopIteration):
            return False
        going = str(effect.get("to") or "")
        return (going in ("actor", "room")
                or str(effect.get("preposition") or "") != preposition)

    if name == "not_in_room" and etype == "move_actor":
        named = str(effect.get("to") or "").strip().lower()
        if named:
            return named != str(value or "").strip().lower()
        return True

    if name == "not_owned_by" and etype == "set_owner":
        whose, _through = _owner_wanted(value)
        going_to = str(effect.get("to") or "")
        if not going_to:
            return False
        if whose == SOMEBODY:
            return going_to == NOBODY
        if whose == NOBODY:
            return going_to != NOBODY
        return going_to != whose

    if name == "is" and etype == "set_state":
        wanted = {str(s).lower() for s in _listed(value)}
        added = {str(s).lower() for s in _listed(effect.get("add"))}
        return bool(wanted) and wanted <= added

    if name == "lacks" and etype == "set_state":
        unwanted = {str(s).lower() for s in _listed(value)}
        removed = {str(s).lower() for s in _listed(effect.get("remove"))}
        return bool(unwanted) and unwanted <= removed

    if name == "holds" and etype == "move_object":
        return str(effect.get("to") or "") == "actor"

    if name == "holds" and etype == "move_contents":
        # Emptying something into your hands is a way to come to hold what was
        # in it. Which particular thing that is, is a fact about the world at
        # the moment it happens rather than about the rule, so this says only
        # "that would help" -- which is all anything here ever says.
        return str(effect.get("to") or "actor") == "actor"

    if name == "owned_by" and etype == "set_owner":
        # Read for the thing the effect names and no further. The cascade is
        # deliberately unreadable backwards: "give her the box" as a way of
        # satisfying "own the sword inside it" is not a plan step any planner
        # should be inventing, and an effect that could be read that way would
        # have the planner handing containers about in the hope of what fell
        # out. A decision on the record rather than a gap. See 6.4.
        whose, _through = _owner_wanted(value)
        going_to = str(effect.get("to") or "")
        if whose == SOMEBODY:
            return bool(going_to) and going_to != NOBODY
        if going_to == "nobody" or whose == NOBODY:
            return going_to == whose
        named = str(effect.get("name_role") or effect.get("role") or "")
        subject = condition.get("subject") or "direct"
        if named and isinstance(subject, str) and named != subject:
            return False
        return going_to == whose

    if name == "placed" and etype == "move_object":
        try:
            preposition = next(iter(dict(value)))
        except (TypeError, ValueError, StopIteration):
            return False
        return str(effect.get("preposition") or "") == preposition

    if name == "exists" and etype == "create_object":
        # What it makes has to be the thing that was wanted. A rule that
        # conjures a candle does not satisfy a goal about a key.
        wanted = _subject_name(condition)
        made = str(effect.get("name") or "")
        return not wanted or wanted.lower() in made.lower()

    if name == "gone" and etype == "destroy_object":
        return True

    if name == "leads_to" and etype == "set_exit":
        wanted = str(value or "").strip().lower()
        made = str(effect.get("to") or "").strip().lower()
        return bool(wanted) and wanted == made


    if name == "trait" and etype == "set_trait":
        if str(effect.get("trait") or "") != str(value):
            return False
        low, high = condition.get("min"), condition.get("max")
        under, over = condition.get("below"), condition.get("above")
        # Set outright: the question is whether where it lands is where the
        # goal wanted it.
        if effect.get("set_to") is not None:
            try:
                target = float(effect["set_to"])
            except (TypeError, ValueError):
                return False
            return _trait_met(target, low, high, under, over)
        # Otherwise, which way the goal wants it to move against which way
        # this moves it. A rate counts: an effect that starts something
        # draining is how a goal about a falling figure is met, just not at
        # once.
        for amount in (effect.get("change"), effect.get("rate")):
            if amount is None:
                continue
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                continue
            if amount > 0 and (low is not None or over is not None):
                return True
            if amount < 0 and (high is not None or under is not None):
                return True
        return False

    if name == "in_room" and etype == "move_actor":
        # Read exactly when the effect named a room, and optimistically when it
        # named a way out.
        #
        # `move_actor` may now say either -- {"to": "the Chapel"} as well as
        # {"exit": "north"} -- and the two deserve different answers. A room is
        # a destination and can be compared with the one the goal wants. An exit
        # is not: where north leads is a fact about the world rather than about
        # the effect, and this function is handed an effect and a condition and
        # nothing else, on purpose. It answers "would that shape help", and the
        # step is checked when it is taken -- so the planner may try a door that
        # turns out to go elsewhere, and learn by trying.
        named = str(effect.get("to") or "").strip().lower()
        if named:
            return named == str(value or "").strip().lower()
        return True

    # `narrate` and `describe` are the two output-only effects, and neither
    # can be read backwards because neither changes anything. Said here rather
    # than left to fall off the end, because 11.1 holds that an effect nobody
    # can answer for is a hole in the planner -- so the two that genuinely have
    # no answer are on the record as decisions. Nothing is ever a goal to have
    # been told something, or to have been seen doing something; what an NPC
    # wants from either is whatever an `after` rule does next.
    if etype in ("narrate", "describe"):
        return False

    return False


# ---------------------------------------------------------------------------
# Reading the two shapes this replaces
# ---------------------------------------------------------------------------

def from_requires(requires):
    """
    A verb rule's role-keyed preconditions, as conditions.

    `{"direct": {"has": ["read"], "lacks": ["burning"]}}` becomes two
    conditions about `direct`. Clause order is fixed rather than dictionary
    order, so the complaint a player reads is the same on two runs -- and it
    leads with what the thing *is*, which is the half they can do something
    about, rather than with what it affords, which they cannot.
    """
    from world import verbs

    out = []
    for role, needed in verbs.requirements(requires).items():
        for clause, predicate in (("is", "is"), ("lacks", "lacks"),
                                  ("has", "affords"), ("holds", "holds")):
            value = needed.get(clause)
            if value:
                out.append({"subject": role, predicate: value})
        wanted = needed.get("trait") or needed.get("traits") or {}
        try:
            for slug, bounds in dict(wanted).items():
                entry = {"subject": role, "trait": slug}
                for edge in ("min", "max"):
                    if isinstance(bounds, dict) and bounds.get(edge) is not None:
                        entry[edge] = bounds[edge]
                out.append(entry)
        except (TypeError, ValueError):
            continue
    return out


#: How a goal's `type` maps onto a predicate. `state` is the odd one: it
#: carries `is` and `lacks` together, so it becomes up to two conditions.
_GOAL_PREDICATES = {
    "holds": "holds", "worn": "wears", "trait": "trait",
    "in_room": "in_room", "exists": "exists", "gone": "gone",
}


def from_goal(condition):
    """
    One goal condition, as conditions. See `world.goals.CONDITION_TYPES`.

    A goal names its subject rather than binding it -- "the brass key", or a
    sort of thing -- so the subject comes back as `{"named": ...}` or
    `{"of_kind": ...}` and is looked up when it is tested.
    """
    try:
        condition = dict(condition)
    except (TypeError, ValueError):
        return []

    ctype = str(condition.get("type") or "")
    name = str(condition.get("object") or "").strip()
    kind = str(condition.get("kind") or "").strip()
    subject = {"named": name} if name else ({"of_kind": kind} if kind else
                                            "actor")

    if ctype in COMBINATORS:
        members = []
        for member in (condition.get("of") or []):
            parts = from_goal(member)
            if not parts:
                return []        # a branch nobody can test spoils the node
            members.append(parts[0] if len(parts) == 1 else {ALL: parts})
        joined = _tidy({ctype: members}) if members else None
        return [joined] if joined is not None else []

    if ctype == "in_room":
        return [{"subject": "actor", "in_room": condition.get("room", "")}]

    if ctype == "not_in_room":
        return [{"subject": "actor", "not_in_room": condition.get("room", "")}]

    if ctype == "trait":
        entry = {"subject": "actor", "trait": condition.get("trait", "")}
        for edge in TRAIT_BOUNDS:
            if condition.get(edge) is not None:
                entry[edge] = condition[edge]
        return [entry]

    if ctype == "state":
        out = []
        for clause in ("is", "lacks"):
            if condition.get(clause):
                out.append({"subject": subject, clause: condition[clause]})
        return out

    if ctype in ("placed", "not_placed"):
        preposition = condition.get("preposition") or "in"
        return [{"subject": subject,
                 ctype: {preposition: condition.get("host", "")}}]

    if ctype == "not_holds":
        return [{"subject": "actor", "not_holds": [name or kind]}]

    if ctype == "not_worn":
        return [{"subject": "actor", "not_wears": [name or kind]}]

    if ctype == "delivered":
        # Being inside the recipient is exactly what `holds` asks, from the
        # other end: `goals` tests whether the thing is in them.
        return [{"subject": {"named": str(condition.get("to") or "")},
                 "holds": [name] if name else []}]

    predicate = _GOAL_PREDICATES.get(ctype)
    if not predicate:
        return []
    if predicate in ("exists", "gone"):
        return [{"subject": subject, predicate: True}]
    if predicate == "holds":
        return [{"subject": "actor", "holds": [name or kind]}]
    if predicate == "wears":
        return [{"subject": "actor", "wears": [name or kind]}]
    return [{"subject": subject, predicate: True}]


def from_goals(conditions):
    """Every goal condition in a list, flattened into conditions."""
    out = []
    for condition in (conditions or []):
        out.extend(from_goal(condition))
    return out


def as_goal(condition, bound=None, actor=None):
    """
    One condition as a goal condition, or None when it cannot be one.

    The other direction from `from_goal`, and the reason it is needed: a check
    rule refuses an attempt in the condition language, and the planner plans in
    the goal language. "A ship only launches under power" has to become the goal
    "the ship is powered" before anything can work out that the step is `power`.

    A role is resolved to whatever it was bound to, because a goal names its
    subject -- `direct` means nothing to a planner looking at the world next
    turn, and the ship does. A condition about a role nothing was bound to, or
    about a zone or the world, has no goal form: there is no object to walk up to
    and do something about, which is the honest answer rather than a guess.

    Only the predicates a planner can actually advance are converted. `affords`,
    `able`, `reachable_by` and the rest describe the shape of a situation rather
    than something a character could go and change, and offering them as goals
    would send an NPC off to make a bottle drinkable.
    """
    try:
        condition = dict(condition)
    except (TypeError, ValueError):
        return None

    node, members = node_of(condition)
    if node:
        # A branch with no goal form is dropped rather than spoiling the node.
        # The planner needs only one way forward, and a branch it cannot act
        # on is a branch it would never have taken.
        converted = [goal for goal in (as_goal(m, bound, actor)
                                       for m in members) if goal is not None]
        if not converted:
            return None
        if len(converted) == 1:
            return converted[0]
        return {"type": node, "of": converted}

    name = _goal_subject_name(condition.get("subject"), bound, actor)
    if name is None:
        return None

    predicate, value = predicate_of(condition)
    if predicate in ("is", "lacks"):
        listed = [str(s) for s in _listed(value) if s]
        return {"type": "state", "object": name, predicate: listed} \
            if listed else None
    goal_types = {"holds": "holds", "wears": "worn",
                  "not_holds": "not_holds", "not_wears": "not_worn"}
    if predicate in goal_types:
        wanted = [str(s) for s in _listed(value) if s]
        return ({"type": goal_types[predicate], "object": wanted[0]}
                if wanted else None)
    if predicate == "trait":
        entry = {"type": "trait", "trait": str(value)}
        for edge in TRAIT_BOUNDS:
            if condition.get(edge) is not None:
                entry[edge] = condition[edge]
        return entry
    if predicate in ("in_room", "not_in_room"):
        return {"type": predicate, "room": str(value)}
    if predicate == "exists":
        return {"type": "exists", "object": name} if bool(value) else None
    if predicate == "gone":
        return {"type": "gone", "object": name} if bool(value) else None
    if predicate in ("placed", "not_placed"):
        try:
            where = dict(value)
        except (TypeError, ValueError):
            return None
        for preposition, host in where.items():
            return {"type": predicate, "object": name,
                    "preposition": str(preposition), "host": str(host)}
    return None


def _goal_subject_name(subject, bound, actor):
    """What to call a condition's subject in a goal, or None."""
    if subject in (None, ""):
        subject = "direct"
    if isinstance(subject, str):
        if subject == "actor":
            return str(getattr(actor, "key", "") or "") if actor else ""
        if subject in (HERE, WORLD):
            return None              # not a thing anybody can act on
        found = (bound or {}).get(subject)
        return str(getattr(found, "key", "") or "") if found is not None \
            else None
    try:
        wanted = dict(subject)
    except (TypeError, ValueError):
        return None
    if "named" in wanted:
        return str(wanted["named"])
    # An enclosure or a zone is a place, and a place is not something a planner
    # can walk up to and change.
    return None


def as_goals(conditions, bound=None, actor=None):
    """Every condition that has a goal form, in order, skipping those that do not."""
    found = []
    for condition in (conditions or []):
        wanted = as_goal(condition, bound, actor)
        if wanted is not None:
            found.append(wanted)
    return found



# ---------------------------------------------------------------------------
# The shape of a condition, for a tool's parameters (docs §4.1)
# ---------------------------------------------------------------------------

def schema(ctx=None):
    """
    One condition, as a finish tool's parameters describe it: a subject and
    one predicate. Which predicate is the model's choice, so every predicate
    is an optional field and `predicate_of` is what checks there is one.
    """
    from world import toolbox as tb

    world_root = getattr(ctx, "world_root", None)
    known_traits = []
    if world_root is not None:
        from world import traits

        known_traits = sorted(traits.vocabulary(world_root))

    def names(what):
        return {"type": "array", "items": {"type": "string"},
                "description": what}

    leaf = _leaf_schema(names, known_traits, tb)
    properties = dict(leaf["properties"])
    # One level of "or", over plain conditions and nothing deeper. A model is
    # offered no `all` and no nesting: a list of conditions already means all
    # of them, and a recursive schema is one some providers will not take.
    properties["any"] = {
        "type": "array", "items": leaf, "minItems": 2,
        "maxItems": MAX_MEMBERS,
        "description": "Instead of a subject and a predicate: conditions of "
                       "which any one will do"}
    # Nothing is required at this level: a plain condition needs its subject
    # and an `any` has none, and `normalise` is what holds either to its shape.
    return {"type": "object", "properties": properties, "required": []}


def _leaf_schema(names, known_traits, tb):
    """One plain condition: a subject and one predicate."""
    return {
        "type": "object",
        "properties": {
            "subject": {"description": "Whose condition: a participant ("
                                       + ", ".join(ROLES) + "), 'here', "
                                       "{\"enclosure\": <a kind>} or "
                                       "{\"zone\": true}"},
            "is": names("states it must be in"),
            "lacks": names("states it must not be in"),
            "affords": names("what must be doable to it"),
            "holds": names("what the subject must be carrying"),
            "not_holds": names("what the subject must not be carrying"),
            "wears": names("what the subject must have on"),
            "not_wears": names("what the subject must not have on"),
            "kind": {"description": "a sort of thing it must be"},
            "not_kind": {"description": "a sort of thing it must not be"},
            "owned_by": {"description": "'actor', a participant, 'nobody' or "
                                        "'somebody'"},
            "not_owned_by": {"description": "whose it must not be"},
            "placed": {"description": "where it must be put"},
            "not_placed": {"description": "where it must not be"},
            "trait": tb.choice(known_traits, "a figure it must reach",
                               ask="list_traits"),
            "min": {"type": "number", "description": "with trait: at least"},
            "max": {"type": "number", "description": "with trait: at most"},
            "below": {"type": "number",
                      "description": "with trait: less than, not equal"},
            "above": {"type": "number",
                      "description": "with trait: more than, not equal"},
            "in_room": {"description": "a room it must be in"},
            "not_in_room": {"description": "a room it must not be in"},
            "exists": {"type": "boolean", "description": "it must exist"},
            "gone": {"type": "boolean", "description": "it must be gone"},
            "able": {"type": "string", "enum": sorted(GATES),
                     "description": "what the subject must be free to do"},
            "reachable_by": {"description": "who must be able to reach it"},
            "visible_to": {"description": "who must be able to see it"},
            "leads_to": {"description": "where a way out must lead"},
            "not_leads_to": {"description": "where no way out may lead"},
            "never": {"type": "boolean",
                      "description": "never true: a rule nothing can pass"},
            "unbound": {"type": "boolean",
                        "description": "nobody named one"},
        },
        "required": ["subject"],
    }
