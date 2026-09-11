"""
Goals: conditions about the world that can be tested.

A goal is a small list of conditions, each of which is either true or false
right now. That is the whole of it -- no planning, no search. Testing is cheap
enough to do whenever the world changes, and costs nothing at all in model
calls.

The same representation serves two purposes that look different and are not:

* An NPC's goal is what it wants. Handed to the dialogue model as context, it
  makes a character act with intent instead of reacting to whatever was said
  last, without any planner behind it.

* A player's quest is a goal with a reward attached. Nobody has to work out
  how the player should achieve it -- they do that themselves -- so a quest
  needs only the testing half, which is the cheap half.

The condition vocabulary deliberately mirrors verb preconditions, so anything
a verb can require of the world is also something a goal can ask for.
"""

#: Condition types understood here. Anything else is discarded on the way in,
#: so a model inventing a condition cannot produce a quest nobody can finish.
CONDITION_TYPES = ("state", "holds", "worn", "trait", "placed", "in_room",
                   "exists", "gone", "delivered")

#: How somebody refers to themselves. A want written in the first person and
#: then formalised comes back with one of these where a name would go.
_SELF_WORDS = frozenset([
    "me", "myself", "self", "himself", "herself", "themselves", "itself",
])


def _names_owner(name, owner):
    """
    Whether a recipient a goal names is the character whose goal it is.

    Deliberately strict: the character's own key, one of its aliases, or a
    word that can only mean the speaker. Nothing looser. A character called
    "Princess Joy" answers to "Joy" when spoken to, but a world may hold
    somebody actually named Joy -- and `find_object` prefers an exact key
    match over a partial one, so it would deliver to her. Guessing wider here
    would quietly rewrite one goal into a different one.
    """
    wanted = str(name or "").strip().lower()
    if not wanted or owner is None:
        return False
    if wanted in _SELF_WORDS:
        return True
    if wanted == str(getattr(owner, "key", "") or "").strip().lower():
        return True
    try:
        return wanted in {str(alias).lower() for alias in owner.aliases.all()}
    except AttributeError:
        return False


def _world_objects(world_root, actor):
    """Everything a goal could plausibly refer to, nearest first."""
    seen, out = set(), []

    def add(obj):
        if obj is not None and obj.id not in seen:
            seen.add(obj.id)
            out.append(obj)

    for obj in actor.contents:
        add(obj)
    if actor.location:
        for obj in actor.location.contents:
            add(obj)
            for held in obj.contents:
                add(held)
    if world_root:
        from evennia import search_tag

        for room in search_tag(str(world_root.id), category="ai_world"):
            add(room)
            for obj in room.contents:
                add(obj)
                for held in obj.contents:
                    add(held)
    return out


def find_of_kind(world_root, actor, kind, actor_only=False):
    """
    Anything in this world that is the sort of thing wanted, nearest first.

    What lets a want be general. A character can want the chocolate cake, and
    a character can want *a* cake, and until kinds existed only the first of
    those could be written down -- every condition had to name one object, so
    "I am hungry" had to be forged into a demand for one particular bun that
    might be eaten by somebody else before they got there.

    Nearest first for the same reason `_world_objects` is: a goal satisfied by
    any cake should be satisfied by the cake in the room rather than sending
    somebody across the world for an identical one.
    """
    from world import kinds as kinds_mod

    wanted = kinds_mod.canonical(kind)
    if not wanted:
        return None
    for obj in (actor.contents if actor_only else
                _world_objects(world_root, actor)):
        for owned in (obj.db.kinds or []):
            if kinds_mod.canonical(owned) == wanted:
                return obj
    return None


def find_object(world_root, actor, name):
    """
    Resolve a name a goal mentions to a real object anywhere in the world.

    Deliberately wider than verb binding: a quest can be about something in
    another room, which is the point of having somewhere to go.
    """
    if not name:
        return None
    wanted = name.lower().strip()
    candidates = _world_objects(world_root, actor)
    for obj in candidates:
        if obj.key.lower() == wanted:
            return obj
    for obj in candidates:
        if wanted in obj.key.lower():
            return obj
    return None


