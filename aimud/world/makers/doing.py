"""
Actions, made by hand: what a verb takes, before anything says what it does.

Inform declares `Powering is an action applying to one thing` before it says
what powering does, and `world/actions.py` says why the separation earns its
keep. What it has never had is a way for a person to make the declaration --
it is learned from an attempt, or asked of a model, and a world built by hand
has neither.

The hard half of the declaration is already multiple choice: five roles, three
degrees of nearness, three gates. The one free answer is the sense, and the
dictionary supplies the menu for that too.
"""

from world import lexicon, making, menus

ACCESS_SAID = (
    ("touchable", "within reach -- the ordinary answer"),
    ("visible", "near enough to see: reading a notice across a room"),
    ("carried", "in their hands, and picked up first if it is not"),
)

GATES_SAID = (
    ("acting", "somebody who cannot act at all may still do this"),
    ("moving", "somebody who cannot move may still do this"),
    ("speaking", "somebody who cannot speak may still do this"),
)

MUST_HELP = (
    "What a rule about this verb is not finished without. Left empty -- "
    "almost always -- a rule may do whatever it likes, which includes "
    "nothing. Name something here and a rule that carries the verb out "
    "without it is refused and asked for again, which is how a world says "
    "\"combining two things always produces a new thing\" and is obeyed "
    "rather than merely heard. It does not say what the new thing is: that "
    "is still the rule's answer, and a different one for every pair."
)


def _root(ctx):
    return making.root_of(ctx)


def _must_choices(ctx):
    from world import actions

    return [menus.Choice(name, said) for name, said, _e in actions.MUST]


def _read_must(text):
    from world import actions

    wanted = [word.strip().lower() for word in str(text or "").split()]
    bad = [word for word in wanted if word and word not in actions.MUSTS]
    if bad:
        return None, (f"{bad[0]} is not one of "
                      + ", ".join(actions.MUSTS) + ".")
    return [word for word in wanted if word], ""


def _said_must(value):
    from world import actions

    return ", ".join(actions.said_must(name)
                     for name in (value or [])) or "anything at all"


# ---------------------------------------------------------------------------
# One role
# ---------------------------------------------------------------------------

def _role_options(ctx):
    from world import actions

    taken = {str(entry.get("role"))
             for entry in (ctx.draft.get("_taken") or [])}
    said = {
        "direct": "the thing it is done to -- open the DOOR",
        "instrument": "what it is done with -- unlock it with the KEY",
        "target": "what it is done to or towards -- tie it to the TREE",
        "container": "what it is done into -- put it in the BOX",
        "source": "what it is done out of -- take it from the SHELF",
    }
    return [(role, f"{role} -- {said.get(role, '')}")
            for role in actions.ROLES if role not in taken]


NEW_ROLE = menus.Form(
    key="new-role", title="A part the verb takes", guided=True,
    intro="Which noun the verb takes, and how near you have to be to it.",
    items=[
        menus.Picker("role", "Which part", options=_role_options,
                     required=True,
                     help="There is always somebody acting, so that is never "
                          "declared. These are the things they act on."),
        menus.Field("access", "How near", kind=menus.CHOICE, required=True,
                    choices=lambda ctx: [menus.Choice(value, label)
                                         for value, label in ACCESS_SAID],
                    help="Carried is the one with a consequence: it picks the "
                         "thing up first, so never also require that they are "
                         "already holding it."),
        menus.Field("optional", "May it be left unsaid?", kind=menus.BOOLEAN,
                    help="Yes where the world can work out what was meant: "
                         "aboard a ship, launch means the ship."),
        making.keeper("keep", "Keep this part", lambda ctx: (
            {"role": str(ctx.draft.get("role") or ""),
             "access": str(ctx.draft.get("access") or "touchable"),
             "optional": bool(ctx.draft.get("optional"))},
            f"{ctx.draft.get('role')}, {ctx.draft.get('access')}"
            + (", optional" if ctx.draft.get("optional") else "") + ".")),
    ],
)


def role_line(ctx, entry):
    return (f"{entry.get('role')} ({entry.get('access')}"
            + (", optional)" if entry.get("optional") else ")"))


# ---------------------------------------------------------------------------
# The action
# ---------------------------------------------------------------------------

def verb_sense_options(ctx):
    word = str(ctx.draft.get("action") or "").strip().lower()
    found = [(name, f"{name} -- {gloss}")
             for name, gloss in lexicon.senses(word, pos="v", limit=12)]
    found.append(("", "None of them -- say what it means below instead"))
    return found


def keep_action(ctx):
    from world import actions, verbs

    root = _root(ctx)
    word = verbs.canonical_verb(
        str(ctx.draft.get("action") or "").strip().lower())
    if not word:
        raise menus.Refuse("An action needs a verb.")
    if actions.spec(root, word) is not None:
        raise menus.Refuse(
            f"This world has already settled what |w{word}|n takes, and every "
            f"rule about it was written against that. |wview action {word}|n "
            f"shows it; |wreset verb {word}|n forgets it, and says what that "
            f"costs first.")
    record = actions.declare(
        root, word,
        applies_to=ctx.draft.get("applies_to") or (),
        sense=str(ctx.draft.get("sense") or ""),
        means=str(ctx.draft.get("means") or ""),
        despite=ctx.draft.get("despite") or (),
        must=ctx.draft.get("must") or ())
    if record is None:
        raise menus.Refuse(f"|w{word}|n could not be declared.")
    takes = ", ".join(r["role"] for r in record["applies_to"]) or "nothing"
    return word, (f"|w{word}|n is declared, and takes {takes}. Nothing yet "
                  f"says what it does: |wcreate rule|n does that.")


