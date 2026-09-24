"""
A world's closed word lists, made by hand: kinds, attributes, conditions, folds.

These four are one module because they are one idea -- the vocabulary a world's
rules are written in -- and because the forms lean on each other: a condition
belongs to a group, a kind hangs beneath another kind, an attribute is refused
a word a condition already holds.

Nothing here stores anything itself. Every form ends by calling the same writer
a generator calls, so a kind somebody typed and a kind a model invented are the
same record, folded the same way, with the same floor applied.

**Grounding is a field, not a store.** A kind's sense and its anchor are asked
here (`lexicon.senses`, `kinds.ANCHOR_RULE`), which is the whole of what
"players can create terms" needed: the place invented vocabulary attaches to
the dictionary already existed and only generators could reach it. See
docs/player-building.md 11.
"""

from world import affordances as af
from world import lexicon, making, menus

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _root(ctx):
    return making.root_of(ctx)


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------

def sense_options(ctx):
    """The senses of the word being defined, for the picker to offer."""
    word = str(ctx.draft.get("word") or "").strip()
    head = lexicon.head_noun(word) or word
    found = [(name, f"{name} -- {gloss}")
             for name, gloss in lexicon.senses(head, pos="n", limit=12)]
    found.append(("", "None of them -- this word is not in the dictionary"))
    return found


def _wants_anchor(ctx):
    """Whether this kind has nothing above it and needs to be told."""
    from world import kinds

    chosen = str(ctx.draft.get("sense") or "").strip()
    if chosen:
        return False
    word = str(ctx.draft.get("word") or "").strip()
    return bool(word) and not lexicon.ancestors(kinds.canonical(word))


ANCHOR_ROOTS = (
    ("device.n.01", "a device -- something made that works"),
    ("container.n.01", "a container -- something that holds things"),
    ("tool.n.01", "a tool -- something used to do a job"),
    ("weapon.n.01", "a weapon"),
    ("clothing.n.01", "clothing -- something worn"),
    ("food.n.01", "food -- something eaten"),
    ("substance.n.01", "a substance -- stuff rather than a thing"),
    ("document.n.01", "a document -- something written"),
    ("structure.n.01", "a structure -- something built and standing"),
    ("vehicle.n.01", "a vehicle -- something ridden or driven"),
)


def anchor_options(ctx):
    """The common roots, plus anything this world already hangs things under."""
    from world import kinds

    found = list(ANCHOR_ROOTS)
    have = {value for value, _label in found}
    root = _root(ctx)
    for kind in kinds.vocabulary(root):
        under = kinds.anchor(root, kind)
        if under and under not in have:
            found.append((under, f"{under} -- what {kind} hangs beneath here"))
            have.add(under)
    return found


#: Verbs worth offering as affordances before a world has invented any of its
#: own. Every one is something done TO a thing, which is the convention
#: `affordances.py` keeps and the one a list has to demonstrate rather than
#: explain: nobody reading "light -- it can be lit" writes "it gives light".
COMMON_AFFORDANCES = (
    ("look", "it can be looked at"), ("get", "it can be picked up"),
    ("open", "it can be opened"), ("close", "it can be shut"),
    ("read", "it can be read"), ("eat", "it can be eaten"),
    ("drink", "it can be drunk"), ("wear", "it can be worn"),
    ("wield", "it can be held in the hand"),
    ("light", "it can be lit"), ("douse", "it can be put out"),
    ("burn", "it can be burned"), ("break", "it can be broken"),
    ("repair", "it can be mended"), ("wash", "it can be washed"),
    ("push", "it can be pushed"), ("pull", "it can be pulled"),
    ("lock", "it can be locked"), ("unlock", "it can be unlocked"),
    ("fill", "it can be filled"), ("empty", "it can be emptied"),
    ("smell", "it can be smelled"), ("hear", "it can be listened to"),
    ("feel", "it can be touched"), ("combine", "it can be combined"),
)


def affordance_options(ctx):
    """Verbs worth offering: this world's actions first, then common English."""
    from world import actions

    root = _root(ctx)
    found, seen = [], set()
    for verb in sorted(actions.vocabulary(root) or {}):
        found.append((verb, f"{verb} -- a verb this world knows"))
        seen.add(verb)
    for verb, said in COMMON_AFFORDANCES:
        if verb not in seen:
            found.append((verb, f"{verb} -- {said}"))
            seen.add(verb)
    return found


def _keep_typed_verb(ctx, text):
    """A verb that is on no list. Folded to one spelling, never refused."""
    verb = af.to_verb(text)
    if not verb:
        raise menus.Refuse(
            f"{text} is not a verb this game can make sense of. Write what "
            f"happens to the thing -- read, burn, open -- and not an "
            f"adjective made out of it.")
    return verb, f"{verb} it is."


TYPED_AFFORDANCE = making.word_form(
    "typed-affordance", "A verb of your own", "The verb",
    _keep_typed_verb,
    intro="Any verb at all. It is folded onto one spelling so that two ways "
          "of writing the same idea do not become two different facts.",
    help="What happens TO the thing, in the infinitive: scry, temper, bless. "
         "Not an adjective made out of it.")


