"""
`view term <word>`: everything the two dictionaries know about a word.

  view term                    asks which
  view term chest              its senses, what each is a sort of, and more

The reading half of "can players create terms", and the half that turns out to
be most of the answer. Grounding an invented word is already a field on every
register -- a kind's sense and its anchor, an action's sense -- and what was
missing was any way for somebody building by hand to *see* what they were
grounding against. A sense picker offering `chest.n.01` and `chest.n.02` is no
help to a person who cannot find out that one is a ribcage.

Both corpora, side by side, and labelled, because they answer different
questions and only one of them is safe to act on. WordNet says what a word CAN
be -- closed, published, and what this game's kinds are made of. ConceptNet
says what people THINK is true of it, which is an oracle and a prior: its nodes
are words rather than senses, so nothing here may ever ground anything. See
world/lexicon.py and world/commonsense.py, which both say so at length.

Free, and free of the network: WordNet is vendored and ConceptNet is on disk or
absent. A word neither has heard of is a perfectly good answer -- it is what an
invented word looks like, and it is the moment to reach for an anchor.
"""

from commands.subjects import Subject, Use
from world import lexicon, menus

#: How many of anything to print. A common noun has dozens of relatives and
#: nobody reads past the first handful.
MOST = 8


def _caller(ctx):
    return ctx.character or ctx.caller


def _root(ctx):
    room = getattr(_caller(ctx), "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


def term_report(caller, word, world_root=None):
    """Everything both dictionaries know about one word."""
    word = " ".join(str(word or "").split()).strip().lower()
    if not word:
        return "Which word? |wview term chest|n."

    lines = [f"|w{word}|n"]
    head = lexicon.head_noun(word) or word
    if head != word:
        lines.append(f"|xread as a {head}|n")

    senses = lexicon.senses(head, pos="n", limit=MOST)
    verbs = lexicon.senses(head, pos="v", limit=MOST)
    if senses:
        lines += ["", "|yAs a noun, it can mean:|n"]
        for name, gloss in senses:
            lines.append(f"  |w{name}|n -- {gloss}")
            above = [step for step in lexicon.ancestors(name) if step != name]
            if above:
                lines.append(f"      |xa sort of {', '.join(sorted(above)[:4])}|n")
    if verbs:
        lines += ["", "|yAs a verb, it can mean:|n"]
        for name, gloss in verbs:
            lines.append(f"  |w{name}|n -- {gloss}")
    if not senses and not verbs:
        lines += ["", "|yThe dictionary has never heard of it.|n",
                  "|xWhich is not a problem -- it is what an invented word "
                  "looks like. A kind made of it is asked what real sort of "
                  "thing it hangs beneath, and everything else follows from "
                  "that.|n"]

    lines += _commonsense_block(word)
    lines += _here_block(word, world_root)
    return "\n".join(lines)


def _commonsense_block(word):
    """What people think is true of it. A prior, never a ground."""
    from world import commonsense

    # Four of ConceptNet's relations are definitionally four things this game
    # had to invent for itself, and they are asked for by the names the
    # module already wraps them under.
    asked = (
        ("what can be done to it", commonsense.can_be_done_to),
        ("sorts of it", commonsense.kinds_of),
        ("parts of it", commonsense.parts_of),
        ("what it is not", commonsense.opposites),
        ("ways of doing it", commonsense.ways_to),
    )
    found = []
    for said, ask in asked:
        try:
            answers = list(ask(word, limit=MOST) or [])
        except Exception:
            answers = []
        if answers:
            found.append(f"  {said}: "
                         f"{', '.join(str(a) for a in answers[:MOST])}")
    if not found:
        return []
    return (["", "|yWhat people say about it:|n"] + found
            + ["|xThat second dictionary knows words rather than meanings, so "
               "it is a hint and never a fact. Nothing here grounds anything: "
               "the sense above does that.|n"])


def _here_block(word, world_root):
    """And what this world has already done with it."""
    if world_root is None:
        return []
    from world import actions, folds, kinds, traits, verbs

    found = []
    settled = kinds.canonical(word)
    if kinds.spec(world_root, settled) is not None:
        found.append(f"  a sort of thing here: |w{settled}|n "
                     f"(|wview kind {settled}|n)")
    for name in kinds.vocabulary(world_root):
        if name != settled and lexicon.head_noun(name) == word:
            found.append(f"  and |w{name}|n (|wview kind {name}|n)")
    if word in actions.vocabulary(world_root):
        found.append(f"  a verb here (|wview action {word}|n)")
    if word in (verbs.vocabulary(world_root) or {}):
        found.append(f"  a condition here (|wview condition {word}|n)")
    if word in (traits.vocabulary(world_root) or {}):
        found.append(f"  an attribute here (|wview attribute {word}|n)")
    means = folds.all_folds(world_root).get(word)
    if means:
        found.append(f"  another word for |w{means}|n here")
    if not found:
        return ["", "|yThis world has not used it for anything yet.|n"]
    return ["", "|yIn this world:|n"] + found


ASK_TERM = menus.Form(
    key="term", title="Look a word up",
    intro="Everything both dictionaries know about a word: what it can mean, "
          "what each meaning is a sort of, and what people think is true of "
          "it. Costs nothing.",
    items=[menus.Field(
        "word", "The word",
        get=lambda ctx: None,
        set=lambda ctx, value: term_report(_caller(ctx), value or "",
                                           _root(ctx)),
        prompt="Type a word to look up",
        help="Any word at all. One the dictionary has never heard of is a "
             "good answer too -- it is what an invented word looks like.")],
)


def view_term_run(cmd, ctx, words):
    caller = cmd.caller
    room = getattr(caller, "location", None)
    root = getattr(room.db, "world_root", None) if room is not None else None
    if words:
        caller.msg(term_report(caller, " ".join(words), root))
        return
    menus.open_menu(caller, ASK_TERM, session=cmd.session)


SUBJECTS = [
    Subject(
        "term", ("term", "terms", "word-meaning", "define"),
        uses={"view": Use(
            view_term_run,
            lambda ctx: [menus.Submenu(
                "term", "Look a word up", ASK_TERM,
                help="What both dictionaries know about a word. Useful while "
                     "building: a sense picker is no help to somebody who "
                     "cannot find out which sense is which.",
                command=lambda ctx: "view term <word>")])},
        help="What English and common sense already know about a word.",
    ),
]
