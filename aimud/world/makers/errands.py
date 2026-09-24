"""
Errands, written in advance: a goal, a reward, and somebody who will ask.

A quest used to exist only from the moment it was offered, which is why a world
with no model had none at all: `quest_gen` wrote them in the middle of a
conversation and there was no such thing as one waiting. `world/quests.py` now
keeps specifications; this is how a person writes one.

Two things are worth knowing.

**A goal is written in the goal vocabulary, not the condition vocabulary.**
`goals.CONDITION_TYPES` is the closed list of things `goals.satisfied` can
actually test, and a goal it cannot test can never be completed -- so the
errand would hang for ever rather than fail. The form offers exactly that list
and nothing else, which is the same reason `quest_gen`'s prompt spells it out.

**Offering is a rule.** The form writes the errand, and then offers to write
the rule that hands it over -- `instead`, on that character, when somebody
greets them. Declining leaves the errand written and unoffered, for a world
that wants to wire it some other way. See docs/player-building.md 10.
"""

from commands.subjects import reachable
from world import goals, making, menus
from world import quests as quests_mod

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _root(ctx):
    return making.root_of(ctx)


def _caller(ctx):
    return making.caller_of(ctx)


# ---------------------------------------------------------------------------
# One thing that must become true
# ---------------------------------------------------------------------------

#: The goal vocabulary, said in the second person, in the order somebody
#: asking for something would think of them. Every entry is one of
#: `goals.CONDITION_TYPES`, which a test holds to: a goal type nobody can
#: reach from a menu is one a hand-built errand cannot ask for.
GOAL_TYPES = (
    ("holds", "they are carrying something", ("object", "kind")),
    ("not_holds", "they are not carrying something", ("object", "kind")),
    ("delivered", "they have given something to somebody", ("object", "to")),
    ("worn", "they have something on", ("object", "kind")),
    ("not_worn", "they do not have something on", ("object", "kind")),
    ("state", "something is in a condition", ("object", "is", "lacks")),
    ("trait", "a figure about them stands somewhere", ("trait", "min", "max")),
    ("placed", "something is in or on something else",
     ("object", "preposition", "host")),
    ("not_placed", "something is not in or on something else",
     ("object", "preposition", "host")),
    ("in_room", "they have gone somewhere", ("room",)),
    ("not_in_room", "they are somewhere else", ("room",)),
    ("exists", "something has been made", ("object",)),
    ("gone", "something is no longer in the world", ("object",)),
)


def goal_options(ctx):
    return [(value, said) for value, said, _fields in GOAL_TYPES]


def _goal_takes(ctx):
    wanted = str(ctx.draft.get("type") or "")
    for value, _said, fields in GOAL_TYPES:
        if value == wanted:
            return fields
    return ()


def _goal_asks(field):
    return lambda ctx: field in _goal_takes(ctx)


def state_options(ctx):
    from world import verbs

    return [(slug, f"{slug} -- {entry.get('means') or ''}".rstrip(" -"))
            for slug, entry in sorted((verbs.vocabulary(_root(ctx))
                                       or {}).items())]


def kind_options(ctx):
    from world.makers import vocabulary

    return vocabulary.kind_entries(_root(ctx))


def trait_options(ctx):
    from world.makers import vocabulary

    return [(value, label) for value, label, _help
            in vocabulary.attribute_entries(_root(ctx))]


def keep_goal(ctx):
    wanted = str(ctx.draft.get("type") or "")
    if not wanted:
        raise menus.Refuse("Say what has to become true.")
    entry = {"type": wanted}
    for field in _goal_takes(ctx):
        value = ctx.draft.get(field)
        if value in (None, "", []):
            continue
        entry[field] = value
    clean = goals.sanitise([entry])
    if not clean:
        raise menus.Refuse(
            "Nothing in that can be tested, so the errand could never be "
            "finished. Name the thing as it is actually called here.")
    return clean[0], f"Added: {goals.describe(clean)}"