NEW_AFFORDANCE = menus.Form(
    key="new-affordance", title="What can be done to it", guided=True,
    intro="A verb, and whether this sort of thing takes it. `read`, not "
          "`readable`; what happens TO the thing, never what it does.",
    items=[
        making.picker("verb", "The verb", "action", options=affordance_options,
                      make=lambda ctx: TYPED_AFFORDANCE, required=True,
                      none="None of these -- type a verb of your own",
                      help="What somebody would type. Passive throughout: a "
                           "lantern affords light because it can be lit, not "
                           "because it gives light."),
        menus.Field("yes", "Can it be done?", kind=menus.BOOLEAN,
                    required=True, default=True,
                    help="No is worth saying only where this sort of thing is "
                         "a plain exception. Leaving a verb out means nobody "
                         "has decided, which is the ordinary case."),
        making.keeper("keep", "Keep it", lambda ctx: (
            {"verb": str(ctx.draft.get("verb") or "").strip().lower(),
             "yes": bool(ctx.draft.get("yes"))},
            f"{ctx.draft.get('verb')}: "
            f"{'yes' if ctx.draft.get('yes') else 'no'}.")),
    ],
)


def _affordance_line(ctx, entry):
    return f"{entry.get('verb')} -- {'yes' if entry.get('yes') else 'no'}"


HOLDS = (("in", "things go in it"), ("on", "things go on it"),
         ("under", "things go under it"), ("behind", "things go behind it"))


def keep_kind(ctx):
    from world import kinds

    root = _root(ctx)
    word = str(ctx.draft.get("word") or "").strip().lower()
    if not word:
        raise menus.Refuse("A kind needs a word.")
    sense = str(ctx.draft.get("sense") or "").strip()
    named = sense or word
    if kinds.spec(root, kinds.canonical(named)) is not None:
        raise menus.Refuse(
            f"This world already knows |w{kinds.canonical(named)}|n. "
            f"|wview kind {kinds.canonical(named)}|n shows what it affords, "
            f"and |wreset kind|n is how it is changed.")
    declared = {}
    for entry in ctx.draft.get("affordances") or []:
        verb = str(entry.get("verb") or "").strip().lower()
        if verb:
            declared[verb] = bool(entry.get("yes"))
    settled = kinds.remember(root, named, declared,
                             accepts=ctx.draft.get("holds") or (),
                             under=str(ctx.draft.get("under") or ""))
    settled_name = kinds.canonical(named)
    can = sorted(af.afforded(settled))
    return settled_name, (
        f"This world now knows |w{settled_name}|n"
        + (f", which can be {', '.join(can)}." if can
           else ", which affords nothing in particular yet."))


NEW_KIND = menus.Form(
    key="new-kind", title="A sort of thing", guided=True,
    intro="What sort of thing something is, and what that sort can do. Every "
          "object of this kind shares the answer, so it is worth getting right "
          "once.",
    discard="Throw away this kind?",
    items=[
        menus.Field("word", "The word", required=True, suggestible=True,
                    help="The common noun this sort of thing IS, singular and "
                         "lower case: cup, chalkboard, datapad. Not the words "
                         "that only describe one."),
        menus.Picker("sense", "Which sense", options=sense_options,
                     help="Which meaning of the word you mean. A chest with a "
                          "lid and a chest with ribs are different sorts of "
                          "thing, and a rule about one will never find the "
                          "other. Pick the plain one if in doubt."),
        menus.Picker("under", "What sort of thing it is",
                     options=anchor_options,
                     lock=_wants_anchor, none="",
                     help="The dictionary has never heard of this word, so "
                          "nothing sits above it: a rule somebody writes "
                          "about containers will not find your cinderstone. "
                          "Name the nearest real sort of thing it is."),
        making.listing_field(
            "affordances", "What can be done to it", NEW_AFFORDANCE,
            _affordance_line, add_label="Add a verb",
            empty="nothing decided yet",
            help="Affordances are half of what decides which rules apply to "
                 "this sort of thing, so two kinds that afford the same are "
                 "taught by one rule between them."),
        menus.Field("holds", "What it holds", kind=menus.CHOICE,
                    choices=lambda ctx: [
                        menus.Choice(value, label) for value, label in HOLDS],
                    show=lambda ctx, value: ", ".join(value) if value
                    else "nothing",
                    parse=lambda ctx, text: _read_holds(text),
                    help="Whether things can be put in, on, under or behind "
                         "one. Several, separated by spaces."),
        making.keeper("keep", "Keep this kind", keep_kind, after=menus.STAY,
                      command=lambda ctx: "create kind <word>"),
    ],
)


def _read_holds(text):
    wanted = [word.strip().lower() for word in str(text or "").split()]
    known = {value for value, _label in HOLDS}
    bad = [word for word in wanted if word and word not in known]
    if bad:
        return None, f"{bad[0]} is not one of in, on, under or behind."
    return [word for word in wanted if word], ""


def kind_entries(root):
    from world import kinds

    found = []
    # `kinds.vocabulary` answers a sorted list of names, not a map: the specs
    # are read one at a time through `spec`.
    for kind in kinds.vocabulary(root):
        entry = kinds.spec(root, kind) or {}
        can = sorted(af.afforded(entry.get("affordances") or {}))
        found.append((kind, f"{kind} -- {', '.join(can) or 'nothing decided'}"))
    return found


