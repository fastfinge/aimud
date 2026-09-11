"""
Help for the words a world made up for itself.

Every other help topic in the game was written before the game ran: a command
has a docstring, a file entry is a file. The vocabularies that matter most to a
player are neither. They are registered as the world plays -- the first rule
that needs "burning" invents it, the first character who needs "composure"
registers it, the first bottle anybody makes settles what a bottle is -- and
each is entered with a sentence in plain words, a `means` for a condition or a
figure and a dictionary gloss for a sort of thing, so that the next model to
see it uses it the same way.

`world.vocabulary` keeps four such registers: a **kind** says what something
is, an **affordance** says what can be done to it, a **state** says what is
true of it now, and a **trait** says what is true of somebody by degree. All
four were being shown to models and to nobody else. The player is the one who
has to read "It is burning", or see a check against "composure", or work out
why this world will let them burn a flyer and not a key -- so the same
sentences answer `help burning`, `help composure`, `help flyer` and `help burn`
now.

Which makes these topics unlike any other in one way worth knowing: they are
per world and they grow. Two worlds have different conditions, a new world has
almost none, and a word enters the help the moment the world first needs it. So
they are built for the caller at the moment they ask, out of the registers
belonging to whatever world they are standing in.

Kinds and affordances are kept out of the main `help` index, which is the one
way they differ from the other two. A mature world holds three hundred kinds,
and three hundred nouns at the top of the index would bury the twenty commands
somebody typing `help` was looking for. They are read by name -- `help bottle`
-- and listed on demand, because `help kinds` and `help affordances` are
category searches, and a category lists everything filed under it whether or
not the index does.
"""

from evennia import default_cmds
from evennia.help.filehelp import FileHelpEntry

#: Where these land in `help`'s index. Four categories rather than one, because
#: they answer four different questions -- what a thing is, what can be done to
#: it, what is true of it now, and what is true of a person by degree -- and
#: the index is read by somebody looking for one of them.
#:
#: Lower case, because that is what the file-help loader does to a category and
#: therefore what a category search compares against. An entry filed under
#: "Conditions" is found by name and never by `help conditions`, which is the
#: one way a player would think to ask for the whole list. Evennia title-cases
#: these for display, so nothing is lost by writing them the way it stores them.
KIND_CATEGORY = "kinds"
EFFECT_CATEGORY = "effects"
AFFORDANCE_CATEGORY = "affordances"
STATE_CATEGORY = "conditions"
TRAIT_CATEGORY = "traits"

#: Anyone may read them. They document a world the player is standing in.
OPEN = "view:all();read:all()"

#: Readable by name and listed by category, and kept out of the main index.
#: `view` is what the index checks and `read` is what a search checks, so this
#: is a topic that exists for whoever asks for it and does not crowd whoever
#: did not. See the module docstring for why kinds need it and conditions do
#: not: there are ten times as many of them.
UNLISTED = "view:false();read:all()"

#: How many words a list in an entry will show before it stops being readable.
#: A world can afford to settle two hundred kinds of thing that can be burned;
#: a person reading `help burn` cannot afford to be shown them.
MOST_LISTED = 24


def _entry(key, category, text, aliases=(), locks=OPEN):
    return FileHelpEntry(
        key=key,
        aliases=list(aliases),
        help_category=category,
        entrytext=text.strip(),
        lock_storage=locks,
    )


def _place(topics, key, label, entry):
    """
    File an entry under its word, or under a qualified one if that is taken.

    Two registers can hold the same word -- a world that measures "fire" and
    also has fires in it is well organised rather than confused, and
    `world.vocabulary` allows exactly that -- so the second comer is keyed
    "fire (kind)" and both stay reachable. Whoever gets there first keeps the
    bare word, which is why the order in `world_topics` is the order a player
    is most likely to have meant.
    """
    key = str(key or "").lower().strip()
    if not key:
        return
    if key not in topics:
        topics[key] = entry
        return

    qualified = f"{key} ({label})"
    attempt = 2
    while qualified in topics:
        qualified = f"{key} ({label} {attempt})"
        attempt += 1
    # The search index is built from the entry's own key rather than from where
    # it was filed, so the qualified name has to go on the entry too or nothing
    # would ever find it. The bare word stays on as an alias: it belongs to
    # whoever got there first, but a search for it should at least offer this.
    entry.key = qualified
    if key not in entry.aliases:
        entry.aliases.append(key)
    topics[qualified] = entry


def _listed(words):
    """A run of words to read, cut off before it becomes a wall of them."""
    words = sorted({str(word) for word in words if word})
    if len(words) <= MOST_LISTED:
        return ", ".join(words)
    return ", ".join(words[:MOST_LISTED]) + f", and {len(words) - MOST_LISTED} more"