NEW_GOAL = menus.Form(
    key="new-goal", title="Something that must become true", guided=True,
    intro="What finishes the errand. It has to be something the game can "
          "test, or it could never be completed.",
    items=[
        menus.Picker("type", "What must become true", options=goal_options,
                     required=True),
        menus.Field("object", "Which thing", lock=_goal_asks("object"),
                    help="Named as it is actually called here. A sort of "
                         "thing below will do instead, for `any key`."),
        making.picker("kind", "Or any of a sort", "kind", options=kind_options,
                      lock=_goal_asks("kind"),
                      help="Use this where any one of a sort will do."),
        menus.Field("to", "Given to", lock=_goal_asks("to"),
                    help="Whoever it has to reach. The character who asked is "
                         "the usual answer, and the commonest shape an errand "
                         "has."),
        making.picker("is", "In the condition", "condition",
                      options=state_options, lock=_goal_asks("is"),
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none"),
        making.picker("lacks", "And not in", "condition",
                      options=state_options, lock=_goal_asks("lacks"),
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none"),
        making.picker("trait", "Which attribute", "attribute",
                      options=trait_options, lock=_goal_asks("trait")),
        menus.Field("min", "At least", kind=menus.NUMBER,
                    lock=_goal_asks("min")),
        menus.Field("max", "At most", kind=menus.NUMBER,
                    lock=_goal_asks("max")),
        menus.Field("preposition", "Where", kind=menus.CHOICE,
                    lock=_goal_asks("preposition"),
                    choices=lambda ctx: [
                        menus.Choice(v, l) for v, l in
                        (("in", "in it"), ("on", "on it"),
                         ("under", "under it"), ("behind", "behind it"))]),
        menus.Field("host", "In or on what", lock=_goal_asks("host")),
        menus.Field("room", "Which room", lock=_goal_asks("room"),
                    help="Named as it is called at the top of the room."),
        making.keeper("keep", "Keep it", keep_goal),
    ],
)


def goal_line(ctx, entry):
    return goals.describe([entry])


def _read_words(text):
    found = [word.strip().lower() for word in str(text or "").split()]
    return [word for word in found if word], ""


# ---------------------------------------------------------------------------
# What it is worth, and what it costs to fail
# ---------------------------------------------------------------------------

def reward_options(ctx):
    """
    Only what a quest may hand out.

    Deliberately narrower than what a verb can do: an errand is a transaction
    between two characters, not a licence to rewrite the room it was agreed
    in. `quests.QUEST_EFFECTS` is the list and this reads it rather than
    repeating it.
    """
    from world import effects as fx

    found = []
    for etype in sorted(quests_mod.QUEST_EFFECTS):
        known = fx.known(etype)
        found.append((etype, f"{etype} -- {known.get('means', '')}"))
    return found


def _reward_form(ctx):
    """The effect form, with its list of effects narrowed to a quest's."""
    from world.makers import rules as rule_forms

    return rule_forms.narrowed_effects(reward_options)


def effect_line(ctx, effect):
    from world import effects as fx

    return fx.say(effect)


# ---------------------------------------------------------------------------
# Who gives it, and in whose words
# ---------------------------------------------------------------------------

def npc_options(ctx):
    return [(str(obj.id), obj.key)
            for obj in reachable(_caller(ctx), people=True)
            if getattr(obj.db, "is_npc", False)]


NEW_GIVER = menus.Form(
    key="new-giver", title="Somebody who hands it out", guided=True,
    intro="Who asks, and how they ask. An errand several characters give is "
          "one errand; what each of them says about it is their own.",
    items=[
        menus.Picker("npc", "Who asks", options=npc_options, required=True,
                     help="Somebody here. An errand with nobody to give it "
                          "stays written and is offered by nothing."),
        menus.Field("description", "In their own words", kind=menus.LONG_TEXT,
                    suggestible=True,
                    help="How this character asks for it. Left empty, the "
                         "errand's own description is used -- which is right "
                         "for a standing bounty and wrong for two people who "
                         "would each ask differently."),
        making.keeper("keep", "Keep them", lambda ctx: (
            {"npc": str(ctx.draft.get("npc") or ""),
             "description": str(ctx.draft.get("description") or "")},
            "Added.")),
    ],
)


def giver_line(ctx, entry):
    from evennia.objects.models import ObjectDB

    try:
        npc = ObjectDB.objects.get(id=int(entry.get("npc")))
        name = npc.key
    except Exception:
        name = "somebody who is gone"
    own = str(entry.get("description") or "")
    return f"{name}" + (" -- in their own words" if own else "")


# ---------------------------------------------------------------------------
# The errand
# ---------------------------------------------------------------------------

def after_options(ctx):
    root = _root(ctx)
    return [(record["id"], f"{record['id']} -- {record.get('title')}")
            for record in sorted(quests_mod.specs(root).values(),
                                 key=lambda r: r.get("id", ""))]


def keep_quest(ctx):
    root = _root(ctx)
    if root is None:
        raise menus.Refuse("You are not in a world.")
    title = str(ctx.draft.get("title") or "").strip()
    if not title:
        raise menus.Refuse("An errand needs a name.")
    goal = list(ctx.draft.get("goal") or [])
    if not goal:
        raise menus.Refuse(
            "An errand with nothing to finish it would hang for ever. Say "
            "what has to become true.")
    record = quests_mod.save_spec(root, {
        "id": str(ctx.draft.get("_id") or ""),
        "title": title,
        "description": str(ctx.draft.get("description") or ""),
        "goal": goal,
        "reward": list(ctx.draft.get("reward") or []),
        "punishment": list(ctx.draft.get("punishment") or []),
        "time_limit": ctx.draft.get("time_limit"),
        "givers": list(ctx.draft.get("givers") or []),
        "repeatable": bool(ctx.draft.get("repeatable")),
        "cooldown": int(ctx.draft.get("cooldown") or 0),
        "after": list(ctx.draft.get("after") or []),
        "only_when": list(ctx.draft.get("only_when") or []),
    })
    if record is None:
        raise menus.Refuse("That errand could not be written.")
    said = [f"|w{record['id']}|n is written: {record['title']}."]
    if not record["givers"]:
        said.append("|xNobody hands it out yet, so nothing offers it. "
                    f"|wedit quest {record['id']}|n adds somebody.|n")
    elif ctx.draft.get("wire", True):
        said.append(_wire_rules(root, record))
    else:
        said.append("|xNo rule offers it. Write one whose effect is "
                    "|woffer_quest|n when you know how you want it asked "
                    "for.|n")
    return record["id"], "\n".join(said)


def _wire_rules(root, record):
    """
    The rule that hands it over: greeting the giver offers it.

    Written rather than hardcoded so that a world can change its mind. The
    effect does the deciding -- whether they have done it already, whether
    what comes first is done, whether their hands are free -- so the rule can
    be this simple and still be right.
    """
    from world import actions, rulebooks

    made = []
    if actions.spec(root, "greet") is None:
        actions.declare(root, "greet",
                        applies_to=[{"role": "direct", "access": "visible"}],
                        means="to say hello to somebody")
    for entry in record.get("givers") or []:
        try:
            npc_id = int(entry.get("npc"))
        except (TypeError, ValueError):
            continue
        rule = rulebooks.add(root, rulebooks.blank(
            action="greet", phase=rulebooks.INSTEAD,
            scope={"object": npc_id}, about="direct",
            name=f"greeting them offers {record['title']}",
            effects=[{"type": "offer_quest", "quest": record["id"],
                      "role": "actor", "name_role": "direct"}],
            source="hand"))
        if rule:
            made.append(rule["id"])
    if not made:
        return "|xNothing offers it yet.|n"
    return (f"|w{', '.join(made)}|n now offer it: greeting them asks. "
            f"|xThat is an ordinary rule -- |wview rules greet|n reads it, "
            f"and |wedit rule|n takes it out of force.|n")


def _quest_items(ctx):
    from world.makers import rules as rule_forms

    return [
        menus.Field("title", "What it is called", required=True,
                    suggestible=True,
                    help="Three or four words naming the errand, as it will "
                         "read in somebody's list."),
        menus.Field("description", "What is asked", kind=menus.LONG_TEXT,
                    suggestible=True,
                    help="What the errand is, in general. A character who "
                         "would ask differently says so when they are added "
                         "below."),
        making.listing_field(
            "goal", "What finishes it", NEW_GOAL, goal_line,
            add_label="Add something that must become true", empty="nothing",
            help="All of them, together. Only what the game can actually "
                 "test: an errand it cannot check is one nobody can finish."),
        making.listing_field(
            "reward", "What they get", _reward_form(ctx), effect_line,
            add_label="Add a reward", empty="nothing"),
        making.listing_field(
            "punishment", "What failing costs", _reward_form(ctx),
            effect_line, add_label="Add a cost", empty="nothing"),
        menus.Field("time_limit", "How long they have", kind=menus.NUMBER,
                    minimum=quests_mod.MIN_TIME_LIMIT,
                    maximum=quests_mod.MAX_TIME_LIMIT,
                    help="In seconds. Left empty, there is no deadline, which "
                         "is usually kinder and always simpler."),
        making.listing_field(
            "givers", "Who hands it out", NEW_GIVER, giver_line,
            add_label="Add somebody", empty="nobody yet",
            help="An errand belongs to the world; the people who give it are "
                 "a field on it, so deleting one leaves the errand written."),
        menus.Field("repeatable", "Can it be done again?", kind=menus.BOOLEAN,
                    help="No means once ever, for this character."),
        menus.Field("cooldown", "Not again for", kind=menus.NUMBER, minimum=0,
                    lock=lambda ctx: bool(ctx.draft.get("repeatable")),
                    help="In seconds. Zero means as often as they like."),
        making.picker("after", "Only after", "quest", options=after_options,
                      make=False,
                      parse=lambda ctx, text: _read_ids(text),
                      show=lambda ctx, value: ", ".join(value or []) or "nothing",
                      help="Errands that must be finished first. This is what "
                           "makes a chain; several, separated by spaces."),
        making.listing_field(
            "only_when", "And only when", rule_forms.NEW_CONDITION,
            rule_forms.condition_line, add_label="Add a condition",
            empty="always",
            help="Anything else that must be true before it is on offer."),
        menus.Field("wire", "Offer it when somebody greets them?",
                    kind=menus.BOOLEAN, default=True,
                    help="Writes the rule that hands it over. No leaves the "
                         "errand written and unoffered, for a world that "
                         "wants to ask for it some other way."),
        making.keeper("keep", "Write this errand", keep_quest,
                      after=menus.STAY,
                      command=lambda ctx: "create quest <name>"),
    ]


NEW_QUEST = menus.Form(
    key="new-quest", title="An errand", guided=False,
    intro="Something somebody here wants done, written now and offered later. "
          "Costs nothing and needs no model.",
    discard="Throw away this errand?",
    items=_quest_items,
)


def _read_ids(text):
    found = [word.strip() for word in str(text or "").split()]
    return [word for word in found if word], ""


def quest_entries(root):
    found = []
    for record in sorted(quests_mod.specs(root).values(),
                         key=lambda r: r.get("id", "")):
        givers = quests_mod.givers_of(root, record)
        who = ", ".join(npc.key for npc, _said in givers) or "nobody"
        found.append((record["id"], f"{record['id']} -- {record['title']}",
                      f"given by {who}"))
    return found


def quest_text(root, spec_id):
    record = quests_mod.spec(root, str(spec_id or "").strip())
    if record is None:
        return ""
    from world import effects as fx

    lines = [f"|w{record['id']}|n {record['title']}"]
    if record.get("description"):
        lines.append(f"  {record['description']}")
    lines.append(f"  finished when: {goals.describe(record.get('goal'))}")
    for label, key in (("gives", "reward"), ("failing costs", "punishment")):
        if record.get(key):
            lines.append(f"  {label}: "
                         + ", ".join(fx.say(e) for e in record[key]))
    if record.get("time_limit"):
        lines.append(f"  within {record['time_limit']} seconds")
    givers = quests_mod.givers_of(root, record)
    if givers:
        lines.append("  given by:")
        for npc, own in givers:
            lines.append(f"    {npc.key}"
                         + (f" -- \"{own}\"" if own else " -- in the "
                                                         "errand's own words"))
    else:
        lines.append("  |ygiven by nobody -- nothing offers it|n")
    if record.get("repeatable"):
        cooldown = int(record.get("cooldown") or 0)
        lines.append("  can be done again"
                     + (f", after {cooldown} seconds" if cooldown else ""))
    else:
        lines.append("  once ever")
    if record.get("after"):
        lines.append(f"  only after {', '.join(record['after'])}")
    if len(givers) > 1:
        lines.append(f"  |xThe goal is one record: changing it changes the "
                     f"errand for all {len(givers)} of them. What each says "
                     f"about it is their own.|n")
    return "\n".join(lines)


def edit_quest(root, spec_id):
    record = quests_mod.spec(root, str(spec_id or "").strip())
    if record is None:
        return None

    def draft_of(ctx):
        return {
            "_id": record["id"],
            "title": record.get("title"),
            "description": record.get("description"),
            "goal": list(record.get("goal") or []),
            "reward": list(record.get("reward") or []),
            "punishment": list(record.get("punishment") or []),
            "time_limit": record.get("time_limit"),
            "givers": list(record.get("givers") or []),
            "repeatable": bool(record.get("repeatable")),
            "cooldown": record.get("cooldown"),
            "after": list(record.get("after") or []),
            "only_when": list(record.get("only_when") or []),
            "wire": False,
        }

    return menus.Form(
        key=f"edit-quest-{record['id']}", title=f"The errand {record['id']}",
        intro=lambda ctx: quest_text(root, record["id"]) + (
            "\n\n|xChanging what finishes it changes it for everybody who "
            "gives it. What each of them says about it is their own.|n"
            if len(quests_mod.givers_of(root, record)) > 1 else ""),
        items=[menus.Submenu(
            "change", "Change it", NEW_QUEST, fresh_draft=True,
            draft=draft_of,
            data=lambda ctx: {"world_root": root},
            help="The same form it was written with, filled in.")],
    )


def remove_quest(root, spec_id):
    gone = quests_mod.remove_spec(root, spec_id)
    if gone is None:
        return f"This world holds no errand called |w{spec_id}|n."
    return (f"|w{gone['id']}|n is gone. |xAnybody already running it keeps "
            f"it; the rules that offered it now offer nothing, and "
            f"|wview faults|n will say so.|n")


MAKERS = [
    making.Maker(
        "quest", ("quest", "quests", "errand", "errands"),
        "Errands", opens_with="title",
        listing=quest_entries, one=quest_text, new=NEW_QUEST,
        edit=edit_quest, remove=remove_quest,
        make_label="An errand somebody here wants done",
        none="None of these -- write a new errand",
        help="Something somebody wants done, written in advance and offered "
             "later. Needs no model, and a chain of them is what a world "
             "built by hand has instead of a plot.",
    ),
]
