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
    """Whether one effect would satisfy one goal condition about `obj_name`."""
    etype = effect.get("type")
    ctype = condition.get("type")

    if ctype == "state" and etype == "set_state":
        wanted = {s.lower() for s in (condition.get("is") or [])}
        added = {str(s).lower() for s in (effect.get("add") or [])}
        if wanted and wanted <= added:
            return True
        unwanted = {s.lower() for s in (condition.get("lacks") or [])}
        removed = {str(s).lower() for s in (effect.get("remove") or [])}
        return bool(unwanted) and unwanted <= removed

    if ctype == "trait" and etype == "set_trait":
        if str(effect.get("trait", "")) != str(condition.get("trait", "")):
            return False
        # Which way the goal wants it to move, and which way this effect moves
        # it. A rate counts: an effect that starts something draining is how a
        # goal about a falling figure gets met, just not immediately.
        low, high = condition.get("min"), condition.get("max")
        wants_up = low is not None
        change = effect.get("change")
        rate = effect.get("rate")
        if effect.get("set_to") is not None:
            target = float(effect["set_to"])
            return (low is None or target >= low) and (high is None or target <= high)
        for amount in (change, rate):
            if amount is None:
                continue
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                continue
            if amount > 0 and wants_up:
                return True
            if amount < 0 and high is not None:
                return True
        return False

    if ctype == "holds" and etype == "move_object":
        return effect.get("to") == "actor"

    if ctype == "gone" and etype == "destroy_object":
        return True

    if ctype == "exists" and etype == "create_object":
        return obj_name.lower() in str(effect.get("name", "")).lower()
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
            kept = {str(a).lower() for a in effect["affordances"] or []}
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
    name = (obj_name or "").lower()

    def matches(room):
        return any(name in obj.key.lower() for obj in room.contents)

    return _route(actor.location, matches)


# ---------------------------------------------------------------------------
# Choosing the next step
# ---------------------------------------------------------------------------

def _bind(actor, name):
    return verbs.bind(actor, name, fuzzy=True)


def _for_condition(actor, world_root, condition):
    """
    One action that would advance `condition`, or None.

    Returns (action string, rule key or None). The rule key is what gets
    blamed if the action does not achieve what it promised.
    """
    ctype = condition.get("type")
    name = condition.get("object", "")

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
        if _bind(actor, recipient) is None:
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
        return _verb_for(actor, world_root, condition, obj)

    return None, None


def _needed_affordances(key):
    """
    What the direct object of a cached rule has to be, read off its key.

    A rule is stored under "eat#direct:edible", which says the rule applies to
    anything edible. That is exactly the question a planner has when it wants
    a trait raised and needs something to do it with -- so the answer is read
    back out of the key rather than stored twice.
    """
    _verb, _, signature = key.partition("#")
    for part in signature.split("|"):
        role, _, marks = part.partition(":")
        if role != "direct":
            continue
        if marks in ("", "plain"):
            return set()
        return {m for m in marks.split(",") if m}
    return None      # the rule takes no direct object at all


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
            wanted = _needed_affordances(key)
            if wanted is None:
                # A verb that acts on nothing in particular -- "rest", "pray".
                if verbs.check(rule.get("requires"), {}, actor) is None:
                    return verb, key
                continue

            obj = _thing_matching(actor, wanted)
            if obj is None:
                continue
            if verbs.check(rule.get("requires"), {"direct": obj}, actor) is not None:
                continue
            return f"{verb} {obj.key}", key
    return None, None


def _verb_for(actor, world_root, condition, obj):
    """
    A verb the world already knows that would put `obj` into the wanted state.

    Only rules whose preconditions currently hold are offered, so the planner
    never proposes lighting something already alight, and never proposes an
    action it has been told needs a key the character does not have.
    """
    from world import verb_gen

    rules = (world_root.db.verb_rules or {}) if world_root else {}
    # Success routes first, then the ones that only work by going wrong.
    for outcome in PLAN_OUTCOMES:
        for key, rule in rules.items():
            rule = dict(rule)
            if not rule.get("valid", True) or unreliable(world_root, key):
                continue
            if not _rule_would_achieve(rule, condition, obj.key, outcome):
                continue
            if outcome == "failure" and _burns_itself_down(rule):
                continue
            bound = {"direct": obj}
            if verbs.check(rule.get("requires"), bound, actor) is not None:
                continue
            verb = key.split("#", 1)[0]
            return f"{verb} {obj.key}", key
    return None, None


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
    return None, (
        f"Nothing you can do from here would help you {wanted}. "
        f"Whatever it needs may be somewhere you have not been yet."
    )


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