def kind_text(root, kind):
    from world import kinds, rulebooks

    settled = kinds.canonical(str(kind or "").strip())
    entry = kinds.spec(root, settled)
    if entry is None:
        return ""
    can = sorted(af.afforded(entry.get("affordances") or {}))
    cannot = sorted(af.refused(entry.get("affordances") or {}))
    lines = [f"|w{settled}|n"]
    under = kinds.anchor(root, settled)
    if under:
        lines.append(f"  hangs beneath |w{under}|n")
    above = sorted(lexicon.ancestors(under or settled))
    if above:
        lines.append(f"  |xa sort of: {', '.join(above[-6:])}|n")
    lines.append(f"  can be {', '.join(can) or 'nothing in particular'}")
    if cannot:
        lines.append(f"  cannot be {', '.join(cannot)}")
    if entry.get("holds"):
        lines.append(f"  things go {'/'.join(entry['holds'])} it")
    # What depends on it, which is what makes `reset kind` answerable.
    filed = [r for r in rulebooks.all_rules(root)
             if (r.get("scope") or {}).get("kind") == settled]
    using = _objects_of(root, settled)
    lines.append(f"  |x{len(using)} thing{'' if len(using) == 1 else 's'} in "
                 f"this world {'is' if len(using) == 1 else 'are'} one; "
                 f"{len(filed)} rule{'' if len(filed) == 1 else 's'} filed "
                 f"against it|n")
    return "\n".join(lines)


def _objects_of(root, kind):
    """
    Everything in this world that is of a sort. Rooms, and what is in them.

    The `ai_world` tag is on **rooms** -- `worldgen._create_room` puts it
    there -- so a search by tag alone finds the places and none of the things
    in them, which is the wrong half for a question about kinds. Walked
    through the rooms instead, contents and all, so a lantern in a chest on a
    shelf is counted with the rest.
    """
    from evennia import search_tag
    from world import kinds as kinds_mod

    if root is None:
        return []
    found, seen = [], set()

    def walk(obj):
        if obj.id in seen:
            return
        seen.add(obj.id)
        try:
            if kind in kinds_mod.of(obj):
                found.append(obj)
        except Exception:
            pass
        for inside in (getattr(obj, "contents", None) or []):
            walk(inside)

    for room in search_tag(str(root.id), category="ai_world"):
        walk(room)
    # A world whose rooms were never tagged -- a fixture, a world built before
    # the tag existed -- still answers for the room somebody is standing in.
    if not seen and root is not None:
        walk(root)
    return found


def reset_kind_question(root, kind):
    """
    What forgetting a kind costs, said before it is done.

    The whole of why this is a separate gesture rather than an `edit`: what a
    kind affords is half of every verb rule's cache key, so every rule this
    world has learned about that sort of thing was filed against the answer
    being forgotten. `view kind` says the same thing, so the question can be
    answered before it is asked.
    """
    from world import kinds, rulebooks

    settled = kinds.canonical(str(kind or "").strip())
    using = _objects_of(root, settled)
    filed = [r for r in rulebooks.all_rules(root)
             if (r.get("scope") or {}).get("kind") == settled]
    said = [f"Forget what this world settled about |w{settled}|n?"]
    if using:
        said.append(f"{len(using)} thing{'' if len(using) == 1 else 's'} here "
                    f"{'is' if len(using) == 1 else 'are'} one, and what "
                    f"{'it affords' if len(using) == 1 else 'they afford'} "
                    f"will be decided afresh.")
    if filed:
        said.append(f"{len(filed)} rule{'' if len(filed) == 1 else 's'} filed "
                    f"against it {'is' if len(filed) == 1 else 'are'} left "
                    f"exactly as {'it is' if len(filed) == 1 else 'they are'}.")
    return " ".join(said)


def reset_kind(root, kind):
    """
    Drop what a kind was settled as, so the next thing of it decides again.

    Beside `reset verb`, and for the same reason and with the same manners:
    the rules are untouched, the narrations written about things of this sort
    are dropped because they were written about what it used to afford, and
    what it does is said out loud rather than implied.
    """
    from world import effects, kinds

    settled = kinds.canonical(str(kind or "").strip())
    store = dict(getattr(root.db, kinds.ATTR, None) or {})
    if settled not in store:
        return f"This world has settled nothing about |w{settled}|n."
    using = _objects_of(root, settled)
    store.pop(settled)
    setattr(root.db, kinds.ATTR, store)
    for obj in using:
        effects.forget_narrations(obj)
    return (f"|w{settled}|n is forgotten. The next thing of that sort settles "
            f"it afresh.\n"
            f"|xIts rules are untouched -- |wview rules|n shows them -- and "
            f"the {len(using)} thing{'' if len(using) == 1 else 's'} of that "
            f"sort here will be described again when anybody looks.|n")


def edit_kind(root, kind):
    """Only what no cache key and no rule reads. See docs 6.4."""
    from world import kinds

    settled = kinds.canonical(str(kind or "").strip())
    if kinds.spec(root, settled) is None:
        return None

    def set_holds(ctx, value):
        store = dict(getattr(root.db, kinds.ATTR, None) or {})
        entry = dict(store.get(settled) or {})
        entry["holds"] = sorted(set(value or []))
        store[settled] = entry
        setattr(root.db, kinds.ATTR, entry and store)
        return f"Things now go {'/'.join(entry['holds']) or 'nowhere'} it."

    return menus.Form(
        key=f"edit-kind-{settled}", title=f"The kind {settled}",
        intro=lambda ctx: kind_text(root, settled) + (
            "\n\n|xWhat it affords is a cache key: every rule this world has "
            "learned is filed against it, so it is not changed here. "
            f"|wreset kind {settled}|n forgets it outright, and says what "
            "that costs first.|n"),
        items=[
            menus.Field("holds", "What it holds", kind=menus.CHOICE,
                        get=lambda ctx: (kinds.spec(root, settled)
                                         or {}).get("holds") or [],
                        set=set_holds,
                        parse=lambda ctx, text: _read_holds(text),
                        show=lambda ctx, value: "/".join(value or [])
                        or "nothing",
                        help="Whether things can be put in, on, under or "
                             "behind one. Several, separated by spaces."),
        ],
    )


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------