def _state_text(world_root, slug, entry):
    """What `help burning` says."""
    from world import verbs

    means = (entry.get("means") or "").strip()
    group = verbs.group_of(world_root, slug)
    rules = verbs.group_rules(world_root, group)

    # A condition that ends when its bearer walks away is a way a PERSON is,
    # not a way a thing is -- nothing else carries itself out of a room. That
    # decides how the rest of the entry is written, because people are shown
    # their condition but are deliberately not addressable by it: offering
    # "get seated" would put a person in the running for every search.
    of_a_person = bool(rules.get("ends_on_move"))
    bearer = "somebody" if of_a_person else "something"

    lines = [
        f"|w{slug}|n is a condition {bearer} can be in"
        + (f": {means}." if means else "."),
        "",
    ]
    if of_a_person:
        lines.append(
            "Conditions are how this world tracks what is true of someone "
            "just now, as against what is always true of them. They are "
            "listed under their description when you look at them, and "
            "several can hold at once."
        )
    else:
        lines += [
            "Conditions are not part of a thing's name -- a bottle is a "
            "bottle whether it is full or empty -- so they are listed under "
            "its description when you look at it, and a thing can be several "
            "at once.",
            "",
            f"You can name a thing by one: |wlook {slug}|n, or |wget {slug} "
            f"bottle|n. It stops answering to it as soon as it stops being it.",
        ]

    # What it cancels, said the way it is actually decided. A declared
    # conflict is worth naming -- there are one or two and they are the point.
    # An exclusive group is not: it may hold twenty near-synonyms, and
    # "becoming seated ends crouched, crouching, kneeling, knelt, laid..." is
    # a worse way of saying you can only be in one posture at a time.
    if rules.get("exclusive"):
        lines += ["", f"Only one {group} holds at a time, so becoming {slug} "
                      f"ends whichever you were in before."]
    cancels = {c for c in (entry.get("conflicts") or []) if c}
    if rules.get("exclusive"):
        cancels -= verbs.group_members(world_root, group)
    if cancels:
        lines += ["", f"Becoming {slug} also ends: {', '.join(sorted(cancels))}."]
    if rules.get("ends_on_move"):
        lines += ["", "It ends when you leave the room."]
    return "\n".join(lines)


def _trait_text(caller, slug, entry):
    """What `help composure` says."""
    from world import gear, traits

    means = (entry.get("means") or "").strip()
    name = (entry.get("name") or slug).strip()
    kind = entry.get("trait_type", "counter")
    lines = [
        f"|w{name}|n is something a person can be measured by"
        + (f": {means}." if means else "."),
        "",
        {
            "gauge": "It runs between a floor and a full mark and can be "
                     "filled or drained -- it is the kind of figure that "
                     "empties as it is spent.",
            "counter": "It is a number that goes up and down, with no "
                       "particular ceiling.",
            "static": "It is a fixed figure that does not drift on its own.",
        }.get(kind, "It is a figure kept about a person."),
    ]

    # Their own standing in it, when they have any. The point of asking what a
    # trait means is usually to find out where you stand in it.
    mine = traits.describe(caller, slug)
    if mine:
        lines += ["", f"Yours: {mine}"]

        # And how much of that is not theirs: armour, a weapon in hand, a fire
        # in the room they are standing in. Worth naming because it is the part
        # a player can change today. Asked only of somebody who has the trait,
        # since nothing can be lending a figure that nobody is keeping.
        granted = gear.describe(caller, slug)
        if granted:
            lines += ["", f"Of that, something else is lending you: {granted}. "
                          f"Take it off, put it down or walk away from it and "
                          f"the figure goes back to what you earned."]
    lines += ["", "|wscore|n shows everything you are measured by."]
    return "\n".join(lines)


