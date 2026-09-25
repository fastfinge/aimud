"""
Rules, made by hand: conditions, effects, scope, and the phase asked last.

The shape of a rule does not change here. `rulebooks.blank` lists every slot,
`rulebooks.add` normalises the conditions and drops what cannot be stored, and
`conditions.normalise` holds each clause to its shape. This module fills the
same dictionary a model fills, through the same door.

Three things are worth knowing before reading it.

**The predicates are grouped by the question somebody is asking.** There are
twenty-six, and offered flat they are a wall. Grouped into the eight questions
a rule writer actually asks -- what state is it in, who has it, where is it,
what is it -- each group is three or four choices, and the one the grouping
earns is that the value picker afterwards can be the right one: `is` offers
this world's conditions, `kind` its kinds, `trait` its attributes.

**Effects are read out of `effects.VOCABULARY`.** That register already carries
a `means` sentence in the second person and a `takes` line naming its fields,
because `view effects` and `help <effect>` needed them. Adding an effect there
puts it in this menu; there is no second list to keep level.

**The phase is asked last**, and docs/player-building.md 8.4 has the argument:
a phase says what *else* runs, so nothing in a rule's own content distinguishes
instead from carry-out. Asked at the end, the question can show the rule its
nudges and its place in firing order, neither of which exists before the rest
is filled in.
"""

from world import conditions as cond
from world import effects as fx
from world import making, menus

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _root(ctx):
    return making.root_of(ctx)


def _caller(ctx):
    return making.caller_of(ctx)


SUBJECTS = (
    ("direct", "what you act on"),
    ("actor", "whoever is doing it"),
    ("instrument", "what you use"),
    ("target", "what you aim at"),
    ("container", "what it goes in"),
    ("source", "what it comes from"),
    ("here", "this place"),
    ("world", "this world"),
)


def subject_options(ctx):
    return [(value, f"{value} -- {said}") for value, said in SUBJECTS]


# ---------------------------------------------------------------------------
# One condition
# ---------------------------------------------------------------------------

#: The predicates, grouped by the question being asked. Every predicate in
#: `conditions.PREDICATES` appears exactly once, which a test holds to: a
#: predicate nobody can reach from a menu is one a hand-built world cannot use.
PREDICATE_GROUPS = (
    ("state", "What condition it is in", (
        ("is", "is in a condition", "states"),
        ("lacks", "is not in a condition", "states"),
    )),
    ("sort", "What sort of thing it is", (
        ("kind", "is a sort of thing", "kinds"),
        ("not_kind", "is not a sort of thing", "kinds"),
        ("affords", "can be verbed at all", "verbs"),
    )),
    ("having", "Who has it", (
        ("holds", "is carrying something", "thing"),
        ("not_holds", "is not carrying something", "thing"),
        ("wears", "has something on", "thing"),
        ("not_wears", "does not have something on", "thing"),
        ("owned_by", "belongs to somebody", "who"),
        ("not_owned_by", "does not belong to somebody", "who"),
    )),
    ("place", "Where it is", (
        ("placed", "is in or on something", "placement"),
        ("not_placed", "is not in or on something", "placement"),
        ("in_room", "is in a room", "text"),
        ("not_in_room", "is not in a room", "text"),
        ("leads_to", "leads somewhere", "text"),
        ("not_leads_to", "does not lead somewhere", "text"),
    )),
    ("figure", "A figure about somebody", (
        ("trait", "an attribute is within bounds", "trait"),
    )),
    ("being", "Whether it is there at all", (
        ("exists", "is in the world", "flag"),
        ("gone", "is no longer in the world", "flag"),
        ("unbound", "was not named at all", "flag"),
    )),
    ("reach", "Reach, sight and being able", (
        ("reachable_by", "can be touched by whoever is acting", "flag"),
        ("visible_to", "can be seen by whoever is acting", "flag"),
        ("able", "is free to act", "flag"),
    )),
    ("clock", "The time", (
        ("clock", "the world's clock stands somewhere", "clock"),
    )),
    ("never", "Never", (
        ("never", "nothing can satisfy this", "flag"),
    )),
)


def _predicate_of(name):
    for _group, _label, members in PREDICATE_GROUPS:
        for predicate, said, takes in members:
            if predicate == name:
                return predicate, said, takes
    return name, name, "text"


def group_options(ctx):
    return [(key, label) for key, label, _members in PREDICATE_GROUPS]


def predicate_options(ctx):
    chosen = str(ctx.draft.get("group") or "")
    for key, _label, members in PREDICATE_GROUPS:
        if key == chosen:
            return [(name, f"{name} -- {said}") for name, said, _t in members]
    return []


def _takes(ctx):
    """What sort of value the chosen predicate wants."""
    return _predicate_of(str(ctx.draft.get("predicate") or ""))[2]


def _wants(*sorts):
    return lambda ctx: _takes(ctx) in sorts


def state_options(ctx):
    from world import verbs

    root = _root(ctx)
    return [(slug, f"{slug} -- {entry.get('means') or ''}".rstrip(" -"))
            for slug, entry in sorted((verbs.vocabulary(root) or {}).items())]


def kind_options(ctx):
    from world.makers import vocabulary

    return vocabulary.kind_entries(_root(ctx))


def trait_options(ctx):
    from world.makers import vocabulary

    return [(value, label) for value, label, _help
            in vocabulary.attribute_entries(_root(ctx))]


def verb_options(ctx):
    from world.makers import vocabulary

    return vocabulary.affordance_options(ctx)