TRAIT_KINDS = (
    ("counter", "a counter -- moves up and down from a base: skills, tallies"),
    ("gauge", "a gauge -- depletes and refills to a maximum: health, fuel"),
    ("static", "a fixed figure only deliberate change moves"),
)


def keep_attribute(ctx):
    from world import traits

    root = _root(ctx)
    slug = str(ctx.draft.get("slug") or "").strip()
    if not slug:
        raise menus.Refuse("An attribute needs a word.")
    properties = {}
    for field in ("base", "min", "max", "rate"):
        if ctx.draft.get(field) is not None:
            properties[field] = ctx.draft[field]
    used = traits.register(
        root, slug, name=str(ctx.draft.get("name") or ""),
        means=str(ctx.draft.get("means") or ""),
        trait_type=str(ctx.draft.get("trait_type") or "counter"),
        **properties)
    if not used:
        raise menus.Refuse(
            f"|w{slug}|n could not be kept. This world already uses that word "
            f"for a condition, and a word cannot be both -- both say what is "
            f"true of a thing now, and two answers to one question is no "
            f"answer. |wview conditions|n shows what it holds.")
    if used != slug:
        return used, (f"This world already keeps |w{used}|n, which is the same "
                      f"figure. Nothing new was made.")
    return used, f"This world now keeps the attribute |w{used}|n."


NEW_ATTRIBUTE = menus.Form(
    key="new-attribute", title="Something measurable about a person",
    guided=True,
    intro="A figure kept about a character: stamina, standing, fuel. A rule "
          "can require one, an effect can move one, and a quest can ask for "
          "one.",
    discard="Throw away this attribute?",
    items=[
        menus.Field("slug", "The word", required=True, suggestible=True,
                    help="One lower-case word, as a rule will name it: "
                         "stamina, standing, discoveries."),
        menus.Field("name", "What it is called", suggestible=True,
                    help="How it reads on a character sheet. Left empty, the "
                         "word itself is used."),
        menus.Field("means", "What it is for", suggestible=True,
                    help="One line, so the next model to see the register "
                         "uses it the same way."),
        menus.Field("trait_type", "How it behaves", kind=menus.CHOICE,
                    required=True,
                    choices=lambda ctx: [menus.Choice(value, label)
                                         for value, label in TRAIT_KINDS],
                    help="A gauge has a current value that falls and refills; "
                         "a counter simply moves; a static figure stays put."),
        menus.Field("base", "Where it starts", kind=menus.NUMBER,
                    help="What every character has of it before anything "
                         "changes it."),
        menus.Field("min", "Lowest it goes", kind=menus.NUMBER),
        menus.Field("max", "Highest it goes", kind=menus.NUMBER),
        menus.Field("rate", "Drift a second", kind=menus.NUMBER,
                    help="How much it moves on its own, every second. A "
                         "poison drains and a rest restores. Leave it empty "
                         "for a figure that only changes when something "
                         "changes it."),
        making.keeper("keep", "Keep this attribute", keep_attribute,
                      after=menus.STAY,
                      command=lambda ctx: "create attribute <word>"),
    ],
)


def attribute_entries(root):
    from world import traits

    found = []
    for slug, entry in sorted((traits.vocabulary(root) or {}).items()):
        found.append((slug, f"{slug} -- {entry.get('means') or entry.get('name')}",
                      f"a {entry.get('trait_type', 'counter')}"))
    return found


def attribute_text(root, slug):
    from world import traits

    slug = traits.resolve(root, str(slug or "").strip())
    entry = traits.known(root, slug)
    if not entry:
        return ""
    lines = [f"|w{slug}|n -- {entry.get('name')}",
             f"  {entry.get('means') or 'nothing written about it'}",
             f"  a {entry.get('trait_type', 'counter')}"]
    for field, said in (("base", "starts at"), ("min", "lowest"),
                        ("max", "highest"), ("rate", "drifts by")):
        if entry.get(field) is not None:
            lines.append(f"  {said} {entry[field]}")
    return "\n".join(lines)


def edit_attribute(root, slug):
    from world import traits

    slug = traits.resolve(root, str(slug or "").strip())
    if not traits.known(root, slug):
        return None

    def writer(field):
        def write(ctx, value):
            vocab = dict(root.db.trait_vocabulary or {})
            entry = dict(vocab.get(slug) or {})
            if value in (None, ""):
                entry.pop(field, None)
            else:
                entry[field] = value
            vocab[slug] = entry
            root.db.trait_vocabulary = vocab
            return f"{slug}: {field} is now {value if value else 'unset'}."

        return write

    def reader(field):
        return lambda ctx: (traits.known(root, slug) or {}).get(field)

    return menus.Form(
        key=f"edit-attribute-{slug}", title=f"The attribute {slug}",
        intro=lambda ctx: attribute_text(root, slug),
        items=[
            menus.Field("name", "What it is called", get=reader("name"),
                        set=writer("name")),
            menus.Field("means", "What it is for", get=reader("means"),
                        set=writer("means"), suggestible=True),
            menus.Field("base", "Where it starts", kind=menus.NUMBER,
                        get=reader("base"), set=writer("base")),
            menus.Field("min", "Lowest it goes", kind=menus.NUMBER,
                        get=reader("min"), set=writer("min")),
            menus.Field("max", "Highest it goes", kind=menus.NUMBER,
                        get=reader("max"), set=writer("max")),
            menus.Field("rate", "Drift a second", kind=menus.NUMBER,
                        get=reader("rate"), set=writer("rate")),
        ],
    )