NEW_ACTION = menus.Form(
    key="new-action", title="A verb this world knows", guided=True,
    intro="What a verb takes, declared once. Every rule about it is written "
          "against this, so it is settled the first time and not revised.",
    discard="Throw away this action?",
    items=[
        menus.Field("action", "The verb", required=True,
                    help="The word somebody types, in the infinitive: launch, "
                         "combine, temper."),
        menus.Picker("sense", "Which sense", options=verb_sense_options,
                     help="Which meaning of the word. This is what lets the "
                          "world offer a rule about a near relation of it as "
                          "a starting point, so it is worth a moment."),
        menus.Field("means", "What it means", suggestible=True,
                    help="One line, in the infinitive: to send a ship away "
                         "from its berth. Left empty, the sense's own "
                         "definition is used."),
        making.listing_field(
            "applies_to", "What it takes", NEW_ROLE, role_line,
            add_label="Add a part", empty="nothing -- it takes no object",
            most=5,
            help="The nouns the verb takes. A verb that takes nothing is "
                 "fine: shrugging, waiting."),
        menus.Field("despite", "Works even when you cannot", kind=menus.CHOICE,
                    choices=lambda ctx: [menus.Choice(value, label)
                                         for value, label in GATES_SAID],
                    parse=lambda ctx, text: _read_gates(text),
                    show=lambda ctx, value: ", ".join(value or []) or "nothing",
                    help="Almost always nothing, and worth a moment's thought "
                         "when it is not. Name a gate only when this action "
                         "is the very thing that would end such a condition "
                         "-- reviving, struggling. A dead character who can "
                         "still open doors is not dead."),
        menus.Field("must", "What a rule about it must do", kind=menus.CHOICE,
                    choices=_must_choices, parse=lambda ctx, t: _read_must(t),
                    show=lambda ctx, value: _said_must(value),
                    help=MUST_HELP),
        making.keeper("keep", "Declare this action", keep_action,
                      command=lambda ctx: "create action <verb>"),
    ],
)


def _read_gates(text):
    from world import actions

    wanted = [word.strip().lower() for word in str(text or "").split()]
    bad = [word for word in wanted if word and word not in actions.GATES]
    if bad:
        return None, f"{bad[0]} is not one of acting, moving or speaking."
    return [word for word in wanted if word], ""


def action_entries(root):
    from world import actions

    found = []
    # `actions.vocabulary` answers a sorted list of verbs, the way
    # `kinds.vocabulary` answers a list of kinds; each record is read through
    # `spec`. The two registers that answer a list and the four that answer a
    # map is a difference worth knowing once rather than being caught by.
    for verb in actions.vocabulary(root):
        record = actions.spec(root, verb) or {}
        takes = ", ".join(r["role"] for r in record.get("applies_to") or [])
        found.append((verb, f"{verb} -- takes {takes or 'nothing'}",
                      record.get("means") or ""))

    return found


def action_text(root, verb):
    from commands.rules_subject import one_verb
    from world import verbs

    verb = verbs.canonical_verb(str(verb or "").strip().lower())
    return one_verb(root, verb)


def edit_action(root, verb):
    """Only the line that says what it means. See docs/player-building.md 6.4."""
    from world import actions, verbs

    verb = verbs.canonical_verb(str(verb or "").strip().lower())
    if actions.spec(root, verb) is None:
        return None

    def set_means(ctx, value):
        store = dict(getattr(root.db, actions.ATTR, None) or {})
        record = dict(store.get(verb) or {})
        record["means"] = str(value or "")
        store[verb] = record
        setattr(root.db, actions.ATTR, store)
        return f"{verb}: {value}"

    def set_must(ctx, value):
        # Changed on a verb already in use, deliberately. What it takes is
        # what existing rules were written against and is not touched here;
        # this is a condition on rules not yet written, and a world wants it
        # exactly when it has just read one that did nothing.
        now = actions.set_must(root, verb, value)
        return f"{verb} must {_said_must(now)}."

    return menus.Form(
        key=f"edit-action-{verb}", title=f"The action {verb}",
        intro=lambda ctx: action_text(root, verb) + (
            "\n\n|xWhat it takes is what every rule about it was written "
            f"against, so it is not changed here. |wreset verb {verb}|n "
            "forgets it outright; its rules are untouched.|n"),
        items=[
            menus.Field(
                "means", "What it means", suggestible=True,
                get=lambda ctx: (actions.spec(root, verb) or {}).get("means"),
                set=set_means),
            menus.Field(
                "must", "What a rule about it must do", kind=menus.CHOICE,
                choices=_must_choices, parse=lambda ctx, t: _read_must(t),
                show=lambda ctx, value: _said_must(value),
                get=lambda ctx: actions.must_of(root, verb),
                set=set_must, help=MUST_HELP),
        ],
    )


MAKERS = [
    making.Maker(
        "action", ("action", "actions"),
        "Verbs this world knows", opens_with="action",
        listing=action_entries, one=action_text,
        new=NEW_ACTION, edit=edit_action,
        make_label="A verb this world knows",
        none="None of these -- declare a new verb",
        help="What a verb takes: which nouns, how near you must be to each. "
             "Declared once, because every rule about it is written against "
             "the answer.",
    ),
]
