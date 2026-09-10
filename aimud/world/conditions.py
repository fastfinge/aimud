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
Context = namedtuple("Context", "bound actor world_root")
Context.__new__.__defaults__ = (None, None, None)


def context(bound=None, actor=None, world_root=None):
    """The world as a condition sees it."""
    if world_root is None and actor is not None:
        room = getattr(actor, "location", None)
        world_root = getattr(room.db, "world_root", None) if room else None
    return Context(dict(bound or {}), actor, world_root)


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
        from world import verbs, zones

        if self.what == ZONE:
            return zones.states(self.ctx.world_root, self.zone_id)
        if self.obj is not None:
            return verbs.states(self.obj)
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
            room = getattr(ctx.actor, "location", None)
            return Subject(ROOM, room, ctx=ctx) if room else Subject(ctx=ctx)
        if subject == WORLD:
            return Subject(WORLD, ctx.world_root, ctx=ctx)
        obj = ctx.actor if subject == "actor" else ctx.bound.get(subject)
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
    see `verbs.requirements`, which learned this the hard way.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    try:
        return [v for v in value if v]
    except TypeError:
        return [value]


def predicate_of(condition):
    """Which predicate a condition uses, and what it names."""
    for name in ("is", "lacks", "affords", "kind", "holds", "wears",
                 "placed", "trait", "in_room", "exists", "gone"):
        if name in condition:
            return name, condition[name]
    return "", None


def evaluate(condition, ctx):
    """Whether this condition holds. The one test everything shares."""
    met, _said = _judge(condition, ctx, WANT)
    return met


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


def unmet(conditions, ctx):
    """The first condition that does not hold, as a complaint, or ""."""
    for condition in (conditions or []):
        met, said = _judge(condition, ctx, UNMET)
        if not met:
            return said
    return ""


def _judge(condition, ctx, mood):
    """One condition, evaluated and said. The single implementation."""
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
        return f"{subject} can be {listed}"
    if name == "kind":
        from world import lexicon

        return f"{subject} {be} a {lexicon.word_of(value)}"
    if name == "holds":
        return f"{subject} {be} holding {listed or 'it'}"
    if name == "wears":
        return f"{subject} {be} wearing {listed or 'it'}"
    if name == "placed":
        try:
            preposition, host = next(iter(dict(value).items()))
        except (TypeError, ValueError, StopIteration):
            return f"{subject} {be} somewhere in particular"
        return f"{subject} {be} {preposition} {host}"
    if name == "trait":
        low, high = condition.get("min"), condition.get("max")
        label = str(value).replace("_", " ")
        if low is not None:
            return f"{subject} {have} {label} of {low} or more"
        if high is not None:
            return f"{subject} {have} {label} of {high} or less"
        return f"{subject} {have} some {label}"
    if name == "in_room":
        return f"{subject} {be} in {value}"
    if name == "exists":
        return f"{subject} exists"
    if name == "gone":
        return f"{subject} {be} gone"
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


def _p_holds(subject, value, condition, ctx, mood):
    """Whether the subject is carrying something."""
    if not subject.found:
        return _missing(subject, condition, mood)
    for wanted in _listed(value):
        held, said = _held(subject, wanted, ctx)
        if held:
            continue
        if mood == WANT:
            return False, f"be carrying {said}"
        return False, _plainly(subject, f"not holding {said}", ctx,
                               verb="is")
    return True, ""


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


def _p_wears(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    for wanted in _listed(value):
        worn = False
        for obj in (getattr(subject.obj, "contents", []) or []):
            if str(wanted).lower() in str(obj.key).lower() and obj.db.worn:
                worn = True
                break
        if not worn:
            if mood == WANT:
                return False, f"be wearing {wanted}"
            return False, _plainly(subject, f"not wearing {wanted}", ctx,
                                   verb="is")
    return True, ""


def _p_placed(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    from world import relations

    try:
        where = dict(value)
    except (TypeError, ValueError):
        return True, ""
    preposition, host_name = next(iter(where.items()), (None, None))
    if not preposition:
        return True, ""
    host = resolve(host_name, ctx)
    if not host.found:
        host_obj = _find(str(host_name), "", ctx)
    else:
        host_obj = host.obj
    met = relations.test(subject.obj, preposition, host_obj)
    called = host.name() if host.found else str(host_name)
    if mood == WANT:
        return met, f"get {subject.name()} {preposition} {called}"
    return met, (f"{_cap(subject.name())} is not {preposition} {called}.")


def _p_trait(subject, value, condition, ctx, mood):
    if not subject.found:
        return _missing(subject, condition, mood)
    from world import traits

    slug = str(value)
    low, high = condition.get("min"), condition.get("max")
    current = traits.value(subject.obj, slug)
    met = current is not None
    if met and low is not None:
        met = current >= low
    if met and high is not None:
        met = current <= high
    label = slug.replace("_", " ")
    if mood == WANT:
        if low is not None:
            return met, f"get {label} to {traits._round(low)}"
        if high is not None:
            return met, f"get {label} down to {traits._round(high)}"
        return met, f"have some {label}"
    return met, traits.meets(subject.obj, {slug: {"min": low, "max": high}}) \
        or f"{_cap(subject.name())} has no {label}."


def _p_in_room(subject, value, condition, ctx, mood):
    who = subject.obj if subject.found else ctx.actor
    here = getattr(who, "location", None)
    title = (here.db.room_title or here.key) if here is not None else ""
    met = bool(value) and str(value).lower() in str(title).lower()
    if mood == WANT:
        return met, f"be in {value}"
    return met, f"You are not in {value}."


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


_PREDICATES = {
    "is": _p_is,
    "lacks": _p_lacks,
    "affords": _p_affords,
    "kind": _p_kind,
    "holds": _p_holds,
    "wears": _p_wears,
    "placed": _p_placed,
    "trait": _p_trait,
    "in_room": _p_in_room,
    "exists": _p_exists,
    "gone": _p_gone,
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
    try:
        etype = str(effect.get("type") or "")
        condition = dict(condition)
    except AttributeError:
        return False
    name, value = predicate_of(condition)

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

    if name == "placed" and etype == "move_object":
        try:
            preposition = next(iter(dict(value)))
        except (TypeError, ValueError, StopIteration):
            return False
        return str(effect.get("preposition") or "") == preposition

    if name == "exists" and etype == "create_object":
        return True

    if name == "gone" and etype == "destroy_object":
        return True

    if name == "trait" and etype == "set_trait":
        if str(effect.get("trait") or "") != str(value):
            return False
        low = condition.get("min")
        change = effect.get("change")
        if low is not None and change is not None:
            return change > 0
        high = condition.get("max")
        if high is not None and change is not None:
            return change < 0
        return True

    if name == "in_room" and etype == "move_actor":
        return True

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

    if ctype == "in_room":
        return [{"subject": "actor", "in_room": condition.get("room", "")}]

    if ctype == "trait":
        entry = {"subject": "actor", "trait": condition.get("trait", "")}
        for edge in ("min", "max"):
            if condition.get(edge) is not None:
                entry[edge] = condition[edge]
        return [entry]

    if ctype == "state":
        out = []
        for clause in ("is", "lacks"):
            if condition.get(clause):
                out.append({"subject": subject, clause: condition[clause]})
        return out

    if ctype == "placed":
        preposition = condition.get("preposition") or "in"
        return [{"subject": subject,
                 "placed": {preposition: condition.get("host", "")}}]

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