PLACEMENTS = (("in", "in it"), ("on", "on it"), ("under", "under it"),
              ("behind", "behind it"))


def keep_condition(ctx):
    """One clause, as `conditions.normalise` will take it."""
    subject = str(ctx.draft.get("subject") or "direct").strip()
    predicate = str(ctx.draft.get("predicate") or "").strip()
    if not predicate:
        raise menus.Refuse("A condition needs something it asks about.")
    takes = _takes(ctx)
    clause = {"subject": _subject_value(subject)}

    if takes == "states":
        wanted = ctx.draft.get("states") or []
        if not wanted:
            raise menus.Refuse("Name at least one condition.")
        clause[predicate] = list(wanted)
    elif takes == "kinds":
        wanted = str(ctx.draft.get("kind") or "").strip()
        if not wanted:
            raise menus.Refuse("Name a sort of thing.")
        clause[predicate] = wanted
    elif takes == "verbs":
        wanted = str(ctx.draft.get("verb") or "").strip()
        if not wanted:
            raise menus.Refuse("Name a verb.")
        clause[predicate] = wanted
    elif takes == "thing":
        clause[predicate] = _thing_value(ctx)
    elif takes == "who":
        clause[predicate] = str(ctx.draft.get("who") or "actor").strip()
    elif takes == "placement":
        where = str(ctx.draft.get("preposition") or "in").strip()
        host = str(ctx.draft.get("host") or "").strip()
        clause[predicate] = {where: host} if host else {where: True}
    elif takes == "trait":
        trait = str(ctx.draft.get("trait") or "").strip()
        if not trait:
            raise menus.Refuse("Name an attribute.")
        clause["trait"] = trait
        for bound in ("min", "max"):
            if ctx.draft.get(bound) is not None:
                clause[bound] = ctx.draft[bound]
        if ctx.draft.get("min") is None and ctx.draft.get("max") is None:
            raise menus.Refuse("Give a lowest, a highest, or both.")
    elif takes == "clock":
        clause["clock"] = str(ctx.draft.get("text") or "").strip()
        if not clause["clock"]:
            raise menus.Refuse("Say when: a part of the day, or an hour.")
    elif takes == "text":
        said = str(ctx.draft.get("text") or "").strip()
        if not said:
            raise menus.Refuse("This one needs a name.")
        clause[predicate] = said
    else:
        clause[predicate] = True

    kept, refused = cond.normalise_all([clause])
    if not kept:
        raise menus.Refuse(
            "That condition cannot be stored as it stands, so it would test "
            "as nothing for ever. Try another way of saying it.")
    return kept[0], f"Added: {cond.describe(kept[0], mood=cond.ABSTRACT)}"


def _subject_value(said):
    if said == "here":
        return cond.HERE
    if said == "world":
        return cond.WORLD
    return said


def _thing_value(ctx):
    """What `holds` and `wears` are given: a name, a sort, or a count of one."""
    kind = str(ctx.draft.get("kind") or "").strip()
    named = str(ctx.draft.get("text") or "").strip()
    count = ctx.draft.get("count")
    if kind:
        found = {"of_kind": kind}
        if count:
            found["count"] = int(count)
        return found
    if named:
        return named
    raise menus.Refuse("Name the thing, or pick a sort of thing.")


NEW_CONDITION = menus.Form(
    key="new-condition-clause", title="Something that must be true",
    guided=True,
    intro="A condition is one thing it is about and one question asked of it.",
    items=[
        menus.Picker("subject", "What it is about", options=subject_options,
                     required=True,
                     help="Which part of what somebody typed. `what you act "
                          "on` is the usual answer; `this place` and `this "
                          "world` are for a rule about somewhere rather than "
                          "something."),
        menus.Picker("group", "What sort of question", options=group_options,
                     required=True,
                     help="Narrows what is asked next. There are twenty-six "
                          "questions a condition can ask and no one writer "
                          "wants all of them at once."),
        menus.Picker("predicate", "The question", options=predicate_options,
                     required=True),
        making.picker("states", "Which conditions", "condition",
                      options=state_options,
                      lock=_wants("states"),
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none",
                      help="One or more, separated by spaces. Every one of "
                           "them must hold."),
        making.picker("kind", "Which sort of thing", "kind",
                      options=kind_options,
                      lock=_wants("kinds", "thing"),
                      help="A sort of thing rather than one particular thing, "
                           "so the rule reaches every one of them."),
        menus.Picker("verb", "Which verb", options=verb_options,
                     lock=_wants("verbs")),
        making.picker("trait", "Which attribute", "attribute",
                      options=trait_options, lock=_wants("trait")),
        menus.Field("min", "At least", kind=menus.NUMBER, lock=_wants("trait")),
        menus.Field("max", "At most", kind=menus.NUMBER, lock=_wants("trait")),
        menus.Field("count", "How many", kind=menus.NUMBER, minimum=1,
                    lock=_wants("thing"),
                    help="How many of that sort. Left empty, one is enough."),
        menus.Field("preposition", "Where", kind=menus.CHOICE,
                    lock=_wants("placement"),
                    choices=lambda ctx: [menus.Choice(v, l)
                                         for v, l in PLACEMENTS]),
        menus.Field("host", "In or on what", lock=_wants("placement"),
                    help="The thing it sits in. Left empty, anything will do "
                         "-- which is how `not placed under anything` says "
                         "that nothing covers it."),
        menus.Field("who", "Whose", lock=_wants("who"),
                    help="A role -- actor -- or somebody's name."),
        menus.Field("text", "Which", lock=_wants("text", "clock", "thing"),
                    help="Named as it is actually called here."),
        making.keeper("keep", "Keep this condition", keep_condition),
    ],
)


