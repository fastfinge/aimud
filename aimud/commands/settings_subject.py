"""
Settings, as a subject of the verbs: `edit settings` and `view settings`.

`settings` is a thing somebody edits or looks over, like a world or a word
list, so it belongs in the menus `edit` and `view` open. The `settings` command
stays as the short way to type `edit settings` -- the same words after it do
the same thing, because both go through `CmdSettings`.

  edit settings [<name> [<value>]]   change one, or open the groups
  view settings [<name>]             read one, or read them all

Reading takes a name the same way changing does, so `view settings mode` is
one setting the way `view effects break` is one verb. It never offers to
change anything: somebody who wants that types `settings mode`, which the
answer tells them.
"""

from commands.subjects import Subject, Use, account_of, names_for
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
    """One setting if a name was given, otherwise the menu of all of them."""
    if words:
        cmd.caller.msg(one_setting(ctx, " ".join(words)))
        return
    menus.open_menu(cmd.caller, VIEW_SETTINGS, session=cmd.session)


# ---------------------------------------------------------------------------
# Reading one
# ---------------------------------------------------------------------------

def _fields(ctx):
    """
    (field, its context) for every setting `ctx` can see, as `list` shows them.

    Flat, because the name that reaches a setting is flat: `settings mode`
    works without naming the group it is in, and so should `view settings
    mode`. A job's own settings are left out for the same reason they are left
    out of `settings <name>` -- they need a job to belong to, and are reached
    through `view settings models`.
    """
    found = []
    for group in preferences.SETTINGS.items_for(ctx):
        child = group.context(ctx)
        for item in group.form.items_for(child):
            if isinstance(item, menus.Field):
                found.append((item, child))
    return found


def _group_named(ctx, word):
    """The settings group `word` names, and its context, or (None, None)."""
    for group in preferences.SETTINGS.items_for(ctx):
        if word in group.names():
            return group, group.context(ctx)
    return None, None


def one_setting(ctx, wanted):
    """What `view settings <name>` says: one setting, or one group of them."""
    word = " ".join(str(wanted or "").split()).lower()

    for field, child in _fields(ctx):
        if word in field.names():
            return _one_field(field, child)

    group, child = _group_named(ctx, word)
    if group is not None:
        return _one_group(group, child)

    return (f"There is no setting called |w{word}|n. |wview settings|n shows "
            f"them all.")


def _one_field(field, ctx):
    lines = [f"|w{field.label_for(ctx)}|n: {field.shown(ctx)}"]
    helped = field.help_for(ctx)
    if helped:
        lines.append(helped)
    lines.append(f"Type |wsettings {field.key} <value>|n to change it.")
    return "\n".join(lines)


def _one_group(group, ctx):
    lines = [f"|w{group.label_for(ctx)}|n"]
    about = group.help_for(ctx)
    if about:
        lines.append(about)
    lines.append("")
    for item in group.form.items_for(ctx):
        if isinstance(item, menus.Field):
            lines.append(f"  {item.label_for(ctx)}: {item.shown(ctx)}"
                         f"  |x(settings {item.key})|n")
        elif isinstance(item, menus.Submenu):
            lines.append(f"  {item.label_for(ctx)}"
                         f"  |x(settings {item.key})|n")
    return "\n".join(lines)


VIEW_SETTINGS = menus.Form(
    key="settings", title="Your settings", kind=menus.VIEW,
    intro=lambda ctx: preferences.listing(ctx),
    items=lambda ctx: [
        menus.Action(f"setting-{field.key}", field.label_for(child),
                     run=lambda ctx, key=field.key: one_setting(ctx, key),
                     aliases=names_for(field.key), topic=field.key,
                     command=lambda ctx, key=field.key: f"view settings {key}")
        for field, child in _fields(ctx)],
    choices_line="One of them:",
    command=lambda ctx: "view settings",
)


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
            "view": Use(view_run, lambda ctx: [menus.Submenu(
                "settings", "Your settings", VIEW_SETTINGS,
                help="Every setting with what it is set to, and the name to "
                     "type to change it.")],
                offered=_has_account),
        },
        help="Your preferences, and your world's.",
    ),
]