# ---------------------------------------------------------------------------
# Conditions: states, and the groups they belong to
# ---------------------------------------------------------------------------

def group_options(ctx):
    from world import verbs

    found = []
    for name, rules in sorted((verbs.groups(_root(ctx)) or {}).items()):
        note = "exclusive" if rules.get("exclusive") else "several at once"
        found.append((name, f"{name} -- {note}"))
    return found


def keep_group(ctx):
    from world import verbs

    root = _root(ctx)
    name = str(ctx.draft.get("group") or "").strip().lower()
    if not name:
        raise menus.Refuse("A group needs a name.")
    used = verbs.register_group(
        root, name,
        exclusive=bool(ctx.draft.get("exclusive")),
        ends_on_move=bool(ctx.draft.get("ends_on_move")),
        prevents_acting=bool(ctx.draft.get("prevents_acting")),
        prevents_moving=bool(ctx.draft.get("prevents_moving")),
        prevents_speaking=bool(ctx.draft.get("prevents_speaking")))
    if not used:
        raise menus.Refuse(f"|w{name}|n could not be kept.")
    return used, f"This world now keeps the group |w{used}|n."


NEW_GROUP = menus.Form(
    key="new-group", title="A group of conditions", guided=True,
    intro="Conditions that answer one question about a thing: open and shut, "
          "lit and dark, wet and dry. A group is what makes wetting a burning "
          "thing put it out.",
    items=[
        menus.Field("group", "What the group is called", required=True,
                    suggestible=True,
                    help="One lower-case word for the question they answer: "
                         "openness, wetness, lightness."),
        menus.Field("exclusive", "Only one at a time?", kind=menus.BOOLEAN,
                    required=True, default=True,
                    help="Yes for open and shut, which cannot both hold. No "
                         "for a group whose members sit happily together."),
        menus.Field("ends_on_move", "Does moving end it?", kind=menus.BOOLEAN,
                    help="Yes for something true only while you stand still: "
                         "hiding, sitting."),
        menus.Field("prevents_acting", "Stops you acting?", kind=menus.BOOLEAN),
        menus.Field("prevents_moving", "Stops you moving?", kind=menus.BOOLEAN),
        menus.Field("prevents_speaking", "Stops you speaking?",
                    kind=menus.BOOLEAN),
        making.keeper("keep", "Keep this group", keep_group, after=menus.STAY),
    ],
)


def _group_members(ctx):
    """The other conditions in the chosen group, to conflict with."""
    from world import verbs

    root = _root(ctx)
    group = str(ctx.draft.get("group") or "").strip()
    if not group:
        return []
    found = []
    for slug, entry in sorted((verbs.vocabulary(root) or {}).items()):
        if entry.get("group") == group:
            found.append((slug, f"{slug} -- {entry.get('means') or ''}"))
    return found


def keep_condition(ctx):
    from world import verbs

    root = _root(ctx)
    slug = str(ctx.draft.get("slug") or "").strip().lower()
    if not slug:
        raise menus.Refuse("A condition needs a word.")
    group = str(ctx.draft.get("group") or "").strip() or None
    used = verbs.register_state(
        root, slug, means=str(ctx.draft.get("means") or ""),
        group=group,
        ends_on_move=ctx.draft.get("ends_on_move"),
        prevents_acting=ctx.draft.get("prevents_acting"),
        prevents_moving=ctx.draft.get("prevents_moving"),
        prevents_speaking=ctx.draft.get("prevents_speaking"),
        when=ctx.draft.get("when") or None)
    if not used:
        raise menus.Refuse(
            f"|w{slug}|n could not be kept. This world already uses that word "
            f"for an attribute, and a word cannot be both.")
    if used != slug:
        return used, (f"This world already keeps |w{used}|n, which is the same "
                      f"condition. Nothing new was made.")
    return used, f"This world now keeps the condition |w{used}|n."


def _new_condition_items(ctx):
    from world.makers import rules as rule_forms

    items = [
        menus.Field("slug", "The word", required=True, suggestible=True,
                    help="One lower-case word, as a rule will name it: lit, "
                         "shut, brewed. A participle usually reads best."),
        menus.Field("means", "What it means", suggestible=True,
                    help="One line saying what is true of a thing in it."),
        making.picker("group", "Which group", "group",
                      options=group_options, make=lambda ctx: NEW_GROUP,
                      none="None of these -- make a new group",
                      help="The question this condition answers: openness, "
                           "wetness, lightness. A group is what lets one "
                           "condition put another out, so a world with none "
                           "has a lamp that lights and never goes dark."),
        menus.Field("ends_on_move", "Does moving end it?", kind=menus.BOOLEAN),
        menus.Field("prevents_acting", "Stops you acting?",
                    kind=menus.BOOLEAN),
        menus.Field("prevents_moving", "Stops you moving?",
                    kind=menus.BOOLEAN),
        menus.Field("prevents_speaking", "Stops you speaking?",
                    kind=menus.BOOLEAN),
        making.listing_field(
            "when", "Or worked out from", rule_forms.NEW_CONDITION,
            rule_forms.condition_line, add_label="Add a condition",
            empty="not worked out -- it is written on a thing",
            help="A condition given these is never written on anything: it is "
                 "worked out whenever anybody asks. Starving is hunger at ten "
                 "or less, defined once."),
        making.keeper("keep", "Keep this condition", keep_condition,
                      after=menus.STAY,
                      command=lambda ctx: "create condition <word>"),
    ]
    return items


