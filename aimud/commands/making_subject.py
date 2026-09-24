"""
Every maker, as a subject of `create`, `edit`, `delete` and `view`.

Nothing here knows what a kind or a rule is. It walks `world/making.py` and
turns each entry into the `Subject` that `commands/subjects.py` already knows
how to offer -- the command line, the entry in a bare `create`'s menu, and the
permission check, once, for all of them.

  create <thing>                     the form
  create <thing> <name>              the form, opened past its first question
  view <thing>                       what this world holds
  view <thing> <id>                  one of them
  edit <thing> [<id>]                change one
  delete <thing> <id> [yes]          remove one, asking first

Reading is open to anybody standing in a world -- the open sandbox -- and
changing is for whoever made it, which is `owns_here` and not a new rule.
"""

from commands.subjects import (Subject, Use, answered, asking, in_world,
                               names_for, owns_here, require_owner,
                               require_world)
from world import making, menus


def _caller(ctx):
    return ctx.character or ctx.caller


def _root(ctx):
    return making.root_of(ctx)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def listing_text(maker, root):
    """What a world holds of one sort, as lines."""
    entries = maker.entries(root)
    if not entries:
        return (f"This world has no {maker.key} yet. "
                f"|wcreate {maker.key}|n makes one.")
    lines = [f"|w{maker.label}|n", ""]
    for value, label, helped in entries:
        lines.append(f"  |w{value}|n -- {label}")
        if helped:
            lines.append(f"      |x{helped}|n")
    return "\n".join(lines)


def one_text(maker, root, ident):
    if maker.one is None:
        return listing_text(maker, root)
    said = maker.one(root, ident)
    return said or f"This world holds no {maker.key} called |w{ident}|n."


def _view_form(maker):
    return menus.Form(
        key=f"view-{maker.key}", title=maker.label, kind=menus.VIEW,
        intro=lambda ctx: listing_text(maker, _root(ctx)),
        items=lambda ctx: maker.extra_items(ctx) + [
            menus.Action(f"at{number}", label,
                         run=lambda ctx, value=value: one_text(
                             maker, _root(ctx), value),
                         aliases=names_for(value),
                         command=lambda ctx, value=value:
                             f"view {maker.key} {value}")
            for number, (value, label, _help)
            in enumerate(maker.entries(_root(ctx)), 1)],
        choices_line="For one of them:",
    )


def _view_run(maker):
    def run(cmd, ctx, words):
        caller = cmd.caller
        root = require_world(caller)
        if root is None:
            return
        if words:
            caller.msg(one_text(maker, root, " ".join(words)))
            return
        menus.open_menu(caller, _view_form(maker), session=cmd.session)

    return run


# ---------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------

def _create_run(maker):
    def run(cmd, ctx, words):
        caller = cmd.caller
        root = require_world(caller)
        if root is None or not _may_change(maker, caller, root,
                                           f"add {maker.key} to it"):
            return
        draft = maker.opening_draft(" ".join(words)) if words else {}
        if words and not draft:
            caller.msg(f"|w{maker.key}|n takes nothing on the line; the menu "
                       f"asks for what it needs.")
        if draft and _kept_outright(maker, cmd, root, draft):
            return
        if draft and _said_what_is_missing(maker, cmd, root, draft):
            return
        # Opened through `create`'s own menu rather than straight at the form,
        # so that `b` backs out to what else can be made here. That is what
        # `create tokens` and `create pronouns` have always done, and the
        # difference is only visible from inside: a form opened on its own has
        # nothing behind it to go back to.
        from commands.subjects import verb_form

        menus.open_menu(caller, verb_form("create"), session=cmd.session,
                        path=[maker.key], world_root=root, opening=draft)

    return run


def _kept_outright(maker, cmd, root, draft):
    """
    A line that gave everything is kept there and then. True when it was.

    The rule every command in this game keeps, said once here for every maker
    instead of once per maker: leave the arguments out and you get a menu,
    give part of them and the menu opens at that point, give all of them and
    there is no menu (docs/commands-and-settings.md §4). `create tokens smell
    = brine | tar` is the line that has always done this, and the port is
    what made it everybody's.
    """
    form = maker.new
    ctx = menus.Context(cmd.caller, session=cmd.session, draft=dict(draft),
                        world_root=root)
    if form.unset_required(ctx) is not None:
        return False
    finishing = making.finisher(form, ctx)
    if finishing is None:
        return False
    try:
        answered = finishing.run(ctx)
    except menus.Refuse as refusal:
        cmd.caller.msg(str(refusal))
        return True
    cmd.caller.msg(getattr(answered, "said", None) or str(answered or ""))
    return True


