"""
Turning what a character wants into conditions the game can test.

Used for two things that are the same job: a quest an NPC asks a player to
do, and a goal an NPC sets for itself.

An NPC asks for something in its own words -- "fetch me the chalk from the
storeroom and I'll give you a token". Making that testable means naming real
objects and writing typed conditions, which is the hardest structured output
in the game and was previously demanded of the dialogue model in the middle
of a tool call that was also supposed to produce speech in character. No
quest was ever successfully offered.

So it happens here instead, in its own call, on its own model. It is rare --
once per quest, not once per reaction -- so it can afford a capable model
where dialogue cannot.
"""

from world import llm

from evennia.utils import logger


_SYSTEM = """You turn a character's request into a quest a game can check.

Answer by calling write_quest. The title is three or four words naming the
errand.

goal is what must become true for the errand to be done. Each entry is one of:
{"type": "holds",     "object": "brass key"}   (or "kind": "key" for any)                  they are carrying it
{"type": "worn",      "object": "grey habit"}                 they have it on
{"type": "trait",     "trait": "standing", "min": 10}         a figure about them
{"type": "placed",    "object": "ledger", "preposition": "in", "host": "safe"}
{"type": "delivered", "object": "letter", "to": "Clerk"}      they gave it to someone
{"type": "state",     "object": "lamp", "is": ["lit"], "lacks": ["broken"]}
{"type": "gone",      "object": "rats"}                        it no longer exists
{"type": "exists",    "object": "stew"}                        it has been made
{"type": "in_room",   "room": "Kitchen"}                       they went there

Name objects as they are actually called in the list you are given. Do not
invent a condition type, and do not ask for something the world has no way to
show: a goal that cannot be tested can never be completed, and the errand
would hang forever.

reward is what they get, and punishment what it costs them to fail. Both are
lists of effects, usually:
{"type": "create_object", "name": "...", "description": "...", "takeable": true, "location": "actor"}
{"type": "destroy_object", "name": "the thing they lose"}
{"type": "set_state", "name": "...", "add": ["blessed"]}
{"type": "set_trait", "role": "actor", "trait": "standing", "change": 2}

A "trait" condition and a set_trait effect may only name a trait the world
already keeps; list_traits shows them. Do not invent one here.

"placed" is for putting a thing somewhere rather than merely carrying it --
"in" a container, "on" a surface, "under" or "behind" anything. Use it when
the errand is about where something ends up; use "delivered" when it ends up
with a person.

Give an empty punishment list unless the character clearly threatened one.
Keep the goal to one or two conditions."""


#: How many room names a goal may be shown. A goal about somewhere else is the
#: commonest thing anybody wants -- "get to the library" -- and it cannot be
#: written unless the library is known to exist. Capped because a large world
#: has hundreds of rooms and the list is not worth a prompt of its own.
MAX_ROOMS_LISTED = 60


def _known_rooms(character):
    """
    Every room of this world that has actually been built, by name.

    Only built rooms: a goal naming somewhere nobody has ever been is one the
    planner can find no route to, and the character would work at it until
    they gave up.
    """
    room = getattr(character, "location", None)
    world_root = room.db.world_root if room else None
    if world_root is None:
        return []

    from evennia import search_tag

    names = set()
    for built in search_tag(str(world_root.id), category="ai_world"):
        title = built.db.room_title or built.key
        if title:
            names.add(title)
    return sorted(names)[:MAX_ROOMS_LISTED]


def _surroundings(npc, target):
    """
    What the quest may refer to: the things that actually exist nearby.

    Without this the model invents object names, and a goal naming something
    that is not there can never be satisfied.
    """
    from evennia.objects.objects import DefaultCharacter

    room = npc.location
    here, carried, people, exits = [], [], [], []
    for obj in (room.contents if room else []):
        if getattr(obj, "destination", None) is not None:
            exits.append(obj.key)
        elif obj.db.is_npc or isinstance(obj, DefaultCharacter):
            people.append(obj.get_display_name(npc))
        else:
            here.append(obj.key)
    # Worn and carried are marked apart: "be wearing the grey habit" and "be
    # carrying it" are different errands, and a coat somebody has on is not
    # loose in the room for anyone else to fetch.
    for obj in target.contents:
        carried.append(f"{obj.key} (worn)" if obj.db.worn else obj.key)
    for obj in npc.contents:
        state = "worn by" if obj.db.worn else "carried by"
        here.append(f"{obj.key} ({state} {npc.key})")

    room_title = (room.db.room_title or room.key) if room else "nowhere"
    elsewhere = [name for name in _known_rooms(npc) if name != room_title]
    return (
        f"Room: {room_title}\n"
        + (f"Other rooms in this world: {', '.join(elsewhere)}\n"
           if elsewhere else "")
        + f"Objects here: {', '.join(here) or 'nothing loose'}\n"
        + f"{target.get_display_name(npc)} has on them: {', '.join(carried) or 'nothing'}\n"
        + f"People here: {', '.join(people) or 'nobody'}\n"
        + f"Ways out: {', '.join(exits) or 'none'}"
    )


