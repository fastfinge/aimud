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
Context = namedtuple("Context", "bound actor world_root action")
Context.__new__.__defaults__ = (None, None, None, "")


def context(bound=None, actor=None, world_root=None, action=""):
    """The world as a condition sees it."""
    if world_root is None and actor is not None:
        room = getattr(actor, "location", None)
        world_root = getattr(room.db, "world_root", None) if room else None
    return Context(dict(bound or {}), actor, world_root, str(action or ""))


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
                 "placed", "trait", "in_room", "exists", "gone",
                 "able", "reachable_by", "visible_to", "leads_to", "never",
                 "unbound"):
        if name in condition:
            return name, condition[name]
    return "", None


def evaluate(condition, ctx):
    """Whether this condition holds. The one test everything shares."""
    met, _said = _judge(condition, ctx, WANT)
    return met


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
    missing = []
    for wanted in _listed(value):
        worn = any(str(wanted).lower() in str(obj.key).lower() and obj.db.worn
                   for obj in (getattr(subject.obj, "contents", []) or []))
        if not worn:
            missing.append(str(wanted))
    listed = " and ".join(missing or [str(v) for v in _listed(value)]) or "it"
    if mood == WANT:
        return not missing, f"be wearing {listed}"
    return not missing, _plainly(subject, f"not wearing {listed}", ctx,
                                 verb="is")


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
            or (here is not None and subject.obj.location is here))
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
    if mood == WANT:
        return within, f"get within reach of {subject.name()}"
    return within, f"{_cap(subject.name())} is out of reach."


_PREDICATES = {
    "is": _p_is,
    "visible_to": _p_visible,
    "leads_to": _p_leads_to,
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
        # Set outright: the question is whether where it lands is where the
        # goal wanted it.
        if effect.get("set_to") is not None:
            try:
                target = float(effect["set_to"])
            except (TypeError, ValueError):
                return False
            return ((low is None or target >= low)
                    and (high is None or target <= high))
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
            if amount > 0 and low is not None:
                return True
            if amount < 0 and high is not None:
                return True
        return False

    if name == "in_room" and etype == "move_actor":
        # The loosest answer in here, and deliberately so. `move_actor` names an
        # exit -- {"exit": "north"} -- not a destination, so whether it reaches
        # the dock depends on where north leads, which is a fact about the world
        # and not about the effect. This function is handed an effect and a
        # condition and nothing else, on purpose, and answers "would that shape
        # help"; the step is checked when it is taken.
        #
        # So the planner may try a door that turns out to go elsewhere, and
        # learn by trying. The alternative -- letting `move_actor` name the room
        # as well as the way -- is worth doing the day a goal about being
        # somewhere is planned wrongly often enough to notice, and not before.
        # Contrast `set_exit` above, which names its room and is read exactly.
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

    name = _goal_subject_name(condition.get("subject"), bound, actor)
    if name is None:
        return None

    predicate, value = predicate_of(condition)
    if predicate in ("is", "lacks"):
        listed = [str(s) for s in _listed(value) if s]
        return {"type": "state", "object": name, predicate: listed} \
            if listed else None
    if predicate == "holds":
        wanted = [str(s) for s in _listed(value) if s]
        return {"type": "holds", "object": wanted[0]} if wanted else None
    if predicate == "wears":
        wanted = [str(s) for s in _listed(value) if s]
        return {"type": "worn", "object": wanted[0]} if wanted else None
    if predicate == "trait":
        entry = {"type": "trait", "trait": str(value)}
        for edge in ("min", "max"):
            if condition.get(edge) is not None:
                entry[edge] = condition[edge]
        return entry
    if predicate == "in_room":
        return {"type": "in_room", "room": str(value)}
    if predicate == "exists":
        return {"type": "exists", "object": name} if bool(value) else None
    if predicate == "gone":
        return {"type": "gone", "object": name} if bool(value) else None
    if predicate == "placed":
        try:
            where = dict(value)
        except (TypeError, ValueError):
            return None
        for preposition, host in where.items():
            return {"type": "placed", "object": name,
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

