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
CONDITION_TYPES = ("state", "holds", "in_room", "exists", "gone", "delivered")


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
        for field in ("object", "room", "to"):
            if raw.get(field):
                entry[field] = str(raw[field]).strip()
        for field in ("is", "lacks"):
            if raw.get(field):
                entry[field] = [str(s).lower().strip() for s in raw[field] if s]
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
        met = find_object(world_root, actor, name) is None
        return met, f"get rid of {name}"

    obj = find_object(world_root, actor, name)

    if ctype == "exists":
        return obj is not None, f"bring {name} into being"

    if ctype == "holds":
        met = obj is not None and obj.location is actor
        return met, f"be carrying {name}"

    if ctype == "delivered":
        recipient_name = condition.get("to", "")
        recipient = find_object(world_root, actor, recipient_name)
        met = (obj is not None and recipient is not None
               and obj.location is recipient)
        return met, f"give {name} to {recipient_name}"

    if ctype == "state":
        wanted = condition.get("is") or []
        unwanted = condition.get("lacks") or []
        if obj is None:
            return False, f"find {name}"
        current = verbs.states(obj)
        met = (all(s in current for s in wanted)
               and not any(s in current for s in unwanted))
        parts = []
        if wanted:
            parts.append(" and ".join(wanted))
        if unwanted:
            parts.append("not " + " or ".join(unwanted))
        return met, f"make {name} {', '.join(parts)}"

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