def formalise(sponsor, npc, target, request, offer, consequence, on_success, on_error):
    """
    Async. Turn a spoken request into a testable quest.

    Calls on_success({"title", "goal", "reward", "punishment"}) or
    on_error(msg) in the main thread.
    """
    model = sponsor.model_for("quests", "commands")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    room = npc.location
    from world import lore

    world = lore.description(room, target)

    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {world}\n\n"
                f"{lore.guidance_block(room, 'dialogue', target)}"
                f"{npc.key} is asking {target.get_display_name(npc)} for something.\n\n"
                f"What {npc.key} wants: {request}\n"
                f"What {npc.key} offers: {offer or 'nothing in particular'}\n"
                f"What {npc.key} threatens if it is not done: "
                f"{consequence or 'nothing'}\n\n"
                f"{_surroundings(npc, target)}\n\n"
                f"Write this as a checkable quest."
            ),
        },
    ]

    def _done(data):
        data = data if isinstance(data, dict) else {}
        on_success({
            "title": str(data.get("title") or "").strip() or "An errand",
            "goal": _listed(data.get("goal")),
            "reward": _listed(data.get("reward")),
            "punishment": _listed(data.get("punishment")),
        })

    from world import lookups
    from world import toolbox as tb

    # Rounds out, the last quest is offered as it stands: `quests.offer` still
    # refuses one with no testable goal, and logs it, as it always did.
    box = tb.Toolbox([quest_tool()] + lookups.named(*QUEST_LOOKUPS),
                     tb.ToolContext(world_root=room.db.world_root if room
                                    else None, room=room, actor=npc,
                                    sponsor=sponsor, job="quests"))
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=on_error,
                 on_exhausted=lambda last: _done(last) if last
                 else on_error("no quest came back"),
                 rounds=QUEST_ROUNDS)


_GOAL_SYSTEM = """You turn what a character wants into conditions a game can check.

Answer by calling write_goal.

Each entry is one of:
{"type": "holds",     "object": "brass key"}   (or "kind": "key" for any)                   they are carrying it
{"type": "worn",      "object": "grey habit"}                  they have it on
{"type": "trait",     "trait": "standing", "min": 10}          a figure about them
{"type": "placed",    "object": "ledger", "preposition": "in", "host": "safe"}
{"type": "delivered", "object": "letter", "to": "Clerk"}       they gave it to someone
{"type": "state",     "object": "lamp", "is": ["lit"]}         its condition
{"type": "gone",      "object": "rats"}                        it no longer exists
{"type": "in_room",   "room": "Kitchen"}                       they went there

Name objects and rooms as they are actually called in the list you are given,
and traits only from those this world measures (list_traits). Give one or two conditions.

"delivered" is about handing something to somebody else, and the "to" must be
another person. A character who simply wants to have the thing wants "holds".

"Get to the library", "go to the kitchen" and the like are in_room conditions,
and are perfectly good goals even when the place is nowhere near: the game
works out the way there. Use the room's name from the list exactly. Everything
else should be near at hand -- this is what they will do next, not their
life's ambition. Return an empty list if what they want cannot be expressed
this way."""


def formalise_goal(sponsor, npc, want, on_success, on_error):
    """
    Async. Turn a character's stated want into testable conditions.

    Calls on_success([condition, ...]) or on_error(msg) in the main thread.
    """
    model = sponsor.model_for("quests", "commands")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    room = npc.location
    from world import lore

    world = lore.description(room)
    messages = [
        {"role": "system", "content": _GOAL_SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {world}\n\n"
                f"{lore.guidance_block(room, 'dialogue')}"
                f"{npc.key} wants: {want}\n\n"
                f"{_surroundings(npc, npc)}\n\n"
                f"Write this as checkable conditions."
            ),
        },
    ]

    def _done(data):
        on_success(_listed((data if isinstance(data, dict) else {}).get("goal")))

    from world import lookups
    from world import toolbox as tb

    # An empty goal is a real answer -- what they want cannot be put this way
    # -- and rounds out takes the last one as it stands, as before.
    box = tb.Toolbox([goal_tool(npc)] + lookups.named(*QUEST_LOOKUPS),
                     tb.ToolContext(world_root=room.db.world_root if room
                                    else None, room=room, actor=npc,
                                    sponsor=sponsor, job="quests"))
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=on_error, on_exhausted=_done, rounds=GOAL_ROUNDS)