NEW_CONDITION_STATE = menus.Form(
    key="new-condition", title="A condition something can be in", guided=True,
    intro="What is true of a thing right now: lit, shut, wet, brewed. Either "
          "so or not -- a figure with a number is an attribute.",
    discard="Throw away this condition?",
    items=_new_condition_items,
)


def condition_entries(root):
    from world import verbs

    found = []
    for slug, entry in sorted((verbs.vocabulary(root) or {}).items()):
        group = entry.get("group")
        note = entry.get("means") or ""
        found.append((slug, f"{slug} -- {note}" if note else slug,
                      f"in the group {group}" if group else ""))
    return found


def condition_text(root, slug):
    from world import verbs

    slug = str(slug or "").strip().lower()
    entry = (verbs.vocabulary(root) or {}).get(slug)
    if entry is None:
        return ""
    lines = [f"|w{slug}|n -- {entry.get('means') or 'nothing written about it'}"]
    if entry.get("group"):
        rules = verbs.group_rules(root, entry["group"])
        note = "only one at a time" if rules.get("exclusive") else "several at once"
        lines.append(f"  in the group |w{entry['group']}|n ({note})")
    if entry.get("conflicts"):
        lines.append(f"  cannot hold with {', '.join(entry['conflicts'])}")
    if entry.get("when"):
        from world import conditions

        said = [conditions.describe(one, mood="abstract")
                for one in entry["when"]]
        lines.append(f"  worked out: {', and '.join(said)}")
    return "\n".join(lines)


def edit_condition(root, slug):
    from world import verbs

    slug = str(slug or "").strip().lower()
    if slug not in (verbs.vocabulary(root) or {}):
        return None

    def set_means(ctx, value):
        vocab = dict(root.db.state_vocabulary or {})
        entry = dict(vocab.get(slug) or {})
        entry["means"] = str(value or "")
        vocab[slug] = entry
        root.db.state_vocabulary = vocab
        return f"{slug}: {value}"

    return menus.Form(
        key=f"edit-condition-{slug}", title=f"The condition {slug}",
        intro=lambda ctx: condition_text(root, slug),
        items=[menus.Field(
            "means", "What it means", suggestible=True,
            get=lambda ctx: (verbs.vocabulary(root) or {}).get(
                slug, {}).get("means"),
            set=set_means)],
    )


def group_entries(root):
    from world import verbs

    found = []
    for name, rules in sorted((verbs.groups(root) or {}).items()):
        said = ["only one at a time" if rules.get("exclusive")
                else "several at once"]
        for flag, words in (("ends_on_move", "moving ends it"),
                            ("prevents_acting", "stops you acting"),
                            ("prevents_moving", "stops you moving"),
                            ("prevents_speaking", "stops you speaking")):
            if rules.get(flag):
                said.append(words)
        found.append((name, f"{name} -- {', '.join(said)}"))
    return found


