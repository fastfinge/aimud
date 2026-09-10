"""
Working out what to do next about a goal.

Layer B. No model calls: the world has already been taught what verbs do, in
exactly the form a planner needs. A verb rule is preconditions plus effects,
which is a planning operator; a goal is a set of testable conditions; and the
coordinate index makes the map searchable. All three were built for other
reasons, so this is mostly a matter of reading them.

It is deliberately shallow. It finds one next step, not a whole plan, and
takes it -- then looks again next time. That is what makes it safe against
the one real weakness here: effects are written by a model and describe what
happens incompletely. A long plan built on a wrong effect fails silently at
the end; a single step that does not achieve what it promised is noticed
immediately, and the rule that promised it is set aside.
"""

from evennia.utils import logger

from world import goals, verbs

#: How many times a rule may promise something and not deliver before the
#: planner stops believing it.
FAILURES_ALLOWED = 2

#: How far to look for a room a goal names. Beyond this an NPC is wandering,
#: not going somewhere.
MAX_TRAVEL = 12

#: How many times a wanted thing may turn into the thing wanted before it.
#:
#: "To launch, first power" is one step of this. "To power, first find the fuel
#: rod; to find it, first open the locker" is three, and the honest reason to stop
#: is not cost but trust: every link is read off an effect a model wrote, and this
#: planner's whole safety argument is that it takes one step and looks again. A
#: chain four deep built on four approximate effects is the long plan that fails
#: silently at the end, which is the thing being avoided.
#:
#: Three, because the spaceship needs one and a lock with a key needs two.
MAX_SUBGOALS = 3


# ---------------------------------------------------------------------------
# Trusting the rules
# ---------------------------------------------------------------------------

def _failures(world_root):
    return dict(world_root.db.rule_failures or {}) if world_root else {}


def unreliable(world_root, key):
    """True when a rule has promised something and not delivered too often."""
    return _failures(world_root).get(key, 0) >= FAILURES_ALLOWED


def note_failure(world_root, key):
    """
    Record that a rule did not bring about what its effects claimed.

    Effects are model-written and often incomplete. Without this an NPC would
    keep choosing the same broken step forever, achieving nothing and looking
    stuck rather than thoughtful.
    """
    if not world_root or not key:
        return
    counts = _failures(world_root)
    counts[key] = counts.get(key, 0) + 1
    world_root.db.rule_failures = counts
    if counts[key] >= FAILURES_ALLOWED:
        logger.log_info(
            f"planner: rule {key!r} did not do what it promised "
            f"{counts[key]} times; no longer planning with it"
        )


# ---------------------------------------------------------------------------
# Would this effect make that condition true?
# ---------------------------------------------------------------------------

def _effect_achieves(effect, condition, obj_name):
    """
    Whether one effect would satisfy one goal condition about `obj_name`.

    `world.conditions.achieves` does the reading. What stays here is the one
    thing it cannot know: the planner may have resolved a condition that named
    a *sort* of thing down to a particular one -- "a cake" to the nearest cake
    -- and it is that name a `create_object` effect has to match.
    """
    from world import conditions as C

    for part in C.from_goal(condition):
        if obj_name and isinstance(part.get("subject"), dict):
            part = dict(part, subject={"named": obj_name})
        if C.achieves(effect, part):
            return True
    return False


#: The outcomes a plan may aim at, in the order it should prefer them.
#:
#: Failing is a real route to some things and the only route to a few. A
#: character who wants a broken shoulder gets one by forcing a door they
#: cannot force, and one who wants to be rid of what they are carrying gets
#: that from the branch where they drop it -- so a planner that reads only
#: success leaves goals the world can satisfy looking impossible.
#:
#: But it is a route whose likeliest outcome is something else, and usually
#: something the character did NOT want. A rule that happens to light a lamp
#: when smashing it goes wrong is not the way to light a lamp while any rule
#: lights one on purpose. So both are searched and success is searched first:
#: failing on purpose is a last resort, which is what it is.
PLAN_OUTCOMES = ("success", "failure")


