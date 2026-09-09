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


def _subject(condition, world_root, actor, actor_only=False):
    """
    What a condition is about: a named thing, or anything of a kind.

    A condition may say `object` and mean that one, or say `kind` and mean any
    of them. Returns (object, how to say it) so the label a player is shown
    reads the way the want was made -- "be carrying the brass key" for one,
    "be carrying a cake" for the other.
    """
    name = str(condition.get("object", "") or "").strip()
    if name:
        return find_object(world_root, actor, name), f"the {name}"

    kind = str(condition.get("kind", "") or "").strip()
    if kind:
        article = "an" if kind[:1].lower() in "aeiou" else "a"
        return (find_of_kind(world_root, actor, kind, actor_only),
                f"{article} {kind}")
    return None, "it"


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


def sanitise(conditions):
    """
    Keep only conditions this module can actually test.

    A goal that cannot be tested can never be completed, so an unrecognised
    condition is dropped rather than stored and silently failed forever.
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
        clean.append(entry)
    return clean


def _test(condition, actor, world_root):
    """Evaluate one condition. Returns (met, human readable description)."""
    from world import verbs

    ctype = condition.get("type")
    name = condition.get("object", "")

    if ctype == "in_room":
        room_name = condition.get("room", "")
        here = actor.location
        title = (here.db.room_title or here.key) if here else ""
        met = bool(room_name) and room_name.lower() in title.lower()
        return met, f"be in {room_name}"

    if ctype == "gone":
        # True when nothing answers to it -- which for a kind means none of
        # them are left anywhere, so "clear out the rats" ends when the last
        # rat does rather than when one named rat does.
        found, said = _subject(condition, world_root, actor)
        return found is None, f"get rid of {said}"

    if ctype == "trait":
        # A want about the character rather than about the world. The same
        # shape a verb rule requires, so anything a rule can demand of someone
        # is something they can set out to become.
        from world import traits

        slug = condition.get("trait", "")
        low, high = condition.get("min"), condition.get("max")
        current = traits.value(actor, slug)
        met = current is not None
        if met and low is not None:
            met = current >= low
        if met and high is not None:
            met = current <= high
        label = slug.replace("_", " ")
        if low is not None:
            return met, f"get {label} to {traits._round(low)}"
        if high is not None:
            return met, f"get {label} down to {traits._round(high)}"
        return met, f"have some {label}"

    # A condition may name one thing or describe a sort of thing. "Holds" is
    # the one that has to look in the actor's own hands rather than across the
    # world, or wanting a cake would be satisfied by a cake on a far shelf.
    obj, said = _subject(condition, world_root, actor,
                         actor_only=(ctype == "holds"))

    if ctype == "exists":
        return obj is not None, f"bring {said} into being"

    if ctype == "holds":
        met = obj is not None and obj.location is actor
        return met, f"be carrying {said}"

    if ctype == "placed":
        # Where a thing has been put, which is a different question from who
        # is carrying it: a ledger in the safe is not a ledger in a pocket.
        from world import relations

        host_name = condition.get("host", "")
        preposition = condition.get("preposition") or relations.DEFAULT
        host = find_object(world_root, actor, host_name)
        met = relations.test(obj, preposition, host)
        return met, f"get {said} {preposition} {host_name}"

    if ctype == "worn":
        # Carrying a coat and having it on are different things, and a
        # character who wants to look like somebody has to do the second.
        met = obj is not None and obj.location is actor and bool(obj.db.worn)
        return met, f"be wearing {said}"

    if ctype == "delivered":
        recipient_name = condition.get("to", "")
        recipient = find_object(world_root, actor, recipient_name)
        met = (obj is not None and recipient is not None
               and obj.location is recipient)
        return met, f"give {said} to {recipient_name}"

    if ctype == "state":
        wanted = condition.get("is") or []
        unwanted = condition.get("lacks") or []
        if obj is None:
            return False, f"find {said}"
        current = verbs.states(obj)
        met = (all(s in current for s in wanted)
               and not any(s in current for s in unwanted))
        parts = []
        if wanted:
            parts.append(" and ".join(wanted))
        if unwanted:
            parts.append("not " + " or ".join(unwanted))
        return met, f"make {said} {', '.join(parts)}"

    return False, "do something impossible"


def progress(conditions, actor, world_root):
    """[(description, met), ...] for every condition, in order."""
    return [_test(c, actor, world_root) for c in conditions or []]


def satisfied(conditions, actor, world_root):
    """True when every condition holds. An empty goal is never satisfied."""
    if not conditions:
        return False
    return all(met for met, _ in progress(conditions, actor, world_root))


def describe(conditions, actor=None, world_root=None):
    """A goal as a readable phrase, for prompts and quest listings."""
    if not conditions:
        return "nothing in particular"
    return ", then ".join(text for _met, text in progress(conditions, actor, world_root))
