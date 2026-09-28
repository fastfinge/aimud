"""
The shared folder: what worlds are in it, and taking one out again.

`export world` and `import world` are uses on the world subject, beside
`create`, `delete` and `reset`, because they are things done to a world.
What is left over is the folder itself -- what is in it, and removing
something you put there -- and that is a subject of its own rather than two
more uses on `world`, because a document in the folder is not one of your
worlds. You have not got it. It is a file somebody could build a world from.

**Nothing here names a path.** A player names a world and never a file:
`exchange.slug` turns a title into a filename and `exchange.read`, `write` and
`remove` join it to a directory from the `WORLD_DIRS` setting. That is the
whole of the path-traversal defence, and it is worth being able to state in
one sentence.

See docs/archived/import-and-export.md 9.
"""

from commands.subjects import Subject, Use, account_of, answered, asking, \
    is_builder, names_for
from world import menus


# Which exports an account wrote is kept in `account.db.exported_worlds`, so
# that `delete export` can tell whose is whose. On the account rather than in
# the file: a shared document should not name anybody, and a name in one would
# be the only thing in the format that meant something on just one server.


def _caller(ctx):
    return ctx.character or ctx.caller


def wrote(account, name):
    """Record that this account wrote this export."""
    if account is None:
        return
    written = list(account.db.exported_worlds or [])
    if name not in written:
        written.append(name)
        account.db.exported_worlds = written


def _may_remove(caller, name):
    """Whether this caller may take `name` out of the folder, and why not."""
    account = account_of(caller)
    if is_builder(caller):
        return True, ""
    if account is not None and name in (account.db.exported_worlds or []):
        return True, ""
    return False, (f"|w{name}|n was not put there by you. Whoever exported it "
                   f"can remove it, and so can a builder.")


# ---------------------------------------------------------------------------
# view exports
# ---------------------------------------------------------------------------

def _line(name, heading):
    rooms = heading["rooms"]
    said = [f"{rooms} room{'s' if rooms != 1 else ''}"]
    if heading["exported"]:
        said.append(f"taken {heading['exported']}")
    if heading["missing"]:
        said.append(f"|rneeds {', '.join(heading['missing'])}, which this "
                    f"server has not got|n")
    return f"{heading['title'] or name} -- {', '.join(said)}"


def listing():
    found = exports()
    if not found:
        return ("The shared folder is empty. |wexport world|n puts one of "
                "yours in it.")
    return (f"{len(found)} world{'s' if len(found) != 1 else ''} anybody here "
            f"can build from. |wimport world <name>|n builds one.")


def exports():
    from world import exchange

    return exchange.available()


def _detail(name, heading):
    lines = [f"|w{heading['title'] or name}|n, {heading['rooms']} room"
             f"{'s' if heading['rooms'] != 1 else ''}."]
    if heading["exported"]:
        lines.append(f"Taken {heading['exported']}.")
    if heading["requires"]:
        lines.append(f"Built with {', '.join(heading['requires'])}.")
    if heading["missing"]:
        lines.append(f"|rThis server has not got "
                     f"{', '.join(heading['missing'])}, so it cannot be "
                     f"built here.|n")
    else:
        lines.append(f"|wimport world {name}|n builds it.")
    return "\n".join(lines)


def _view_entry(name, heading):
    return menus.Action(
        f"export-{name}", _line(name, heading),
        run=lambda ctx: _detail(name, heading),
        aliases=names_for(name, heading["title"]),
        command=lambda ctx: f"view exports {name}")


VIEW_EXPORTS = menus.Form(
    key="exports", title="The shared folder", kind=menus.VIEW,
    intro=lambda ctx: listing(),
    items=lambda ctx: [_view_entry(name, heading)
                       for name, heading in sorted(exports().items())],
    command=lambda ctx: "view exports",
)


def view_run(cmd, ctx, words):
    found = exports()
    if words:
        name = " ".join(words).strip()
        heading = found.get(name) or _by_title(found, name)
        if heading is None:
            cmd.caller.msg(f"There is no world called {name} in the shared "
                           f"folder. |wview exports|n lists what is.")
            return
        cmd.caller.msg(_detail(name, heading))
        return
    menus.open_menu(cmd.caller, VIEW_EXPORTS, session=cmd.session)


def _by_title(found, said):
    """The one whose title is `said`, when the filename was not it."""
    lowered = said.lower()
    matches = [heading for heading in found.values()
               if heading["title"].lower() == lowered]
    return matches[0] if len(matches) == 1 else None


def view_items(ctx):
    return [menus.Submenu("exports", "The shared folder", VIEW_EXPORTS, help=(
        "Worlds anybody here can build from, and what each one needs."))]


# ---------------------------------------------------------------------------
# delete export
# ---------------------------------------------------------------------------

QUESTION = "Take {name} out of the shared folder? Nobody can build it here " \
           "afterwards."


def remove(caller, name):
    from world import exchange

    allowed, refused = _may_remove(caller, name)
    if not allowed:
        return refused
    try:
        gone = exchange.remove(name)
    except exchange.Refused as refusal:
        return f"|r{refusal}|n"
    if not gone:
        return f"There is no world called {name} in the shared folder."
    account = account_of(caller)
    if account is not None:
        written = [made for made in (account.db.exported_worlds or [])
                   if made != name]
        account.db.exported_worlds = written
    return f"|g{name} is no longer in the shared folder.|n"


def _delete_entry(name, heading):
    return menus.Action(
        f"export-{name}", _line(name, heading),
        run=lambda ctx: remove(_caller(ctx), name),
        confirm="delete_export", question=QUESTION.format(name=name),
        after=menus.CLOSE, aliases=names_for(name, heading["title"]),
        command=lambda ctx: f"delete export {name}")


DELETE_EXPORT = menus.Form(
    key="delete-export", title="Remove which exported world?",
    intro=lambda ctx: "" if exports() else "The shared folder is empty.",
    items=lambda ctx: [_delete_entry(name, heading)
                       for name, heading in sorted(exports().items())],
    command=lambda ctx: "delete export",
)


def delete_run(cmd, ctx, words):
    words, yes = answered(words)
    if not words:
        menus.open_menu(cmd.caller, DELETE_EXPORT, session=cmd.session)
        return
    name = " ".join(words).strip()
    asking(cmd, QUESTION.format(name=name), "delete_export",
           f"delete export {name}",
           lambda: cmd.caller.msg(remove(cmd.caller, name)), already=yes)


def delete_items(ctx):
    return [menus.Submenu("export", "A world in the shared folder",
                          DELETE_EXPORT, help=(
                              "Take an exported world out of the folder. "
                              "Whoever put it there, or a builder."))]


SUBJECTS = [
    Subject(
        "export", ("export", "exports", "folder"),
        uses={
            "view": Use(view_run, view_items),
            "delete": Use(delete_run, delete_items),
        },
        help="Worlds in the shared folder, which anybody here can build from.",
    ),
]