def _rule_would_achieve(rule, condition, obj_name, outcome="success"):
    from world import checks

    return any(
        _effect_achieves(effect, condition, obj_name)
        for effect in checks.effects_for(rule, outcome)
    )


def _effect_role(effect):
    """Which role an effect acts on, however it happens to name it."""
    for key in ("name_role", "role", "to_role"):
        role = effect.get(key)
        if role:
            return str(role)
    return ""


def _burns_itself_down(rule):
    """
    True when succeeding at this rule makes it impossible to attempt again.

    Only matters for a plan that is aiming at the failure branch. Failing is a
    route you cannot choose, so it is worth taking only when you can keep
    taking it: attacking a guard until one of the blows goes badly is a way of
    getting hurt, but forcing a door that is then open is one attempt at
    getting hurt and afterwards a door standing open for no reason anybody in
    the room can see.

    Read off the rule alone, by asking whether its own success would falsify
    its own preconditions. Nothing is rolled and nothing is simulated -- this
    runs inside the planner's search, which costs nothing and must go on
    costing nothing.

    Traits are deliberately not considered. Whether spending five stamina
    drops a character below the ten a rule needs depends on what they have
    now, which makes it a question about this attempt rather than about the
    rule, and answering it wrongly would hide a perfectly repeatable route.
    """
    from world import checks, verbs

    # Read through the same normaliser the checks use, so a clause written as
    # one word rather than a list of one is a condition here too and not a
    # string this walks letter by letter.
    requires = verbs.requirements(rule.get("requires"))
    if not requires:
        return False

    for effect in checks.effects_for(rule, "success"):
        try:
            etype = str(effect.get("type", ""))
        except AttributeError:
            continue
        role = _effect_role(effect)
        needed = requires.get(role) if role else None
        if needed is None:
            continue

        if etype == "destroy_object":
            return True     # the thing the rule needs will not be there
        if etype == "set_state":
            added = {str(s) for s in effect.get("add") or []}
            removed = {str(s) for s in effect.get("remove") or []}
            if added & {str(s) for s in needed.get("lacks") or []}:
                return True
            if removed & {str(s) for s in needed.get("is") or []}:
                return True
        if etype == "modify_object" and effect.get("affordances") is not None:
            from world import affordances as af

            kept = af.afforded(af.normalise(effect["affordances"]))
            if {str(a).lower() for a in needed.get("has") or []} - kept:
                return True
    return False


# ---------------------------------------------------------------------------
# Getting about
# ---------------------------------------------------------------------------

def _route(start_room, matches, limit=MAX_TRAVEL):
    """
    First step of the shortest way from `start_room` to any room `matches`.

    Walks the exits rather than the coordinate grid: two rooms can be next to
    each other with a wall between them, and a plan that walks through walls
    is not a plan.
    """
    if start_room is None:
        return None
    seen = {start_room.id}
    # (room, the direction we first left the start room by)
    queue = [(start_room, None, 0)]
    while queue:
        room, first_step, depth = queue.pop(0)
        if first_step and matches(room):
            return first_step
        if depth >= limit:
            continue
        for obj in room.contents:
            destination = getattr(obj, "destination", None)
            if destination is None or destination is room:
                continue
            if destination.id in seen:
                continue
            seen.add(destination.id)
            queue.append((destination, first_step or obj.key, depth + 1))
    return None


def _step_towards_room(actor, room_name):
    name = (room_name or "").lower()

    def matches(room):
        title = (room.db.room_title or room.key or "").lower()
        return bool(name) and name in title

    return _route(actor.location, matches)


def _step_towards_object(actor, obj_name):
    name = (obj_name or "").strip().lower()
    if not name:
        # An empty name is in every string there has ever been, so this would
        # otherwise answer "yes" for any room holding anything, and send a
        # character to whichever one is nearest -- for ever, since arriving
        # achieves nothing. Nothing to look for is not the same as something
        # findable everywhere.
        return None

    def matches(room):
        return any(name in obj.key.lower() for obj in room.contents)

    return _route(actor.location, matches)


# ---------------------------------------------------------------------------
# Choosing the next step
# ---------------------------------------------------------------------------

