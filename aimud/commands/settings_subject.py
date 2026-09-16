"""
Settings, as a subject of the verbs: `edit settings` and `view settings`.

`settings` is a thing somebody edits or looks over, like a world or a word
list, so it belongs in the menus `edit` and `view` open. The `settings` command
stays as the short way to type `edit settings` -- the same words after it do
the same thing, because both go through `CmdSettings`.
"""

from commands.subjects import Subject, Use, account_of
from world import menus, preferences


def edit_run(cmd, ctx, words):
    """`edit settings ...` is `settings ...`, word for word."""
    from commands.settings_cmds import CmdSettings

    settings = CmdSettings()
    settings.caller = cmd.caller
    settings.session = cmd.session
    settings.args = " ".join(words)
    settings.func()


def view_run(cmd, ctx, words):
    """Every setting with its value, and the name to type to change it."""
    cmd.caller.msg(preferences.listing(ctx))


def _has_account(ctx):
    return account_of(ctx.character or ctx.caller) is not None


SUBJECTS = [
    Subject(
        "settings", ("settings", "setting"),
        uses={
            "edit": Use(edit_run, lambda ctx: [menus.Submenu(
                "settings", "Your settings", preferences.SETTINGS,
                help="Notices, confirmations, your API key and address, "
                     "models, and in a world who you are there.")],
                offered=_has_account),
            "view": Use(view_run, lambda ctx: [menus.Action(
                "settings", "Your settings",
                run=lambda ctx: preferences.listing(ctx), after=menus.CLOSE,
                help="Every setting with what it is set to, and the name to "
                     "type to change it.",
                command=lambda ctx: "view settings")],
                offered=_has_account),
        },
        help="Your preferences, and your world's.",
    ),
]
