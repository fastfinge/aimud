"""
Your score, as a subject of the verbs: `view score`.

`score` is a thing somebody reads, so it belongs in the menu `view` opens
beside this world's rules and what its verbs do. The `score` command stays as
the short way to type it -- `score light` and `view score light` are the same
words in the same order, because both come here.
"""

from commands.subjects import Subject, Use
from world import menus


def view_run(cmd, ctx, words):
    """One trait if a name was given, otherwise the whole score."""
    from commands.trait_cmds import SCORE, score

    if words:
        cmd.caller.msg(score(cmd.caller, " ".join(words).lower()))
        return
    menus.open_menu(cmd.caller, SCORE, session=cmd.session)


def view_items(ctx):
    from commands.trait_cmds import SCORE

    return [menus.Submenu(
        "score", "Your score", SCORE,
        help="Every trait you have, what it stands at, and what this world "
             "calls standing there.")]


SUBJECTS = [
    Subject(
        "score", ("score", "traits", "sheet"),
        uses={"view": Use(view_run, view_items)},
        help="What is measurably true of you, trait by trait.",
    ),
]