def _bind(actor, name):
    return verbs.bind(actor, name, fuzzy=True)


def _for_condition(actor, world_root, condition, depth=0):
    """
    One action that would advance `condition`, or None.

    Returns (action string, rule key or None). The rule key is what gets
    blamed if the action does not achieve what it promised.

    `depth` counts how many wants deep this is: a goal is 0, the precondition of
    a verb that would satisfy it is 1, and so on to `MAX_SUBGOALS`. Only the
    state branch recurses, because that is the only one whose answer is a verb
    with preconditions of its own -- walking somewhere and picking something up
    are mechanics, and a mechanic has no rulebook to be refused by.
    """
    ctype = condition.get("type")
    name = condition.get("object", "")

    if not name and condition.get("kind"):
        # A want may name a sort of thing rather than one thing -- "a cake",
        # not "the chocolate cake". Testing whether it is met knows that;
        # planning towards it did not, and every branch below is written round
        # a name. So the kind is resolved to whichever one is nearest and the
        # rest proceeds unchanged.
        #
        # Nothing anywhere of that sort means there is nothing to walk towards
        # and no step to take, which the goal above will notice and spend its
        # patience on. That is the honest answer: before this, an unfound kind
        # left the name empty, and an empty name matches every object in the
        # world -- so a character with no soju anywhere to find would set off
        # towards the nearest room that had anything in it at all, arrive, and
        # set off again.
        from world.goals import find_of_kind

        found = find_of_kind(world_root, actor, condition["kind"])
        if found is None:
            return None, None
        name = found.key

    if ctype == "in_room":
        step = _step_towards_room(actor, condition.get("room", ""))
        return (step, None) if step else (None, None)

    if ctype == "holds":
        obj = _bind(actor, name)
        if obj is not None and obj.location is not actor:
            if obj.location is actor.location:
                return f"get {obj.key}", None
            return (_step_towards_object(actor, name), None)
        if obj is None:
            step = _step_towards_object(actor, name)
            return (step, None) if step else (None, None)
        return None, None

    if ctype == "worn":
        # Three steps, one at a time: find it, pick it up, put it on. Wearing
        # is a mechanic rather than a learned verb, so there is no rule to
        # blame and nothing to check afterwards -- it either went on or it did
        # not, and the next look will say which.
        obj = _bind(actor, name)
        if obj is None:
            step = _step_towards_object(actor, name)
            return (step, None) if step else (None, None)
        if obj.location is not actor:
            if obj.location is actor.location:
                return f"get {obj.key}", None
            return (_step_towards_object(actor, name), None)
        if not obj.db.worn:
            return f"wear {obj.key}", None
        return None, None

    if ctype == "placed":
        # Fetch it, find the thing it goes at, put it there. Placement is a
        # mechanic rather than a learned verb, so there is no rule to blame
        # and nothing to check afterwards.
        from world import relations

        host_name = condition.get("host", "")
        preposition = condition.get("preposition") or relations.DEFAULT
        obj = _bind(actor, name)
        if obj is None:
            step = _step_towards_object(actor, name)
            return (step, None) if step else (None, None)
        host = _bind(actor, host_name)
        if host is None:
            step = _step_towards_object(actor, host_name)
            return (step, None) if step else (None, None)
        if obj.location is not actor and relations.host_of(obj) is not host:
            return f"get {obj.key}", None
        return f"put {obj.key} {preposition} {host.key}", None

    if ctype == "delivered":
        obj = _bind(actor, name)
        recipient = condition.get("to", "")
        if obj is None:
            step = _step_towards_object(actor, name)
            return (step, None) if step else (None, None)
        if obj.location is not actor:
            return f"get {obj.key}", None
        target = _bind(actor, recipient)
        if target is actor:
            # A delivery to oneself, which is a want to be holding the thing,
            # and it is held: there is nothing left to do. Goals made since
            # this was understood are written down as `holds` on the way in;
            # ones stored before that are not, and `_test` and this both bind
            # the recipient by their own rules and can disagree about who it
            # is. Offering the step anyway would spend the turn on a `give`
            # that both implementations refuse without a word.
            return None, None
        if target is None:
            step = _step_towards_object(actor, recipient)
            return (step, None) if step else (None, None)
        return f"give {obj.key} to {recipient}", None

    if ctype == "trait":
        return _trait_step(actor, world_root, condition)

    if ctype in ("state", "gone"):
        obj = _bind(actor, name)
        if obj is None:
            step = _step_towards_object(actor, name)
            return (step, None) if step else (None, None)
        return _verb_for(actor, world_root, condition, obj, depth)

    return None, None


