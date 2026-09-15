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
                from world.model_json import listed

                entry[field] = [str(s).lower().strip()
                                for s in listed(raw[field]) if s]
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


def recover(obj):
    """
    "Get back what is mine", as a goal.

    Having it in hand again, which is all getting a thing back can be tested
    as: whether it is returned, bargained for or snatched is the character's
    business, and the planner already knows how to go and pick up something
    it wants. Named by key, as every goal names what it is about. See
    `world.ownership.want_back`.
    """
    return [{"type": "holds", "object": str(getattr(obj, "key", "") or "")}]


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


# ---------------------------------------------------------------------------
# What people want and cannot get
# ---------------------------------------------------------------------------

def blocked_wants(world_root):
    """
    Every want in this world the planner can make no step towards, and why.

    Read off the characters in it. A character's goal already holds a quest it
    accepted. A player's is kept in two places, because `quests._adopt_goal`
    copies a quest into `db.goal` for characters only: their own goal, and
    their active quest. Players who have logged out are in no room and are not
    counted, which is enough -- rooms and things are made while somebody plays.

    Each entry is a dict:

      who        the character who wants it
      whose      "quest" or "goal"
      player     whether a person is playing them
      condition  the want itself
      reason     `planner.blocker`'s reason
      what       what it names
      words      the exact words it accepts, for a generator to name a thing by
      avoid      room ids no hint should go to: the quest giver's, and the room
                 of a character whose own want it is -- finding it should mean
                 going somewhere

    Player quests first, then players' own goals, then characters' wants.
    Free: no model, only the tests goals already make and the planner's search.
    """
    if world_root is None:
        return []

    from evennia import search_tag
    from evennia.objects.models import ObjectDB

    from world import planner, quests

    rooms = list(search_tag(str(world_root.id), category="ai_world"))
    if world_root not in rooms:
        rooms.append(world_root)

    found, seen = [], set()
    for room in rooms:
        for who in room.contents:
            if who.id in seen:
                continue
            npc = bool(who.db.is_npc)
            player = not npc and getattr(who, "account", None) is not None
            if not (npc or player):
                continue
            seen.add(who.id)

            wants = []
            if player:
                quest = quests.current(who)
                if quest is not None:
                    wants.append(("quest", quest.get("goal"), quest))
                if who.db.goal:
                    wants.append(("goal", who.db.goal, None))
            elif who.db.goal:
                taken = (quests._find(who, who.db.goal_from_quest)
                         if who.db.goal_from_quest is not None else None)
                wants.append(("quest" if taken else "goal", who.db.goal, taken))

            for whose, goal, quest in wants:
                goal = list(goal or [])
                for condition, (met, _text) in zip(goal, progress(goal, who,
                                                                  world_root)):
                    if met:
                        continue
                    reason, what = planner.blocker(who, world_root, condition)
                    if not reason:
                        continue
                    avoid = set()
                    if npc and who.location is not None:
                        avoid.add(who.location.id)
                    giver_id = (quest or {}).get("giver_id")
                    if giver_id:
                        giver = ObjectDB.objects.filter(id=giver_id).first()
                        if giver is not None and giver.location is not None:
                            avoid.add(giver.location.id)
                    found.append({
                        "who": who, "whose": whose, "player": player,
                        "condition": dict(condition), "reason": reason,
                        "what": what, "avoid": avoid,
                        "words": accepted_words(condition, reason, what),
                    })

    rank = {(True, "quest"): 0, (True, "goal"): 1}
    found.sort(key=lambda entry: rank.get((entry["player"], entry["whose"]), 2))
    return found


def accepted_words(condition, reason, what):
    """
    How a thing has to be named for a want to count it, or "" when no thing
    would help.

    An `object` condition finds a thing whose name contains its words
    (`find_object` tries the exact key, then a substring), so "unrefined ore
    chunk" does not satisfy a quest for raw ore however right it looks. A
    `kind` condition is satisfied by anything of that kind.
    """
    from world import planner

    if reason == planner.MISSING_ROOM:
        return f"a room whose name contains '{what}'"
    if reason != planner.MISSING_THING:
        return ""
    kind = str(condition.get("kind") or "").strip()
    if kind and not condition.get("object"):
        return f"of kind '{what}'"
    return f"named so that the name contains '{what}'"


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`find_rooms`: the rooms built in this world, by name."""
    from world import toolbox as tb

    def finding(ctx, args):
        from evennia import search_tag

        root = ctx.world_root
        rooms = list(search_tag(str(root.id), category="ai_world"))
        if root not in rooms:
            rooms.append(root)
        names = sorted({(room.db.room_title or room.key) for room in rooms
                        if (room.db.room_title or room.key)})
        return tb.paged(names, args, "rooms")

    return [tb.Tool(
        "find_rooms",
        "The rooms built in this world, by name. A goal or an effect that "
        "names a room has to name one of these.",
        tb.params(tb.PAGE), tb.answering(finding),
        doing="looking up this world's rooms", looks=True,
        available=lambda ctx: ctx.world_root is not None)]


# ---------------------------------------------------------------------------
# The shape of a goal condition, for a tool's parameters (docs §4.1)
# ---------------------------------------------------------------------------

def schema(ctx=None):
    """One goal condition, closed to the types `sanitise` keeps."""
    from world import relations
    from world import toolbox as tb

    world_root = getattr(ctx, "world_root", None)
    known_traits = []
    if world_root is not None:
        from world import traits

        known_traits = sorted(traits.vocabulary(world_root))
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(CONDITION_TYPES),
                     "description": "What must become true"},
            "object": {"type": "string",
                       "description": "The thing, as it is called; a thing "
                                      "whose name contains these words "
                                      "counts"},
            "kind": {"type": "string",
                     "description": "Instead of object: any thing of this "
                                    "sort counts"},
            "room": {"type": "string",
                     "description": "in_room: a room's name, as find_rooms "
                                    "lists them"},
            "to": {"type": "string",
                   "description": "delivered: who it is handed to"},
            "host": {"type": "string",
                     "description": "placed: what it is put in or on"},
            "preposition": {"type": "string",
                            "enum": list(relations.PREPOSITIONS),
                            "description": "placed: how it goes there"},
            "trait": tb.choice(known_traits, "trait: the figure",
                               ask="list_traits"),
            "min": {"type": "number", "description": "trait: at least"},
            "max": {"type": "number", "description": "trait: at most"},
            "is": {"type": "array", "items": {"type": "string"},
                   "description": "state: conditions it must be in"},
            "lacks": {"type": "array", "items": {"type": "string"},
                      "description": "state: conditions it must not be in"},
        },
        "required": ["type"],
    }
