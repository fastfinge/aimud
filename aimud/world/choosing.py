"""
Putting a question to somebody, when the game cannot decide for them.

There is exactly one of these today -- "Which her? Jessica or Britney?" -- and
three more are wanted: a rule that offers a menu and gets the answer back,
disambiguation as a proper menu rather than a prompt, and MXP's clickable
lists built from a world's own verbs. They are one mechanism, and the point of
this module existing before any of them do is that the first one should not be
written somewhere a menu cannot later replace.

**What it does now is the least it can do**: it says the question and the
options, and the player answers by typing what they meant. There is no pending
state, nothing is waiting, and a player who types something else entirely has
simply moved on -- which is the right first version, because a
half-implemented "waiting for an answer" state is worse than none.

**What it will do** is run the options through Evennia's `EvMenu`, which is
already how `pronouns new` asks its questions. When that happens, every caller
here changes in one place and none of them has to know.

The contract is deliberately narrow so that both versions can honour it:
`ask` never blocks, never returns an answer, and tells the caller only whether
the question was put at all.
"""


def phrase_options(options):
    """"Jessica or Britney" -- the options as somebody would say them."""
    names = [str(name) for name in options if str(name or "").strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


def question(asked, options):
    """
    The sentence to put. Kept apart from `ask` so a test can read it without
    a character, and so a menu can render the same words a different way.
    """
    listed = phrase_options(options)
    if not listed:
        return f"Which {asked} do you mean?"
    return f"Which {asked} do you mean -- {listed}?"


def ask(caller, asked, options, on_chosen=None):
    """
    Put a choice to somebody. True when it was put, False when there is
    nothing to ask about.

    `on_chosen` is accepted and ignored, and that is not an oversight: it is
    the argument the menu version will need, and taking it now means the
    callers written today are the callers that work afterwards.
    """
    if caller is None or not options:
        return False
    caller.msg(question(asked, options))
    return True