def condition_line(ctx, clause):
    return cond.describe(clause, mood=cond.ABSTRACT)


def _read_words(text):
    found = [word.strip().lower() for word in str(text or "").split()]
    return [word for word in found if word], ""


# ---------------------------------------------------------------------------
# One effect
# ---------------------------------------------------------------------------

#: Which fields each effect's form asks for, in the order it asks them.
#: `effects.VOCABULARY[...]["fields"]` is what the applier reads; this is the
#: same list arranged for somebody filling it in, with the two renames below.
#: A test holds them level, and that test is why this is now complete: it was
#: written from the `takes` prose, which had drifted, and so the menu could
#: not say what sort of thing a rule was making.
EFFECT_FIELDS = {
    "set_state": ("role", "add", "remove", "styles"),
    "set_trait": ("role", "trait", "change", "set_to", "rate"),
    "create_object": ("name", "description", "kind", "takeable", "states",
                      "trait_bonuses", "bonus_when", "bonus_while", "where"),
    "destroy_object": ("name_role",),
    "move_object": ("name_role", "to", "preposition"),
    "move_contents": ("name_role", "to", "taken_from"),
    "set_owner": ("name_role", "to", "cascade"),
    "modify_object": ("name_role", "new_name", "new_description",
                      "affordances"),
    "modify_room": ("new_name", "new_description"),
    "move_actor": ("way", "to"),
    "set_exit": ("way", "to"),
    "create_room": ("direction", "way", "why"),
    "describe": ("role",),
    "narrate": (),
    "try": ("action",),
    "offer_quest": ("quest", "name_role", "role"),
}

#: What a form deliberately does not ask for, and why. A gap on the record
#: rather than a gap: the test below reads this, so leaving something out is
#: a decision somebody wrote down instead of one nobody noticed.
NOT_ASKED = {
    ("try", "roles"):
        "a redirect runs the other verb over the roles the parser already "
        "bound, which is what makes it useful; naming different ones is a "
        "shape no menu can express usefully and no rule has ever wanted",
}


def effect_options(ctx):
    found = []
    for etype in sorted(EFFECT_FIELDS):
        known = fx.known(etype)
        found.append((etype, f"{etype} -- {known.get('means', '')}"))
    return found


def _effect_takes(ctx):
    return EFFECT_FIELDS.get(str(ctx.draft.get("type") or ""), ())


def _name_role_label(ctx):
    """One field, two questions: what it is done to, or who is doing it."""
    if str(ctx.draft.get("type") or "") == "offer_quest":
        return "Who asks"
    return "To what"


def _asks(field):
    return lambda ctx: field in _effect_takes(ctx)


#: Where a field is asked under one name and stored under another. Two, and
#: both for a reason outside the effect itself: `exit` quits every menu in the
#: game, and `location` reads as a place rather than a choice between two.
#: `taken_from` is the third: `from` is a Python keyword, so it cannot be a
#: field name, and a form field called `from` would read as where the thing
#: goes rather than where it comes out of.
STORED_AS = {"way": "exit", "where": "location", "taken_from": "from"}

#: Fields that hold several things, however few were typed.
LISTED = frozenset(["add", "remove", "states"])


WHERE_NEW = (("room", "here, on the floor"), ("actor", "in your hands"))


def keep_effect(ctx):
    etype = str(ctx.draft.get("type") or "").strip()
    if not etype:
        raise menus.Refuse("An effect needs a type.")
    effect = {"type": etype}
    wanted = EFFECT_FIELDS.get(etype, ())

    for field in wanted:
        value = ctx.draft.get(field)
        if value in (None, "", []):
            continue
        if field in LISTED:
            effect[field] = list(value) if isinstance(value, list) else [value]
        elif field == "affordances":
            effect[field] = {str(one.get("verb")): bool(one.get("yes"))
                             for one in value if one.get("verb")}
        elif field == "styles":
            effect[field] = {str(one.get("state")): str(one.get("said"))
                             for one in value if one.get("state")}
        elif field in ("trait_bonuses", "bonus_when", "bonus_while"):
            continue            # written together, below

        else:
            effect[STORED_AS.get(field, field)] = value

    if etype == "set_state" and not (effect.get("add") or effect.get("remove")):
        raise menus.Refuse("Say what it puts something into, or takes it out "
                           "of.")
    if etype == "set_trait" and not any(
            effect.get(f) is not None for f in ("change", "set_to", "rate")):
        raise menus.Refuse("Say how the figure moves: by how much, to what, "
                           "or at what rate a second.")
    if etype == "create_object" and not effect.get("name"):
        raise menus.Refuse("Say what it produces.")

    if etype == "create_object":
        # The three that are one answer: what it grants, when that counts and
        # what it must be in first. `gearing.spec` writes nothing at all when
        # nothing was granted, because an empty map reads to `gear.bonuses`
        # as a claim that this is a thing worth having.
        from world.makers import gearing

        effect.update(gearing.spec(ctx.draft))

    # Held to what a rule's effect is held to whoever wrote it: a name says
    # what a thing is and never its condition, and a description may only ask
    # for word lists this world keeps.
    complaint = _text_complaints(ctx, effect)
    if complaint:
        raise menus.Refuse(complaint)
    return effect, f"Added: {fx.say(effect)}"