def _needed_affordances(key, rule=None):
    """
    What the direct object of a rule has to be able to do.

    Read off the rule rather than off the key. A rule used to be stored under
    "eat#direct:edible", so the key carried the answer; now a rule is stored
    under "eat" and nothing else, because what a verb means stopped depending
    on what it was first tried on. What remains is the rule's own `requires`,
    which is where the condition was always stated.

    None still means the rule acts on nothing in particular -- "rest", "pray"
    -- and an empty set still means it acts on a direct object that need not
    be anything special.
    """
    try:
        needed = dict((rule or {}).get("requires") or {})
    except (AttributeError, TypeError, ValueError):
        return None
    if "direct" not in needed:
        return None
    try:
        return {str(a) for a in (dict(needed["direct"]).get("has") or [])}
    except (AttributeError, TypeError, ValueError):
        return set()


def _kinds_admitting(world_root, verb):
    """
    Every kind this world has decided can be verbed this way.

    The planner's other way of finding something to act on, now that a rule
    no longer carries an affordance in its key. A verb with no affordance
    requirement at all -- and most have none -- used to leave the planner
    nothing to search for; the kind table knows which sorts of thing admit it.
    """
    from world import kinds as kinds_mod

    found = set()
    if not world_root:
        return found
    for kind in kinds_mod.vocabulary(world_root):
        entry = kinds_mod.spec(world_root, kind) or {}
        try:
            if dict(entry.get("affordances") or {}).get(verb):
                found.add(kind)
        except (AttributeError, TypeError, ValueError):
            continue
    return found


def _thing_of_kind(actor, wanted_kinds):
    """Something in reach whose kind admits the verb, nearest first."""
    for location in (actor, actor.location):
        for obj in (location.contents if location else []):
            if getattr(obj, "destination", None) is not None or obj is actor:
                continue
            if set(obj.db.kinds or []) & wanted_kinds:
                return obj
    return None


def _thing_matching(actor, wanted):
    """Something in reach with all of these affordances, nearest first."""
    for location in (actor, actor.location):
        for obj in (location.contents if location else []):
            if getattr(obj, "destination", None) is not None:
                continue
            if obj is actor:
                continue
            if wanted <= verbs.affordances(obj):
                return obj
    return None


def _trait_step(actor, world_root, condition):
    """
    Something to do that would move a figure about this character.

    The world has already been taught which verbs change which traits -- that
    is what a rule's set_trait effect is -- so wanting to be stronger becomes
    a search for a verb the world knows will raise strength, and then for
    something in reach to use it on. "To recover your stamina, eat something
    edible" falls out of the rules themselves rather than being written here.
    """
    rules = (world_root.db.verb_rules or {}) if world_root else {}
    slug = condition.get("trait", "")

    # Every rule is tried as a way of succeeding before any is tried as a way
    # of failing. See PLAN_OUTCOMES.
    for outcome in PLAN_OUTCOMES:
        for key, rule in rules.items():
            rule = dict(rule)
            if not rule.get("valid", True) or unreliable(world_root, key):
                continue
            if not _rule_would_achieve(rule, condition, slug, outcome):
                continue
            if outcome == "failure" and _burns_itself_down(rule):
                continue

            verb = key.split("#", 1)[0]
            wanted = _needed_affordances(key, rule)
            if wanted is None:
                # A verb that acts on nothing in particular -- "rest", "pray".
                if verbs.check(rule.get("requires"), {}, actor) is None:
                    return verb, key
                continue

            obj = _thing_matching(actor, wanted) if wanted else None
            if obj is None:
                # Nothing declares the capability, which is the ordinary case:
                # most rules require no affordance at all. The kinds this
                # world has decided admit the verb are the other way in.
                obj = _thing_of_kind(actor, _kinds_admitting(world_root, verb))
            if obj is None:
                continue
            if verbs.check(rule.get("requires"), {"direct": obj}, actor) is not None:
                continue
            return f"{verb} {obj.key}", key

    return _trait_step_by_object(actor, world_root, condition, slug)