# ---------------------------------------------------------------------------
# The finish tools (docs/generator-tool-loops.md §4.2)
# ---------------------------------------------------------------------------

#: Rounds each may take (§10.3).
QUEST_ROUNDS = 8
GOAL_ROUNDS = 6

#: What either may look up: the trait register the prompts used to paste in,
#: the rooms a goal may name, and the states a condition may ask for.
QUEST_LOOKUPS = ("list_traits", "show_trait", "find_rooms", "list_states",
                 "examine")


def _listed(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def goal_complaints(conditions, world_root, owner=None, need_goal=False):
    """
    What is wrong with a goal that asking again can put right.

    What `goals.sanitise` would drop -- which used to happen after the answer
    was taken, silently, leaving a quest nobody could finish -- and a trait
    condition naming a trait nothing measures.
    """
    from world import goals, traits

    said = []
    given = _listed(conditions)
    kept = goals.sanitise(given, owner=owner)
    if len(kept) < len(given):
        said.append(f"{len(given) - len(kept)} of the goal's conditions cannot "
                    f"be tested: each needs one of the types "
                    f"{', '.join(goals.CONDITION_TYPES)}, and a trait "
                    f"condition needs its trait")
    elif need_goal and not kept:
        said.append("a quest needs at least one condition that can be tested")
    strange = sorted({traits._slug(condition.get("trait")) for condition in kept
                      if condition.get("type") == "trait"}
                     - set(traits.vocabulary(world_root)) - {""})
    if strange:
        said.append("the goal names " + ", ".join(strange) + ", which this "
                    "world does not measure; list_traits shows what it does")
    return said


def effect_complaints(given, world_root, label):
    """An effect nothing can apply, or a trait nothing measures."""
    from world import effects, traits

    said = []
    known = traits.vocabulary(world_root)
    for effect in _listed(given):
        if not isinstance(effect, dict):
            said.append(f"a {label} effect that is not an object")
            continue
        kind = str(effect.get("type") or "")
        if kind not in effects.VOCABULARY:
            said.append(f"there is no such effect as {kind!r} in the {label}")
            continue
        if (kind == "set_trait"
                and traits._slug(effect.get("trait")) not in known):
            said.append(f"the {label} names the trait "
                        f"{effect.get('trait')!r}, which this world does not "
                        f"measure")
    return said


def quest_tool():
    """`write_quest`, the finish tool `formalise` answers with."""
    from world import toolbox as tb

    def parameters(ctx):
        from world import effects, goals

        return tb.params({
            "title": {"type": "string",
                      "description": "Three or four words naming the errand"},
            "goal": {"type": "array", "items": goals.schema(ctx),
                     "minItems": 1, "maxItems": 2,
                     "description": "What must become true for it to be done: "
                                    "one or two conditions"},
            "reward": {"type": "array", "items": effects.schema(ctx),
                       "description": "What they get for doing it"},
            "punishment": {"type": "array", "items": effects.schema(ctx),
                           "description": "What failing costs them; empty "
                                          "unless it was threatened"},
        }, ["title", "goal"])

    def handler(ctx, args, answer):
        said = (goal_complaints(args.get("goal"), ctx.world_root,
                                need_goal=True)
                + effect_complaints(args.get("reward"), ctx.world_root,
                                    "reward")
                + effect_complaints(args.get("punishment"), ctx.world_root,
                                    "punishment"))
        if said:
            answer(tb.complain("Not written: " + "; ".join(said) + ". Send "
                               "the quest again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("write_quest", "Write the request as a checkable quest.",
                   parameters, handler, finishes=True)


def goal_tool(owner):
    """`write_goal`, the finish tool `formalise_goal` answers with."""
    from world import toolbox as tb

    def parameters(ctx):
        from world import goals

        return tb.params({
            "goal": {"type": "array", "items": goals.schema(ctx),
                     "maxItems": 2,
                     "description": "One or two conditions; empty if what "
                                    "they want cannot be put this way"},
        }, ["goal"])

    def handler(ctx, args, answer):
        said = goal_complaints(args.get("goal"), ctx.world_root, owner=owner)
        if said:
            answer(tb.complain("Not written: " + "; ".join(said) + ". Send "
                               "the goal again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("write_goal", "Write what they want as checkable "
                                 "conditions.",
                   parameters, handler, finishes=True)