def _text_complaints(ctx, effect):
    from world import token_lists, verbs

    root = _root(ctx)
    said = []
    for field in ("name", "new_name"):
        name = str(effect.get(field) or "")
        if name:
            wrong = verbs.name_contradicts_states(name, set(), root)
            if wrong:
                said.append(
                    f"a name says what a thing is and not what condition it "
                    f"is in, and {', '.join(wrong)} "
                    f"{'is a condition' if len(wrong) == 1 else 'are conditions'}")
    for field in ("description", "new_description"):
        text = str(effect.get(field) or "")
        if text:
            unknown = sorted(
                name for name in token_lists.references(text)
                if name not in fx._BUILTIN_SLOTS
                and token_lists.get(root, name) is None)
            if unknown:
                said.append(
                    f"this world keeps no word list called "
                    f"{', '.join(unknown)} -- |wcreate tokens|n makes one, or "
                    f"take the braces out")
    return "; ".join(said).capitalize() + "." if said else ""


def _affordance_form(ctx):
    from world.makers import vocabulary

    return vocabulary.NEW_AFFORDANCE


def _affordance_said(ctx, entry):
    return f"{entry.get('verb')} -- {'yes' if entry.get('yes') else 'no'}"


STYLE = menus.Form(
    key="new-style", title="How it is in that condition", guided=True,
    intro="A condition, and this thing's own way of being in it.",
    items=[
        making.picker("state", "Which condition", "condition",
                      options=state_options, required=True),
        menus.Field("said", "In its own words", required=True,
                    suggestible=True,
                    help="Slung over one arm; jammed half open; guttering."),
        making.keeper("keep", "Keep it", lambda ctx: (
            {"state": str(ctx.draft.get("state") or ""),
             "said": str(ctx.draft.get("said") or "")},
            f"{ctx.draft.get('state')}: {ctx.draft.get('said')}")),
    ],
)


def _style_form(ctx):
    return STYLE


def _style_said(ctx, entry):
    return f"{entry.get('state')}: {entry.get('said')}"


def _gearing():
    """
    What the thing a rule makes is worth, asked the way an item's is.

    Locked to `create_object`, which is the one effect that makes something to
    be worth anything. Shared with `create item` rather than written twice, so
    a sword a rule forges and one somebody typed are armed the same way.
    """
    from world.makers import gearing

    found = []
    for item in gearing.items():
        was = item.lock
        item.lock = (lambda ctx, key=item.key, was=was:
                     key in _effect_takes(ctx)
                     and (was is None or was(ctx)))
        found.append(item)
    return found