def _trait_step_by_object(actor, world_root, condition, slug):
    """
    The same search, asked of particular things rather than of rules.

    A rule says what a verb does to everything of its sort, and that is what
    the scan above reads. But an object may carry its own effects -- what
    happens when *this* pie is eaten -- and one of them may move a figure the
    verb's own rule never mentions. A rule-only scan cannot see that, so an
    NPC would never think to eat the one thing in the room that would restore
    it, and would spend the goal's patience finding out.

    Second rather than first because it is the narrow case and the expensive
    one: it looks at things in reach instead of at what the world knows. Most
    objects carry specifics for one verb and most carry none at all, so in
    practice this is a short loop over a short list.
    """
    rules = (world_root.db.verb_rules or {}) if world_root else {}
    for location in (actor, actor.location):
        for obj in (location.contents if location else []):
            if getattr(obj, "destination", None) is not None or obj is actor:
                continue
            try:
                specifics = dict(obj.db.verb_specifics or {})
            except (TypeError, ValueError):
                continue
            for verb, entry in specifics.items():
                rule = rules.get(verb)
                if not rule or unreliable(world_root, verb):
                    continue
                merged = dict(rule)
                try:
                    if dict(entry).get("effects") is not None:
                        merged["effects"] = dict(entry)["effects"]
                except (AttributeError, TypeError, ValueError):
                    continue
                for outcome in PLAN_OUTCOMES:
                    if not _rule_would_achieve(merged, condition, slug, outcome):
                        continue
                    if outcome == "failure" and _burns_itself_down(merged):
                        continue
                    if verbs.check(merged.get("requires"), {"direct": obj},
                                   actor) is not None:
                        continue
                    return f"{verb} {obj.key}", verb
    return None, None


def _verb_for(actor, world_root, condition, obj, depth=0):
    """
    A verb the world already knows that would put `obj` into the wanted state.

    Two stores are searched, because a world mid-cutover holds both: the learned
    verb rules, one per verb, and the rulebook, where everything written since
    phase 7 lives. Reading only the first was a real blindness -- every check rule
    a world has written since the rulebooks arrived was invisible here, so the
    planner would propose launching a cold ship, watch the attempt be refused, and
    blame the rule for not doing what it promised.

    A verb whose own preconditions are unmet is not discarded. It becomes the
    question "what would meet them", and that is the subgoal: `launch` refused for
    want of power is the goal "the ship is powered" is the step `power`. One link
    at a time and no more than `MAX_SUBGOALS` of them.
    """
    bound = {"direct": obj}

    # Success routes first, then the ones that only work by going wrong. The
    # blocked candidates are kept rather than dropped: if nothing is ready to go,
    # the nearest thing to ready is what the next step should be about.
    blocked = []
    for outcome in PLAN_OUTCOMES:
        for action, key, unmet in _candidates(actor, world_root, condition,
                                              obj, outcome):
            if not unmet:
                return action, key
            blocked.append((action, key, unmet))

    if depth >= MAX_SUBGOALS:
        return None, None
    for _action, key, unmet in blocked:
        for wanted in unmet:
            step, blame = _towards(actor, world_root, wanted, bound, depth + 1)
            if step:
                # Blamed on the rule whose precondition this is in aid of, not on
                # the one that will be run: if powering the ship does not leave it
                # powered, the rule that says what powering does is the one that
                # promised something it did not deliver.
                return step, blame or key
    return None, None