def _kind_text(world_root, kind, entry):
    """What `help bottle` says."""
    from world import affordances as af, kinds, lexicon

    word = lexicon.word_of(kind) or kind
    gloss = lexicon.definition(kind)
    granted = dict(entry.get("affordances") or {})
    can = sorted(af.afforded(granted))
    cannot = sorted(af.refused(granted))
    takes = [where for where in kinds.PLACEMENT
             if where in {str(p) for p in (entry.get("holds") or [])}]
    been = sorted(str(s) for s in (entry.get("states") or []) if s)

    lines = [
        f"|w{word}|n is a sort of thing this world has in it"
        + (f": {gloss}." if gloss else "."),
        "",
        f"What a sort of thing affords is decided once, by the first "
        f"{word} the world ever makes, and every one after that agrees with "
        f"it. That is what makes a rule worth learning: whatever is worked "
        f"out on one {word} is free on the next, and free on anything else "
        f"that affords the same things.",
    ]
    if can:
        lines += ["", f"What can be done to a {word}: "
                      f"{_listed(can)}."]
    if cannot:
        lines += ["", f"What plainly cannot: {_listed(cannot)}."]
    if not can and not cannot:
        lines += ["", f"Nothing has been settled yet about what can be done "
                      f"to a {word}. Try something, and it will be."]
    if takes:
        where = " and ".join(f"|w{place}|n one" for place in takes)
        lines += ["", f"Things can be put {where}."]
    if been:
        lines += ["", f"Ones in this world have been: {_listed(been)}. "
                      f"|whelp {been[0]}|n says what that means."]
    lines += [
        "",
        "A thing can be two sorts at once -- a sword with runes on the blade "
        "is a sword and an inscription -- and then it affords whatever either "
        "of them does. Nothing can afford less than its sort does; a thing "
        "that cannot do what its sort can is either in a condition that "
        "stops it, or is really another sort.",
    ]
    return "\n".join(lines)


def _affordance_text(verb, yes, no):
    """What `help burn` says."""
    lines = [
        f"|w{verb}|n is something this world knows can be done to a thing.",
        "",
        "Read it the way |wreadable|n reads: it says what can be done TO "
        "something, never what that something does. A lantern affords "
        "|wlight|n because it can be lit, not because it gives light.",
    ]
    if yes:
        lines += ["", f"Sorts of thing that afford it: {_listed(yes)}."]
    if no:
        lines += ["", f"Sorts that plainly do not: {_listed(no)}."]
    lines += [
        "",
        "Anything not named either way has not been decided, which is the "
        "ordinary state of most pairs of verb and thing. Whoever tries it "
        f"first settles it -- once, for that whole sort of thing -- so "
        f"|w{verb} <something>|n is how the question gets answered.",
    ]
    if yes:
        lines += ["", f"|whelp {sorted(yes)[0]}|n says everything that sort "
                      f"affords."]
    return "\n".join(lines)


def _kind_topics(world_root):
    """Every kind this world has settled, as (word, label, entry) triples."""
    from world import kinds, lexicon

    found = []
    for kind in kinds.vocabulary(world_root):
        spec = kinds.spec(world_root, kind) or {}
        word = lexicon.word_of(kind) or kind
        # The synset id is an alias rather than the key: a player types
        # "chest", and "chest.n.02" is what the world wrote down. Both reach
        # the same entry, and the id is also what tells two kinds sharing a
        # word apart when one of them has to be filed under a qualified name.
        found.append((word, kind, _entry(
            word, KIND_CATEGORY, _kind_text(world_root, kind, spec),
            aliases=[kind] if kind != word else [], locks=UNLISTED)))
    return found


def _affordance_topics(world_root):
    """
    Every verb this world's kinds have an opinion about.

    Read out of the kind specs rather than kept anywhere of its own, because
    that is where an affordance lives now: it is a fact about bottles, held
    against the kind. This turns that store inside out to answer the other
    question -- not "what can be done to this" but "what is this done to".
    """
    from world import kinds, lexicon

    yes, no = {}, {}
    for kind in kinds.vocabulary(world_root):
        spec = kinds.spec(world_root, kind) or {}
        word = lexicon.word_of(kind) or kind
        for verb, allowed in dict(spec.get("affordances") or {}).items():
            (yes if allowed else no).setdefault(str(verb), set()).add(word)

    # A verb that is also a command -- `get`, `wear`, `look` -- keeps its
    # command help, because Evennia lets a command win any name clash and that
    # is the right answer: the command is what the player types. The entry is
    # still reachable through `help affordances`.
    return [(verb, "affordance", _entry(
        verb, AFFORDANCE_CATEGORY,
        _affordance_text(verb, yes.get(verb, ()), no.get(verb, ())),
        locks=UNLISTED)) for verb in sorted(set(yes) | set(no))]


def _effect_text(name, entry):
    """What `help set_state` says."""
    lines = [
        f"|w{name}|n is one of the changes a rule can make. It "
        f"{entry['means']}.",
        "",
        (f"Written as: |x{{\"type\": \"{name}\"}}|n, and it takes no other "
         f"fields." if entry["takes"] == "nothing" else
         f"Written as: |x{{\"type\": \"{name}\", ...}}|n, taking "
         f"{entry['takes']}."),
    ]
    if entry.get("answers"):
        lines += [
            "",
            "Its own output is the whole of what you read, so nothing is "
            "written on top of it. That is what lets looking at something "
            "cost nothing at all.",
        ]
    if not entry.get("backwards"):
        lines += [
            "",
            "A character planning ahead cannot use this as a step, because "
            "there is no way to read it backwards into something somebody "
            "could want. That is a decision rather than a gap: nothing is "
            "ever a goal to have been told something, or to have been seen "
            "doing something.",
        ]
    else:
        lines += [
            "",
            "A character planning ahead can use this as a step: it can be "
            "read backwards into the thing somebody would want it for.",
        ]
    lines += ["", "|weffects <verb>|n says which of these a verb will make, "
                  "and |wrules <verb>|n says in what order."]
    return "\n".join(lines)