def _said_what_is_missing(maker, cmd, root, draft):
    """
    For somebody with no menu: what the line still needs. True when it was said.

    A half-finished line is the one case where the general answer is worse
    than the old particular one. `open_menu` tells a caller with no session
    what the *menu* offers, which for a partial line is the whole `create`
    list over again and not the two words that are missing. An agent, a batch
    file or a player who turned menus off is owed the answer they asked for.
    """
    ctx = menus.Context(cmd.caller, session=cmd.session, draft=dict(draft),
                        world_root=root)
    runner = ctx.account or cmd.caller
    if menus.interactive(runner):
        return False
    wanted = [item for item in maker.new.items_for(ctx)
              if isinstance(item, menus.Field) and item.required
              and not item.is_set(ctx)]
    if not wanted:
        return False
    finishing = making.finisher(maker.new, ctx)
    typed = finishing.command_for(ctx) if finishing is not None else ""
    said = ", ".join(item.label_for(ctx).lower() for item in wanted)
    cmd.caller.msg(f"That {maker.key} still needs its {said}."
                   + (f" Type |w{typed}|n." if typed else ""))
    return True


def _create_items(maker):
    return lambda ctx: [menus.Submenu(
        maker.key, maker.make_label, maker.new, fresh_draft=True,
        # What was typed on the line, handed down into the fresh draft. A
        # submenu with a draft of its own would otherwise drop it.
        draft=lambda ctx: dict((ctx.data or {}).get("opening") or {}),
        data=lambda ctx: {"world_root": _root(ctx)},
        help=maker.help, aliases=maker.words[1:],
        command=lambda ctx: f"create {maker.key}")]


# ---------------------------------------------------------------------------
# Changing one
# ---------------------------------------------------------------------------

def _edit_form(maker, root, ident):
    form = maker.edit(root, ident)
    return form


def _choose_form(maker, verb, title, then):
    """A menu of what this world holds, for `edit` or `delete` with no id."""
    return menus.Form(
        key=f"{verb}-{maker.key}", title=title,
        intro=lambda ctx: "" if maker.entries(_root(ctx))
        else f"This world has no {maker.key}.",
        items=lambda ctx: [
            then(ctx, value, label)
            for value, label, _help in maker.entries(_root(ctx))],
    )


def _edit_items(maker):
    def one(ctx, value, label):
        root = _root(ctx)
        return menus.Submenu(
            f"at-{value}".lower(), label, maker.edit(root, value),
            aliases=names_for(value),
            command=lambda ctx: f"edit {maker.key} {value}")

    return one


def _reached_form(maker, verb, title, then):
    """A menu of what is in front of you, for a maker of objects."""
    return menus.Form(
        key=f"{verb}-{maker.key}-here", title=title,
        intro=lambda ctx: "" if maker.targets(_caller(ctx))
        else f"There is no {maker.key} here.",
        items=lambda ctx: [then(ctx, ident, label)
                           for ident, label in maker.targets(_caller(ctx))],
    )


def _reached_edit_items(maker):
    def one(ctx, ident, label):
        return menus.Submenu(
            f"at-{ident}", label, maker.edit(_root(ctx), ident),
            data=lambda ctx, ident=ident: {
                "target": _found(_caller(ctx), maker, ident)},
            command=lambda ctx: f"edit {maker.key} {label}")

    return one


def _found(caller, maker, ident):
    for obj in (maker.reached(caller) if maker.reached else []):
        if str(obj.id) == str(ident):
            return obj
    return None