def _towards(actor, world_root, condition, bound, depth):
    """
    One step towards a condition written in the condition language.

    The bridge between the two vocabularies. A check rule refuses in conditions
    and the planner plans in goals, so the condition is read back into a goal --
    naming whatever the role was bound to, since `direct` means nothing to a
    planner looking at the world next turn and the ship does.
    """
    from world import conditions

    wanted = conditions.as_goal(condition, bound, actor)
    if wanted is None:
        return None, None
    return _for_condition(actor, world_root, wanted, depth)


def _candidates(actor, world_root, condition, obj, outcome):
    """
    Every verb that might bring this condition about, with what blocks each.

    Yields `(action, rule key or None, unmet conditions)`. An empty list of unmet
    conditions means it is ready to be done now.
    """
    from world import rulebooks, verb_gen

    seen = set()
    learned = (world_root.db.verb_rules or {}) if world_root else {}
    for key, rule in learned.items():
        rule = dict(rule)
        if not rule.get("valid", True) or unreliable(world_root, key):
            continue
        if not _rule_would_achieve(rule, condition, obj.key, outcome):
            continue
        if outcome == "failure" and _burns_itself_down(rule):
            continue
        verb = key.split("#", 1)[0]
        seen.add(verb)
        if verbs.check(rule.get("requires"), {"direct": obj}, actor) is not None:
            # The old shape hands back a sentence rather than conditions, so
            # there is nothing to turn into a subgoal. Skipped, as before.
            continue
        yield (f"{verb} {obj.key}", key,
               conditions_unmet_for(actor, world_root, verb, obj))

    if outcome != "success":
        return                    # a rulebook rule has no failure branch to read
    for rule in rulebooks.all_rules(world_root):
        if rule.get("phase") != rulebooks.CARRY_OUT:
            continue
        if not rule.get("listed", True):
            continue
        verb = rule.get("action")
        if not verb or verb in seen:
            continue
        if not _achieves_any(rule.get("effects"), condition, obj.key):
            continue
        seen.add(verb)
        yield (f"{verb} {obj.key}", None,
               conditions_unmet_for(actor, world_root, verb, obj))


def _achieves_any(effects, condition, obj_name):
    """Whether any of these effects would bring the condition about."""
    for effect in (effects or []):
        try:
            if _effect_achieves(dict(effect), condition, obj_name):
                return True
        except (AttributeError, TypeError, ValueError):
            continue
    return False


def conditions_unmet_for(actor, world_root, verb, obj):
    """
    The check conditions that would refuse this verb on this object right now.

    Read out of the rulebooks rather than guessed, so the planner and the pipeline
    cannot disagree about why something is refused: this gathers the same rules in
    the same order that an actual attempt would.
    """
    from world import conditions, rulebooks

    bound = {"direct": obj}
    ctx = conditions.context(bound, actor, world_root, verb)
    found = []
    try:
        book = rulebooks.for_attempt(world_root, verb, bound, actor,
                                     phase=rulebooks.CHECK)
    except Exception:
        return []
    for rule in book:
        for condition in (rule.get("conditions") or []):
            if not conditions.evaluate(condition, ctx):
                found.append(dict(condition))
    return found


def plan_for(actor, world_root, goal):
    """
    The next thing to do about `goal`, whoever's goal it is.

    Returns (action, rule_key, condition) or (None, None, None). The action is
    written the way a player would type it, so it goes through exactly the same
    verb pipeline -- an NPC pursuing a goal is doing ordinary things, not
    operating a private mechanism. That is also what lets the same answer be
    handed to a player as a suggestion: it is a command, not an instruction to
    some inner machinery.
    """
    goal = list(goal or [])
    if not goal or actor.location is None:
        return None, None, None

    for condition, (met, _text) in zip(goal, goals.progress(goal, actor, world_root)):
        if met:
            continue
        action, key = _for_condition(actor, world_root, condition)
        if action:
            return action, key, dict(condition)
    return None, None, None


def plan_step(actor, world_root):
    """The next thing this character should do about its own goal."""
    return plan_for(actor, world_root, actor.db.goal)