NEW_EFFECT = menus.Form(
    key="new-effect", title="Something that happens", guided=True,
    intro="What a rule actually does. Everything a verb changes it changes "
          "through one of these.",
    items=[
        menus.Picker("type", "What happens", options=effect_options,
                     required=True,
                     help="Each says what it does in one line. An effect "
                          "nothing can read backwards -- renaming, digging -- "
                          "is one no character can ever plan towards."),
        menus.Picker("role", "To what", options=subject_options,
                     lock=_asks("role")),
        menus.Picker("name_role", _name_role_label, options=subject_options,
                     lock=_asks("name_role"),
                     help=lambda ctx: (
                         "Whoever is doing the asking. Left empty, whatever "
                         "is being acted on -- greeting somebody offers "
                         "their errand."
                         if str(ctx.draft.get("type") or "") == "offer_quest"
                         else "Which part of what somebody typed this "
                              "happens to.")),
        making.picker("add", "Puts it into", "condition",
                      options=state_options, lock=_asks("add"),
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none",
                      help="One or more conditions, separated by spaces."),
        making.picker("remove", "Takes it out of", "condition",
                      options=state_options, lock=_asks("remove"),
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none"),
        making.picker("trait", "Which attribute", "attribute",
                      options=trait_options, lock=_asks("trait")),
        menus.Field("change", "Moves it by", kind=menus.NUMBER,
                    lock=_asks("change"),
                    help="Up or down, at once. Negative costs them."),
        menus.Field("set_to", "Puts it at", kind=menus.NUMBER,
                    lock=_asks("set_to")),
        menus.Field("rate", "A second, from now on", kind=menus.NUMBER,
                    lock=_asks("rate"),
                    help="Sets it drifting: a poison drains, a rest restores. "
                         "Zero stops it drifting."),
        menus.Field("name", "What it produces", lock=_asks("name"),
                    suggestible=True,
                    help="Two to four words, as the thing will be called."),
        menus.Field("description", "What it looks like", kind=menus.LONG_TEXT,
                    lock=_asks("description"), suggestible=True),
        making.picker("kind", "What sort of thing it is", "kind",
                      options=kind_options, lock=_asks("kind"),
                      help="Which sort the thing it makes belongs to. This is "
                           "where its affordances come from and what a rule "
                           "about that sort of thing will reach -- and left "
                           "empty it is guessed from the head noun of "
                           "whatever the thing is called, which is how a "
                           "Wisp of Steam becomes a wisp."),
        menus.Field("takeable", "Can it be picked up?", kind=menus.BOOLEAN,
                    lock=_asks("takeable"), default=True,
                    help="Answered for the sort of thing rather than only "
                         "this one, so a world with forty chairs answers "
                         "once."),
        making.picker("states", "What condition it is made in", "condition",
                      options=state_options, lock=_asks("states"),
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none",
                      help="Conditions it exists in from the moment it is "
                           "made: lit, wet, brewed. Several, separated by "
                           "spaces."),
        *_gearing(),
        menus.Field("where", "Where it appears", kind=menus.CHOICE,
                    lock=_asks("where"),
                    choices=lambda ctx: [menus.Choice(v, l)
                                         for v, l in WHERE_NEW]),
        menus.Field("to", "Where it goes", lock=_asks("to"),
                    help="actor for their hands, room for the floor, a role, "
                         "or the name of a room."),
        menus.Field("preposition", "How", kind=menus.CHOICE,
                    lock=_asks("preposition"),
                    choices=lambda ctx: [menus.Choice(v, l)
                                         for v, l in PLACEMENTS]),
        menus.Field("taken_from", "Out of where", kind=menus.CHOICE,
                    lock=_asks("taken_from"),
                    choices=lambda ctx: [menus.Choice(v, l)
                                         for v, l in PLACEMENTS],
                    help="Which of the things it holds are emptied out: what "
                         "is in it, on it, under it or behind it. Left empty, "
                         "whatever is inside."),
        menus.Field("cascade", "And everything it holds?", kind=menus.BOOLEAN,
                    lock=_asks("cascade"),
                    help="Yes hands over what is inside it as well, so giving "
                         "somebody a satchel gives them what is in it."),
        making.listing_field(
            "affordances", "What can now be done to it",
            _affordance_form, _affordance_said,
            add_label="Add a verb", empty="leave it as its sort decides",
            help="Changes what this particular thing affords, which its sort "
                 "would otherwise decide. Burning one book does not stop "
                 "books being readable."),
        making.listing_field(
            "styles", "How it is in that condition", _style_form, _style_said,
            add_label="Add a way of being in one", empty="said plainly",
            help="How this thing wears a condition, in its own words: a "
                 "cloak slung over one arm rather than merely worn. One per "
                 "condition."),
        menus.Field("new_name", "Its new name", lock=_asks("new_name")),
        menus.Field("new_description", "Its new look", kind=menus.LONG_TEXT,
                    lock=_asks("new_description"), suggestible=True),
        # Stored as `exit`, which is what `effects.apply` reads. Not named
        # that here: `exit` quits every menu in the game.
        menus.Field("way", "Which way out", lock=_asks("way"),
                    help="The name of a way out of this room: north, the "
                         "hatch, down."),
        menus.Field("direction", "Which way", lock=_asks("direction"),
                    help="north, down, in. The way the new place opens off "
                         "this one."),
        menus.Field("why", "What the place is", kind=menus.LONG_TEXT,
                    lock=_asks("why"), suggestible=True,
                    help="What is through there and how it came to be, for "
                         "whoever writes it when somebody first walks in."),
        making.picker("action", "Which verb instead", "action",
                      lock=_asks("action"),
                      help="The whole attempt starts again as that verb, so "
                           "every check about it still applies."),
        making.picker("quest", "Which errand", "quest",
                      lock=_asks("quest"), make=False,
                      help="An errand this world has written. Whether it may "
                           "actually be offered -- already done, too soon, "
                           "something else first -- the effect decides, so "
                           "the rule does not have to."),
        making.keeper("keep", "Keep this effect", keep_effect),
    ],
)


def narrowed_effects(options):
    """
    The same effect form, offering a shorter list.

    A quest's reward may do less than a verb may (`quests.QUEST_EFFECTS`), and
    the difference belongs in the list offered rather than in a second form
    that would drift from this one the first time an effect gained a field.
    """
    items = []
    for item in NEW_EFFECT.items:
        if isinstance(item, menus.Picker) and item.key == "type":
            items.append(menus.Picker(
                "type", item.label, options=options, required=True,
                help="Narrower than what a verb may do: an errand is a "
                     "transaction between two characters, not a licence to "
                     "rewrite the room it was agreed in."))
        else:
            items.append(item)
    return menus.Form(key="new-quest-effect", title=NEW_EFFECT.title,
                      guided=True, intro=NEW_EFFECT.intro, items=items)


def effect_line(ctx, effect):
    return fx.say(effect)


# ---------------------------------------------------------------------------
# Where a rule applies
# ---------------------------------------------------------------------------

def scope_options(ctx):
    """Every scope worth offering, most particular first."""
    from world import kinds, zones

    root = _root(ctx)
    here = getattr(_caller(ctx), "location", None)
    found = []
    if here is not None:
        for obj in _things_here(ctx):
            found.append((f"object:{obj.id}",
                          f"this very {obj.key}"))
        for kind in sorted(_kinds_here(ctx)):
            found.append((f"kind:{kind}", f"anything of the sort {kind}"))
        found.append((f"room:{here.id}", f"this room ({here.key})"))
        zone = getattr(here.db, "zone", "")
        if zone:
            found.append((f"zone:{zones.slugify(zone)}",
                          f"this whole area ({zone})"))
    for kind in kinds.vocabulary(root):
        entry = f"kind:{kind}"
        if entry not in {value for value, _label in found}:
            found.append((entry, f"anything of the sort {kind}"))
    found.append(("world", "everywhere in this world"))
    return found


def _things_here(ctx):
    from world import relations

    caller = _caller(ctx)
    try:
        return [obj for obj in relations.reachable(caller)
                if obj is not caller][:12]
    except Exception:
        return []


def _kinds_here(ctx):
    from world import kinds

    found = set()
    for obj in _things_here(ctx):
        try:
            found.update(kinds.of(obj))
        except Exception:
            continue
    return found


def _scope_dict(said):
    """The picker's value, as `rulebooks._clean_scope` wants it."""
    said = str(said or "world").strip()
    if said == "world" or ":" not in said:
        return {"world": True}
    which, _colon, value = said.partition(":")
    if which in ("object", "room"):
        try:
            return {which: int(value)}
        except ValueError:
            return {"world": True}
    return {which: value}


ABOUT = (
    ("direct", "what you act on"),
    ("actor", "whoever is doing it"),
    ("instrument", "what you use"),
    ("target", "what you aim at"),
    ("here", "the room it happens in"),
    ("zone", "the area it happens in"),
    ("enclosure", "whatever you are inside at the time"),
)


# ---------------------------------------------------------------------------
# The phase, asked last
# ---------------------------------------------------------------------------

PHASE_CHOICES = (
    ("check", "It should be stopped -- say why it cannot happen, and refuse "
              "it"),
    ("carry_out", "It is what happens -- this is what the verb does here"),
    ("instead", "Something else should happen instead, and the usual thing "
                "should not"),
    ("after", "It follows afterwards -- once it has already worked"),
    ("becomes", "Nothing is being tried -- this happens when something "
                "becomes true"),
)

PHASE_NOTES = {
    "check": "Every rule like this applies, so you can write half of it now "
             "and add the rest later.",
    "carry_out": "The most particular rule wins; the checks still apply "
                 "first.",
    "instead": "The most particular rule wins outright, and nothing else "
               "runs -- not even the checks.",
    "after": "It runs only once the action has worked.",
    "becomes": "It runs because the world changed, not because anybody typed "
               "anything.",
}


def phase_options(ctx):
    return [(value, said, PHASE_NOTES.get(value, ""))
            for value, said in PHASE_CHOICES]


def phase_nudge(ctx):
    """
    What the rest of the rule says about the phase chosen. Never a choice.

    Three of them, and each names a way a rule fails by doing nothing rather
    than by breaking -- which is the failure this game is most careful about
    everywhere else and had no way to catch here.
    """
    phase = str(ctx.draft.get("phase") or "")
    effects = list(ctx.draft.get("effects") or [])
    action = str(ctx.draft.get("action") or "")
    said = []
    if phase == "check" and effects:
        said.append(
            "|yThis is a check rule that changes something.| That is allowed "
            "-- refusing can set a condition -- and is usually a slip: a check "
            "rule runs while the world decides whether to let the action "
            "happen at all.|n")
    if phase in ("carry_out", "instead") and not effects:
        said.append(
            "|yThis rule does nothing.| A carry-out with no effects means the "
            "verb succeeds and changes nothing, which reads to a player as it "
            "having worked. Add an effect, or make it a check.|n")
    if phase in ("carry_out", "instead", "after") and ctx.draft.get(
            "conditions"):
        said.append(
            "|yWhat this rule requires will never be tested.| Only a check "
            "rule's requirements are looked at; in this phase the field that "
            "decides whether the rule applies at all is |wOnly when|y. Move "
            "them there, or make this a check rule and write a second one to "
            "do the work.|n")
    if not action and phase != "becomes":
        said.append(
            "|yNo verb is named, so this rule is about every action there "
            "is.| That is how a world says `nothing works while you are "
            "dead` once. If you meant `when something becomes true`, that is "
            "the last choice.|n")
    if phase == "becomes" and action:
        said.append(
            "|yA becomes rule has no verb| -- it runs because the world "
            "changed. The verb will be dropped.|n")
    return "\n".join(said)


def firing_order(ctx):
    """Where this rule would sit among the ones already there."""
    from world import rulebooks

    root = _root(ctx)
    if root is None:
        return ""
    action = str(ctx.draft.get("action") or "") or None
    found = [r for r in rulebooks.all_rules(root)
             if r.get("action") in (None, action)]
    mine = _draft_rule(ctx)
    lines = []
    from world import rulecheck

    dead = {gone.get("id") for gone, _winner in rulecheck.shadowed(
        {r["id"]: r for r in rulebooks.all_rules(root)}, root)}
    for phase in rulebooks.PHASES:
        here = sorted((r for r in found if r.get("phase") == phase),
                      key=lambda r: rulebooks.rank(r, None, root))
        rows = [f"    {rulebooks.said_scope(r.get('scope'), root)} -- "
                f"{r.get('name') or 'unnamed'}"
                + ("  |rnever fires|n" if r.get("id") in dead else "")
                for r in here]
        if mine.get("phase") == phase:
            rows.append(f"    {rulebooks.said_scope(mine.get('scope'), root)} "
                        f"-- {mine.get('name') or 'this one'}  |g<- yours|n")
        if rows:
            lines.append(f"  |y{phase.replace('_', ' ')}|n")
            lines += rows
    return "\n".join(lines)


def _draft_rule(ctx):
    """The draft as a rule record, for showing and for keeping."""
    from world import rulebooks

    phase = str(ctx.draft.get("phase") or rulebooks.CHECK)
    action = str(ctx.draft.get("action") or "").strip() or None
    if phase == rulebooks.BECOMES:
        action = None
    return rulebooks.blank(
        action=action, phase=phase,
        scope=_scope_dict(ctx.draft.get("scope")),
        about=str(ctx.draft.get("about") or "direct"),
        name=str(ctx.draft.get("name") or ""),
        when=list(ctx.draft.get("when") or []),
        conditions=list(ctx.draft.get("conditions") or []),
        effects=list(ctx.draft.get("effects") or []),
        source="hand",
        report=str(ctx.draft.get("report") or ""))


PHASE_FORM_INTRO = (
    "A phase does not say what this rule does. It says what else runs.\n")


def _phase_items(ctx):
    return [
        menus.Picker("phase", "What should happen", options=phase_options,
                     required=True, after=menus.BACK,
                     help="Each line names the consequence rather than the "
                          "rulebook: whether every rule like it applies or "
                          "only the most particular one, and whether the "
                          "checks still run."),
    ]


PHASE_FORM = menus.Form(
    key="rule-phase", title="What should happen?",
    intro=lambda ctx: PHASE_FORM_INTRO + _phase_intro(ctx),
    items=_phase_items,
)


def _phase_intro(ctx):
    said = []
    nudge = phase_nudge(ctx)
    if nudge:
        said += ["", nudge]
    order = firing_order(ctx)
    if order:
        said += ["", "Where it would sit:", order]
    return "\n".join(said)


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def action_options(ctx):
    from world.makers import doing

    found = [(value, label) for value, label, _help
             in doing.action_entries(_root(ctx))]
    return found


def keep_rule(ctx):
    from world import rulebooks

    root = _root(ctx)
    record = _draft_rule(ctx)
    if not record.get("effects") and not record.get("conditions"):
        raise menus.Refuse(
            "A rule that requires nothing and does nothing would never be "
            "noticed. Give it something to require, or something to do.")
    stored = rulebooks.add(root, record)
    if stored is None:
        raise menus.Refuse("That rule could not be filed.")
    said = [f"|w{stored['id']}|n is filed: "
            f"{rulebooks.said_scope(stored['scope'], root)}, "
            f"{stored['phase'].replace('_', ' ')}"
            + (f", when somebody tries {stored['action']}"
               if stored["action"] else ", for every action")
            + "."]
    warning = _faults_about(root, stored)
    if warning:
        said += ["", warning]
    return stored["id"], "\n".join(said)


def _faults_about(root, rule):
    """
    What this world's own rules say about the one just written.

    Shown and never refused: a builder who knows what they are doing is
    allowed to write a rule whose moment has not arrived yet, and `view
    faults` says the same thing later.
    """
    from world import rulebooks, rulecheck

    said = []
    try:
        report = set(rulecheck.scan(rulecheck.of_world(root))
                     .get("unsettable") or [])
    except Exception:
        report = set()
    wanted = set()
    for clause in rule.get("conditions") or []:
        predicate, value = cond.predicate_of(clause)
        if predicate in ("is", "lacks"):
            wanted.update(str(one) for one in (value or []))
    stuck = sorted(wanted & report)
    if stuck:
        said.append(f"|xNothing in this world can bring about "
                    f"{', '.join(stuck)}, so this rule cannot fire yet. "
                    f"|wview faults|n keeps track.|n")

    # And the one worth saying loudly, at the moment it is written: a second
    # unguarded rule at one scope, in a phase that takes one winner, is a
    # rule that can never fire -- and nothing about playing the world would
    # ever say so. See `rulecheck.shadowed`.
    try:
        book = {r["id"]: r for r in rulebooks.all_rules(root)}
        dead = rulecheck.shadowed(book, root)
    except Exception:
        dead = []
    if str(rule.get("phase") or "") not in ("check", "becomes") \
            and (rule.get("conditions") or []):
        said.append(
            f"|yWhat this rule requires is not tested.|n Only a check rule's "
            f"requirements are; in "
            f"{str(rule.get('phase', '')).replace('_', ' ')} the field that "
            f"decides whether it applies is |wOnly when|n. As written it "
            f"applies whenever it is reached.\n"
            f"|x|wedit rule {rule.get('id')}|x can move them.|n")
    for gone, winner in dead:
        if gone.get("id") != rule.get("id"):
            continue
        said.append(
            f"|yThis rule will never fire.|n "
            f"|w{winner.get('name') or winner.get('id')}|n is at the same "
            f"scope with nothing to hold it back, and "
            f"{str(rule.get('phase', '')).replace('_', ' ')} takes one "
            f"winner, so that one wins every time.\n"
            f"|xGive this one a guard -- |wOnly when|x -- or a narrower "
            f"place to apply, so the world can tell which one an attempt "
            f"means. |wedit rule {winner.get('id')}|x reaches the other.|n")
    return "\n".join(said)


def _rule_items(ctx):
    from world import rulebooks

    return [
        menus.Field("name", "What to call it", required=True,
                    help="A line somebody reading the rules will understand: "
                         "`a lit lamp cannot be lit again`."),
        making.picker("action", "When somebody tries", "action",
                      options=action_options,
                      help="Which verb this is about. Left empty, the rule is "
                           "about every action there is, which is how a world "
                           "says `nothing works while you are dead` once."),
        menus.Picker("scope", "Where it applies", options=scope_options,
                     required=True,
                     help="Most particular wins. A rule about datapads "
                          "decides what powering a datapad does even aboard a "
                          "ship with its own rule about powering."),
        menus.Field("about", "What that is matched against", kind=menus.CHOICE,
                    choices=lambda ctx: [menus.Choice(v, f"{v} -- {said}")
                                         for v, said in ABOUT],
                    help="Whether the sort of thing above means the thing "
                         "acted on, or the place it happens in. This is the "
                         "difference between powering the datapad and "
                         "powering the ship you are standing in."),
        making.listing_field(
            "conditions", "It requires", NEW_CONDITION, condition_line,
            add_label="Add a condition", empty="nothing",
            help="What must be true. All of them, together."),
        making.listing_field(
            "effects", "Then", NEW_EFFECT, effect_line,
            add_label="Add an effect", empty="nothing",
            help="What it does. Everything a rule changes it changes through "
                 "one of these."),
        making.listing_field(
            "when", "Only when", NEW_CONDITION, condition_line,
            add_label="Add a guard", empty="always",
            help="Guards: whether this rule is consulted at all. Different "
                 "from what it requires, which is what it refuses for."),
        menus.Field("report", "What people see", kind=menus.LONG_TEXT,
                    lock=lambda ctx: str(ctx.draft.get("phase") or "")
                    == rulebooks.BECOMES,
                    help="What is said when this fires. Only a becomes rule "
                         "needs one: everything else is narrated already."),
        menus.Submenu("phase", _phase_label, PHASE_FORM,
                      help="What else runs. Asked last, because it is the one "
                           "field that is about the rest of the rule."),
        making.keeper("keep", "File this rule", keep_rule,
                      command=lambda ctx: "create rule <name>"),
    ]


def _phase_label(ctx):
    chosen = str(ctx.draft.get("phase") or "")
    for value, said in PHASE_CHOICES:
        if value == chosen:
            return f"What should happen: {said}"
    return "What should happen: |ynot chosen yet|n"


NEW_RULE = menus.Form(
    key="new-rule", title="A rule", guided=False,
    intro="What happens when somebody tries something here, and what has to "
          "be true first.",
    discard="Throw away this rule?",
    items=_rule_items,
)


def rule_entries(root):
    from commands.rules_subject import rule_line
    from world import rulebooks

    found = []
    for rule in rulebooks.all_rules(root):
        found.append((rule["id"],
                      f"{rule['id']} [{rule.get('phase')}] "
                      f"{rule.get('name') or rule_line(rule, root)}"))
    return found


def rule_text(root, rule_id):
    from world import rulebooks

    rule = rulebooks.get(root, str(rule_id or "").strip())
    if rule is None:
        return ""
    lines = [f"|w{rule['id']}|n {rule.get('name') or ''}",
             f"  {rule.get('phase', '').replace('_', ' ')}"
             + (f", when somebody tries {rule['action']}" if rule.get("action")
                else ", for every action"),
             f"  applies to {rulebooks.said_scope(rule.get('scope'), root)}, "
             f"matched against {rule.get('about')}"]
    if not rule.get("listed", True):
        lines.append("  |ysuspended|n")
    for label, key in (("only when", "when"), ("requires", "conditions")):
        clauses = rule.get(key) or []
        if clauses:
            lines.append(f"  {label}:")
            lines += [f"    {cond.describe(c, mood=cond.ABSTRACT)}"
                      for c in clauses]
    if rule.get("effects"):
        lines.append("  then:")
        lines += [f"    {fx.say(e)}" for e in rule["effects"]]
    if rule.get("report"):
        lines.append(f"  says: {rule['report']}")
    return "\n".join(lines)


def edit_rule(root, rule_id):
    from world import rulebooks

    rule = rulebooks.get(root, str(rule_id or "").strip())
    if rule is None:
        return None

    def rename(ctx, value):
        store = dict(getattr(root.db, rulebooks.ATTR, None) or {})
        record = dict(store.get(rule["id"]) or {})
        record["name"] = str(value or "")
        store[rule["id"]] = record
        setattr(root.db, rulebooks.ATTR, store)
        return f"{rule['id']}: {value}"

    def listing(ctx, value):
        rulebooks.set_listed(root, rule["id"], bool(value))
        return ("In force again." if value
                else "Suspended. It stays readable and does nothing.")

    return menus.Form(
        key=f"edit-rule-{rule['id']}", title=f"Rule {rule['id']}",
        intro=lambda ctx: rule_text(root, rule["id"]),
        items=[
            menus.Field("name", "What to call it",
                        get=lambda ctx: (rulebooks.get(root, rule["id"]) or {})
                        .get("name"), set=rename),
            menus.Field("listed", "In force?", kind=menus.BOOLEAN,
                        get=lambda ctx: (rulebooks.get(root, rule["id"]) or {})
                        .get("listed", True), set=listing,
                        help="A suspended rule stays readable and does "
                             "nothing. This is how a rule is taken back "
                             "without losing what it said."),
        ],
    )


def remove_rule(root, rule_id):
    from world import rulebooks

    rule_id = str(rule_id or "").strip()
    store = dict(getattr(root.db, rulebooks.ATTR, None) or {})
    if rule_id not in store:
        return f"This world holds no rule called |w{rule_id}|n."
    store.pop(rule_id)
    setattr(root.db, rulebooks.ATTR, store)
    return (f"|w{rule_id}|n is gone. |xIf you only meant to take it out of "
            f"force, |wedit rule|n suspends one instead and keeps what it "
            f"said.|n")


MAKERS = [
    making.Maker(
        "rule", ("rule",),
        "Rules", opens_with="name",
        listing=rule_entries, one=rule_text, new=NEW_RULE,
        edit=edit_rule, remove=remove_rule,
        make_label="A rule",
        help="What happens when somebody tries something here, what has to be "
             "true first, and what follows.",
    ),
]