def sanitise(conditions, owner=None):
    """
    Keep only conditions this module can actually test.

    A goal that cannot be tested can never be completed, so an unrecognised
    condition is dropped rather than stored and silently failed forever.

    `owner` is whose want this is, and is given only when the goal is somebody
    acting on their own account rather than an errand somebody else set them.
    It turns a delivery to oneself into what it actually means. A quest passes
    no owner on purpose: there, a delivery to the person who asked is the
    ordinary case and the whole point of the errand.
    """
    clean = []
    for raw in conditions or []:
        try:
            ctype = str(raw.get("type", "")).strip().lower()
        except AttributeError:
            continue
        if ctype not in CONDITION_TYPES:
            continue
        entry = {"type": ctype}
        for field in ("object", "kind", "room", "to", "trait", "host",
                      "preposition"):
            if raw.get(field):
                entry[field] = str(raw[field]).strip()
        for field in ("is", "lacks"):
            if raw.get(field):
                entry[field] = [str(s).lower().strip() for s in raw[field] if s]
        for field in ("min", "max"):
            if raw.get(field) is not None:
                try:
                    entry[field] = float(raw[field])
                except (TypeError, ValueError):
                    pass
        if ctype == "trait" and not entry.get("trait"):
            continue     # a trait goal that names no trait can never be tested
        # "Have the letter brought to me" is a want to be carrying the letter,
        # so it is written down as one. Nothing could carry out the other
        # reading: `give` refuses a self recipient in the NPC's own tool and
        # again in the command set, both silently, so the step would be a
        # turn spent on a line nobody sees. And the test was already the same
        # test -- `delivered` asks whether the thing is inside the recipient,
        # which for oneself is exactly `holds` -- so the goal was either
        # finished before it was set or finished by picking the thing up,
        # while the character was described the whole time as trying to hand
        # something to itself.
        if ctype == "delivered" and _names_owner(entry.get("to"), owner):
            entry.pop("to", None)
            entry["type"] = "holds"
        clean.append(entry)
    return clean


def _test(condition, actor, world_root):
    """
    Evaluate one condition. Returns (met, how it reads as a want).

    Kept as the shape the planner still asks by. Everything under it is
    `world.conditions` now: one goal condition may be more than one there --
    a `state` carrying both `is` and `lacks` is two -- so all of them have to
    hold and all of them are said.
    """
    from world import conditions as C

    parts = C.from_goal(condition)
    if not parts:
        # A condition this game cannot check can never be completed, which is
        # why `sanitise` drops them on the way in. One that got past it is
        # reported unmet rather than silently true.
        return False, "do something the game cannot check"
    ctx = C.context(None, actor, world_root)
    met = all(C.evaluate(part, ctx) for part in parts)
    said = " and ".join(
        part for part in (C.describe(p, ctx, C.WANT) for p in parts) if part)
    return met, said


def progress(conditions, actor, world_root):
    """[(description, met), ...] for every condition, in order."""
    return [_test(c, actor, world_root) for c in conditions or []]


def satisfied(conditions, actor, world_root):
    """True when every condition holds. An empty goal is never satisfied."""
    if not conditions:
        return False
    return all(met for met, _ in progress(conditions, actor, world_root))


def describe(conditions, actor=None, world_root=None):
    """
    A goal as a readable phrase, for prompts and quest listings.

    With nobody to test it against -- which is how every NPC prompt calls it,
    `goals.describe(npc.db.goal)` -- it is said abstractly rather than
    evaluated. That used to reach `actor.location` on `None` and raise for any
    goal about being somewhere; it now reads "you are in the Library" and
    costs nothing.
    """
    from world import conditions as C

    if not conditions:
        return "nothing in particular"
    if actor is None:
        said = [C.describe(part) for part in C.from_goals(conditions)]
        return ", then ".join(p for p in said if p) or "nothing in particular"
    return ", then ".join(text for _met, text in
                          progress(conditions, actor, world_root))