def group_text(root, name):
    from world import verbs

    name = str(name or "").strip().lower()
    rules = (verbs.groups(root) or {}).get(name)
    if rules is None:
        return ""
    members = [slug for slug, entry in (verbs.vocabulary(root) or {}).items()
               if entry.get("group") == name]
    lines = [f"|w{name}|n",
             "  only one at a time" if rules.get("exclusive")
             else "  several may hold at once"]
    if members:
        lines.append(f"  holds: {', '.join(sorted(members))}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Word folds: another spelling for something this world already knows
# ---------------------------------------------------------------------------

def fold_options(ctx):
    """What a spelling may be folded onto: this world's verbs and kinds."""
    from world import actions, kinds

    root = _root(ctx)
    found = [(verb, f"{verb} -- a verb") for verb
             in sorted(actions.vocabulary(root) or {})]
    found += [(kind, f"{kind} -- a sort of thing")
              for kind in kinds.vocabulary(root)]
    return found


def keep_fold(ctx):
    from world import folds

    root = _root(ctx)
    word = str(ctx.draft.get("word") or "").strip().lower()
    means = str(ctx.draft.get("means") or "").strip()
    said = folds.add(root, word, means)
    if not said.startswith("This world"):
        raise menus.Refuse(said)
    return word, said


NEW_FOLD = menus.Form(
    key="new-fold", title="Another word for something", guided=True,
    intro="Teaches this world that one word means another: that a blaster is "
          "a raygun, that forging is making. The parser then finds it, and "
          "nothing else has to change.",
    discard="Throw away this word?",
    items=[
        menus.Field("word", "The word", required=True,
                    help="What somebody might type: blaster, zapper, forge."),
        menus.Picker("means", "What it means", options=fold_options,
                     required=True,
                     help="Something this world already knows: one of its "
                          "verbs, or one of its sorts of thing. Which "
                          "register it is in decides what the fold does."),
        making.keeper("keep", "Keep this word", keep_fold, after=menus.STAY,
                      command=lambda ctx: "create word <word>"),
    ],
)


def fold_entries(root):
    from world import folds

    return [(word, f"{word} means {means}")
            for word, means in sorted(folds.all_folds(root).items())]


def fold_text(root, word):
    from world import folds

    word = str(word or "").strip().lower()
    means = folds.all_folds(root).get(word)
    if not means:
        return ""
    return f"|w{word}|n means |w{means}|n here."


def remove_fold(root, word):
    from world import folds

    return folds.remove(root, str(word or "").strip().lower())


# ---------------------------------------------------------------------------
# The makers
# ---------------------------------------------------------------------------

MAKERS = [
    making.Maker(
        "kind", ("kind", "kinds", "sort", "sorts"),
        "Sorts of thing", opens_with="word",
        listing=kind_entries, one=kind_text,
        new=NEW_KIND, edit=edit_kind, reset=reset_kind,
        reset_question=reset_kind_question,
        make_label="A sort of thing",
        none="None of these -- describe a new sort of thing",
        help="What sort of thing something is, and what that sort can do. "
             "Every object of a kind shares one answer, so a rule written "
             "about the kind reaches all of them.",
    ),
    making.Maker(
        "attribute", ("attribute", "attributes"),
        "Figures kept about people", opens_with="slug",
        listing=attribute_entries,
        one=attribute_text, new=NEW_ATTRIBUTE, edit=edit_attribute,
        make_label="Something measurable about a person",
        help="A number kept about a character: stamina, standing, fuel. "
             "Rules can require one and effects can move one.",
    ),
    making.Maker(
        "condition", ("condition", "conditions", "state", "states"),
        "Conditions things can be in", opens_with="slug",
        listing=condition_entries,
        one=condition_text, new=NEW_CONDITION_STATE, edit=edit_condition,
        make_label="A condition something can be in",
        help="What is true of a thing right now: lit, shut, wet. Either so "
             "or not.",
    ),
    making.Maker(
        "group", ("group", "groups"),
        "Groups of conditions", opens_with="group",
        listing=group_entries, one=group_text,
        new=NEW_GROUP,
        make_label="A group of conditions",
        help="Conditions that answer one question about a thing, so that one "
             "can put another out.",
    ),
    making.Maker(
        "word", ("word", "words", "synonym", "synonyms"),
        "Other words for things", opens_with="word",
        listing=fold_entries, one=fold_text,
        new=NEW_FOLD, remove=remove_fold,
        make_label="Another word for something",
        help="Teaches this world that one spelling means another, so the "
             "parser finds an invented word.",
    ),
]


# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------
#
# Word lists and pronoun sets were the first two things `create` ever reached
# that were not a world, and they were each written out by hand: a Subject, a
# Use per verb, a listing, a form, a deletion. Ported onto the table so there
# is one way of adding something a player can make rather than two -- and
# because the table had to prove it can carry a subject it did not shape.
#
# Three things were missing to do it, and all three are general rather than
# concessions: a command line that fills more than one field (`Maker.opens`),
# an entry in a view menu that is about the register rather than any one thing
# in it (`extras`), and a maker anybody standing here may use (`owner`).


def tokens_listing(root):
    from world import token_lists

    kept = token_lists.vocabulary(root)
    if not kept:
        return "This world keeps no word lists yet. |wcreate tokens|n makes one."
    lines = ["Word lists this world keeps:", ""]
    for name, entry in sorted(kept.items()):
        lines.append(f"  |w{{{name}}}|n -- {token_lists.spelled(entry)} -- "
                     f"{entry.get('means', '')}")
    return "\n".join(lines)


def token_entries(root):
    from world import token_lists

    found = []
    for name, entry in sorted((token_lists.vocabulary(root) or {}).items()):
        found.append((name, f"{{{name}}} -- {token_lists.spelled(entry)}",
                      entry.get("means", "")))
    return found


def token_list(root, name):
    from world import token_lists

    name = str(name or "").strip()
    entry = token_lists.get(root, name)
    if entry is None:
        return f"This world keeps no list called |w{name}|n."
    lines = [f"|w{{{name.lower()}}}|n -- {entry.get('means', '')}",
             f"Kept: {entry.get('scope')}"
             + (f", as a condition in the group |w{entry['group']}|n"
                if entry.get("group") else ""), ""]
    for item in entry["entries"]:
        weight = item.get("weight", 1)
        sets = (item.get("sets") or {}).get("states") or []
        lines.append(f"  {item['text']}"
                     + (f"  (weight {weight:g})" if weight != 1 else "")
                     + (f"  sets {', '.join(sets)}" if sets else ""))
    return "\n".join(lines)


def one_token_list(root, name):
    """
    One list, or what some text comes to.

    `view tokens try <text>` is a question about the register rather than
    about any one list in it, and the view menu offers it as its own entry.
    The command line has spelled it this way since word lists existed, so it
    is answered here rather than taken away.
    """
    said = str(name or "").strip()
    if said.lower() == "try" or said.lower().startswith("try "):
        return try_text(None, root, said[3:])
    return token_list(root, said)


def try_text(caller, root, text):
    from world import tokens

    if not str(text or "").strip():
        return "Try what? |wview tokens try It smells of {smell}.|n"
    shown = tokens.text(text, tokens.Context(viewer=caller, world_root=root,
                                             purpose="display"))
    return f"That comes to: {shown}"


TRY_TOKENS = menus.Form(
    key="try-tokens", title="Try some text",
    items=[menus.Field(
        "text", "Text to try",
        get=lambda ctx: None,
        set=lambda ctx, value: try_text(making.caller_of(ctx), _root(ctx),
                                        value or ""),
        prompt="Type some text with a list in braces, like It smells of {smell}",
        help="Shows what a piece of text comes to for you, here, with each "
             "list in braces replaced by one of its entries.")],
)


def token_extras(ctx):
    return [menus.Submenu("try", "Try some text", TRY_TOKENS,
                          command=lambda ctx: "view tokens try <text>")]


def add_list(root, name, means, entries):
    from world import token_lists

    name = str(name or "").strip().lower()
    if not name or not entries:
        return ("A word list needs a name and at least one entry: "
                "|wcreate tokens smell = brine | tar|n.")
    used = token_lists.register(root, name, {
        "means": str(means or "").strip() or f"a word list called {name}",
        "entries": entries,
    })
    if not used:
        return (f"|w{name}|n could not be kept. A list needs a name nothing "
                f"else here uses, and entries that finish.")
    if used != name:
        return (f"This world already keeps |w{used}|n, which is the same list. "
                f"Nothing changed.")
    return f"This world now keeps |w{{{used}}}|n."


def _split_entries(text):
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


def _world_context(ctx):
    """What a model filling in a word list should know about the world."""
    from world import lore

    root = _root(ctx)
    if root is None:
        return ""
    return (f"The world is {lore.title(root)}: "
            f"{(root.db.world_description or '').strip()}")


def _sponsor(ctx):
    from world import sponsor

    return sponsor.of(making.caller_of(ctx))


def keep_tokens(ctx):
    name = str(ctx.draft.get("name") or "")
    said = add_list(_root(ctx), name, ctx.draft.get("means") or "",
                    _split_entries(ctx.draft.get("entries")))
    if not said.startswith("This world now keeps"):
        raise menus.Refuse(said)
    return name.strip().lower(), said


def opening_tokens(said):
    """
    `create tokens smell: what it is for = brine | tar`, as a draft.

    Three fields out of one line, which is why a maker may name a function
    here rather than one field. The line is what it always was; only where it
    is read has moved.
    """
    left, sep, right = str(said or "").partition("=")
    name, _colon, means = left.partition(":")
    draft = {"name": name.strip()}
    if means.strip():
        draft["means"] = means.strip()
    if sep and right.strip():
        draft["entries"] = right.strip()
    return draft


NEW_TOKENS = menus.Form(
    key="new-tokens", title="A new word list",
    intro="A description that says {name} has one entry of the list chosen "
          "for it, and keeps that choice.",
    discard="Throw away this word list?",
    sponsor=_sponsor,
    context=_world_context,
    items=[
        menus.Field("name", "Name", required=True, suggestible=True,
                    help="What descriptions write in braces: smell for {smell}. "
                         "One lower-case word."),
        menus.Field("means", "What it is for", suggestible=True,
                    help="One line saying what the list is for, so the next "
                         "model to see it uses it the same way."),
        menus.Field("entries", "Entries", required=True, suggestible=True,
                    prompt="Type the entries separated by a bar, like brine | "
                           "tar | fish",
                    help="The words or phrases the list chooses between."),
        making.keeper("keep", "Keep this list", keep_tokens,
                      after=menus.CLOSE,
                      command=lambda ctx: "create tokens <list> = <entry> | "
                                          "<entry>"),
    ],
)


def remove_list(root, name):
    from world import token_lists

    said = str(name or "").strip()
    removed, complaint = token_lists.unregister(root, said)
    return f"|w{said}|n is gone." if removed else complaint


def _delete_tokens_question(root, name):
    return f"Delete the word list {name}? Descriptions that use it lose it."


# ---------------------------------------------------------------------------
# Pronoun sets
# ---------------------------------------------------------------------------

def pronoun_entries(root):
    from world import pronouns

    found = []
    for name in sorted(pronouns.vocabulary(root) or {}):
        entry = pronouns.get(root, name)
        found.append((name, pronouns.spelled(entry) if entry else name))
    return found


def pronoun_text(root, name):
    from world import pronouns

    entry = pronouns.get(root, str(name or "").strip())
    if entry is None:
        return ""
    return (f"|w{pronouns.spelled(entry)}|n -- {entry.get('means', '')}\n"
            f"  |wpronouns {name}|n goes by it.")


def _new_pronouns():
    from commands.pronoun_cmds import NEW_SET

    return NEW_SET


MAKERS += [
    making.Maker(
        "tokens", ("tokens", "token", "wordlists", "wordlist"),
        "Word lists", opens=opening_tokens,
        listing=token_entries, one=one_token_list, extras=token_extras,
        new=NEW_TOKENS, remove=remove_list,
        delete_question=_delete_tokens_question,
        make_label="A word list",
        none="None of these -- make a new word list",
        help="The word lists this world keeps. A description that writes "
             "{smell} has one entry of the list chosen for it, and keeps that "
             "choice, so twenty rooms written from one description differ.",
    ),
    making.Maker(
        "pronouns", ("pronouns", "pronoun"),
        "Pronoun sets", listing=pronoun_entries, one=pronoun_text,
        new=_new_pronouns(), opens_with="subject",
        # Anybody standing here, not only whoever made the world: how somebody
        # is spoken about is a fact about them rather than about the world, and
        # a guest refused one would be the world deciding it for them. See
        # `Maker.owner`.
        owner=False,
        make_label="A pronoun set this world does not have",
        help="Walks through the five forms and the verb after them. The set "
             "is then there for everybody here, and you go by it.",
    ),
]