def advise(actor, world_root, goal):
    """
    What to do next about a goal, for somebody who will do it themselves.

    Returns (action, note). `action` is the command to type, or None when
    there is nothing to suggest; `note` says what it is in aid of, or why
    there is no suggestion. Nothing here decides anything or acts: this is the
    planner answering a question, which is the whole difference between
    helping a player and playing for them.
    """
    if not goal:
        return None, "You have nothing in mind."
    if goals.satisfied(goal, actor, world_root):
        return None, "You have done it."

    action, _key, condition = plan_for(actor, world_root, goal)
    if action:
        _met, text = goals._test(condition, actor, world_root)
        return action, text

    outstanding = [text for met, text in goals.progress(goal, actor, world_root)
                   if not met]
    # Goal descriptions read as "be in Library", "be carrying brass lamp", so
    # they take a verb-phrase frame -- "closer to be in Library" does not.
    wanted = outstanding[0] if outstanding else "do that"

    # Before giving up: a verb this world has never been taught might do it.
    # Offered here and only here, because finding out costs a model call and a
    # person asking for advice is somebody who can decide to spend it. A
    # character acting on a tick is not, and `plan_for` never reaches this.
    for condition in goal:
        met, _text = goals._test(condition, actor, world_root)
        if met or str(condition.get("type") or "") != "state":
            continue
        obj = _bind(actor, condition.get("object", ""))
        if obj is None:
            continue
        for verb in untried_verbs(world_root, condition):
            return f"{verb} {obj.key}", (
                f"Nothing here knows how to {wanted}. |w{verb}|n might be the "
                f"word for it, but nobody has tried -- so the world would have "
                f"to work out what it means.")

    return None, (
        f"Nothing you can do from here would help you {wanted}. "
        f"Whatever it needs may be somewhere you have not been yet."
    )


# ---------------------------------------------------------------------------
# A verb nobody has taught this world yet
# ---------------------------------------------------------------------------

def untried_verbs(world_root, condition, limit=3):
    """
    Verbs that might bring a wanted state about, which this world has no rule for.

    Two lexical routes, cheapest first. The state usually names its own verb --
    `powered` is what `power` leaves behind -- and when it does not, the
    inverted causation relation answers the harder question: to make something
    descend, fell it or lower it. See `lexicon.causing`.

    **Nothing here is knowledge.** Every name is a guess that a verb exists and
    means what its spelling suggests, and the world has to be asked before any of
    it is true -- which costs a model call. So this is offered to a person who can
    decide to spend it, through `advise`, and never taken by a character acting on
    a tick. A planner that bought rules on a timer is the clock this design keeps
    refusing, wearing a different hat.
    """
    from world import lexicon, suggest

    wanted = ""
    for clause in ("is",):
        for state in (condition.get(clause) or []):
            wanted = str(state)
            break
    if not wanted:
        return []

    plain = suggest._verb_for_state(wanted)
    found = []
    for verb in [plain] + lexicon.causing(plain, limit=limit):
        if not verb or verb in found:
            continue
        if _world_knows(world_root, verb):
            continue
        found.append(verb)
    return found[:limit]


def _world_knows(world_root, verb):
    """Whether this world has already decided what a verb does."""
    from world import rulebooks

    learned = (world_root.db.verb_rules or {}) if world_root else {}
    if any(key.split("#", 1)[0] == verb for key in learned):
        return True
    for rule in rulebooks.all_rules(world_root):
        if rule.get("action") == verb and rule.get("listed", True):
            return True
    return verb in verbs.command_verbs()


def check_outcome(actor, world_root, condition, rule_key):
    """
    Did the step do what it promised? Call after acting.

    A rule that repeatedly fails to bring about its own stated effect is set
    aside, which is the whole reason this is one step at a time.
    """
    if not rule_key or not condition:
        return
    met, _text = goals._test(condition, actor, world_root)
    if met:
        return

    # A contested rule is allowed to not work: that is what a check is for,
    # and losing a fight twice is not evidence that fighting is broken. Left
    # unguarded, this would quietly blacklist every verb worth rolling for.
    from world import checks, verb_gen

    if checks.wanted(verb_gen.get_rule(world_root, rule_key)):
        return
    note_failure(world_root, rule_key)
