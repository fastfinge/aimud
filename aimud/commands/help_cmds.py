"""
Help for the words a world made up for itself.

Every other help topic in the game was written before the game ran: a command
has a docstring, a file entry is a file. The two vocabularies that matter most
to a player are neither. States and traits are registered as the world plays
-- the first rule that needs "burning" invents it, the first character who
needs "composure" registers it -- and each is entered with a `means` written
in plain words so the next model to see it uses it the same way.

That sentence exists already, for every state and trait in the world, and it
was being shown to models and to nobody else. The player is the one who has to
read "It is burning" or see a check against "composure" and work out what the
world meant by it, so the same sentence answers `help burning` now.

Which makes these topics unlike any other in one way worth knowing: they are
per world and they grow. Two worlds have different states, a new world has
almost none, and a word enters the help the moment the world first needs it.
So they are built for the caller at the moment they ask, out of the register
belonging to whatever world they are standing in.
"""

from evennia import default_cmds
from evennia.help.filehelp import FileHelpEntry

#: Where these land in `help`'s index. Two categories rather than one, because
#: they answer different questions -- what a thing is like, and what a person
#: is like -- and the index is read by someone looking for one or the other.
STATE_CATEGORY = "Conditions"
TRAIT_CATEGORY = "Traits"

#: Anyone may read them. They document a world the player is standing in.
OPEN = "view:all();read:all()"


def _entry(key, category, text):
    return FileHelpEntry(
        key=key,
        aliases=[],
        help_category=category,
        entrytext=text.strip(),
        lock_storage=OPEN,
    )


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
    from world import traits

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
    lines += ["", "|wscore|n shows everything you are measured by."]
    return "\n".join(lines)


def world_topics(caller, world_root=None):
    """
    The help this world has taught itself, as {key: entry}.

    Empty for anyone standing outside an AI world, which is the right answer:
    these words describe a particular world's rules and mean nothing away
    from it.
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
        topics[str(slug).lower()] = _entry(
            slug, STATE_CATEGORY, _state_text(world_root, slug, entry))
    for slug, entry in (traits.vocabulary(world_root) or {}).items():
        if not slug:
            continue
        # A world that registered a trait and a state under one word is
        # telling us something about people; the state entry is about things.
        # Keep both reachable by keying the trait on its own name.
        key = str(slug).lower()
        if key in topics:
            key = f"{key} (trait)"
        topics[key] = _entry(
            slug, TRAIT_CATEGORY, _trait_text(caller, slug, entry))
    return topics


class CmdAIHelp(default_cmds.CmdHelp):
    """
    Get help on a command, a topic, or a word this world uses.

    Usage:
      help
      help <topic or command>

    As well as the usual commands and topics, this world keeps its own
    vocabulary: the conditions a thing can be in and the figures a person is
    measured by, both of which it invents as it goes. `help empty` and `help
    composure` say what this world means by them.
    """

    def collect_topics(self, caller, mode="list"):
        """
        The usual three sources, with this world's own words folded in.

        They join the file-based entries because that is what they most
        resemble -- text with a key, owned by nobody in the database. Evennia
        lets commands win a name clash and database entries beat file ones, so
        a world that registers a state called "look" cannot bury the command.
        """
        cmd_topics, db_topics, file_topics = super().collect_topics(caller, mode)
        merged = dict(file_topics)
        for key, entry in world_topics(caller).items():
            merged.setdefault(key, entry)
        return cmd_topics, db_topics, merged