def _edit_run(maker):
    def run(cmd, ctx, words):
        caller = cmd.caller
        root = require_world(caller)
        if root is None or not _may_change(
                maker, caller, root, f"change its {maker.key}"):
            return
        if maker.sole:
            menus.open_menu(caller, maker.edit(root, None),
                            session=cmd.session, world_root=root)
            return
        if maker.reached is not None:
            return _edit_reached(maker, cmd, root, words)
        if not words:
            menus.open_menu(
                caller,
                _choose_form(maker, "edit", f"Change which {maker.key}?",
                             _edit_items(maker)),
                session=cmd.session, world_root=root)
            return
        ident = " ".join(words)
        form = maker.edit(root, ident)
        if form is None:
            caller.msg(f"This world holds no {maker.key} called "
                       f"|w{ident}|n.")
            return
        menus.open_menu(caller, form, session=cmd.session, world_root=root)

    return run


def _edit_reached(maker, cmd, root, words):
    """
    `edit item lamp` means the lamp in front of you, or asks which.

    Never a search of the world: see docs/player-building.md 5. With nothing
    named, everything in reach is offered, which is the same list a player
    would get by looking.
    """
    caller = cmd.caller
    if not words:
        menus.open_menu(
            caller,
            _reached_form(maker, "edit", f"Change which {maker.key}?",
                          _reached_edit_items(maker)),
            session=cmd.session, world_root=root)
        return
    found, complaint = maker.find(caller, " ".join(words))
    if found is None:
        caller.msg(complaint or f"Which {maker.key}?")
        return
    menus.open_menu(caller, maker.edit(root, str(found.id)),
                    session=cmd.session, world_root=root, target=found)


# ---------------------------------------------------------------------------
# Removing one
# ---------------------------------------------------------------------------

def _delete_question(maker, root, ident):
    if maker.delete_question is not None:
        return maker.delete_question(root, ident)
    return f"Delete the {maker.key} {ident}?"


def _delete_items(maker):
    def one(ctx, value, label):
        return menus.Action(
            f"at-{value}".lower(), label,
            run=lambda ctx, value=value: maker.remove(_root(ctx), value),
            confirm=f"delete_{maker.key}",
            question=_delete_question(maker, _root(ctx), value),
            after=menus.STAY, aliases=names_for(value),
            command=lambda ctx: f"delete {maker.key} {value}")

    return one


def _reached_delete_items(maker):
    def one(ctx, ident, label):
        return menus.Action(
            f"at-{ident}", label,
            run=lambda ctx, ident=ident: maker.remove(_root(ctx), ident),
            confirm=f"delete_{maker.key}",
            question=_delete_question(maker, _root(ctx), label), after=menus.STAY,
            command=lambda ctx: f"delete {maker.key} {label}")

    return one


def _delete_run(maker):
    def run(cmd, ctx, words):
        caller = cmd.caller
        root = require_world(caller)
        if root is None or not _may_change(
                maker, caller, root, f"change its {maker.key}"):
            return
        words, yes = answered(words)
        if maker.reached is not None:
            return _delete_reached(maker, cmd, root, words, yes)
        if not words:
            menus.open_menu(
                caller,
                _choose_form(maker, "delete", f"Delete which {maker.key}?",
                             _delete_items(maker)),
                session=cmd.session, world_root=root)
            return
        ident = " ".join(words)
        asking(cmd, _delete_question(maker, root, ident), f"delete_{maker.key}",
               f"delete {maker.key} {ident}",
               lambda: caller.msg(maker.remove(root, ident)), already=yes)

    return run


def _delete_reached(maker, cmd, root, words, yes):
    caller = cmd.caller
    if not words:
        menus.open_menu(
            caller,
            _reached_form(maker, "delete", f"Delete which {maker.key}?",
                          _reached_delete_items(maker)),
            session=cmd.session, world_root=root)
        return
    said = " ".join(words)
    found, complaint = maker.find(caller, said)
    if found is None:
        caller.msg(complaint or f"Which {maker.key}?")
        return
    ident, label = str(found.id), found.key
    asking(cmd, _delete_question(maker, root, label), f"delete_{maker.key}",
           f"delete {maker.key} {said}",
           lambda: caller.msg(maker.remove(root, ident)), already=yes)


# ---------------------------------------------------------------------------
# The subjects
# ---------------------------------------------------------------------------

def _reset_question(maker, root, ident):
    if maker.reset_question is not None:
        return maker.reset_question(root, ident)
    return f"Forget what this world settled about the {maker.key} {ident}?"


