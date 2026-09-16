"""
Putting a question to somebody, when the game cannot decide for them.

There is exactly one of these today -- "Which her? Jessica or Britney?" -- and
three more are wanted: a rule that offers a menu and gets the answer back,
disambiguation as a proper menu rather than a prompt, and MXP's clickable
lists built from a world's own verbs. They are one mechanism, and the point of
this module existing before any of them do is that the first one should not be
written somewhere a menu cannot later replace.

**Asked with a callback, it is a menu.** `ask` with `on_chosen` puts the
options up through `world.menus`, the same engine every other choice in the
game uses, so `b`, `q`, `?` and the numbers work the way they do everywhere,
and choosing one calls `on_chosen` with it. Without a callback, or with nobody
connected to be shown a menu, it says the question and the options, and the
player answers by typing what they meant -- which is what the two callers
today still want, because they answer by the player typing the command again.

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


def ask(caller, asked, options, on_chosen=None, session=None):
    """
    Put a choice to somebody. True when it was put, False when there is
    nothing to ask about.

    With `on_chosen`, and somebody connected, the options are a menu and
    `on_chosen(option)` is called with the one chosen. Otherwise the question
    is said. Never blocks, and never returns the answer.
    """
    if caller is None or not options:
        return False
    from world import menus

    runner = menus.account_of(caller) or caller
    if on_chosen is None or not menus.interactive(runner):
        caller.msg(question(asked, options))
        return True
    menus.open_menu(caller, choice_form(asked, options, on_chosen),
                    session=session)
    return True


def choice_form(asked, options, on_chosen):
    """The menu `ask` puts up: one entry per option, and choosing ends it."""
    from world import menus

    def entry(number, option):
        name = str(option)
        spoken = name.strip().lower()
        aliases = () if (spoken in menus.RESERVED or spoken.isdigit()) \
            else (spoken,)
        return menus.Action(f"option{number}", name,
                            run=lambda ctx: on_chosen(option),
                            after=menus.CLOSE, aliases=aliases)

    names = [option for option in options if str(option or "").strip()]
    return menus.Form(key="choose", title=f"Which {asked} do you mean?",
                      items=[entry(number, option)
                             for number, option in enumerate(names, 1)])