def effect_topics():
    """
    Every change a rule can make, as (key, label, entry) triples.

    The one set of topics here that is not per world. An effect is the
    engine's vocabulary rather than a world's -- `set_state` means the same
    thing in every world there will ever be -- so these read identically
    wherever somebody is standing, and they are built from
    `world.effects.VOCABULARY` so that adding an effect documents it for
    nothing. That is the same bargain the other four registers strike, with
    the register kept in code because this one is not invented as the game
    runs.
    """
    from world import effects

    return [(name, "effect", _entry(
        name, EFFECT_CATEGORY, _effect_text(name, entry), locks=UNLISTED))
        for name, entry in sorted(effects.VOCABULARY.items())]


def world_topics(caller, world_root=None):
    """
    The help this world has taught itself, as {key: entry}.

    Empty for anyone standing outside an AI world, which is the right answer:
    these words describe a particular world's rules and mean nothing away
    from it.

    Ordered by who should keep a word the registers share. Conditions and
    traits first because a player asking what "burning" or "composure" means
    is asking about the thing in front of them, then kinds, then affordances
    -- which are verbs, and verbs collide with participles least of all.
    """
    if world_root is None:
        room = getattr(caller, "location", None)
        world_root = room.db.world_root if room is not None else None
    if world_root is None:
        return {}

    from world import traits, verbs

    topics = {}
    for slug, entry in (verbs.vocabulary(world_root) or {}).items():
        if not slug:
            continue
        _place(topics, slug, "condition",
               _entry(slug, STATE_CATEGORY,
                      _state_text(world_root, slug, entry)))
    for slug, entry in (traits.vocabulary(world_root) or {}).items():
        if not slug:
            continue
        # A world that registered a trait and a state under one word is
        # telling us something about people; the state entry is about things.
        # Keep both reachable by keying the trait on its own name.
        _place(topics, slug, "trait",
               _entry(slug, TRAIT_CATEGORY, _trait_text(caller, slug, entry)))
    for key, label, entry in _kind_topics(world_root):
        _place(topics, key, label, entry)
    for key, label, entry in _affordance_topics(world_root):
        _place(topics, key, label, entry)
    return topics


class CmdAIHelp(default_cmds.CmdHelp):
    """
    Get help on a command, a topic, or a word this world uses.

    Usage:
      help
      help <topic or command>

    As well as the usual commands and topics, this world keeps its own
    vocabulary, invented as it goes, and every word of it has an entry:

      |wkinds|n         what a thing is -- `help bottle`
      |waffordances|n   what can be done to one -- `help burn`
      |wconditions|n    what is true of one just now -- `help empty`
      |wtraits|n        what a person is measured by -- `help composure`

    Typing the name of a group -- `help kinds` -- lists every word this world
    has put in it, and `score` does the same for the figures kept about you.
    The lists are per world: another world knows other things, and a new one
    knows almost nothing until it has been played in. `help vocabulary` says
    how the four differ.
    """

    def collect_topics(self, caller, mode="list"):
        """
        The usual three sources, with this world's own words folded in.

        They join the file-based entries because that is what they most
        resemble -- text with a key, owned by nobody in the database. Evennia
        lets commands win a name clash and database entries beat file ones, so
        a world that registers a state called "look" cannot bury the command.

        Locks are checked here rather than left to the caller, because the
        superclass checks them before it returns and anything added afterwards
        would have slipped past: `view` for the index and `read` for a search
        is exactly the distinction that keeps three hundred kinds readable
        without putting all three hundred at the top of `help`.
        """
        cmd_topics, db_topics, file_topics = super().collect_topics(caller, mode)
        permitted = self.can_list_topic if mode == "list" else self.can_read_topic
        merged = dict(file_topics)

        # The effect vocabulary first, and outside `world_topics`, because it
        # is the only one of the registers that is not a world's own: it reads
        # the same in Limbo as aboard a ship, and somebody looking up what
        # `set_state` means should not have to be standing anywhere in
        # particular to find out.
        found = dict(world_topics(caller))
        for key, _label, entry in effect_topics():
            _place(found, key, "effect", entry)
        for key, entry in found.items():
            if permitted(entry, caller):
                merged.setdefault(key, entry)
        return cmd_topics, db_topics, merged