def _reset_items(maker):
    def one(ctx, value, label):
        root = _root(ctx)
        return menus.Action(
            f"at-{value}".lower(), label,
            run=lambda ctx, value=value: maker.reset(_root(ctx), value),
            confirm=f"reset_{maker.key}",
            question=_reset_question(maker, root, value), after=menus.STAY,
            aliases=names_for(value),
            command=lambda ctx: f"reset {maker.key} {value}")

    return one


def _reset_run(maker):
    def run(cmd, ctx, words):
        caller = cmd.caller
        root = require_world(caller)
        if root is None or not _may_change(
                maker, caller, root, f"change its {maker.key}"):
            return
        words, yes = answered(words)
        if not words:
            menus.open_menu(
                caller,
                _choose_form(maker, "reset", f"Forget which {maker.key}?",
                             _reset_items(maker)),
                session=cmd.session, world_root=root)
            return
        ident = " ".join(words)
        asking(cmd, _reset_question(maker, root, ident),
               f"reset_{maker.key}", f"reset {maker.key} {ident}",
               lambda: caller.msg(maker.reset(root, ident)), already=yes)

    return run


def _edit_menu(maker, ctx):
    if maker.sole:
        return maker.edit(_root(ctx), None)
    if maker.reached is not None:
        return _reached_form(maker, "edit", f"Change which {maker.key}?",
                             _reached_edit_items(maker))
    return _choose_form(maker, "edit", f"Change which {maker.key}?",
                        _edit_items(maker))


def _delete_menu(maker):
    if maker.reached is not None:
        return _reached_form(maker, "delete", f"Delete which {maker.key}?",
                             _reached_delete_items(maker))
    return _choose_form(maker, "delete", f"Delete which {maker.key}?",
                        _delete_items(maker))


def _may_change(maker, caller, root, what):
    """
    Whether this caller may build with this maker, telling them if not.

    Almost always "whoever made the world", which is what everything the
    world is built out of needs. A pronoun set is the exception and says so
    on the maker: it is a fact about the person choosing it, and refusing one
    to a guest would be the world deciding how they are spoken about.
    """
    if not maker.owner:
        return True
    return require_owner(caller, root, what)


def _offered(maker, owner):
    def offered(ctx):
        if not maker.is_offered(ctx):
            return False
        return owns_here(ctx) if (owner and maker.owner) else in_world(ctx)

    return offered


def build():
    """One `Subject` per maker, with the verbs it answers."""
    found = []
    for maker in making.registered():
        uses = {}
        if maker.answers("view"):
            uses["view"] = Use(
                _view_run(maker),
                lambda ctx, maker=maker: [menus.Submenu(
                    maker.key, maker.label, _view_form(maker),
                    help=f"What this world holds: {maker.label.lower()}.",
                    command=lambda ctx: f"view {maker.key}")],
                offered=_offered(maker, owner=False))
        if maker.answers("create"):
            uses["create"] = Use(_create_run(maker), _create_items(maker),
                                 offered=_offered(maker, owner=True))
        if maker.answers("edit"):
            uses["edit"] = Use(
                _edit_run(maker),
                lambda ctx, maker=maker: [menus.Submenu(
                    maker.key, maker.label, _edit_menu(maker, ctx),
                    help=f"Change {maker.label.lower()}.",
                    command=lambda ctx: f"edit {maker.key}")],
                offered=_offered(maker, owner=True))
        if maker.answers("delete"):
            uses["delete"] = Use(
                _delete_run(maker),
                lambda ctx, maker=maker: [menus.Submenu(
                    maker.key, maker.label, _delete_menu(maker),
                    help=f"Remove {maker.label.lower()}.",
                    command=lambda ctx: f"delete {maker.key}")],
                offered=_offered(maker, owner=True))
        if maker.answers("reset"):
            uses["reset"] = Use(
                _reset_run(maker),
                lambda ctx, maker=maker: [menus.Submenu(
                    maker.key, maker.label,
                    _choose_form(maker, "reset",
                                 f"Forget which {maker.key}?",
                                 _reset_items(maker)),
                    help=f"Forget what this world settled about "
                         f"{maker.label.lower()}, so it is decided afresh.",
                    command=lambda ctx: f"reset {maker.key}")],
                offered=_offered(maker, owner=True))
        if not uses:
            continue
        found.append(Subject(maker.key, maker.words, uses=uses,
                             help=maker.help))
    return found


SUBJECTS = build()
